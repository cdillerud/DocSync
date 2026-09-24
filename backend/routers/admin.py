"""GPI Document Hub - Admin Router"""

import uuid
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Body, Query, BackgroundTasks, Depends
from datetime import datetime, timezone, timedelta
from deps import get_db
from services.auth_deps import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/deprecation-metrics")
async def deprecation_metrics(
    days: int = Query(14, ge=1, le=180, description="Lookback window in days (UTC day buckets)"),
    _user: dict = Depends(require_admin),
):
    """Observability for deprecated-route usage. ADMIN ONLY.

    Returns day-bucketed hit counts for every deprecated route that has
    received traffic in the lookback window. Used as the gating metric for
    AP_PATH_CONSOLIDATION Phase 4 — removal is safe once the six AP mutation
    routes show zero hits across the required drain window.

    Response also carries a ``phase_4_gate`` projection so a single curl
    answers "can we ship Phase 4?" with a boolean + reasons, AND an
    ``observability_limitations`` field that explicitly names the blind
    spot (see below).

    OBSERVABILITY LIMITATION (documented per user directive 2026-04-22):
      HTTP 422 body-validation failures are raised by FastAPI/Pydantic
      BEFORE the ``routers/workflows.py::_deprecate()`` wrapper runs, so
      malformed requests to Path B are NOT recorded in
      ``db.deprecation_hits`` and do NOT emit ``[DEPRECATED]`` log lines.
      This means ``deprecation_hits`` reflects *valid* Path B requests
      that reached the deprecated wrapper — not every attempted call.
      In practice any real caller (BC extension, AL script, automated
      flow, or our own frontend) sends well-formed bodies, so this blind
      spot is narrow. A future enhancement could move hit recording into
      a starlette middleware keyed on the matched route template BEFORE
      body parsing. Not implemented in v2.5.27 per user directive
      ("finish drain + Phase 4 first, then decide").
    """
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    raw = await db.deprecation_hits.find(
        {"day_bucket": {"$gte": cutoff}},
        {"_id": 0},
    ).sort([("deprecated_path", 1), ("day_bucket", 1)]).to_list(5000)

    # Aggregate totals per route.
    totals: dict = {}
    for row in raw:
        key = f"{row['method']} {row['deprecated_path']}"
        bucket = totals.setdefault(key, {
            "method": row["method"],
            "deprecated_path": row["deprecated_path"],
            "canonical_path": row.get("canonical_path"),
            "total_hits": 0,
            "days_with_traffic": 0,
            "last_seen_utc": None,
            "last_status": None,
            "last_client_host": None,
            "last_user_agent": None,
            "last_auth_present": None,
        })
        bucket["total_hits"] += row.get("count", 0)
        bucket["days_with_traffic"] += 1
        if not bucket["last_seen_utc"] or row.get("last_seen_utc", "") > bucket["last_seen_utc"]:
            bucket["last_seen_utc"] = row.get("last_seen_utc")
            bucket["last_status"] = row.get("last_status")
            bucket["last_client_host"] = row.get("last_client_host")
            bucket["last_user_agent"] = row.get("last_user_agent")
            bucket["last_auth_present"] = row.get("last_auth_present")

    route_totals = sorted(totals.values(), key=lambda r: r["total_hits"], reverse=True)

    # ── Phase 4 gate projection ──────────────────────────────────────────
    # Hard gate per user directive (2026-04-22): the six AP mutation
    # templates must show zero hits for 7 consecutive days plus a green
    # regression suite. This projection computes the first half (the hit
    # count) so one curl answers "gate met?".
    AP_MUTATION_TEMPLATES = [
        "/api/workflows/ap_invoice/{doc_id}/set-vendor",
        "/api/workflows/ap_invoice/{doc_id}/update-fields",
        "/api/workflows/ap_invoice/{doc_id}/override-bc-validation",
        "/api/workflows/ap_invoice/{doc_id}/start-approval",
        "/api/workflows/ap_invoice/{doc_id}/approve",
        "/api/workflows/ap_invoice/{doc_id}/reject",
    ]
    GATE_WINDOW_DAYS = 7
    gate_cutoff = (
        datetime.now(timezone.utc) - timedelta(days=GATE_WINDOW_DAYS)
    ).strftime("%Y-%m-%d")

    # Query the 7-day gate window directly (independent of the caller's
    # `days` arg, so /deprecation-metrics?days=1 still reports the full
    # 7-day gate truthfully).
    gate_rows = await db.deprecation_hits.find(
        {
            "day_bucket": {"$gte": gate_cutoff},
            "deprecated_path": {"$in": AP_MUTATION_TEMPLATES},
        },
        {"_id": 0, "deprecated_path": 1, "count": 1, "last_seen_utc": 1,
         "last_client_host": 1, "last_user_agent": 1, "day_bucket": 1},
    ).to_list(500)

    hits_by_template: dict = {t: 0 for t in AP_MUTATION_TEMPLATES}
    offending_callers: list = []
    for row in gate_rows:
        hits_by_template[row["deprecated_path"]] = (
            hits_by_template.get(row["deprecated_path"], 0) + row.get("count", 0)
        )
        offending_callers.append({
            "deprecated_path": row["deprecated_path"],
            "day_bucket": row.get("day_bucket"),
            "count": row.get("count", 0),
            "last_seen_utc": row.get("last_seen_utc"),
            "last_client_host": row.get("last_client_host"),
            "last_user_agent": row.get("last_user_agent"),
        })

    total_hits_in_gate_window = sum(hits_by_template.values())
    gate_met = total_hits_in_gate_window == 0

    phase_4_gate = {
        "gate_met": gate_met,
        "gate_description": (
            "Zero hits on all six AP mutation Path B templates across "
            f"{GATE_WINDOW_DAYS} consecutive days AND regression suite green."
        ),
        "window_days": GATE_WINDOW_DAYS,
        "window_since_day_bucket": gate_cutoff,
        "ap_mutation_routes_monitored": AP_MUTATION_TEMPLATES,
        "total_hits_in_window": total_hits_in_gate_window,
        "hits_by_template": hits_by_template,
        "offending_callers": offending_callers,  # empty when gate_met
        "action_if_gate_not_met": (
            "Identify caller via last_client_host + last_user_agent, "
            "repoint to the canonical Path A URL, then restart the "
            f"{GATE_WINDOW_DAYS}-day drain clock."
        ),
        "observability_limitations": [
            "HTTP 422 body-validation failures are raised by FastAPI/Pydantic "
            "BEFORE the _deprecate() wrapper runs, so malformed requests to "
            "Path B are NOT recorded here. `deprecation_hits` reflects valid "
            "Path B requests that reached the deprecated wrapper, not every "
            "attempted call. In practice real callers send well-formed bodies, "
            "so the blind spot is narrow.",
            "401 (missing JWT) and 404 (missing doc) DO reach the wrapper and "
            "are recorded — so callers hitting a deprecated URL without auth "
            "or against a bad doc_id are still visible.",
            "The counter is day-bucketed in UTC. A caller that hits the route "
            "twice in the same UTC day shows as count=2 on one row; across "
            "two UTC days shows as two rows with count=1 each.",
        ],
    }

    return {
        "window_days": days,
        "since_day_bucket": cutoff,
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "route_totals": route_totals,
        "daily_breakdown": raw,
        "phase_4_gate": phase_4_gate,
    }


