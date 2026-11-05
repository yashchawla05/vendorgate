"""Typed data shapes used across the app (pydantic v2).

SubmissionForm is also the JSON format for programmatic submissions:
see data/scenarios/*/submission.json for examples.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Country = Literal["IN", "US", "GB"]
EntityType = Literal["company", "llp_partnership", "proprietorship", "other"]
Severity = Literal["INFO", "WARN", "HIGH", "CRITICAL"]
Status = Literal["APPROVED", "PENDING", "REJECTED"]

COUNTRY_NAMES = {"IN": "India", "US": "United States", "GB": "United Kingdom"}
ENTITY_LABELS = {
    "company": "Company",
    "llp_partnership": "LLP / Partnership",
    "proprietorship": "Proprietorship",
    "other": "Other",
}


# ---------------------------------------------------------------- submission form
class Address(BaseModel):
    line1: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""


class Contact(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""


class TaxIds(BaseModel):
    pan: str = ""
    gstin: str = ""
    no_gst_declaration: bool = False  # vendor below the GST threshold declares non-registration
    ein: str = ""
    company_number: str = ""
    vat_number: str = ""


class BankDetails(BaseModel):
    account_holder: str = ""
    account_number: str = ""
    ifsc: str = ""
    routing_number: str = ""
    sort_code: str = ""
    bank_name: str = ""
    currency: str = ""
    bank_country: str = ""  # defaults to the vendor country when blank


class Declarations(BaseModel):
    information_accurate: bool = False
    consent_to_verification: bool = False


class DocumentRef(BaseModel):
    """One uploaded file and the slot the vendor put it in (what they *claim* it is)."""

    slot: str
    filename: str


class SubmissionForm(BaseModel):
    legal_name: str = ""
    trade_name: str = ""
    country: str = ""
    entity_type: str = ""
    address: Address = Field(default_factory=Address)
    contact: Contact = Field(default_factory=Contact)
    website: str = ""
    tax: TaxIds = Field(default_factory=TaxIds)
    bank: BankDetails = Field(default_factory=BankDetails)
    declarations: Declarations = Field(default_factory=Declarations)
    documents: list[DocumentRef] = Field(default_factory=list)


# ---------------------------------------------------------------- pipeline output
class Finding(BaseModel):
    """One rule outcome. Severity, category and resolver come from config/rules.yaml."""

    rule_id: str
    severity: Severity
    category: str
    title: str
    message: str
    resolver: Literal["vendor", "internal"] = "vendor"
    blocks_approval: bool = True
    field: str = ""
    evidence: dict = Field(default_factory=dict)
    vendor_request: str = ""  # what we ask the vendor to provide/fix (empty for internal-only)


class StageEvent(BaseModel):
    """Emitted by the pipeline generator; the Live Run page renders these as they arrive."""

    stage: str  # "S1".."S10"
    name: str
    phase: Literal["started", "completed"]
    status: str = "running"  # passed | flagged | failed | degraded | skipped | running
    duration_ms: int = 0
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)
