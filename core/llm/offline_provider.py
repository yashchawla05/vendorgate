"""Offline provider: deterministic document reading without an LLM.

Used when no API key is configured, and by every automated test. It is honest
about its limits:
  * it reads only the PDF text layer - scans/photos come back as unreadable;
  * it classifies by keywords and extracts by label-anchored regular expressions;
  * it cannot judge borderline names, so it always answers "unsure" (-> human review);
  * emails come from a fixed template.
"""
from __future__ import annotations

import re

from core.documents.dates import to_iso_date
from core.documents.reader import DocumentContent
from core.documents.types import DOC_TYPES
from core.llm.base import Usage
from core.llm.schemas import DocumentUnderstanding, EmailDraft, ExtractedField, NameVerdict

LABELLED = 0.92  # value found next to its printed label
PATTERN = 0.85  # value found by its format alone (e.g. a GSTIN-shaped string)
INFERRED = 0.80  # value inferred from position (e.g. bank name = letterhead)

_BOILERPLATE = ("synthetic test document",)

RE_PAN = r"\b[A-Z]{3}[ABCFGHJLPT][A-Z][0-9]{4}[A-Z]\b"
RE_GSTIN = r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b"
RE_IFSC = r"\b[A-Z]{4}[0O][A-Z0-9]{6}\b"
RE_CIN = r"\b[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}\b"
RE_LLPIN = r"\b[A-Z]{3}-[0-9]{4}\b"
RE_EIN = r"\b[0-9]{2}-[0-9]{7}\b"
RE_SORT = r"\b[0-9]{2}-[0-9]{2}-[0-9]{2}\b"
RE_DATE = r"\b(\d{1,2}/\d{1,2}/\d{4}|\d{1,2} [A-Z][a-z]+ \d{4})\b"


# ---------------------------------------------------------------- helpers
def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not any(b in ln.lower() for b in _BOILERPLATE)]


def _field(name: str, value: str = "", confidence: float = 0.0, evidence: str = "") -> ExtractedField:
    value = (value or "").strip(" :.-\t")
    return ExtractedField(name=name, value=value, confidence=confidence if value else 0.0,
                          evidence=evidence.strip() if value else "")


def _labelled(lines: list[str], labels: list[str]) -> tuple[str, str]:
    """Find 'Label value' on one line, or 'LABEL' then value on the next line (stacked layout)."""
    for i, line in enumerate(lines):
        for lab in labels:
            m = re.match(rf"^{lab}\b[\s:]*", line, re.IGNORECASE)
            if not m:
                continue
            rest = line[m.end():].strip()
            if rest:
                return rest, line
            if i + 1 < len(lines):
                return lines[i + 1], f"{line} / {lines[i + 1]}"
    return "", ""


def _search(text: str, pattern: str, flags: int = 0, group: int = 0) -> tuple[str, str]:
    m = re.search(pattern, text, flags)
    if not m:
        return "", ""
    line = next((ln for ln in text.splitlines() if m.group(0) in ln), m.group(0))
    return m.group(group), line


def _date_field(name: str, raw: str, evidence: str, conf: float, us_format: bool = False) -> ExtractedField:
    raw = " ".join(raw.split())  # dates in paragraphs can wrap across lines
    m = re.search(RE_DATE, raw)
    iso = to_iso_date(m.group(1), us_format) if m else ""
    return _field(name, iso, conf, evidence)


def _letterhead(lines: list[str]) -> str:
    """First line of a letter = issuer (bank name on cheques and bank letters)."""
    return lines[0] if lines else ""


# ---------------------------------------------------------------- classification
def classify(text: str) -> tuple[str, float]:
    """Keyword vote. Two or more distinctive phrases = confident; one = tentative."""
    lower = text.lower()
    best, best_hits = "other", 0
    for key, doc in DOC_TYPES.items():
        hits = sum(1 for kw in doc.keywords if kw in lower)
        if hits > best_hits:
            best, best_hits = key, hits
    if best_hits >= 2:
        return best, 0.95
    if best_hits == 1:
        return best, 0.75
    return "other", 0.3


