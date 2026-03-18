"""
PO Resolution Metrics Router

Exposes truthful metrics for PO resolution and BC linkage rates.
"""
from fastapi import APIRouter
from deps import get_db

router = APIRouter(prefix="/po-resolution", tags=["PO Resolution"])


@router.get("/metrics")
async def get_po_resolution_metrics():
    """
    PO resolution and BC link metrics for shipping-style documents.
    Returns counts for the dashboard KPIs.
    """
    db = get_db()

    from services.po_resolution_service import PO_REQUIRED_DOC_TYPES
    doc_types = list(PO_REQUIRED_DOC_TYPES)

    # Total shipping-style docs
    total = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}}
    )

    # PO resolution attempted (has po_resolution field)
    po_attempted = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "po_resolution": {"$exists": True}}
    )

    # PO resolution statuses
    po_resolved = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "po_resolution.status": "resolved"}
    )
    po_ambiguous = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "po_resolution.status": "ambiguous"}
    )
    po_not_found = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "po_resolution.status": "not_found"}
    )
    po_skipped = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "po_resolution.status": "skipped"}
    )

    # BC link stats — real BC linkage (has bc_record_id from resolution)
    bc_link_attempted = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "po_resolution.bc_record_id": {"$nin": [None, ""]}}
    )
    bc_linked = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "po_resolution.status": "resolved", "po_resolution.bc_record_id": {"$nin": [None, ""]}}
    )

    # Docs still in NeedsReview
    needs_review = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "status": "NeedsReview"}
    )

    # PO candidates present but not resolved
    has_candidates_no_resolution = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types},
         "po_candidates.0": {"$exists": True},
         "$or": [
             {"po_resolution": {"$exists": False}},
             {"po_resolution.status": {"$in": ["not_found", "skipped"]}},
         ]}
    )

    # Match method distribution
    match_methods = {}
    pipeline = [
        {"$match": {"document_type": {"$in": doc_types}, "po_resolution.match_method": {"$ne": None}}},
        {"$group": {"_id": "$po_resolution.match_method", "count": {"$sum": 1}}},
    ]
    async for item in db.hub_documents.aggregate(pipeline):
        match_methods[item["_id"]] = item["count"]

    # By doc type breakdown
    type_breakdown = {}
    for dt in doc_types:
        dt_total = await db.hub_documents.count_documents({"document_type": dt})
        dt_resolved = await db.hub_documents.count_documents({"document_type": dt, "po_resolution.status": "resolved"})
        type_breakdown[dt] = {"total": dt_total, "resolved": dt_resolved}

    return {
        "total_shipping_docs": total,
        "po_resolution": {
            "attempted": po_attempted,
            "resolved": po_resolved,
            "ambiguous": po_ambiguous,
            "not_found": po_not_found,
            "skipped": po_skipped,
            "rate": round(po_resolved / po_attempted * 100, 1) if po_attempted > 0 else 0,
        },
        "bc_link": {
            "attempted": bc_link_attempted,
            "succeeded": bc_linked,
            "rate": round(bc_linked / total * 100, 1) if total > 0 else 0,
        },
        "queue": {
            "needs_review": needs_review,
            "has_candidates_unresolved": has_candidates_no_resolution,
        },
        "match_methods": match_methods,
        "by_doc_type": type_breakdown,
    }
