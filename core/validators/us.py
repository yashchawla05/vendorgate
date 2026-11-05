"""US identifier validators: EIN and ABA routing number."""
from __future__ import annotations

import re

from core.reference.ein_prefixes import VALID_EIN_PREFIXES
from core.validators.common import Check


def validate_ein(value: str | None) -> Check:
    digits = re.sub(r"[\s\-]", "", value or "")
    if not re.fullmatch(r"[0-9]{9}", digits):
        return Check(False, digits, "EIN must be 9 digits (NN-NNNNNNN)")
    normalized = f"{digits[:2]}-{digits[2:]}"
    if digits[:2] not in VALID_EIN_PREFIXES:
        return Check(False, normalized, f"EIN prefix {digits[:2]} has never been issued by the IRS")
    return Check(True, normalized)


def _aba_prefix_ok(prefix: int) -> bool:
    # 00-12 Federal Reserve/government, 21-32 thrifts, 61-72 electronic, 80 traveller's cheques.
    return 0 <= prefix <= 12 or 21 <= prefix <= 32 or 61 <= prefix <= 72 or prefix == 80


def aba_checksum_ok(routing: str) -> bool:
    """3-7-1 weighted checksum: the weighted digit sum must be a multiple of 10."""
    d = [int(c) for c in routing]
    total = 3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])
    return total % 10 == 0


def validate_aba(value: str | None) -> Check:
    routing = re.sub(r"[\s\-]", "", value or "")
    if not re.fullmatch(r"[0-9]{9}", routing):
        return Check(False, routing, "ABA routing number must be 9 digits")
    if not _aba_prefix_ok(int(routing[:2])):
        return Check(False, routing, f"Routing prefix {routing[:2]} is not a valid Federal Reserve range")
    if not aba_checksum_ok(routing):
        return Check(False, routing, "Routing number fails the 3-7-1 checksum — likely a typo")
    return Check(True, routing)


def validate_us_account(value: str | None) -> Check:
    acct = re.sub(r"[\s\-]", "", value or "")
    # US account numbers have no national format; 4-17 digits covers practice.
    if not re.fullmatch(r"[0-9]{4,17}", acct):
        return Check(False, acct, "US account numbers are 4-17 digits")
    return Check(True, acct)
