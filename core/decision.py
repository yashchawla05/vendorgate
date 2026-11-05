"""The decision engine. Pure and deterministic: same findings + same policy = same decision.

No LLM output reaches this function except through findings that deterministic code
created. That is how "the LLM never makes or changes a decision" is enforced structurally.

Order of evaluation (from config/policy.yaml):
  1. REJECTED  if any reject-trigger rule fired (strong sanctions hit, identifier shared with
               another vendor), or >= N CRITICAL findings, or too many failed resubmissions.
  2. PENDING   if any finding blocks approval, or the risk score is at/above the approval limit.
               Sub-status "awaiting_vendor" when every blocker is something the vendor can fix,
               otherwise "awaiting_internal_review".
  3. APPROVED  otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.models import Finding

AWAITING_VENDOR = "awaiting_vendor"
AWAITING_REVIEW = "awaiting_internal_review"


@dataclass
class Decision:
    status: str
    sub_status: str
    risk_score: int
    contributions: list[dict] = field(default_factory=list)  # per-finding risk points
    reasons: list[str] = field(default_factory=list)  # rule-level reasons for the status
    explanation: str = ""  # plain-English paragraph for the banner


def risk(findings: list[Finding], policy: dict) -> tuple[int, list[dict]]:
    weights = policy["risk_weights"]
    contributions = [{"rule_id": f.rule_id, "severity": f.severity, "title": f.title, "points": weights[f.severity]}
                     for f in findings if weights[f.severity] > 0]
    return min(policy["risk_cap"], sum(c["points"] for c in contributions)), contributions


def decide(findings: list[Finding], policy: dict, failed_resubmissions: int = 0) -> Decision:
    score, contributions = risk(findings, policy)
    rules_fired = {f.rule_id for f in findings}
    critical = [f for f in findings if f.severity == "CRITICAL"]
    reject = policy["reject"]

    # 1. Rejection conditions
    reasons = []
    triggers = sorted(rules_fired & set(reject["trigger_rules"]))
    if triggers:
        reasons.append(f"Reject-trigger rule(s) fired: {', '.join(triggers)}")
    if len(critical) >= reject["min_critical_findings"]:
        reasons.append(f"{len(critical)} CRITICAL findings (limit {reject['min_critical_findings']})")
    if failed_resubmissions > reject["max_failed_resubmissions"]:
        reasons.append(f"{failed_resubmissions} failed resubmissions (limit {reject['max_failed_resubmissions']})")
    if reasons:
        return Decision("REJECTED", "", score, contributions, reasons,
                        _explain("REJECTED", "", findings, score, reasons))

    # 2. Pending conditions
    blockers = [f for f in findings if f.blocks_approval or f.severity in ("HIGH", "CRITICAL")]
    limit = policy["thresholds"]["approve_max_risk"]
    if blockers or score >= limit:
        if blockers:
            reasons.append(f"{len(blockers)} finding(s) block approval: "
                           + ", ".join(sorted({f.rule_id for f in blockers})))
        if score >= limit:
            reasons.append(f"Risk score {score} is at or above the approval limit {limit}")
        vendor_fixable = blockers and all(f.resolver == "vendor" for f in blockers)
        sub = AWAITING_VENDOR if vendor_fixable else AWAITING_REVIEW
        return Decision("PENDING", sub, score, contributions, reasons, _explain("PENDING", sub, findings, score, reasons))

    # 3. Approved
    reasons.append(f"No blocking findings and risk score {score} < {limit}")
    return Decision("APPROVED", "", score, contributions, reasons, _explain("APPROVED", "", findings, score, reasons))


def _explain(status: str, sub: str, findings: list[Finding], score: int, reasons: list[str]) -> str:
    """Deterministic plain-English summary (no LLM), shown on the decision banner."""
    if status == "APPROVED":
        notes = [f for f in findings if f.severity in ("INFO", "WARN")]
        tail = f" {len(notes)} non-blocking note(s) recorded." if notes else ""
        return f"All required checks passed. Risk score {score}/100.{tail}"
    ranked = sorted(findings, key=lambda f: ["CRITICAL", "HIGH", "WARN", "INFO"].index(f.severity))
    counts: dict[str, int] = {}
    for f in ranked:  # one entry per rule, most severe first; a rule hit on several documents shows "×n"
        counts[f.rule_id] = counts.get(f.rule_id, 0) + 1
    titles = {f.rule_id: f.title for f in ranked}
    issues = "; ".join(f"{titles[r]} ({r}{f' ×{n}' if n > 1 else ''})" for r, n in list(counts.items())[:3])
    if status == "REJECTED":
        return f"Rejected under policy: {reasons[0]}. Key issues: {issues}. Risk score {score}/100."
    who = "the vendor needs to provide or correct information" if sub == AWAITING_VENDOR \
        else "a reviewer must make a judgement before onboarding can continue"
    return f"Pending: {who}. Key issues: {issues}. Risk score {score}/100."
