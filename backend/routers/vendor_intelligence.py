"""GPI Document Hub - Vendor Intelligence Router"""

import asyncio
import logging
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
