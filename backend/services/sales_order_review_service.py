"""Sales-order review, shadow preflight, approval, and controlled creation.

The current application stores Sales mailbox documents in ``sales_documents``
while older workflows use ``hub_documents``. This service intentionally supports
both collections during the migration to a unified document model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo import ReturnDocument

from services.sales_order_bc_lookup import find_existing_bc_sales_order
from services.sales_order_bc_writer import create_sales_order_draft
from services.sales_order_preflight import (
    build_bc_sales_order_payload,
    preflight_sales_order,
)
from services.sales_order_runtime import prepare_sales_order_document

SALES_ORDER_TYPES = [
    "Sales_Order",
    "SALES_ORDER",
    "SalesOrder",
    "CUSTOMER_PO",
    "CUSTOMER_PURCHASE_ORDER",
]

_NORMALIZED_SALES_ORDER_TYPES = {
    "SALES_ORDER",
    "SALESORDER",
    "CUSTOMER_PO",
    "CUSTOMER_PURCHASE_ORDER",
}


def _normalize_document_type(value: Any) -> str:
    if not value:
        return ""
    return str(value).strip().upper().replace("-", "_").replace(" ", "_")


def _effective_document_type(doc: Dict[str, Any]) -> str:
    """Return the first populated classification using current-field precedence."""

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
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


@dataclass
class LocatedDocument:
    collection_name: str
    id_field: str
    document_id: str
    document: Dict[str, Any]

    @property
    def selector(self) -> Dict[str, Any]:
        return {self.id_field: self.document_id}


class SalesOrderDocumentNotFound(LookupError):
    pass


def writes_enabled() -> bool:
    return os.environ.get(
        "AUTO_CREATE_SALES_ORDER_ENABLED", "false"
    ).strip().lower() in {"true", "1", "yes"}


def _threshold(name: str, default: str) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


async def locate_document(db, document_id: str) -> LocatedDocument:
    sales_doc = await db.sales_documents.find_one(
        {"document_id": document_id},
        {"_id": 0},
    )
    if sales_doc:
        return LocatedDocument(
            collection_name="sales_documents",
            id_field="document_id",
            document_id=document_id,
            document=sales_doc,
        )

    hub_doc = await db.hub_documents.find_one(
        {"$or": [{"id": document_id}, {"document_id": document_id}]},
        {"_id": 0},
    )
    if hub_doc:
        id_field = "id" if hub_doc.get("id") == document_id else "document_id"
        return LocatedDocument(
            collection_name="hub_documents",
            id_field=id_field,
            document_id=document_id,
            document=hub_doc,
        )

    raise SalesOrderDocumentNotFound(document_id)


async def run_shadow_preflight(db, document_id: str) -> Dict[str, Any]:
    located = await locate_document(db, document_id)
    prepared = prepare_sales_order_document(located.document)
    result = preflight_sales_order(
        prepared,
        confidence_threshold=_threshold(
            "SALES_ORDER_CONFIDENCE_THRESHOLD", "0.90"
        ),
        item_match_threshold=_threshold(
            "SALES_ORDER_ITEM_MATCH_THRESHOLD", "0.95"
        ),
        require_sharepoint=True,
        require_approval=True,
    )
    result_dict = result.to_dict()
    now = datetime.now(timezone.utc).isoformat()
    collection = getattr(db, located.collection_name)

    await collection.update_one(
        located.selector,
        {
            "$set": {
                "sales_order_preflight": result_dict,
                "sales_order_preflight_at": now,
                "sales_order_idempotency_key": result.candidate.get(
                    "idempotencyKey"
                ),
                "bc_create_ready": result.can_create,
                "updated_utc": now,
            }
        },
    )

    return {
        "document_id": document_id,
        "collection": located.collection_name,
        "write_enabled": writes_enabled(),
        **result_dict,
    }


async def list_review_queue(
    db,
    *,
    limit: int = 50,
    refresh_missing: bool = True,
) -> List[Dict[str, Any]]:
    per_collection_limit = max(1, min(limit, 200))

    sales_docs = await db.sales_documents.find(
        {
            "document_type": {"$in": SALES_ORDER_TYPES},
            "bc_posting_status": {"$nin": ["created", "auto_created"]},
        },
        {"_id": 0},
    ).sort("created_utc", -1).limit(per_collection_limit).to_list(
        per_collection_limit
    )

    hub_docs = await db.hub_documents.find(
        {
            "$and": [
                {
                    "$or": [
                        {"doc_type": {"$in": SALES_ORDER_TYPES}},
                        {"document_type": {"$in": SALES_ORDER_TYPES}},
                        {"suggested_job_type": {"$in": SALES_ORDER_TYPES}},
                    ]
                },
                {
                    "bc_posting_status": {
                        "$nin": ["created", "auto_created"]
                    }
                },
            ]
        },
        {"_id": 0},
    ).sort("created_utc", -1).limit(per_collection_limit).to_list(
        per_collection_limit
    )

    combined: List[Tuple[str, Dict[str, Any]]] = [
        ("sales_documents", doc) for doc in sales_docs
    ] + [("hub_documents", doc) for doc in hub_docs]

    combined = [
        (collection_name, doc)
        for collection_name, doc in combined
        if _normalize_document_type(_effective_document_type(doc))
        in _NORMALIZED_SALES_ORDER_TYPES
    ]

    combined.sort(
        key=lambda item: item[1].get("created_utc") or "",
        reverse=True,
    )
    combined = combined[:limit]

    if refresh_missing:
        for _, doc in combined:
            if doc.get("sales_order_preflight"):
                continue
            doc_id = doc.get("document_id") or doc.get("id")
            if not doc_id:
                continue
            await run_shadow_preflight(db, doc_id)

        # Re-read so the response contains the results just persisted.
        refreshed: List[Dict[str, Any]] = []
        for collection_name, doc in combined:
            doc_id = doc.get("document_id") or doc.get("id")
            if not doc_id:
                continue
            located = await locate_document(db, doc_id)
            refreshed.append(
                _queue_item(located.document, collection_name)
            )
        return refreshed

    return [
        _queue_item(doc, collection_name)
        for collection_name, doc in combined
    ]


async def approve_candidate(
    db,
    document_id: str,
    *,
    reviewer: str,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("Reviewer is required")

    located = await locate_document(db, document_id)
    now = datetime.now(timezone.utc).isoformat()
    collection = getattr(db, located.collection_name)
    update: Dict[str, Any] = {
        "sales_order_approved": True,
        "review_status": "approved",
        "sales_order_approved_by": reviewer,
        "sales_order_approved_at": now,
        "updated_utc": now,
    }
    if note:
        update["sales_order_approval_note"] = note.strip()

    await collection.update_one(located.selector, {"$set": update})
    return await run_shadow_preflight(db, document_id)


async def reject_candidate(
    db,
    document_id: str,
    *,
    reviewer: str,
    reason: str,
) -> Dict[str, Any]:
    reviewer = reviewer.strip()
    reason = reason.strip()
    if not reviewer or not reason:
        raise ValueError("Reviewer and rejection reason are required")

    located = await locate_document(db, document_id)
    now = datetime.now(timezone.utc).isoformat()
    collection = getattr(db, located.collection_name)
    await collection.update_one(
        located.selector,
        {
            "$set": {
                "sales_order_approved": False,
                "review_status": "rejected",
                "sales_order_rejected_by": reviewer,
                "sales_order_rejected_at": now,
                "sales_order_rejection_reason": reason,
                "bc_create_ready": False,
                "updated_utc": now,
            }
        },
    )
    return await run_shadow_preflight(db, document_id)


async def create_draft_order(
    db,
    bc_service,
    document_id: str,
) -> Dict[str, Any]:
    preflight = await run_shadow_preflight(db, document_id)
    if not preflight.get("can_create"):
        return {
            "success": False,
            "status": "preflight_blocked",
            "message": "Sales-order preflight did not pass",
            "preflight": preflight,
        }

    if not writes_enabled():
        return {
            "success": False,
            "status": "shadow_mode",
            "message": (
                "Preflight passed, but Business Central writes are disabled"
            ),
            "preflight": preflight,
        }

    located = await locate_document(db, document_id)
    candidate = preflight["candidate"]

    local_duplicate = await _find_local_duplicate(
        db,
        document_id=document_id,
        idempotency_key=candidate["idempotencyKey"],
    )
    if local_duplicate:
        return {
            "success": False,
            "status": "duplicate_blocked",
            "message": "The customer PO already has an active Hub order",
            "duplicate": local_duplicate,
            "preflight": preflight,
        }

    bc_duplicate = await find_existing_bc_sales_order(
        bc_service,
        customer_number=candidate["customerNumber"],
        external_document_number=candidate["externalDocumentNumber"],
    )
    if bc_duplicate:
        await _mark_duplicate(
            db,
            located,
            message=(
                "The customer PO already exists in Business Central as "
                f"{bc_duplicate.get('number')}"
            ),
        )
        return {
            "success": False,
            "status": "duplicate_blocked",
            "message": "The customer PO already exists in Business Central",
            "duplicate": bc_duplicate,
            "preflight": preflight,
        }

    collection = getattr(db, located.collection_name)
    now = datetime.now(timezone.utc).isoformat()
    locked = await collection.find_one_and_update(
        {
            **located.selector,
            "$and": [
                {
                    "$or": [
                        {"bc_document_id": {"$exists": False}},
                        {"bc_document_id": None},
                    ]
                },
                {
                    "$or": [
                        {"bc_sales_order_id": {"$exists": False}},
                        {"bc_sales_order_id": None},
                    ]
                },
                {
                    "bc_posting_status": {
                        "$nin": ["auto_creating", "created"]
                    }
                },
            ],
        },
        {
            "$set": {
                "bc_posting_status": "auto_creating",
                "auto_create_attempted": True,
                "auto_create_attempted_at": now,
                "sales_order_idempotency_key": candidate[
                    "idempotencyKey"
                ],
                "updated_utc": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if not locked:
        return {
            "success": False,
            "status": "creation_locked",
            "message": "Creation is already in progress or completed",
            "preflight": preflight,
        }

    result = await create_sales_order_draft(
        bc_service,
        build_bc_sales_order_payload(candidate),
    )
    await _persist_creation_result(db, located, result)

    return {
        **result,
        "document_id": document_id,
        "collection": located.collection_name,
        "preflight": preflight,
    }


async def batch_preflight_pending(
    db,
    *,
    limit: int = 100,
) -> Dict[str, Any]:
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
        results.append(await run_shadow_preflight(db, document_id))

    return {
        "evaluated": len(results),
        "ready": sum(1 for result in results if result.get("can_create")),
        "blocked": sum(
            1 for result in results if not result.get("can_create")
        ),
        "write_enabled": writes_enabled(),
        "results": results,
    }


async def _find_local_duplicate(
    db,
    *,
    document_id: str,
    idempotency_key: str,
) -> Optional[Dict[str, Any]]:
    active_statuses = ["auto_creating", "created", "auto_create_partial"]
    for collection_name, id_field in (
        ("sales_documents", "document_id"),
        ("hub_documents", "id"),
    ):
        collection = getattr(db, collection_name)
        duplicate = await collection.find_one(
            {
                id_field: {"$ne": document_id},
                "sales_order_idempotency_key": idempotency_key,
                "bc_posting_status": {"$in": active_statuses},
            },
            {
                "_id": 0,
                "id": 1,
                "document_id": 1,
                "bc_document_id": 1,
                "bc_document_number": 1,
                "bc_sales_order_id": 1,
                "bc_sales_order_number": 1,
            },
        )
        if duplicate:
            duplicate["collection"] = collection_name
            return duplicate
    return None


async def _mark_duplicate(
    db,
    located: LocatedDocument,
    *,
    message: str,
) -> None:
    collection = getattr(db, located.collection_name)
    await collection.update_one(
        located.selector,
        {
            "$set": {
                "bc_posting_status": "duplicate_blocked",
                "auto_create_error": message,
                "bc_create_ready": False,
                "review_status": "needs_review",
                "updated_utc": datetime.now(timezone.utc).isoformat(),
            }
        },
    )


async def _persist_creation_result(
    db,
    located: LocatedDocument,
    result: Dict[str, Any],
) -> None:
    collection = getattr(db, located.collection_name)
    now = datetime.now(timezone.utc).isoformat()
    success = bool(result.get("success"))
    manual_cleanup = bool(result.get("manualCleanupRequired"))
    bc_document_id = result.get("bcDocumentId")
    bc_document_number = result.get("bcDocumentNumber")

    update = {
        "bc_document_id": bc_document_id,
        "bc_document_number": bc_document_number,
        "bc_sales_order_id": bc_document_id,
        "bc_sales_order_number": bc_document_number,
        "bc_posting_status": (
            "created"
            if success
            else (
                "auto_create_partial"
                if manual_cleanup
                else "auto_create_failed"
            )
        ),
        "bc_posting_error": None if success else result.get("error"),
        "bc_line_errors": result.get("lineErrors") or [],
        "manual_bc_cleanup_required": manual_cleanup,
        "auto_create_success": success,
        "updated_utc": now,
    }
    if success:
        update.update(
            {
                "review_status": "auto_created",
                "status": "Created",
                "workflow_status": "exported",
                "created_in_bc_utc": now,
            }
        )
    else:
        update["review_status"] = "needs_review"

    await collection.update_one(located.selector, {"$set": update})


def _queue_item(
    doc: Dict[str, Any],
    collection_name: str,
) -> Dict[str, Any]:
    preflight = doc.get("sales_order_preflight") or {}
    candidate = preflight.get("candidate") or {}
    return {
        "document_id": doc.get("document_id") or doc.get("id"),
        "collection": collection_name,
        "file_name": doc.get("file_name") or doc.get("filename"),
        "created_utc": doc.get("created_utc"),
        "document_type": _effective_document_type(doc),
        "customer_name": candidate.get("customerName") or doc.get(
            "customer_name_extracted"
        ),
        "customer_number": candidate.get("customerNumber"),
        "customer_po_number": candidate.get("externalDocumentNumber"),
        "review_status": doc.get("review_status"),
        "bc_posting_status": doc.get("bc_posting_status"),
        "bc_create_ready": bool(doc.get("bc_create_ready")),
        "preflight": preflight,
    }
