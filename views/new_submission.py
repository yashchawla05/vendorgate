"""Vendor portal: submit a vendor (form + documents), load a demo scenario, or upload API-format JSON.

Every path builds the same SubmissionDraft and hands it to the Live Run page, which runs
the real pipeline. Demo scenarios are just pre-filled inputs read from data/scenarios/;
form samples (data/form_samples/) only fill in the form's fields and attach files, and the
vendor can still edit, detach or replace anything before submitting.
"""
from pathlib import Path

import streamlit as st

from core.documents.types import SLOT_LABELS
from core.models import COUNTRY_NAMES, ENTITY_LABELS, SubmissionForm
from core.pipeline.context import SubmissionDraft
from core.rules import policy
from core.submissions import draft_from_folder, list_form_samples, list_scenarios
from ui.theme import page_header, status_chip
from ui.widgets import SUB_STATUS, esc

page_header("New submission", "Vendor portal · company, tax and bank details plus supporting documents.")

GST_OPTIONS = ["Registered (I have a GSTIN)", "Not registered (below threshold)"]
CURRENCY = {"IN": "INR", "US": "USD", "GB": "GBP"}
SAMPLES = {s["id"]: s for s in list_form_samples()}


def start_run(draft: SubmissionDraft) -> None:
    st.session_state["pending_draft"] = draft
    st.switch_page("views/live_run.py")


def expected_html(expect: dict) -> str:
    return status_chip(expect["status"]) + (f" <span class='vg-muted'>{esc(SUB_STATUS[expect['sub_status']])}</span>"
                                            if expect.get("sub_status") else "")


def sample_form(sample_id: str) -> SubmissionForm | None:
    sample = SAMPLES.get(sample_id or "")
    return SubmissionForm.model_validate_json((Path(sample["folder"]) / "submission.json").read_text()) if sample else None


def widget_values(form: SubmissionForm) -> dict:
    """Form-tab widget values that reproduce `form` (the inverse of the mapping on submit)."""
    country = form.country
    values = {
        "f_legal_name": form.legal_name, "f_trade_name": form.trade_name, "f_website": form.website,
        "f_line1": form.address.line1, "f_city": form.address.city, "f_state": form.address.state,
        "f_postal": form.address.postal_code, "f_contact_name": form.contact.name, "f_email": form.contact.email,
        "f_phone": form.contact.phone, "f_pan": form.tax.pan, "f_gstin": form.tax.gstin, "f_ein": form.tax.ein,
        "f_company_number": form.tax.company_number, "f_vat": form.tax.vat_number,
        "f_holder": form.bank.account_holder, "f_account": form.bank.account_number, "f_bank_name": form.bank.bank_name,
        "f_accurate": form.declarations.information_accurate, "f_consent": form.declarations.consent_to_verification,
        "f_gst": GST_OPTIONS[1] if form.tax.no_gst_declaration else GST_OPTIONS[0],
    }
    if country in COUNTRY_NAMES:
        values["f_country"] = country
        values[f"f_bank_code_{country}"] = {"IN": form.bank.ifsc, "US": form.bank.routing_number,
                                            "GB": form.bank.sort_code}[country]
        values[f"f_currency_{country}"] = form.bank.currency or CURRENCY[country]
    if form.entity_type in ENTITY_LABELS:
        values["f_entity"] = form.entity_type
    values.update({f"f_use_{d.slot}": True for d in form.documents})
    return values


def load_sample() -> None:
    """on_change of the sample picker: fill every field from the sample, or clear them for a blank form."""
    form = sample_form(st.session_state["f_sample"])
    if form is None:  # blank form: keep the chosen country and entity, empty everything else
        form = SubmissionForm(country=st.session_state.get("f_country", "IN"),
                              entity_type=st.session_state.get("f_entity", "company"))
    st.session_state.update(widget_values(form))
    st.session_state["f_upload_round"] = st.session_state.get("f_upload_round", 0) + 1  # clears earlier uploads


tab_demo, tab_form, tab_json = st.tabs(["Demo scenarios", "Fill in the form", "Upload JSON (API format)"])

