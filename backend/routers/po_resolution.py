"""
PO Resolution Metrics Router

Exposes truthful metrics for PO resolution and BC linkage rates.
Includes miss taxonomy, BC link failure breakdown, and batch validation.
"""
from fastapi import APIRouter, Query
from deps import get_db

router = APIRouter(prefix="/po-resolution", tags=["PO Resolution"])


@router.get("/metrics")
async def get_po_resolution_metrics():
    """PO resolution and BC link metrics for shipping-style documents."""
    db = get_db()

    from services.po_resolution_service import PO_REQUIRED_DOC_TYPES
    doc_types = list(PO_REQUIRED_DOC_TYPES)

    total = await db.hub_documents.count_documents({"document_type": {"$in": doc_types}})
    po_attempted = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "po_resolution": {"$exists": True}}
    )
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

    # Miss reason breakdown
    miss_pipeline = [
        {"$match": {"document_type": {"$in": doc_types}, "po_resolution.miss_reason": {"$ne": None}}},
        {"$group": {"_id": "$po_resolution.miss_reason", "count": {"$sum": 1}}},
    ]
    unresolved_by_miss_reason = {}
    async for item in db.hub_documents.aggregate(miss_pipeline):
        unresolved_by_miss_reason[item["_id"]] = item["count"]

    # BC link stats — real BC linkage only (has bc_record_id AND linked status)
    bc_link_attempted = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "po_resolution.bc_link": {"$exists": True}}
    )
    bc_linked_real = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "po_resolution.bc_link.status": "linked"}
    )
    bc_linked_local = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "po_resolution.bc_link.status": "linked_local"}
    )
    bc_link_failed = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "po_resolution.bc_link.status": "failed"}
    )

    # BC link failure reasons
    bc_fail_pipeline = [
        {"$match": {"document_type": {"$in": doc_types}, "po_resolution.bc_link.status": "failed"}},
        {"$group": {"_id": "$po_resolution.bc_link.error_code", "count": {"$sum": 1}}},
    ]
    bc_link_failures_by_reason = {}
    async for item in db.hub_documents.aggregate(bc_fail_pipeline):
        bc_link_failures_by_reason[item["_id"] or "unknown"] = item["count"]

    # Match method distribution
    method_pipeline = [
        {"$match": {"document_type": {"$in": doc_types}, "po_resolution.match_method": {"$ne": None}}},
        {"$group": {"_id": "$po_resolution.match_method", "count": {"$sum": 1}}},
    ]
    match_methods = {}
    async for item in db.hub_documents.aggregate(method_pipeline):
        match_methods[item["_id"]] = item["count"]

    # Lookup source distribution
    source_pipeline = [
        {"$match": {"document_type": {"$in": doc_types}, "po_resolution.lookup_source": {"$ne": None}}},
        {"$group": {"_id": "$po_resolution.lookup_source", "count": {"$sum": 1}}},
    ]
    lookup_sources = {}
    async for item in db.hub_documents.aggregate(source_pipeline):
        lookup_sources[item["_id"]] = item["count"]

    # Multi-PO docs
    multi_po = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "po_candidates.2": {"$exists": True}}
    )

    needs_review = await db.hub_documents.count_documents(
        {"document_type": {"$in": doc_types}, "status": "NeedsReview"}
    )

    # By doc type breakdown
    type_breakdown = {}
    for dt in doc_types:
        dt_total = await db.hub_documents.count_documents({"document_type": dt})
        dt_resolved = await db.hub_documents.count_documents(
            {"document_type": dt, "po_resolution.status": "resolved"}
        )
        dt_bc_linked = await db.hub_documents.count_documents(
            {"document_type": dt, "po_resolution.bc_link.status": "linked"}
        )
        type_breakdown[dt] = {"total": dt_total, "resolved": dt_resolved, "bc_linked": dt_bc_linked}

    cache_match_count = lookup_sources.get("bc_cache", 0)
    live_bc_match_count = lookup_sources.get("bc_api", 0)
    local_match_count = lookup_sources.get("local_staging", 0)

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
            "succeeded_real": bc_linked_real,
            "succeeded_local": bc_linked_local,
            "failed": bc_link_failed,
            "rate_real": round(bc_linked_real / total * 100, 1) if total > 0 else 0,
            "rate_total": round((bc_linked_real + bc_linked_local) / total * 100, 1) if total > 0 else 0,
        },
        "unresolved_by_miss_reason": unresolved_by_miss_reason,
        "bc_link_failures_by_reason": bc_link_failures_by_reason,
        "match_methods": match_methods,
        "lookup_sources": {
            "bc_cache": cache_match_count,
            "bc_api": live_bc_match_count,
            "local_staging": local_match_count,
        },
        "multi_po_count": multi_po,
        "queue": {"needs_review": needs_review},
        "by_doc_type": type_breakdown,
    }


