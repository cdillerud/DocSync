"""GPI Document Hub - Workflows Router (Domain 8)

Mutation routes (set-vendor, approve, reject, etc.) are sourced from
services.workflow_handlers (authoritative) and registered via add_api_route.
Simple query routes are implemented directly using deps.get_db().

DEPRECATION NOTICE (2026-04-21, AP_PATH_CONSOLIDATION.md Phase 2):
  The six /api/workflows/ap_invoice/{doc_id}/{action} mutation endpoints are
  DEPRECATED. Use the canonical /api/ap-review/documents/{doc_id}/{action}
  equivalents on Path A. These are kept live for one release with
  deprecated=True and an X-Deprecated response header; they will be removed
  in Phase 4.
"""

import logging
from functools import wraps
from typing import Optional, Dict

from fastapi import APIRouter, HTTPException, Query

from deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflows", tags=["Workflows"])


# =============================================================================
# DEPRECATION WRAPPER — adds X-Deprecated response header
# =============================================================================

def _deprecate(handler, canonical_path: str):
    """Wrap a workflow handler so every response carries X-Deprecated headers.

    Catches HTTPException raised by the inner handler and converts it to a
    JSONResponse so the deprecation headers survive error responses (404 on
    missing doc, 400 on invalid transitions, etc.). Success responses are
    re-wrapped in JSONResponse with the same headers attached.
    """
    from fastapi.responses import JSONResponse
    from fastapi.encoders import jsonable_encoder

    headers = {
        "X-Deprecated": "true",
        "X-Deprecated-Sunset": "next-release",
        "X-Deprecated-Use": canonical_path,
    }

    @wraps(handler)
    async def wrapper(*args, **kwargs):
        try:
            result = await handler(*args, **kwargs)
        except HTTPException as e:
            return JSONResponse(
                status_code=e.status_code,
                content={"detail": e.detail},
                headers={**(e.headers or {}), **headers},
            )
        return JSONResponse(content=jsonable_encoder(result), headers=headers)

    return wrapper


# =============================================================================
# COMPLEX ROUTES — Thin wrappers via add_api_route
# =============================================================================

_routes_registered = False


def register_server_routes(app=None):
    """Register workflow-domain handler functions on the app.

    Handlers are sourced from services.workflow_handlers (authoritative).
    Called from main.py during startup.
    """
    global _routes_registered
    if _routes_registered:
        return
    _routes_registered = True

    if app is None:
        logger.warning("No app provided to register_server_routes (workflows)")
        return

    from services.workflow_handlers import (
        set_vendor_for_document,
        update_document_fields,
        override_bc_validation,
        start_approval,
        approve_document,
        reject_document,
        mark_ready_for_review,
        mark_reviewed,
        start_approval_generic,
        approve_generic,
        reject_generic,
        complete_triage,
        link_credit_to_invoice,
        tag_quality_doc,
        export_document,
    )

    # AP Invoice mutation routes — DEPRECATED. Use /api/ap-review/documents/{id}/{action}.
    # Kept live for one release with X-Deprecated header; removed in Phase 4.
    app.add_api_route(
        "/api/workflows/ap_invoice/{doc_id}/set-vendor",
        _deprecate(set_vendor_for_document, "/api/ap-review/documents/{doc_id}/set-vendor"),
        methods=["POST"], tags=["Workflows"], deprecated=True,
    )
    app.add_api_route(
        "/api/workflows/ap_invoice/{doc_id}/update-fields",
        _deprecate(update_document_fields, "/api/ap-review/documents/{doc_id}/update-fields"),
        methods=["POST"], tags=["Workflows"], deprecated=True,
    )
    app.add_api_route(
        "/api/workflows/ap_invoice/{doc_id}/override-bc-validation",
        _deprecate(override_bc_validation, "/api/ap-review/documents/{doc_id}/override-bc-validation"),
        methods=["POST"], tags=["Workflows"], deprecated=True,
    )
    app.add_api_route(
        "/api/workflows/ap_invoice/{doc_id}/start-approval",
        _deprecate(start_approval, "/api/ap-review/documents/{doc_id}/start-approval"),
        methods=["POST"], tags=["Workflows"], deprecated=True,
    )
    app.add_api_route(
        "/api/workflows/ap_invoice/{doc_id}/approve",
        _deprecate(approve_document, "/api/ap-review/documents/{doc_id}/approve"),
        methods=["POST"], tags=["Workflows"], deprecated=True,
    )
    app.add_api_route(
        "/api/workflows/ap_invoice/{doc_id}/reject",
        _deprecate(reject_document, "/api/ap-review/documents/{doc_id}/reject"),
        methods=["POST"], tags=["Workflows"], deprecated=True,
    )

    # Generic workflow mutation routes
    app.add_api_route(
        "/api/workflows/{doc_id}/mark-ready-for-review", mark_ready_for_review,
        methods=["POST"], tags=["Workflows"]
    )
    app.add_api_route(
        "/api/workflows/{doc_id}/mark-reviewed", mark_reviewed,
        methods=["POST"], tags=["Workflows"]
    )
    app.add_api_route(
        "/api/workflows/{doc_id}/start-approval", start_approval_generic,
        methods=["POST"], tags=["Workflows"]
    )
    app.add_api_route(
        "/api/workflows/{doc_id}/approve", approve_generic,
        methods=["POST"], tags=["Workflows"]
    )
    app.add_api_route(
        "/api/workflows/{doc_id}/reject", reject_generic,
        methods=["POST"], tags=["Workflows"]
    )
    app.add_api_route(
        "/api/workflows/{doc_id}/complete-triage", complete_triage,
        methods=["POST"], tags=["Workflows"]
    )
    app.add_api_route(
        "/api/workflows/{doc_id}/link-credit-to-invoice", link_credit_to_invoice,
        methods=["POST"], tags=["Workflows"]
    )
    app.add_api_route(
        "/api/workflows/{doc_id}/tag-quality", tag_quality_doc,
        methods=["POST"], tags=["Workflows"]
    )
    app.add_api_route(
        "/api/workflows/{doc_id}/export", export_document,
        methods=["POST"], tags=["Workflows"]
    )


