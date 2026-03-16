"""GPI Document Hub - Stable Vendor Auto-Ready Router"""

import logging
from fastapi import APIRouter, HTTPException, Body, Query, BackgroundTasks
from deps import get_db
from services.stable_vendor_service import get_stable_vendor_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stable-vendor", tags=["Stable Vendor"])


def _svc():
    svc = get_stable_vendor_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Stable vendor service not initialized")
    return svc


# ==================== CONFIG ====================

@router.get("/config")
async def get_stable_vendor_config():
    """Get current stable vendor configuration thresholds."""
    return await _svc().get_config()


@router.put("/config")
async def update_stable_vendor_config(updates: dict = Body(...)):
    """Update stable vendor configuration thresholds."""
    return await _svc().update_config(updates)


# ==================== DOCUMENT EVALUATION ====================

@router.get("/evaluate/{vendor_id}")
async def evaluate_vendor_stability(vendor_id: str):
    """Evaluate whether a specific vendor qualifies as stable."""
    return await _svc().evaluate_vendor_stability(vendor_id)


@router.post("/evaluate-document/{doc_id}")
async def evaluate_document_routing(doc_id: str):
    """Evaluate a document's stable-vendor auto-ready eligibility."""
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await _svc().evaluate_document(doc)

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "stable_vendor_routing": {
                "routing": result["routing"],
                "reasons": result["reasons"],
                "evaluated_at": result["evaluated_at"],
                "vendor_stable": result.get("vendor_stability", {}).get("stable_vendor_flag", False),
                "vendor_score": result.get("vendor_stability", {}).get("stable_vendor_score", 0),
                "checks": result.get("checks", []),
            },
            "updated_utc": result["evaluated_at"],
        }},
    )
    return result


# ==================== DASHBOARD ====================

@router.get("/dashboard-metrics")
async def get_stable_vendor_dashboard_metrics():
    """Get headline KPIs for the stable vendor dashboard widget."""
    return await _svc().get_dashboard_metrics()


@router.post("/reevaluate-all")
async def reevaluate_all_vendors(background_tasks: BackgroundTasks):
    """Full rebuild of vendor profiles from document data, then reevaluate stability."""
    from routers.vendor_profile_rebuild import rebuild_run

    async def _run():
        try:
            result = await rebuild_run()
            logger.info("[StableVendor] Profile rebuild complete: %s", result)
        except Exception as e:
            logger.error("[StableVendor] Profile rebuild failed: %s", e)

    background_tasks.add_task(_run)
    return {"status": "accepted", "message": "Vendor profile rebuild started in background"}


# ==================== ADMIN: VENDOR LIST / DETAIL ====================

@router.get("/vendors")
async def list_stable_vendors(
    search: str = Query("", description="Search by vendor name/no"),
    status: str = Query("", description="Filter: stable, watch, unstable, overridden"),
    sort_by: str = Query("stable_vendor_score", description="Sort field"),
    sort_dir: int = Query(-1, description="Sort direction: -1 desc, 1 asc"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """Get paginated vendor list for admin table with filtering/sorting."""
    return await _svc().get_vendor_list(
        search=search, status_filter=status,
        sort_by=sort_by, sort_dir=sort_dir,
        skip=skip, limit=limit,
    )


@router.get("/vendors/{vendor_no}")
async def get_stable_vendor_detail(vendor_no: str):
    """Get full vendor detail for the admin drawer."""
    detail = await _svc().get_vendor_detail(vendor_no)
    if not detail:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return detail


# ==================== ADMIN: OVERRIDE ACTIONS ====================

@router.post("/vendors/{vendor_no}/override")
async def apply_vendor_override(vendor_no: str, body: dict = Body(...)):
    """
    Apply a manual override to a vendor's status.
    Body: { status, reason, note, actor, expires_at }
    Valid statuses: force_stable, force_watch, force_unstable
    """
    override_status = body.get("status", "")
    reason = body.get("reason", "")
    note = body.get("note", "")
    actor = body.get("actor", "admin")
    expires_at = body.get("expires_at")

    if not override_status:
        raise HTTPException(status_code=400, detail="Override status required")

    result = await _svc().apply_override(
        vendor_no, override_status, reason=reason,
        actor=actor, expires_at=expires_at, note=note,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/vendors/{vendor_no}/clear-override")
async def clear_vendor_override(vendor_no: str, body: dict = Body({})):
    """Clear manual override, reverting to system-derived status."""
    actor = body.get("actor", "admin")
    reason = body.get("reason", "")
    result = await _svc().clear_override(vendor_no, actor=actor, reason=reason)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/vendors/{vendor_no}/history")
async def get_vendor_override_history(
    vendor_no: str,
    limit: int = Query(50, ge=1, le=200),
):
    """Get override audit history for a vendor."""
    return await _svc().get_override_history(vendor_no, limit=limit)
