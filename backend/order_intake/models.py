"""Normalized models for order-intake source documents.

Source facts and Business Central transaction values are deliberately separate.
A customer PO may state BC-ready values directly, while a supplier/manufacturer
schedule may describe a linked customer order using the supplier's own quantity,
UOM, plant, or reference scheme. Parsers must preserve source evidence and never
promote supplier-side values into BC Sales Order fields without authoritative
customer/item resolution.
"""

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class DocumentType(str, Enum):
    STANDARD_PO = "STANDARD_PO"
    BLANKET_RELEASE_BATCH = "BLANKET_RELEASE_BATCH"
    SUPPLIER_SALES_ORDER_SCHEDULE = "SUPPLIER_SALES_ORDER_SCHEDULE"


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
    source_party_role: Optional[str] = None
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

    # Customer-PO document evidence. These are source facts, not proof that the
    # corresponding Business Central customer/order context has been resolved.
    customer_order_reference: Optional[str] = None
    order_date: Optional[date] = None
    currency: Optional[str] = None


@dataclass
class NormalizedRelease:
    customer_release_reference: str
    load_number: Optional[int] = None
    product_context: Optional[str] = None
    customer_item_reference: Optional[str] = None
    description: Optional[str] = None

    # Source-line identity and evidence. Preserve exactly enough information to
    # explain how the parser interpreted the customer's source document.
    source_line_number: Optional[str] = None
    source_quantity_text: Optional[str] = None
    source_uom_text: Optional[str] = None
    source_unit_price: Optional[float] = None
    source_price_uom: Optional[str] = None
    source_line_total: Optional[float] = None

    # BC-ready transaction values. Populate these only when the source is actually
    # the customer order context or after an authoritative BC/customer/item mapping
    # resolves source quantity/UOM into the BC sales transaction values.
    quantity: Optional[float] = None
    uom: Optional[str] = None

    # Source physical quantity evidence. Supplier/manufacturer schedules belong here
    # until their relationship to the end-customer Sales Order is explicitly proven.
    physical_quantity: Optional[float] = None
    physical_uom: Optional[str] = None
    source_facility_reference: Optional[str] = None

    requested_shipment_date: Optional[datetime] = None
    requested_delivery_date: Optional[date] = None

    # Customer ship-to and BC inventory/location are separate concepts. Source
    # supplier/manufacturer plants are separate again and belong in
    # source_facility_reference, never ship_to_candidate or location_candidate.
    ship_to_candidate: Optional[str] = None
    location_candidate: Optional[str] = None
    resolved_location_code: Optional[str] = None
    resolved_location_id: Optional[str] = None

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
    location_status: Optional[str] = None
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
        if self.document.order_date:
            value["document"]["order_date"] = self.document.order_date.isoformat()
        for index, release in enumerate(self.releases):
            if release.requested_shipment_date:
                value["releases"][index]["requested_shipment_date"] = release.requested_shipment_date.isoformat()
            if release.requested_delivery_date:
                value["releases"][index]["requested_delivery_date"] = release.requested_delivery_date.isoformat()
        return value
