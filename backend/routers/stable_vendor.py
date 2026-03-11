"""GPI Document Hub - Stable Vendor Auto-Ready Router"""

import asyncio
import logging
from fastapi import APIRouter, HTTPException, Body, BackgroundTasks
from deps import get_db
from services.stable_vendor_service import get_stable_vendor_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stable-vendor", tags=["Stable Vendor"])


@router.get("/config")
async def get_stable_vendor_config():
    """Get current stable vendor configuration thresholds."""
    svc = get_stable_vendor_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Stable vendor service not initialized")
    return await svc.get_config()


@router.put("/config")
async def update_stable_vendor_config(updates: dict = Body(...)):
    """Update stable vendor configuration thresholds."""
    svc = get_stable_vendor_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Stable vendor service not initialized")
    return await svc.update_config(updates)


@router.get("/evaluate/{vendor_id}")
async def evaluate_vendor_stability(vendor_id: str):
    """Evaluate whether a specific vendor qualifies as stable."""
    svc = get_stable_vendor_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Stable vendor service not initialized")
    return await svc.evaluate_vendor_stability(vendor_id)


@router.post("/evaluate-document/{doc_id}")
async def evaluate_document_routing(doc_id: str):
    """Evaluate a document's stable-vendor auto-ready eligibility."""
    svc = get_stable_vendor_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Stable vendor service not initialized")
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await svc.evaluate_document(doc)

    # Store the routing decision on the document
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


@router.get("/dashboard-metrics")
async def get_stable_vendor_dashboard_metrics():
    """Get headline KPIs for the stable vendor dashboard widget."""
    svc = get_stable_vendor_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Stable vendor service not initialized")
    return await svc.get_dashboard_metrics()


@router.post("/reevaluate-all")
async def reevaluate_all_vendors(background_tasks: BackgroundTasks):
    """
    Reevaluate all vendors for stability status.
    Runs in the background to avoid blocking.
    """
    svc = get_stable_vendor_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Stable vendor service not initialized")

    async def _run():
        try:
            result = await svc.reevaluate_all_vendors()
            logger.info("[StableVendor] Reevaluation complete: %s", result)
        except Exception as e:
            logger.error("[StableVendor] Reevaluation failed: %s", e)

    background_tasks.add_task(_run)
    return {"status": "accepted", "message": "Vendor reevaluation started in background"}
