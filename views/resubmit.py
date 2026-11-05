"""Vendor resubmission (hidden page, reached only through the tokenised link in our email).

The vendor sees what we asked for, edits only what is needed, and uploads only the missing
or corrected documents. Everything else carries over from the previous submission. The new
version runs through the full pipeline, which diffs it against the previous one.
"""

import streamlit as st

from core import tokens
from core.config import SCENARIO_DIR
from core.documents.types import SLOT_LABELS
from core.models import SubmissionForm
from core.pipeline.context import SubmissionDraft
from core.submissions import draft_from_folder, get_submission
from ui.theme import page_header
from ui.widgets import esc

page_header("Update your submission", "Vendor portal · secure resubmission link")

# Keep the token for this browser session as well, so reruns (button clicks) never lose it.
token = st.query_params.get("token", "") or st.session_state.get("resubmit_token", "")
parent_id, problem = tokens.resolve(token)
if parent_id:
    st.session_state["resubmit_token"] = token
if not parent_id:
    st.error(problem)
    st.stop()

parent = get_submission(parent_id)
form = SubmissionForm.model_validate(parent["form"])
requests = [f for f in parent["findings"] if f["vendor_request"]]
review_requests = [r for r in parent["reviews"] if r["action"] == "request_info"]

st.markdown(f"**{esc(form.legal_name)}** · reference `{esc(parent_id)}`")
with st.container(border=True):
    st.markdown("**What we need from you**")
    seen = set()
    for f in requests:
        if f["vendor_request"] not in seen:
            seen.add(f["vendor_request"])
            st.markdown(f"- {esc(f['vendor_request'])}")
    for r in review_requests:
        st.markdown(f"- Additional information: {esc(r['reason'])}")
    st.caption("Documents you already sent are kept; upload only what is listed. Do not change bank or tax details "
               "unless we asked for them: unrequested changes are reviewed manually.")

# Demo helper: scenarios ship the vendor's corrected files, so the presenter can resubmit in one click.
scenario_id = parent["source"].split(":", 1)[1] if parent["source"].startswith("scenario:") else ""
fix_dir = SCENARIO_DIR / scenario_id / "resubmit" if scenario_id else None
if fix_dir and (fix_dir / "submission.json").exists():
    with st.container(border=True):
        st.markdown(f"**Demo helper** — load the vendor's corrected files from `data/scenarios/{esc(scenario_id)}/resubmit/` "
                    "and submit them through this link (same pipeline as the form below).")
        if st.button("Submit the scenario's corrected files", type="primary"):
            draft = draft_from_folder(fix_dir, f"scenario:{scenario_id}", parent_id=parent_id, token=token)
            st.session_state["pending_draft"] = draft
            st.switch_page("views/live_run.py")

with st.form("resubmit"):
    st.markdown("**Your details** (pre-filled from your last submission)")
    a, b = st.columns(2)
    legal_name = a.text_input("Legal name", form.legal_name)
    trade_name = b.text_input("Trade name", form.trade_name)
    email = a.text_input("Contact email", form.contact.email)
    st.markdown("**Tax**")
    a, b = st.columns(2)
    pan = a.text_input("PAN", form.tax.pan) if form.country == "IN" else form.tax.pan
    gstin = b.text_input("GSTIN", form.tax.gstin) if form.country == "IN" else form.tax.gstin
    ein = a.text_input("EIN", form.tax.ein) if form.country == "US" else form.tax.ein
    crn = a.text_input("Company number", form.tax.company_number) if form.country == "GB" else form.tax.company_number
    st.markdown("**Bank**")
    a, b, c = st.columns(3)
    holder = a.text_input("Account holder", form.bank.account_holder)
    account = b.text_input("Account number", form.bank.account_number)
    code_field = {"IN": "ifsc", "US": "routing_number", "GB": "sort_code"}.get(form.country, "ifsc")
    code = c.text_input({"ifsc": "IFSC", "routing_number": "Routing number", "sort_code": "Sort code"}[code_field],
                        getattr(form.bank, code_field))
    st.markdown("**Documents to add or replace**")
    slots = list(dict.fromkeys([f["field"] for f in requests if f["field"] in SLOT_LABELS] +
                               [d["slot"] for d in parent["documents"]]))
    uploads = {s: st.file_uploader(SLOT_LABELS[s], type=["pdf", "jpg", "jpeg", "png"], key=f"re_{s}") for s in slots}
    submitted = st.form_submit_button("Submit update", type="primary")

if submitted:
    updated = form.model_copy(deep=True)
    updated.legal_name, updated.trade_name, updated.contact.email = legal_name, trade_name, email
    updated.tax.pan, updated.tax.gstin, updated.tax.ein, updated.tax.company_number = pan, gstin, ein, crn
    updated.bank.account_holder, updated.bank.account_number = holder, account
    setattr(updated.bank, code_field, code)
    files = {s: (f.name, f.getvalue()) for s, f in uploads.items() if f is not None}
    updated.documents = [d for d in updated.documents if d.slot not in files]
    updated = SubmissionForm.model_validate(updated.model_dump() | {
        "documents": [d.model_dump() for d in updated.documents] + [{"slot": s, "filename": n} for s, (n, _) in files.items()]})
    st.session_state["pending_draft"] = SubmissionDraft(form=updated, files=files, source="portal-resubmit",
                                                        parent_id=parent_id, token=token)
    st.switch_page("views/live_run.py")

