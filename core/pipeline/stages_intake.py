"""S1 Intake, S2 Completeness, S3 Document understanding."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from core import audit, config, db, tokens
from core.documents.dates import DATE_FIELDS, month_first, to_iso_date
from core.documents.injection import find_injection
from core.documents.reader import read_document, sha256_bytes
from core.documents.types import KEY_FIELDS, SLOT_LABELS, SLOTS, label
from core.llm.base import LLMError, Usage
from core.llm.schemas import ExtractedField
from core.models import COUNTRY_NAMES
from core.pipeline.context import DocResult, RunContext, StageOutcome
from core.rules import make_finding, threshold

FIELD_LABELS = {
    "legal_name": "Legal name", "country": "Country", "entity_type": "Entity type",
    "address.line1": "Registered address", "address.city": "City", "address.state": "State",
    "address.postal_code": "Postal code", "contact.name": "Contact name", "contact.email": "Contact email",
    "bank.account_holder": "Bank account holder name", "bank.account_number": "Bank account number",
    "bank.bank_name": "Bank name", "bank.ifsc": "IFSC code", "bank.routing_number": "ABA routing number",
    "bank.sort_code": "Sort code", "tax.pan": "PAN", "tax.gstin": "GSTIN", "tax.ein": "EIN",
    "tax.company_number": "Companies House company number",
}

SLOT_REQUESTS = {
    "pan_card": "please upload a copy of the PAN card of the registered entity",
    "gst_certificate": "please upload your GST registration certificate (Form GST REG-06)",
    "no_gst_declaration": "please upload a signed declaration of non-registration under GST",
    "bank_proof": "please upload a cancelled cheque or a bank letter showing the account holder name, "
                  "account number and IFSC",
    "incorporation_certificate": "please upload your certificate of incorporation",
    "w9": "please upload a completed and signed IRS Form W-9",
    "bank_letter": "please upload a recent letter from your bank confirming the account holder name and account details",
    "company_registration": "please upload your Companies House certificate of incorporation",
}


def form_value(form, path: str) -> str:
    obj = form
    for part in path.split("."):
        obj = getattr(obj, part, "")
    return obj if isinstance(obj, str) else str(obj or "")


# ================================================================ S1 Intake
def _next_id(when: datetime) -> str:
    prefix = f"VG-{when:%y%m%d}-"
    row = db.query_one("SELECT COUNT(*) AS n FROM submissions WHERE id LIKE ?", (prefix + "%",))
    return f"{prefix}{row['n'] + 1:04d}"


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80] or "file"


def s1_intake(ctx: RunContext) -> StageOutcome:
    draft = ctx.draft
    ctx.submitted_at = draft.submitted_at or datetime.now(timezone.utc)
    ctx.submission_id = _next_id(ctx.submitted_at)
    if draft.parent_id:
        parent = db.query_one("SELECT * FROM submissions WHERE id = ?", (draft.parent_id,))
        parent["form"] = json.loads(parent["form_json"])
        parent["findings"] = db.query("SELECT * FROM findings WHERE submission_id = ?", (draft.parent_id,))
        ctx.parent, ctx.chain_id, ctx.version = parent, parent["chain_id"], parent["version"] + 1
    else:
        ctx.chain_id, ctx.version = ctx.submission_id, 1

    folder = config.UPLOAD_DIR / ctx.submission_id
    folder.mkdir(parents=True, exist_ok=True)
    limit = config.max_docs_per_submission()  # cost guard
    files = list(draft.files.items())[:limit]
    ignored = [slot for slot, _ in list(draft.files.items())[limit:]]
    stored = []
    for slot, (filename, data) in files:
        path = folder / f"{slot}__{_safe_name(filename)}"
        path.write_bytes(data)
        stored.append({"slot": slot, "filename": filename, "path": str(path), "sha256": sha256_bytes(data),
                       "size": len(data), "carried_from": None})
    # A resubmission keeps the previous documents for every slot the vendor did not re-upload.
    carried = []
    if ctx.parent:
        new_slots = {s["slot"] for s in stored}
        for d in db.query("SELECT * FROM documents WHERE submission_id = ?", (ctx.parent["id"],)):
            if d["slot"] not in new_slots:
                stored.append({"slot": d["slot"], "filename": d["filename"], "path": d["path"],
                               "sha256": d["sha256"], "size": d["size"], "carried_from": d["id"]})
                carried.append(d["slot"])

    form = ctx.form
    with db.session() as conn:
        conn.execute(
            "INSERT INTO submissions(id, chain_id, version, parent_id, legal_name, country, entity_type, form_json,"
            " source, submitted_at, status, provider, seeded) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ctx.submission_id, ctx.chain_id, ctx.version, draft.parent_id, form.legal_name, form.country,
             form.entity_type, form.model_dump_json(), draft.source, ctx.submitted_at.isoformat(timespec="seconds"),
             "RUNNING", ctx.provider.name, int(draft.seeded)))
        for s in stored:
            cur = conn.execute(
                "INSERT INTO documents(submission_id, slot, filename, path, sha256, size, carried_from)"
                " VALUES (?,?,?,?,?,?,?)",
                (ctx.submission_id, s["slot"], s["filename"], s["path"], s["sha256"], s["size"], s["carried_from"]))
            ctx.docs.append(DocResult(cur.lastrowid, s["slot"], s["filename"], s["path"], s["sha256"], s["carried_from"]))
        if draft.token:
            tokens.mark_used(draft.token, conn=conn)
        audit.log("submission_received", submission_id=ctx.submission_id, actor=f"vendor ({draft.source})",
                  details={"version": ctx.version, "parent": draft.parent_id, "files": len(stored),
                           "carried_over": carried}, conn=conn, ts=ctx.submitted_at.isoformat(timespec="seconds"))

    summary = f"Assigned {ctx.submission_id}; stored {len(files)} file(s)"
    if carried:
        summary += f", carried over {len(carried)} from {draft.parent_id}"
    if ignored:
        summary += f"; ignored {len(ignored)} file(s) over the {limit}-file limit"
    return StageOutcome("passed", summary, [], {
        "submission_id": ctx.submission_id, "version": ctx.version, "parent_id": draft.parent_id,
        "files": [{k: s[k] for k in ("slot", "filename", "size")} | {"sha256": s["sha256"][:16]} for s in stored],
        "carried_over": carried, "ignored": ignored})


# ================================================================ S2 Completeness
def _required_fields(country: str, entity: str, req: dict) -> list[str]:
    return req["fields"]["all"] + req["fields"].get(country, []) + req["fields"].get(f"{country}_{entity}", [])


def _required_slots(form, req: dict) -> list[str]:
    country, entity = form.country, form.entity_type
    slots = req["documents"].get(country, []) + req["documents"].get(f"{country}_{entity}", [])
    if country == "IN":
        # GST registration is optional below the turnover threshold: then a declaration replaces the certificate.
        if form.tax.gstin.strip():
            slots.append("gst_certificate")
        elif form.tax.no_gst_declaration:
            slots.append("no_gst_declaration")
    return slots


def s2_completeness(ctx: RunContext) -> StageOutcome:
    form, req = ctx.form, ctx.policy["requirements"]
    findings = []
    if form.country not in req["supported_countries"]:
        findings.append(make_finding(
            "COMP-003", f"Country '{form.country or 'not given'}' is outside the supported set (India, US, UK).",
            field="country", evidence={"country": form.country}))
        return StageOutcome("flagged", "Unsupported country: manual review required", findings,
                            {"supported": req["supported_countries"]})

    missing_fields = [p for p in _required_fields(form.country, form.entity_type, req) if not form_value(form, p).strip()]
    for path in missing_fields:
        name = FIELD_LABELS.get(path, path)
        findings.append(make_finding("COMP-001", f"{name} is required for {COUNTRY_NAMES[form.country]} vendors.",
                                     field=path, vendor_request=f"{name}: please provide your {name}"))
    if form.country == "IN" and not form.tax.gstin.strip() and not form.tax.no_gst_declaration:
        findings.append(make_finding(
            "COMP-001", "Neither a GSTIN nor a GST non-registration declaration was provided.", field="tax.gstin",
            vendor_request="GSTIN: please provide your GSTIN, or confirm you are not GST-registered and upload a "
                           "signed non-registration declaration"))

    present = {d.slot for d in ctx.docs}
    required = _required_slots(form, req)
    missing_slots = [s for s in required if s not in present]
    for slot in missing_slots:
        findings.append(make_finding("COMP-002", f"{SLOT_LABELS[slot]} was not uploaded.", field=slot,
                                     vendor_request=f"{SLOT_LABELS[slot]}: {SLOT_REQUESTS[slot]}"))
    if not (form.declarations.information_accurate and form.declarations.consent_to_verification):
        findings.append(make_finding("COMP-004", "Accuracy declaration and consent to verification were not both accepted.",
                                     field="declarations",
                                     vendor_request="Declarations: please confirm the accuracy declaration and consent to verification"))
    checked = len(_required_fields(form.country, form.entity_type, req)) + len(required)
    summary = (f"{checked} requirements checked; {len(missing_fields)} field(s) and {len(missing_slots)} document(s) missing"
               if findings else f"All {checked} required fields and documents present")
    return StageOutcome("flagged" if findings else "passed", summary, findings,
                        {"required_documents": required, "missing_fields": missing_fields, "missing_documents": missing_slots})


# ================================================================ S3 Document understanding
def _log_llm(ctx: RunContext, usage: Usage | None, stage: str, ok: bool, error: str = "", purpose: str = "") -> None:
    usage = usage or Usage(provider=ctx.provider.name, model=getattr(ctx.provider, "model", ""), purpose=purpose)
    with db.session() as conn:
        conn.execute(
            "INSERT INTO llm_calls(ts, submission_id, stage, provider, model, purpose, input_tokens, output_tokens,"
            " latency_ms, ok, error) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (db.now_iso(), ctx.submission_id, stage, usage.provider, usage.model, usage.purpose or purpose,
             usage.input_tokens, usage.output_tokens, usage.latency_ms, int(ok), error))


def _reuse_previous(ctx: RunContext, doc: DocResult) -> bool:
    """A carried-over document already analysed by the same provider is not re-sent (saves tokens)."""
    if not doc.carried_from:
        return False
    prev = db.query_one("SELECT * FROM documents WHERE id = ?", (doc.carried_from,))
    if not prev or prev["provider"] != ctx.provider.name or prev["detected_type"] is None:
        return False
    doc.detected_type, doc.type_confidence = prev["detected_type"], prev["type_confidence"] or 0.0
    doc.readable = bool(prev["readable"])
    doc.fields = {k: ExtractedField(**v) for k, v in json.loads(prev["fields_json"] or "{}").items()}
    doc.provider, doc.notes = prev["provider"], f"reused analysis from {prev['submission_id']}"
    return True


def _doc_confidence(doc: DocResult) -> tuple[float, list[str]]:
    """Document confidence = the weakest of: type confidence and each key field's confidence.

    A key field that was not found at all counts as confidence 0, so it can never pass silently.
    """
    keys = KEY_FIELDS.get(doc.detected_type, ())
    conf = {k: (doc.fields[k].confidence if k in doc.fields and doc.fields[k].value else 0.0) for k in keys}
    weak = [k for k, c in conf.items() if c < threshold("doc_confidence_min")]
    return round(min([doc.type_confidence, *conf.values()]), 2), weak


def _normalise_dates(doc: DocResult, us_format: bool) -> None:
    """Rules need ISO dates whatever the provider returned; an unparseable date becomes a weak field, not a skip."""
    for name, f in list(doc.fields.items()):
        if name not in DATE_FIELDS or not f.value:
            continue
        iso = to_iso_date(f.value, us_format)
        if iso:
            doc.fields[name] = f.model_copy(update={"value": iso})
        else:
            doc.fields[name] = f.model_copy(update={"confidence": 0.0})
            doc.notes = f"{doc.notes} Unrecognised date in {name}: {f.value!r}.".strip()


def s3_documents(ctx: RunContext) -> StageOutcome:
    findings, degraded, rows = [], False, []
    for doc in ctx.docs:
        slot_label = SLOT_LABELS.get(doc.slot, doc.slot)
        content = read_document(Path(doc.path), max_pages=config.max_pages_per_doc())
        if content.error:
            findings.append(make_finding("DOC-002", f"{doc.filename}: {content.error}", field=doc.slot,
                                         evidence={"file": doc.filename},
                                         vendor_request=f"{slot_label}: the file could not be opened; please upload a PDF, JPG or PNG"))
            rows.append(doc)
            continue
        if not _reuse_previous(ctx, doc):
            try:
                result, usage = ctx.provider.understand_document(content, list(SLOTS.get(doc.slot, ())))
                _log_llm(ctx, usage, "S3", True, purpose="document")
            except LLMError as exc:
                _log_llm(ctx, None, "S3", False, str(exc), purpose="document")
                degraded = True
                doc.notes = f"degraded: {exc}"
                findings.append(make_finding("DOC-004", f"{doc.filename}: document understanding failed ({exc}). "
                                             "Treated as unread.", field=doc.slot, evidence={"error": str(exc)}))
                rows.append(doc)
                continue
            doc.detected_type, doc.type_confidence = result.document_type, result.type_confidence
            doc.readable, doc.provider = result.readable, ctx.provider.name
            doc.fields = {f.name: f for f in result.fields}
            doc.notes = result.notes
            values = {k: f.value for k, f in doc.fields.items()}
            _normalise_dates(doc, us_format=month_first(doc.detected_type, values, ctx.draft.form.country))
            if result.suspicious_instructions:
                doc.notes = (doc.notes + " LLM flagged instruction-like text.").strip()

        injected = find_injection(content.text)
        if injected or "instruction-like" in doc.notes:
            findings.append(make_finding("DOC-005", f"{doc.filename} contains text addressed to an AI or reviewer. "
                                         "It was treated as data and ignored.", field=doc.slot,
                                         evidence={"lines": injected[:3] or ["(flagged by the LLM)"]}))
        if not doc.readable:
            findings.append(make_finding(
                "DOC-002", f"{doc.filename} could not be read ({doc.notes or 'unreadable'}).", field=doc.slot,
                evidence={"file": doc.filename, "kind": content.kind, "has_text_layer": content.has_text},
                vendor_request=f"{slot_label}: we could not read the file you uploaded; please upload a clear, "
                               f"complete copy (a digital PDF is best)"))
        elif doc.detected_type not in SLOTS.get(doc.slot, ()):
            findings.append(make_finding(
                "DOC-001", f"The file uploaded as {slot_label} looks like a {label(doc.detected_type)} "
                           f"(confidence {doc.type_confidence:.2f}).", field=doc.slot,
                evidence={"file": doc.filename, "expected": list(SLOTS.get(doc.slot, ())), "detected": doc.detected_type},
                vendor_request=f"{slot_label}: the file uploaded for this item appears to be a "
                               f"{label(doc.detected_type)}; {SLOT_REQUESTS.get(doc.slot, 'please upload the correct document')}"))
        else:
            doc.accepted = True
            doc.confidence, weak = _doc_confidence(doc)
            if doc.confidence < threshold("doc_confidence_min"):
                findings.append(make_finding(
                    "DOC-003", f"{doc.filename}: key field(s) {', '.join(weak) or 'document type'} read with low "
                               f"confidence ({doc.confidence:.2f}).", field=doc.slot,
                    evidence={"confidence": doc.confidence, "weak_fields": weak},
                    vendor_request=f"{slot_label}: some details ({', '.join(weak) or 'the document'}) could not be read "
                                   f"clearly; please upload a clearer copy"))
        rows.append(doc)

    with db.session() as conn:
        for d in rows:
            conn.execute(
                "UPDATE documents SET detected_type=?, type_confidence=?, confidence=?, readable=?, accepted=?,"
                " fields_json=?, provider=?, notes=? WHERE id=?",
                (d.detected_type or None, d.type_confidence, d.confidence, int(d.readable), int(d.accepted),
                 json.dumps({k: v.model_dump() for k, v in d.fields.items()}), d.provider or ctx.provider.name,
                 d.notes, d.doc_id))
    accepted = sum(d.accepted for d in ctx.docs)
    status = "degraded" if degraded else ("flagged" if findings else "passed")
    summary = f"{len(ctx.docs)} document(s) analysed; {accepted} accepted"
    if degraded:
        failed = sum(f.rule_id == "DOC-004" for f in findings)
        summary += f" (the document-reading service did not answer for {failed} document(s))"
    return StageOutcome(status, summary, findings, {
        "provider": ctx.provider.name, "model": getattr(ctx.provider, "model", ""),
        "documents": [{"slot": d.slot, "filename": d.filename, "detected_type": d.detected_type,
                       "type_confidence": d.type_confidence, "confidence": d.confidence, "accepted": d.accepted,
                       "notes": d.notes,
                       "fields": {k: {"value": v.value, "confidence": v.confidence, "evidence": v.evidence}
                                  for k, v in d.fields.items() if v.value}}
                      for d in ctx.docs]})
