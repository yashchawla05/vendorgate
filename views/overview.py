"""Overview dashboard: volume, outcomes, speed, backlog, why submissions fail, and risk."""
import streamlit as st

from core import metrics
from core.rules import policy
from ui.charts import CONFIG, risk_distribution, status_over_time, top_reasons
from ui.theme import kpi, page_header, status_chip
from ui.widgets import SUB_STATUS, esc

page_header("Overview", "Vendor onboarding at a glance: every number is computed from stored pipeline runs.")

include_seeded = st.toggle("Include seeded history (16 older synthetic submissions replayed through the pipeline at startup)",
                           value=True)
df = metrics.submissions_frame(include_seeded)
k = metrics.kpis(df)
if not k["total"]:
    st.info("No submissions yet. Run a demo scenario from **New submission**.")
    st.stop()


def fmt_seconds(s: float | None) -> str:
    if s is None:
        return "-"
    if s < 1:
        return f"{s * 1000:.0f} ms"
    return f"{s:.1f} s" if s < 60 else f"{s / 60:.1f} min"


c = st.columns(6)
with c[0]:
    kpi("Submissions", str(k["total"]), f"{int((df['seeded'] == 0).sum())} live · {int((df['seeded'] == 1).sum())} seeded")
with c[1]:
    kpi("Approved", f"{k['pct']['APPROVED']}%", f"{k['approved']} submissions")
with c[2]:
    kpi("Pending", f"{k['pct']['PENDING']}%", f"{k['awaiting_vendor']} with vendor · {k['awaiting_review']} with us")
with c[3]:
    kpi("Rejected", f"{k['pct']['REJECTED']}%", f"{k['rejected']} submissions")
with c[4]:
    kpi("Avg time to decision", fmt_seconds(k["avg_decision_seconds"]), "measured pipeline run, intake to decision")
with c[5]:
    kpi("Pending aging", f"{k['pending_avg_days']:.1f} d", f"average · oldest {k['pending_max_days']:.0f} d")

st.write("")
c1, c2 = st.columns([1, 2])
with c1:
    kpi("Manual review time saved (estimate)", f"{k['hours_saved']} h",
        f"{k['automated']} submissions decided or sent back without a person × {k['minutes_assumption']} min "
        "each (assumption in policy.yaml)")
with c2:
    usage = metrics.llm_usage()
    kpi("LLM usage", f"{usage['calls']} calls",
        f"{usage['tin']:,} input / {usage['tout']:,} output tokens · {usage['failures']} failed calls "
        "(offline-mode runs use no tokens)")

st.write("")


def chart_card(title: str, how_to_read: str):
    """A bordered card with the chart's title and one line on how to read it."""
    card = st.container(border=True)
    card.markdown(f"<div class='vg-chart-title'>{esc(title)}</div><div class='vg-muted'>{esc(how_to_read)}</div>",
                  unsafe_allow_html=True)
    return card


limit = int(policy()["thresholds"]["approve_max_risk"])
weekly = metrics.weekly_status(df)
reasons = metrics.top_reasons(df)
left, right = st.columns(2)
with left, chart_card("Submissions per week, by outcome", "Each column is one week; the number on top is the total."):
    st.plotly_chart(status_over_time(weekly), width="stretch", config=CONFIG)
    with st.expander("Show the numbers"):
        table = weekly.pivot(index="week", columns="status", values="count").fillna(0).astype(int)
        table.index = [w.strftime("Week of %d %b") for w in table.index]
        st.dataframe(table, width="stretch")
with right, chart_card("Why submissions are held",
                       f"Share of all {k['total']} submissions with each finding (one can have several)."):
    if reasons.empty:
        st.caption("No findings yet.")
    else:
        st.plotly_chart(top_reasons(reasons, k["total"]), width="stretch", config=CONFIG)
        with st.expander("Show the numbers"):
            st.dataframe(reasons[["rule_id", "title", "severity", "count"]], hide_index=True, width="stretch")

left, right = st.columns(2)
with left, chart_card("Risk score of each submission",
                      f"Scores under {limit} can be approved; higher scores are held for review or fixes."):
    scores = df["risk_score"].fillna(0)
    st.plotly_chart(risk_distribution(scores, limit), width="stretch", config=CONFIG)
    with st.expander("Show the numbers"):
        st.dataframe(df[["id", "legal_name", "status", "risk_score"]], hide_index=True, width="stretch")
with right, chart_card("Recent submissions", "The latest six; open one to see every check and its evidence."):
    recent = df.head(6)
    rows = "".join(
        f"<tr><td class='vg-mono' style='white-space:nowrap'><a href='detail?id={esc(r.id)}' target='_self'>{esc(r.id)}</a></td>"
        f"<td>{esc(r.legal_name or '-')}</td><td>{status_chip(r.status)}"
        f"<div class='vg-muted' style='font-size:0.78rem;margin-top:3px'>{esc(SUB_STATUS.get(r.sub_status or '', ''))}</div></td>"
        f"<td style='text-align:right'>{'' if r.risk_score != r.risk_score else int(r.risk_score)}</td></tr>"
        for r in recent.itertuples())
    st.markdown("<table class='vg-table'><thead><tr><th>ID</th><th>Vendor</th><th>Status</th>"
                f"<th style='text-align:right'>Risk</th></tr></thead><tbody>{rows}</tbody></table>", unsafe_allow_html=True)
