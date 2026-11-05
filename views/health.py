"""System health: database, LLM provider reachability, sanctions snapshot, registry, email mode."""
import platform

import streamlit as st

from core import config, db, sanctions
from core.registry import get_registry
from ui.theme import kpi, page_header, simulated_label

page_header("System health", "Is this deployment able to do its job right now?")

counts = {t: db.query_one(f"SELECT COUNT(*) AS n FROM {t}")["n"]
          for t in ("submissions", "vendors", "findings", "outbox", "audit_events", "llm_calls")}
meta = sanctions.snapshot_meta()
provider = config.llm_provider_name()
c = st.columns(4)
with c[0]:
    kpi("Database", "OK", f"{counts['submissions']} submissions · {counts['vendors']} vendors · SQLite")
with c[1]:
    kpi("Document understanding", provider,
        config.llm_model(provider) if provider in ("anthropic", "gemini") else "rule-based, text PDFs only")
with c[2]:
    kpi("Sanctions snapshot", meta.get("publish_date", "missing"), f"{meta.get('record_count', '?')} SDN records · US lists only")
with c[3]:
    kpi("Email", config.email_mode(), "simulated = outbox only")

st.write("")
st.markdown("**LLM reachability**")
if provider in ("anthropic", "gemini"):
    if st.button("Check now (looks up the model; uses no tokens)"):
        try:
            if provider == "anthropic":
                import anthropic

                model_id = anthropic.Anthropic(timeout=15.0, max_retries=1).models.retrieve(config.llm_model(provider)).id
            else:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=config.gemini_api_key(), http_options=types.HttpOptions(timeout=15_000))
                model_id = client.models.get(model=config.llm_model(provider)).name
            st.success(f"Reachable. Model {model_id} available.")
        except Exception as exc:  # report, don't crash the health page
            st.error(f"Not reachable: {type(exc).__name__}: {exc}")
    if provider == "gemini":
        st.caption(f"Gemini requests are paced to at most {config.env('GEMINI_RPM', '10')} per minute (GEMINI_RPM; "
                   "the free-tier limit), so a run with many documents may pause between documents. When Google "
                   "says the model is busy or rate limited, the request goes to the backup models: "
                   f"{', '.join(config.gemini_fallback_models()) or 'none set'} (GEMINI_FALLBACK_MODELS).")
else:
    st.info("No ANTHROPIC_API_KEY or GEMINI_API_KEY configured: running in offline mode. Text-layer PDFs are read by "
            "deterministic rules; scans are reported unreadable (PENDING). Add a key in the host's secrets to enable "
            "Claude or Gemini.")

st.markdown(f"**Registry** {simulated_label()} {get_registry().label}", unsafe_allow_html=True)
st.caption("Real GST portal and bank penny-drop checks need paid/credentialed providers; see core/registry.py for the interface.")
st.markdown("**Runtime**")
st.json({"python": platform.python_version(), "db_path": str(config.db_path()), "app_base_url": config.app_base_url(),
         "cost_guard": {"max_pages_per_doc": config.max_pages_per_doc(), "max_docs": config.max_docs_per_submission()},
         "rows": counts, "sanctions_meta": {k: meta.get(k) for k in ("publish_date", "fetched_at", "coverage")}},
        expanded=False)

st.markdown("**Reset demo data**")
st.caption("Deletes all submissions, emails and audit events, then re-seeds the vendor master and replays the history. "
           "Use before a demo so scenarios start from a clean state.")
confirm = st.checkbox("I understand this deletes all runs")
if st.button("Reset demo data", disabled=not confirm):
    from core.seed import reset_demo_data

    with st.spinner("Rebuilding…"):
        result = reset_demo_data()
    st.session_state.pop("last_run_id", None)
    st.success(f"Reset done: {result['vendors']} vendors seeded, {result['history_replayed']} history submissions replayed.")
