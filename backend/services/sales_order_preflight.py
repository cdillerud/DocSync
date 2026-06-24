"""Deterministic preflight validation for sales-order automation.

The AI/extraction layer may propose values, but this module decides whether a
document is safe to create as a draft sales order in Business Central.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Optional


SUPPORTED_SALES_ORDER_TYPES = {
    "SALES_ORDER",
    "SALESORDER",
    "CUSTOMER_PO",
    "CUSTOMER_PURCHASE_ORDER",
}

UNRESOLVED_MAPPING_STATES = {
    "unresolved",
    "ambiguous",
    "needs_review",
    "review",
    "suggested",
    "unknown",
    "rejected",
}

APPROVED_REVIEW_STATES = {
    "approved",
    "sales_order_approved",
    "ready_for_bc",
}


@dataclass(frozen=True)
class PreflightIssue:
    code: str
    message: str
    severity: str = "error"
    line: Optional[int] = None
    field: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SalesOrderPreflightResult:
    candidate: Dict[str, Any]
    errors: List[PreflightIssue] = field(default_factory=list)
    warnings: List[PreflightIssue] = field(default_factory=list)
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def can_create(self) -> bool:
        return not self.errors

    def add_error(
        self,
        code: str,
        message: str,
        *,
        line: Optional[int] = None,
        field: Optional[str] = None,
    ) -> None:
        self.errors.append(
            PreflightIssue(
                code=code,
                message=message,
                severity="error",
                line=line,
                field=field,
            )
        )

    def add_warning(
        self,
        code: str,
        message: str,
        *,
        line: Optional[int] = None,
        field: Optional[str] = None,
    ) -> None:
        self.warnings.append(
            PreflightIssue(
                code=code,
                message=message,
                severity="warning",
                line=line,
                field=field,
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "can_create": self.can_create,
            "candidate": self.candidate,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "evaluated_at": self.evaluated_at,
        }


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _nested(mapping: Dict[str, Any], *path: str) -> Any:
    value: Any = mapping
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def _normalize_doc_type(value: Any) -> str:
    if not value:
        return ""
    return str(value).strip().upper().replace("-", "_").replace(" ", "_")


def _normalize_lines(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized_fields = doc.get("normalized_fields") or {}
    extracted_fields = doc.get("extracted_fields") or {}
    data = doc.get("data") or {}

    raw_lines = _first_value(
        doc.get("sales_order_lines"),
        doc.get("mapped_lines"),
        doc.get("line_items"),
        normalized_fields.get("lines"),
        normalized_fields.get("line_items"),
        extracted_fields.get("lines"),
        extracted_fields.get("line_items"),
        data.get("lines"),
    )

    if not isinstance(raw_lines, list):
        return []

    lines: List[Dict[str, Any]] = []
    for index, raw in enumerate(raw_lines, start=1):
        if not isinstance(raw, dict):
            lines.append(
                {
                    "source_line_number": index,
                    "raw_value": raw,
                    "itemNumber": None,
                    "customerItemNumber": None,
                    "description": None,
                    "quantity": None,
                    "unitOfMeasureCode": None,
                    "unitPrice": None,
                    "shipmentDate": None,
                    "locationId": None,
                    "mappingStatus": None,
                    "mappingApproved": False,
                    "itemMatchConfidence": None,
                }
            )
            continue

        lines.append(
            {
                "source_line_number": _first_value(
                    raw.get("source_line_number"),
                    raw.get("lineNumber"),
                    raw.get("line_number"),
                    index,
                ),
                "itemNumber": _first_value(
                    raw.get("itemNumber"),
                    raw.get("item_number"),
                    raw.get("item_no"),
                    raw.get("bc_item_number"),
                    raw.get("bc_item_no"),
                    raw.get("resolved_item_number"),
                ),
                "customerItemNumber": _first_value(
                    raw.get("customerItemNumber"),
                    raw.get("customer_item_number"),
                    raw.get("customer_sku"),
                    raw.get("sku"),
                ),
                "description": _first_value(
                    raw.get("description"),
                    raw.get("item_description"),
                    raw.get("customer_description"),
                ),
                "quantity": _first_value(
                    raw.get("quantity"),
                    raw.get("ordered_qty"),
                    raw.get("qty"),
                ),
                "unitOfMeasureCode": _first_value(
                    raw.get("unitOfMeasureCode"),
                    raw.get("unit_of_measure_code"),
                    raw.get("unit_of_measure"),
                    raw.get("uom"),
                ),
                "unitPrice": _first_value(
                    raw.get("unitPrice"),
                    raw.get("unit_price"),
                    raw.get("price"),
                ),
                "shipmentDate": _first_value(
                    raw.get("shipmentDate"),
                    raw.get("shipment_date"),
                    raw.get("deliveryDate"),
                    raw.get("delivery_date"),
                    raw.get("requestedDeliveryDate"),
                    raw.get("requested_delivery_date"),
                ),
                "locationId": _first_value(
                    raw.get("locationId"),
                    raw.get("location_id"),
                    raw.get("bc_location_id"),
                ),
                "mappingStatus": _first_value(
                    raw.get("mappingStatus"),
                    raw.get("mapping_status"),
                    raw.get("item_mapping_status"),
                ),
                "mappingApproved": bool(
                    _first_value(
                        raw.get("mappingApproved"),
                        raw.get("mapping_approved"),
                        raw.get("item_mapping_approved"),
                        False,
                    )
                ),
                "itemMatchConfidence": _first_value(
                    raw.get("itemMatchConfidence"),
                    raw.get("item_match_confidence"),
                    raw.get("mapping_confidence"),
                ),
            }
        )

    return lines


def build_sales_order_candidate(doc: Dict[str, Any]) -> Dict[str, Any]:
    normalized_fields = doc.get("normalized_fields") or {}
    extracted_fields = doc.get("extracted_fields") or {}
    data = doc.get("data") or {}
    classification = doc.get("classification") or {}
    resolved_customer = doc.get("resolved_customer") or data.get("resolved_customer") or {}

    customer_number = _first_value(
        doc.get("bc_customer_number"),
        doc.get("bc_customer_no"),
        doc.get("customer_number_resolved"),
        normalized_fields.get("bc_customer_number"),
        normalized_fields.get("customer_number"),
        data.get("bc_customer_number"),
        data.get("customer_number"),
        resolved_customer.get("number") if isinstance(resolved_customer, dict) else None,
        resolved_customer.get("customerNumber") if isinstance(resolved_customer, dict) else None,
    )

    customer_name = _first_value(
        doc.get("customer_extracted"),
        normalized_fields.get("customer"),
        normalized_fields.get("customer_raw"),
        extracted_fields.get("customer"),
        extracted_fields.get("customer_name"),
        data.get("customer_name"),
        resolved_customer.get("displayName") if isinstance(resolved_customer, dict) else None,
        resolved_customer.get("name") if isinstance(resolved_customer, dict) else None,
    )

    external_document_number = _first_value(
        doc.get("order_number_extracted"),
        doc.get("customer_po_number"),
        normalized_fields.get("customer_po"),
        normalized_fields.get("po_number"),
        normalized_fields.get("order_number"),
        extracted_fields.get("customer_po_no"),
        extracted_fields.get("customer_po_number"),
        extracted_fields.get("po_number"),
        extracted_fields.get("order_number"),
        data.get("customer_po"),
        data.get("customer_po_number"),
    )

    order_date = _first_value(
        normalized_fields.get("order_date"),
        extracted_fields.get("order_date"),
        data.get("order_date"),
    )

    requested_delivery_date = _first_value(
        normalized_fields.get("requested_delivery_date"),
        normalized_fields.get("requested_ship_date"),
        extracted_fields.get("requested_delivery_date"),
        extracted_fields.get("requested_ship_date"),
        data.get("requested_delivery_date"),
    )

    confidence = _first_value(
        doc.get("ai_confidence"),
        doc.get("classification_confidence"),
        classification.get("confidence") if isinstance(classification, dict) else None,
        0,
    )

    source_metadata = doc.get("source_metadata") or {}
    file_hash = _first_value(
        doc.get("file_hash"),
        source_metadata.get("file_hash"),
        source_metadata.get("attachment_hash"),
    )
    internet_message_id = _first_value(
        doc.get("internet_message_id"),
        doc.get("email_message_id"),
        source_metadata.get("internet_message_id"),
        source_metadata.get("email_id"),
    )

    idempotency_seed = "|".join(
        str(value or "")
        for value in (
            customer_number,
            external_document_number,
            file_hash,
            internet_message_id,
        )
    )

    return {
        "document_id": _first_value(doc.get("id"), doc.get("document_id")),
        "document_type": _first_value(
            doc.get("doc_type"),
            doc.get("document_type"),
            doc.get("suggested_job_type"),
            classification.get("suggested_type")
            if isinstance(classification, dict)
            else None,
        ),
        "customerNumber": customer_number,
        "customerName": customer_name,
        "externalDocumentNumber": (
            str(external_document_number).strip()
            if external_document_number is not None
            else None
        ),
        "orderDate": order_date,
        "requestedDeliveryDate": requested_delivery_date,
        "currencyCode": _first_value(
            normalized_fields.get("currency_code"),
            extracted_fields.get("currency_code"),
            data.get("currency_code"),
            doc.get("currency"),
            "USD",
        ),
        "shipToCode": _first_value(
            normalized_fields.get("ship_to_code"),
            extracted_fields.get("ship_to_code"),
            data.get("ship_to_code"),
        ),
        "sharepointUrl": _first_value(
            doc.get("sharepoint_share_link_url"),
            doc.get("sharepoint_web_url"),
            _nested(doc, "sharepoint", "web_url"),
        ),
        "classificationConfidence": float(confidence or 0),
        "reviewStatus": str(doc.get("review_status") or "").strip().lower(),
        "salesOrderApproved": bool(doc.get("sales_order_approved")),
        "workflowStatus": str(doc.get("workflow_status") or "").strip().lower(),
        "lines": _normalize_lines(doc),
        "idempotencyKey": sha256(idempotency_seed.encode("utf-8")).hexdigest(),
    }


def preflight_sales_order(
    doc: Dict[str, Any],
    *,
    confidence_threshold: float = 0.90,
    item_match_threshold: float = 0.95,
    require_sharepoint: bool = True,
    require_approval: bool = True,
) -> SalesOrderPreflightResult:
    candidate = build_sales_order_candidate(doc)
    result = SalesOrderPreflightResult(candidate=candidate)

    document_type = _normalize_doc_type(candidate.get("document_type"))
    if document_type not in SUPPORTED_SALES_ORDER_TYPES:
        result.add_error(
            "UNSUPPORTED_DOCUMENT_TYPE",
            f"Document type '{candidate.get('document_type') or 'unknown'}' is not a supported customer sales order.",
            field="document_type",
        )

    confidence = candidate.get("classificationConfidence") or 0
    if confidence < confidence_threshold:
        result.add_error(
            "LOW_CLASSIFICATION_CONFIDENCE",
            f"Classification confidence {confidence:.2f} is below the required {confidence_threshold:.2f}.",
            field="classification_confidence",
        )

    if not candidate.get("customerNumber"):
        result.add_error(
            "CUSTOMER_NOT_RESOLVED",
            "A Business Central customer number has not been resolved.",
            field="customerNumber",
        )

    if not candidate.get("externalDocumentNumber"):
        result.add_error(
            "CUSTOMER_PO_REQUIRED",
            "Customer PO or external document number is required.",
            field="externalDocumentNumber",
        )

    if require_sharepoint and not candidate.get("sharepointUrl"):
        result.add_error(
            "SOURCE_DOCUMENT_NOT_ARCHIVED",
            "The source document must be stored in SharePoint before BC creation.",
            field="sharepointUrl",
        )

    if require_approval:
        approved = (
            candidate.get("salesOrderApproved")
            or candidate.get("reviewStatus") in APPROVED_REVIEW_STATES
        )
        if not approved:
            result.add_error(
                "REVIEW_APPROVAL_REQUIRED",
                "A reviewer must approve the sales-order candidate before BC creation.",
                field="review_status",
            )

    lines = candidate.get("lines") or []
    if not lines:
        result.add_error(
            "ORDER_LINES_REQUIRED",
            "At least one resolved sales-order line is required.",
            field="lines",
        )

    for index, line in enumerate(lines, start=1):
        item_number = line.get("itemNumber")
        customer_item = line.get("customerItemNumber")
        if not item_number:
            suffix = f" Customer item '{customer_item}' is not mapped." if customer_item else ""
            result.add_error(
                "ITEM_NOT_RESOLVED",
                f"Line {index} does not have a resolved Business Central item number.{suffix}",
                line=index,
                field="itemNumber",
            )

        quantity = _to_decimal(line.get("quantity"))
        if quantity is None:
            result.add_error(
                "QUANTITY_INVALID",
                f"Line {index} quantity is missing or invalid.",
                line=index,
                field="quantity",
            )
        elif quantity <= 0:
            result.add_error(
                "QUANTITY_NOT_POSITIVE",
                f"Line {index} quantity must be greater than zero.",
                line=index,
                field="quantity",
            )

        if not line.get("unitOfMeasureCode"):
            result.add_error(
                "UOM_NOT_RESOLVED",
                f"Line {index} does not have a resolved unit of measure.",
                line=index,
                field="unitOfMeasureCode",
            )

        mapping_status = str(line.get("mappingStatus") or "").strip().lower()
        if mapping_status in UNRESOLVED_MAPPING_STATES:
            result.add_error(
                "ITEM_MAPPING_NOT_APPROVED",
                f"Line {index} item mapping status is '{mapping_status}'.",
                line=index,
                field="mappingStatus",
            )

        match_confidence = _to_decimal(line.get("itemMatchConfidence"))
        if (
            match_confidence is not None
            and float(match_confidence) < item_match_threshold
            and not line.get("mappingApproved")
        ):
            result.add_error(
                "ITEM_MATCH_CONFIDENCE_LOW",
                f"Line {index} item-match confidence {float(match_confidence):.2f} is below {item_match_threshold:.2f}.",
                line=index,
                field="itemMatchConfidence",
            )

        unit_price = _to_decimal(line.get("unitPrice"))
        if unit_price is not None and unit_price < 0:
            result.add_error(
                "UNIT_PRICE_NEGATIVE",
                f"Line {index} unit price cannot be negative.",
                line=index,
                field="unitPrice",
            )

    for message in _as_messages(doc.get("validation_errors")):
        result.add_error("UPSTREAM_VALIDATION_ERROR", message)

    for message in _as_messages(doc.get("validation_warnings")):
        result.add_warning("UPSTREAM_VALIDATION_WARNING", message)

    return result


def _as_messages(values: Any) -> Iterable[str]:
    if not values:
        return []
    if isinstance(values, str):
        return [values]
    if isinstance(values, list):
        messages: List[str] = []
        for value in values:
            if isinstance(value, str):
                messages.append(value)
            elif isinstance(value, dict):
                messages.append(
                    str(value.get("message") or value.get("detail") or value)
                )
            else:
                messages.append(str(value))
        return messages
    return [str(values)]


def build_bc_sales_order_payload(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a validated candidate into the shape expected by the BC writer."""

    payload: Dict[str, Any] = {
        "customerNumber": candidate.get("customerNumber"),
        "externalDocumentNumber": candidate.get("externalDocumentNumber"),
        "currencyCode": candidate.get("currencyCode") or "USD",
        "lines": [],
    }

    if candidate.get("orderDate"):
        payload["orderDate"] = candidate["orderDate"]
    if candidate.get("requestedDeliveryDate"):
        payload["requestedDeliveryDate"] = candidate["requestedDeliveryDate"]
    if candidate.get("shipToCode"):
        payload["shipToCode"] = candidate["shipToCode"]

    for line in candidate.get("lines") or []:
        bc_line: Dict[str, Any] = {
            "itemNumber": line.get("itemNumber"),
            "quantity": float(_to_decimal(line.get("quantity")) or 0),
            "unitOfMeasureCode": line.get("unitOfMeasureCode"),
        }
        if line.get("description"):
            bc_line["description"] = str(line["description"])[:100]

        unit_price = _to_decimal(line.get("unitPrice"))
        if unit_price is not None:
            bc_line["unitPrice"] = float(unit_price)

        if line.get("shipmentDate"):
            bc_line["shipmentDate"] = line["shipmentDate"]

        if line.get("locationId"):
            bc_line["locationId"] = line["locationId"]

        payload["lines"].append(bc_line)

    return payload
