"""Visual system: one CSS block + small HTML helpers (status chips, cards, page headers).

Kept in one place so every page looks the same and the palette is easy to change.
Look inspired by zamp.ai: white pages and near-black ink in Geist, a cream sidebar, flat cards
with hairline borders, small monospace labels, black pill buttons and active tabs, one blue
accent, and a soft pastel "aura" (lavender, sky, sage) behind each page title. Status colours
stay reserved for status.

Light and dark mode: Streamlit's own widgets take their colours from [theme.light] and
[theme.dark] in .streamlit/config.toml; the viewer switches with the Light / Dark buttons at the
top of every page (ui/topbar.py). Our HTML uses CSS light-dark(): Streamlit sets color-scheme on
the app to match the active theme, so the browser picks the right half at once, with no rerun.
Every text colour below meets WCAG AA contrast (4.5:1) in both themes; tests/test_theme.py checks it.
"""
from __future__ import annotations

import html

import streamlit as st

# CSS variable -> (light, dark). Page colours must equal backgroundColor in .streamlit/config.toml.
TOKENS = {
    "page": ("#FFFFFF", "#111111"),
    "surface": ("#FFFFFF", "#181818"),
    "text": ("#171717", "#EDEDED"),
    "muted": ("#6B6B6B", "#A3A3A3"),
    "label": ("#525252", "#B5B5B5"),
    "faint": ("#C4C4C4", "#4A4A4A"),  # placeholder dashes only, never content
    "border": ("#E8E8E6", "#2A2A2A"),
    "rule": ("#F0F0EE", "#222222"),
    "accent": ("#0050E0", "#7AA8FF"),
    "ink": ("#171717", "#F2F2F2"),         # pill buttons and active tabs
    "on-ink": ("#FFFFFF", "#111111"),      # text on those pills
}

# Status colours, inside content only. name -> ((light background, light text), (dark background, dark text))
PALETTE = {
    "neutral": (("#F0F0EE", "#4A4A4A"), ("#262626", "#B8B8B8")),
    "green": (("#E6F4EC", "#1D6B44"), ("#132E20", "#7ED3A2")),
    "amber": (("#FFF3DD", "#855600"), ("#352808", "#F0C46B")),
    "orange": (("#FDEBD8", "#9A4A00"), ("#3D2511", "#F5AE6E")),
    "red": (("#FDE8EC", "#A3203F"), ("#3D1720", "#F4A0B2")),
    "blue": (("#EDF4FF", "#0047C7"), ("#14233F", "#8DB4FF")),
    "violet": (("#F1ECFB", "#5B3A9E"), ("#2A2142", "#C9B5F2")),
    "quiet": (("#F5F5F4", "#68686A"), ("#1E1E1E", "#8E8E90")),
}


def ld(light: str, dark: str) -> str:
    """A CSS colour that follows the viewer's light/dark theme."""
    return f"light-dark({light}, {dark})"


def colors(name: str) -> tuple[str, str]:
    """(background, text) CSS colours of a palette entry."""
    (light_bg, light_fg), (dark_bg, dark_fg) = PALETTE[name]
    return ld(light_bg, dark_bg), ld(light_fg, dark_fg)


NEUTRAL = colors("neutral")
STATUS_COLORS = {key: colors(name) for key, name in {
    "APPROVED": "green", "PENDING": "amber", "REJECTED": "red", "RUNNING": "blue", "RECEIVED": "neutral"}.items()}
SEVERITY_COLORS = {key: colors(name) for key, name in {
    "INFO": "neutral", "WARN": "amber", "HIGH": "orange", "CRITICAL": "red"}.items()}
STAGE_COLORS = {key: colors(name) for key, name in {
    "passed": "green", "flagged": "amber", "failed": "red", "degraded": "violet", "skipped": "neutral",
    "running": "blue", "queued": "quiet", "done": "blue"}.items()}

MONO = '"Geist Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace'

