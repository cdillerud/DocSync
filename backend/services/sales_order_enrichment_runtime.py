"""Orchestrate read-only sales-order enrichment before deterministic preflight."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.sales_order_enrichment import enrich_sales_order_document

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

    ``sales_documents`` remains authoritative for workflow/review state.  Empty
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

    enriched, evidence = await enrich_sales_order_document(
        db,
        source_document,
    )
    evidence["source_merge"] = {
        "primary_collection": located.collection_name,
        "companion_collection": companion_collection if companion else None,
        "companion_found": bool(companion),
        "match_method": companion_match,
        "companion_document_id": (
            companion.get("document_id") or companion.get("id")
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
        validation_errors.append(
            f"{_EXISTING_ORDER_ERROR_PREFIX} {order_number} already uses "
            "this customer PO. Review the existing order instead of creating "
            "a duplicate."
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