# ---------------------------------------------------------------- demo scenarios
with tab_demo:
    st.caption("Each scenario loads real input files from data/scenarios/ and runs them through the live pipeline. "
               "Nothing is pre-computed: the expected outcome shown is the test oracle, not the result.")
    for sc in list_scenarios():
        first = sc["steps"][0]
        exp_html = expected_html(first["expect"])
        with st.container(border=True):
            left, right = st.columns([5, 1.3], vertical_alignment="center")
            with left:
                st.markdown(f"<div class='vg-scenario'><h4>{esc(sc['title'])}</h4>"
                            f"<div style='font-size:0.9rem'>{esc(sc['story'])}</div>"
                            f"<div style='margin-top:6px' class='vg-muted'>Expected first outcome: {exp_html}"
                            + (" · then the vendor resubmits through the emailed link" if len(sc["steps"]) > 1 else "")
                            + "</div></div>", unsafe_allow_html=True)
            with right:
                if st.button("Run scenario", key=f"run_{sc['id']}", type="primary", width="stretch"):
                    start_run(draft_from_folder(Path(sc["folder"]) / first["dir"], f"scenario:{sc['id']}"))

# ---------------------------------------------------------------- manual form
with tab_form:
    req = policy()["requirements"]
    st.selectbox("Fill in from a sample (optional)", ["", *SAMPLES], key="f_sample", on_change=load_sample,
                 format_func=lambda s: f"{SAMPLES[s]['title']} (expected: {SAMPLES[s]['expect']['status']})" if s
                 else "Blank form: type everything yourself",
                 help="Samples fill in every field and attach their documents from data/form_samples/. "
                      "You can still edit any field, untick a document or upload your own before submitting.")
    sample = SAMPLES.get(st.session_state.get("f_sample") or "")
    if sample:
        st.markdown(f"<div class='vg-muted' style='font-size:0.9rem'>{esc(sample['story'])}<br>Expected outcome: "
                    f"{expected_html(sample['expect'])} (the test oracle, not the result)</div>", unsafe_allow_html=True)
        st.caption("An approved sample becomes a vendor, so running the same sample again is flagged as a duplicate "
                   "(FRD-006). Reset demo data on System health to start clean.")
    c1, c2 = st.columns(2)
    country = c1.selectbox("Country of registration", list(COUNTRY_NAMES), format_func=lambda c: COUNTRY_NAMES[c],
                           key="f_country")
    entity = c2.selectbox("Entity type", list(ENTITY_LABELS), format_func=lambda e: ENTITY_LABELS[e], key="f_entity")
    gst_choice = None
    if country == "IN":
        gst_choice = st.radio("GST registration", GST_OPTIONS, horizontal=True, key="f_gst")
    if f"f_currency_{country}" not in st.session_state:
        st.session_state[f"f_currency_{country}"] = CURRENCY[country]
    form_sample = sample_form(st.session_state.get("f_sample"))
    sample_files = {d.slot: d.filename for d in form_sample.documents} if form_sample else {}
    upload_round = st.session_state.get("f_upload_round", 0)
    with st.form("vendor_form"):
        st.markdown("**Company**")
        a, b = st.columns(2)
        legal_name = a.text_input("Legal name *", key="f_legal_name")
        trade_name = b.text_input("Trade name", key="f_trade_name")
        website = a.text_input("Website", placeholder="https://", key="f_website")
        st.markdown("**Registered address**")
        a, b, c, d = st.columns([3, 1.4, 1.4, 1])
        line1 = a.text_input("Address line *", key="f_line1")
        city = b.text_input("City *", key="f_city")
        state = c.text_input("State / county" + (" *" if country in ("IN", "US") else ""), key="f_state")
        postal = d.text_input("Postal code *", key="f_postal")
        st.markdown("**Contact**")
        a, b, c = st.columns(3)
        contact_name = a.text_input("Contact name *", key="f_contact_name")
        email = b.text_input("Email *", key="f_email")
        phone = c.text_input("Phone", key="f_phone")
        st.markdown("**Tax registration**")
        a, b = st.columns(2)
        pan = gstin = ein = company_number = vat = ""
        if country == "IN":
            pan = a.text_input("PAN *", max_chars=10, key="f_pan")
            if gst_choice and gst_choice.startswith("Registered"):
                gstin = b.text_input("GSTIN *", max_chars=15, key="f_gstin")
        elif country == "US":
            ein = a.text_input("EIN *", placeholder="NN-NNNNNNN", key="f_ein")
        else:
            company_number = a.text_input("Companies House number" + (" *" if entity == "company" else ""),
                                          key="f_company_number")
            vat = b.text_input("VAT number (optional)", key="f_vat")
        st.markdown("**Bank account**")
        a, b, c = st.columns(3)
        holder = a.text_input("Account holder name *", key="f_holder")
        account = b.text_input("Account number *", key="f_account")
        code_label = {"IN": "IFSC *", "US": "ABA routing number *", "GB": "Sort code *"}[country]
        bank_code = c.text_input(code_label, key=f"f_bank_code_{country}")
        bank_name = a.text_input("Bank name *", key="f_bank_name")
        currency = b.text_input("Currency", key=f"f_currency_{country}")

        st.markdown("**Documents** (PDF, JPG or PNG, max 10 MB each)")
        slots = req["documents"].get(country, []) + req["documents"].get(f"{country}_{entity}", [])
        if country == "IN":
            slots.append("gst_certificate" if gst_choice and gst_choice.startswith("Registered") else "no_gst_declaration")
        uploads, use_sample = {}, {}
        for slot in slots:
            uploads[slot] = st.file_uploader(SLOT_LABELS[slot], type=["pdf", "jpg", "jpeg", "png"],
                                             key=f"up_{slot}_{upload_round}")
            if slot in sample_files:
                use_sample[slot] = st.checkbox(f"Attach the sample file {sample_files[slot]} (an upload above "
                                               "replaces it)", key=f"f_use_{slot}")
        st.markdown("**Declarations**")
        accurate = st.checkbox("I confirm the information provided is accurate and complete.", key="f_accurate")
        consent = st.checkbox("I consent to verification of these details, including sanctions screening.",
                              key="f_consent")
        submitted = st.form_submit_button("Submit for verification", type="primary")

    if submitted:
        files = {slot: (f.name, f.getvalue()) for slot, f in uploads.items() if f is not None}
        for slot, attach in use_sample.items():
            if attach and slot not in files:
                files[slot] = (sample_files[slot], (Path(sample["folder"]) / sample_files[slot]).read_bytes())
        form = SubmissionForm.model_validate({
            "legal_name": legal_name, "trade_name": trade_name, "country": country, "entity_type": entity,
            "address": {"line1": line1, "city": city, "state": state, "postal_code": postal},
            "contact": {"name": contact_name, "email": email, "phone": phone}, "website": website,
            "tax": {"pan": pan, "gstin": gstin, "ein": ein, "company_number": company_number, "vat_number": vat,
                    "no_gst_declaration": bool(gst_choice and gst_choice.startswith("Not"))},
            "bank": {"account_holder": holder, "account_number": account, "bank_name": bank_name, "currency": currency,
                     "bank_country": country,
                     "ifsc": bank_code if country == "IN" else "", "routing_number": bank_code if country == "US" else "",
                     "sort_code": bank_code if country == "GB" else ""},
            "declarations": {"information_accurate": accurate, "consent_to_verification": consent},
            "documents": [{"slot": s, "filename": n} for s, (n, _) in files.items()],
        })
        # Incomplete submissions are accepted on purpose: the pipeline itemises what is missing.
        start_run(SubmissionDraft(form=form, files=files, source="portal"))

