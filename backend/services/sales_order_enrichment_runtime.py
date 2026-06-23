"""Orchestrate read-only sales-order enrichment before deterministic preflight."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from services.sales_order_enrichment import enrich_sales_order_document

_EXISTING_ORDER_ERROR_PREFIX = (
    "[Sales Order Intake] Existing Business Central sales order"
)


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


async def enrich_and_persist_sales_order_document(
    db,
    document_id: str,
) -> Dict[str, Any]:
    """Run existing resolvers and persist only their review-time evidence."""

    from services.sales_order_review_service import locate_document

    located = await locate_document(db, document_id)
    enriched, evidence = await enrich_sales_order_document(
        db,
        located.document,
    )

    validation_errors = [
        value
        for value in _validation_messages(
            located.document.get("validation_errors")
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
