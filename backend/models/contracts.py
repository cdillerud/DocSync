"""GPI Document Hub — Contract Intelligence Pydantic Models (Phase 1).

Schemas for the 10 new MongoDB collections that back the DocuSign x BC
Contract Intelligence module. Phase 1 is read-only / analytics oriented:
no BC writes, no envelope mutation, no UI.

Collections (one model per collection):
    1.  agreements                — top-level agreement record
    2.  agreement_parties         — signers / CCs / senders
    3.  agreement_terms           — extracted contractual terms
    4.  agreement_pricing         — line-level pricing
    5.  agreement_obligations     — payment / delivery / reporting commitments
    6.  agreement_documents       — DocuSign documents attached to the envelope
    7.  agreement_bc_links        — confirmed / proposed BC links (customers,
                                    vendors, items, SO/PO) — read-only/advisory
    8.  agreement_events          — raw webhook + polling events (audit-grade)
    9.  agreement_exceptions      — match misses requiring manual intervention
    10. agreement_match_audit     — full audit trail of every link / unlink /
                                    confirmation / rejection / resolution

Conventions:
    - All ids are UUID4 strings (NEVER ObjectId / Mongo _id).
    - Timestamps are timezone-aware UTC (`datetime.now(timezone.utc)`).
    - Status / role / kind fields are constrained `Literal` unions.
    - All models permit additive forward fields via `model_config` extras="ignore".
    - No model embeds another by document — collections are flat and joined
      by `agreement_id` for query clarity and migration safety.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerated value sets (kept as Literal for static + runtime validation)
# ---------------------------------------------------------------------------

AgreementStatus = Literal[
    "drafted", "sent", "delivered", "completed",
    "declined", "voided", "expired", "unknown",
]

PartyRole = Literal[
    "signer", "carbon_copy", "certified_delivery",
    "in_person_signer", "agent", "editor", "intermediary",
    "sender", "approver", "witness",
]

PartySigningStatus = Literal[
    "created", "sent", "delivered", "signed",
    "declined", "completed", "auto_responded", "unknown",
]

TermSource = Literal["custom_field", "tab", "form_data", "inferred", "manual"]

PricingSource = Literal["tab", "custom_field", "form_data", "manual", "inferred"]

ObligationKind = Literal[
    "payment", "delivery", "reporting", "renewal",
    "termination", "sla", "compliance", "other",
]

ObligationStatus = Literal["open", "met", "overdue", "waived", "unknown"]

BCLinkType = Literal[
    "customer", "vendor", "item", "sales_order", "purchase_order", "contact",
]

BCLinkStatus = Literal["proposed", "confirmed", "rejected", "auto_confirmed"]

MatchMethod = Literal[
    "exact_no", "exact_name", "alias", "normalized",
    "fuzzy", "manual", "llm_assisted", "unmatched",
]

ExceptionCode = Literal[
    "party_unmatched", "item_unmatched", "term_missing",
    "pricing_unparsable", "duplicate_envelope", "missing_envelope",
    "hmac_invalid", "normalization_failed", "other",
]

ExceptionSeverity = Literal["low", "medium", "high", "critical"]

ExceptionStatus = Literal["open", "in_review", "resolved", "wont_fix"]

AuditAction = Literal[
    "proposed_link", "confirmed_link", "rejected_link",
    "unlinked", "reassigned", "exception_opened",
    "exception_resolved", "agreement_normalized",
    "agreement_status_changed",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _ContractBase(BaseModel):
    """Shared config: serialize datetimes as ISO 8601 with timezone, ignore extras."""

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        ser_json_timedelta="iso8601",
    )


# ---------------------------------------------------------------------------
# 1. Agreement
# ---------------------------------------------------------------------------

class Agreement(_ContractBase):
    """Top-level agreement record. One row per envelope."""

    id: str = Field(default_factory=_new_id)
    provider: Literal["docusign"] = "docusign"
    provider_envelope_id: str
    provider_account_id: Optional[str] = None

    status: AgreementStatus = "unknown"
    title: Optional[str] = None
    subject: Optional[str] = None
    email_subject: Optional[str] = None

    sender_name: Optional[str] = None
    sender_email: Optional[EmailStr] = None

    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    declined_at: Optional[datetime] = None
    voided_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    # Stored on the agreements collection for fast filtering; counts maintained
    # by the normalizer (Phase 2). Kept advisory and read-only.
    party_count: int = 0
    document_count: int = 0
    has_unmatched_exceptions: bool = False

    last_event_id: Optional[str] = None
    last_normalized_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("provider_envelope_id")
    @classmethod
    def _envelope_id_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("provider_envelope_id must be non-empty")
        return v.strip()


# ---------------------------------------------------------------------------
# 2. AgreementParty
# ---------------------------------------------------------------------------

class AgreementParty(_ContractBase):
    """A recipient or sender attached to an agreement."""

    id: str = Field(default_factory=_new_id)
    agreement_id: str

    role: PartyRole
    routing_order: Optional[int] = None

    name: Optional[str] = None
    email: Optional[EmailStr] = None
    organization: Optional[str] = None

    # Lower-cased, punctuation-stripped form used for BC matching.
    normalized_name: Optional[str] = None
    normalized_org: Optional[str] = None

    signing_status: PartySigningStatus = "unknown"
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    signed_at: Optional[datetime] = None
    declined_reason: Optional[str] = None

    provider_recipient_id: Optional[str] = None

    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# 3. AgreementTerm
# ---------------------------------------------------------------------------

class AgreementTerm(_ContractBase):
    """A single normalized contractual term extracted from the envelope."""

    id: str = Field(default_factory=_new_id)
    agreement_id: str

    term_key: str
    term_value: Optional[str] = None
    raw_value: Optional[str] = None

    source: TermSource = "inferred"
    source_field_name: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("term_key")
    @classmethod
    def _term_key_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("term_key must be non-empty")
        return v.strip()


# ---------------------------------------------------------------------------
# 4. AgreementPricing
# ---------------------------------------------------------------------------

class AgreementPricing(_ContractBase):
    """Line-level pricing extracted from agreement tabs / custom fields."""

    id: str = Field(default_factory=_new_id)
    agreement_id: str

    line_no: Optional[int] = None
    item_label: Optional[str] = None
    description: Optional[str] = None

    quantity: Optional[float] = None
    uom: Optional[str] = None
    unit_price: Optional[float] = None
    line_total: Optional[float] = None
    currency: Optional[str] = None

    source: PricingSource = "inferred"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Match outcomes (populated by Phase 2 matcher; advisory only).
    matched_bc_item_no: Optional[str] = None
    match_method: Optional[MatchMethod] = None
    match_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    created_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# 5. AgreementObligation
# ---------------------------------------------------------------------------

class AgreementObligation(_ContractBase):
    """A commitment / obligation embedded in the agreement."""

    id: str = Field(default_factory=_new_id)
    agreement_id: str

    kind: ObligationKind
    description: str
    due_at: Optional[datetime] = None

    status: ObligationStatus = "open"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# 6. AgreementDocument
# ---------------------------------------------------------------------------

class AgreementDocument(_ContractBase):
    """A document file attached to a DocuSign envelope."""

    id: str = Field(default_factory=_new_id)
    agreement_id: str

    provider_document_id: str
    name: Optional[str] = None
    mime_type: Optional[str] = None

    page_count: Optional[int] = None
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None

    storage_uri: Optional[str] = None
    downloaded_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# 7. AgreementBCLink
# ---------------------------------------------------------------------------

class AgreementBCLink(_ContractBase):
    """Proposed or confirmed link between an agreement and a BC entity."""

    id: str = Field(default_factory=_new_id)
    agreement_id: str

    link_type: BCLinkType
    bc_entity: str
    bc_no: str
    bc_name_snapshot: Optional[str] = None

    match_method: MatchMethod = "unmatched"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    status: BCLinkStatus = "proposed"

    # Optional party / pricing back-references (when the link is scoped to a row).
    party_id: Optional[str] = None
    pricing_id: Optional[str] = None

    linked_by: str = "system"
    linked_at: datetime = Field(default_factory=_utc_now)
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None

    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# 8. AgreementEvent
# ---------------------------------------------------------------------------

class AgreementEvent(_ContractBase):
    """Raw inbound event from DocuSign Connect / poll. Always-write, never mutate."""

    id: str = Field(default_factory=_new_id)
    agreement_id: Optional[str] = None  # populated after normalization

    provider: Literal["docusign"] = "docusign"
    provider_event_id: str  # unique-indexed alongside provider
    provider_envelope_id: Optional[str] = None
    event_type: str

    received_at: datetime = Field(default_factory=_utc_now)
    hmac_valid: Optional[bool] = None
    transport: Literal["webhook", "poll", "manual"] = "webhook"

    raw_payload: Dict[str, Any] = Field(default_factory=dict)

    processed: bool = False
    processed_at: Optional[datetime] = None
    error: Optional[str] = None

    @field_validator("provider_event_id")
    @classmethod
    def _event_id_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("provider_event_id must be non-empty")
        return v.strip()


# ---------------------------------------------------------------------------
# 9. AgreementException
# ---------------------------------------------------------------------------

class AgreementException(_ContractBase):
    """A queue row for matches that need manual intervention or review."""

    id: str = Field(default_factory=_new_id)
    agreement_id: str

    code: ExceptionCode
    severity: ExceptionSeverity = "medium"
    details: Dict[str, Any] = Field(default_factory=dict)

    status: ExceptionStatus = "open"
    opened_at: datetime = Field(default_factory=_utc_now)
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolution_note: Optional[str] = None

    # Optional cross-references for tooling.
    related_party_id: Optional[str] = None
    related_pricing_id: Optional[str] = None
    related_event_id: Optional[str] = None


# ---------------------------------------------------------------------------
# 10. AgreementMatchAudit
# ---------------------------------------------------------------------------

class AgreementMatchAudit(_ContractBase):
    """Append-only audit row for every match / link / resolution operation."""

    id: str = Field(default_factory=_new_id)
    agreement_id: str

    action: AuditAction
    actor: str = "system"  # user_id, service name, or 'system'
    at: datetime = Field(default_factory=_utc_now)

    link_id: Optional[str] = None
    exception_id: Optional[str] = None

    before: Dict[str, Any] = Field(default_factory=dict)
    after: Dict[str, Any] = Field(default_factory=dict)

    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Collection name registry (single source of truth)
# ---------------------------------------------------------------------------

CONTRACTS_COLLECTIONS: Dict[str, str] = {
    "agreements": "agreements",
    "agreement_parties": "agreement_parties",
    "agreement_terms": "agreement_terms",
    "agreement_pricing": "agreement_pricing",
    "agreement_obligations": "agreement_obligations",
    "agreement_documents": "agreement_documents",
    "agreement_bc_links": "agreement_bc_links",
    "agreement_events": "agreement_events",
    "agreement_exceptions": "agreement_exceptions",
    "agreement_match_audit": "agreement_match_audit",
}


# Indexes are declared (not created) here; creation is one-shot via
# scripts/contracts_init_indexes.py to avoid touching existing startup paths.
CONTRACTS_INDEXES: Dict[str, List[Dict[str, Any]]] = {
    "agreements": [
        {"keys": [("provider_envelope_id", 1)], "unique": True, "name": "uniq_envelope"},
        {"keys": [("status", 1), ("expires_at", 1)], "name": "by_status_expiry"},
        {"keys": [("updated_at", -1)], "name": "by_updated"},
    ],
    "agreement_parties": [
        {"keys": [("agreement_id", 1)], "name": "by_agreement"},
        {"keys": [("normalized_org", 1)], "name": "by_norm_org"},
        {"keys": [("email", 1)], "name": "by_email"},
    ],
    "agreement_terms": [
        {"keys": [("agreement_id", 1), ("term_key", 1)], "name": "by_agreement_term"},
    ],
    "agreement_pricing": [
        {"keys": [("agreement_id", 1), ("line_no", 1)], "name": "by_agreement_line"},
        {"keys": [("matched_bc_item_no", 1)], "name": "by_matched_item"},
    ],
    "agreement_obligations": [
        {"keys": [("agreement_id", 1), ("kind", 1)], "name": "by_agreement_kind"},
        {"keys": [("status", 1), ("due_at", 1)], "name": "by_status_due"},
    ],
    "agreement_documents": [
        {"keys": [("agreement_id", 1)], "name": "by_agreement"},
        {"keys": [("provider_document_id", 1), ("agreement_id", 1)],
         "unique": True, "name": "uniq_provider_doc"},
    ],
    "agreement_bc_links": [
        {"keys": [("agreement_id", 1), ("link_type", 1)], "name": "by_agreement_type"},
        {"keys": [("bc_entity", 1), ("bc_no", 1)], "name": "by_bc_entity_no"},
        {"keys": [("status", 1)], "name": "by_status"},
    ],
    "agreement_events": [
        {"keys": [("provider", 1), ("provider_event_id", 1)],
         "unique": True, "name": "uniq_provider_event"},
        {"keys": [("provider_envelope_id", 1), ("received_at", -1)],
         "name": "by_envelope_received"},
        {"keys": [("processed", 1)], "name": "by_processed"},
    ],
    "agreement_exceptions": [
        {"keys": [("agreement_id", 1), ("status", 1)], "name": "by_agreement_status"},
        {"keys": [("code", 1), ("status", 1)], "name": "by_code_status"},
    ],
    "agreement_match_audit": [
        {"keys": [("agreement_id", 1), ("at", -1)], "name": "by_agreement_at"},
        {"keys": [("action", 1), ("at", -1)], "name": "by_action_at"},
    ],
}
