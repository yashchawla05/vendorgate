"""Plotly charts with one shared look (the data-viz method: form first, colour by job, validated palette).

  * Approved / pending / rejected are STATES: the reserved status palette, always with a legend,
    a 2px surface gap between stacked parts (ui/theme.py) and hover; never used for anything else.
  * One series = one hue (Zamp-style blue). Emphasis = that hue for the part that matters, grey for the rest.
  * Thin bars (bargap), 4px rounded data-ends, hairline recessive grid, values at the bar tip in text
    colour (Streamlit's chart theme supplies text, grid and axis colours, so they follow light/dark).
  * The palette passes the validator in both modes (scripts/validate_palette.py from the data-viz
    method): green/amber is in the 6-8 CVD band, legal here because of the legend, gaps and tables.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

STATUS = {"APPROVED": "#2B9A68", "PENDING": "#C98316", "REJECTED": "#DB3A62"}
STATUS_LABEL = {"APPROVED": "Approved", "PENDING": "Pending", "REJECTED": "Rejected"}
SERIES_1 = "#2F6BFF"                 # single-series hue: 4.5:1 on white, 4.1:1 on the dark page
TRACK = "rgba(47, 107, 255, 0.13)"   # same hue, light step: reads on both page colours
DE_EMPHASIS = "#8A93A0"
REFERENCE_LINE = "#8A93A0"
APPROVAL_ZONE = "rgba(43, 154, 104, 0.10)"
FONT = "Geist, Inter, system-ui, sans-serif"
CONFIG = {"displayModeBar": False}


def _layout(fig: go.Figure, height: int = 280) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=4, r=12, t=8, b=4), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=12), barcornerradius=4, hoverlabel=dict(font_size=12, font_family=FONT),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None, font=dict(size=12)),
        hovermode="closest",
    )
    fig.update_xaxes(showgrid=False, ticks="", fixedrange=True)
    fig.update_yaxes(zeroline=False, gridwidth=1, ticks="", fixedrange=True)
    return fig


def status_over_time(weekly: pd.DataFrame) -> go.Figure:
    """Stacked columns per week; the week's total sits on the cap."""
    weeks = sorted(weekly["week"].unique())
    labels = [pd.Timestamp(w).strftime("%d %b") for w in weeks]
    fig = go.Figure()
    for status in ("APPROVED", "PENDING", "REJECTED"):  # fixed order, never by rank
        part = weekly[weekly["status"] == status].set_index("week").reindex(weeks, fill_value=0)
        fig.add_bar(x=labels, y=part["count"], name=STATUS_LABEL[status], marker_color=STATUS[status],
                    marker_line=dict(color="#FFFFFF", width=2),  # recoloured to the page colour in ui/theme.py
                    hovertemplate="Week of %{x}<br>" + STATUS_LABEL[status] + ": %{y}<extra></extra>")
    totals = weekly.groupby("week")["count"].sum().reindex(weeks, fill_value=0)
    fig.add_scatter(x=labels, y=totals, mode="text", text=[str(int(t)) if t else "" for t in totals],
                    textposition="top center", textfont=dict(size=12), hoverinfo="skip", showlegend=False)
    fig.update_layout(barmode="stack", bargap=0.55, legend_traceorder="normal")
    fig.update_yaxes(dtick=2 if totals.max() > 6 else 1, rangemode="tozero", range=[0, totals.max() * 1.25 + 0.5])
    return _layout(fig)


def top_reasons(reasons: pd.DataFrame, total: int) -> go.Figure:
    """Ranked bars on a 100% track: how many of all submissions were held for each reason."""
    data = reasons.iloc[::-1]  # largest at the top
    share = [c / total * 100 if total else 0 for c in data["count"]]
    fig = go.Figure()
    fig.add_bar(x=[100] * len(data), y=data["title"], orientation="h", marker_color=TRACK, hoverinfo="skip",
                showlegend=False, text=[f"{c} · {s:.0f}%" for c, s in zip(data["count"], share)],
                textposition="outside", cliponaxis=False)
    fig.add_bar(x=share, y=data["title"], orientation="h", marker_color=SERIES_1, showlegend=False,
                customdata=data["rule_id"], hovertemplate="%{y} (%{customdata})<br>%{x:.0f}% of submissions<extra></extra>")
    fig.update_layout(barmode="overlay", bargap=0.5)
    fig.update_xaxes(showticklabels=False, showgrid=False, range=[0, 128])
    fig.update_yaxes(showgrid=False)
    return _layout(fig, height=max(200, 38 * len(data) + 24))


def risk_distribution(scores: pd.Series, limit: int = 30) -> go.Figure:
    """Histogram in bands of 10; the bands that can be approved are coloured, the rest grey."""
    edges = list(range(0, 101, 10))
    labels = [f"{b}+" for b in edges[:-1]]
    counts = pd.cut(scores, bins=[-1] + edges[1:], labels=labels).value_counts().reindex(labels, fill_value=0)
    colours = [SERIES_1 if b < limit else DE_EMPHASIS for b in edges[:-1]]
    fig = go.Figure(go.Bar(x=labels, y=list(counts.values), marker_color=colours,
                           text=[str(v) if v else "" for v in counts.values], textposition="outside", cliponaxis=False,
                           customdata=[f"{b}–{b + 9}" if b < 90 else "90–100" for b in edges[:-1]],
                           hovertemplate="Risk %{customdata}: %{y} submission(s)<extra></extra>"))
    zone_end = limit / 10 - 0.5
    fig.add_vrect(x0=-0.5, x1=zone_end, fillcolor=APPROVAL_ZONE, line_width=0, layer="below")
    fig.add_vline(x=zone_end, line=dict(color=REFERENCE_LINE, width=1, dash="dot"))
    fig.add_annotation(x=-0.45, y=1.0, yref="paper", xanchor="left", yanchor="top", showarrow=False,
                       text="Approvable", font=dict(size=11))
    fig.add_annotation(x=zone_end + 0.15, y=1.0, yref="paper", xanchor="left", yanchor="top", showarrow=False,
                       text="Held", font=dict(size=11))
    fig.update_layout(bargap=0.45)
    fig.update_xaxes(tickangle=0)
    fig.update_yaxes(rangemode="tozero", range=[0, max(counts.max(), 1) * 1.3], dtick=max(1, int(counts.max() // 4)))
    return _layout(fig)


def risk_breakdown(contributions: list[dict]) -> go.Figure:
    data = list(reversed(contributions))
    fig = go.Figure(go.Bar(x=[c["points"] for c in data], y=[c["title"] for c in data], orientation="h",
                           marker_color=SERIES_1, text=[f"+{c['points']}" for c in data], textposition="outside",
                           cliponaxis=False, customdata=[c["rule_id"] for c in data],
                           hovertemplate="%{y} (%{customdata})<br>+%{x} points<extra></extra>"))
    fig.update_layout(bargap=0.5)
    fig.update_xaxes(showgrid=False, showticklabels=False, range=[0, max([c["points"] for c in data] + [1]) * 1.2])
    fig.update_yaxes(showgrid=False)
    return _layout(fig, height=max(160, 38 * len(data) + 24))
