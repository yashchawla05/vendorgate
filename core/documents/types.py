"""Catalogue of document types: what each one is, what fields we extract from it,
and which upload slot accepts it.

Both extractors (offline rules and the LLM) use this catalogue, so they always
agree on field names.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocType:
    key: str
    label: str
    fields: tuple[str, ...]
    # Phrases that identify this document type in its text (used by the offline classifier).
    keywords: tuple[str, ...]


DOC_TYPES: dict[str, DocType] = {
    d.key: d
    for d in [
        DocType("pan_card", "PAN card", ("pan", "name", "date"),
                ("permanent account number", "income tax department")),
        DocType("gst_certificate", "GST registration certificate",
                ("gstin", "legal_name", "trade_name", "address", "registration_date", "constitution"),
                ("form gst reg-06", "registration certificate", "goods and services tax", "constitution of business")),
        DocType("no_gst_declaration", "GST non-registration declaration",
                ("legal_name", "pan", "declaration_date"),
                ("non-registration under gst", "hereby declare that we are not registered",
                 "aggregate turnover is below")),
        DocType("cancelled_cheque", "Cancelled cheque", ("account_holder", "account_number", "ifsc", "bank_name"),
                ("cancelled", "or bearer")),
        DocType("bank_letter", "Bank account confirmation letter",
                ("account_holder", "account_number", "ifsc", "routing_number", "sort_code", "bank_name", "letter_date"),
                ("account confirmation", "bank account verification", "confirm that the following account",
                 "holds account number", "without any liability on the bank")),
        DocType("incorporation_certificate", "Certificate of incorporation (India)",
                ("company_name", "cin", "incorporation_date"),
                ("certificate of incorporation", "corporate identity number", "registrar of companies",
                 "llp identification number", "ministry of corporate affairs")),
        DocType("w9", "Form W-9", ("name", "business_name", "tax_classification", "ein", "address", "signature_date"),
                ("form w-9", "request for taxpayer identification number")),
        DocType("company_registration_certificate", "UK company registration certificate",
                ("company_name", "company_number", "incorporation_date"),
                ("companies house", "registrar of companies for england and wales", "company number",
                 "companies act 2006")),
        DocType("other", "Other / unrecognised", (), ()),
    ]
}

# Upload slots shown on the form -> document types that satisfy the slot.
SLOTS: dict[str, tuple[str, ...]] = {
    "pan_card": ("pan_card",),
    "gst_certificate": ("gst_certificate",),
    "no_gst_declaration": ("no_gst_declaration",),
    "bank_proof": ("cancelled_cheque", "bank_letter"),
    "incorporation_certificate": ("incorporation_certificate",),
    "w9": ("w9",),
    "bank_letter": ("bank_letter",),
    "company_registration": ("company_registration_certificate",),
}

SLOT_LABELS = {
    "pan_card": "PAN card",
    "gst_certificate": "GST registration certificate",
    "no_gst_declaration": "GST non-registration declaration",
    "bank_proof": "Cancelled cheque or bank letter",
    "incorporation_certificate": "Certificate of incorporation",
    "w9": "Form W-9",
    "bank_letter": "Bank account confirmation letter",
    "company_registration": "Company registration certificate",
}


# Fields the rules depend on. A document's overall confidence is the lowest confidence
# among these, so a bank letter whose account number cannot be read is "low confidence".
KEY_FIELDS: dict[str, tuple[str, ...]] = {
    "pan_card": ("pan", "name"),
    "gst_certificate": ("gstin", "legal_name"),
    "no_gst_declaration": ("legal_name", "pan"),
    "cancelled_cheque": ("account_holder", "account_number", "ifsc"),
    "bank_letter": ("account_holder", "account_number", "letter_date"),
    "incorporation_certificate": ("company_name", "cin"),
    "w9": ("name", "ein"),
    "company_registration_certificate": ("company_name", "company_number"),
    "other": (),
}


def label(doc_type: str) -> str:
    return DOC_TYPES.get(doc_type, DOC_TYPES["other"]).label
