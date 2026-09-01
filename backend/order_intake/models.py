"""Normalized models for inbound customer orders.

Source facts and Business Central transaction values are deliberately separate.
For example, a customer blanket schedule may say 89,775 physical units per truck,
while Business Central may order the item as 89.775 M or as 22 PALLET. The parser
must preserve the source evidence and never infer the BC transaction quantity.
"""

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class DocumentType(str, Enum):
    STANDARD_PO = "STANDARD_PO"
    BLANKET_RELEASE_BATCH = "BLANKET_RELEASE_BATCH"


class ProposedAction(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    REJECT = "REJECT"
    DUPLICATE = "DUPLICATE"


@dataclass
class OrderSource:
    attachment_name: str
    attachment_sha256: str
    source_format: str
    source_sheet: Optional[str] = None
    message_id: Optional[str] = None
    internet_message_id: Optional[str] = None
    sender: Optional[str] = None
    subject: Optional[str] = None
    received_datetime: Optional[datetime] = None


@dataclass
class OrderCustomer:
    candidate_customer_name: Optional[str] = None
    resolved_customer_no: Optional[str] = None
    resolution_method: Optional[str] = None
    resolution_confidence: Optional[float] = None
    evidence: List[str] = field(default_factory=list)


@dataclass
class OrderDocument:
    document_type: DocumentType
    blanket_reference: Optional[str] = None
    period: Optional[str] = None
    source_revision_key: Optional[str] = None


@dataclass
class NormalizedRelease:
    customer_release_reference: str
    load_number: Optional[int] = None
    product_context: Optional[str] = None
    customer_item_reference: Optional[str] = None
    description: Optional[str] = None

    # BC-ready transaction values. These may be populated directly from a normal
    # PO (CanPack) or only after an authoritative customer/item profile resolves
    # the customer's physical release into the BC sales UOM (Giovanni).
    quantity: Optional[float] = None
    uom: Optional[str] = None

    # Customer/source physical quantity evidence. Never send these fields directly
    # to BC without resolving the item's BC sales UOM/profile first.
    physical_quantity: Optional[float] = None
    physical_uom: Optional[str] = None

    requested_shipment_date: Optional[datetime] = None
    requested_delivery_date: Optional[date] = None
    ship_to_candidate: Optional[str] = None
    existing_gamer_order: Optional[str] = None
    notes: Optional[str] = None
    source_coordinates: List[str] = field(default_factory=list)
    quantity_source: Optional[str] = None
    quantity_resolution_method: Optional[str] = None
    extraction_confidence: Optional[float] = None
    parser_review_reasons: List[str] = field(default_factory=list)


@dataclass
class OrderValidation:
    duplicate_status: Optional[str] = None
    customer_status: Optional[str] = None
    item_status: Optional[str] = None
    quantity_status: Optional[str] = None
    ship_to_status: Optional[str] = None
    date_status: Optional[str] = None
    price_status: Optional[str] = None
    exceptions: List[str] = field(default_factory=list)
    proposed_action: Optional[ProposedAction] = None


@dataclass
class NormalizedInboundOrder:
    source: OrderSource
    customer: OrderCustomer
    document: OrderDocument
    releases: List[NormalizedRelease]
    validation: Optional[OrderValidation] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly dictionary."""
        value = asdict(self)
        value["document"]["document_type"] = self.document.document_type.value
        if self.validation and self.validation.proposed_action:
            value["validation"]["proposed_action"] = self.validation.proposed_action.value
        if self.source.received_datetime:
            value["source"]["received_datetime"] = self.source.received_datetime.isoformat()
        for index, release in enumerate(self.releases):
            if release.requested_shipment_date:
                value["releases"][index]["requested_shipment_date"] = release.requested_shipment_date.isoformat()
            if release.requested_delivery_date:
                value["releases"][index]["requested_delivery_date"] = release.requested_delivery_date.isoformat()
        return value
