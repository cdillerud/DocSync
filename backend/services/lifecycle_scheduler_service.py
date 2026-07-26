"""
Canonical application lifecycle scheduler coroutines.
"""

from __future__ import annotations

import asyncio


async def startup_sync_status(
    *,
    logger,
) -> None:
    """Run lightweight inbox cleanup 30s after startup to file any ready docs."""
    await asyncio.sleep(30)
    try:
        from routers.readiness import sync_readiness_to_status
        result = await sync_readiness_to_status()
        total = result.get("total_fixed", 0)
        if total > 0:
            logger.info("[Startup] Sync-status auto-filed %d docs that were ready but sitting in inbox", total)
        else:
            logger.info("[Startup] Sync-status check: inbox is clean, no docs to auto-file")
    except Exception as e:
        logger.warning("[Startup] Sync-status auto-run failed: %s", e)


async def periodic_sync_status(
    *,
    logger,
) -> None:
    """Periodically sync readiness→status to catch any docs that fall through cracks."""
    await asyncio.sleep(120)  # Initial delay: 2 minutes after startup sync
    while True:
        try:
            from routers.readiness import sync_readiness_to_status
            result = await sync_readiness_to_status()
            total = result.get("total_fixed", 0)
            if total > 0:
                logger.info("[PeriodicSync] Sync-status auto-filed %d docs", total)
        except Exception as e:
            logger.warning("[PeriodicSync] Sync-status failed: %s", e)
        await asyncio.sleep(30 * 60)  # Every 30 minutes


async def startup_requeue_not_run(
    *,
    db,
    logger,
    get_auto_resolve_service,
) -> None:
    """Scan for docs with ref intel = not_run and enqueue them."""
    await asyncio.sleep(10)  # Let all services finish initializing
    svc = get_auto_resolve_service()
    if not svc:
        return
    query = {"reference_intelligence_status": {"$in": [None, "not_run"]}}
    not_run_docs = await db.hub_documents.find(
        query, {"id": 1, "_id": 0}
    ).limit(500).to_list(500)
    if not_run_docs:
        for doc in not_run_docs:
            await svc.enqueue(doc["id"])
        logger.info(
            "[Startup] Re-queued %d documents with not_run ref intel status",
            len(not_run_docs),
        )
    else:
        logger.info("[Startup] No not_run documents to re-queue")


async def catalog_sync_scheduler(
    *,
    db,
    logger,
) -> None:
    """Background worker: sync BC item catalog and GL accounts every 24 hours."""
    await asyncio.sleep(60)  # Initial delay — let other services start first
    while True:
        try:
            from services.bc_catalog_sync_service import sync_all
            logger.info("[CatalogSync] Starting scheduled BC catalog sync")
            result = await sync_all(db)
            logger.info("[CatalogSync] Completed: %s", result)
        except Exception as e:
            logger.warning("[CatalogSync] Scheduled sync failed: %s", e)
        await asyncio.sleep(24 * 3600)  # Sleep 24 hours


async def shipment_sync_scheduler(
    *,
    db,
    logger,
) -> None:
    """Background worker: sync BC shipment lines into inventory every 1 hour."""
    await asyncio.sleep(120)  # Initial delay
    while True:
        try:
            from services.inventory_so_integration import sync_bc_shipments
            logger.info("[ShipmentSync] Starting scheduled BC shipment sync")
            result = await sync_bc_shipments(db, lookback_hours=24)
            logger.info("[ShipmentSync] Completed: %s", result)
        except Exception as e:
            logger.warning("[ShipmentSync] Scheduled sync failed: %s", e)
        await asyncio.sleep(3600)  # 1 hour


async def daily_trace_scheduler(
    *,
    logger,
) -> None:
    """Background worker: run random invoice traces once per day."""
    await asyncio.sleep(120)  # Wait 2 min after startup
    while True:
        try:
            from routers.posting_patterns import _run_daily_traces
            result = await _run_daily_traces()
            logger.info("[DailyTrace] Scheduler complete: %s/%s success, avg match=%s%%",
                        result.get("traces_success", 0), result.get("traces_requested", 0),
                        result.get("avg_match_rate", 0))
        except Exception as e:
            logger.warning("[DailyTrace] Scheduler failed: %s", e)
        await asyncio.sleep(24 * 3600)  # Every 24 hours
