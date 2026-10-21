"""FastAPI app: REST API + static dashboard + background scheduler."""

import asyncio
import csv
import io
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings, load_settings
from .db import Database, now_iso
from .destinations import LEAD_FIELDS, post_json
from .enrichment import get_enricher
from .pipeline import Pipeline
from .providers import get_provider
from .scoring import Scorer

log = logging.getLogger("signal_radar")
STATIC = Path(__file__).resolve().parent.parent / "static"


class MonitorIn(BaseModel):
    name: str = Field(min_length=1)
    kind: Literal["keyword", "profile", "company"]
    query: str = Field(min_length=1, description="Comma-separated keywords, or a profile/company URL")
    exclude_keywords: str = ""
    is_competitor: bool = False
    active: bool = True


class MonitorPatch(BaseModel):
    name: str | None = None
    query: str | None = None
    exclude_keywords: str | None = None
    is_competitor: bool | None = None
    active: bool | None = None


class LeadPatch(BaseModel):
    status: Literal["new", "qualified", "disqualified", "contacted", "exported"]


class ICPIn(BaseModel):
    titles_include: list[str] = []
    titles_exclude: list[str] = []
    seniorities: list[str] = []
    company_size_min: int | None = None
    company_size_max: int | None = None
    industries: list[str] = []
    locations: list[str] = []


class OfferIn(BaseModel):
    product: str = ""
    value_prop: str = ""
    competitors: list[str] = []


class RoutingIn(BaseModel):
    min_icp_fit: int = Field(60, ge=0, le=100)
    min_intent: int = Field(50, ge=0, le=100)
    webhook_url: str = ""
    slack_webhook_url: str = ""


def seed_demo(db: Database) -> None:
    """First boot on demo data: two example monitors and an ICP, so the UI isn't empty."""
    if db.one("SELECT 1 FROM monitors LIMIT 1"):
        return
    for name, kind, query, competitor in (
        ("Outbound pain", "keyword", "outbound prospecting, cold email", 0),
        ("Competitor: Acme", "company", "https://www.linkedin.com/company/acme-sales", 1),
    ):
        db.execute("INSERT INTO monitors (name, kind, query, is_competitor, created_at) VALUES (?,?,?,?,?)",
                   (name, kind, query, competitor, now_iso()))
    db.set_setting("icp", {**db.get_setting("icp"),
                           "titles_include": ["founder", "ceo", "coo", "sales", "growth", "revenue",
                                              "marketing", "partnerships", "business development"],
                           "seniorities": ["c_level", "vp", "director", "manager"],
                           "company_size_min": 10, "company_size_max": 1000})


