"""Append-only audit trail. Every state change writes one row here.

The audit log replaces "the trail lives in inboxes": who did what, when, and why,
queryable and exportable to CSV from the Audit log page.
"""
from __future__ import annotations

import sqlite3

from core import db


def log(event: str, *, submission_id: str | None = None, actor: str = "system", details: dict | None = None,
        conn: sqlite3.Connection | None = None, ts: str | None = None) -> None:
    row = (ts or db.now_iso(), submission_id, actor, event, db.to_json(details or {}))
    sql = "INSERT INTO audit_events(ts, submission_id, actor, event, details_json) VALUES (?, ?, ?, ?, ?)"
    if conn is not None:
        conn.execute(sql, row)  # inside the caller's transaction
    else:
        with db.session() as c:
            c.execute(sql, row)
