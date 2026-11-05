"""IFSC bank codes (first 4 characters of an IFSC) for major Indian banks.

Source: Razorpay's open IFSC dataset (src/banknames.json), checked 2026-11-01.
A small local lookup is enough to catch "IFSC says HDFC, bank name says ICICI".
Unknown codes are a WARN (there are ~1,500 banks), never a hard failure.
"""

IFSC_BANK_CODES: dict[str, str] = {
    "SBIN": "State Bank of India",
    "HDFC": "HDFC Bank",
    "ICIC": "ICICI Bank",
    "UTIB": "Axis Bank",
    "KKBK": "Kotak Mahindra Bank",
    "PUNB": "Punjab National Bank",
    "BARB": "Bank of Baroda",
    "CNRB": "Canara Bank",
    "UBIN": "Union Bank of India",
    "IDIB": "Indian Bank",
    "YESB": "Yes Bank",
    "IDFB": "IDFC FIRST Bank",
    "INDB": "IndusInd Bank",
    "BKID": "Bank of India",
    "IOBA": "Indian Overseas Bank",
    "UCBA": "UCO Bank",
    "CBIN": "Central Bank of India",
    "MAHB": "Bank of Maharashtra",
    "PSIB": "Punjab and Sind Bank",
    "FDRL": "Federal Bank",
}

# Words that appear in many bank names and therefore say nothing about *which* bank.
_GENERIC = {"bank", "of", "the", "ltd", "limited", "and", "&", "india", "co", "operative"}


def _distinctive_tokens(name: str) -> set[str]:
    words = name.lower().replace(".", " ").replace(",", " ").split()
    return {w for w in words if w not in _GENERIC}


def bank_name_matches_code(bank_name: str, code: str) -> bool | None:
    """True/False if we know the code; None if the code is not in our lookup."""
    expected = IFSC_BANK_CODES.get(code.upper())
    if expected is None:
        return None
    given = _distinctive_tokens(bank_name)
    wanted = _distinctive_tokens(expected)
    # "SBI" is how most people write State Bank of India.
    if code.upper() == "SBIN" and "sbi" in given:
        return True
    return bool(given & wanted)