_CSS = """
<style>
  :root { /*TOKENS*/ }
  .block-container { padding-top: 2.6rem; max-width: 1240px; }
  h1, h2, h3, h4 { letter-spacing: -0.02em; font-weight: 500 !important; }
  h1 { font-size: 2.1rem !important; }

  /* Page header: editorial title on a soft pastel aura (lavender, sky, sage), like zamp.ai's artwork. */
  .st-key-vg_hero { position: relative; overflow: hidden; border-radius: 16px; padding: 22px 28px 22px; gap: 4px;
      border: 1px solid var(--vg-border); margin-bottom: 6px;
      background: radial-gradient(60% 120% at 0% 0%, light-dark(#DCD2F5, #2A2342) 0%, transparent 60%),
                  radial-gradient(55% 130% at 62% 10%, light-dark(#C7DAF3, #1B2A40) 0%, transparent 62%),
                  radial-gradient(50% 120% at 100% 100%, light-dark(#D3DCC0, #262E1F) 0%, transparent 65%),
                  light-dark(#EEF0F6, #16181D); }
  .st-key-vg_hero [data-testid="stHeading"], .st-key-vg_hero [data-testid="stHeadingWithActionElements"] {
      margin: 0 !important; }
  .st-key-vg_hero h1 { color: light-dark(#171717, #F2F2F2) !important; padding: 0 0 6px 0 !important;
                       margin: 0 !important; line-height: 1.15 !important; letter-spacing: -0.035em; }
  .st-key-vg_hero .vg-hero-sub { color: light-dark(#4A4A4A, #C9C9C9); font-size: 0.98rem; max-width: 760px; }

  /* Sidebar: cream (light) / near-black (dark), colours in config.toml. */
  [data-testid="stSidebarNav"] span { font-size: 0.92rem; }
  [data-testid="stNavSectionHeader"] { font-family: /*MONO*/; text-transform: uppercase; letter-spacing: 0.08em;
                                        font-size: 0.7rem !important; color: var(--vg-muted) !important; }

  /* Cards, KPI tiles, tables: flat, hairline borders. */
  .vg-card { border: 1px solid var(--vg-border); border-radius: 12px; padding: 14px 16px; background: var(--vg-surface); }
  .vg-kpi { padding: 16px 18px; transition: border-color .15s ease; }
  .vg-kpi:hover { border-color: var(--vg-label); }
  .vg-kpi-label { font-family: /*MONO*/; font-size: 0.7rem; color: var(--vg-muted); text-transform: uppercase;
                  letter-spacing: 0.08em; }
  .vg-kpi-value { font-size: 1.85rem; font-weight: 500; color: var(--vg-text); line-height: 1.25;
                  letter-spacing: -0.03em; margin: 4px 0 2px; }
  .vg-kpi-sub { font-size: 0.8rem; color: var(--vg-muted); }
  .vg-chart-title { font-size: 1.02rem; font-weight: 500; color: var(--vg-text); letter-spacing: -0.01em; }
  .vg-chip { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.74rem; font-family: /*MONO*/;
             font-weight: 500; letter-spacing: 0.03em; white-space: nowrap; }
  .vg-banner { border-radius: 12px; padding: 16px 20px; margin-bottom: 8px; }
  .vg-banner h2 { margin: 0 0 4px 0; font-size: 1.25rem; }
  .vg-muted { color: var(--vg-muted); font-size: 0.85rem; }
  .vg-label-sim { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 0.7rem; font-weight: 600;
                  font-family: /*MONO*/; letter-spacing: 0.06em; }
  .vg-mono { font-family: /*MONO*/; font-size: 0.85rem; }
  .vg-table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
  .vg-table th { text-align: left; color: var(--vg-muted); font-weight: 500; border-bottom: 1px solid var(--vg-border);
                 padding: 6px 8px; font-family: /*MONO*/; font-size: 0.7rem; text-transform: uppercase;
                 letter-spacing: 0.06em; }
  .vg-table td { border-bottom: 1px solid var(--vg-rule); padding: 8px 8px; vertical-align: top; }
  .vg-scenario h4 { margin: 0 0 4px 0; font-size: 1.02rem; }

  /* Buttons: black pills with monospace labels (white pills in dark mode); secondary ones outlined. */
  [data-testid^="stBaseButton-primary"] { background: var(--vg-ink) !important; border: 1px solid var(--vg-ink) !important;
      color: var(--vg-on-ink) !important; border-radius: 999px !important; padding-left: 18px !important;
      padding-right: 18px !important; }
  [data-testid^="stBaseButton-primary"] * { color: var(--vg-on-ink) !important; }
  /* Labels only: an icon (":material/...:") must keep its icon font, or it shows as its name ("download"). */
  [data-testid^="stBaseButton-primary"] *:not([data-testid="stIconMaterial"]) { font-family: /*MONO*/; }
  [data-testid^="stBaseButton-primary"]:hover { opacity: 0.85; }
  [data-testid^="stBaseButton-secondary"], [data-testid^="stBaseLinkButton"] { border-radius: 999px !important; }
  [data-testid^="stBaseButton-secondary"] *:not([data-testid="stIconMaterial"]),
  [data-testid^="stBaseLinkButton"] *:not([data-testid="stIconMaterial"]) { font-family: /*MONO*/; }

  /* Tabs: pills; the active one is ink, like the highlighted chip on zamp.ai. */
  [data-testid="stTab"] { border-radius: 999px; padding: 4px 14px !important; }
  [data-testid="stTab"][aria-selected="true"] { background: var(--vg-ink); }
  [data-testid="stTab"][aria-selected="true"] p { color: var(--vg-on-ink) !important; }
  [data-testid="stTabs"] .react-aria-SelectionIndicator { display: none; }

  /* Plotly draws the 2px gap between stacked bar segments as a white outline: use the page colour. */
  .js-plotly-plot .barlayer .point path { stroke: var(--vg-page) !important; }

  /* The ⋮ menu: no theme choice there (the top bar has it), and no GitHub buttons from Streamlit Cloud. */
  [data-testid="stThemeSwitcher"], [data-testid="stThemeSwitcher"] + [data-testid="stMainMenuDivider"] {
      display: none !important; }
  [data-testid="stToolbarActionButton"]:has([aria-label*="github" i]),
  [data-testid="stToolbarActionButton"]:has([aria-label*="fork" i]) { display: none !important; }

  /* Top bar (ui/topbar.py): pinned into the header row, just left of Streamlit's own buttons. */
  @media (min-width: 641px) {
    .st-key-vg_topbar { position: fixed; top: 14px; right: var(--vg-header-right, 4.5rem); z-index: 999991;
                        width: auto !important; }
  }
  @media (max-width: 640px) { .st-key-vg_topbar { margin-top: 1.6rem; } }  /* phones: in the page, below the header */
  @media print { .st-key-vg_topbar { display: none !important; } }
  .vg-theme { display: inline-flex; gap: 2px; padding: 2px; border: 1px solid var(--vg-border); border-radius: 999px;
              background: var(--vg-surface); }
  .vg-theme button { display: inline-flex; align-items: center; gap: 6px; border: 0; margin: 0; padding: 2px 12px;
                     border-radius: 999px; font-family: /*MONO*/; font-size: 0.8rem; line-height: 1.55;
                     cursor: pointer; }
  .vg-icon { font-family: "Material Symbols Rounded"; font-size: 16px; line-height: 1; font-weight: 400;
             letter-spacing: normal; text-transform: none; white-space: nowrap; }
  .vg-theme button:focus-visible { outline: 2px solid var(--vg-accent); outline-offset: 1px; }
  /* The button for the theme on screen is the ink pill (AA contrast in both themes). */
  .vg-theme-light { background: light-dark(#171717, transparent); color: light-dark(#FFFFFF, #A3A3A3); }
  .vg-theme-dark { background: light-dark(transparent, #F2F2F2); color: light-dark(#6B6B6B, #111111); }
  .st-key-vg_topbar [data-testid="stPageLink"] a { border: 1px solid var(--vg-border); border-radius: 999px;
      background: var(--vg-surface); height: 30px; min-height: 0; padding: 0 14px; box-sizing: border-box;
      display: flex; align-items: center; }
  .st-key-vg_topbar [data-testid="stPageLink"] p { font-family: /*MONO*/; font-size: 0.8rem; }
</style>
""".replace("/*TOKENS*/", " ".join(f"--vg-{name}: {ld(*pair)};" for name, pair in TOKENS.items())) \
   .replace("/*MONO*/", MONO)


