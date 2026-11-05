"""Rules & policy (read-only): the rule catalogue and the decision policy, straight from config/."""
import pandas as pd
import streamlit as st

from core.config import CONFIG_DIR
from core.rules import catalogue, catalogue_version, policy
from ui.theme import page_header

page_header("Rules & policy", "Read-only. Edit config/rules.yaml and config/policy.yaml in the repository; both are versioned.")
pol = policy()
st.markdown(f"Rule catalogue version **{catalogue_version()}** · policy version **{pol['version']}**")

st.markdown("#### Decision policy")
weights_text = ", ".join(f"{k} {v}" for k, v in pol["risk_weights"].items())
st.markdown(
    f"""
1. **REJECTED** if any of {', '.join(pol['reject']['trigger_rules'])} fires (strong sanctions match; identifier shared
   with a different vendor), or **{pol['reject']['min_critical_findings']}+ CRITICAL** findings, or more than
   **{pol['reject']['max_failed_resubmissions']}** failed resubmissions.
2. **PENDING** if any finding blocks approval (every HIGH/CRITICAL, plus some WARNs) or the risk score is
   **≥ {pol['thresholds']['approve_max_risk']}**. *Awaiting vendor* when every blocker is vendor-fixable, otherwise
   *awaiting internal review*.
3. **APPROVED** otherwise: all checks pass, document confidence ≥ {pol['thresholds']['doc_confidence_min']}, no possible
   sanctions match, risk < {pol['thresholds']['approve_max_risk']}.

Risk score = min({pol['risk_cap']}, Σ weights) with weights {weights_text}. An LLM never makes or changes this
decision: it only reads documents, judges borderline names, and words emails.
""")
c1, c2 = st.columns(2)
c1.markdown("**Thresholds**")
c1.dataframe(pd.DataFrame([{"threshold": k, "value": v} for k, v in pol["thresholds"].items()]), hide_index=True,
             width="stretch")
c2.markdown("**Required fields & documents**")
c2.json(pol["requirements"], expanded=False)

st.markdown("#### Rule catalogue")
rules = pd.DataFrame(catalogue().values())
cats = ["All"] + sorted(rules["category"].unique())
cat = st.segmented_control("Category", cats, default="All")
if cat and cat != "All":
    rules = rules[rules["category"] == cat]
st.dataframe(rules[["id", "title", "severity", "resolver", "blocks_approval", "stage", "rationale"]], hide_index=True,
             width="stretch", height=min(700, 38 * (len(rules) + 1)))

with st.expander("Raw config/policy.yaml"):
    st.code((CONFIG_DIR / "policy.yaml").read_text(encoding="utf-8"), language="yaml")
