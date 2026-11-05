"""Vendor and internal communications (S9).

Who decides what:
  * WHAT to ask for = deterministic: the vendor_request text of each finding.
  * HOW to word it  = the LLM may draft the vendor email from that list (never from raw documents).
  * Guard rail      = every requested item must appear in the draft, else we use the template.
  * Rejections      = fixed neutral template, never LLM-drafted, never reveals detection logic.
  * Escalations     = internal note listing rule IDs and evidence, for compliance.
Sending is simulated unless EMAIL_MODE=resend|smtp is configured.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

import requests

from core import config
from core.decision import AWAITING_VENDOR
from core.llm.base import LLMError, provider_label
from core.llm.schemas import EmailDraft
from core.models import Finding

SIGN_OFF = "Kind regards,\nVendor Onboarding Team"


def requested_items(findings: list[Finding]) -> list[dict]:
    """Unique vendor requests as {item, detail}. vendor_request text is 'Item: detail'."""
    items, seen = [], set()
    for f in findings:
        if not f.vendor_request:
            continue
        item, _, detail = f.vendor_request.partition(": ")
        key = (item.lower(), detail.lower())
        if key in seen:
            continue
        seen.add(key)
        items.append({"item": item, "detail": detail})
    return items


def build_payload(form, submission_id: str, status: str, sub_status: str, findings: list[Finding],
                  link: str | None) -> dict:
    """Everything the email drafter may see. Deliberately excludes rule IDs, scores and evidence."""
    return {
        "reference": submission_id,
        "vendor_name": form.legal_name or form.trade_name,
        "contact_name": form.contact.name,
        "status": status,
        "sub_status": sub_status,
        "requested_items": requested_items(findings) if status == "PENDING" else [],
        "resubmission_link": link or "",
    }


def _items_text(items: list[dict]) -> str:
    return "\n".join(f"  {i}. {it['item']}: {it['detail']}" for i, it in enumerate(items, 1))


def template_email(payload: dict) -> EmailDraft:
    """Deterministic email used offline and whenever an LLM draft fails its checks."""
    name = payload.get("contact_name") or payload["vendor_name"]
    ref = payload["reference"]
    status = payload["status"]
    if status == "APPROVED":
        return EmailDraft(subject=f"Onboarding complete - {payload['vendor_name']} ({ref})",
                          body=f"Dear {name},\n\nThank you for completing vendor onboarding. Your details have been "
                               f"verified and you are now set up as a supplier. No further action is needed.\n\n"
                               f"Reference: {ref}\n\n{SIGN_OFF}")
    if status == "REJECTED":
        return rejection_notice(payload)
    items = payload.get("requested_items") or []
    link = payload.get("resubmission_link")
    if items:
        body = (f"Dear {name},\n\nThank you for your onboarding submission (reference {ref}). Before we can "
                f"complete onboarding we need the following:\n\n{_items_text(items)}\n\n")
        if link:
            body += f"Please use this secure link to update your submission (valid for a limited time):\n{link}\n\n"
        body += "You only need to update the items listed above.\n\n" + SIGN_OFF
        return EmailDraft(subject=f"Action needed: onboarding information for {payload['vendor_name']} ({ref})", body=body)
    return EmailDraft(subject=f"Your onboarding submission is under review ({ref})",
                      body=f"Dear {name},\n\nThank you for your submission (reference {ref}). It is with our team "
                           f"for a final review. No action is needed from you at this stage; we will be in touch "
                           f"shortly.\n\n{SIGN_OFF}")


def rejection_notice(payload: dict) -> EmailDraft:
    """Neutral by design: no reasons, no hints about what was detected."""
    name = payload.get("contact_name") or payload["vendor_name"]
    return EmailDraft(
        subject=f"Update on your onboarding submission ({payload['reference']})",
        body=f"Dear {name},\n\nThank you for your interest in working with us. After review, we are unable to "
             f"proceed with your vendor registration at this time.\n\nReference: {payload['reference']}\n\n{SIGN_OFF}",
    )


def escalation_note(submission_id: str, vendor_name: str, status: str, findings: list[Finding], risk_score: int) -> EmailDraft:
    """Internal note to compliance with the evidence a reviewer needs."""
    serious = [f for f in findings if f.severity in ("CRITICAL", "HIGH")]
    lines = [f"- [{f.severity}] {f.rule_id} {f.title}: {f.message}" for f in serious]
    return EmailDraft(
        subject=f"[Compliance] {status}: {vendor_name} ({submission_id}) - risk {risk_score}",
        body=(f"Automated onboarding checks {status.lower()} submission {submission_id} ({vendor_name}).\n\n"
              f"Findings requiring attention:\n" + "\n".join(lines) +
              "\n\nThe vendor received a neutral notice that does not disclose these reasons. "
              "Full evidence and the audit trail are in the Reviewer Console."),
    )


def check_draft(draft: EmailDraft, payload: dict) -> str:
    """Return '' if the LLM draft is acceptable, else the reason it was rejected."""
    body = draft.body.lower()
    missing = [it["item"] for it in payload["requested_items"] if it["item"].lower() not in body]
    if missing:
        return f"draft omitted requested item(s): {', '.join(missing)}"
    if payload["resubmission_link"] and payload["resubmission_link"] not in draft.body:
        return "draft omitted the resubmission link"
    banned = ["sanction", "fraud", "risk score", "rule id", "ofac", "blacklist"]
    if any(word in body for word in banned):
        return "draft mentioned internal checks"
    if payload["status"] != "APPROVED" and "approved" in body and "not approved" not in body:
        return "draft implied approval"
    return ""


def draft_vendor_email(provider, payload: dict):
    """Returns (draft, drafted_by, usage_or_None)."""
    if payload["status"] != "PENDING" or provider.name == "offline":
        return template_email(payload), "template", None
    try:
        draft, usage = provider.draft_email(payload)
    except LLMError as exc:
        return template_email(payload), f"template (LLM draft failed: {exc})", None
    problem = check_draft(draft, payload)
    if problem:
        return template_email(payload), f"template (LLM draft rejected: {problem})", usage
    return draft, provider_label(provider.name), usage  # the model that answered is in llm_calls


def vendor_email_needed(status: str, sub_status: str) -> bool:
    return status in ("APPROVED", "REJECTED") or sub_status in (AWAITING_VENDOR, "awaiting_internal_review")


# ---------------------------------------------------------------- delivery
def deliver(to_addr: str, draft: EmailDraft) -> tuple[str, str]:
    """Send for real only when EMAIL_MODE says so. Returns (delivery_status, detail)."""
    mode = config.email_mode()
    if mode == "resend" and config.env("RESEND_API_KEY"):
        try:
            r = requests.post("https://api.resend.com/emails", timeout=15,
                              headers={"Authorization": f"Bearer {config.env('RESEND_API_KEY')}"},
                              json={"from": config.env("EMAIL_FROM"), "to": [to_addr],
                                    "subject": draft.subject, "text": draft.body})
            return ("sent", f"resend id {r.json().get('id')}") if r.ok else ("failed", f"resend HTTP {r.status_code}")
        except requests.RequestException as exc:
            return "failed", f"resend error: {exc}"
    if mode == "smtp" and config.env("SMTP_HOST"):
        try:
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = config.env("EMAIL_FROM"), to_addr, draft.subject
            msg.set_content(draft.body)
            with smtplib.SMTP(config.env("SMTP_HOST"), int(config.env("SMTP_PORT", "587")), timeout=15) as s:
                s.starttls()
                if config.env("SMTP_USER"):
                    s.login(config.env("SMTP_USER"), config.env("SMTP_PASSWORD"))
                s.send_message(msg)
            return "sent", "smtp"
        except (OSError, smtplib.SMTPException) as exc:
            return "failed", f"smtp error: {exc}"
    return "simulated", "EMAIL_MODE=simulated: written to outbox, not sent"
