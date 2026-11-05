"""Human review actions from the Review Queue. Every action needs a reason and is audited.

The system decision is kept in submissions.system_status; the human decision becomes the
current status. Both remain visible, so overrides are never hidden.
"""
from __future__ import annotations

from core import audit, comms, db, tokens
from core.models import SubmissionForm
from core.pipeline.stages_outcome import create_vendor
from core.rules import policy

ACTIONS = {"approve": "Approve", "reject": "Reject", "request_info": "Request information"}
MIN_REASON = 10


def apply_review(submission_id: str, action: str, reason: str, reviewer: str, request_text: str = "") -> dict:
    if action not in ACTIONS:
        raise ValueError(f"Unknown action {action}")
    reason = (reason or "").strip()
    if len(reason) < MIN_REASON:
        raise ValueError(f"A reason of at least {MIN_REASON} characters is required.")
    sub = db.query_one("SELECT * FROM submissions WHERE id = ?", (submission_id,))
    if not sub or sub["status"] != "PENDING":
        raise ValueError("Only PENDING submissions can be reviewed.")
    form = SubmissionForm.model_validate_json(sub["form_json"])
    reviewer = reviewer.strip() or "reviewer"
    now = db.now_iso()
    result = {"action": action}
    with db.session() as conn:
        conn.execute("INSERT INTO review_actions(submission_id, action, reason, reviewer, created_at) VALUES (?,?,?,?,?)",
                     (submission_id, action, reason, reviewer, now))
        if action == "approve":
            conn.execute("UPDATE submissions SET status='APPROVED', sub_status='' WHERE id=?", (submission_id,))
            result["vendor_id"] = create_vendor(conn, submission_id, form, now)
            draft = comms.template_email({"reference": submission_id, "vendor_name": form.legal_name,
                                          "contact_name": form.contact.name, "status": "APPROVED"})
        elif action == "reject":
            conn.execute("UPDATE submissions SET status='REJECTED', sub_status='' WHERE id=?", (submission_id,))
            draft = comms.rejection_notice({"reference": submission_id, "vendor_name": form.legal_name,
                                            "contact_name": form.contact.name})
        else:
            conn.execute("UPDATE submissions SET sub_status='awaiting_vendor' WHERE id=?", (submission_id,))
            token = tokens.create(submission_id, policy()["resubmission_token_ttl_days"], conn=conn)
            items = [{"item": "Additional information", "detail": (request_text or reason).strip()}]
            draft = comms.template_email({"reference": submission_id, "vendor_name": form.legal_name,
                                          "contact_name": form.contact.name, "status": "PENDING",
                                          "requested_items": items, "resubmission_link": tokens.link(token)})
        delivery, detail = comms.deliver(form.contact.email, draft)
        conn.execute("INSERT INTO outbox(submission_id, created_at, audience, to_addr, subject, body, drafted_by, delivery,"
                     " delivery_detail) VALUES (?,?,?,?,?,?,?,?,?)",
                     (submission_id, now, "vendor", form.contact.email, draft.subject, draft.body,
                      f"template (reviewer {reviewer})", delivery, detail))
        audit.log(f"review_{action}", submission_id=submission_id, actor=f"reviewer:{reviewer}", conn=conn,
                  details={"reason": reason, "system_status": sub["system_status"], **result})
    return result


def queue(sub_status: str | None = None) -> list[dict]:
    sql = ("SELECT s.id, s.legal_name, s.country, s.sub_status, s.risk_score, s.submitted_at, s.version, s.seeded "
           "FROM submissions s WHERE s.status = 'PENDING'")
    params: tuple = ()
    if sub_status:
        sql += " AND s.sub_status = ?"
        params = (sub_status,)
    rows = db.query(sql + " ORDER BY s.submitted_at", params)
    for r in rows:
        r["rules"] = [f["rule_id"] for f in db.query(
            "SELECT DISTINCT rule_id FROM findings WHERE submission_id = ? AND severity IN ('CRITICAL','HIGH','WARN')",
            (r["id"],))]
    return rows

