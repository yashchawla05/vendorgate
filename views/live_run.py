"""Live run: consumes the pipeline generator and redraws the stage tracker as each event arrives.

Nothing here is animated or simulated: every row changes because a real stage started or
finished. The optional "demo pacing" adds a pause BETWEEN stages so an audience can follow;
the durations shown are always the measured execution times.
"""
import time

import streamlit as st

from core.llm.base import LLMError, get_provider
from core.pipeline.runner import STAGES, run_pipeline
from core.submissions import get_submission
from ui.theme import page_header, simulated_label
from ui.widgets import decision_banner, esc, provider_label, stage_details, tracker_html

page_header("Live run", "Each verification stage as it executes, with its findings and evidence.")

draft = st.session_state.pop("pending_draft", None)
pacing = st.toggle("Demo pacing (0.4 s pause between stages; timings shown are real)",
                   value=st.session_state.get("pacing", False), key="pacing")


def recorded_view(submission_id: str) -> None:
    sub = get_submission(submission_id)
    if not sub:
        st.warning("Submission not found.")
        return
    st.caption(f"Recorded run of {submission_id} (stored results, not re-executed).")
    rows = [{"stage": s["stage"], "name": s["name"], "status": s["status"], "ms": s["duration_ms"], "summary": s["summary"],
             "findings": sum(1 for f in sub["findings"] if f["stage"] == s["stage"])} for s in sub["stages"]]
    st.markdown(tracker_html(rows), unsafe_allow_html=True)
    if sub["decision"]:
        decision_banner(sub["status"], sub["sub_status"], sub["decision"]["explanation"], sub["risk_score"])
    for s in sub["stages"]:
        stage_findings = [f for f in sub["findings"] if f["stage"] == s["stage"]]
        with st.expander(f"{s['stage']} · {s['name']} — {s['status']}", expanded=False):
            stage_details(s["stage"], s["details"], stage_findings)
    if st.button("Open submission detail", type="primary"):
        st.switch_page("views/submission_detail.py", query_params={"id": submission_id})


if draft is None:
    last = st.session_state.get("last_run_id")
    if last:
        recorded_view(last)
    else:
        st.info("No run in progress. Start one from **New submission** (try a demo scenario).")
        if st.button("Go to New submission", type="primary"):
            st.switch_page("views/new_submission.py")
    st.stop()

# ---------------------------------------------------------------- a real run
try:
    provider = get_provider()
except LLMError as exc:  # e.g. LLM_PROVIDER=gemini without a key: say so instead of crashing
    st.error(f"The document-understanding provider is not configured: {exc}. Add the key in the app's secrets, "
             "or set LLM_PROVIDER to auto or offline. Then start the submission again.")
    st.stop()
name = draft.form.legal_name or draft.form.trade_name or "(no name)"
kind = "Resubmission" if draft.parent_id else "Submission"
st.markdown(f"**{kind}: {esc(name)}** · source `{esc(draft.source)}` · {len(draft.files)} file(s) · "
            f"document understanding by **{esc(provider_label(provider.name))}** · registry {simulated_label()}",
            unsafe_allow_html=True)

rows = [{"stage": code, "name": stage_name, "status": "queued", "ms": "", "summary": "", "findings": 0}
        for code, stage_name, _ in STAGES]
tracker = st.empty()
tracker.markdown(tracker_html(rows), unsafe_allow_html=True)
banner = st.empty()
st.markdown("##### Stage evidence")
details_area = st.container()

submission_id = ""
by_code = {r["stage"]: r for r in rows}
try:
    for event in run_pipeline(draft, provider=provider):
        row = by_code[event.stage]
        if event.phase == "started":
            row.update(status="running", summary="Running…")
        else:
            submission_id = event.details.get("submission_id") or submission_id
            row.update(status=event.status, ms=event.duration_ms, summary=event.summary, findings=len(event.findings))
            with details_area:
                with st.expander(f"{event.stage} · {event.name} — {event.status}", expanded=bool(event.findings)):
                    stage_details(event.stage, event.details, event.findings)
        tracker.markdown(tracker_html(rows), unsafe_allow_html=True)
        if pacing and event.phase == "completed":
            time.sleep(0.4)
except Exception as exc:  # intake failure: nothing was stored, show the error plainly
    st.error(f"The submission could not be taken in: {type(exc).__name__}: {exc}")
    st.stop()

st.session_state["last_run_id"] = submission_id
sub = get_submission(submission_id)
with banner.container():
    decision_banner(sub["status"], sub["sub_status"], sub["decision"]["explanation"], sub["risk_score"])
    c1, c2 = st.columns([1, 4])
    if c1.button("Open submission detail", type="primary"):
        st.switch_page("views/submission_detail.py", query_params={"id": submission_id})
    c2.caption(f"{submission_id} saved. Emails are in the Outbox; the audit log has every step.")
