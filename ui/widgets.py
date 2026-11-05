"""Reusable page pieces. Live Run and Submission Detail render stages with the same code,
so what you watch live is exactly what is stored."""
from __future__ import annotations

import html
import json
import re

import pandas as pd
import streamlit as st

from core.documents.types import SLOT_LABELS, label as doc_label
from core.llm.base import provider_label  # noqa: F401  (screens name the provider, never a model ID)
from ui.theme import NEUTRAL, STATUS_COLORS, severity_chip, simulated_label, stage_chip

SUB_STATUS = {"awaiting_vendor": "Awaiting vendor", "awaiting_internal_review": "Awaiting internal review", "": ""}
SEVERITY_ORDER = ["CRITICAL", "HIGH", "WARN", "INFO"]
CATEGORY_LABELS = {"completeness": "Completeness", "documents": "Documents", "format": "Format & checksum",
                   "consistency": "Consistency", "registry": "Registry (simulated)", "fraud": "Duplicates & fraud",
                   "sanctions": "Sanctions", "policy": "Policy", "system": "System"}


def as_dict(f) -> dict:
    return f.model_dump() if hasattr(f, "model_dump") else f


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


# ---------------------------------------------------------------- decision banner
def decision_banner(status: str, sub_status: str, explanation: str, risk: int | None, human: str = "") -> None:
    bg, fg = STATUS_COLORS.get(status, NEUTRAL)
    sub = SUB_STATUS.get(sub_status or "", sub_status or "")
    risk_html = f'<div style="font-size:0.85rem;color:{fg}">Risk score <b>{risk}</b>/100</div>' if risk is not None else ""
    human_html = (f'<div style="margin-top:6px;font-size:0.85rem;color:var(--vg-text)">{esc(human)}</div>'
                  if human else "")
    st.markdown(
        f'<div class="vg-banner" style="background:{bg};border:1px solid color-mix(in srgb, {fg} 20%, transparent)">'
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap">'
        f'<h2 style="color:{fg}">{esc(status)}{" · " + esc(sub) if sub else ""}</h2>{risk_html}</div>'
        f'<div style="color:var(--vg-text)">{esc(explanation)}</div>{human_html}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- stage tracker
def tracker_html(rows: list[dict]) -> str:
    """rows: {stage, name, status, ms, summary, findings}"""
    body = []
    for r in rows:
        ms = f"{r['ms']} ms" if r.get("ms") not in (None, "") else ""
        n = r.get("findings", 0)
        count = f'<span class="vg-muted">{n} finding{"s" if n != 1 else ""}</span>' if n else ""
        body.append(
            f'<tr><td class="vg-mono" style="width:44px;color:var(--vg-label)">{esc(r["stage"])}</td>'
            f'<td style="width:290px"><b>{esc(r["name"])}</b></td>'
            f'<td style="width:110px">{stage_chip(r["status"])}</td>'
            f'<td class="vg-mono" style="width:80px;text-align:right;color:var(--vg-label)">{esc(ms)}</td>'
            f'<td style="color:var(--vg-text)">{esc(r.get("summary", ""))} {count}</td></tr>')
    return ('<div class="vg-card" style="padding:4px 8px;overflow-x:auto"><table style="width:100%;border-collapse:collapse;'
            'font-size:0.9rem">'
            + "".join(body).replace("<tr>", '<tr style="border-bottom:1px solid var(--vg-rule);height:38px">')
            + "</table></div>")


# ---------------------------------------------------------------- findings
def findings_by_category(findings: list) -> None:
    items = [as_dict(f) for f in findings]
    if not items:
        st.success("No findings: every check passed.")
        return
    groups: dict[str, list[dict]] = {}
    for f in sorted(items, key=lambda f: SEVERITY_ORDER.index(f["severity"])):
        groups.setdefault(f["category"], []).append(f)
    for category, group in groups.items():
        st.markdown(f"**{CATEGORY_LABELS.get(category, category.title())}**"
                    + (" " + simulated_label() if category == "registry" else ""), unsafe_allow_html=True)
        for f in group:
            finding_row(f)


def finding_row(f: dict) -> None:
    f = as_dict(f)
    who = "Vendor can fix" if f["resolver"] == "vendor" else "Needs internal review"
    blocks = "blocks approval" if f["blocks_approval"] else "note only"
    st.markdown(
        f'<div style="padding:8px 0;border-bottom:1px solid var(--vg-rule)">{severity_chip(f["severity"])} '
        f'<span class="vg-mono" style="color:var(--vg-label)">{esc(f["rule_id"])}</span> <b>{esc(f["title"])}</b>'
        f'<div style="margin:4px 0 0 2px">{esc(f["message"])}</div>'
        f'<div class="vg-muted">{who} · {blocks}</div></div>', unsafe_allow_html=True)
    evidence = f.get("evidence") or {}
    if evidence:
        with st.expander(f"Evidence · {f['rule_id']}", expanded=False):
            st.json(evidence, expanded=2)


# ---------------------------------------------------------------- field x source
def comparison_table(rows: list[dict]) -> None:
    if not rows:
        st.info("No cross-source fields to compare (documents missing or unread).")
        return
    sources = []
    for r in rows:
        for s in r["sources"]:
            if s not in sources:
                sources.append(s)
    head = "".join(f"<th>{esc(s)}</th>" for s in sources)
    bad_bg, bad_fg = STATUS_COLORS["REJECTED"]
    dash = '<span style="color:var(--vg-faint)">-</span>'
    body = []
    for r in rows:
        bad = r["status"] == "mismatch"
        reference = next((v for v in r["sources"].values() if v), "")
        cells = []
        for s in sources:
            v = r["sources"].get(s, "")
            differs = bool(v) and (_norm_cell(v, r) != _norm_cell(reference, r))
            style = f"background:{bad_bg};color:{bad_fg};font-weight:600" if bad and differs else ""
            cells.append(f'<td class="vg-mono" style="{style}">{esc(v) or dash}</td>')
        chip = {"match": ("MATCH", "APPROVED"), "mismatch": ("MISMATCH", "REJECTED")}.get(r["status"], ("1 SOURCE", "RECEIVED"))
        body.append(f'<tr><td><b>{esc(r["label"])}</b></td>{"".join(cells)}<td>{status_chip_text(*chip)}</td></tr>')
    st.markdown(
        '<div style="overflow-x:auto"><table class="vg-table"><thead><tr><th>Field</th>' + head + "<th>Result</th></tr></thead>"
        "<tbody>" + "".join(body) + "</tbody></table></div>", unsafe_allow_html=True)


def _norm_cell(value: str, row: dict) -> str:
    from core.names import core_and_form
    from core.validators.common import compact

    return core_and_form(value)[0] if row["field"] in ("legal_name", "bank.account_holder") else compact(value)


def status_chip_text(text: str, palette_key: str) -> str:
    bg, fg = STATUS_COLORS[palette_key]
    return f'<span class="vg-chip" style="background:{bg};color:{fg}">{esc(text)}</span>'


# ---------------------------------------------------------------- stage details
def stage_details(stage: str, details: dict, findings: list) -> None:
    """Stage-specific evidence, then the stage's findings."""
    if stage == "S1":
        st.dataframe(pd.DataFrame(details.get("files", [])), hide_index=True, width="stretch")
        if details.get("carried_over"):
            st.caption(f"Carried over from {details.get('parent_id')}: {', '.join(details['carried_over'])}")
    elif stage == "S3":
        docs = details.get("documents", [])
        st.caption(f"Document understanding by {provider_label(details.get('provider'))}")
        for d in docs:
            ok = "accepted" if d["accepted"] else "not accepted"
            st.markdown(f"**{esc(SLOT_LABELS.get(d['slot'], d['slot']))}** — `{esc(d['filename'])}` → detected "
                        f"**{esc(doc_label(d['detected_type']) if d['detected_type'] else 'unread')}** "
                        f"(type conf {d['type_confidence']:.2f}, doc conf {d['confidence']:.2f}, {ok})")
            if d["fields"]:
                st.dataframe(pd.DataFrame([{"field": k, "value": v["value"], "confidence": v["confidence"],
                                            "evidence (verbatim)": v["evidence"]} for k, v in d["fields"].items()]),
                             hide_index=True, width="stretch")
            if d.get("notes"):
                st.caption(d["notes"])
    elif stage == "S4" and details.get("normalised"):
        st.dataframe(pd.DataFrame([{"identifier": k, "normalised": v, "valid": details["valid"].get(k)}
                                   for k, v in details["normalised"].items()]), hide_index=True, width="stretch")
    elif stage == "S5":
        comparison_table(details.get("comparison", []))
        reg = details.get("registry") or {}
        if reg:
            st.markdown(f"{simulated_label()} {esc(reg.get('label', ''))}", unsafe_allow_html=True)
    elif stage == "S6" and details.get("diff"):
        diff_table(details["diff"])
    elif stage == "S7":
        st.caption(f"Lists: OFAC SDN + consolidated, published {details.get('list_publish_date')} "
                   f"({details.get('record_count')} SDN records). {details.get('coverage')}. "
                   f"Thresholds: strong ≥ {details.get('thresholds', {}).get('strong')}, possible ≥ "
                   f"{details.get('thresholds', {}).get('possible')}.")
        if details.get("hits"):
            st.dataframe(pd.DataFrame(details["hits"]), hide_index=True, width="stretch")
    elif stage == "S8":
        for reason in details.get("reasons", []):
            st.markdown(f"- {esc(reason)}")
    elif stage == "S9":
        for m in details.get("messages", []):
            st.markdown(f"- **{esc(m['audience'])}** → {esc(m['to'])}: {esc(m['subject'])} "
                        f"<span class='vg-muted'>({esc(m['drafted_by'])}; {esc(m['delivery'])})</span>", unsafe_allow_html=True)
    if findings:
        for f in findings:
            finding_row(f)


def diff_table(diff: list[dict]) -> None:
    rows = [{"field": d["field"], "before": d["before"], "after": d["after"],
             "requested by us": "yes" if d["requested"] else "no"} for d in diff]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# ---------------------------------------------------------------- emails
LINK_RE = re.compile(r"https?://\S+/resubmit\?token=[\w-]+")


def email_card(m: dict) -> None:
    audience = "To vendor" if m["audience"] == "vendor" else "Internal"
    st.markdown(
        f'<div class="vg-card" style="margin-bottom:10px"><div class="vg-muted">{audience} · {esc(m["to_addr"])} · '
        f'{esc(m["created_at"])} · drafted by {esc(m["drafted_by"])} · delivery: {esc(m["delivery"])}</div>'
        f'<div style="font-weight:650;margin:6px 0">{esc(m["subject"])}</div>'
        f'<div style="font-size:0.9rem;line-height:1.5">{body_html(m["body"])}</div></div>', unsafe_allow_html=True)


def body_html(body: str) -> str:
    """Plain-text email -> one HTML block (no raw newlines, so markdown leaves it alone); links clickable."""
    text = esc(body)
    text = re.sub(r"(https?://[^\s<]+)", r'<a href="\1" target="_blank">\1</a>', text)
    return text.replace("\n", "<br>")


def token_in(body: str) -> str | None:
    m = LINK_RE.search(body or "")
    return m.group(0).split("token=")[1] if m else None


def pretty_json(value) -> str:
    return json.dumps(value, indent=2, default=str)
