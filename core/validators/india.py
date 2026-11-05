"""Indian identifier validators: PAN, GSTIN, IFSC, bank account, CIN.

All checks are offline and structural. They prove a value is well-formed, not
that it exists — existence needs a registry lookup (see core/registry.py).
"""
from __future__ import annotations

import re

from core.reference.gst_states import GST_STATE_CODES, LEGACY_OR_SPECIAL_CODES
from core.reference.ifsc_banks import bank_name_matches_code
from core.validators.common import Check, compact

# 4th character of a PAN = holder status (Income Tax Department list).
PAN_HOLDER_TYPES = {
    "A": "Association of Persons",
    "B": "Body of Individuals",
    "C": "Company",
    "F": "Firm / LLP",
    "G": "Government agency",
    "H": "Hindu Undivided Family",
    "J": "Artificial juridical person",
    "L": "Local authority",
    "P": "Individual",
    "T": "Trust",
}

# Which PAN holder letters are acceptable for each entity type on our form.
ENTITY_TO_PAN_LETTERS = {
    "company": {"C"},
    "llp_partnership": {"F"},
    "proprietorship": {"P"},  # a proprietor uses their personal PAN
    "other": set(PAN_HOLDER_TYPES),  # trusts, HUFs, etc. — not checked
}

_PAN_RE = re.compile(r"^[A-Z]{3}[ABCFGHJLPT][A-Z][0-9]{4}[A-Z]$")
_GSTIN_SHAPE_RE = re.compile(r"^[0-9]{2}[A-Z]{3}[ABCFGHJLPT][A-Z][0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_ACCOUNT_RE = re.compile(r"^[0-9]{9,18}$")
_CIN_RE = re.compile(r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")
_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


# ---------------------------------------------------------------- PAN
def validate_pan(value: str | None) -> Check:
    pan = compact(value)
    if not pan:
        return Check(False, pan, "PAN is empty")
    if len(pan) != 10:
        return Check(False, pan, f"PAN must be 10 characters, got {len(pan)}")
    if not _PAN_RE.match(pan):
        if pan[3:4].isalpha() and pan[3] not in PAN_HOLDER_TYPES:
            return Check(False, pan, f"4th character '{pan[3]}' is not a valid PAN holder type")
        return Check(False, pan, "PAN must be 5 letters, 4 digits, 1 letter (e.g. ZZZCZ0001Z)")
    return Check(True, pan)


def pan_holder_type(pan: str) -> str | None:
    """Return the holder type described by the 4th letter, e.g. 'Company'."""
    pan = compact(pan)
    return PAN_HOLDER_TYPES.get(pan[3]) if len(pan) >= 4 else None


def pan_matches_entity(pan: str, entity_type: str) -> bool:
    allowed = ENTITY_TO_PAN_LETTERS.get(entity_type, set(PAN_HOLDER_TYPES))
    pan = compact(pan)
    return len(pan) == 10 and pan[3] in allowed


# ---------------------------------------------------------------- GSTIN
def gstin_check_char(first14: str) -> str:
    """GSTIN check character (Luhn mod 36).

    Map 0-9A-Z to 0-35; weight the 14 characters 1,2,1,2,... from the left;
    for each product add (product // 36) + (product % 36); the check value is
    (36 - total % 36) % 36, mapped back to a character.
    """
    total = 0
    for i, ch in enumerate(first14):
        product = _B36.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _B36[(36 - total % 36) % 36]


def validate_gstin(value: str | None) -> Check:
    gstin = compact(value)
    if not gstin:
        return Check(False, gstin, "GSTIN is empty")
    if len(gstin) != 15:
        return Check(False, gstin, f"GSTIN must be 15 characters, got {len(gstin)}")
    state = gstin[:2]
    if state in LEGACY_OR_SPECIAL_CODES:
        return Check(False, gstin, f"State code {state} is not valid for a vendor GSTIN: {LEGACY_OR_SPECIAL_CODES[state]}")
    if state not in GST_STATE_CODES:
        return Check(False, gstin, f"State code {state} is not a GST state code")
    if gstin[13] != "Z":
        return Check(False, gstin, "14th character must be 'Z' for a regular taxpayer (TDS/TCS/OIDAR GSTINs are not accepted)")
    if not _GSTIN_SHAPE_RE.match(gstin):
        return Check(False, gstin, "GSTIN must be state code + PAN + entity number + 'Z' + check character")
    expected = gstin_check_char(gstin[:14])
    if gstin[14] != expected:
        return Check(False, gstin, f"Check character is '{gstin[14]}' but should be '{expected}' — likely a typo")
    return Check(True, gstin)


def gstin_embedded_pan(gstin: str) -> str:
    return compact(gstin)[2:12]


def gstin_state(gstin: str) -> str | None:
    return GST_STATE_CODES.get(compact(gstin)[:2])


# ---------------------------------------------------------------- Bank
def validate_ifsc(value: str | None) -> Check:
    ifsc = compact(value)
    if not ifsc:
        return Check(False, ifsc, "IFSC is empty")
    if len(ifsc) != 11:
        return Check(False, ifsc, f"IFSC must be 11 characters, got {len(ifsc)}")
    if ifsc[4] != "0":
        return Check(False, ifsc, f"5th character of an IFSC is always '0', got '{ifsc[4]}'")
    if not _IFSC_RE.match(ifsc):
        return Check(False, ifsc, "IFSC must be 4 letters (bank), '0', then 6 letters/digits (branch)")
    return Check(True, ifsc)


def check_ifsc_bank(ifsc: str, bank_name: str) -> Check:
    """Soft check that the IFSC's bank code agrees with the declared bank name."""
    code = compact(ifsc)[:4]
    verdict = bank_name_matches_code(bank_name or "", code)
    if verdict is None:
        return Check(True, code, f"Bank code {code} not in local lookup; not checked", soft=True)
    if not verdict:
        return Check(False, code, f"IFSC bank code {code} does not belong to '{bank_name}'", soft=True)
    return Check(True, code)


def validate_in_account(value: str | None) -> Check:
    # Account numbers are strings: leading zeros matter.
    acct = re.sub(r"[\s\-]", "", value or "")
    if not acct:
        return Check(False, acct, "Account number is empty")
    if not _ACCOUNT_RE.match(acct):
        return Check(False, acct, "Indian account numbers are 9-18 digits")
    return Check(True, acct)


def validate_cin(value: str | None) -> Check:
    cin = compact(value)
    if not _CIN_RE.match(cin):
        return Check(False, cin, "CIN must be 21 characters, e.g. U72200KA2019PTC123456")
    return Check(True, cin)
