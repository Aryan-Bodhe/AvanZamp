from __future__ import annotations
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field

class Outcome(str, Enum):
    AUTO_APPROVE = "AUTO_APPROVE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    HOLD_MISSING_INFO = "HOLD_MISSING_INFO"
    REJECT = "REJECT"

# When several checks propose different outcomes, the first in this list wins.
PRECEDENCE = [Outcome.REJECT, Outcome.HOLD_MISSING_INFO, Outcome.NEEDS_REVIEW, Outcome.AUTO_APPROVE]

class Quality(str, Enum):
    VERIFIED = "VERIFIED"      # deterministic parse AND arithmetic reconciles
    GROUNDED = "GROUNDED"      # LLM value whose evidence snippet was found in the PDF text layer
    UNVERIFIED = "UNVERIFIED"  # LLM value from vision only (no text layer to check against)
    MISSING = "MISSING"        # genuinely absent after all tiers

class LineItem(BaseModel):
    supplier_name: str | None = None
    part_number: str | None = None
    unit: str | None = None
    description: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None

class Party(BaseModel):
    name: str | None = None
    address: str | None = None
    email: str | None = None
    tax_id: str | None = None

class Adjustment(BaseModel):
    description: str = ""
    amount: Decimal | None = None  # signed adjustment printed between subtotal and grand total

class FieldEvidence(BaseModel):
    path: str
    snippet: str
    page: int | None = Field(default=None, ge=1)

class ExtractedInvoice(BaseModel):
    field_evidence: list[FieldEvidence] = Field(default_factory=list)
    document_type: Literal["invoice", "bill_of_materials", "advance_request", "quotation", "purchase_order", "other", "unknown"] = "unknown"
    sender: Party | None = None       # document issuer; not necessarily the invoice seller
    recipient: Party | None = None
    adjustments: list[Adjustment] = Field(default_factory=list)
    document_date: date | None = None
    vendor_name: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    po_reference: str | None = None        # as printed, e.g. "PO-1001"; None if absent
    currency: str | None = None
    subtotal: Decimal | None = None        # pre-tax, if shown
    tax_amount: Decimal | None = None
    total: Decimal | None = None           # amount due as printed
    prices_include_tax: bool | None = None # True if the printed total already embeds tax
    line_items: list[LineItem] = Field(default_factory=list)
    reference_text: str | None = None      # free-text description / "Re:" line, used for implied PO matching
    field_quality: dict[str, Quality] = Field(default_factory=dict)  # per field name
    evidence: dict[str, str] = Field(default_factory=dict)           # per field: verbatim snippet from the doc
    extraction_path: Literal["deterministic", "llm_text", "llm_vision", "failed"] = "deterministic"
    warnings: list[str] = Field(default_factory=list)

class NormalizedInvoice(BaseModel):
    vendor_name: str | None
    invoice_number: str | None             # raw
    invoice_number_key: str | None         # upper-cased, alphanumerics only
    invoice_date: date | None
    po_reference_key: str | None           # e.g. "PO1001"
    currency: str
    net_amount: Decimal | None             # tax-normalised; basis for PO comparison
    tax_amount: Decimal | None
    gross_amount: Decimal | None
    net_is_inferred: bool = False          # True if net had to be derived from a PO tax rate
    description_text: str                  # reference_text + line item descriptions, joined

class CheckStatus(str, Enum):
    PASS = "PASS"; WARN = "WARN"; FAIL = "FAIL"; SKIP = "SKIP"; INFO = "INFO"

class CheckResult(BaseModel):
    check_id: str                          # stable id, see 5.3
    stage: str
    status: CheckStatus
    proposed: Outcome | None = None        # None = no objection
    title: str                             # e.g. "Vendor is approved"
    detail: str                            # one deterministic sentence a human can read
    evidence: dict[str, Any] = Field(default_factory=dict)

class Comms(BaseModel):
    audience: Literal["vendor", "internal"]
    subject: str
    body: str

class Decision(BaseModel):
    outcome: Outcome
    summary: str                           # one sentence
    reasons: list[str]                     # ordered; each backed by a check in driving_checks
    driving_checks: list[str]              # check_ids that determined the outcome
    recommended_action: str
    comms: Comms | None = None

class StageEvent(BaseModel):
    run_id: str
    seq: int
    stage: str                             # intake|extract|normalize|completeness|vendor|duplicates|po_match|amounts|decide|explain|complete
    state: Literal["started", "completed", "failed"]
    title: str
    detail: str = ""
    checks: list[CheckResult] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)   # stage-specific data; final event carries the Decision
    elapsed_ms: int = 0