# =============================================================================
# SIMPLE QUERY ROUTES — Direct implementations
# =============================================================================

@router.get("")
async def list_workflows(skip: int = Query(0), limit: int = Query(50), status: str = Query(None)):
    db = get_db()
    fq = {}
    if status:
        fq["status"] = status
    workflows = await db.hub_workflow_runs.find(fq, {"_id": 0}).sort("started_utc", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.hub_workflow_runs.count_documents(fq)
    return {"workflows": workflows, "total": total}


@router.get("/ap_invoice/status-counts")
async def get_ap_workflow_status_counts():
    """Get counts of AP_INVOICE documents by workflow status."""
    from services.workflow_engine import WorkflowEngine, DocType

    db = get_db()
    pipeline = [
        {"$match": {"$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ]}},
        {"$group": {"_id": "$workflow_status", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}
    ]
    results = await db.hub_documents.aggregate(pipeline).to_list(100)
    counts = {r["_id"] or "none": r["count"] for r in results}

    return {
        "status_counts": counts,
        "total": sum(counts.values()),
        "exception_queue_total": sum(
            counts.get(s, 0) for s in WorkflowEngine.get_exception_statuses(DocType.AP_INVOICE.value)
        )
    }


@router.get("/ap_invoice/vendor-pending")
async def get_vendor_pending_queue(
    skip: int = Query(0), limit: int = Query(50),
    vendor_raw: Optional[str] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None)
):
    from services.workflow_engine import DocType, WorkflowStatus

    db = get_db()
    fq: Dict = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.VENDOR_PENDING.value
    }
    if vendor_raw:
        fq["vendor_raw"] = {"$regex": vendor_raw, "$options": "i"}
    if min_amount is not None:
        fq["amount_float"] = {"$gte": min_amount}
    if max_amount is not None:
        fq.setdefault("amount_float", {})["$lte"] = max_amount
    if date_from:
        fq["created_utc"] = {"$gte": f"{date_from}T00:00:00"}
    if date_to:
        fq.setdefault("created_utc", {})["$lte"] = f"{date_to}T23:59:59.999999"

    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    return {"documents": docs, "total": total, "queue": "vendor_pending"}


@router.get("/ap_invoice/bc-validation-pending")
async def get_bc_validation_pending_queue(
    skip: int = Query(0), limit: int = Query(50),
    vendor_canonical: Optional[str] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None)
):
    from services.workflow_engine import DocType, WorkflowStatus

    db = get_db()
    fq: Dict = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.BC_VALIDATION_PENDING.value
    }
    if vendor_canonical:
        fq["vendor_canonical"] = vendor_canonical
    if min_amount is not None:
        fq["amount_float"] = {"$gte": min_amount}
    if max_amount is not None:
        fq.setdefault("amount_float", {})["$lte"] = max_amount

    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    return {"documents": docs, "total": total, "queue": "bc_validation_pending"}