@router.post("/backfill-ap-mailbox")
async def backfill_ap_mailbox(
    background_tasks: BackgroundTasks,
    days_back: int = Query(7, description="How many days back to search"),
    max_messages: int = Query(25, description="Maximum messages to process"),
    dry_run: bool = Query(False, description="If true, only report what would be processed"),
    mailbox: str = Query(None, description="Mailbox to poll (defaults to EMAIL_POLLING_USER)"),
    _user: dict = Depends(require_admin),
):
    """Backfill AP documents from email mailbox. ADMIN ONLY."""
    from services.email_service import get_email_service
    email_service = get_email_service()
    if not email_service:
        raise HTTPException(status_code=503, detail="Email service not initialized")
    result = await email_service.poll_ap_mailbox(
        days_back=days_back, max_messages=max_messages, dry_run=dry_run, mailbox=mailbox
    )
    return result


@router.post("/backfill-sales-mailbox")
async def backfill_sales_mailbox(
    background_tasks: BackgroundTasks,
    days_back: int = Query(30, description="How many days back to search"),
    max_messages: int = Query(50, description="Maximum messages to process"),
    dry_run: bool = Query(False, description="If true, only report what would be processed"),
    _user: dict = Depends(require_admin),
):
    """Backfill sales documents from email mailbox. ADMIN ONLY."""
    from services.email_service import get_email_service
    email_service = get_email_service()
    if not email_service:
        raise HTTPException(status_code=503, detail="Email service not initialized")
    result = await email_service.poll_sales_mailbox(
        days_back=days_back, max_messages=max_messages, dry_run=dry_run
    )
    return result


