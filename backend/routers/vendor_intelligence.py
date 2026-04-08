"""GPI Document Hub - Vendor Intelligence Router"""

import asyncio
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from services.vendor_intelligence_service import get_vendor_intelligence_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vendor-intelligence", tags=["Vendor Intelligence"])


@router.get("/stats")
async def get_vendor_intelligence_stats():
    svc = get_vendor_intelligence_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Vendor Intelligence not initialized")
    return await svc.get_stats()


@router.get("/profiles")
async def list_vendor_profiles(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    sort_by: str = Query("invoice_count", description="Sort field")
):
    svc = get_vendor_intelligence_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Vendor Intelligence not initialized")
    profiles = await svc.get_all_profiles(skip=skip, limit=limit, sort_by=sort_by)
    total = await svc.get_profile_count()
    return {"profiles": profiles, "total": total}


@router.get("/profiles/{vendor_id}")
async def get_vendor_profile(vendor_id: str):
    svc = get_vendor_intelligence_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Vendor Intelligence not initialized")
    profile = await svc.get_profile(vendor_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Vendor profile not found")
    return profile


@router.post("/rebuild")
async def rebuild_vendor_profiles():
    svc = get_vendor_intelligence_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Vendor Intelligence not initialized")

    async def _run_rebuild():
        try:
            await svc.rebuild_all_profiles()
        except Exception as e:
            logger.error("[VendorIntel] Rebuild error: %s", str(e))

    asyncio.create_task(_run_rebuild())
    return {"status": "rebuild_started", "message": "Vendor profiles are being rebuilt from historical data."}


@router.get("/resolver-hints/{vendor_name}")
async def get_vendor_resolver_hints(vendor_name: str):
    svc = get_vendor_intelligence_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Vendor Intelligence not initialized")
    return await svc.get_resolver_hints(vendor_name)



@router.patch("/profiles/{vendor_no}/bypass")
async def set_vendor_processing_bypass(vendor_no: str, enabled: bool = True, reason: str = ""):
    """Flag a vendor for auto-processing bypass.
    
    When enabled, documents from this vendor will be routed to manual review
    instead of attempting auto-processing. Useful for vendors with consistently
    poor extraction quality (e.g., NOFACH).
    """
    from deps import get_db
    db = get_db()
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Update vendor_invoice_profiles
    result = await db.vendor_invoice_profiles.update_one(
        {"vendor_no": vendor_no},
        {"$set": {
            "auto_process_bypass": enabled,
            "bypass_reason": reason or ("Vendor flagged for manual review" if enabled else ""),
            "bypass_updated_at": now,
        }},
        upsert=False,
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"Vendor profile not found: {vendor_no}")
    
    return {
        "vendor_no": vendor_no,
        "auto_process_bypass": enabled,
        "reason": reason,
        "updated_at": now,
    }


@router.get("/bypassed-vendors")
async def get_bypassed_vendors():
    """List all vendors currently flagged for processing bypass."""
    from deps import get_db
    db = get_db()
    
    vendors = await db.vendor_invoice_profiles.find(
        {"auto_process_bypass": True},
        {"_id": 0, "vendor_no": 1, "vendor_name": 1, "bypass_reason": 1,
         "bypass_updated_at": 1, "invoice_count": 1},
    ).to_list(100)
    
    return {"bypassed_vendors": vendors, "count": len(vendors)}