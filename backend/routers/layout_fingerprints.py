"""GPI Document Hub - Layout Fingerprints Router"""

from fastapi import APIRouter, HTTPException
from services.layout_fingerprint_service import get_layout_fingerprint_service

router = APIRouter(prefix="/layout-fingerprints", tags=["Layout Fingerprints"])


@router.get("/stats")
async def get_layout_fingerprint_stats():
    svc = get_layout_fingerprint_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Layout Fingerprint service not initialized")
    return await svc.get_family_stats()


@router.get("/families")
async def get_layout_families(
    vendor_no: str = None,
    doc_type: str = None,
    status: str = "active",
    skip: int = 0,
    limit: int = 100
):
    svc = get_layout_fingerprint_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Layout Fingerprint service not initialized")
    families = await svc.get_all_families(vendor_no=vendor_no, doc_type=doc_type, status=status, skip=skip, limit=limit)
    return {"families": families, "total": len(families)}


@router.get("/families/{family_id}")
async def get_layout_family_detail(family_id: str):
    svc = get_layout_fingerprint_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Layout Fingerprint service not initialized")
    family = await svc.get_family_detail(family_id)
    if not family:
        raise HTTPException(status_code=404, detail="Layout family not found")
    return family


@router.get("/vendor/{vendor_no}")
async def get_layout_families_by_vendor(vendor_no: str):
    svc = get_layout_fingerprint_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Layout Fingerprint service not initialized")
    families = await svc.get_families_by_vendor(vendor_no)
    return {"vendor_no": vendor_no, "families": families, "total": len(families)}


@router.get("/document/{doc_id}")
async def get_document_fingerprint(doc_id: str):
    svc = get_layout_fingerprint_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Layout Fingerprint service not initialized")
    fp = await svc.get_fingerprint_for_document(doc_id)
    if not fp:
        return {"document_id": doc_id, "has_fingerprint": False}
    return {**fp, "has_fingerprint": True}


@router.post("/backfill")
async def backfill_layout_fingerprints(limit: int = 100):
    svc = get_layout_fingerprint_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Layout Fingerprint service not initialized")
    return await svc.backfill_fingerprints(limit=limit)


@router.get("/alerts")
async def get_layout_family_alerts():
    svc = get_layout_fingerprint_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Layout Fingerprint service not initialized")
    alerts = await svc.get_families_needing_attention()
    return {"alerts": alerts, "total": len(alerts)}
