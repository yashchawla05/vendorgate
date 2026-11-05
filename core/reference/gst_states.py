"""GST state codes (first two digits of a GSTIN).

Source: GSTN e-way bill API state-code table (docs.ewaybillgst.gov.in/apidocs/state-code.html)
and the e-invoice master (einvoice1.gst.gov.in/Others/MasterCodes), checked 2026-11-01.

Deliberately NOT valid for a new vendor's GSTIN:
  25 Daman & Diu  - GSTINs cancelled 31-Jul-2020 and reissued under 26 (merged UT)
  28              - old undivided Andhra Pradesh, never used for GST registrations
  96 / 99         - foreign / OIDAR registrations, never a normal-taxpayer GSTIN
"""

GST_STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
}

LEGACY_OR_SPECIAL_CODES: dict[str, str] = {
    "25": "Daman and Diu (legacy code, cancelled 2020; use 26)",
    "28": "Andhra Pradesh (pre-2014 code, not used for GST)",
    "96": "Other country (place-of-supply code, not a GSTIN prefix)",
    "99": "Centre jurisdiction / OIDAR (not a normal-taxpayer GSTIN)",
}

# Common alternative spellings people type into an address form.
_STATE_ALIASES = {
    "orissa": "Odisha",
    "pondicherry": "Puducherry",
    "nct of delhi": "Delhi",
    "new delhi": "Delhi",
    "j&k": "Jammu and Kashmir",
    "jammu & kashmir": "Jammu and Kashmir",
    "uttaranchal": "Uttarakhand",
    "andaman & nicobar islands": "Andaman and Nicobar Islands",
}


def canonical_state(name: str) -> str | None:
    """Map a free-text state name to the canonical GST state name (or None)."""
    key = " ".join(name.lower().replace("&", "and").split())
    alias = _STATE_ALIASES.get(" ".join(name.lower().split()))
    if alias:
        return alias
    for state in GST_STATE_CODES.values():
        if state.lower() == key:
            return state
    return None


def state_for_code(code: str) -> str | None:
    return GST_STATE_CODES.get(code)
