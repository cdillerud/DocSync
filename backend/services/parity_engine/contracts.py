# GPI Square9 Parity Engine - canonical shadow classification contract.
# V77: inference evidence only. No routing, BC mutation, SharePoint mutation, or Mongo mutation.

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from jsonschema import Draft202012Validator


SCHEMA_VERSION = "1.0"

# Recovered from the current Hub classification contract.
CANONICAL_DOCUMENT_TYPES = (
    "Graphics_Artwork",
    "AP_Invoice",
    "AR_Invoice",
    "Credit_Memo",
    "Remittance",
    "Freight_Document",
    "Sales_Order",
    "Sales_Quote",
    "Order_Confirmation",
    "Warehouse_Receipt",
    "Inventory_Report",
    "Shipping_Document",
    "Quality_Issue",
    "Inspection_Form",
    "Return_Request",
    "Unknown_Document",
)


def canonical_classification_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "schema_version": {
                "type": "string",
                "enum": [SCHEMA_VERSION],
            },
            "document_type": {
                "type": "string",
                "enum": list(CANONICAL_DOCUMENT_TYPES),
            },
            "document_type_confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
            },
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "value": {"type": "string"},
                        "page": {
                            "type": ["integer", "null"],
                            "minimum": 1,
                        },
                        "source_text": {"type": "string"},
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                    },
                    "required": [
                        "field",
                        "value",
                        "page",
                        "source_text",
                        "confidence",
                    ],
                    "additionalProperties": False,
                },
            },
            "references": {
                "type": "object",
                "properties": {
                    "po_numbers": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "invoice_number": {
                        "type": ["string", "null"],
                    },
                    "vendor_name": {
                        "type": ["string", "null"],
                    },
                    "customer_name": {
                        "type": ["string", "null"],
                    },
                    "is_international": {
                        "type": ["boolean", "null"],
                    },
                },
                "required": [
                    "po_numbers",
                    "invoice_number",
                    "vendor_name",
                    "customer_name",
                    "is_international",
                ],
                "additionalProperties": False,
            },
            "ambiguities": {
                "type": "array",
                "items": {"type": "string"},
            },
            "needs_review": {
                "type": "boolean",
            },
            "review_reasons": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "schema_version",
            "document_type",
            "document_type_confidence",
            "evidence",
            "references",
            "ambiguities",
            "needs_review",
            "review_reasons",
        ],
        "additionalProperties": False,
    }


_VALIDATOR = Draft202012Validator(canonical_classification_schema())


def validation_errors(result: Dict[str, Any]) -> List[str]:
    errors = sorted(
        _VALIDATOR.iter_errors(result),
        key=lambda item: list(item.path),
    )

    rendered = []

    for error in errors:
        path = ".".join(str(part) for part in error.path)
        rendered.append(
            f"{path or '<root>'}: {error.message}"
        )

    if not errors:
        doc_type = result.get("document_type")
        needs_review = result.get("needs_review")
        ambiguities = result.get("ambiguities") or []

        if doc_type == "Unknown_Document" and needs_review is not True:
            rendered.append(
                "Unknown_Document must set needs_review=true"
            )

        if ambiguities and needs_review is not True:
            rendered.append(
                "non-empty ambiguities must set needs_review=true"
            )

    return rendered


def assert_valid_result(result: Dict[str, Any]) -> None:
    errors = validation_errors(result)
    if errors:
        raise ValueError("; ".join(errors))


def fail_closed_result(reason: str) -> Dict[str, Any]:
    safe_reason = str(reason or "unspecified shadow-classifier failure")[:500]

    result = {
        "schema_version": SCHEMA_VERSION,
        "document_type": "Unknown_Document",
        "document_type_confidence": 0.0,
        "evidence": [],
        "references": {
            "po_numbers": [],
            "invoice_number": None,
            "vendor_name": None,
            "customer_name": None,
            "is_international": None,
        },
        "ambiguities": [safe_reason],
        "needs_review": True,
        "review_reasons": [safe_reason],
    }

    assert_valid_result(result)
    return deepcopy(result)
