"""S4 Format, S5 Consistency (+ simulated registry), S6 Duplicates & fraud, S7 Sanctions.

All deterministic. The only LLM touch-point is adjudicating borderline name pairs in S5,
and even then the verdict only selects which rule fires; it never sets a status.
"""
from __future__ import annotations

import re
from datetime import date

from core import db, sanctions
from core.documents.types import label as doc_label
from core.llm.base import LLMError
from core.models import COUNTRY_NAMES, ENTITY_LABELS
from core.names import compare_names, normalise
from core.pipeline.context import RunContext, StageOutcome
from core.pipeline.stages_intake import _log_llm
from core.reference.gst_states import canonical_state
from core.rules import make_finding, threshold
from core.validators import india, uk, us
from core.validators.common import compact

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ================================================================ S4 Format and checksum
def _check(ctx: RunContext, findings: list, rule_id: str, key: str, label: str, value: str, result, path: str,
           soft_rule: str | None = None) -> None:
    """Record a validator result; store the normalised value for later stages."""
    ctx.valid[key] = result.ok
    ctx.norm[key] = result.normalized
    if result.ok and not result.reason:
        return
    if result.ok and result.soft:  # e.g. unknown bank code: passes, nothing to flag
        return
    rule = soft_rule if (result.soft and soft_rule) else rule_id
    findings.append(make_finding(rule, f"{label} '{value}': {result.reason}.", field=path,
                                 evidence={"value": value, "reason": result.reason},
                                 vendor_request=f"{label}: '{value}' looks incorrect ({result.reason}); please check and correct it"))


def s4_formats(ctx: RunContext) -> StageOutcome:
    form, findings, checked = ctx.form, [], 0
    tax, bank = form.tax, form.bank

    def run(rule_id, key, label, value, validator, path, soft_rule=None):
        nonlocal checked
        if value.strip():
            checked += 1
            _check(ctx, findings, rule_id, key, label, value, validator(value), path, soft_rule)

    if form.country == "IN":
        run("FMT-PAN", "pan", "PAN", tax.pan, india.validate_pan, "tax.pan")
        run("FMT-GSTIN", "gstin", "GSTIN", tax.gstin, india.validate_gstin, "tax.gstin")
        run("FMT-IFSC", "ifsc", "IFSC", bank.ifsc, india.validate_ifsc, "bank.ifsc")
        run("FMT-ACCT", "account", "Account number", bank.account_number, india.validate_in_account, "bank.account_number")
        if ctx.valid.get("ifsc") and bank.bank_name:
            bank_check = india.check_ifsc_bank(bank.ifsc, bank.bank_name)
            checked += 1
            if not bank_check.ok:
                findings.append(make_finding("FMT-IFSC-BANK", bank_check.reason + ".", field="bank.ifsc",
                                             evidence={"ifsc": bank.ifsc, "bank_name": bank.bank_name},
                                             vendor_request=f"IFSC code: {bank_check.reason}; please check the IFSC and bank name"))
        # The CIN/LLPIN is read from the incorporation certificate (it is not a form field).
        inc = ctx.doc("incorporation_certificate")
        cin = inc.value("cin") if inc else ""
        is_llpin = bool(re.fullmatch(r"[A-Z]{3}-?\d{4}", cin.strip().upper()))
        if cin and not is_llpin:
            run("FMT-CIN", "cin", "CIN", cin, india.validate_cin, "incorporation_certificate")
    elif form.country == "US":
        run("FMT-EIN", "ein", "EIN", tax.ein, us.validate_ein, "tax.ein")
        run("FMT-ABA", "routing", "Routing number", bank.routing_number, us.validate_aba, "bank.routing_number")
        run("FMT-ACCT", "account", "Account number", bank.account_number, us.validate_us_account, "bank.account_number")
    elif form.country == "GB":
        run("FMT-SORT", "sort_code", "Sort code", bank.sort_code, uk.validate_sort_code, "bank.sort_code")
        run("FMT-ACCT", "account", "Account number", bank.account_number, uk.validate_uk_account,
            "bank.account_number", soft_rule="FMT-ACCT-REVIEW")
        run("FMT-CRN", "company_number", "Company number", tax.company_number, uk.validate_company_number, "tax.company_number")
        run("FMT-VAT", "vat", "VAT number", tax.vat_number, uk.validate_uk_vat, "tax.vat_number", soft_rule="FMT-VAT")
    if form.contact.email.strip():
        checked += 1
        if not EMAIL_RE.match(form.contact.email.strip()):
            findings.append(make_finding("FMT-EMAIL", f"Contact email '{form.contact.email}' is not a valid address.",
                                         field="contact.email", vendor_request="Contact email: please provide a valid email address"))
    summary = f"{checked} format/checksum checks; {len(findings)} problem(s)" if findings else f"{checked} format/checksum checks passed"
    return StageOutcome("flagged" if findings else "passed", summary, findings,
                        {"normalised": ctx.norm, "valid": ctx.valid})


