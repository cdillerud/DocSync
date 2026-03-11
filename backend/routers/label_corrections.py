"""GPI Document Hub - Label Corrections Router"""

from fastapi import APIRouter, HTTPException
from services.label_correction_service import get_label_correction_service

router = APIRouter(prefix="/label-corrections", tags=["Label Corrections"])


@router.get("/stats")
async def get_label_correction_stats():
    svc = get_label_correction_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Label correction service not initialized")
    return await svc.get_stats()


@router.get("/summary")
async def get_label_correction_summary():
    """Full dashboard summary with accuracy rate and time-based metrics."""
    svc = get_label_correction_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Label correction service not initialized")
    return await svc.get_summary()


@router.get("/top-patterns")
async def get_label_correction_top_patterns():
    """Top mislabel patterns with vendor breakdown and examples."""
    svc = get_label_correction_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Label correction service not initialized")
    return await svc.get_top_patterns()


@router.get("/vendors")
async def get_all_vendor_corrections():
    """Aggregated correction data per vendor for the vendor table."""
    svc = get_label_correction_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Label correction service not initialized")
    return await svc.get_all_vendor_corrections()


@router.get("/over-time")
async def get_corrections_over_time():
    """Corrections grouped by day for time series chart."""
    svc = get_label_correction_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Label correction service not initialized")
    return await svc.get_corrections_over_time()


@router.get("/recommendations")
async def get_label_correction_recommendations():
    """Automated recommendations and extraction adjustment suggestions."""
    svc = get_label_correction_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Label correction service not initialized")
    return await svc.get_recommendations()


@router.get("/recent")
async def get_recent_corrections(limit: int = 20):
    svc = get_label_correction_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Label correction service not initialized")
    return await svc.get_recent_corrections(limit=min(limit, 100))


@router.get("/vendor/{vendor_id}")
async def get_vendor_correction_patterns(vendor_id: str):
    """Extended vendor insights with correction rate and frequency breakdowns."""
    svc = get_label_correction_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Label correction service not initialized")
    return await svc.get_vendor_insights(vendor_id)


@router.get("/document/{doc_id}")
async def get_document_corrections(doc_id: str):
    svc = get_label_correction_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Label correction service not initialized")
    return await svc.get_corrections_for_document(doc_id)