@router.post("/migrate-sales-to-unified")
async def migrate_sales_documents_to_unified():
    """
    One-time migration to move sales_documents into the main hub_documents collection.
    Documents from sales_documents will be copied to hub_documents with category='Sales'.
    Duplicates (by document_id) will be skipped.
    """
    db = get_db()
    run_id = uuid.uuid4().hex[:8]
    stats = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "sales_documents_found": 0,
        "migrated": 0,
        "skipped_duplicate": 0,
        "errors": [],
        "migrated_documents": []
    }

    try:
        sales_docs = await db.sales_documents.find({}, {"_id": 0}).to_list(1000)
        stats["sales_documents_found"] = len(sales_docs)
        logger.info("[Migration:%s] Found %d sales documents to migrate", run_id, len(sales_docs))

        for sdoc in sales_docs:
            doc_id = sdoc.get("document_id")
            existing = await db.hub_documents.find_one({"id": doc_id})
            if existing:
                stats["skipped_duplicate"] += 1
                continue

            now = datetime.now(timezone.utc).isoformat()
            hub_doc = {
                "id": doc_id,
                "source": sdoc.get("source", "email"),
                "file_name": sdoc.get("file_name"),
                "sha256_hash": sdoc.get("file_hash"),
                "file_size": sdoc.get("file_size"),
                "content_type": "application/octet-stream",
                "email_sender": sdoc.get("email_sender"),
                "email_subject": sdoc.get("email_subject"),
                "email_id": sdoc.get("email_message_id"),
                "email_received_utc": sdoc.get("created_utc"),
                "document_type": sdoc.get("document_type"),
                "category": "Sales",
                "suggested_job_type": sdoc.get("document_type"),
                "ai_confidence": sdoc.get("ai_confidence"),
                "extracted_fields": sdoc.get("extracted_fields", {}),
                "status": sdoc.get("status", "NeedsReview"),
                "workflow_state": sdoc.get("workflow_state", "Classified"),
                "created_utc": sdoc.get("created_utc", now),
                "updated_utc": now,
                "migrated_from": "sales_documents",
                "migrated_at": now,
            }
            try:
                await db.hub_documents.insert_one(hub_doc)
                stats["migrated"] += 1
                stats["migrated_documents"].append({
                    "document_id": doc_id,
                    "document_type": sdoc.get("document_type"),
                    "file_name": sdoc.get("file_name")
                })
            except Exception as e:
                stats["errors"].append(f"Failed to migrate {doc_id}: {str(e)}")

        stats["ended_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        stats["errors"].append(f"Migration error: {str(e)}")
        logger.error("[Migration:%s] Error: %s", run_id, str(e))

    return stats


@router.post("/square9-cutover")
async def execute_square9_cutover():
    """Decommission Square9 — GPI Hub becomes the authoritative document system.

    Sets square9_active=false in hub_config, records timestamp,
    and logs a system activity record. Idempotent.
    """
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    existing = await db.hub_config.find_one({"_key": "square9_cutover"}, {"_id": 0})
    if existing and existing.get("square9_active") is False:
        return {
            "status": "already_decommissioned",
            "cutover_at": existing.get("cutover_at"),
            "message": "Square9 was already decommissioned.",
        }

    await db.hub_config.update_one(
        {"_key": "square9_cutover"},
        {"$set": {
            "_key": "square9_cutover",
            "square9_active": False,
            "cutover_at": now,
            "cutover_by": "admin",
        }},
        upsert=True,
    )

    await db.activity_log.insert_one({
        "id": uuid.uuid4().hex,
        "entity_type": "system",
        "entity_id": "square9_cutover",
        "action": "square9_decommissioned",
        "title": "Square9 Decommissioned",
        "body": "GPI Hub is now the authoritative document system. Square9 stages are archived as historical metadata.",
        "created_utc": now,
    })

    logger.info("[Admin] Square9 cutover executed at %s", now)

    return {
        "status": "decommissioned",
        "cutover_at": now,
        "message": "Square9 decommissioned. GPI Hub is now the authoritative document system.",
    }


@router.post("/recompute-derived-states")
async def recompute_derived_states(
    background_tasks: BackgroundTasks,
    dry_run: bool = Query(False),
):
    """Batch recompute derived states for all documents.
    
    This updates validation_state, workflow_state, and automation_state
    on every document based on current event history and document fields.
    Useful after validation logic changes to refresh queue badges.
    """
    run_id = str(uuid.uuid4())[:8]
    logger.info("[RecomputeStates:%s] Starting (dry_run=%s)", run_id, dry_run)
    
    background_tasks.add_task(_recompute_states_task, run_id, dry_run)
    return {
        "run_id": run_id,
        "status": "started",
        "dry_run": dry_run,
        "message": "Derived state recomputation started in background. Check /api/admin/recompute-status/{run_id} for progress."
    }


@router.get("/recompute-status/{run_id}")
async def get_recompute_status(run_id: str):
    """Check status of a recompute job."""
    db = get_db()
    job = await db.admin_jobs.find_one({"run_id": run_id}, {"_id": 0})
    if not job:
        return {"run_id": run_id, "status": "not_found"}
    return job


async def _recompute_states_task(run_id: str, dry_run: bool):
    """Background task to recompute derived states."""
    from services.derived_state_service import DerivedStateService
    
    db = get_db()
    svc = DerivedStateService(db)
    
    stats = {
        "run_id": run_id,
        "status": "running",
        "dry_run": dry_run,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "total": 0,
        "processed": 0,
        "changed": 0,
        "errors": 0,
        "changes": [],
    }
    
    await db.admin_jobs.update_one(
        {"run_id": run_id}, {"$set": stats}, upsert=True
    )
    
    try:
        docs = await db.hub_documents.find(
            {},
            {"_id": 0, "id": 1, "validation_state": 1, "workflow_state": 1, 
             "automation_state": 1, "file_name": 1}
        ).to_list(10000)
        
        stats["total"] = len(docs)
        
        for i, doc in enumerate(docs):
            doc_id = doc["id"]
            old_vs = doc.get("validation_state")
            old_ws = doc.get("workflow_state")
            old_as = doc.get("automation_state")
            
            try:
                if dry_run:
                    derived = await svc.derive_state(doc_id)
                else:
                    derived = await svc.update_document_derived_state(doc_id)
                
                new_vs = derived["validation_state"]
                new_ws = derived["workflow_state"]
                new_as = derived["automation_state"]
                
                changed = (old_vs != new_vs or old_ws != new_ws or old_as != new_as)
                if changed:
                    stats["changed"] += 1
                    if len(stats["changes"]) < 100:  # Cap detail list
                        stats["changes"].append({
                            "doc_id": doc_id,
                            "file_name": doc.get("file_name", ""),
                            "validation": f"{old_vs} -> {new_vs}" if old_vs != new_vs else None,
                            "workflow": f"{old_ws} -> {new_ws}" if old_ws != new_ws else None,
                            "automation": f"{old_as} -> {new_as}" if old_as != new_as else None,
                        })
                
                stats["processed"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.error("[RecomputeStates:%s] Error on doc %s: %s", run_id, doc_id[:8], str(e))
            
            # Update progress every 50 docs
            if (i + 1) % 50 == 0:
                await db.admin_jobs.update_one(
                    {"run_id": run_id}, {"$set": stats}
                )
        
        stats["status"] = "completed"
        stats["ended_at"] = datetime.now(timezone.utc).isoformat()
        
    except Exception as e:
        stats["status"] = "failed"
        stats["error_message"] = str(e)
        logger.error("[RecomputeStates:%s] Fatal error: %s", run_id, str(e))
    
    await db.admin_jobs.update_one(
        {"run_id": run_id}, {"$set": stats}
    )
    logger.info(
        "[RecomputeStates:%s] Done: %d processed, %d changed, %d errors",
        run_id, stats["processed"], stats["changed"], stats["errors"]
    )


# =========================================================================
# SH_INVOICE: Processor Assignment & Queue
# =========================================================================

@router.post("/sh-invoice/{doc_id}/assign-processor")
async def assign_sh_processor(doc_id: str, payload: dict = Body(...)):
    """Assign a processor (Andy or Ellie) to an SH_Invoice document.

    Body: {"processor": "Andy" | "Ellie"}
    Sets the processor field on the document and returns the updated doc.
    """
    processor = (payload.get("processor") or "").strip()
    if processor not in ("Andy", "Ellie"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid processor '{processor}'. Must be 'Andy' or 'Ellie'.",
        )

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc_type = doc.get("suggested_job_type") or doc.get("document_type") or ""
    if doc_type != "SH_Invoice":
        raise HTTPException(
            status_code=400,
            detail=f"Document type is '{doc_type}', expected SH_Invoice",
        )

    now = datetime.now(timezone.utc).isoformat()
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "processor": processor,
            "processor_assigned_utc": now,
            "updated_utc": now,
        }},
    )

    # Return updated document
    updated = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "success": True,
        "doc_id": doc_id,
        "processor": processor,
        "assigned_at": now,
        "document": updated,
    }


