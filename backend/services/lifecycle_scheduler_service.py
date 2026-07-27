"""
Canonical application lifecycle scheduler coroutines.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
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


async def draft_feedback_sync_scheduler(
    *,
    db,
    logger,
) -> None:
    """Background worker: sync auto-drafted PIs from BC, detect human edits, run all learning engines, auto-approve qualifying drafts."""
    await asyncio.sleep(300)  # 5 min delay — let all services start
    while True:
        try:
            from services.draft_feedback_service import process_feedback_batch
            logger.info("[DraftFeedback] Starting scheduled BC draft sync")
            result = await process_feedback_batch(db, limit=100)
            logger.info(
                "[DraftFeedback] Sync complete: processed=%d, changes=%d, no_changes=%d, errors=%d",
                result.get("processed", 0), result.get("changes_found", 0),
                result.get("no_changes", 0), result.get("errors", 0),
            )
        except Exception as e:
            logger.warning("[DraftFeedback] Scheduled sync failed: %s", e)

        # Run all continuous learning engines
        try:
            from services.continuous_learning_service import run_all_learning_engines
            logger.info("[ContinuousLearning] Starting scheduled learning engines")
            learn_result = await run_all_learning_engines(db)
            posted = learn_result.get("posted_draft_detection", {})
            cross = learn_result.get("cross_vendor_learning", {})
            promo = learn_result.get("confidence_auto_promotion", {})
            logger.info(
                "[ContinuousLearning] Complete: posted_found=%s, cross_vendor=%s, promoted=%s, demoted=%s",
                posted.get("posted_found", 0), cross.get("propagated_to_vendors", 0),
                len(promo.get("promoted", [])), len(promo.get("demoted", [])),
            )
        except Exception as e:
            logger.warning("[ContinuousLearning] Scheduled learning failed: %s", e)

        # Auto-approve qualifying drafts (high-confidence vendors with proven templates)
        try:
            from routers.posting_patterns import auto_approve_drafts
            logger.info("[DraftAutoApprove] Running scheduled auto-approve for pending drafts")
            approve_result = await auto_approve_drafts(
                min_vendor_invoices=5, min_confidence="medium", dry_run=False, limit=500
            )
            approved_count = approve_result.get("approved", 0)
            skipped_count = approve_result.get("skipped", 0)
            if approved_count > 0:
                logger.info("[DraftAutoApprove] Auto-approved %d drafts, skipped %d", approved_count, skipped_count)
            else:
                logger.debug("[DraftAutoApprove] No drafts to auto-approve (skipped=%d)", skipped_count)
        except Exception as e:
            logger.warning("[DraftAutoApprove] Scheduled auto-approve failed: %s", e)

        # 4. Backfill vendor learning from approved drafts that have BC data but $0 amounts
        try:
            from services.posting_pattern_analyzer import learn_from_posting
            # Find approved docs with bc_purchase_invoice but no learning amount
            zero_amount_docs = await db.hub_documents.find(
                {
                    "auto_draft_created": True,
                    "draft_review_status": "approved",
                    "bc_purchase_invoice": {"$exists": True},
                    "amount_learning_backfilled": {"$ne": True},
                },
                {"_id": 0, "id": 1, "bc_vendor_number": 1, "vendor_no": 1,
                 "vendor_canonical": 1, "doc_type": 1, "extracted_fields": 1,
                 "normalized_fields": 1, "bc_purchase_invoice": 1},
            ).limit(50).to_list(50)

            backfilled = 0
            for zdoc in zero_amount_docs:
                doc_id = zdoc.get("id", "")
                vendor_no = zdoc.get("bc_vendor_number") or zdoc.get("vendor_no") or ""
                if not doc_id or not vendor_no:
                    continue
                try:
                    pi_data = zdoc.get("bc_purchase_invoice") or {}
                    pi_lines = pi_data.get("lines") or pi_data.get("purchaseInvoiceLines") or []
                    # Build simple line objects for learning
                    clean_lines = []
                    for pl in pi_lines:
                        line = {
                            "No_": pl.get("no") or pl.get("No_") or pl.get("lineObjectNumber") or "",
                            "Description": pl.get("description") or pl.get("Description") or "",
                            "Quantity": pl.get("quantity") or pl.get("Quantity") or 1,
                            "Direct_Unit_Cost": pl.get("directUnitCost") or pl.get("Direct_Unit_Cost") or pl.get("unitCost") or 0,
                            "Amount": pl.get("amountIncludingVAT") or pl.get("Amount") or pl.get("lineAmount") or 0,
                        }
                        clean_lines.append(line)

                    if clean_lines:
                        await learn_from_posting(
                            db, doc_id, vendor_no, clean_lines,
                            result_status="Posted",
                            source="bc_sync_backfill"
                        )
                        await db.hub_documents.update_one(
                            {"id": doc_id},
                            {"$set": {"amount_learning_backfilled": True}},
                        )
                        backfilled += 1
                except Exception as le:
                    logger.debug("[VendorLearnBackfill] Error for %s: %s", doc_id[:8], le)

            if backfilled > 0:
                logger.info("[VendorLearnBackfill] Backfilled learning data for %d docs", backfilled)
        except Exception as e:
            logger.warning("[VendorLearnBackfill] Scheduled backfill failed: %s", e)

        await asyncio.sleep(2 * 3600)  # Every 2 hours


async def intelligence_maintenance_scheduler(
    *,
    db,
    logger,
) -> None:
    await asyncio.sleep(180)  # Initial delay: 3 minutes
    while True:
        # 1. Auto-clear safe duplicate flags
        try:
            from services.duplicate_intelligence_service import batch_auto_clear_safe_duplicates
            logger.info("[IntelMaint] Running duplicate intelligence batch-clear...")
            dup_result = await batch_auto_clear_safe_duplicates(db, limit=200)
            logger.info("[IntelMaint] Duplicate clear: %d cleared, %d safe vendors",
                        dup_result.get("cleared", 0), dup_result.get("safe_vendors", 0))
        except Exception as e:
            logger.warning("[IntelMaint] Duplicate clear failed: %s", e)

        # 2. Backfill escalation intelligence from recent outcomes
        try:
            from services.escalation_intelligence_service import record_automation_outcome
            # Find recently completed/posted docs that haven't been tracked
            recent_docs = await db.hub_documents.find(
                {
                    "status": {"$in": ["Completed", "Posted", "Auto-Draft", "Linked", "Filed", "Needs Review", "Review", "Rejected"]},
                    "escalation_tracked": {"$ne": True},
                },
                {"_id": 0, "id": 1, "bc_vendor_number": 1, "vendor_no": 1, "matched_vendor_no": 1,
                 "document_type": 1, "suggested_job_type": 1, "status": 1}
            ).limit(200).to_list(200)

            tracked = 0
            for d in recent_docs:
                vendor = d.get("bc_vendor_number") or d.get("vendor_no") or d.get("matched_vendor_no") or ""
                doc_type = d.get("document_type") or d.get("suggested_job_type") or ""
                status = d.get("status", "")
                doc_id = d.get("id", "")
                if not vendor or not doc_type:
                    continue

                if status in ("Completed", "Posted", "Auto-Draft", "Linked", "Filed"):
                    outcome = "success"
                elif status in ("Rejected",):
                    outcome = "failure"
                else:
                    outcome = "review"

                await record_automation_outcome(db, vendor, doc_type, outcome, doc_id)
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {"escalation_tracked": True}}
                )
                tracked += 1

            if tracked > 0:
                logger.info("[IntelMaint] Escalation backfill: tracked %d documents", tracked)
        except Exception as e:
            logger.warning("[IntelMaint] Escalation backfill failed: %s", e)

        # 3. Backfill duplicate intelligence from resolved documents
        try:
            from services.duplicate_intelligence_service import record_duplicate_outcome
            dup_docs = await db.hub_documents.find(
                {
                    "possible_duplicate": True,
                    "status": {"$in": ["Completed", "Posted", "Auto-Draft", "Linked", "Filed"]},
                    "duplicate_outcome_tracked": {"$ne": True},
                },
                {"_id": 0, "id": 1, "bc_vendor_number": 1, "vendor_no": 1, "matched_vendor_no": 1}
            ).limit(200).to_list(200)

            dup_tracked = 0
            for d in dup_docs:
                vendor = d.get("bc_vendor_number") or d.get("vendor_no") or d.get("matched_vendor_no") or ""
                doc_id = d.get("id", "")
                if not vendor:
                    continue

                # If doc was completed despite being flagged duplicate → false positive
                await record_duplicate_outcome(
                    db, doc_id=doc_id, vendor_no=vendor,
                    was_flagged_duplicate=True,
                    actual_outcome="false_positive",
                    resolution_source="backfill_completed",
                )
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {"duplicate_outcome_tracked": True}}
                )
                dup_tracked += 1

            if dup_tracked > 0:
                logger.info("[IntelMaint] Duplicate backfill: tracked %d false positives", dup_tracked)
        except Exception as e:
            logger.warning("[IntelMaint] Duplicate backfill failed: %s", e)

        # 4. Auto-close validation gaps (vendor_match + po_validation)
        try:
            from services.unified_validation_service import run_readiness
            # Find docs with open validation gaps that might now be resolvable
            gap_docs = await db.hub_documents.find(
                {
                    "is_duplicate": {"$ne": True},
                    "status": {"$nin": ["Completed", "Posted", "Archived", "batch_parent",
                                        "Exception", "exception", "FileMissing"]},
                    "$or": [
                        {"readiness.blocking_reasons": {"$exists": True, "$ne": []}},
                        {"readiness.warning_reasons": {"$exists": True, "$ne": []}},
                    ],
                    "gap_closer_last_run": {"$not": {"$gte": datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()}},
                },
                {"_id": 0},
            ).limit(100).to_list(100)

            gaps_resolved = 0
            for gdoc in gap_docs:
                doc_id = gdoc.get("id", "")
                if not doc_id:
                    continue
                try:
                    readiness = await run_readiness(doc_id)
                    is_ready = readiness.get("status", "").startswith("ready")
                    blocking = readiness.get("blocking_reasons", [])
                    if is_ready or not blocking:
                        gaps_resolved += 1
                    await db.hub_documents.update_one(
                        {"id": doc_id},
                        {"$set": {"gap_closer_last_run": datetime.now(timezone.utc).isoformat()}},
                    )
                except Exception:
                    pass

            if gaps_resolved > 0:
                logger.info("[IntelMaint] Gap closer: resolved %d/%d validation gaps", gaps_resolved, len(gap_docs))
        except Exception as e:
            logger.warning("[IntelMaint] Gap closer failed: %s", e)

        await asyncio.sleep(2 * 3600)  # Every 2 hours


async def po_retry_scheduler(
    *,
    db,
    logger,
    PO_RETRY_INTERVAL_HOURS,
    PO_MAX_WAIT_DAYS,
    PO_MAX_RETRIES,
) -> None:
    await asyncio.sleep(600)  # Initial delay: 10 minutes
    while True:
        try:
            logger.info("[PO Retry] Starting scheduled PO pending retry cycle...")
            # 1. Park any new PO-gap docs
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()

            DONE_STATUSES = ["Completed", "Posted", "Archived", "completed", "posted",
                             "archived", "FileMissing", "Exception", "exception",
                             "Validated", "validated", "ReadyForPost", "AutoFiled"]

            # Doc types that should NEVER enter the PO retry loop
            NON_PO_TYPES = [
                "Shipping_Document", "Shipping Document", "Packing_Slip", "Packing_List",
                "BOL", "Bill_of_Lading", "Bill of Lading", "Warehouse_Receipt",
                "STATEMENT", "Statement", "Account_Statement", "Remittance",
                "REMINDER", "Reminder", "Sales_Quote", "Quality_Issue",
                "Inventory_Report", "SALES_CREDIT_MEMO", "Return_Request",
            ]

            # Auto-park new PO-gap docs (AP types only, not already cleared)
            new_parked = await db.hub_documents.update_many(
                {
                    "is_duplicate": {"$ne": True},
                    "status": {"$nin": DONE_STATUSES},
                    "auto_cleared": {"$ne": True},
                    "po_pending_parked": {"$ne": True},
                    "doc_type": {"$nin": NON_PO_TYPES},
                    "document_type": {"$nin": NON_PO_TYPES},
                    "$or": [
                        {"readiness.warning_reasons": "po_missing"},
                        {"readiness.blocking_reasons": {"$regex": "po"}},
                        {"validation_results.checks": {
                            "$elemMatch": {"check_name": {"$in": ["po_validation", "po_check"]}, "passed": False},
                        }},
                    ],
                },
                {"$set": {
                    "po_pending_parked": True,
                    "po_pending_parked_at": now,
                    "po_pending_retry_count": 0,
                    "po_pending_max_retries": PO_MAX_RETRIES,
                    "po_pending_next_retry": now,
                    "workflow_status": "po_pending",
                }},
            )
            if new_parked.modified_count > 0:
                logger.info("[PO Retry] Auto-parked %d new PO-gap docs", new_parked.modified_count)

            # 2. Retry all pending docs
            from services.unified_validation_service import run_readiness

            pending = await db.hub_documents.find(
                {
                    "po_pending_parked": True,
                    "status": {"$nin": ["Completed", "Posted", "Exception", "exception"]},
                    "auto_cleared": {"$ne": True},
                    "doc_type": {"$nin": NON_PO_TYPES},
                },
                {"_id": 0},
            ).limit(200).to_list(200)

            resolved = 0
            escalated = 0
            still_waiting = 0

            for doc in pending:
                doc_id = doc["id"]
                retry_count = doc.get("po_pending_retry_count", 0) + 1
                max_r = doc.get("po_pending_max_retries", PO_MAX_RETRIES)

                try:
                    readiness = await run_readiness(doc_id)
                    po_ok = (readiness.get("signals") or {}).get("po_resolved", False)
                    is_ready = readiness.get("status", "").startswith("ready")

                    if po_ok or is_ready:
                        await db.hub_documents.update_one(
                            {"id": doc_id},
                            {"$set": {
                                "po_pending_parked": False,
                                "po_pending_resolved_at": now,
                                "po_pending_retry_count": retry_count,
                            }},
                        )
                        resolved += 1
                    elif retry_count >= max_r:
                        await db.hub_documents.update_one(
                            {"id": doc_id},
                            {"$set": {
                                "po_pending_parked": False,
                                "po_pending_retry_count": retry_count,
                                "status": "Exception",
                                "workflow_status": "exception_review",
                                "auto_cleared": True,
                                "auto_escalated": True,
                                "escalation_reason": f"PO not found after {retry_count} retries ({PO_MAX_WAIT_DAYS} days)",
                                "updated_utc": now,
                            }},
                        )
                        escalated += 1
                    else:
                        await db.hub_documents.update_one(
                            {"id": doc_id},
                            {"$set": {
                                "po_pending_retry_count": retry_count,
                                "po_pending_last_retry": now,
                                "updated_utc": now,
                            }},
                        )
                        still_waiting += 1
                except Exception as e:
                    logger.warning("[PO Retry] Error on doc=%s: %s", doc_id[:8], str(e))

            logger.info(
                "[PO Retry] Cycle done: %d checked, %d resolved, %d still waiting, %d escalated",
                len(pending), resolved, still_waiting, escalated,
            )

            # Cleanup: un-park non-AP docs that were incorrectly parked
            cleanup = await db.hub_documents.update_many(
                {
                    "po_pending_parked": True,
                    "$or": [
                        {"doc_type": {"$in": NON_PO_TYPES}},
                        {"document_type": {"$in": NON_PO_TYPES}},
                        {"auto_cleared": True},
                    ],
                },
                {"$set": {"po_pending_parked": False}, "$unset": {"escalation_reason": ""}},
            )
            if cleanup.modified_count > 0:
                logger.info("[PO Retry] Cleaned up %d incorrectly parked non-AP/cleared docs", cleanup.modified_count)
        except Exception as e:
            logger.warning("[PO Retry] Scheduled cycle failed: %s", e)

        await asyncio.sleep(PO_RETRY_INTERVAL_HOURS * 3600)


async def ready_to_post_scheduler(
    *,
    db,
    logger,
    READY_POST_INTERVAL_SECONDS,
    READY_POST_MAX_RETRIES,
) -> None:
    await asyncio.sleep(120)  # Initial delay: 2 minutes after startup
    while True:
        try:
            import os as _os
            bc_write_enabled = _os.environ.get("BC_WRITE_ENABLED", "false").lower() == "true"
            if not bc_write_enabled:
                logger.debug("[ReadyToPost] BC_WRITE_ENABLED=false, skipping cycle")
                await asyncio.sleep(READY_POST_INTERVAL_SECONDS)
                continue

            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()

            # Find ReadyForPost docs that haven't already been posted
            ready_docs = await db.hub_documents.find(
                {
                    "$or": [
                        {"status": "ReadyForPost"},
                        {"workflow_status": "ready_for_post"},
                    ],
                    "status": {"$nin": ["Posted", "Completed", "Archived"]},
                    "bc_purchase_invoice": {"$exists": False},
                    "ready_post_exhausted": {"$ne": True},
                },
                {"_id": 0, "id": 1, "bc_vendor_number": 1, "vendor_no": 1,
                 "ready_post_retry_count": 1, "file_name": 1},
            ).limit(50).to_list(50)

            if not ready_docs:
                logger.debug("[ReadyToPost] No ReadyForPost docs to process")
                await asyncio.sleep(READY_POST_INTERVAL_SECONDS)
                continue

            logger.info("[ReadyToPost] Found %d ReadyForPost docs to attempt posting", len(ready_docs))
            posted = 0
            failed = 0
            exhausted = 0

            for doc in ready_docs:
                doc_id = doc.get("id", "")
                if not doc_id:
                    continue
                retry_count = doc.get("ready_post_retry_count", 0) + 1
                vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""

                try:
                    from routers.gpi_integration import create_purchase_invoice_from_document
                    result = await create_purchase_invoice_from_document(
                        doc_id, vendor_no_override="", force=False
                    )

                    if result.get("success") or result.get("already_exists"):
                        bc_record_no = result.get("bc_record_no", "")
                        await db.hub_documents.update_one(
                            {"id": doc_id},
                            {"$set": {
                                "status": "Posted",
                                "workflow_status": "posted",
                                "auto_cleared": True,
                                "auto_post_success": True,
                                "bc_posting_status": "posted",
                                "bc_record_no": bc_record_no,
                                "bc_purchase_invoice_no": bc_record_no,
                                "bc_system_id": result.get("bc_system_id", ""),
                                "posted_to_bc_at": now_iso,
                                "ready_post_retry_count": retry_count,
                                "updated_utc": now_iso,
                            }},
                        )
                        posted += 1
                        logger.info("[ReadyToPost] Posted doc %s to BC: PI #%s", doc_id[:8], bc_record_no)
                    else:
                        error_msg = result.get("error_message") or result.get("error") or result.get("detail") or "Unknown error"
                        if retry_count >= READY_POST_MAX_RETRIES:
                            await db.hub_documents.update_one(
                                {"id": doc_id},
                                {"$set": {
                                    "ready_post_retry_count": retry_count,
                                    "ready_post_exhausted": True,
                                    "ready_post_last_error": str(error_msg)[:500],
                                    "updated_utc": now_iso,
                                }},
                            )
                            exhausted += 1
                            logger.warning("[ReadyToPost] Exhausted retries for doc %s after %d attempts: %s",
                                           doc_id[:8], retry_count, str(error_msg)[:200])
                        else:
                            await db.hub_documents.update_one(
                                {"id": doc_id},
                                {"$set": {
                                    "ready_post_retry_count": retry_count,
                                    "ready_post_last_error": str(error_msg)[:500],
                                    "updated_utc": now_iso,
                                }},
                            )
                            failed += 1
                            logger.info("[ReadyToPost] BC post attempt %d/%d failed for %s: %s",
                                        retry_count, READY_POST_MAX_RETRIES, doc_id[:8], str(error_msg)[:200])

                except Exception as e:
                    error_msg = str(e)
                    if retry_count >= READY_POST_MAX_RETRIES:
                        await db.hub_documents.update_one(
                            {"id": doc_id},
                            {"$set": {
                                "ready_post_retry_count": retry_count,
                                "ready_post_exhausted": True,
                                "ready_post_last_error": error_msg[:500],
                                "updated_utc": now_iso,
                            }},
                        )
                        exhausted += 1
                    else:
                        await db.hub_documents.update_one(
                            {"id": doc_id},
                            {"$set": {
                                "ready_post_retry_count": retry_count,
                                "ready_post_last_error": error_msg[:500],
                                "updated_utc": now_iso,
                            }},
                        )
                        failed += 1
                    logger.warning("[ReadyToPost] Exception posting doc %s (attempt %d): %s",
                                   doc_id[:8], retry_count, error_msg[:200])

            logger.info("[ReadyToPost] Cycle done: %d found, %d posted, %d failed (will retry), %d exhausted",
                        len(ready_docs), posted, failed, exhausted)
        except Exception as e:
            logger.warning("[ReadyToPost] Scheduled cycle failed: %s", e)

        await asyncio.sleep(READY_POST_INTERVAL_SECONDS)


async def captured_retry_scheduler(
    *,
    db,
    logger,
    _reprocess_document_inner,
    CAPTURED_RETRY_INTERVAL_SECONDS,
    CAPTURED_STALE_THRESHOLD_SECONDS,
    CAPTURED_MAX_RETRIES,
) -> None:
    await asyncio.sleep(180)  # Initial delay: 3 minutes after startup
    while True:
        try:
            logger.info("[CapturedRetry] Starting captured-doc retry cycle...")
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()
            cutoff = (now - timedelta(seconds=CAPTURED_STALE_THRESHOLD_SECONDS)).isoformat()

            # Find docs stuck in "captured" workflow_status for > threshold
            stuck_docs = await db.hub_documents.find(
                {
                    "workflow_status": {"$in": ["captured", "Captured"]},
                    "status": {"$nin": ["Completed", "Posted", "Archived", "Exception",
                                        "exception", "batch_parent", "FileMissing"]},
                    "created_utc": {"$lt": cutoff},
                    "captured_retry_escalated": {"$ne": True},
                },
                {"_id": 0, "id": 1, "file_name": 1, "captured_retry_count": 1},
            ).limit(50).to_list(50)

            if not stuck_docs:
                logger.info("[CapturedRetry] No stuck captured docs found.")
            else:
                retried = 0
                escalated = 0
                failed = 0

                for doc in stuck_docs:
                    doc_id = doc["id"]
                    retry_count = doc.get("captured_retry_count", 0) + 1

                    if retry_count > CAPTURED_MAX_RETRIES:
                        # Escalate to Exception Queue
                        await db.hub_documents.update_one(
                            {"id": doc_id},
                            {"$set": {
                                "status": "Exception",
                                "workflow_status": "exception_review",
                                "auto_cleared": True,
                                "auto_escalated": True,
                                "captured_retry_escalated": True,
                                "captured_retry_count": retry_count,
                                "escalation_reason": f"Stuck in captured after {retry_count - 1} retries",
                                "updated_utc": now_iso,
                            },
                            "$push": {"workflow_history": {
                                "timestamp": now_iso,
                                "from_status": "captured",
                                "to_status": "exception_review",
                                "event": "captured_retry_escalation",
                                "actor": "system",
                                "reason": f"Max retries ({CAPTURED_MAX_RETRIES}) reached",
                            }}},
                        )
                        escalated += 1
                        logger.info("[CapturedRetry] Escalated doc %s to Exception Queue (retries=%d)", doc_id[:8], retry_count - 1)
                        continue

                    # Attempt reprocess
                    try:
                        full_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
                        if not full_doc:
                            continue

                        result = await _reprocess_document_inner(doc_id, full_doc, reclassify=True)
                        reprocessed = result.get("reprocessed", False) if isinstance(result, dict) else False

                        # Update retry tracking
                        update_set = {
                            "captured_retry_count": retry_count,
                            "captured_last_retry_utc": now_iso,
                            "updated_utc": now_iso,
                        }

                        # Check if the doc moved out of "captured"
                        refreshed = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "workflow_status": 1, "status": 1})
                        ws = (refreshed or {}).get("workflow_status", "captured")
                        if ws not in ("captured", "Captured"):
                            # Successfully moved forward
                            logger.info("[CapturedRetry] Doc %s moved to '%s' after retry %d", doc_id[:8], ws, retry_count)
                            retried += 1
                        else:
                            # Still stuck — just track the retry
                            logger.info("[CapturedRetry] Doc %s still captured after retry %d/%d", doc_id[:8], retry_count, CAPTURED_MAX_RETRIES)
                            retried += 1

                        await db.hub_documents.update_one(
                            {"id": doc_id},
                            {"$set": update_set,
                            "$push": {"workflow_history": {
                                "timestamp": now_iso,
                                "from_status": "captured",
                                "to_status": ws,
                                "event": "captured_auto_retry",
                                "actor": "system",
                                "reason": f"Auto-retry attempt {retry_count}/{CAPTURED_MAX_RETRIES}",
                            }}},
                        )
                    except Exception as e:
                        logger.warning("[CapturedRetry] Error reprocessing doc %s: %s", doc_id[:8], str(e))
                        # Still track the retry attempt even on error
                        await db.hub_documents.update_one(
                            {"id": doc_id},
                            {"$set": {
                                "captured_retry_count": retry_count,
                                "captured_last_retry_utc": now_iso,
                                "captured_last_retry_error": str(e)[:500],
                                "updated_utc": now_iso,
                            }},
                        )
                        failed += 1

                logger.info(
                    "[CapturedRetry] Cycle done: %d found, %d retried, %d escalated, %d failed",
                    len(stuck_docs), retried, escalated, failed,
                )
        except Exception as e:
            logger.warning("[CapturedRetry] Scheduled cycle failed: %s", e)

        await asyncio.sleep(CAPTURED_RETRY_INTERVAL_SECONDS)
