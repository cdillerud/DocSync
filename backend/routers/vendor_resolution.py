"""
GPI Document Hub - Vendor Resolution Router

Endpoints:
  GET /api/vendor-resolution/metrics    - Resolution analytics
  GET /api/vendor-resolution/rejections - Admin review of rejected auto-matches
"""

from fastapi import APIRouter, Query

router = APIRouter(prefix="/vendor-resolution", tags=["Vendor Resolution"])


@router.get("/metrics")
async def get_vendor_resolution_metrics():
    """Get vendor resolution analytics: rates, method breakdown, score buckets, top unresolved."""
    from services.vendor_resolution_service import get_resolution_metrics
    return await get_resolution_metrics()


@router.get("/rejections")
async def get_vendor_match_rejections(
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    """Get vendor match rejection history for admin review."""
    from services.vendor_resolution_service import get_rejections
    rejections = await get_rejections(limit=limit, skip=skip)
    return {"rejections": rejections, "count": len(rejections)}
