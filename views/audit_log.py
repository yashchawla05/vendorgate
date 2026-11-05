"""Audit log: append-only record of every state change, filterable and exportable."""
import pandas as pd
import streamlit as st

from core import db
from ui.theme import page_header

page_header("Audit log", "Who did what, when, and why. Replaces the trail that used to live in inboxes.")
events = pd.DataFrame(db.query("SELECT id, ts, submission_id, actor, event, details_json AS details FROM audit_events ORDER BY id DESC"))
if events.empty:
    st.info("No events yet.")
    st.stop()
c1, c2, c3 = st.columns(3)
kinds = c1.multiselect("Event", sorted(events["event"].unique()))
actors = c2.multiselect("Actor", sorted(events["actor"].unique()))
sid = c3.text_input("Submission ID contains")
view = events
if kinds:
    view = view[view["event"].isin(kinds)]
if actors:
    view = view[view["actor"].isin(actors)]
if sid.strip():
    view = view[view["submission_id"].fillna("").str.contains(sid.strip(), regex=False)]
st.caption(f"{len(view)} of {len(events)} events")
st.dataframe(view, hide_index=True, width="stretch", height=560)
st.download_button("Export CSV", view.to_csv(index=False).encode("utf-8"), file_name="vendorgate_audit_log.csv",
                   mime="text/csv")
