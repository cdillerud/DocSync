"""Operator-facing Document Detail truth normalization.

GPI-APP-TRUTH-WR-V83

Pure response-layer normalization for the Document Detail endpoint.

This module does not query or write MongoDB, Business Central, SharePoint, or
any other service. It receives one persisted document dictionary and returns a
deep-copied operator-facing representation.

For a resolved Warehouse Receipt whose authoritative po_resolution came from
the live BC API and points to posted purchase history, legacy validation and
reference-intelligence fields in the API response are reconciled to that newer
authoritative truth. Historical persisted fields remain unchanged.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


_MARKER = "GPI-APP-TRUTH-WR-V83"
_POSTED_ENTITIES = {"purchase_receipt", "posted_purchase_invoice"}


def _document_type(document: Dict[str, Any]) -> str:
    value = (
        document.get("document_type")
        or document.get("suggested_job_type")
        or document.get("doc_type")
        or ""
    )
    return str(value).strip().lower().replace(" ", "_")


def _table_for_entity(entity_type: str) -> str:
    if entity_type == "purchase_receipt":
        return "purchaseReceipts"
    if entity_type == "posted_purchase_invoice":
        return "purchaseInvoices"
    return ""


def _record_type_for_entity(entity_type: str) -> str:
    if entity_type == "purchase_receipt":
        return "purchaseReceipt"
    if entity_type == "posted_purchase_invoice":
        return "postedPurchaseInvoice"
    return ""


def _clean_stale_values(values: Any) -> list:
    cleaned = []
    for value in values or []:
        text = str(value).lower()
        if "database not initialized" in text or "call set_db()" in text:
            continue
        cleaned.append(value)
    return cleaned


def normalize_document_detail_authoritative_truth(
    document: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a response-only copy normalized from authoritative PO state.

    Fail closed: unless every live posted-history condition is satisfied, the
    input is returned as an ordinary deep copy with no semantic changes.
    """

    result = deepcopy(document)

    if _document_type(document) != "warehouse_receipt":
        return result

    po_resolution = document.get("po_resolution")
    if not isinstance(po_resolution, dict):
        return result

    if str(po_resolution.get("status") or "").strip().lower() != "resolved":
        return result

    best = po_resolution.get("best_match") or {}
    if not isinstance(best, dict):
        best = {}

    entity_type = str(
        po_resolution.get("bc_entity_type")
        or best.get("bc_entity_type")
        or ""
    ).strip()

    lookup_source = str(
        po_resolution.get("lookup_source")
        or best.get("lookup_source")
        or ""
    ).strip()

    bc_record_id = str(
        po_resolution.get("bc_record_id")
        or best.get("bc_record_id")
        or ""
    ).strip()

    bc_document_no = str(
        best.get("bc_document_no")
        or po_resolution.get("bc_document_no")
        or ""
    ).strip()

    po_number = str(
        po_resolution.get("po_number")
        or po_resolution.get("bc_order_number")
        or best.get("bc_order_number")
        or ""
    ).strip()

    confidence = po_resolution.get("confidence")
    if confidence is None:
        confidence = best.get("confidence")
    if confidence is None:
        confidence = 1.0

    match_method = str(
        po_resolution.get("match_method")
        or best.get("match_method")
        or "authoritative_po_resolution"
    ).strip()

    if (
        entity_type not in _POSTED_ENTITIES
        or lookup_source != "bc_api"
        or not bc_record_id
        or not bc_document_no
        or not po_number
    ):
        return result

    record_type = _record_type_for_entity(entity_type)

    bc_record_info = {
        "id": bc_record_id,
        "number": bc_document_no,
        "order_number": po_number,
        "table": _table_for_entity(entity_type),
        "environment": "Production",
        "vendor_name": str(
            po_resolution.get("bc_vendor_name")
            or best.get("bc_vendor_name")
            or ""
        ),
        "vendor_number": str(
            po_resolution.get("bc_vendor_no")
            or best.get("bc_vendor_no")
            or ""
        ),
        "customer_name": str(
            po_resolution.get("bc_customer_name")
            or best.get("bc_customer_name")
            or ""
        ),
        "customer_number": str(
            po_resolution.get("bc_customer_no")
            or best.get("bc_customer_no")
            or ""
        ),
        "status": "Posted",
        "source": "bc_api",
    }
    bc_record_info["document_number"] = bc_document_no
    bc_record_info["entity_type"] = entity_type
    bc_record_info["displayName"] = (
        bc_record_info["vendor_name"]
        or bc_record_info["customer_name"]
    )

    validation = deepcopy(document.get("validation_results") or {})
    normalized_fields = deepcopy(
        validation.get("normalized_fields")
        or document.get("normalized_fields")
        or document.get("extracted_fields")
        or {}
    )
    normalized_fields["po_number"] = po_number
    normalized_fields["_po_resolution_number"] = po_number

    validation.update(
        {
            "all_passed": True,
            "checks": [
                {
                    "field": "po_number",
                    "status": "passed",
                    "passed": True,
                    "required": True,
                    "message": (
                        f"PO {po_number} resolved through live BC posted "
                        f"history to {entity_type} {bc_document_no}."
                    ),
                    "match_method": match_method,
                    "lookup_source": lookup_source,
                    "score": confidence,
                }
            ],
            "warnings": _clean_stale_values(validation.get("warnings")),
            "bc_record_id": bc_record_id,
            "bc_record_info": bc_record_info,
            "normalized_fields": normalized_fields,
            "match_method": match_method,
            "match_score": confidence,
            "validation_status": "pass",
            "operator_truth_source": "po_resolution",
            "operator_truth_marker": _MARKER,
        }
    )

    authoritative_best = {
        "entity_type": entity_type,
        "bc_entity_type": entity_type,
        "bc_record_id": bc_record_id,
        "bc_document_no": bc_document_no,
        "bc_order_number": po_number,
        "bc_record_info": bc_record_info,
        "match_score": confidence,
        "confidence": confidence,
        "match_method": match_method,
        "lookup_source": lookup_source,
        "match_reasoning": (
            f"Authoritative live BC posted-history resolution for PO "
            f"{po_number}."
        ),
        "candidate_domain": "purchase",
        "counterparty_name": (
            bc_record_info["vendor_name"]
            or bc_record_info["customer_name"]
        ),
        "candidate_state": "resolved",
        "source": "po_resolution",
    }

    reference_intelligence = deepcopy(
        document.get("reference_intelligence") or {}
    )
    reference_intelligence.update(
        {
            "document_id": document.get("id"),
            "document_type": (
                document.get("document_type") or "Warehouse_Receipt"
            ),
            "resolver_strategy": "Warehouse_Receipt",
            "match_outcome": "exact_match",
            "best_match": authoritative_best,
            "alternate_matches": [],
            "operator_truth_source": "po_resolution",
            "operator_truth_marker": _MARKER,
        }
    )

    result["validation_results"] = validation
    result["bc_validation"] = {
        "status": "pass",
        "all_passed": True,
        "po_number": po_number,
        "entity_type": entity_type,
        "bc_record_type": record_type,
        "bc_record_id": bc_record_id,
        "bc_document_no": bc_document_no,
        "match_method": match_method,
        "lookup_source": lookup_source,
        "confidence": confidence,
        "link_status": "linked_history",
        "source": "po_resolution",
        "operator_truth_marker": _MARKER,
    }

    result["reference_intelligence"] = reference_intelligence
    result["reference_intelligence_status"] = "completed"
    result["reference_bc_document_no"] = bc_document_no
    result["reference_bc_record_id"] = bc_record_id
    result["reference_bc_type"] = entity_type
    result["reference_best_match"] = authoritative_best

    # Existing Document Detail cards consume these convenience fields.
    # They are response-only here; the persisted Mongo document is untouched.
    result["bc_record_type"] = record_type
    result["bc_record_id"] = bc_record_id
    result["bc_document_no"] = bc_document_no
    result["bc_link_status"] = "linked_history"
    result["link_status"] = "linked_history"

    result["operator_truth"] = {
        "source": "po_resolution",
        "marker": _MARKER,
        "authoritative": True,
        "po_number": po_number,
        "entity_type": entity_type,
        "bc_record_type": record_type,
        "bc_record_id": bc_record_id,
        "bc_document_no": bc_document_no,
        "lookup_source": lookup_source,
        "match_method": match_method,
        "confidence": confidence,
        "link_status": "linked_history",
    }

    return result
