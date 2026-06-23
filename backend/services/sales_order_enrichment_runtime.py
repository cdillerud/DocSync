"""Orchestrate read-only sales-order enrichment before deterministic preflight."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.sales_order_enrichment import (
    _fetch_bc_order_lines,
    _optional_attr,
    enrich_sales_order_document,
)
from services.sales_order_source_inference import infer_sales_order_reference

_EXISTING_ORDER_ERROR_PREFIX = (
    "[Sales Order Intake] Existing Business Central sales order"
)

_EMPTY_VALUES = (None, "")


def _validation_messages(values: Any) -> List[Any]:
    if not values:
        return []
    if isinstance(values, list):
        return list(values)
    return [values]


def _message_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("message") or value.get("detail") or value)
    return str(value)


def _is_empty(value: Any) -> bool:
    return value in _EMPTY_VALUES or value == [] or value == {}


def _merge_document_records(
    primary: Dict[str, Any],
    fallback: Dict[str, Any],
) -> Dict[str, Any]:
    """Deep-merge records while preserving every populated primary value.

    ``sales_documents`` remains authoritative for workflow/review state. Empty
    fields are filled from the richer ``hub_documents`` companion record.
    """

    merged = copy.deepcopy(fallback or {})

    for key, primary_value in (primary or {}).items():
        fallback_value = merged.get(key)
        if isinstance(primary_value, dict) and isinstance(fallback_value, dict):
            merged[key] = _merge_document_records(
                primary_value,
                fallback_value,
            )
        elif _is_empty(primary_value) and not _is_empty(fallback_value):
            continue
        else:
            merged[key] = copy.deepcopy(primary_value)

    return merged


def _companion_queries(document: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    document_id = document.get("document_id") or document.get("id")
    file_hash = document.get("file_hash")
    message_id = document.get("email_message_id") or document.get(
        "internet_message_id"
    )
    file_name = document.get("file_name") or document.get("filename")

    queries: List[Tuple[str, Dict[str, Any]]] = []
    if document_id:
        queries.append(
            (
                "document_id",
                {"$or": [{"id": document_id}, {"document_id": document_id}]},
            )
        )
    if file_hash:
        queries.append(("file_hash", {"file_hash": file_hash}))
    if message_id and file_name:
        queries.append(
            (
                "message_and_file",
                {
                    "$and": [
                        {
                            "$or": [
                                {"email_message_id": message_id},
                                {"internet_message_id": message_id},
                            ]
                        },
                        {
                            "$or": [
                                {"file_name": file_name},
                                {"filename": file_name},
                            ]
                        },
                    ]
                },
            )
        )
    return queries


async def _find_companion_document(
    db,
    collection_name: str,
    document: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """Find the same logical document in the other migration collection."""

    other_collection_name = (
        "hub_documents"
        if collection_name == "sales_documents"
        else "sales_documents"
    )
    other_collection = getattr(db, other_collection_name, None)
    if other_collection is None:
        return None, None, None

    for match_method, query in _companion_queries(document):
        try:
            companion = await other_collection.find_one(query, {"_id": 0})
        except Exception:
            continue
        if companion:
            return companion, other_collection_name, match_method

    return None, other_collection_name, None


async def _hydrate_lines_from_existing_order(
    db,
    enriched: Dict[str, Any],
    evidence: Dict[str, Any],
) -> None:
    """Use existing BC order lines when a historical shell has no OCR lines."""

    if enriched.get("sales_order_lines"):
        return

    existing = evidence.get("existing_order") or {}
    record_id = existing.get("bc_record_id")
    if not record_id:
        return

    cache_class = _optional_attr(
        "services.bc_reference_cache_service",
        "BCReferenceCacheService",
    )
    if cache_class is None:
        evidence.setdefault("warnings", []).append(
            "BC cache service was unavailable for historical line hydration"
        )
        return

    try:
        cache = cache_class(db)
        bc_lines, warning = await _fetch_bc_order_lines(
            cache,
            {"bc_record_id": record_id},
        )
    except Exception as exc:
        evidence.setdefault("warnings", []).append(
            f"Historical BC line hydration failed: {exc}"
        )
        return

    if warning:
        evidence.setdefault("warnings", []).append(warning)
    evidence["existing_order_lines_checked"] = len(bc_lines)

    hydrated_lines: List[Dict[str, Any]] = []
    hydrated_mappings: List[Dict[str, Any]] = []
    for source_index, bc_line in enumerate(bc_lines, start=1):
        item_number = str(bc_line.get("lineObjectNumber") or "").strip()
        if not item_number:
            continue

        hydrated_lines.append(
            {
                "source_line_number": source_index,
                "itemNumber": item_number,
                "customerItemNumber": None,
                "description": bc_line.get("description"),
                "quantity": bc_line.get("quantity"),
                "unitOfMeasureCode": bc_line.get("unitOfMeasureCode"),
                "unitPrice": bc_line.get("unitPrice"),
                "mappingStatus": "existing_bc_order",
                "mappingApproved": False,
                "itemMatchConfidence": 1.0,
                "mappingMethod": "existing_bc_order_line_hydration",
                "catalogValidated": True,
            }
        )
        hydrated_mappings.append(
            {
                "line": len(hydrated_lines),
                "matched": True,
                "method": "existing_bc_order_line_hydration",
                "confidence": 1.0,
                "item_number": item_number,
                "uom": bc_line.get("unitOfMeasureCode"),
                "source": "existing_bc_order",
            }
        )

    if hydrated_lines:
        enriched["sales_order_lines"] = hydrated_lines
        evidence["line_mappings"] = hydrated_mappings
        evidence["hydrated_from_existing_order"] = True
        evidence["hydrated_line_count"] = len(hydrated_lines)


async def enrich_and_persist_sales_order_document(
    db,
    document_id: str,
) -> Dict[str, Any]:
    """Run existing resolvers and persist only their review-time evidence."""

    from services.sales_order_review_service import locate_document

    located = await locate_document(db, document_id)
    companion, companion_collection, companion_match = (
        await _find_companion_document(
            db,
            located.collection_name,
            located.document,
        )
    )
    source_document = _merge_document_records(
        located.document,
        companion or {},
    )
    source_document, reference_evidence = infer_sales_order_reference(
        source_document
    )

    enriched, evidence = await enrich_sales_order_document(
        db,
        source_document,
    )
    await _hydrate_lines_from_existing_order(db, enriched, evidence)

    evidence["source_reference"] = reference_evidence
    evidence["source_merge"] = {
        "primary_collection": located.collection_name,
        "companion_collection": companion_collection if companion else None,
        "companion_found": bool(companion),
        "match_method": companion_match,
        "companion_document_id": (
            (companion.get("document_id") or companion.get("id"))
            if companion
            else None
        ),
    }

    validation_errors = [
        value
        for value in _validation_messages(
            source_document.get("validation_errors")
        )
        if not _message_text(value).startswith(
            _EXISTING_ORDER_ERROR_PREFIX
        )
    ]

    existing_order = evidence.get("existing_order") or {}
    if existing_order:
        order_number = existing_order.get("bc_order_number") or "unknown"
        reference = reference_evidence.get("reference") or "the source reference"
        validation_errors.append(
            f"{_EXISTING_ORDER_ERROR_PREFIX} {order_number} matches "
            f"reference {reference}. Review the existing order instead of "
            "creating a duplicate."
        )

    now = datetime.now(timezone.utc).isoformat()
    update = {
        "bc_customer_no": enriched.get("bc_customer_no"),
        "bc_customer_number": enriched.get("bc_customer_number"),
        "customer_number_resolved": enriched.get(
            "customer_number_resolved"
        ),
        "matched_customer_no": enriched.get("matched_customer_no"),
        "customer_name_extracted": enriched.get(
            "customer_name_extracted"
        ),
        "customer_po_number": enriched.get("customer_po_number"),
        "order_number_extracted": enriched.get("order_number_extracted"),
        "extracted_fields": enriched.get("extracted_fields") or {},
        "normalized_fields": enriched.get("normalized_fields") or {},
        "resolved_customer": enriched.get("resolved_customer"),
        "sales_order_lines": enriched.get("sales_order_lines") or [],
        "sales_order_enrichment": evidence,
        "validation_errors": validation_errors,
        "sales_order_enriched_at": now,
        "updated_utc": now,
    }

    collection = getattr(db, located.collection_name)
    await collection.update_one(located.selector, {"$set": update})
    return evidence


async def run_enriched_shadow_preflight(
    db,
    document_id: str,
) -> Dict[str, Any]:
    """Enrich, persist, and then run the existing deterministic preflight."""

    await enrich_and_persist_sales_order_document(db, document_id)

    from services.sales_order_review_service import run_shadow_preflight

    result = await run_shadow_preflight(db, document_id)
    located_enrichment = result.get("enrichment")
    if located_enrichment is None:
        from services.sales_order_review_service import locate_document

        located = await locate_document(db, document_id)
        result["enrichment"] = located.document.get(
            "sales_order_enrichment"
        ) or {}
    return result


async def batch_enriched_preflight_pending(
    db,
    *,
    limit: int = 100,
) -> Dict[str, Any]:
    """Run guarded enrichment and deterministic preflight for queue records."""

    from services.sales_order_review_service import list_review_queue

    queue = await list_review_queue(
        db,
        limit=limit,
        refresh_missing=False,
    )
    results = []
    for item in queue:
        document_id = item.get("document_id")
        if not document_id:
            continue
        results.append(
            await run_enriched_shadow_preflight(db, document_id)
        )

    return {
        "evaluated": len(results),
        "ready": sum(
            1 for result in results if result.get("can_create")
        ),
        "blocked": sum(
            1 for result in results if not result.get("can_create")
        ),
        "results": results,
    }
