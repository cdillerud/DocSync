"""
Canonical application lifecycle scheduler coroutines.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Optional


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


async def knowledge_seed_scheduler(
    *,
    db,
    logger,
) -> None:
    """Background worker: keep knowledge base fresh after BC cache changes."""
    await asyncio.sleep(30)  # Let BC cache and other services initialize first
    while True:
        try:
            from services.knowledge_seed_service import run_full_knowledge_seed
            logger.info("[KnowledgeSeed] Starting scheduled knowledge seed")
            result = await run_full_knowledge_seed(db)
            aliases = result.get("vendor_aliases", {}).get("total_aliases", 0)
            profiles = result.get("vendor_profiles", {}).get("total_profiles", 0)
            domains = result.get("sender_domains", {}).get("total_sender_mappings", 0)
            logger.info("[KnowledgeSeed] Scheduled seed complete: aliases=%s, profiles=%s, domains=%s", aliases, profiles, domains)
        except Exception as e:
            logger.warning("[KnowledgeSeed] Scheduled seed failed: %s", e)
        await asyncio.sleep(6 * 3600)  # Every 6 hours


async def intake_pattern_hygiene_scheduler(
    *,
    logger,
) -> None:
    await asyncio.sleep(600)  # Let refresh scheduler run first
    while True:
        try:
            from workflows.core.learning_core import run_hygiene
            result = await run_hygiene(domain="all", actor="scheduler")
            logger.info(
                "[PatternHygiene.scheduler] done — scanned=%d retired=%d promoted=%d",
                result.get("total_scanned", 0),
                result.get("total_retired", 0),
                result.get("total_promoted", 0),
            )
        except Exception as e:
            logger.warning("[PatternHygiene.scheduler] failed: %s", e)
        await asyncio.sleep(24 * 3600)


async def drift_alert_scheduler(
    *,
    logger,
) -> None:
    await asyncio.sleep(900)  # 15-min startup delay so other schedulers settle
    while True:
        try:
            from services.drift_alert_service import run_drift_scan
            result = await run_drift_scan(actor="scheduler")
            logger.info(
                "[DriftAlerts.scheduler] done — fired=%d open_total=%d",
                result.get("rules_fired", 0),
                result.get("open_alerts_total", 0),
            )
        except Exception as e:
            logger.warning("[DriftAlerts.scheduler] failed: %s", e)
        await asyncio.sleep(24 * 3600)


async def weekly_digest_scheduler(
    *,
    logger,
) -> None:
    await asyncio.sleep(1200)  # 20-min startup delay
    while True:
        try:
            from workflows.core.learning_core import build_weekly_digest
            d = await build_weekly_digest(actor="scheduler")
            logger.info(
                "[WeeklyDigest.scheduler] built %s — events=%d reviewers=%d drift=%d",
                d.get("week_key"),
                d.get("events", {}).get("total", 0),
                len(d.get("top_reviewers", [])),
                d.get("drift_summary", {}).get("total_new", 0),
            )
        except Exception as e:
            logger.warning("[WeeklyDigest.scheduler] failed: %s", e)
        await asyncio.sleep(24 * 3600)


async def intake_learning_refresh_scheduler(
    *,
    logger,
) -> None:
    import os as _os
    lookback = int(_os.environ.get("INTAKE_LEARNING_LOOKBACK_HOURS", "24"))
    interval = int(_os.environ.get("INTAKE_LEARNING_INTERVAL_SECONDS", str(24 * 3600)))
    await asyncio.sleep(300)  # Wait 5 min after startup so BC cache + catalog sync settle first
    while True:
        try:
            from services.sales_intake_learning_service import refresh_active_customers
            logger.info("[IntakeLearning.scheduler] Starting daily refresh (lookback=%dh)", lookback)
            result = await refresh_active_customers(lookback_hours=lookback)
            logger.info(
                "[IntakeLearning.scheduler] done — customers=%d docs=%d xls=%d",
                result.get("active_customers", 0),
                result.get("docs_refreshed", 0),
                result.get("xls_refreshed", 0),
            )
        except Exception as e:
            logger.warning("[IntakeLearning.scheduler] failed: %s", e)
        await asyncio.sleep(interval)


async def drift_watchlist_scheduler(
    *,
    logger,
) -> None:
    await asyncio.sleep(1500)  # 25-min startup delay
    target_dow = int(os.environ.get("DRIFT_WATCHLIST_CRON_DOW", "0"))  # 0 = Mon
    target_hour = int(os.environ.get("DRIFT_WATCHLIST_CRON_HOUR", "7"))
    enabled = os.environ.get("DRIFT_WATCHLIST_ENABLED", "false").lower() in ("1", "true", "yes")
    if not enabled:
        logger.info("Drift Watchlist scheduler disabled (set DRIFT_WATCHLIST_ENABLED=true to enable)")
        return
    last_sent_day: Optional[str] = None
    while True:
        try:
            now = datetime.now()
            day_key = now.strftime("%Y-%m-%d")
            if (
                now.weekday() == target_dow
                and now.hour == target_hour
                and last_sent_day != day_key
            ):
                from workflows.core.learning_core.drift_watchlist_service import send_watchlist
                result = await send_watchlist(actor="scheduler")
                last_sent_day = day_key
                logger.info(
                    "[DriftWatchlist.scheduler] dispatched: vendors=%d channels=%s",
                    result.get("vendor_count", 0),
                    list(result.get("per_channel", {})),
                )
        except Exception as e:
            logger.warning("[DriftWatchlist.scheduler] tick failed: %s", e)
        # Wake every hour so we don't drift past the target window
        await asyncio.sleep(3600)


async def startup_clean_noise_learning_events(
    *,
    db,
    logger,
) -> None:
    """One-time cleanup: move readiness self-correction events out of posting_learning_events."""
    await asyncio.sleep(45)
    try:
        noise_count = await db.posting_learning_events.count_documents({
            "event_type": {"$in": ["readiness_contradiction_fix", "readiness_self_correction"]}
        })
        if noise_count > 0:
            result = await db.posting_learning_events.delete_many({
                "event_type": {"$in": ["readiness_contradiction_fix", "readiness_self_correction"]}
            })
            logger.info("[Startup] Cleaned %d noise events from posting_learning_events (readiness self-corrections)", result.deleted_count)
        # Also clean events with blank vendor_no and no amount data
        blank_count = await db.posting_learning_events.count_documents({
            "vendor_no": {"$in": [None, ""]},
            "$or": [
                {"amount": {"$exists": False}},
                {"amount": 0},
                {"amount": None},
            ],
        })
        if blank_count > 0:
            result2 = await db.posting_learning_events.delete_many({
                "vendor_no": {"$in": [None, ""]},
                "$or": [
                    {"amount": {"$exists": False}},
                    {"amount": 0},
                    {"amount": None},
                ],
            })
            logger.info("[Startup] Cleaned %d blank-vendor/zero-amount noise events from posting_learning_events", result2.deleted_count)
        # Clean events with known vendor but $0 amount AND no line data (ghost events)
        ghost_count = await db.posting_learning_events.count_documents({
            "$and": [
                {"$or": [{"amount": 0}, {"amount": None}, {"amount": {"$exists": False}}]},
                {"$or": [{"line_count": 0}, {"line_count": None}, {"line_count": {"$exists": False}}]},
                {"$or": [
                    {"items_used": {"$exists": False}},
                    {"items_used": None},
                    {"items_used": {"$size": 0}},
                    {"items_used": []},
                ]},
            ],
        })
        if ghost_count > 0:
            result3 = await db.posting_learning_events.delete_many({
                "$and": [
                    {"$or": [{"amount": 0}, {"amount": None}, {"amount": {"$exists": False}}]},
                    {"$or": [{"line_count": 0}, {"line_count": None}, {"line_count": {"$exists": False}}]},
                    {"$or": [
                        {"items_used": {"$exists": False}},
                        {"items_used": None},
                        {"items_used": {"$size": 0}},
                        {"items_used": []},
                    ]},
                ],
            })
            logger.info("[Startup] Cleaned %d ghost learning events ($0/no-lines/no-items)", result3.deleted_count)
    except Exception as e:
        logger.warning("[Startup] Noise event cleanup failed: %s", e)


async def startup_fix_shipping_po_escalations(
    *,
    db,
    logger,
) -> None:
    await asyncio.sleep(12)
    try:
        NON_PO_TYPES = [
            "Shipping_Document", "Shipping Document", "Packing_Slip", "Packing_List",
            "BOL", "Bill_of_Lading", "Bill of Lading", "Warehouse_Receipt",
            "STATEMENT", "Statement", "Account_Statement", "Remittance",
        ]
        # Un-park non-AP docs that were incorrectly parked by PO retry
        r1 = await db.hub_documents.update_many(
            {
                "po_pending_parked": True,
                "$or": [
                    {"doc_type": {"$in": NON_PO_TYPES}},
                    {"document_type": {"$in": NON_PO_TYPES}},
                ],
            },
            {"$set": {"po_pending_parked": False}, "$unset": {"escalation_reason": ""}},
        )
        # Fix shipping docs incorrectly escalated to Exception/Manual Review
        r2 = await db.hub_documents.update_many(
            {
                "$or": [
                    {"doc_type": {"$in": NON_PO_TYPES}},
                    {"document_type": {"$in": NON_PO_TYPES}},
                ],
                "escalation_reason": {"$regex": "PO not found", "$options": "i"},
            },
            {
                "$set": {"po_pending_parked": False},
                "$unset": {"escalation_reason": "", "auto_escalated": ""},
            },
        )
        if r1.modified_count or r2.modified_count:
            logger.info("[Startup] Fixed %d incorrectly PO-parked + %d incorrectly escalated non-AP docs",
                        r1.modified_count, r2.modified_count)
    except Exception as e:
        logger.warning("[Startup] Shipping PO-escalation fix failed: %s", e)


async def startup_backfill_pi_no(
    *,
    db,
    logger,
) -> None:
    await asyncio.sleep(15)
    try:
        # Find docs that have bc_purchase_invoice.bc_record_no but missing bc_purchase_invoice_no
        cursor = db.hub_documents.find(
            {
                "bc_purchase_invoice.bc_record_no": {"$exists": True, "$nin": [None, ""]},
                "$or": [
                    {"bc_purchase_invoice_no": {"$exists": False}},
                    {"bc_purchase_invoice_no": None},
                    {"bc_purchase_invoice_no": ""},
                ],
            },
            {"_id": 0, "id": 1, "bc_purchase_invoice.bc_record_no": 1},
        )
        backfilled = 0
        async for doc in cursor:
            pi_no = (doc.get("bc_purchase_invoice") or {}).get("bc_record_no", "")
            if pi_no:
                await db.hub_documents.update_one(
                    {"id": doc["id"]},
                    {"$set": {"bc_purchase_invoice_no": pi_no}},
                )
                backfilled += 1
        if backfilled > 0:
            logger.info("[Startup] Backfilled bc_purchase_invoice_no on %d documents", backfilled)
    except Exception as e:
        logger.warning("[Startup] PI no backfill failed: %s", e)


async def deep_learning_scheduler(
    *,
    db,
    logger,
) -> None:
    await asyncio.sleep(300)  # Initial delay: 5 minutes
    while True:
        try:
            logger.info("[DeepLearning] Running scheduled self-correction audit + vendor maturity...")
            from services.deep_learning_engine import run_self_correction_audit, compute_all_vendor_maturity
            audit = await run_self_correction_audit(db, sample_size=100)
            logger.info("[DeepLearning] Self-correction: %d audited, %d drifts (%.1f%%)",
                        audit.get("audited", 0), audit.get("drifts", 0), audit.get("drift_rate", 0) * 100)
            maturity = await compute_all_vendor_maturity(db)
            logger.info("[DeepLearning] Vendor maturity: %d vendors scored, levels=%s",
                        maturity.get("computed", 0), maturity.get("levels", {}))
        except Exception as e:
            logger.warning("[DeepLearning] Scheduled deep learning failed: %s", e)
        await asyncio.sleep(4 * 3600)  # Every 4 hours
