"""GPI Document Hub - Vendor Extraction Profiles Router"""

from fastapi import APIRouter, HTTPException
from services.vendor_extraction_profile_service import get_vep_service

router = APIRouter(prefix="/vendor-extraction-profiles", tags=["Vendor Extraction Profiles"])


@router.get("")
async def get_all_extraction_profiles():
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")
    return await svc.get_all_profiles()


@router.get("/stats")
async def get_extraction_profile_stats():
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")
    return await svc.get_profile_stats()


@router.get("/{vendor_id}")
async def get_vendor_extraction_profile(vendor_id: str):
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")
    profile = await svc.get_profile(vendor_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.post("/{vendor_id}/generate")
async def generate_vendor_profile(vendor_id: str):
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")
    profile = await svc.generate_profile(vendor_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Insufficient data to generate profile")
    return profile


@router.post("/generate-all")
async def generate_all_profiles():
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")
    return await svc.generate_all_profiles()


@router.post("/{vendor_id}/toggle")
async def toggle_vendor_profile(vendor_id: str, enabled: bool = True):
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")
    ok = await svc.toggle_profile(vendor_id, enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"vendor_id": vendor_id, "enabled": enabled}


@router.post("/{vendor_id}/reset")
async def reset_vendor_profile(vendor_id: str):
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")
    ok = await svc.reset_profile(vendor_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"vendor_id": vendor_id, "status": "reset"}
