"""SQLite storage. One connection per call keeps things thread-safe and simple."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS monitors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('keyword', 'profile', 'company')),
    query TEXT NOT NULL,
    exclude_keywords TEXT NOT NULL DEFAULT '',
    is_competitor INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_run_at TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id INTEGER NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    author_name TEXT NOT NULL DEFAULT '',
    author_headline TEXT NOT NULL DEFAULT '',
    author_url TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    posted_at TEXT,
    reaction_count INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL,
    UNIQUE (monitor_id, external_id)
);

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_url TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    headline TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    company_domain TEXT NOT NULL DEFAULT '',
    company_size INTEGER,
    industry TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    seniority TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    email_status TEXT NOT NULL DEFAULT '',
    icp_fit INTEGER NOT NULL DEFAULT 0,
    intent_score INTEGER NOT NULL DEFAULT 0,
    sentiment TEXT NOT NULL DEFAULT '',
    buying_stage TEXT NOT NULL DEFAULT '',
    intent_reason TEXT NOT NULL DEFAULT '',
    suggested_opener TEXT NOT NULL DEFAULT '',
    scored_by TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    monitor_id INTEGER NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('reaction', 'comment')),
    reaction_type TEXT NOT NULL DEFAULT '',
    comment_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (lead_id, post_id, kind)
);

CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    destination TEXT NOT NULL,
    ok INTEGER NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (lead_id, destination)
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id INTEGER REFERENCES monitors(id) ON DELETE SET NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    posts_found INTEGER NOT NULL DEFAULT 0,
    signals_found INTEGER NOT NULL DEFAULT 0,
    new_leads INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "icp": {
        "titles_include": [],
        "titles_exclude": ["student", "intern", "recruiter"],
        "seniorities": [],
        "company_size_min": None,
        "company_size_max": None,
        "industries": [],
        "locations": [],
    },
    "offer": {
        "product": "",
        "value_prop": "",
        "competitors": [],
    },
    "routing": {
        "min_icp_fit": 60,
        "min_intent": 50,
        "webhook_url": "",
        "slack_webhook_url": "",
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Database:
    def __init__(self, path: str):
        self.path = path
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        with self.connect() as conn:
            return conn.execute(sql, params).lastrowid

    # --- settings -------------------------------------------------------
    def get_setting(self, key: str) -> Any:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        default = DEFAULT_SETTINGS.get(key)
        if row is None:
            return json.loads(json.dumps(default))
        value = json.loads(row["value"])
        if isinstance(default, dict):
            return {**default, **value}
        return value

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
