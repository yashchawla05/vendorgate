"""Valid EIN prefixes (first two digits) issued by IRS campuses.

Source: https://www.irs.gov/businesses/small-businesses-self-employed/valid-eins (checked 2026-11-01).
EINs have no checksum, so the prefix allow-list is the only offline structural check.
Never issued: 00 07 08 09 17 18 19 28 29 49 69 70 78 79 89 96 97.
"""

VALID_EIN_PREFIXES: frozenset[str] = frozenset(
    "01 02 03 04 05 06 10 11 12 13 14 15 16 20 21 22 23 24 25 26 27 30 31 32 33 34 35 36 37 38 39 "
    "40 41 42 43 44 45 46 47 48 50 51 52 53 54 55 56 57 58 59 60 61 62 63 64 65 66 67 68 71 72 73 74 "
    "75 76 77 80 81 82 83 84 85 86 87 88 90 91 92 93 94 95 98 99".split()
)
