"""Shared result type for every format validator."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    """Outcome of one format check.

    ok          - the value is structurally valid
    normalized  - cleaned-up value (upper-cased, separators removed) to store/compare
    reason      - human-readable explanation when not ok (shown to reviewers and vendors)
    soft        - True when a failure should only WARN (e.g. unknown bank code)
    """

    ok: bool
    normalized: str
    reason: str = ""
    soft: bool = False


def compact(value: str | None) -> str:
    """Upper-case and drop spaces, hyphens, dots and slashes — the usual typing noise."""
    return re.sub(r"[\s\-./]", "", (value or "").upper())
