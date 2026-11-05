"""Light and dark mode: both palettes are configured, our colours stay readable in both, and no page
hard-codes a colour that would break when the viewer switches theme."""
import re
import tomllib

import pytest

from core.config import ROOT
from ui import charts
from ui.theme import _CSS, PALETTE, TOKENS


def contrast(a: str, b: str) -> float:
    def luminance(hex_colour: str) -> float:
        channels = [int(hex_colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        r, g, b_ = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_config_defines_light_and_dark_themes_matching_our_page_colours():
    theme = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))["theme"]
    assert "base" not in theme  # a single base theme would hide the light/dark switch in the menu
    light, dark = TOKENS["page"]
    assert theme["light"]["backgroundColor"] == light and theme["dark"]["backgroundColor"] == dark
    assert f"--vg-page: light-dark({light}, {dark})" in _CSS


@pytest.mark.parametrize("mode", [0, 1], ids=["light", "dark"])
def test_text_colours_meet_wcag_aa_in_both_themes(mode):
    for name in ("text", "muted", "label"):
        for ground in ("page", "surface"):
            assert contrast(TOKENS[name][mode], TOKENS[ground][mode]) >= 4.5, (name, ground)
    for name, pairs in PALETTE.items():
        bg, fg = pairs[mode]
        assert contrast(fg, bg) >= 4.5, name


def test_chart_marks_are_visible_on_the_dark_page():
    dark_page = TOKENS["page"][1]
    for colour in [*charts.STATUS.values(), charts.SERIES_1, charts.REFERENCE_LINE]:
        assert contrast(colour, dark_page) >= 3, colour


def test_pages_do_not_hard_code_colours():
    files = [ROOT / "ui" / "widgets.py", ROOT / "ui" / "topbar.py", *sorted((ROOT / "views").glob("*.py"))]
    for path in files:
        assert not re.findall(r"#[0-9A-Fa-f]{6}\b", path.read_text(encoding="utf-8")), path.name


def test_theme_lives_in_the_top_bar_not_the_menu():
    assert '[data-testid="stThemeSwitcher"]' in _CSS and "display: none" in _CSS


def test_run_screens_name_the_provider_without_model_ids():
    from ui.widgets import provider_label

    assert provider_label("gemini") == "Google Gemini"
    assert provider_label("anthropic") == "Anthropic Claude"
    for path in (ROOT / "views" / "live_run.py", ROOT / "ui" / "widgets.py"):
        assert "provider.model" not in path.read_text(encoding="utf-8") and "get('model')" not in path.read_text(encoding="utf-8")


def test_wildcard_font_rules_leave_icons_alone():
    # Streamlit icons (":material/download:") are a ligature font: a font-family rule that reaches them
    # prints the icon's name over the label ("download" on top of "Download CV").
    css = re.sub(r"/\*.*?\*/", "", _CSS, flags=re.S)
    for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        if "font-family" in body and "*" in selector:
            for part in selector.split(","):
                assert ":not([data-testid=\"stIconMaterial\"])" in part, part.strip()
