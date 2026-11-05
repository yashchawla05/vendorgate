"""Sanctions screening against a committed OFAC snapshot (US lists only).

Design (tuned on the real 2026-10-28 list):
  * Screen entity and individual names (primary + aliases). Vessels/aircraft are irrelevant to vendors.
  * Normalise both sides and strip legal-form words (LTD, PVT, LLC...), which carry no identity.
  * Score = max(token_sort_ratio, ratio with spaces removed). WRatio/token_set were rejected:
    they score ~86+ for almost any two company names and would flag every vendor.
  * False-positive gates: very short names need an exact match; candidates that share no
    distinctive word are capped below the review threshold.
  * The decision is deterministic. An LLM is never consulted here.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from core.config import SANCTIONS_DIR

_LEGAL_FORMS = set(
    "LTD LIMITED LLC INC INCORPORATED CO COMPANY CORP CORPORATION PVT PRIVATE PLC GMBH SA SAS SARL SRL "
    "SPA AG BV NV JSC OJSC CJSC PJSC PAO OAO ZAO AO OOO TOO LLP LP FZE FZCO FZC DMCC PTE PTY BHD KG KFT "
    "EOOD DOO SL SE AB AS OY THE AND OF DE".split()
)
# Common business words: kept in the match string, but sharing only these is not evidence of identity.
_GENERIC = set(
    "TRADING TRADE TRADERS INTERNATIONAL INTL GROUP HOLDING HOLDINGS INDUSTRIES INDUSTRIAL INDUSTRY "
    "ENTERPRISE ENTERPRISES SERVICES SERVICE GENERAL GLOBAL SOLUTIONS TECHNOLOGIES TECHNOLOGY TECH IMPORT "
    "EXPORT IMPEX LOGISTICS SHIPPING INVESTMENT INVESTMENTS DEVELOPMENT MANAGEMENT CONSULTING PARTNERS "
    "VENTURES BANK NATIONAL".split()
)


def normalise(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().upper()
    text = text.replace("&", " AND ")
    text = re.sub(r"[.']", "", text)
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    tokens = text.split()
    core = [t for t in tokens if t not in _LEGAL_FORMS]
    return " ".join(core or tokens)  # if everything was a legal word, keep the original


def _distinctive(tokens: list[str]) -> set[str]:
    return {t for t in tokens if t not in _GENERIC and len(t) > 1}


def composite_score(query: str, candidate: str) -> float:
    """Both inputs already normalised."""
    return max(
        fuzz.token_sort_ratio(query, candidate),
        fuzz.ratio(query.replace(" ", ""), candidate.replace(" ", "")),
    )


def gated_score(query: str, candidate: str) -> float:
    score = composite_score(query, candidate)
    # Gate 1: short names ("HAWK", "M23") collide with everything; demand an exact match.
    if len(query.replace(" ", "")) < 6 or len(candidate.replace(" ", "")) < 6:
        return 100.0 if query.replace(" ", "") == candidate.replace(" ", "") else min(score, 60.0)
    # Gate 2: no distinctive word in common and distinctive parts not alike -> not the same party.
    q_dist, c_dist = _distinctive(query.split()), _distinctive(candidate.split())
    if not (q_dist & c_dist):
        joined = fuzz.ratio(" ".join(sorted(q_dist)), " ".join(sorted(c_dist)))
        if joined < 85:
            score = min(score, 84.0)
    return float(score)


@dataclass(frozen=True)
class Entry:
    norm: str
    display: str
    list_name: str  # "SDN" or "Non-SDN Consolidated"
    ent_num: str
    sdn_type: str
    program: str
    is_alias: bool


@dataclass(frozen=True)
class Hit:
    query: str
    score: float
    entry: Entry


def _read_gz_csv(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    text = gzip.decompress(path.read_bytes()).decode("utf-8", errors="replace")
    rows = []
    for row in csv.reader(io.StringIO(text, newline="")):
        cleaned = [c.strip() for c in row]
        rows.append([None if c == "-0-" else c for c in cleaned])  # -0- is OFAC's null marker
    return rows


def _load_list(prim_file: str, alt_file: str, list_name: str) -> list[Entry]:
    entries: list[Entry] = []
    primaries: dict[str, tuple[str, str]] = {}
    for row in _read_gz_csv(SANCTIONS_DIR / prim_file):
        if len(row) != 12 or not row[1]:
            continue  # skips the trailing Ctrl-Z line
        sdn_type = row[2] or "entity"  # entities have no type string in the CSV
        if sdn_type not in ("entity", "individual"):
            continue  # vessels and aircraft are not vendors
        primaries[row[0]] = (sdn_type, row[3] or "")
        entries.append(Entry(normalise(row[1]), row[1], list_name, row[0], sdn_type, row[3] or "", False))
    for row in _read_gz_csv(SANCTIONS_DIR / alt_file):
        if len(row) != 5 or not row[3] or row[0] not in primaries:
            continue
        sdn_type, program = primaries[row[0]]
        entries.append(Entry(normalise(row[3]), row[3], list_name, row[0], sdn_type, program, True))
    return entries


@lru_cache(maxsize=1)
def load_index() -> tuple[Entry, ...]:
    entries = _load_list("sdn.csv.gz", "alt.csv.gz", "SDN")
    entries += _load_list("cons_prim.csv.gz", "cons_alt.csv.gz", "Non-SDN Consolidated")
    return tuple(e for e in entries if e.norm)


@lru_cache(maxsize=1)
def snapshot_meta() -> dict:
    path = SANCTIONS_DIR / "meta.json"
    return json.loads(path.read_text()) if path.exists() else {}


def screen(name: str, review_threshold: float = 85.0, limit: int = 5) -> list[Hit]:
    """Return the best hits scoring >= review_threshold, highest first."""
    query = normalise(name)
    if not query:
        return []
    index = load_index()
    norms = [e.norm for e in index]
    nospace = [n.replace(" ", "") for n in norms]
    # Fast C-level prefilter on both halves of the composite, then the exact gated score.
    candidates = {i for _, _, i in process.extract(query, norms, scorer=fuzz.token_sort_ratio, limit=40, score_cutoff=70)}
    candidates |= {i for _, _, i in process.extract(query.replace(" ", ""), nospace, scorer=fuzz.ratio, limit=40, score_cutoff=70)}
    hits = [Hit(name, gated_score(query, index[i].norm), index[i]) for i in candidates]
    hits = [h for h in hits if h.score >= review_threshold]
    hits.sort(key=lambda h: (-h.score, h.entry.is_alias))
    # One hit per listed party is enough for a reviewer.
    seen, unique = set(), []
    for h in hits:
        key = (h.entry.list_name, h.entry.ent_num)
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return unique[:limit]
