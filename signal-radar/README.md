# Signal Radar

A signal-based prospecting tool in the style of Jungler.ai. It watches public LinkedIn
conversations, captures **everyone who reacts to or comments on** relevant posts, ranks
them by ICP fit and buying intent, and pushes qualified leads to your stack.

```
Monitors ──► Posts ──► Engagers ──► ICP fit ──► AI intent score ──► Enrich ──► Slack / Webhook / CSV
(keywords,     (provider)  (reactions,   (title, seniority,  (Claude: score, stage,   (email)   (Clay, n8n, HeyReach,
 competitors,              comments)      size, industry,     reason, opener)                    Make, CRM…)
 profiles)                                geo)
```

## What it does

| Capability | How |
|---|---|
| **Keyword monitors** | Track phrases like `"cold email", "outbound tool"`; optional exclude list (`hiring`) |
| **Competitor / profile monitors** | Track a competitor's company page or a thought leader's profile; flagged engagement weighs more |
| **Engager capture** | Every reaction and comment becomes a signal, de-duplicated per person across all monitors |
| **ICP fit (0–100)** | Weighted match on title keywords, seniority (inferred), company size, industry, location; hard excludes |
| **Intent score (0–100)** | Claude reads the post + what the person said and returns score, sentiment, buying stage, a one-line reason and a personalised opener. Falls back to a transparent keyword heuristic when no API key is set |
| **Enrichment** | Pluggable; demo enricher guesses `first.last@domain` (clearly labelled `guessed`) |
| **Routing** | Leads above both thresholds are pushed once to a generic webhook and/or Slack; CSV export anytime |
| **Scheduler** | Active monitors re-run automatically every `RUN_INTERVAL_MINUTES` |
| **Dashboard** | Leads table with filters, lead drawer (signals, opener, contact), monitors, ICP & offer, integrations |

## Quick start

```bash
cd signal-radar
pip install -r requirements.txt
uvicorn app.main:create_app --factory --reload --port 8000
# open http://localhost:8000
```

It runs fully on **demo data** with no keys: add a monitor, click **Run all monitors**.

To turn on AI scoring, set `ANTHROPIC_API_KEY` (model via `SCORING_MODEL`, default
`claude-opus-5-5` at low effort). See `.env.example` for every setting.

```bash
pytest -q   # tests
```

## Going live: data sources

Signal Radar **does not log into LinkedIn or scrape with your account**. Doing that
violates LinkedIn's terms and gets accounts restricted. Real data comes through a
provider in `app/providers/`:

- `mock`: deterministic demo data (default).
- `apify`: runs Apify actors for post search, profile posts, post reactions and post
  comments. Pick actors from the Apify store, set their IDs in env vars, and adjust
  the field mapping in `apify.py` if their output differs.
- Your own: implement `search_posts`, `profile_posts`, `engagements` (see
  `providers/base.py`) against any licensed data vendor.

Do a legal and ToS review of whichever data vendor you choose before selling this.
That review matters more than any code in this repo.

## Integrations

The webhook sends `{"event": "lead.qualified", "lead": {...}, "signals": [...]}`.
Point it at Clay, n8n, Make, Zapier or a HeyReach/CRM endpoint (via one of those)
to start sequences automatically. Slack uses an incoming-webhook URL.

## API

| Method | Path | |
|---|---|---|
| GET/POST | `/api/monitors` | list / create |
| PATCH/DELETE | `/api/monitors/{id}` | update / delete |
| POST | `/api/monitors/{id}/run`, `/api/run-all` | run now |
| GET | `/api/leads?status=&min_intent=&min_fit=&q=&monitor_id=` | ranked leads |
| GET | `/api/leads.csv` | export (same filters) |
| GET/PATCH | `/api/leads/{id}` | detail with signals / set status |
| POST | `/api/leads/{id}/rescore`, `/api/leads/{id}/push`, `/api/rescore-all` | |
| GET/PUT | `/api/settings/{icp,offer,routing}` | configuration |
| POST | `/api/destinations/test` | send a test event |

Interactive docs at `/docs`.

## Layout

```
app/
  main.py          FastAPI app, REST API, scheduler
  pipeline.py      monitor → posts → engagers → score → enrich → route
  providers/       LinkedIn data sources (mock, apify)
  icp.py           ICP fit + seniority inference
  scoring.py       Claude intent scoring + heuristic fallback
  enrichment.py    email enrichment (pluggable)
  destinations.py  webhook / Slack payloads
  db.py            SQLite schema + settings
static/            dashboard (vanilla JS, no build step)
tests/
```

## Roadmap to parity and beyond

- Licensed data provider in production, plus per-workspace usage credits and billing (Stripe)
- Multi-user auth and workspaces
- Native HeyReach / HubSpot / Salesforce pushes, and email verification (e.g. a waterfall across vendors)
- Saved lead views, and Slack digests instead of per-lead pings
- Company-level rollup: several people at one account engaging means account-level intent
- Batch scoring via the Message Batches API to halve LLM cost at volume
