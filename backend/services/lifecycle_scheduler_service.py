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
