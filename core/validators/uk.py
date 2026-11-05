"""UK identifier validators: sort code, account number, VAT number, company number."""
from __future__ import annotations

import re

from core.validators.common import Check, compact

_CRN_PREFIXES = (
    "AC ZC FC GE LP OC SE SA SZ SF GS SL SO SC ES NA NZ NF GN NL NC R0 NI EN IP SP IC SI NP NV RC SR "
    "NR NO CE CS PC RS SG FE".split()
)


def validate_sort_code(value: str | None) -> Check:
    digits = re.sub(r"[\s\-]", "", value or "")
    if not re.fullmatch(r"[0-9]{6}", digits):
        return Check(False, digits, "Sort code must be 6 digits (NN-NN-NN)")
    return Check(True, f"{digits[:2]}-{digits[2:4]}-{digits[4:]}")


def validate_uk_account(value: str | None) -> Check:
    digits = re.sub(r"[\s\-]", "", value or "")
    if not re.fullmatch(r"[0-9]{6,10}", digits):
        return Check(False, digits, "UK account numbers are 8 digits")
    if len(digits) in (6, 7):
        # Standard practice: shorter legacy numbers are left-padded to 8.
        return Check(True, digits.zfill(8))
    if len(digits) in (9, 10):
        # Real (Santander, NatWest, Co-op…) but converted by bank-specific rules we do not implement.
        return Check(False, digits, "9-10 digit account needs bank-specific conversion; manual review", soft=True)
    return Check(True, digits)


def _vat_remainder(nine: str) -> int:
    weights = [8, 7, 6, 5, 4, 3, 2]
    total = sum(int(d) * w for d, w in zip(nine[:7], weights)) + int(nine[7:9])
    return total % 97


def validate_uk_vat(value: str | None) -> Check:
    vat = compact(value)
    if vat.startswith(("GB", "XI")):
        prefix, body = vat[:2], vat[2:]
    else:
        prefix, body = "GB", vat
    normalized = prefix + body
    if re.fullmatch(r"GD[0-4][0-9]{2}|HA[5-9][0-9]{2}", body):
        return Check(True, normalized)  # government / health authority numbers: no checksum
    if not re.fullmatch(r"[0-9]{9}|[0-9]{12}", body):
        return Check(False, normalized, "UK VAT number must be GB followed by 9 (or 12) digits")
    remainder = _vat_remainder(body[:9])
    # Two HMRC schemes (mod 97 and the newer 9755); follow python-stdnum's accepted remainders.
    valid = remainder == 0 or (int(body[:3]) >= 100 and remainder in (42, 55))
    if not valid:
        # Soft: the algorithm is not officially published and HMRC's own test numbers fail it.
        return Check(False, normalized, "VAT number fails the HMRC check-digit test — please re-check", soft=True)
    return Check(True, normalized)


def validate_company_number(value: str | None) -> Check:
    crn = compact(value)
    if crn.isdigit() and len(crn) <= 8:
        crn = crn.zfill(8)
    if re.fullmatch(r"[0-9]{8}", crn):
        return Check(True, crn)
    if len(crn) == 8 and crn[:2] in _CRN_PREFIXES and crn[2:].isdigit():
        return Check(True, crn)
    return Check(False, crn, "Company number must be 8 digits, or a 2-letter prefix (e.g. SC, NI, OC) + 6 digits")