@router.get("/ap_invoice/bc-validation-failed")
async def get_bc_validation_failed_queue(
    skip: int = Query(0), limit: int = Query(50),
    vendor_canonical: Optional[str] = Query(None)
):
    from services.workflow_engine import DocType, WorkflowStatus

    db = get_db()
    fq: Dict = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.BC_VALIDATION_FAILED.value
    }
    if vendor_canonical:
        fq["vendor_canonical"] = vendor_canonical

    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    return {"documents": docs, "total": total, "queue": "bc_validation_failed"}


@router.get("/ap_invoice/data-correction-pending")
async def get_data_correction_pending_queue(
    skip: int = Query(0), limit: int = Query(50),
    vendor_canonical: Optional[str] = Query(None)
):
    from services.workflow_engine import DocType, WorkflowStatus

    db = get_db()
    fq: Dict = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.DATA_CORRECTION_PENDING.value
    }
    if vendor_canonical:
        fq["vendor_canonical"] = vendor_canonical

    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    return {"documents": docs, "total": total, "queue": "data_correction_pending"}


@router.get("/ap_invoice/ready-for-approval")
async def get_ready_for_approval_queue(
    skip: int = Query(0), limit: int = Query(50),
    vendor_canonical: Optional[str] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None)
):
    from services.workflow_engine import DocType, WorkflowStatus

    db = get_db()
    fq: Dict = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.READY_FOR_APPROVAL.value
    }
    if vendor_canonical:
        fq["vendor_canonical"] = vendor_canonical
    if min_amount is not None:
        fq["amount_float"] = {"$gte": min_amount}
    if max_amount is not None:
        fq.setdefault("amount_float", {})["$lte"] = max_amount

    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    return {"documents": docs, "total": total, "queue": "ready_for_approval"}


@router.get("/generic/queue")
async def get_generic_workflow_queue(
    doc_type: Optional[str] = Query(None, description="Filter by doc_type"),
    workflow_status: Optional[str] = Query(None, description="Filter by workflow_status"),
    category: Optional[str] = Query(None, description="Filter by category"),
    skip: int = Query(0),
    limit: int = Query(50)
):
    from services.workflow_engine import DocType

    db = get_db()
    non_ap_types = [dt.value for dt in DocType if dt != DocType.AP_INVOICE]

    fq: Dict = {"doc_type": {"$in": non_ap_types}} if not doc_type else {"doc_type": doc_type}
    if workflow_status:
        fq["workflow_status"] = workflow_status
    if category:
        fq["category"] = category

    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    return {"documents": docs, "total": total, "queue": "generic"}


@router.get("/generic/status-counts-by-type")
async def get_generic_status_counts_by_type():
    from services.workflow_engine import DocType

    db = get_db()
    non_ap_types = [dt.value for dt in DocType if dt != DocType.AP_INVOICE]

    pipeline = [
        {"$match": {"doc_type": {"$in": non_ap_types}}},
        {"$group": {"_id": {"doc_type": "$doc_type", "status": "$workflow_status"}, "count": {"$sum": 1}}},
        {"$sort": {"_id.doc_type": 1, "_id.status": 1}}
    ]
    results = await db.hub_documents.aggregate(pipeline).to_list(500)

    by_type: Dict = {}
    for r in results:
        dt = r["_id"]["doc_type"]
        status = r["_id"]["status"] or "none"
        by_type.setdefault(dt, {})[status] = r["count"]

    return {"status_counts_by_type": by_type, "doc_types": list(by_type.keys())}


