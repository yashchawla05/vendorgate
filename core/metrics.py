"""Dashboard numbers, computed from the database (no Streamlit here, so it is testable)."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from core import db
from core.rules import catalogue, policy


def submissions_frame(include_seeded: bool = True) -> pd.DataFrame:
    rows = db.query("SELECT s.*, d.decided_at AS system_decided_at FROM submissions s "
                    "LEFT JOIN decisions d ON d.submission_id = s.id ORDER BY s.submitted_at DESC")
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    if not include_seeded:
        df = df[df["seeded"] == 0]
    df["submitted_at"] = pd.to_datetime(df["submitted_at"], utc=True, format="ISO8601")
    df["system_decided_at"] = pd.to_datetime(df["system_decided_at"], utc=True, format="ISO8601")
    return df


def kpis(df: pd.DataFrame) -> dict:
    now = datetime.now(timezone.utc)
    total = len(df)
    if not total:
        return {"total": 0}
    counts = df["status"].value_counts().to_dict()
    # Automated decision time = measured duration of the pipeline run (sum of stage timings),
    # more precise than timestamps, which are stored to the second.
    ids = tuple(df["id"])
    marks = ",".join("?" * len(ids))
    runs = db.query(f"SELECT submission_id, SUM(duration_ms) AS ms FROM stage_runs WHERE submission_id IN ({marks})"
                    " GROUP BY submission_id", ids)
    seconds = pd.Series([r["ms"] / 1000 for r in runs], dtype=float)
    pending = df[df["status"] == "PENDING"]
    aging_days = (now - pending["submitted_at"]).dt.total_seconds() / 86400
    reviewed_ids = {r["submission_id"] for r in db.query("SELECT DISTINCT submission_id FROM review_actions")}
    # "Time saved" assumption: every submission the system decided without a human (approved,
    # rejected, or sent back to the vendor with an itemised email) saves one manual review.
    automated = df[(df["status"].isin(["APPROVED", "REJECTED"]) | (df["sub_status"] == "awaiting_vendor"))
                   & ~df["id"].isin(reviewed_ids)]
    minutes = policy()["manual_review_minutes_per_submission"]
    return {
        "total": total,
        "approved": counts.get("APPROVED", 0), "pending": counts.get("PENDING", 0), "rejected": counts.get("REJECTED", 0),
        "pct": {k: round(100 * counts.get(k, 0) / total) for k in ("APPROVED", "PENDING", "REJECTED")},
        "avg_decision_seconds": float(seconds.mean()) if len(seconds) else None,
        "pending_avg_days": float(aging_days.mean()) if len(aging_days) else 0.0,
        "pending_max_days": float(aging_days.max()) if len(aging_days) else 0.0,
        "awaiting_vendor": int((pending["sub_status"] == "awaiting_vendor").sum()),
        "awaiting_review": int((pending["sub_status"] == "awaiting_internal_review").sum()),
        "automated": len(automated),
        "hours_saved": round(len(automated) * minutes / 60, 1),
        "minutes_assumption": minutes,
    }


def top_reasons(df: pd.DataFrame, limit: int = 8) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["rule_id", "title", "severity", "count"])
    ids = tuple(df["id"])
    marks = ",".join("?" * len(ids))
    rows = db.query(f"SELECT rule_id, COUNT(DISTINCT submission_id) AS count FROM findings "
                    f"WHERE submission_id IN ({marks}) AND severity != 'INFO' GROUP BY rule_id ORDER BY count DESC LIMIT ?",
                    (*ids, limit))
    cat = catalogue()
    for r in rows:
        r["title"] = cat[r["rule_id"]]["title"]
        r["severity"] = cat[r["rule_id"]]["severity"]
    return pd.DataFrame(rows, columns=["rule_id", "title", "severity", "count"])


def weekly_status(df: pd.DataFrame) -> pd.DataFrame:
    """Submissions per week (starting Monday) and outcome; every week in the range, empty ones as 0."""
    if df.empty:
        return pd.DataFrame(columns=["week", "status", "count"])
    week = (df["submitted_at"].dt.tz_convert(None).dt.normalize()
            - pd.to_timedelta(df["submitted_at"].dt.weekday, unit="D"))
    counts = df.assign(week=week).groupby(["week", "status"]).size()
    weeks = pd.date_range(week.min(), week.max(), freq="7D")
    full = pd.MultiIndex.from_product([weeks, ["APPROVED", "PENDING", "REJECTED"]], names=["week", "status"])
    return counts.reindex(full, fill_value=0).reset_index(name="count")


def llm_usage() -> dict:
    row = db.query_one("SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens),0) AS tin, COALESCE(SUM(output_tokens),0) AS tout,"
                       " COALESCE(SUM(1 - ok),0) AS failures FROM llm_calls WHERE provider != 'offline'")
    return row or {"calls": 0, "tin": 0, "tout": 0, "failures": 0}
