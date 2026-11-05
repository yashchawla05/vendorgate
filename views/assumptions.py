"""Assumptions & limitations: the same text as ASSUMPTIONS.md and LIMITATIONS.md in the repository."""
import streamlit as st

from core.config import ROOT
from ui.theme import page_header

page_header("Assumptions & limitations", "Where the brief was ambiguous we decided and wrote it down. What is simulated is said plainly.")
tab_a, tab_l = st.tabs(["Assumptions", "Limitations & next steps"])
for tab, name in ((tab_a, "ASSUMPTIONS.md"), (tab_l, "LIMITATIONS.md")):
    with tab:
        path = ROOT / name
        st.markdown(path.read_text(encoding="utf-8") if path.exists() else f"{name} not found.")
