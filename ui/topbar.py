"""The bar at the top of every page, beside Streamlit's own header buttons (Share and ⋮ on Streamlit
Cloud): a Light / Dark switch and a link to the About me page.

Streamlit has no Python call that changes the theme, so the two buttons use Streamlit's own theme
items in the ⋮ menu through a few lines of JavaScript, with the menu kept invisible while they do
(ui/theme.py hides those items from the menu, so this bar is the only theme control). The last
choice is saved in the browser and re-applied on every page, because Streamlit itself remembers
it per page address. Which button is highlighted
follows the theme actually on screen (CSS light-dark(), see ui/theme.py), so it is never out of step.
Positioning and styles: .st-key-vg_topbar and .vg-theme in ui/theme.py.
"""
from __future__ import annotations

import streamlit as st

# st.html strips <svg>, so icons use the Material Symbols font Streamlit already loads for its own icons.
_SUN = '<span class="vg-icon" aria-hidden="true" translate="no">light_mode</span>'
_MOON = '<span class="vg-icon" aria-hidden="true" translate="no">dark_mode</span>'

_SCRIPT = """
<script>
(() => {
  if (window.vgThemeSwitch) return;  // once per page load: reruns and page changes keep it
  const q = (selector) => document.querySelector(selector);
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const KEY = "vendorgate-theme";
  const MENU = '[data-testid="stMainMenuButton"]';
  const POPOVER = '[data-testid="stMainMenuPopover"]';
  const ITEM = "stMainMenuItem-theme-";
  const saved = { get() { try { return localStorage.getItem(KEY); } catch (e) { return null; } },
                  set(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* storage blocked */ } } };

  async function waitFor(selector, tries) {
    for (let i = 0; i < (tries || 80); i++) {
      const el = q(selector);
      if (el) return el;
      await sleep(25);
    }
    return null;
  }

  // Select System, Light or Dark in Streamlit's own menu without showing the menu.
  let busy = false;
  async function choose(label) {
    const menu = await waitFor(MENU);
    if (!menu || busy) return;
    busy = true;
    const focused = document.activeElement;
    const hide = document.createElement("style");
    hide.textContent = POPOVER + "{opacity:0 !important;pointer-events:none !important}";
    document.head.appendChild(hide);
    try {
      menu.click();
      const item = await waitFor('[data-testid="' + ITEM + label + '"]');
      if (item && item.getAttribute("aria-checked") !== "true") item.click();
    } finally {
      await sleep(30);
      if (q(POPOVER)) menu.click();
      setTimeout(() => hide.remove(), 200);
      if (focused && focused.focus) focused.focus();
      busy = false;
    }
  }

  document.addEventListener("click", (event) => {
    const mine = event.target.closest("[data-vg-theme]");
    if (!mine) return;
    saved.set(mine.dataset.vgTheme);
    choose(mine.dataset.vgTheme);
  }, true);

  // Sit just left of the header buttons (Share, ⋮), wherever they are.
  function place() {
    const parts = ['[data-testid="stToolbarActions"]', '[data-testid="stMainMenu"]'].map(q)
      .filter((el) => el && el.getBoundingClientRect().width > 0);
    if (!parts.length) return;
    const left = Math.min(...parts.map((el) => el.getBoundingClientRect().left));
    document.documentElement.style.setProperty("--vg-header-right", Math.max(0, window.innerWidth - left + 8) + "px");
  }
  waitFor('[data-testid="stHeader"]', 400).then((header) => {
    if (!header) return;
    new ResizeObserver(place).observe(header);
    new MutationObserver(place).observe(header, { childList: true, subtree: true });
    place();
  });
  window.addEventListener("resize", place);

  window.vgThemeSwitch = { choose, place };
  const last = saved.get();
  if (last) choose(last);
})();
</script>
"""

SWITCH_HTML = (
    '<div class="vg-theme" role="group" aria-label="Colour theme">'
    f'<button type="button" class="vg-theme-light" data-vg-theme="Light" title="Light mode">{_SUN}<span>Light</span>'
    '</button>'
    f'<button type="button" class="vg-theme-dark" data-vg-theme="Dark" title="Dark mode">{_MOON}<span>Dark</span>'
    '</button></div>' + _SCRIPT
)


def top_bar(about_page) -> None:
    """Theme switch + About me link; ui/theme.py pins it into the header row on wide screens."""
    with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small",
                      key="vg_topbar"):
        st.html(SWITCH_HTML, width="content", unsafe_allow_javascript=True)
        st.page_link(about_page, label="About me", icon=":material/person:")
