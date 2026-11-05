"""Company-name normalisation and comparison.

Why: the same legal entity is written many ways ("Acme Pvt. Ltd.", "ACME PRIVATE
LIMITED", "M/s Acme Private Ltd"). We normalise the benign variants first, then
fuzzy-compare what is left, so that real differences stand out.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

# Abbreviation -> canonical word. Applied token by token after punctuation removal.
_ABBREVIATIONS = {
    "pvt": "private",
    "pvt.": "private",
    "prv": "private",
    "ltd": "limited",
    "ltd.": "limited",
    "co": "company",
    "corp": "corporation",
    "inc": "incorporated",
    "intl": "international",
    "mfg": "manufacturing",
    "bros": "brothers",
    "svcs": "services",
    "tech": "technologies",
    "techs": "technologies",
}

# Legal-form words. They are compared separately (Ltd vs LLP is a real difference)
# and removed from the "core" name so they do not dominate the fuzzy score.
_LEGAL_FORMS = {"private", "limited", "public", "llp", "llc", "incorporated", "corporation",
                "company", "plc", "lp", "opc"}

_HONORIFICS = {"m/s", "ms", "messrs", "the"}


def normalise(name: str | None) -> str:
    """Lower-case, ASCII-fold, '&'->'and', drop punctuation, expand abbreviations."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    text = re.sub(r"\bm/s\b", " ", text)  # "M/s" is a courtesy prefix on Indian documents
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    tokens = [_ABBREVIATIONS.get(t, t) for t in text.split()]
    tokens = [t for t in tokens if t not in _HONORIFICS]
    return " ".join(tokens)


def core_and_form(name: str | None) -> tuple[str, frozenset[str]]:
    """Split a normalised name into (core words, legal-form words)."""
    tokens = normalise(name).split()
    core = [t for t in tokens if t not in _LEGAL_FORMS]
    form = frozenset(t for t in tokens if t in _LEGAL_FORMS)
    return " ".join(core) or " ".join(tokens), form


@dataclass(frozen=True)
class NameComparison:
    a: str
    b: str
    score: float  # 0-100
    band: str  # "match" | "ambiguous" | "mismatch"
    note: str


def compare_names(a: str | None, b: str | None, match_at: float = 95, ambiguous_at: float = 80) -> NameComparison:
    """Compare two names. Thresholds come from config/policy.yaml.

    Score = token_sort_ratio of the core names (word order does not matter).
    If both names state a legal form and the forms differ (Limited vs LLP), the
    score is capped just below the match threshold: that difference needs a human.
    """
    core_a, form_a = core_and_form(a)
    core_b, form_b = core_and_form(b)
    score = float(fuzz.token_sort_ratio(core_a, core_b))
    note = ""
    if form_a and form_b and form_a != form_b and score >= match_at:
        score = min(score, match_at - 1)
        note = f"legal form differs ({' '.join(sorted(form_a))} vs {' '.join(sorted(form_b))})"
    if score >= match_at:
        band = "match"
    elif score >= ambiguous_at:
        band = "ambiguous"
    else:
        band = "mismatch"
    return NameComparison(a or "", b or "", round(score, 1), band, note)