# ================================================================ S5 Consistency
def _adjudicate(ctx: RunContext, a: str, b: str, what: str):
    """Fuzzy band, with the LLM asked only for the ambiguous middle band."""
    cmp = compare_names(a, b, threshold("name_match"), threshold("name_ambiguous"))
    verdict = None
    if cmp.band == "ambiguous":
        try:
            v, usage = ctx.provider.adjudicate_names(a, b, what)
            _log_llm(ctx, usage, "S5", True, purpose="names")
            verdict = v
        except LLMError as exc:
            _log_llm(ctx, None, "S5", False, str(exc), purpose="names")
    band = cmp.band
    if verdict and verdict.same_entity == "yes":
        band = "match"
    elif verdict and verdict.same_entity == "no":
        band = "mismatch"
    return band, cmp, verdict


def _name_finding(ctx, findings, band, cmp, verdict, rule_mismatch, what, source):
    evidence = {"a": cmp.a, "b": cmp.b, "score": cmp.score, "note": cmp.note, "source": source,
                "adjudication": verdict.model_dump() if verdict else None,
                "adjudicator": ctx.provider.name if verdict else None}
    if band == "mismatch":
        findings.append(make_finding(rule_mismatch, f"{what}: '{cmp.a}' vs '{cmp.b}' on {source} (similarity {cmp.score:.0f}).",
                                     field="legal_name", evidence=evidence))
    elif band == "ambiguous":
        why = verdict.reason if verdict else "adjudicator unavailable"
        findings.append(make_finding("CON-006", f"{what}: '{cmp.a}' vs '{cmp.b}' on {source} is ambiguous "
                                     f"(similarity {cmp.score:.0f}; {why}).", field="legal_name", evidence=evidence))


def _row(field: str, label: str, sources: dict, kind: str = "id") -> dict:
    """One row of the field x source table. Status compares every non-empty value."""
    values = {k: v for k, v in sources.items() if v}
    if len(values) < 2:
        status = "single source"
    elif kind == "name":
        base = next(iter(values.values()))
        status = "match" if all(compare_names(base, v).band == "match" for v in values.values()) else "mismatch"
    else:
        status = "match" if len({compact(v) for v in values.values()}) == 1 else "mismatch"
    return {"field": field, "label": label, "sources": sources, "status": status}


def _foreign_ids(form) -> list[str]:
    tax = form.tax
    if form.country == "IN":
        return [n for n, v in (("EIN", tax.ein), ("UK company number", tax.company_number)) if v.strip()]
    if form.country == "US":
        return [n for n, v in (("GSTIN", tax.gstin), ("PAN", tax.pan), ("UK company number", tax.company_number)) if v.strip()]
    if form.country == "GB":
        return [n for n, v in (("GSTIN", tax.gstin), ("PAN", tax.pan), ("EIN", tax.ein)) if v.strip()]
    return []


