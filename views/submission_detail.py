"""Submission detail: the decision, why, and all the evidence behind it."""
import json

import pandas as pd
import streamlit as st

from core import db
from core.documents.types import SLOT_LABELS, label as doc_label
from core.models import COUNTRY_NAMES, ENTITY_LABELS
from core.submissions import get_submission
from ui.charts import risk_breakdown
from ui.theme import page_header, simulated_label, status_chip
from ui.widgets import (comparison_table, decision_banner, diff_table, email_card, esc,
                        findings_by_category, provider_label, stage_details, token_in)

page_header("Submission detail")

recent = db.query("SELECT id, legal_name, status FROM submissions ORDER BY submitted_at DESC LIMIT 200")
if not recent:
    st.info("No submissions yet.")
    st.stop()
ids = [r["id"] for r in recent]
labels = {r["id"]: f"{r['id']} · {r['legal_name'] or '(no name)'} · {r['status']}" for r in recent}
wanted = st.query_params.get("id") or st.session_state.get("last_run_id") or ids[0]
if wanted not in labels:
    row = db.query_one("SELECT id, legal_name, status FROM submissions WHERE id = ?", (wanted,))
    if row:
        ids.insert(0, wanted)
        labels[wanted] = f"{row['id']} · {row['legal_name']} · {row['status']}"
    else:
        wanted = ids[0]
sid = st.selectbox("Submission", ids, index=ids.index(wanted), format_func=lambda i: labels[i])
st.query_params["id"] = sid
sub = get_submission(sid)
form, decision = sub["form"], sub["decision"]

# ---------------------------------------------------------------- banner + facts
human = ""
if sub["reviews"]:
    last = sub["reviews"][-1]
    human = (f"Human review: {last['action']} by {last['reviewer']} on {last['created_at'][:16]} — \"{last['reason']}\". "
             f"System decision was {sub['system_status']}.")
if decision:
    decision_banner(sub["status"], sub["sub_status"], decision["explanation"], sub["risk_score"], human)
else:
    st.warning(f"Status {sub['status']}: the run did not finish.")

facts = [("Vendor", form["legal_name"] or "-"), ("Trade name", form["trade_name"] or "-"),
         ("Country", COUNTRY_NAMES.get(form["country"], form["country"])),
         ("Entity", ENTITY_LABELS.get(form["entity_type"], form["entity_type"])),
         ("Submitted", sub["submitted_at"][:16].replace("T", " ") + " UTC"),
         ("Attempt", f"v{sub['version']} of chain {sub['chain_id']}"), ("Source", sub["source"]),
         ("Read by", provider_label(sub["provider"]) + (" (seeded history)" if sub["seeded"] else ""))]
st.markdown('<div class="vg-card"><table class="vg-table" style="margin:0"><tr>' +
            "".join(f"<th>{esc(k)}</th>" for k, _ in facts[:4]) + "</tr><tr>" +
            "".join(f"<td>{esc(v)}</td>" for _, v in facts[:4]) + "</tr><tr>" +
            "".join(f"<th>{esc(k)}</th>" for k, _ in facts[4:]) + "</tr><tr>" +
            "".join(f"<td>{esc(v)}</td>" for _, v in facts[4:]) + "</tr></table></div>", unsafe_allow_html=True)

if sub["status"] == "PENDING" and sub["sub_status"] == "awaiting_vendor":
    vendor_mail = next((m for m in reversed(sub["outbox"]) if m["audience"] == "vendor"), None)
    token = token_in(vendor_mail["body"]) if vendor_mail else None
    newer = [c for c in sub["chain"] if c["version"] > sub["version"]]
    if token and not newer:
        if st.button("Open the vendor's resubmission link (as the vendor would from the email)"):
            st.switch_page("views/resubmit.py", query_params={"token": token})

st.write("")
tabs = st.tabs(["Reasoning & checks", "Field × source", "Documents", "Risk breakdown", "Emails",
                "Timeline & audit", "Stages"])

with tabs[0]:
    if decision:
        st.markdown("**Why this outcome** (deterministic policy " + esc(decision["policy_version"]) + ")",
                    unsafe_allow_html=True)
        for reason in json.loads(decision["reasons_json"]):
            st.markdown(f"- {esc(reason)}")
    st.markdown("**Checks with findings**, grouped by category")
    findings_by_category(sub["findings"])