@router.get("/sh-invoice/queue")
async def get_sh_invoice_queue(
    status: str = Query("pending_approval", description="Filter by workflow status"),
    processor: str = Query(None, description="Filter by assigned processor"),
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    """Return SH_Invoice documents in the approval queue.

    Defaults to pending_approval status. Supports filtering by processor.
    """
    db = get_db()

    query = {
        "$or": [
            {"suggested_job_type": "SH_Invoice"},
            {"document_type": "SH_Invoice"},
        ],
    }
    if status:
        query["workflow_status"] = status
    if processor:
        query["processor"] = processor

    total = await db.hub_documents.count_documents(query)
    docs = await db.hub_documents.find(
        query, {"_id": 0}
    ).sort("created_utc", -1).skip(skip).limit(limit).to_list(length=limit)

    return {
        "total": total,
        "returned": len(docs),
        "status_filter": status,
        "processor_filter": processor,
        "documents": docs,
    }


# =============================================================================
# Sales Order Learning
# =============================================================================


# =============================================================================
# Sales Order Readiness Evaluation
# =============================================================================


# =============================================================================
# Sales Order Reviewer Feedback Analytics
# =============================================================================


# =============================================================================
# Sales Order Disagreement Diagnostics
# =============================================================================


# =============================================================================
# Sales Order Confidence Calibration
# =============================================================================


# =============================================================================
# Post-Tuning Calibration & Impact Review
# =============================================================================


# =============================================================================
# Strong-Profile Validation Review
# =============================================================================


# =============================================================================
# Feedback-to-Learning Pipeline
# =============================================================================


# =============================================================================
# Learning Suggestion Approval / Apply Workflow
# =============================================================================


# =============================================================================
# Learning Apply-Impact Review
# =============================================================================


# =============================================================================
# Profile Drift & Change History
# =============================================================================


# =============================================================================
# Customer Hotspot Review
# =============================================================================


# =============================================================================
# Maturity Checkpoint & Reusability
# =============================================================================


# =============================================================================
# Unified Learning Summary (Cross-Pipeline View)
# =============================================================================


# ─────────────── Unknown-Doc Reclaim (v2.5.5) ───────────────

@router.get("/unknown-doc-reclaim/preview")
async def unknown_doc_reclaim_preview(
    limit: int = Query(50, ge=1, le=500),
    smart: bool = Query(False, description="If true, surface how many candidates could inherit parent metadata"),
    skip_noise: bool = Query(False, description="If true, surface how many candidates match the noise filter"),
):
    """Dry-run the reclaim sweep. With `smart=true` + `skip_noise=true` the
    sample_breakdown includes `smart_inheritable` and `filtered_as_noise`
    counts so you can see the impact before flipping `execute=true`."""
    from services.admin.unknown_doc_reclaim_service import preview
    return await preview(limit=limit, smart=smart, skip_noise=skip_noise)


@router.post("/unknown-doc-reclaim/run")
async def unknown_doc_reclaim_run(
    execute: bool = Query(False, description="Required True to actually mutate"),
    limit: int = Query(None, ge=1, le=10000,
                       description="Optional cap — reclaim at most N docs this run"),
    actor: str = Query("admin", description="Audit actor label"),
    smart: bool = Query(False, description=(
        "Batch-split children whose parent is classified inherit the "
        "parent's doc_type + vendor before routing to NeedsReview"
    )),
    skip_noise: bool = Query(False, description=(
        "Filename-noise candidates (email sprites, signatures, image.png, "
        "tracking pixels) are marked noise_filtered and kept OUT of "
        "NeedsReview"
    )),
):
    """Execute the reclaim. Defaults to `execute=false` (dry-run). Mode
    flags `smart` + `skip_noise` can be combined freely. Per-run audit
    row written to `unknown_doc_reclaim_runs`."""
    from services.admin.unknown_doc_reclaim_service import run as do_run
    return await do_run(
        execute=execute, limit=limit, actor=actor,
        smart=smart, skip_noise=skip_noise,
    )


@router.get("/unknown-doc-reclaim/runs")
async def unknown_doc_reclaim_runs(limit: int = Query(20, ge=1, le=100)):
    """Recent reclaim run history — audit trail for the sweep."""
    from services.admin.unknown_doc_reclaim_service import recent_runs
    runs = await recent_runs(limit=limit)
    return {"total": len(runs), "runs": runs}


@router.post("/unknown-doc-reclaim/post-process")
async def unknown_doc_reclaim_post_process(
    execute: bool = Query(False, description="Required True to actually mutate"),
    limit: int = Query(None, ge=1, le=10000, description="Optional cap"),
    actor: str = Query("admin", description="Audit actor label"),
    smart: bool = Query(False, description=(
        "Retroactively inherit parent metadata onto batch-split children "
        "that were reclaimed without the smart flag"
    )),
    skip_noise: bool = Query(False, description=(
        "Retroactively revert filename-noise docs out of NeedsReview "
        "into noise_filtered=true"
    )),
):
    """Retroactively apply smart + skip_noise modes to docs that were
    already reclaimed by an earlier plain v2.5.5 run. Dry-run by default.
    Idempotent via `post_process_applied_at` sentinel."""
    from services.admin.unknown_doc_reclaim_service import post_process
    return await post_process(
        execute=execute, limit=limit, actor=actor,
        smart=smart, skip_noise=skip_noise,
    )


@router.get("/unknown-doc-reclaim/post-process/runs")
async def unknown_doc_reclaim_post_process_runs(limit: int = Query(20, ge=1, le=100)):
    """Recent retro post-process run history."""
    from services.admin.unknown_doc_reclaim_service import recent_post_process_runs
    runs = await recent_post_process_runs(limit=limit)
    return {"total": len(runs), "runs": runs}


# ─────────────── Filename Heuristics (v2.5.8) ───────────────

@router.get("/filename-heuristics/rules")
async def filename_heuristics_rules():
    """Expose the current rule set so operators can see what patterns will match."""
    from services.admin.filename_heuristics_service import list_rules
    rules = list_rules()
    return {"total": len(rules), "rules": rules}


@router.get("/filename-heuristics/preview")
async def filename_heuristics_preview(
    limit: int = Query(2000, ge=1, le=10000),
):
    """Dry-run the heuristic classifier across candidate docs. Returns
    match counts by rule + by target doc_type + a 30-doc sample showing
    exactly which rule matched each filename."""
    from services.admin.filename_heuristics_service import preview
    return await preview(limit=limit)


@router.post("/filename-heuristics/apply")
async def filename_heuristics_apply(
    execute: bool = Query(False, description="Required True to mutate"),
    limit: int = Query(None, ge=1, le=10000),
    actor: str = Query("admin"),
    min_confidence: float = Query(0.70, ge=0.0, le=1.0),
    keep_in_review: bool = Query(True, description=(
        "If True (default) the doc stays at its current status (usually "
        "NeedsReview) but gets enriched with doc_type + vendor. Never "
        "auto-clears — always requires human signoff."
    )),
):
    """Apply filename-heuristic classifications. Dry-run by default."""
    from services.admin.filename_heuristics_service import apply
    return await apply(
        execute=execute, limit=limit, actor=actor,
        min_confidence=min_confidence, keep_in_review=keep_in_review,
    )


@router.get("/filename-heuristics/runs")
async def filename_heuristics_runs(limit: int = Query(20, ge=1, le=100)):
    """Audit trail for heuristic runs."""
    from services.admin.filename_heuristics_service import recent_runs
    runs = await recent_runs(limit=limit)
    return {"total": len(runs), "runs": runs}


# ─────────── Triage Tools: Unmatched Sample + Duplicate Scan (v2.5.9) ───────────

@router.get("/filename-heuristics/unmatched-sample")
async def filename_heuristics_unmatched_sample(
    limit: int = Query(2000, ge=1, le=10000,
                       description="Max docs scanned"),
    top_n: int = Query(40, ge=1, le=200,
                       description="Top N groups returned"),
    min_group_size: int = Query(2, ge=1, le=50,
                                description="Skip groups smaller than this"),
):
    """Groups currently-unmatched filenames by (vendor, shape-signature)
    to surface next-wave rule candidates. Shape collapses digit runs to
    `#+` and letter runs to `A+` so e.g. `ROT12345_p1.pdf` and
    `ROT99_p3.pdf` share the same shape `A+#+_A+#+.A+`."""
    from services.admin.triage_tools_service import unmatched_sample
    return await unmatched_sample(
        limit=limit, top_n=top_n, min_group_size=min_group_size,
    )


@router.get("/duplicate-docs/scan")
async def duplicate_docs_scan(
    same_day: bool = Query(True,
                           description="Also require same YYYY-MM-DD ingestion day"),
    limit: int = Query(20000, ge=1, le=100000),
    min_count: int = Query(2, ge=2, le=100,
                           description="Only flag groups with at least this many dupes"),
    max_groups_returned: int = Query(
        1000, ge=1, le=10000,
        description="Cap on the returned groups array (response size). "
                    "`groups_total` always reflects the true count."),
):
    """Find groups of docs with identical (file_name + vendor_canonical
    [+ ingestion day]). Catches email-poller dedup misses — e.g. the
    GAMMIN_AR_20260316.xls that arrived 12 times in one day."""
    from services.admin.triage_tools_service import duplicate_scan
    return await duplicate_scan(
        same_day=same_day, limit=limit, min_count=min_count,
        max_groups_returned=max_groups_returned,
    )


@router.post("/duplicate-docs/resolve")
async def duplicate_docs_resolve(
    execute: bool = Query(False, description="Required True to mutate"),
    keep: str = Query("oldest", description="'oldest' | 'newest'"),
    same_day: bool = Query(True),
    limit: int = Query(20000, ge=1, le=100000),
    actor: str = Query("admin"),
):
    """Mark all-but-one doc per duplicate group as `duplicate_of=<keeper>`,
    status=Completed, queue_visible=false. Dry-run by default. One call
    now clears the full backlog (previously required a for-loop)."""
    from services.admin.triage_tools_service import duplicate_resolve
    if keep not in ("oldest", "newest"):
        keep = "oldest"
    return await duplicate_resolve(
        execute=execute, keep=keep, same_day=same_day,
        limit=limit, actor=actor,
    )


@router.get("/duplicate-docs/runs")
async def duplicate_docs_runs(limit: int = Query(20, ge=1, le=100)):
    """Audit trail for duplicate-resolve runs."""
    from services.admin.triage_tools_service import recent_duplicate_runs
    runs = await recent_duplicate_runs(limit=limit)
    return {"total": len(runs), "runs": runs}


# ─────────── Auto-Proposed Filename Heuristic Rules (v2.5.10) ───────────

@router.get("/filename-heuristics/auto-propose")
async def filename_heuristics_auto_propose(
    limit: int = Query(3000, ge=100, le=20000,
                       description="Max unmatched docs scanned"),
    min_group_size: int = Query(3, ge=1, le=50,
                                description="Skip (vendor, shape) groups smaller than this"),
    min_vendor_samples: int = Query(5, ge=1, le=500,
                                    description="Min classified docs for a vendor "
                                                "to drive a majority vote"),
    min_majority_pct: float = Query(70.0, ge=50.0, le=100.0,
                                    description="Minimum %% the winning doc_type "
                                                "needs to carry"),
):
    """Derive rule proposals by mining each vendor's own classified
    history. Returns `proposals` (ready to execute) + `deferred` (need
    a human)."""
    from services.admin.filename_heuristics_auto_service import auto_propose
    return await auto_propose(
        limit=limit,
        min_group_size=min_group_size,
        min_vendor_samples=min_vendor_samples,
        min_majority_pct=min_majority_pct,
    )


@router.post("/filename-heuristics/auto-apply")
async def filename_heuristics_auto_apply(
    execute: bool = Query(False, description="Required True to persist"),
    actor: str = Query("admin"),
    min_unmatched_count: int = Query(3, ge=1, le=500),
    min_confidence: float = Query(0.70, ge=0.5, le=1.0),
    limit: int = Query(3000, ge=100, le=20000),
):
    """Persist every high-confidence auto-proposed rule into
    `filename_heuristic_custom_rules`. Dry-run by default."""
    from services.admin.filename_heuristics_auto_service import apply_auto_proposed
    return await apply_auto_proposed(
        execute=execute, actor=actor,
        min_unmatched_count=min_unmatched_count,
        min_confidence=min_confidence, limit=limit,
    )


@router.get("/filename-heuristics/custom-rules")
async def filename_heuristics_custom_rules(
    only_enabled: bool = Query(False),
):
    """List all custom (auto-proposed) rules currently in Mongo."""
    from services.admin.filename_heuristics_auto_service import list_custom_rules
    rules = await list_custom_rules(only_enabled=only_enabled)
    return {"total": len(rules), "rules": rules}


@router.post("/filename-heuristics/custom-rules/{rule_id}/toggle")
async def filename_heuristics_custom_rule_toggle(
    rule_id: str,
    enabled: bool = Query(...),
):
    """Enable or disable a single custom rule."""
    from services.admin.filename_heuristics_auto_service import (
        set_custom_rule_enabled,
    )
    from services.admin.filename_heuristics_service import (
        _invalidate_custom_rule_cache,
    )
    result = await set_custom_rule_enabled(rule_id, enabled)
    _invalidate_custom_rule_cache()
    return result


@router.get("/filename-heuristics/vendor-history")
async def filename_heuristics_vendor_history(
    vendor: str = Query(..., description="vendor_canonical (primary) or vendor_name fallback"),
    include_heuristic_applied: bool = Query(
        False,
        description="If True, also count docs that were classified by a previous "
                    "filename-heuristic run (normally excluded to avoid feedback loops).",
    ),
    limit: int = Query(2000, ge=100, le=20000),
):
    """Diagnostic: show a vendor's full classified doc_type distribution.

    Use this when `/auto-propose` deferred a vendor with
    `reason='vendor has 0 classified docs'` or a low majority — it
    surfaces WHY so you can decide whether to lower thresholds,
    classify a few docs manually first, or write a rule by hand.
    """
    from services.admin.filename_heuristics_auto_service import (
        vendor_doc_type_distribution,
    )
    from deps import get_db
    db = get_db()
    return await vendor_doc_type_distribution(
        db, vendor, vendor,
        include_heuristic_applied=include_heuristic_applied,
        limit=limit,
    )

