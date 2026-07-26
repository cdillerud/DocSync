"""
Canonical application lifecycle cleanup service.

Startup remains in server.py while its larger initialization and scheduler
responsibilities are extracted incrementally.
"""

from __future__ import annotations

import asyncio


_BACKGROUND_TASKS: set[asyncio.Task] = set()


def register_background_task(
    task: asyncio.Task,
    *,
    name: str,
) -> asyncio.Task:
    """Register one application-owned background task."""
    task.set_name(name)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(
        _BACKGROUND_TASKS.discard
    )

    return task


async def cancel_registered_tasks(
    logger,
) -> None:
    """Cancel and await every active registered task."""
    tasks = [
        task
        for task in tuple(
            _BACKGROUND_TASKS
        )
        if not task.done()
    ]

    for task in tasks:
        task.cancel()

    if tasks:
        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        logger.info(
            "Stopped %d registered "
            "background tasks",
            len(tasks),
        )

    _BACKGROUND_TASKS.clear()


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
    get_alert_pattern_service,
    get_vep_service,
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

    await cancel_registered_tasks(
        logger
    )

    alert_pattern = (
        get_alert_pattern_service()
    )

    if alert_pattern:
        alert_pattern.stop_background_eval()

    vep = get_vep_service()

    if vep:
        vep.stop_background_learning()

    cache = get_cache_service()

    if cache:
        cache.stop_background_sync()

    auto_resolve = (
        get_auto_resolve_service()
    )

    if auto_resolve:
        auto_resolve.stop()

    client.close()