with tabs[1]:
    s5 = next((s for s in sub["stages"] if s["stage"] == "S5"), None)
    st.caption("Every identifier and name, as it appears in each source. Mismatches are highlighted. Only documents "
               "that matched their slot are used.")
    comparison_table(s5["details"].get("comparison", []) if s5 else [])
    if s5 and s5["details"].get("registry"):
        reg = s5["details"]["registry"]
        st.markdown(f"{simulated_label()} {esc(reg.get('label'))}", unsafe_allow_html=True)
        st.json({k: v for k, v in reg.items() if k in ("gstin", "bank")}, expanded=False)

with tabs[2]:
    for d in sub["documents"]:
        status = "accepted" if d["accepted"] else "not used in cross-checks"
        with st.container(border=True):
            st.markdown(f"**{esc(SLOT_LABELS.get(d['slot'], d['slot']))}** · `{esc(d['filename'])}` · detected "
                        f"**{esc(doc_label(d['detected_type']) if d['detected_type'] else 'unread')}** · type confidence "
                        f"{(d['type_confidence'] or 0):.2f} · document confidence {(d['confidence'] or 0):.2f} · {status}"
                        + (" · carried over from the previous submission" if d["carried_from"] else ""))
            st.caption(f"SHA-256 {d['sha256'][:24]}… · read by {provider_label(d['provider'])}" + (f" · {d['notes']}" if d["notes"] else ""))
            fields = [{"field": k, "value": v["value"], "confidence": v["confidence"], "evidence (verbatim)": v["evidence"]}
                      for k, v in d["fields"].items() if v.get("value")]
            if fields:
                st.dataframe(pd.DataFrame(fields), hide_index=True, width="stretch")

with tabs[3]:
    if decision:
        contributions = json.loads(decision["breakdown_json"])
        st.markdown(f"Risk score = min(100, 5 × WARN + 20 × HIGH + 40 × CRITICAL) = **{sub['risk_score']}**. "
                    "Approval needs no blocking findings and a score below 30.")
        if contributions:
            st.plotly_chart(risk_breakdown(contributions), width="stretch", config={"displayModeBar": False})
            st.dataframe(pd.DataFrame(contributions), hide_index=True, width="stretch")
        else:
            st.success("No finding added risk points.")

with tabs[4]:
    if not sub["outbox"]:
        st.info("No messages.")
    for m in sub["outbox"]:
        email_card(m)

with tabs[5]:
    if len(sub["chain"]) > 1:
        st.markdown("**Submission chain**")
        st.markdown(" → ".join(f"{esc(c['id'])} (v{c['version']}) {status_chip(c['status'])}" for c in sub["chain"]),
                    unsafe_allow_html=True)
        s6 = next((s for s in sub["stages"] if s["stage"] == "S6"), None)
        if s6 and s6["details"].get("diff"):
            st.markdown(f"**What changed versus {esc(sub['parent_id'])}**")
            diff_table(s6["details"]["diff"])
        if sub["parent_id"]:
            new_docs = [SLOT_LABELS.get(d["slot"], d["slot"]) for d in sub["documents"] if not d["carried_from"]]
            kept = [SLOT_LABELS.get(d["slot"], d["slot"]) for d in sub["documents"] if d["carried_from"]]
            st.caption(f"Documents uploaded in this attempt: {', '.join(new_docs) or 'none'}. "
                       f"Carried over unchanged: {', '.join(kept) or 'none'}.")
    events = db.query("SELECT ts, actor, event, details_json FROM audit_events WHERE submission_id IN "
                      f"({','.join('?' * len(sub['chain']))}) ORDER BY ts, id", tuple(c["id"] for c in sub["chain"]))
    st.markdown("**Audit trail** (all attempts in this chain)")
    st.dataframe(pd.DataFrame(events), hide_index=True, width="stretch")

with tabs[6]:
    for s in sub["stages"]:
        stage_findings = [f for f in sub["findings"] if f["stage"] == s["stage"]]
        with st.expander(f"{s['stage']} · {s['name']} — {s['status']} · {s['duration_ms']} ms · {s['summary']}"):
            stage_details(s["stage"], s["details"], stage_findings)