def s5_consistency(ctx: RunContext) -> StageOutcome:
    form, findings = ctx.form, []
    tax, bank = form.tax, form.bank
    country_name = COUNTRY_NAMES.get(form.country, form.country)

    # --- tax ID type vs country
    foreign = _foreign_ids(form)
    if foreign:
        own = {"IN": "PAN and GSTIN", "US": "EIN", "GB": "Companies House company number"}.get(form.country, "local tax ID")
        findings.append(make_finding("CON-001", f"Vendor is in {country_name} but supplied {', '.join(foreign)}.",
                                     field="tax", evidence={"country": form.country, "foreign_ids": foreign},
                                     vendor_request=f"Tax ID: you supplied {', '.join(foreign)}, which does not apply to a "
                                                    f"{country_name} company; please provide your {own} instead"))
    if bank.bank_country and form.country and bank.bank_country != form.country:
        findings.append(make_finding("CON-010", f"Bank account is in {bank.bank_country}, vendor is in {form.country}.",
                                     field="bank.bank_country",
                                     vendor_request=f"Bank account: please provide an account held in {country_name}"))

    # --- India: PAN / GSTIN internal consistency
    if form.country == "IN":
        if ctx.valid.get("gstin") and ctx.valid.get("pan"):
            embedded = india.gstin_embedded_pan(ctx.norm["gstin"])
            if embedded != ctx.norm["pan"]:
                findings.append(make_finding(
                    "CON-002", f"GSTIN {ctx.norm['gstin']} embeds PAN {embedded}, but the declared PAN is {ctx.norm['pan']}.",
                    field="tax.gstin", evidence={"gstin": ctx.norm["gstin"], "embedded_pan": embedded, "declared_pan": ctx.norm["pan"]},
                    vendor_request="PAN and GSTIN: please confirm the PAN registered against your GSTIN and attach your "
                                   "GST registration certificate"))
            state = india.gstin_state(ctx.norm["gstin"])
            declared_state = canonical_state(form.address.state or "")
            if declared_state and state and declared_state != state:
                findings.append(make_finding("CON-003", f"GSTIN is registered in {state}; address is in {form.address.state}.",
                                             field="address.state", evidence={"gstin_state": state, "address_state": form.address.state}))
        if ctx.valid.get("pan") and form.entity_type in india.ENTITY_TO_PAN_LETTERS:
            if not india.pan_matches_entity(ctx.norm["pan"], form.entity_type):
                holder = india.pan_holder_type(ctx.norm["pan"])
                findings.append(make_finding(
                    "CON-004", f"PAN {ctx.norm['pan']} is issued to a '{holder}' (4th letter '{ctx.norm['pan'][3]}'), "
                               f"but the vendor is declared as '{ENTITY_LABELS[form.entity_type]}'.",
                    field="tax.pan", evidence={"pan": ctx.norm["pan"], "pan_holder_type": holder, "declared_entity": form.entity_type},
                    vendor_request=f"PAN: please confirm the PAN issued to your {ENTITY_LABELS[form.entity_type].lower()} "
                                   "and attach a copy of the PAN card"))

    # --- field x source comparison (IDs must be identical everywhere)
    pan_card, gst, bank_doc = ctx.doc("pan_card"), ctx.doc("gst_certificate"), ctx.bank_doc()
    inc, uk_cert, w9, nogst = (ctx.doc("incorporation_certificate"), ctx.doc("company_registration_certificate"),
                               ctx.doc("w9"), ctx.doc("no_gst_declaration"))
    id_checks = [
        ("tax.pan", "PAN", tax.pan, [(pan_card, "pan"), (nogst, "pan")]),
        ("tax.gstin", "GSTIN", tax.gstin, [(gst, "gstin")]),
        ("tax.ein", "EIN", tax.ein, [(w9, "ein")]),
        ("tax.company_number", "Company number", tax.company_number, [(uk_cert, "company_number")]),
        ("bank.account_number", "Account number", bank.account_number, [(bank_doc, "account_number")]),
        ("bank.ifsc", "IFSC", bank.ifsc, [(bank_doc, "ifsc")]),
        ("bank.routing_number", "Routing number", bank.routing_number, [(bank_doc, "routing_number")]),
        ("bank.sort_code", "Sort code", bank.sort_code, [(bank_doc, "sort_code")]),
    ]
    for path, label, form_val, doc_sources in id_checks:
        sources = {"form": form_val}
        for doc, fname in doc_sources:
            if doc and doc.value(fname):
                sources[doc_label(doc.detected_type)] = doc.value(fname)
                if form_val and compact(doc.value(fname)) != compact(form_val):
                    findings.append(make_finding(
                        "CON-009", f"{label} on the {doc_label(doc.detected_type)} ({doc.value(fname)}) differs from the form ({form_val}).",
                        field=path, evidence={"form": form_val, "document": doc.value(fname), "document_type": doc.detected_type},
                        vendor_request=f"{label}: the {label} on your {doc_label(doc.detected_type)} ({doc.value(fname)}) "
                                       f"does not match the form ({form_val}); please correct whichever is wrong"))
        if any(v for k, v in sources.items()):
            ctx.comparison.append(_row(path, label, sources))
    # The PAN embedded in the GSTIN is one more source for the PAN row (this is what exposes E1).
    gstin_for_pan = (gst.value("gstin") if gst else "") or (tax.gstin if ctx.valid.get("gstin") else "")
    if gstin_for_pan and form.country == "IN":
        pan_row = next(r for r in ctx.comparison if r["field"] == "tax.pan")
        pan_row["sources"]["GSTIN (chars 3-12)"] = india.gstin_embedded_pan(gstin_for_pan)
        ctx.comparison[ctx.comparison.index(pan_row)] = _row("tax.pan", "PAN", pan_row["sources"])

    # --- legal name across sources
    name_sources = [(gst, "legal_name"), (pan_card, "name"), (inc, "company_name"), (uk_cert, "company_name"),
                    (w9, "name"), (nogst, "legal_name")]
    names = {"form": form.legal_name}
    for doc, fname in name_sources:
        if doc and doc.value(fname):
            src = doc_label(doc.detected_type)
            names[src] = doc.value(fname)
            band, cmp, verdict = _adjudicate(ctx, form.legal_name, doc.value(fname), "legal name on form vs document")
            _name_finding(ctx, findings, band, cmp, verdict, "CON-005", "Legal name differs", src)
    ctx.comparison.append(_row("legal_name", "Legal name", names, kind="name"))

    # --- bank account holder must be the vendor (legal or trade name)
    holders = {"form": bank.account_holder}
    if bank_doc and bank_doc.value("account_holder"):
        holders[doc_label(bank_doc.detected_type)] = bank_doc.value("account_holder")
    # The same holder name on the form and the cheque is one problem, not two: group by name.
    by_name: dict[str, list[str]] = {}
    for src, holder in holders.items():
        if holder:
            by_name.setdefault(normalise(holder), []).append(src)
    rank = ["mismatch", "ambiguous", "match"]
    for sources in by_name.values():
        holder = holders[sources[0]]
        best = None
        for candidate in [n for n in (form.legal_name, form.trade_name) if n]:
            result = _adjudicate(ctx, holder, candidate, "bank account holder vs vendor name")
            if best is None or rank.index(result[0]) > rank.index(best[0]):
                best = result
        if best:
            _name_finding(ctx, findings, best[0], best[1], best[2], "CON-007", "Account holder differs from vendor name",
                          " and ".join(sources))
    ctx.comparison.append(_row("bank.account_holder", "Account holder", holders, kind="name"))

    # --- bank letter freshness (relative to the submission date)
    letter = ctx.doc("bank_letter")
    if letter and letter.value("letter_date"):
        try:
            issued = date.fromisoformat(letter.value("letter_date"))
            age = (ctx.submitted_at.date() - issued).days
            max_age = int(threshold("bank_letter_max_age_days"))
            if age > max_age or age < 0:
                what = f"{age} days old" if age > 0 else "dated in the future"
                findings.append(make_finding(
                    "CON-008", f"Bank letter dated {issued} is {what} (max {max_age} days).", field="bank_letter",
                    evidence={"letter_date": str(issued), "age_days": age},
                    vendor_request=f"Bank letter: the letter you sent is dated {issued:%d %b %Y}; please upload one "
                                   f"issued within the last {max_age} days"))
        except ValueError:
            pass

    # --- SIMULATED registry lookups
    registry_notes = _registry_checks(ctx, findings)
    total = len(findings)
    return StageOutcome("flagged" if findings else "passed",
                        f"Cross-checked {len(ctx.comparison)} fields across sources; {total} inconsistenc{'y' if total == 1 else 'ies'}"
                        if findings else f"Cross-checked {len(ctx.comparison)} fields across sources; all consistent",
                        findings, {"comparison": ctx.comparison, "registry": registry_notes})