def create_app(settings: Settings | None = None, pipeline: Pipeline | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = pipeline.db if pipeline else Database(settings.db_path)
    pipeline = pipeline or Pipeline(
        db=db,
        provider=get_provider(settings),
        enricher=get_enricher(settings.enrichment_provider),
        scorer=Scorer(settings.anthropic_api_key, settings.scoring_model),
    )

    async def scheduler():
        interval = settings.run_interval_minutes * 60
        while True:
            await asyncio.sleep(interval)
            try:
                await asyncio.to_thread(pipeline.run_all)
            except Exception:
                log.exception("Scheduled run failed")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if settings.seed_demo and settings.linkedin_provider == "mock":
            seed_demo(db)
        task = asyncio.create_task(scheduler()) if settings.run_interval_minutes > 0 else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Signal Radar", lifespan=lifespan)
    app.state.pipeline = pipeline

    @app.middleware("http")
    async def require_api_key(request: Request, call_next):
        # Protects the API when API_KEY is set. Header for API clients, query param for CSV links.
        if (settings.api_key and request.url.path.startswith("/api/")
                and request.method != "OPTIONS"):
            given = request.headers.get("x-api-key") or request.query_params.get("api_key") or ""
            if not secrets.compare_digest(given, settings.api_key):
                return JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
        return await call_next(request)

    # Added after the auth middleware so it wraps it: 401s still carry CORS headers.
    app.add_middleware(CORSMiddleware, allow_origin_regex=settings.cors_origin_regex,
                       allow_methods=["*"], allow_headers=["*"])

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    # --- meta -----------------------------------------------------------------
    @app.get("/api/status")
    def status():
        return {"provider": pipeline.provider.name, "enrichment": pipeline.enricher.name,
                "scoring": pipeline.scorer.mode, "scoring_model": settings.scoring_model,
                "run_interval_minutes": settings.run_interval_minutes}

    @app.get("/api/stats")
    def stats():
        one = lambda sql: db.one(sql)["n"]  # noqa: E731
        return {
            "monitors": one("SELECT COUNT(*) n FROM monitors WHERE active = 1"),
            "posts": one("SELECT COUNT(*) n FROM posts"),
            "signals": one("SELECT COUNT(*) n FROM signals"),
            "leads": one("SELECT COUNT(*) n FROM leads"),
            "qualified": one("SELECT COUNT(*) n FROM leads WHERE status = 'qualified'"),
            "leads_this_month": one("SELECT COUNT(*) n FROM leads "
                                    "WHERE first_seen >= strftime('%Y-%m-01', 'now')"),
            "recent_runs": db.query("SELECT r.*, m.name AS monitor_name FROM runs r "
                                    "LEFT JOIN monitors m ON m.id = r.monitor_id "
                                    "ORDER BY r.id DESC LIMIT 8"),
        }

    # --- monitors -------------------------------------------------------------
    @app.get("/api/monitors")
    def list_monitors():
        return db.query("""SELECT m.*, COUNT(DISTINCT s.lead_id) AS lead_count,
                                  COUNT(DISTINCT p.id) AS post_count
                           FROM monitors m
                           LEFT JOIN posts p ON p.monitor_id = m.id
                           LEFT JOIN signals s ON s.monitor_id = m.id
                           GROUP BY m.id ORDER BY m.id DESC""")

    @app.post("/api/monitors", status_code=201)
    def create_monitor(body: MonitorIn):
        mid = db.execute(
            """INSERT INTO monitors (name, kind, query, exclude_keywords, is_competitor, active, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (body.name, body.kind, body.query, body.exclude_keywords, int(body.is_competitor),
             int(body.active), now_iso()))
        return db.one("SELECT * FROM monitors WHERE id = ?", (mid,))

    @app.patch("/api/monitors/{monitor_id}")
    def update_monitor(monitor_id: int, body: MonitorPatch):
        changes = {k: (int(v) if isinstance(v, bool) else v)
                   for k, v in body.model_dump(exclude_none=True).items()}
        if not db.one("SELECT 1 FROM monitors WHERE id = ?", (monitor_id,)):
            raise HTTPException(404, "Monitor not found")
        if changes:
            sets = ", ".join(f"{k} = ?" for k in changes)
            db.execute(f"UPDATE monitors SET {sets} WHERE id = ?", (*changes.values(), monitor_id))
        return db.one("SELECT * FROM monitors WHERE id = ?", (monitor_id,))

    @app.delete("/api/monitors/{monitor_id}", status_code=204)
    def delete_monitor(monitor_id: int):
        db.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
        # leads with no remaining signals came only from this monitor
        db.execute("DELETE FROM leads WHERE id NOT IN (SELECT DISTINCT lead_id FROM signals)")

    @app.post("/api/monitors/{monitor_id}/run")
    async def run_monitor(monitor_id: int):
        try:
            return await asyncio.to_thread(pipeline.run_monitor, monitor_id)
        except KeyError:
            raise HTTPException(404, "Monitor not found")

    @app.post("/api/run-all")
    async def run_all():
        return await asyncio.to_thread(pipeline.run_all)

    # --- leads ----------------------------------------------------------------
    def _lead_filter(status: str | None, min_intent: int, min_fit: int, q: str | None,
                     monitor_id: int | None) -> tuple[str, list]:
        where, params = ["l.intent_score >= ?", "l.icp_fit >= ?"], [min_intent, min_fit]
        if status:
            where.append("l.status = ?")
            params.append(status)
        if q:
            where.append("(l.name LIKE ? OR l.headline LIKE ? OR l.company LIKE ?)")
            params += [f"%{q}%"] * 3
        if monitor_id:
            where.append("l.id IN (SELECT lead_id FROM signals WHERE monitor_id = ?)")
            params.append(monitor_id)
        return " AND ".join(where), params

    @app.get("/api/leads")
    def list_leads(status: str | None = None, min_intent: int = 0, min_fit: int = 0,
                   q: str | None = None, monitor_id: int | None = None, limit: int = 200):
        where, params = _lead_filter(status, min_intent, min_fit, q, monitor_id)
        return db.query(
            f"""SELECT l.*, COUNT(s.id) AS signal_count,
                       SUM(s.kind = 'comment') AS comment_count,
                       (SELECT s2.comment_text FROM signals s2 WHERE s2.lead_id = l.id
                          AND s2.comment_text != '' ORDER BY s2.created_at DESC LIMIT 1) AS last_comment
                FROM leads l LEFT JOIN signals s ON s.lead_id = l.id
                WHERE {where} GROUP BY l.id
                ORDER BY l.intent_score DESC, l.icp_fit DESC, l.last_seen DESC LIMIT ?""",
            (*params, limit))

    @app.get("/api/leads.csv")
    def export_leads(status: str | None = None, min_intent: int = 0, min_fit: int = 0,
                     q: str | None = None, monitor_id: int | None = None):
        where, params = _lead_filter(status, min_intent, min_fit, q, monitor_id)
        rows = db.query(f"SELECT l.* FROM leads l WHERE {where} ORDER BY l.intent_score DESC", params)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=LEAD_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=leads.csv"})

    @app.get("/api/leads/{lead_id}")
    def get_lead(lead_id: int):
        lead = db.one("SELECT * FROM leads WHERE id = ?", (lead_id,))
        if not lead:
            raise HTTPException(404, "Lead not found")
        lead["signals"] = pipeline.signals_for(lead_id)
        lead["deliveries"] = db.query("SELECT * FROM deliveries WHERE lead_id = ?", (lead_id,))
        return lead

    @app.patch("/api/leads/{lead_id}")
    def update_lead(lead_id: int, body: LeadPatch):
        if not db.one("SELECT 1 FROM leads WHERE id = ?", (lead_id,)):
            raise HTTPException(404, "Lead not found")
        db.execute("UPDATE leads SET status = ? WHERE id = ?", (body.status, lead_id))
        return get_lead(lead_id)

    @app.post("/api/leads/{lead_id}/rescore")
    async def rescore_lead(lead_id: int):
        if not db.one("SELECT 1 FROM leads WHERE id = ?", (lead_id,)):
            raise HTTPException(404, "Lead not found")
        await asyncio.to_thread(pipeline.evaluate_lead, lead_id)
        return get_lead(lead_id)

    @app.post("/api/leads/{lead_id}/push")
    async def push_lead(lead_id: int):
        lead = db.one("SELECT * FROM leads WHERE id = ?", (lead_id,))
        if not lead:
            raise HTTPException(404, "Lead not found")
        db.execute("DELETE FROM deliveries WHERE lead_id = ?", (lead_id,))
        return await asyncio.to_thread(pipeline.route, lead, pipeline.signals_for(lead_id),
                                       db.get_setting("routing"))

    @app.post("/api/rescore-all")
    async def rescore_all():
        ids = [r["id"] for r in db.query("SELECT id FROM leads")]
        for lead_id in ids:
            await asyncio.to_thread(pipeline.evaluate_lead, lead_id, False)
        return {"rescored": len(ids)}

    # --- settings ---------------------------------------------------------------
    for key, model in (("icp", ICPIn), ("offer", OfferIn), ("routing", RoutingIn)):
        def make(key=key, model=model):
            @app.get(f"/api/settings/{key}", name=f"get_{key}")
            def get_setting():
                return db.get_setting(key)

            @app.put(f"/api/settings/{key}", name=f"put_{key}")
            def put_setting(body: model):  # type: ignore[valid-type]
                db.set_setting(key, body.model_dump())
                return db.get_setting(key)
        make()

    @app.post("/api/destinations/test")
    def test_destinations():
        routing = db.get_setting("routing")
        results = {}
        if routing.get("webhook_url"):
            results["webhook"] = post_json(routing["webhook_url"],
                                           {"event": "test", "source": "signal-radar"}, pipeline.http)
        if routing.get("slack_webhook_url"):
            results["slack"] = post_json(routing["slack_webhook_url"],
                                         {"text": "✅ Signal Radar is connected."}, pipeline.http)
        return {k: {"ok": ok, "detail": d} for k, (ok, d) in results.items()}

    # --- UI ---------------------------------------------------------------------
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    return app
