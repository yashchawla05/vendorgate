"""SQLite storage.

Why SQLite: one file, zero setup, enough for a demo with a handful of concurrent users.
The database is disposable: free hosts wipe the disk on restart, so core/seed.py rebuilds
it (idempotently) on startup. Each operation opens its own short-lived connection, which
is the simplest way to be safe with Streamlit's one-thread-per-session model.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from core import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY,
    chain_id TEXT NOT NULL,          -- first submission of this vendor's attempts
    version INTEGER NOT NULL,        -- 1 = first attempt, 2 = first resubmission, ...
    parent_id TEXT,
    legal_name TEXT, country TEXT, entity_type TEXT,
    form_json TEXT NOT NULL,
    source TEXT,                     -- portal | api | scenario:<id> | history
    submitted_at TEXT NOT NULL,
    status TEXT NOT NULL,            -- RUNNING | APPROVED | PENDING | REJECTED
    sub_status TEXT,
    system_status TEXT,              -- what the pipeline decided (kept after a human override)
    risk_score INTEGER,
    decided_at TEXT,
    provider TEXT,
    seeded INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL,
    slot TEXT, filename TEXT, path TEXT, sha256 TEXT, size INTEGER,
    carried_from INTEGER,            -- document id reused from the previous submission
    detected_type TEXT, type_confidence REAL, confidence REAL, readable INTEGER,
    accepted INTEGER,                -- 1 if the document satisfies its slot and is used in cross-checks
    fields_json TEXT, provider TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS stage_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL, stage TEXT, name TEXT, status TEXT,
    started_at TEXT, duration_ms INTEGER, summary TEXT, details_json TEXT
);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL, stage TEXT, rule_id TEXT, severity TEXT, category TEXT, title TEXT,
    message TEXT, resolver TEXT, blocks_approval INTEGER, field TEXT, evidence_json TEXT, vendor_request TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    submission_id TEXT PRIMARY KEY, status TEXT, sub_status TEXT, risk_score INTEGER,
    breakdown_json TEXT, reasons_json TEXT, explanation TEXT, policy_version TEXT, decided_at TEXT
);
CREATE TABLE IF NOT EXISTS vendors (
    vendor_id TEXT PRIMARY KEY, legal_name TEXT, trade_name TEXT, country TEXT, entity_type TEXT,
    pan TEXT, gstin TEXT, ein TEXT, company_number TEXT, bank_name TEXT, bank_code TEXT,
    account_number TEXT, account_holder TEXT, contact_email TEXT, website TEXT,
    status TEXT, approved_on TEXT, source_submission_id TEXT
);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT, created_at TEXT, audience TEXT, to_addr TEXT, subject TEXT, body TEXT,
    drafted_by TEXT, delivery TEXT, delivery_detail TEXT
);
CREATE TABLE IF NOT EXISTS tokens (
    token_hash TEXT PRIMARY KEY, submission_id TEXT, created_at TEXT, expires_at TEXT, used_at TEXT
);
CREATE TABLE IF NOT EXISTS review_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT, action TEXT, reason TEXT, reviewer TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, submission_id TEXT, actor TEXT, event TEXT, details_json TEXT
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, submission_id TEXT, stage TEXT, provider TEXT, model TEXT, purpose TEXT,
    input_tokens INTEGER, output_tokens INTEGER, latency_ms INTEGER, ok INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS ix_findings_sub ON findings(submission_id);
CREATE INDEX IF NOT EXISTS ix_stage_sub ON stage_runs(submission_id);
CREATE INDEX IF NOT EXISTS ix_docs_sub ON documents(submission_id);
CREATE INDEX IF NOT EXISTS ix_audit_sub ON audit_events(submission_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    path = config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # readers do not block the writer
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    """Open, commit on success, always close."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_schema() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)


def to_json(value) -> str:
    return json.dumps(value, default=str)


def query(sql: str, params: tuple = ()) -> list[dict]:
    with session() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def get_meta(key: str) -> str | None:
    row = query_one("SELECT value FROM meta WHERE key = ?", (key,))
    return row["value"] if row else None


def set_meta(key: str, value: str) -> None:
    with session() as conn:
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))
