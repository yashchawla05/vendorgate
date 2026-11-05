"""Idempotent startup: create the schema, seed the vendor master, replay history.

Free hosts (Streamlit Community Cloud) can wipe the disk whenever the app sleeps or
restarts, so this runs on every start and only does work that is missing:
  1. CREATE TABLE IF NOT EXISTS ...
  2. vendor master from data/vendor_master_seed.json (INSERT OR IGNORE)
  3. history: older synthetic submissions replayed through the REAL pipeline (offline
     provider, back-dated timestamps, flagged seeded=1) so the dashboard has a past.
"""
from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone

from core import audit, db
from core.config import HISTORY_DIR, VENDOR_SEED_FILE
from core.llm.offline_provider import OfflineProvider
from core.pipeline.runner import run_to_completion
from core.submissions import draft_from_folder

COLUMNS = ["vendor_id", "legal_name", "trade_name", "country", "entity_type", "pan", "gstin", "ein", "company_number",
           "bank_name", "bank_code", "account_number", "account_holder", "contact_email", "website", "status", "approved_on"]


def seed_vendors() -> int:
    vendors = json.loads(VENDOR_SEED_FILE.read_text())
    with db.session() as conn:
        for v in vendors:
            conn.execute(f"INSERT OR IGNORE INTO vendors({', '.join(COLUMNS)}, source_submission_id) "
                         f"VALUES ({', '.join('?' * len(COLUMNS))}, 'seed')", [v[c] for c in COLUMNS])
    return len(vendors)


def backfill_history() -> int:
    if db.get_meta("history_backfilled"):
        return 0
    manifest = json.loads((HISTORY_DIR / "manifest.json").read_text())
    today = datetime.now(timezone.utc).date()
    provider = OfflineProvider()  # free and deterministic; the UI labels these runs "seeded"
    count = 0
    for i, entry in enumerate(sorted(manifest, key=lambda e: -e["days_ago"])):
        submitted = datetime.combine(today - timedelta(days=entry["days_ago"]), time(9 + i % 8, 10 * (i % 6)), timezone.utc)
        draft = draft_from_folder(HISTORY_DIR / entry["id"], "history", submitted_at=submitted, seeded=True)
        run_to_completion(draft, provider=provider)
        count += 1
    db.set_meta("history_backfilled", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return count


def ensure_ready(with_history: bool = True) -> dict:
    db.init_schema()
    vendors = seed_vendors()
    replayed = backfill_history() if with_history else 0
    if replayed:
        audit.log("demo_data_seeded", details={"vendors": vendors, "history_submissions": replayed})
    return {"vendors": vendors, "history_replayed": replayed}


def reset_demo_data() -> dict:
    """Delete the database and rebuild it (Reviewer Console > System health > Reset)."""
    from core import config

    path = config.db_path()
    for suffix in ("", "-wal", "-shm"):
        p = path.with_name(path.name + suffix)
        if p.exists():
            p.unlink()
    return ensure_ready()
