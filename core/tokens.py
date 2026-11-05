"""Resubmission tokens for the vendor's "fix your submission" link.

* 32 random bytes (secrets.token_urlsafe) - unguessable.
* Only the SHA-256 hash is stored, so a database leak does not leak working links.
* Expires after policy.resubmission_token_ttl_days; single use (marked used on resubmit).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from core import config, db


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(submission_id: str, ttl_days: int, conn=None) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    row = (_hash(token), submission_id, now.isoformat(timespec="seconds"),
           (now + timedelta(days=ttl_days)).isoformat(timespec="seconds"))
    sql = "INSERT INTO tokens(token_hash, submission_id, created_at, expires_at) VALUES (?, ?, ?, ?)"
    if conn is not None:
        conn.execute(sql, row)
    else:
        with db.session() as c:
            c.execute(sql, row)
    return token


def link(token: str) -> str:
    return f"{config.app_base_url()}/resubmit?token={token}"


def resolve(token: str) -> tuple[str | None, str]:
    """Return (submission_id, '') if the token is usable, else (None, reason)."""
    if not token:
        return None, "No token supplied."
    row = db.query_one("SELECT * FROM tokens WHERE token_hash = ?", (_hash(token),))
    if not row:
        return None, "This link is not valid."
    if row["used_at"]:
        return None, "This link has already been used. Please use the link in the most recent email."
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        return None, "This link has expired. Please contact the onboarding team for a new one."
    return row["submission_id"], ""


def mark_used(token: str, conn=None) -> None:
    sql, params = "UPDATE tokens SET used_at = ? WHERE token_hash = ?", (db.now_iso(), _hash(token))
    if conn is not None:
        conn.execute(sql, params)
    else:
        with db.session() as c:
            c.execute(sql, params)


def latest_for(submission_id: str) -> dict | None:
    return db.query_one("SELECT * FROM tokens WHERE submission_id = ? ORDER BY created_at DESC LIMIT 1",
                        (submission_id,))
