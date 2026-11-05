"""State shared by the pipeline stages during one run."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.decision import Decision
from core.llm.schemas import ExtractedField
from core.models import Finding, SubmissionForm


@dataclass
class SubmissionDraft:
    """What arrives at the door: a form, files per slot, and where it came from."""

    form: SubmissionForm
    files: dict[str, tuple[str, bytes]]  # slot -> (filename, file bytes)
    source: str = "portal"  # portal | api | scenario:<id> | history
    parent_id: str | None = None  # set for a resubmission
    token: str | None = None  # the resubmission token used (marked as used at intake)
    submitted_at: datetime | None = None  # only history backfill sets this; otherwise "now"
    seeded: bool = False


@dataclass
class DocResult:
    doc_id: int
    slot: str
    filename: str
    path: str
    sha256: str
    carried_from: int | None = None
    detected_type: str = ""
    type_confidence: float = 0.0
    confidence: float = 0.0
    readable: bool = False
    accepted: bool = False  # right type, readable -> used in cross-checks
    fields: dict[str, ExtractedField] = field(default_factory=dict)
    provider: str = ""
    notes: str = ""

    def value(self, name: str) -> str:
        f = self.fields.get(name)
        return f.value if f else ""


@dataclass
class StageOutcome:
    status: str  # passed | flagged | failed | degraded | done (S8-S10: produced output, nothing to pass/fail)
    summary: str
    findings: list[Finding] = field(default_factory=list)
    details: dict = field(default_factory=dict)


@dataclass
class RunContext:
    draft: SubmissionDraft
    provider: object  # LLMProvider
    registry: object  # RegistryClient
    policy: dict
    submission_id: str = ""
    chain_id: str = ""
    version: int = 1
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    parent: dict | None = None  # previous submission row (+ "form", "findings")
    docs: list[DocResult] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    norm: dict[str, str] = field(default_factory=dict)  # validated, normalised IDs from S4
    valid: dict[str, bool] = field(default_factory=dict)
    comparison: list[dict] = field(default_factory=list)  # field x source table for the UI
    decision: Decision | None = None
    failed_resubmissions: int = 0
    token_raw: str | None = None
    stage_errors: list[str] = field(default_factory=list)
    elapsed: float = 0.0  # seconds since the run started (used to timestamp on the submission clock)

    @property
    def form(self) -> SubmissionForm:
        return self.draft.form

    def doc(self, doc_type: str) -> DocResult | None:
        """First accepted document of a type (wrong-type or unreadable docs are never used)."""
        return next((d for d in self.docs if d.accepted and d.detected_type == doc_type), None)

    def bank_doc(self) -> DocResult | None:
        return self.doc("bank_letter") or self.doc("cancelled_cheque")