@router.post("/batch-resolve")
async def batch_resolve_po(
    doc_types: str = Query("Shipping_Document,Warehouse_Receipt,Freight_Document"),
    limit: int = Query(200),
    force: bool = Query(False, description="Re-resolve even if po_resolution already exists"),
    status_filter: str = Query(None, description="Filter by document status e.g. NeedsReview"),
):
    """Batch resolve PO for shipping-style documents. Returns a summary."""
    db = get_db()

    from services.po_resolution_service import (
        extract_po_candidates, resolve_po, attempt_bc_link, PO_REQUIRED_DOC_TYPES,
    )

    types = [t.strip() for t in doc_types.split(",") if t.strip()]
    query = {"document_type": {"$in": types}}
    if not force:
        query["$or"] = [
            {"po_resolution": {"$exists": False}},
            {"po_resolution": None},
        ]
    if status_filter:
        query["status"] = status_filter

    docs = await db.hub_documents.find(
        query,
        {"_id": 0, "id": 1, "file_name": 1, "document_type": 1,
         "extracted_fields": 1, "raw_text": 1, "po_candidates": 1}
    ).limit(limit).to_list(limit)

    stats = {
        "processed": 0,
        "resolved": 0,
        "ambiguous": 0,
        "not_found": 0,
        "bc_link_attempted": 0,
        "bc_link_succeeded": 0,
        "bc_link_failed": 0,
        "miss_reasons": {},
        "bc_link_failures": {},
        "by_doc_type": {},
        "details": [],
    }

    for doc in docs:
        doc_id = doc["id"]
        doc_type = doc.get("document_type", "")
        ef = doc.get("extracted_fields") or {}
        raw_text = doc.get("raw_text") or ""

        candidates = extract_po_candidates(raw_text, ef)

        result = await resolve_po(
            po_candidates=candidates,
            doc_type=doc_type,
            document_id=doc_id,
            source_filename=doc.get("file_name", ""),
        )

        bc_link = await attempt_bc_link(doc_id, result)
        result["bc_link"] = bc_link

        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {"po_resolution": result, "po_candidates": candidates}},
        )

        status = result["status"]
        stats["processed"] += 1
        if status == "resolved":
            stats["resolved"] += 1
        elif status == "ambiguous":
            stats["ambiguous"] += 1
        else:
            stats["not_found"] += 1

        miss = result.get("miss_reason")
        if miss:
            stats["miss_reasons"][miss] = stats["miss_reasons"].get(miss, 0) + 1

        if bc_link.get("status") in ("linked", "linked_local"):
            stats["bc_link_succeeded"] += 1
            stats["bc_link_attempted"] += 1
        elif bc_link.get("status") == "failed":
            stats["bc_link_failed"] += 1
            stats["bc_link_attempted"] += 1
            err = bc_link.get("error_code", "unknown")
            stats["bc_link_failures"][err] = stats["bc_link_failures"].get(err, 0) + 1

        dt = doc_type
        if dt not in stats["by_doc_type"]:
            stats["by_doc_type"][dt] = {"total": 0, "resolved": 0}
        stats["by_doc_type"][dt]["total"] += 1
        if status == "resolved":
            stats["by_doc_type"][dt]["resolved"] += 1

        if len(stats["details"]) < 50:
            stats["details"].append({
                "doc_id": doc_id,
                "file_name": doc.get("file_name", ""),
                "status": status,
                "miss_reason": miss,
                "po_number": result.get("po_number"),
                "bc_link_status": bc_link.get("status"),
            })

    stats["po_resolution_rate"] = round(
        stats["resolved"] / stats["processed"] * 100, 1
    ) if stats["processed"] > 0 else 0
    stats["bc_link_success_rate"] = round(
        stats["bc_link_succeeded"] / stats["processed"] * 100, 1
    ) if stats["processed"] > 0 else 0

    return stats
