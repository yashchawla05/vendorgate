"""S8 Risk & decision, S9 Communication, S10 Finalise."""
from __future__ import annotations

from datetime import timedelta

from core import audit, comms, db, tokens
from core.decision import AWAITING_REVIEW, decide
from core.pipeline.context import RunContext, StageOutcome
from core.pipeline.stages_intake import _log_llm
from core.rules import make_finding

COMPLIANCE_INBOX = "compliance@vendorgate.example"
REVIEW_INBOX = "onboarding-review@vendorgate.example"


# ================================================================ S8 Risk scoring and decision
def s8_decision(ctx: RunContext) -> StageOutcome:
    findings = []
    if ctx.stage_errors:
        # A check that could not run is an unknown, and unknown is never approved.
        findings.append(make_finding("SYS-001", f"Stage(s) failed: {'; '.join(ctx.stage_errors)}",
                                     evidence={"errors": ctx.stage_errors}))
    ctx.decision = decide(ctx.findings + findings, ctx.policy, ctx.failed_resubmissions)
    d = ctx.decision
    label = d.status + (f" ({d.sub_status.replace('_', ' ')})" if d.sub_status else "")
    return StageOutcome("done", f"{label}; risk score {d.risk_score}/100", findings, {
        "status": d.status, "sub_status": d.sub_status, "risk_score": d.risk_score,
        "contributions": d.contributions, "reasons": d.reasons, "explanation": d.explanation,
        "policy_version": ctx.policy["version"]})


# ================================================================ S9 Communication
def _outbox(ctx: RunContext, audience: str, to_addr: str, draft, drafted_by: str) -> dict:
    delivery, detail = comms.deliver(to_addr, draft) if audience == "vendor" else ("internal", "stored for reviewers")
    with db.session() as conn:
        conn.execute("INSERT INTO outbox(submission_id, created_at, audience, to_addr, subject, body, drafted_by, delivery,"
                     " delivery_detail) VALUES (?,?,?,?,?,?,?,?,?)",
                     (ctx.submission_id, _ts(ctx), audience, to_addr, draft.subject, draft.body, drafted_by, delivery, detail))
    return {"audience": audience, "to": to_addr, "subject": draft.subject, "drafted_by": drafted_by, "delivery": delivery}


def s9_communication(ctx: RunContext) -> StageOutcome:
    d, form = ctx.decision, ctx.form
    items = comms.requested_items(ctx.findings) if d.status == "PENDING" else []
    link = None
    if d.status == "PENDING" and items:
        ctx.token_raw = tokens.create(ctx.submission_id, ctx.policy["resubmission_token_ttl_days"])
        link = tokens.link(ctx.token_raw)
    payload = comms.build_payload(form, ctx.submission_id, d.status, d.sub_status, ctx.findings, link)
    draft, drafted_by, usage = comms.draft_vendor_email(ctx.provider, payload)
    if usage:
        _log_llm(ctx, usage, "S9", not drafted_by.startswith("template"), purpose="email")
    sent = [_outbox(ctx, "vendor", form.contact.email or "(no email given)", draft, drafted_by)]
    if d.status == "REJECTED":
        note = comms.escalation_note(ctx.submission_id, form.legal_name, d.status, ctx.findings, d.risk_score)
        sent.append(_outbox(ctx, "internal", COMPLIANCE_INBOX, note, "template"))
    elif d.sub_status == AWAITING_REVIEW:
        note = comms.escalation_note(ctx.submission_id, form.legal_name, "routed for review", ctx.findings, d.risk_score)
        sent.append(_outbox(ctx, "internal", REVIEW_INBOX, note, "template"))
    return StageOutcome("done", f"{len(sent)} message(s) written to outbox; vendor email drafted by {drafted_by}", [],
                        {"messages": sent, "requested_items": items, "resubmission_link": link})


# ================================================================ S10 Finalise
def _ts(ctx: RunContext) -> str:
    """Timestamp on the submission's own clock (history backfill is back-dated)."""
    return (ctx.submitted_at + timedelta(seconds=ctx.elapsed)).isoformat(timespec="seconds")


def _next_vendor_id(conn) -> str:
    n = conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
    return f"V{n + 1:03d}"


def s10_finalise(ctx: RunContext) -> StageOutcome:
    d, form = ctx.decision, ctx.form
    decided_at = _ts(ctx)
    vendor_id = None
    with db.session() as conn:
        conn.execute("INSERT OR REPLACE INTO decisions(submission_id, status, sub_status, risk_score, breakdown_json,"
                     " reasons_json, explanation, policy_version, decided_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (ctx.submission_id, d.status, d.sub_status, d.risk_score, db.to_json(d.contributions),
                      db.to_json(d.reasons), d.explanation, ctx.policy["version"], decided_at))
        conn.execute("UPDATE submissions SET status=?, sub_status=?, system_status=?, risk_score=?, decided_at=? WHERE id=?",
                     (d.status, d.sub_status, d.status, d.risk_score, decided_at, ctx.submission_id))
        audit.log("decision_made", submission_id=ctx.submission_id, conn=conn, ts=decided_at,
                  details={"status": d.status, "sub_status": d.sub_status, "risk_score": d.risk_score,
                           "rules": sorted({f.rule_id for f in ctx.findings}), "policy_version": ctx.policy["version"]})
        if ctx.token_raw:
            audit.log("resubmission_link_issued", submission_id=ctx.submission_id, conn=conn, ts=decided_at,
                      details={"expires_in_days": ctx.policy["resubmission_token_ttl_days"]})
        if d.status == "APPROVED":
            vendor_id = create_vendor(conn, ctx.submission_id, form, decided_at)
            audit.log("vendor_created", submission_id=ctx.submission_id, conn=conn, ts=decided_at,
                      details={"vendor_id": vendor_id})
    summary = f"Decision {d.status} saved"
    if vendor_id:
        summary += f"; added to vendor master as {vendor_id}"
    if ctx.token_raw:
        summary += "; resubmission link issued"
    return StageOutcome("done", summary, [], {"vendor_id": vendor_id, "token_issued": bool(ctx.token_raw)})


def create_vendor(conn, submission_id: str, form, approved_on: str) -> str:
    """Add an approved submission to the vendor master (also used by manual approvals)."""
    vendor_id = _next_vendor_id(conn)
    bank_code = form.bank.ifsc or form.bank.routing_number or form.bank.sort_code
    conn.execute("INSERT INTO vendors(vendor_id, legal_name, trade_name, country, entity_type, pan, gstin, ein,"
                 " company_number, bank_name, bank_code, account_number, account_holder, contact_email, website, status,"
                 " approved_on, source_submission_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (vendor_id, form.legal_name, form.trade_name, form.country, form.entity_type, form.tax.pan.upper(),
                  form.tax.gstin.upper(), form.tax.ein, form.tax.company_number.upper(), form.bank.bank_name,
                  bank_code.upper(), form.bank.account_number.strip(), form.bank.account_holder, form.contact.email,
                  form.website, "approved", approved_on[:10], submission_id))
    return vendor_id

