"""The pipeline: a plain Python generator that yields a StageEvent before and after each stage.

    for event in run_pipeline(draft):
        print(event.stage, event.phase, event.status)

The Live Run page consumes exactly this generator, so what you see on screen is the real
execution, stage by stage. The CLI, the smoke test and the history backfill use it too.
"""
from __future__ import annotations

import time
import traceback
from typing import Iterator

from core import db
from core.llm.base import get_provider
from core.models import StageEvent
from core.pipeline.context import RunContext, StageOutcome, SubmissionDraft
from core.pipeline.stages_checks import s4_formats, s5_consistency, s6_duplicates, s7_sanctions
from core.pipeline.stages_intake import s1_intake, s2_completeness, s3_documents
from core.pipeline.stages_outcome import s8_decision, s9_communication, s10_finalise
from core.registry import get_registry
from core.rules import policy

STAGES = [
    ("S1", "Intake", s1_intake),
    ("S2", "Completeness", s2_completeness),
    ("S3", "Document understanding", s3_documents),
    ("S4", "Format & checksum validation", s4_formats),
    ("S5", "Cross-field & cross-document consistency", s5_consistency),
    ("S6", "Duplicates & vendor-master risk", s6_duplicates),
    ("S7", "Sanctions screening", s7_sanctions),
    ("S8", "Risk scoring & decision", s8_decision),
    ("S9", "Communication", s9_communication),
    ("S10", "Finalise", s10_finalise),
]

# Stages whose failure makes later stages meaningless (nothing to check without intake).
FATAL = {"S1"}


def run_pipeline(draft: SubmissionDraft, provider=None, registry=None) -> Iterator[StageEvent]:
    ctx = RunContext(draft=draft, provider=provider or get_provider(), registry=registry or get_registry(),
                     policy=policy())
    started_run = time.perf_counter()
    for code, name, fn in STAGES:
        yield StageEvent(stage=code, name=name, phase="started")
        t0 = time.perf_counter()
        try:
            outcome = fn(ctx)
        except Exception as exc:  # a broken check must surface, never pass silently
            if code in FATAL:
                raise
            ctx.stage_errors.append(f"{code} {name}: {type(exc).__name__}: {exc}")
            outcome = StageOutcome("failed", f"Stage error: {type(exc).__name__}: {exc}", [],
                                   {"traceback": traceback.format_exc(limit=5)})
        duration_ms = int((time.perf_counter() - t0) * 1000)
        ctx.elapsed = time.perf_counter() - started_run
        ctx.findings.extend(outcome.findings)
        _persist(ctx, code, name, outcome, duration_ms)
        yield StageEvent(stage=code, name=name, phase="completed", status=outcome.status, duration_ms=duration_ms,
                         summary=outcome.summary, findings=outcome.findings,
                         details=outcome.details | {"submission_id": ctx.submission_id})


def _persist(ctx: RunContext, code: str, name: str, outcome: StageOutcome, duration_ms: int) -> None:
    with db.session() as conn:
        conn.execute("INSERT INTO stage_runs(submission_id, stage, name, status, started_at, duration_ms, summary, details_json)"
                     " VALUES (?,?,?,?,?,?,?,?)",
                     (ctx.submission_id, code, name, outcome.status, db.now_iso(), duration_ms, outcome.summary,
                      db.to_json(outcome.details)))
        for f in outcome.findings:
            conn.execute("INSERT INTO findings(submission_id, stage, rule_id, severity, category, title, message, resolver,"
                         " blocks_approval, field, evidence_json, vendor_request) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (ctx.submission_id, code, f.rule_id, f.severity, f.category, f.title, f.message, f.resolver,
                          int(f.blocks_approval), f.field, db.to_json(f.evidence), f.vendor_request))


def run_to_completion(draft: SubmissionDraft, provider=None, registry=None) -> tuple[str, list[StageEvent]]:
    """Convenience for CLI/tests: run everything, return (submission_id, completed events)."""
    events = [e for e in run_pipeline(draft, provider, registry) if e.phase == "completed"]
    return events[0].details["submission_id"], events
