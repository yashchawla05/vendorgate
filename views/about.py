"""About me: who built VendorGate, kept short, with the CV itself below.

The CV is shown exactly as written (assets/Yash_Chawla_CV.pdf, drawn with pypdfium2, which the
app already uses for scans) and can be downloaded. Figures about this project are read from the
repository, so they always match the code.
"""
import io
import json

import pypdfium2 as pdfium
import streamlit as st

from core.config import EVAL_DIR, ROOT
from core.rules import catalogue
from ui.theme import page_header

CV_FILE = ROOT / "assets" / "Yash_Chawla_CV.pdf"
LINKEDIN = "https://www.linkedin.com/in/yash-chawla-2b642528a"


@st.cache_data(show_spinner=False)
def cv_pages(pdf: bytes) -> list[bytes]:
    """Every page of the CV as a PNG, sharp on high-density screens."""
    document = pdfium.PdfDocument(pdf)
    try:
        pages = []
        for page in document:
            buffer = io.BytesIO()
            page.render(scale=2.5).to_pil().save(buffer, format="PNG")
            pages.append(buffer.getvalue())
        return pages
    finally:
        document.close()


cv = CV_FILE.read_bytes()
eval_docs = len(json.loads((EVAL_DIR / "ground_truth.json").read_text()))

page_header("About me", "The person behind VendorGate, my case study for the AI Solutions Analyst role at Zamp.")

with st.container(border=True):
    st.markdown("### Yash Chawla")
    st.markdown("B.Tech, Mechanical and Aerospace Engineering · IIT Hyderabad, 2027 · CGPA 8.65  \n"
                "Business Analyst Intern, **Licious** · Jan – Jul 2026")
    st.markdown("I like turning business processes into clear rules, useful data and AI that people can trust, "
                "and measuring whether it works.")
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.download_button("Download CV", cv, file_name="Yash_Chawla_CV.pdf", mime="application/pdf",
                           icon=":material/download:", type="primary")
        st.link_button("LinkedIn", LINKEDIN, icon=":material/open_in_new:")
        st.caption("me23btech11016@iith.ac.in")

st.write("")
st.markdown("#### Why I fit the AI Solutions Analyst role")
FIT = [
    (":material/rule:", "Process into rules",
     f"Defined the leakage rules behind Licious's short-settlement dashboard. VendorGate decides with "
     f"{len(catalogue())} explicit rules."),
    (":material/smart_toy:", "AI with guardrails",
     "Built a multi-agent system that validates its own answers and retries. In VendorGate, AI reads the "
     "documents and code makes every decision."),
    (":material/query_stats:", "Measured, not assumed",
     f"Cross-validated a wallet model (R² ≈ 0.72) and measured launch lift against baselines. VendorGate's "
     f"document reading is scored on {eval_docs} test documents."),
    (":material/handshake:", "Customer-facing",
     "Pitched 100+ companies and onboarded 20+ recruiters; secured MoUs with 50+ VC firms for the E-Cell."),
]
for row in (FIT[:2], FIT[2:]):
    for column, (icon, title, text) in zip(st.columns(2), row):
        with column, st.container(border=True, height="stretch"):
            st.markdown(f"**:violet[{icon} {title}]**  \n{text}")

st.write("")
st.markdown("#### My CV")
_, middle, _ = st.columns([1, 5, 1])
with middle, st.container(border=True):
    for image in cv_pages(cv):
        st.image(image, width="stretch")
