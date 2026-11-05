"""Dates as printed on documents -> ISO (YYYY-MM-DD). Deterministic and shared by every provider.

Providers copy dates exactly as printed, and this code converts them. The conversion is not left to
the model because "10/02/2026" is 2 October on a US bank letter and 10 February on an Indian one: an
eval run showed a model guessing day-first on US letters. The document's own identifiers say which
convention applies (month_first). A date that cannot be understood gets confidence 0 in S3, which
makes it a weak key field (DOC-003) instead of a silently skipped check.
"""
from __future__ import annotations

import re
from datetime import datetime

DATE_FIELDS = frozenset({"date", "registration_date", "declaration_date", "letter_date", "incorporation_date",
                         "signature_date"})

_DAY_FIRST = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"]
_MONTH_FIRST = ["%m/%d/%Y", "%m-%d-%Y", "%m.%d.%Y"]
_UNAMBIGUOUS = ["%Y-%m-%d", "%Y/%m/%d", "%d %B %Y", "%d %b %Y", "%d-%b-%Y", "%d-%B-%Y", "%B %d, %Y", "%b %d, %Y",
                "%B %d %Y", "%b %d %Y"]


US_MARKERS = ("routing_number", "ein")
NON_US_MARKERS = ("ifsc", "sort_code", "gstin", "pan", "cin", "company_number")


def month_first(doc_type: str, values: dict[str, str], country: str = "") -> bool:
    """US documents write NN/NN/NNNN month first. The document's own identifiers decide; the declared
    country only breaks the tie for a document that carries none."""
    if doc_type == "w9" or any(values.get(k) for k in US_MARKERS):
        return True
    if any(values.get(k) for k in NON_US_MARKERS):
        return False
    return country == "US"


def to_iso_date(raw: str, us_format: bool = False) -> str:
    """Parse a printed date; '' if unparseable. Ambiguous NN/NN/NNNN is month-first only for US documents."""
    raw = " ".join(raw.replace("Date:", "").split()).strip(" .,")
    raw = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", raw)  # "2nd October 2026" -> "2 October 2026"
    formats = _UNAMBIGUOUS + (_MONTH_FIRST + _DAY_FIRST if us_format else _DAY_FIRST + _MONTH_FIRST)
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return ""