@router.get("/generic/metrics-by-type")
async def get_generic_metrics_by_type():
    from services.workflow_engine import DocType

    db = get_db()
    non_ap_types = [dt.value for dt in DocType if dt != DocType.AP_INVOICE]

    pipeline = [
        {"$match": {"doc_type": {"$in": non_ap_types}}},
        {"$group": {
            "_id": "$doc_type",
            "total": {"$sum": 1},
            "completed": {"$sum": {"$cond": [{"$eq": ["$workflow_status", "completed"]}, 1, 0]}},
            "active": {"$sum": {"$cond": [{"$in": ["$workflow_status", ["captured", "classifying", "ready_for_review", "in_review", "pending_approval"]]}, 1, 0]}},
            "exceptions": {"$sum": {"$cond": [{"$in": ["$workflow_status", ["classification_failed", "review_exception"]]}, 1, 0]}}
        }},
        {"$sort": {"_id": 1}}
    ]
    results = await db.hub_documents.aggregate(pipeline).to_list(100)

    metrics = {}
    for r in results:
        dt = r["_id"]
        total = r["total"]
        metrics[dt] = {
            "total": total,
            "completed": r["completed"],
            "active": r["active"],
            "exceptions": r["exceptions"],
            "completion_rate": round(r["completed"] / total * 100, 1) if total > 0 else 0
        }

    return {"metrics_by_type": metrics}


@router.get("/ap_invoice/metrics")
async def get_ap_workflow_metrics():
    from services.workflow_engine import DocType

    db = get_db()
    pipeline = [
        {"$match": {"$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ]}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "completed": {"$sum": {"$cond": [{"$eq": ["$workflow_status", "approved"]}, 1, 0]}},
            "vendor_pending": {"$sum": {"$cond": [{"$eq": ["$workflow_status", "vendor_pending"]}, 1, 0]}},
            "bc_validation": {"$sum": {"$cond": [{"$eq": ["$workflow_status", "bc_validation_pending"]}, 1, 0]}},
            "bc_failed": {"$sum": {"$cond": [{"$eq": ["$workflow_status", "bc_validation_failed"]}, 1, 0]}},
            "data_correction": {"$sum": {"$cond": [{"$eq": ["$workflow_status", "data_correction_pending"]}, 1, 0]}},
            "ready_for_approval": {"$sum": {"$cond": [{"$eq": ["$workflow_status", "ready_for_approval"]}, 1, 0]}},
            "rejected": {"$sum": {"$cond": [{"$eq": ["$workflow_status", "rejected"]}, 1, 0]}},
            "auto_match_vendor": {"$sum": {"$cond": [{"$eq": ["$vendor_match_method", "auto"]}, 1, 0]}},
            "manual_match_vendor": {"$sum": {"$cond": [{"$eq": ["$vendor_match_method", "manual"]}, 1, 0]}}
        }}
    ]
    results = await db.hub_documents.aggregate(pipeline).to_list(1)

    if not results:
        return {"metrics": {"total": 0}}

    m = results[0]
    m.pop("_id", None)
    total = m.get("total", 0)

    m["automation_rate"] = round(
        m.get("auto_match_vendor", 0) / total * 100, 1
    ) if total > 0 else 0

    return {"metrics": m}


@router.get("/{wf_id}")
async def get_workflow(wf_id: str):
    db = get_db()
    wf = await db.hub_workflow_runs.find_one({"id": wf_id}, {"_id": 0})
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


@router.post("/{wf_id}/retry")
async def retry_workflow(wf_id: str):
    db = get_db()
    wf = await db.hub_workflow_runs.find_one({"id": wf_id}, {"_id": 0})
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    doc_id = wf.get("document_id")
    if not doc_id:
        raise HTTPException(status_code=400, detail="No document associated with this workflow")
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Associated document not found")
    if doc.get("sharepoint_share_link_url") and (doc.get("bc_record_id") or doc.get("bc_document_no")):
        from server import link_document
        result = await link_document(doc_id)
        return {"message": "Retry completed", "result": result}
    return {"message": "Cannot retry - document missing SharePoint link or BC reference"}