# ---------------------------------------------------------------- per-type extraction
def _extract(doc_type: str, text: str) -> list[ExtractedField]:
    lines = _lines(text)
    joined = "\n".join(lines)
    f: list[ExtractedField] = []

    if doc_type == "pan_card":
        v, ev = _labelled(lines, ["Permanent Account Number(?! Card)", "PAN"])
        m = re.search(RE_PAN, v) if v else None
        if m:
            f.append(_field("pan", m.group(0), LABELLED, ev))
        else:
            val, ev = _search(joined, RE_PAN)
            f.append(_field("pan", val, PATTERN, ev))
        v, ev = _labelled(lines, ["Name of holder", r"Name(?! of)"])
        f.append(_field("name", v, LABELLED, ev))
        v, ev = _labelled(lines, ["Date of Incorporation/Formation", "Date of birth / incorporation", "Date of birth"])
        f.append(_date_field("date", v, ev, LABELLED))

    elif doc_type == "gst_certificate":
        v, ev = _labelled(lines, ["Registration Number", "GSTIN"])
        m = re.search(RE_GSTIN, v)
        if m:
            f.append(_field("gstin", m.group(0), LABELLED, ev))
        else:
            val, ev = _search(joined, RE_GSTIN)
            f.append(_field("gstin", val, PATTERN, ev))
        f.append(_field("legal_name", *_swap(_labelled(lines, ["Legal Name of Business", "Legal Name"]))))
        f.append(_field("trade_name", *_swap(_labelled(lines, [r"Trade Name, if any", "Trade Name"]))))
        f.append(_field("address", *_swap(_labelled(lines, ["Address of Principal Place of Business",
                                                             "Principal Place of Business"]))))
        v, ev = _labelled(lines, ["Date of Liability", "Date of Registration"])
        f.append(_date_field("registration_date", v, ev, LABELLED))
        f.append(_field("constitution", *_swap(_labelled(lines, ["Constitution of Business"]))))

    elif doc_type == "no_gst_declaration":
        val, ev = _search(joined, r"I/We,\s*(.+?),\s*holding PAN", re.S, 1)
        f.append(_field("legal_name", " ".join(val.split()), LABELLED, ev))
        val, ev = _search(joined, RE_PAN)
        f.append(_field("pan", val, PATTERN, ev))
        v, ev = _labelled(lines, ["Date"])
        f.append(_date_field("declaration_date", v, ev, LABELLED))

    elif doc_type in ("cancelled_cheque", "bank_letter"):
        f.extend(_bank_fields(doc_type, lines, joined))

    elif doc_type == "incorporation_certificate":
        v, ev = _labelled(lines, [r"Name(?! of)"])
        if not v:
            v, ev = _search(joined, r"certify\s+that\s+(.+?)\s+is\s+incorporated", re.S, 1)
            v = " ".join(v.split())
        f.append(_field("company_name", v, LABELLED, ev))
        val, ev = _search(joined, RE_CIN)
        if not val:
            val, ev = _search(joined, RE_LLPIN)
        f.append(_field("cin", val, PATTERN, ev))
        v, ev = _labelled(lines, ["Date of Incorporation"])
        if not v:
            v, ev = _search(joined, r"incorporated on\s+(.+?)\s+under", re.S, 1)
        f.append(_date_field("incorporation_date", v, ev, LABELLED))

    elif doc_type == "w9":
        f.append(_field("name", *_swap(_labelled(lines, [r"1 Name of entity/individual"]))))
        f.append(_field("business_name", *_swap(_labelled(lines, [r"2 Business name/disregarded entity"]))))
        f.append(_field("tax_classification", *_swap(_labelled(lines, [r"3a Federal tax classification"]))))
        v, ev = _labelled(lines, [r"Part I\s+Employer identification number", "Employer identification number"])
        m = re.search(RE_EIN, v)
        f.append(_field("ein", m.group(0) if m else "", LABELLED, ev))
        street, ev1 = _labelled(lines, [r"5 Address"])
        city, ev2 = _labelled(lines, [r"6 City, state, and ZIP code"])
        f.append(_field("address", ", ".join(p for p in (street, city) if p), LABELLED, f"{ev1} {ev2}"))
        v, ev = _labelled(lines, [r"Date"])
        f.append(_date_field("signature_date", v, ev, LABELLED, us_format=True))

    elif doc_type == "company_registration_certificate":
        v, ev = _labelled(lines, ["Company name"])
        if not v:
            v, ev = _search(joined, r"certifies\s+that\s+(.+?)\s+is\s+this\s+day\s+incorporated", re.S, 1)
            v = " ".join(v.split())
        f.append(_field("company_name", v, LABELLED, ev))
        v, ev = _labelled(lines, ["Company Number"])
        f.append(_field("company_number", v.split()[0] if v else "", LABELLED, ev))
        v, ev = _labelled(lines, ["Date of incorporation"])
        if not v:
            v, ev = _search(joined, r"Cardiff, on\s+(.+)", 0, 1)
        f.append(_date_field("incorporation_date", v, ev, LABELLED))
    return f


