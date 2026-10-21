"""The core loop: monitor -> posts -> engagers -> leads -> ICP fit -> intent -> enrich -> route."""

import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

from .db import Database, now_iso
from .destinations import lead_payload, post_json, slack_payload
from .enrichment import Enricher
from .icp import icp_fit, infer_seniority
from .providers import LinkedInProvider, Post
from .scoring import Scorer

log = logging.getLogger(__name__)

SIGNALS_SQL = """
SELECT s.*, p.text AS post_text, p.url AS post_url, p.author_name, p.posted_at,
       m.name AS monitor_name, m.kind AS monitor_kind, m.is_competitor
FROM signals s
JOIN posts p ON p.id = s.post_id
JOIN monitors m ON m.id = s.monitor_id
WHERE s.lead_id = ?
ORDER BY s.created_at DESC
"""


def _split(csv: str) -> list[str]:
    return [x.strip() for x in csv.split(",") if x.strip()]


class Pipeline:
    def __init__(self, db: Database, provider: LinkedInProvider, enricher: Enricher, scorer: Scorer,
                 http: httpx.Client | None = None, max_workers: int = 4):
        self.db = db
        self.provider = provider
        self.enricher = enricher
        self.scorer = scorer
        self.http = http or httpx.Client(timeout=15)
        self.max_workers = max_workers

    # --- fetching -----------------------------------------------------------
    def _fetch_posts(self, monitor: dict) -> list[Post]:
        if monitor["kind"] == "keyword":
            posts = self.provider.search_posts(_split(monitor["query"]))
        else:
            posts = self.provider.profile_posts(monitor["query"].strip())
        excludes = [e.lower() for e in _split(monitor.get("exclude_keywords") or "")]
        return [p for p in posts if not any(e in p.text.lower() for e in excludes)]

    def _upsert_post(self, monitor_id: int, post: Post) -> int:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO posts (monitor_id, external_id, url, author_name, author_headline,
                       author_url, text, posted_at, reaction_count, comment_count, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(monitor_id, external_id) DO UPDATE SET
                       reaction_count = excluded.reaction_count,
                       comment_count = excluded.comment_count,
                       fetched_at = excluded.fetched_at""",
                (monitor_id, post.external_id, post.url, post.author_name, post.author_headline,
                 post.author_url, post.text, post.posted_at, post.reaction_count,
                 post.comment_count, now_iso()),
            )
            return conn.execute("SELECT id FROM posts WHERE monitor_id = ? AND external_id = ?",
                                (monitor_id, post.external_id)).fetchone()["id"]

    def _upsert_lead(self, person) -> tuple[int, bool]:
        existing = self.db.one("SELECT id FROM leads WHERE profile_url = ?", (person.profile_url,))
        ts = now_iso()
        if existing:
            self.db.execute("UPDATE leads SET last_seen = ? WHERE id = ?", (ts, existing["id"]))
            return existing["id"], False
        lead_id = self.db.execute(
            """INSERT INTO leads (profile_url, name, headline, title, company, company_domain,
                   company_size, industry, location, seniority, first_seen, last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (person.profile_url, person.name, person.headline, person.title, person.company,
             person.company_domain, person.company_size, person.industry, person.location,
             infer_seniority(person.title or person.headline), ts, ts),
        )
        return lead_id, True

    # --- per-lead processing ----------------------------------------------
    def signals_for(self, lead_id: int) -> list[dict]:
        return self.db.query(SIGNALS_SQL, (lead_id,))

    def evaluate_lead(self, lead_id: int, route: bool = True) -> dict:
        lead = self.db.one("SELECT * FROM leads WHERE id = ?", (lead_id,))
        icp = self.db.get_setting("icp")
        offer = self.db.get_setting("offer")
        routing = self.db.get_setting("routing")
        signals = self.signals_for(lead_id)

        fit, _ = icp_fit(lead, icp)
        updates: dict = {"icp_fit": fit}
        if fit > 0:
            assessment, scored_by = self.scorer.score(lead, signals, offer)
            updates.update(intent_score=assessment.intent_score, sentiment=assessment.sentiment,
                           buying_stage=assessment.buying_stage, intent_reason=assessment.reason,
                           suggested_opener=assessment.suggested_opener, scored_by=scored_by)
        else:
            updates.update(intent_score=0, intent_reason="Outside ICP", scored_by="icp")

        qualified = fit >= routing["min_icp_fit"] and updates["intent_score"] >= routing["min_intent"]
        if lead["status"] in ("new", "qualified", "disqualified"):
            updates["status"] = "qualified" if qualified else ("disqualified" if fit == 0 else "new")
        if qualified and not lead["email"]:
            updates.update(self.enricher.enrich(lead))

        sets = ", ".join(f"{k} = ?" for k in updates)
        self.db.execute(f"UPDATE leads SET {sets} WHERE id = ?", (*updates.values(), lead_id))
        lead = self.db.one("SELECT * FROM leads WHERE id = ?", (lead_id,))
        if qualified and route:
            self.route(lead, signals, routing)
        return lead

    def route(self, lead: dict, signals: list[dict], routing: dict) -> list[dict]:
        results = []
        targets = [("webhook", routing.get("webhook_url"), lead_payload),
                   ("slack", routing.get("slack_webhook_url"), slack_payload)]
        for name, url, build in targets:
            if not url:
                continue
            if self.db.one("SELECT 1 FROM deliveries WHERE lead_id = ? AND destination = ? AND ok = 1",
                           (lead["id"], name)):
                continue  # each lead is delivered once per destination
            ok, detail = post_json(url, build(lead, signals), self.http)
            self.db.execute(
                """INSERT INTO deliveries (lead_id, destination, ok, detail, created_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(lead_id, destination) DO UPDATE SET
                       ok = excluded.ok, detail = excluded.detail, created_at = excluded.created_at""",
                (lead["id"], name, int(ok), detail, now_iso()))
            results.append({"destination": name, "ok": ok, "detail": detail})
        return results

    # --- monitor run ----------------------------------------------------------
    def run_monitor(self, monitor_id: int) -> dict:
        monitor = self.db.one("SELECT * FROM monitors WHERE id = ?", (monitor_id,))
        if monitor is None:
            raise KeyError(monitor_id)
        run_id = self.db.execute("INSERT INTO runs (monitor_id, started_at) VALUES (?, ?)",
                                 (monitor_id, now_iso()))
        stats = {"posts_found": 0, "signals_found": 0, "new_leads": 0, "error": ""}
        touched: set[int] = set()
        try:
            posts = self._fetch_posts(monitor)
            stats["posts_found"] = len(posts)
            for post in posts:
                post_id = self._upsert_post(monitor_id, post)
                engagements = post.engagements or self.provider.engagements(post)
                for eng in engagements:
                    if not eng.person.profile_url or eng.person.profile_url == post.author_url:
                        continue
                    lead_id, created = self._upsert_lead(eng.person)
                    stats["new_leads"] += int(created)
                    with self.db.connect() as conn:
                        cur = conn.execute(
                            """INSERT OR IGNORE INTO signals
                                   (lead_id, post_id, monitor_id, kind, reaction_type, comment_text, created_at)
                               VALUES (?,?,?,?,?,?,?)""",
                            (lead_id, post_id, monitor_id, eng.kind, eng.reaction_type,
                             eng.comment_text, post.posted_at or now_iso()))
                    if cur.rowcount:
                        stats["signals_found"] += 1
                        touched.add(lead_id)
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                list(pool.map(self.evaluate_lead, touched))
        except Exception as exc:
            log.exception("Monitor %s failed", monitor_id)
            stats["error"] = str(exc)
        self.db.execute(
            """UPDATE runs SET finished_at = ?, posts_found = ?, signals_found = ?,
                   new_leads = ?, error = ? WHERE id = ?""",
            (now_iso(), stats["posts_found"], stats["signals_found"], stats["new_leads"],
             stats["error"], run_id))
        self.db.execute("UPDATE monitors SET last_run_at = ? WHERE id = ?", (now_iso(), monitor_id))
        return {"monitor_id": monitor_id, **stats}

    def run_all(self) -> list[dict]:
        return [self.run_monitor(m["id"])
                for m in self.db.query("SELECT id FROM monitors WHERE active = 1")]