def _registry_checks(ctx: RunContext, findings: list) -> dict:
    form, reg = ctx.form, ctx.registry
    notes = {"label": reg.label, "simulated": reg.simulated}
    if form.country == "IN" and ctx.valid.get("gstin"):
        record = reg.lookup_gstin(ctx.norm["gstin"])
        notes["gstin"] = record
        if record is None:
            findings.append(make_finding("REG-004", f"GSTIN {ctx.norm['gstin']} not found in the simulated registry.",
                                         field="tax.gstin", evidence={"registry": reg.label}))
        else:
            if record["status"].lower() != "active":
                findings.append(make_finding("REG-001", f"GSTIN {ctx.norm['gstin']} status is '{record['status']}' (simulated registry).",
                                             field="tax.gstin", evidence={"record": record, "registry": reg.label}))
            band, cmp, verdict = _adjudicate(ctx, form.legal_name, record["legal_name"], "legal name on form vs GST registry")
            _name_finding(ctx, findings, band, cmp, verdict, "REG-002", "Registry legal name differs", "simulated GST registry")
    code = {"IN": form.bank.ifsc, "US": form.bank.routing_number, "GB": form.bank.sort_code}.get(form.country, "")
    code_key = {"IN": "ifsc", "US": "routing", "GB": "sort_code"}.get(form.country, "")
    if code and ctx.valid.get(code_key) and ctx.valid.get("account"):
        record = reg.verify_bank_account(ctx.norm[code_key], ctx.norm["account"])
        notes["bank"] = record
        if record is None:
            findings.append(make_finding("REG-004", "Bank account not found in the simulated bank verification service.",
                                         field="bank.account_number", evidence={"registry": reg.label}))
        else:
            best = None
            for candidate in [n for n in (form.legal_name, form.trade_name) if n]:
                result = _adjudicate(ctx, record["holder_name"], candidate, "bank's account holder vs vendor name")
                if best is None or result[1].score > best[1].score:
                    best = result
            if best:
                _name_finding(ctx, findings, best[0], best[1], best[2], "REG-003",
                              "Bank reports a different account holder", "simulated bank verification")
    return notes