def _swap(pair: tuple[str, str]) -> tuple[str, float, str]:
    """(value, evidence) -> (value, confidence, evidence) for labelled fields."""
    value, evidence = pair
    return value, LABELLED, evidence


def _bank_fields(doc_type: str, lines: list[str], joined: str) -> list[ExtractedField]:
    f = [_field("bank_name", _letterhead(lines), INFERRED, _letterhead(lines))]
    holder, ev = _labelled(lines, ["Account Holder Name", "Account holder", "For"])
    if not holder:
        holder, ev = _search(joined, r"confirm that\s+(.+?)\s+holds account", re.S, 1)
        holder = " ".join(holder.split())
    f.append(_field("account_holder", holder, LABELLED, ev))
    acct, ev = _labelled(lines, [r"A/c No\.?", "Account Number"])
    m = re.search(r"\d{6,18}", acct or "")
    if not m:
        acct, ev = _search(joined, r"account number\s+(\d{6,18})", re.I, 1)
        m = re.search(r"\d{6,18}", acct or "")
    f.append(_field("account_number", m.group(0) if m else "", LABELLED, ev))
    val, ev = _search(joined, RE_IFSC)
    f.append(_field("ifsc", val, PATTERN, ev))
    val, ev = _search(joined, r"Routing Number\)?\s*:?\s*(\d{9})", re.I, 1)
    f.append(_field("routing_number", val, LABELLED, ev))
    val, ev = _search(joined, RE_SORT)
    f.append(_field("sort_code", val, PATTERN, ev))
    if doc_type == "bank_letter":
        is_us = bool(re.search(r"routing", joined, re.I))
        date_line = next((ln for ln in lines[:4] if re.search(RE_DATE, ln)), "")
        f.append(_date_field("letter_date", date_line, date_line, LABELLED, us_format=is_us))
    return f


# ---------------------------------------------------------------- provider
class OfflineProvider:
    name = "offline"
    model = "rules-v1"

    def understand_document(self, content: DocumentContent, expected_types: list[str]) -> tuple[DocumentUnderstanding, Usage]:
        usage = Usage(provider=self.name, model=self.model, purpose="document")
        if not content.has_text:
            return DocumentUnderstanding(
                document_type="other", type_confidence=0.0, readable=False, fields=[], suspicious_instructions=False,
                notes="No text layer (scan or photo). Offline mode cannot read images; an LLM provider is required.",
            ), usage
        doc_type, type_conf = classify(content.text)
        fields = _extract(doc_type, content.text) if doc_type != "other" else []
        return DocumentUnderstanding(
            document_type=doc_type, type_confidence=type_conf, readable=True, fields=fields,
            suspicious_instructions=False, notes="",
        ), usage

    def adjudicate_names(self, name_a: str, name_b: str, context: str) -> tuple[NameVerdict, Usage]:
        verdict = NameVerdict(same_entity="unsure",
                              reason="Offline mode cannot judge borderline names; a human reviewer must decide.")
        return verdict, Usage(provider=self.name, model=self.model, purpose="names")

    def draft_email(self, payload: dict) -> tuple[EmailDraft, Usage]:
        from core.comms import template_email

        return template_email(payload), Usage(provider=self.name, model=self.model, purpose="email")
