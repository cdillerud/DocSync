"""Runtime helpers for sales-order automation.

These helpers normalize values arriving from MongoDB, AI extraction, forms, and
legacy records before deterministic preflight runs.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

from services.sales_order_source_inference import assess_sales_order_source

_TRUE_VALUES = {"true", "1", "yes", "y", "on", "approved"}
_FALSE_VALUES = {"false", "0", "no", "n", "off", "", "none", "null"}
_SUPPORTED_SALES_ORDER_TYPES = {
    "SALES_ORDER",
    "SALESORDER",
    "CUSTOMER_PO",
    "CUSTOMER_PURCHASE_ORDER",
}
_AP_ONLY_VALIDATION_TERMS = (
    "vendor name",
    "vendor number",
    "vendor no",
    "invoice number",
    "invoice date",
    "ap invoice",
)


def parse_bool(value: Any, *, default: bool = False) -> bool:
    """Parse booleans without treating the string ``"false"`` as truthy."""

    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    return default


def prepare_sales_order_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Return a defensive copy with known sales-order fields normalized.

    The repository contains documents produced by several generations of ingestion
    code. Some records contain real booleans while others contain strings such as
    ``"false"``. Older AP-oriented validation also attached vendor and invoice
    errors to documents later classified as customer sales orders. Those AP-only
    messages must not block sales-order preflight.

    Strong evidence that the source is a Gamer-issued vendor purchase order is a
    hard safety block. The in-memory type is changed to ``PURCHASE_ORDER`` so the
    deterministic preflight rejects it even when a stale Mongo record still says
    ``Sales_Order``.
    """

    prepared = copy.deepcopy(doc)
    prepared["sales_order_approved"] = parse_bool(
        prepared.get("sales_order_approved")
    )

    source_assessment = assess_sales_order_source(prepared)
    if source_assessment.get("excluded"):
        prepared["sales_order_excluded"] = True
        prepared["sales_order_source_assessment"] = source_assessment
        prepared["doc_type"] = "PURCHASE_ORDER"

        validation_errors = prepared.get("validation_errors")
        if isinstance(validation_errors, list):
            errors = list(validation_errors)
        elif validation_errors:
            errors = [validation_errors]
        else:
            errors = []

        exclusion_message = str(
            source_assessment.get("reason")
            or "The source is not a customer sales-order intake document."
        )
        if exclusion_message not in [_message_text(value) for value in errors]:
            errors.append(exclusion_message)
        prepared["validation_errors"] = errors

    for container_name in (
        "sales_order_lines",
        "mapped_lines",
        "line_items",
    ):
        _normalize_line_flags(prepared.get(container_name))

    for parent_name in ("normalized_fields", "extracted_fields", "data"):
        parent = prepared.get(parent_name)
        if not isinstance(parent, dict):
            continue
        _normalize_line_flags(parent.get("lines"))
        _normalize_line_flags(parent.get("line_items"))

    if _is_supported_sales_order(prepared):
        prepared["validation_errors"] = _remove_ap_only_messages(
            prepared.get("validation_errors")
        )
        prepared["validation_warnings"] = _remove_ap_only_messages(
            prepared.get("validation_warnings")
        )

    return prepared


def mongo_field_missing_or_null(field_name: str) -> Dict[str, Any]:
    """Build a Mongo predicate that accepts both absent and explicit null."""

    return {
        "$or": [
            {field_name: {"$exists": False}},
            {field_name: None},
        ]
    }


def append_validation_error(
    preflight_dict: Dict[str, Any],
    *,
    code: str,
    message: str,
    field: str | None = None,
    line: int | None = None,
) -> Dict[str, Any]:
    """Append a structured error to a serialized preflight result."""

    errors: List[Dict[str, Any]] = list(preflight_dict.get("errors") or [])
    errors.append(
        {
            "code": code,
            "message": message,
            "severity": "error",
            "field": field,
            "line": line,
        }
    )
    preflight_dict["errors"] = errors
    preflight_dict["can_create"] = False
    return preflight_dict


def _normalize_line_flags(lines: Any) -> None:
    if not isinstance(lines, list):
        return

    for line in lines:
        if not isinstance(line, dict):
            continue
        for key in (
            "mappingApproved",
            "mapping_approved",
            "item_mapping_approved",
        ):
            if key in line:
                line[key] = parse_bool(line.get(key))


def _normalize_doc_type(value: Any) -> str:
    if not value:
        return ""
    return str(value).strip().upper().replace("-", "_").replace(" ", "_")


def _effective_document_type(doc: Dict[str, Any]) -> str:
    classification = doc.get("classification") or {}
    values = [
        doc.get("doc_type"),
        doc.get("document_type"),
        doc.get("suggested_job_type"),
        classification.get("suggested_type")
        if isinstance(classification, dict)
        else None,
    ]
    for value in values:
        normalized = _normalize_doc_type(value)
        if normalized:
            return normalized
    return ""


def _is_supported_sales_order(doc: Dict[str, Any]) -> bool:
    return _effective_document_type(doc) in _SUPPORTED_SALES_ORDER_TYPES


def _message_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("message") or value.get("detail") or value)
    return str(value)


def _remove_ap_only_messages(values: Any) -> Any:
    if not values:
        return values

    was_string = isinstance(values, str)
    sequence = [values] if was_string else values
    if not isinstance(sequence, list):
        return values

    filtered = [
        value
        for value in sequence
        if not any(
            term in _message_text(value).strip().lower()
            for term in _AP_ONLY_VALIDATION_TERMS
        )
    ]

    if was_string:
        return filtered[0] if filtered else None
    return filtered
