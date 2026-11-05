"""Review queue: PENDING submissions, oldest first. Approve / reject / request info, with a mandatory reason."""
from datetime import datetime, timezone

import streamlit as st

from core import review
from core.submissions import get_submission
from ui.theme import page_header
from ui.widgets import SUB_STATUS, decision_banner, esc, findings_by_category

page_header("Review queue", "Submissions waiting on a person. Every action needs a reason and is written to the audit log.")

flash = st.session_state.pop("review_flash", None)
if flash:
    st.success(flash)

which = st.segmented_control("Show", ["Awaiting internal review", "Awaiting vendor", "All pending"],
                             default="Awaiting internal review")
filter_map = {"Awaiting internal review": "awaiting_internal_review", "Awaiting vendor": "awaiting_vendor", "All pending": None}
rows = review.queue(filter_map.get(which or "All pending"))
if not rows:
    st.info("Nothing waiting here.")
    st.stop()

now = datetime.now(timezone.utc)
table = "".join(
    f"<tr><td class='vg-mono'>{esc(r['id'])}</td><td>{esc(r['legal_name'] or '-')}</td>"
    f"<td>{esc(SUB_STATUS.get(r['sub_status'], r['sub_status']))}</td>"
    f"<td style='text-align:right'>{(now - datetime.fromisoformat(r['submitted_at'])).days} d</td>"
    f"<td style='text-align:right'>{r['risk_score']}</td><td class='vg-mono'>{esc(', '.join(r['rules']))}</td></tr>"
    for r in rows)
st.markdown("<table class='vg-table'><thead><tr><th>ID</th><th>Vendor</th><th>Waiting on</th><th style='text-align:right'>Age</th>"
            f"<th style='text-align:right'>Risk</th><th>Rules</th></tr></thead><tbody>{table}</tbody></table>",
            unsafe_allow_html=True)

st.write("")
sid = st.selectbox("Open a submission", [r["id"] for r in rows],
                   format_func=lambda i: next(f"{r['id']} · {r['legal_name']}" for r in rows if r["id"] == i))
sub = get_submission(sid)
decision_banner(sub["status"], sub["sub_status"], sub["decision"]["explanation"] if sub["decision"] else "", sub["risk_score"])
left, right = st.columns([3, 2])
with left:
    findings_by_category(sub["findings"])
    if st.button("Open full detail"):
        st.switch_page("views/submission_detail.py", query_params={"id": sid})
with right:
    with st.form(f"review_{sid}", clear_on_submit=True):
        st.markdown("**Reviewer decision**")
        action = st.radio("Action", list(review.ACTIONS), format_func=review.ACTIONS.get, horizontal=True)
        reviewer = st.text_input("Your name", value=st.session_state.get("reviewer_name", ""))
        reason = st.text_area("Reason (required, recorded in the audit log)",
                              placeholder="e.g. Sanctions hit is a false positive: different country, program and "
                                          "incorporation date.")
        request_text = st.text_area("What to ask the vendor (for 'Request information')",
                                    placeholder="e.g. Please send a board resolution confirming the change of bank account.")
        go = st.form_submit_button("Record decision", type="primary")
    if go:
        st.session_state["reviewer_name"] = reviewer
        try:
            result = review.apply_review(sid, action, reason, reviewer, request_text)
        except ValueError as exc:
            st.error(str(exc))
        else:
            extra = f" Vendor {result['vendor_id']} created." if result.get("vendor_id") else ""
            st.session_state["review_flash"] = f"{review.ACTIONS[action]} recorded for {sid}.{extra} The vendor email is in the Outbox."
            st.rerun()