def apply_theme() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def chip(text: str, palette: dict[str, tuple[str, str]] | None = None, key: str | None = None) -> str:
    """Return HTML for a coloured pill. `key` selects the colour (defaults to text)."""
    palette = palette or STATUS_COLORS
    bg, fg = palette.get(key or text, NEUTRAL)
    return f'<span class="vg-chip" style="background:{bg};color:{fg}">{html.escape(text)}</span>'


def status_chip(status: str) -> str:
    return chip(status, STATUS_COLORS)


def severity_chip(severity: str) -> str:
    return chip(severity, SEVERITY_COLORS)


def stage_chip(stage_status: str) -> str:
    return chip(stage_status.upper(), STAGE_COLORS, key=stage_status)


def simulated_label(text: str = "SIMULATED") -> str:
    bg, fg = colors("violet")
    return f'<span class="vg-label-sim" style="background:{bg};color:{fg}">{html.escape(text)}</span>'


def kpi(label: str, value: str, sub: str = "") -> None:
    st.markdown(
        f'<div class="vg-card vg-kpi"><div class="vg-kpi-label">{html.escape(label)}</div>'
        f'<div class="vg-kpi-value">{html.escape(value)}</div>'
        f'<div class="vg-kpi-sub">{html.escape(sub)}</div></div>',
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str = "") -> None:
    """Title on the pastel aura (still a real st.title, so tests and screen readers see it)."""
    with st.container(key="vg_hero"):
        st.title(title)
        if subtitle:
            st.markdown(f'<div class="vg-hero-sub">{html.escape(subtitle)}</div>', unsafe_allow_html=True)
