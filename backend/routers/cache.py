"""GPI Document Hub - Cache / BC Reference Cache Router"""

import asyncio
import logging
from fastapi import APIRouter, HTTPException, Query
from services.bc_reference_cache_service import get_cache_service
from services.bc_write_safety_guard import get_write_guard

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Cache & BC"])


@router.get("/bc/write-guard/status")
async def get_bc_write_guard_status():
    guard = get_write_guard()
    return guard.get_status()


@router.post("/bc/write-guard/check")
async def check_bc_write_permission(
    document_id: str = Query(...),
    action: str = Query(...)
):
    guard = get_write_guard()
    result = await guard.check_write_permission(document_id, action)
    return result.to_dict()


@router.get("/cache/status")
async def get_cache_status():
    cache = get_cache_service()
    if not cache:
        raise HTTPException(status_code=503, detail="Cache service not initialized")
    return await cache.get_status()


@router.post("/cache/sync")
async def trigger_cache_sync(
    mode: str = Query(default="incremental", description="'bulk' or 'incremental'")
):
    cache = get_cache_service()
    if not cache:
        raise HTTPException(status_code=503, detail="Cache service not initialized")
    incremental = mode != "bulk"

    async def _run_sync():
        try:
            await cache.sync_all(incremental=incremental)
        except Exception as e:
            logger.error("[Cache Sync] Background sync error: %s", str(e))

    asyncio.create_task(_run_sync())
    return {
        "status": "sync_started",
        "mode": mode,
        "message": f"{'Incremental' if incremental else 'Bulk'} cache sync started in background. Check /api/cache/status for progress."
    }


@router.get("/cache/search")
async def search_cache(
    reference: str = Query(..., description="Reference number to search"),
    entity_type: str = Query(default=None, description="Filter by entity type")
):
    cache = get_cache_service()
    if not cache:
        raise HTTPException(status_code=503, detail="Cache service not initialized")
    entity_types = [entity_type] if entity_type else None
    results = await cache.search_multi(reference, entity_types=entity_types)
    return {
        "reference": reference,
        "match_count": len(results),
        "matches": results
    }


@router.get("/auto-resolve/stats")
async def get_auto_resolve_stats():
    from services.auto_resolution_service import get_auto_resolve_service
    svc = get_auto_resolve_service()
    if not svc:
        return {"status": "not_initialized"}
    return svc.get_stats()


@router.get("/cache/metrics")
async def get_cache_metrics():
    """Get BC reference cache metrics: hit/miss rates by entity type, last sync, record counts."""
    from deps import get_db
    db = get_db()
    cache_svc = get_cache_service()
    if not cache_svc:
        raise HTTPException(status_code=503, detail="Cache service not initialized")
    status = await cache_svc.get_status()
    pipeline = [
        {"$group": {"_id": "$bc_entity_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    by_type = await db.bc_reference_cache.aggregate(pipeline).to_list(20)
    total_resolutions = await db.matching_diagnostics.count_documents({})
    cache_hit_count = await db.matching_diagnostics.count_documents({"cache_results": {"$ne": []}})
    bc_fallback_count = await db.matching_diagnostics.count_documents({"bc_fallback_results": {"$ne": []}})
    return {
        "cache_status": status,
        "records_by_entity_type": [{"entity_type": r["_id"], "count": r["count"]} for r in by_type],
        "total_records": sum(r["count"] for r in by_type),
        "resolution_metrics": {
            "total_resolutions": total_resolutions,
            "cache_hit_count": cache_hit_count,
            "bc_fallback_count": bc_fallback_count,
            "cache_hit_rate": round(cache_hit_count / max(total_resolutions, 1), 3),
        },
    }