# ---------------------------------------------------------------- JSON (programmatic)
with tab_json:
    st.caption("Programmatic format: a submission.json matching the SubmissionForm schema, plus the files it "
               "lists in documents[].filename. Example: data/scenarios/happy/initial/submission.json.")
    spec = st.file_uploader("submission.json", type=["json"], key="json_spec")
    files = st.file_uploader("Documents referenced by the JSON", type=["pdf", "jpg", "jpeg", "png"],
                             accept_multiple_files=True, key="json_files")
    with st.expander("JSON schema"):
        st.json(SubmissionForm.model_json_schema(), expanded=False)
    if st.button("Submit JSON", type="primary", disabled=spec is None):
        try:
            form = SubmissionForm.model_validate_json(spec.getvalue())
        except Exception as exc:  # show validation errors to the user instead of crashing
            st.error(f"Invalid submission.json: {exc}")
        else:
            by_name = {f.name: f.getvalue() for f in files or []}
            missing = [d.filename for d in form.documents if d.filename not in by_name]
            if missing:
                st.warning(f"Files listed but not uploaded (they will be reported as missing): {', '.join(missing)}")
            start_run(SubmissionDraft(form=form, source="api",
                                      files={d.slot: (d.filename, by_name[d.filename]) for d in form.documents
                                             if d.filename in by_name}))
