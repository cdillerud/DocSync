"""
Canonical application lifecycle cleanup service.

Startup remains in server.py while its larger initialization and scheduler
responsibilities are extracted incrementally.
"""

from __future__ import annotations

import asyncio


async def _cancel_task(
    task,
    stopped_message: str,
    logger,
) -> None:
    """Cancel and await one optional background task."""
    if task is None or task.done():
        return

    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        logger.info(stopped_message)


async def shutdown_application(
    *,
    dynamic_mailbox_task,
    email_polling_task,
    sales_polling_task,
    pilot_summary_task,
    get_cache_service,
    get_auto_resolve_service,
    client,
    logger,
) -> None:
    """Stop owned workers and close shared application resources once."""
    await _cancel_task(
        dynamic_mailbox_task,
        "Dynamic mailbox polling worker stopped",
        logger,
    )

    await _cancel_task(
        email_polling_task,
        "AP email polling worker stopped",
        logger,
    )

    await _cancel_task(
        sales_polling_task,
        "Sales email polling worker stopped",
        logger,
    )

    await _cancel_task(
        pilot_summary_task,
        "Pilot summary scheduler stopped",
        logger,
    )

    cache = get_cache_service()

    if cache:
        cache.stop_background_sync()

    auto_resolve = get_auto_resolve_service()

    if auto_resolve:
        auto_resolve.stop()

    client.close()