# ================================================================ S6 Duplicates, vendor master, fraud patterns
SENSITIVE = ["bank.account_number", "bank.ifsc", "bank.routing_number", "bank.sort_code", "bank.account_holder",
             "tax.pan", "tax.gstin", "tax.ein", "tax.company_number"]


def _flatten(form_dict: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in form_dict.items():
        if k == "documents":
            continue
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def s6_duplicates(ctx: RunContext) -> StageOutcome:
    form, findings = ctx.form, []
    vendors = db.query("SELECT * FROM vendors WHERE status = 'approved'")
    ids = {"PAN": ("pan", ctx.norm.get("pan") or compact(form.tax.pan)),
           "GSTIN": ("gstin", ctx.norm.get("gstin") or compact(form.tax.gstin)),
           "EIN": ("ein", ctx.norm.get("ein") or form.tax.ein),
           "Company number": ("company_number", ctx.norm.get("company_number") or compact(form.tax.company_number))}
    bank_code = {"IN": form.bank.ifsc, "US": form.bank.routing_number, "GB": form.bank.sort_code}.get(form.country, "")
    matched_vendor_ids = set()
    for v in vendors:
        hits = [(label, val) for label, (col, val) in ids.items() if val and compact(v[col] or "") == compact(val)]
        if form.bank.account_number and v["account_number"] == form.bank.account_number.strip() \
                and compact(v["bank_code"] or "") == compact(bank_code):
            hits.append(("Bank account", f"{bank_code} / {form.bank.account_number}"))
        if not hits:
            continue
        matched_vendor_ids.add(v["vendor_id"])
        same = max(compare_names(form.legal_name, v["legal_name"]).score,
                   compare_names(form.trade_name or form.legal_name, v["trade_name"] or v["legal_name"]).score)
        evidence = {"vendor_id": v["vendor_id"], "vendor_name": v["legal_name"], "shared": [h[0] for h in hits],
                    "values": dict(hits), "name_similarity": same}
        if same >= threshold("name_match"):
            findings.append(make_finding("FRD-006", f"Already onboarded as {v['vendor_id']} ({v['legal_name']}); "
                                         f"shared: {', '.join(h[0] for h in hits)}.", evidence=evidence))
        else:
            findings.append(make_finding("FRD-001", f"{', '.join(h[0] for h in hits)} already belongs to approved vendor "
                                         f"{v['vendor_id']} '{v['legal_name']}', a different legal name.", evidence=evidence))
    for v in vendors:
        if v["vendor_id"] in matched_vendor_ids:
            continue
        cmp = compare_names(form.legal_name, v["legal_name"])
        if cmp.score >= threshold("duplicate_name_similarity") and v["account_number"] != form.bank.account_number.strip():
            findings.append(make_finding("FRD-002", f"Name is {cmp.score:.0f}% similar to existing vendor {v['vendor_id']} "
                                         f"'{v['legal_name']}', which has different bank details.",
                                         evidence={"vendor_id": v["vendor_id"], "vendor_name": v["legal_name"], "score": cmp.score}))

    # --- resubmission: what changed, and was it asked for?
    diff = []
    if ctx.parent:
        before, after = _flatten(ctx.parent["form"]), _flatten(form.model_dump())
        requested = {f["field"] for f in ctx.parent["findings"] if f["field"]}
        for key in sorted(set(before) | set(after)):
            if str(before.get(key, "")).strip() != str(after.get(key, "")).strip():
                diff.append({"field": key, "before": before.get(key, ""), "after": after.get(key, ""),
                             "requested": key in requested})
        replaced = [d.slot for d in ctx.docs if not d.carried_from]
        unrequested = [d for d in diff if d["field"] in SENSITIVE and not d["requested"]]
        for d in unrequested:
            findings.append(make_finding("FRD-003", f"{d['field']} changed from '{d['before']}' to '{d['after']}' on resubmission, "
                                         "although it was not one of the items requested.", field=d["field"],
                                         evidence={"before": d["before"], "after": d["after"], "previous_submission": ctx.parent["id"]}))
        chain = db.query("SELECT status FROM submissions WHERE chain_id = ? AND id != ?", (ctx.chain_id, ctx.submission_id))
        ctx.failed_resubmissions = sum(1 for r in chain if r["status"] != "APPROVED")
        if ctx.failed_resubmissions > ctx.policy["reject"]["max_failed_resubmissions"]:
            findings.append(make_finding("POL-001", f"{ctx.failed_resubmissions} earlier attempts did not pass.",
                                         evidence={"failed_attempts": ctx.failed_resubmissions}))
    else:
        replaced = []

    # --- contact email domain
    email = form.contact.email.strip().lower()
    domain = email.split("@")[-1] if "@" in email else ""
    site = re.sub(r"^https?://", "", form.website.strip().lower()).split("/")[0].removeprefix("www.")
    if domain:
        if domain in ctx.policy["free_email_domains"] and form.entity_type in ("company", "llp_partnership"):
            findings.append(make_finding("FRD-004", f"Contact email uses the free domain '{domain}' for a registered business.",
                                         field="contact.email", evidence={"email": email},
                                         vendor_request="Contact email: please provide a contact address on your company's own domain"))
        elif site and not (domain == site or domain.endswith("." + site) or site.endswith("." + domain)):
            findings.append(make_finding("FRD-005", f"Email domain '{domain}' does not match website '{site}'.",
                                         field="contact.email", evidence={"email_domain": domain, "website": site}))
    summary = (f"Compared with {len(vendors)} approved vendors; {len(findings)} flag(s)" if findings
               else f"Compared with {len(vendors)} approved vendors; no duplicates or fraud patterns")
    return StageOutcome("flagged" if findings else "passed", summary, findings,
                        {"vendors_compared": len(vendors), "diff": diff, "replaced_documents": replaced,
                         "failed_resubmissions": ctx.failed_resubmissions})


# ================================================================ S7 Sanctions
def s7_sanctions(ctx: RunContext) -> StageOutcome:
    form, findings = ctx.form, []
    meta = sanctions.snapshot_meta()
    strong, possible = threshold("sanctions_strong"), threshold("sanctions_possible")
    screened = {n.strip() for n in (form.legal_name, form.trade_name, form.bank.account_holder) if n.strip()}
    hits_out, seen = [], set()
    for name in sorted(screened):
        for hit in sanctions.screen(name, review_threshold=possible):
            key = (hit.entry.list_name, hit.entry.ent_num)
            if key in seen:
                continue
            seen.add(key)
            e = hit.entry
            evidence = {"screened_name": name, "listed_name": e.display, "list": e.list_name, "ent_num": e.ent_num,
                        "program": e.program, "type": e.sdn_type, "alias": e.is_alias, "score": round(hit.score, 1),
                        "list_date": meta.get("publish_date")}
            hits_out.append(evidence)
            if e.list_name != "SDN":
                rule = "SAN-003"
            elif hit.score >= strong:
                rule = "SAN-001"
            else:
                rule = "SAN-002"
            findings.append(make_finding(rule, f"'{name}' resembles '{e.display}' ({e.list_name}, program {e.program or 'n/a'}) "
                                         f"with score {hit.score:.0f}.", evidence=evidence))
    details = {"screened_names": sorted(screened), "hits": hits_out, "list_publish_date": meta.get("publish_date"),
               "record_count": meta.get("record_count"), "coverage": "US OFAC lists only (SDN + consolidated non-SDN)",
               "thresholds": {"strong": strong, "possible": possible}}
    summary = (f"Screened {len(screened)} name(s) against OFAC lists of {meta.get('publish_date')}; {len(findings)} potential match(es)"
               if findings else f"Screened {len(screened)} name(s) against OFAC lists of {meta.get('publish_date')}; no matches")
    return StageOutcome("flagged" if findings else "passed", summary, findings, details)
