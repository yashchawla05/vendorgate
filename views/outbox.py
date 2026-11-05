"""Outbox: every message the system wrote. Sending is simulated unless EMAIL_MODE is configured."""
import streamlit as st

from core import config, db
from ui.theme import page_header, simulated_label
from ui.widgets import email_card, esc, token_in

page_header("Outbox", "Vendor emails and internal notes, newest first.")
mode = config.email_mode()
if mode == "simulated":
    st.markdown(f"{simulated_label('SIMULATED SENDING')} EMAIL_MODE=simulated: messages are stored here, not sent. "
                "Set EMAIL_MODE=resend or smtp (with credentials) to deliver for real.", unsafe_allow_html=True)
else:
    st.caption(f"EMAIL_MODE={esc(mode)}: vendor emails are delivered; internal notes stay here.")

c1, c2 = st.columns([2, 3])
audience = c1.segmented_control("Audience", ["All", "Vendor", "Internal"], default="All")
search = c2.text_input("Filter by submission ID or text", "")
sql, params = "SELECT * FROM outbox", []
where = []
if audience in ("Vendor", "Internal"):
    where.append("audience = ?")
    params.append(audience.lower())
if search.strip():
    where.append("(submission_id LIKE ? OR subject LIKE ? OR body LIKE ?)")
    params += [f"%{search.strip()}%"] * 3
if where:
    sql += " WHERE " + " AND ".join(where)
messages = db.query(sql + " ORDER BY id DESC LIMIT 100", tuple(params))
st.caption(f"{len(messages)} message(s)")
for m in messages:
    email_card(m)
    token = token_in(m["body"]) if m["audience"] == "vendor" else None
    if token:
        if st.button("Open this link as the vendor", key=f"open_{m['id']}"):
            st.switch_page("views/resubmit.py", query_params={"token": token})
