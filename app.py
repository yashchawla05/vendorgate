"""VendorGate — Streamlit entry point.

Run locally:  python -m streamlit run app.py
This file only sets up the page and the navigation; every page lives in views/.
"""
import streamlit as st

from core.config import ROOT
from ui.theme import apply_theme
from ui.boot import boot, remember_base_url
from ui.topbar import top_bar

st.set_page_config(page_title="VendorGate", page_icon=":material/verified_user:", layout="wide")
apply_theme()
st.logo(str(ROOT / "assets" / "logo.svg"), size="large", icon_image=str(ROOT / "assets" / "logo_icon.svg"))
boot()  # idempotent: create DB schema + seed demo data once per process
remember_base_url()

about = st.Page("views/about.py", title="About me", icon=":material/person:", url_path="about", visibility="hidden")
pages = {
    "Vendor portal": [
        st.Page("views/new_submission.py", title="New submission", icon=":material/upload_file:", url_path="submit"),
    ],
    "Reviewer console": [
        st.Page("views/overview.py", title="Overview", icon=":material/dashboard:", default=True),
        st.Page("views/live_run.py", title="Live run", icon=":material/play_circle:", url_path="run"),
        st.Page("views/submission_detail.py", title="Submission detail", icon=":material/description:", url_path="detail"),
        st.Page("views/review_queue.py", title="Review queue", icon=":material/inbox:", url_path="queue"),
        st.Page("views/vendors.py", title="Vendor master", icon=":material/store:", url_path="vendors"),
        st.Page("views/outbox.py", title="Outbox", icon=":material/outgoing_mail:", url_path="outbox"),
    ],
    "Governance": [
        st.Page("views/rules.py", title="Rules & policy", icon=":material/rule:", url_path="rules"),
        st.Page("views/audit_log.py", title="Audit log", icon=":material/history:", url_path="audit"),
        st.Page("views/assumptions.py", title="Assumptions & limits", icon=":material/info:", url_path="assumptions"),
        st.Page("views/health.py", title="System health", icon=":material/monitor_heart:", url_path="health"),
    ],
    # Hidden from the sidebar: About me is linked from the top bar; Resubmit only through the
    # tokenised link in vendor emails.
    "": [
        about,
        st.Page("views/resubmit.py", title="Resubmit", url_path="resubmit", visibility="hidden"),
    ],
}

navigation = st.navigation(pages)
top_bar(about)  # Light / Dark switch + About me, beside the header buttons on every page
navigation.run()
