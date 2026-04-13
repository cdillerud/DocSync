"""GPI Document Hub - Admin Router"""

import uuid
import logging
from fastapi import APIRouter, HTTPException, Body, Query, BackgroundTasks
from datetime import datetime, timezone
from deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/backfill-ap-mailbox")
async def backfill_ap_mailbox(
    background_tasks: BackgroundTasks,
    days_back: int = Query(7, description="How many days back to search"),
    max_messages: int = Query(25, description="Maximum messages to process"),
    dry_run: bool = Query(False, description="If true, only report what would be processed"),
    mailbox: str = Query(None, description="Mailbox to poll (defaults to EMAIL_POLLING_USER)")
):
    """Backfill AP documents from email mailbox."""
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
    dry_run: bool = Query(False, description="If true, only report what would be processed")
):
    """Backfill sales documents from email mailbox."""
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

@router.post("/sales-learning/backfill-bc-orders")
async def backfill_sales_learning(background_tasks: BackgroundTasks):
    """Trigger bulk customer posting profile build from BC sales orders."""
    from deps import get_db
    db = get_db()

    async def _run_backfill():
        try:
            from services.sales_order_learning_service import build_all_customer_posting_profiles
            from services.business_central_service import BusinessCentralService
            bc = BusinessCentralService()
            await build_all_customer_posting_profiles(db, bc, top_n=50)
        except Exception as exc:
            logger.error("[SalesLearning] Background backfill failed: %s", exc)

    background_tasks.add_task(_run_backfill)
    return {"job_started": True, "message": "Sales order learning backfill started in background"}


@router.get("/sales-learning/customer-profiles")
async def get_customer_profiles_summary():
    """Summary of all customer posting profiles."""
    from deps import get_db
    db = get_db()

    total = await db.customer_posting_profiles.count_documents({})
    high = await db.customer_posting_profiles.count_documents({"template_confidence": "high"})
    medium = await db.customer_posting_profiles.count_documents({"template_confidence": "medium"})
    low = await db.customer_posting_profiles.count_documents({"template_confidence": "low"})

    # Top customers by orders analyzed
    cursor = db.customer_posting_profiles.find(
        {"status": "analyzed"},
        {"_id": 0, "customer_no": 1, "customer_name": 1, "invoices_analyzed": 1,
         "template_confidence": 1, "typical_order_value": 1, "common_items": 1}
    ).sort("invoices_analyzed", -1).limit(20)
    top_customers = []
    async for doc in cursor:
        top_customers.append(doc)

    # Last run
    last_job = await db.sales_learning_jobs.find_one(
        {}, {"_id": 0}, sort=[("started_at", -1)]
    )

    return {
        "total_profiles": total,
        "confidence_breakdown": {"high": high, "medium": medium, "low": low},
        "top_customers": top_customers,
        "last_job": last_job,
    }


@router.post("/sales-learning/detect-posted-drafts")
async def detect_posted_so_drafts():
    """Manually trigger SO draft detection."""
    from deps import get_db
    from services.sales_order_learning_service import detect_posted_sales_drafts
    db = get_db()
    result = await detect_posted_sales_drafts(db)
    return result



# =============================================================================
# Sales Order Readiness Evaluation
# =============================================================================

@router.post("/sales-learning/evaluate-readiness")
async def evaluate_readiness(
    background_tasks: BackgroundTasks,
    limit: int = Query(50, ge=1, le=500),
    sync: bool = Query(False, description="Run synchronously (slower, returns full results)"),
):
    """Run readiness reviewer against historical sales docs. Evaluation only — changes nothing."""
    from deps import get_db
    from services.sales_order_readiness_evaluator import run_batch_evaluation
    db = get_db()

    if sync:
        return await run_batch_evaluation(db, limit=limit)

    async def _run():
        try:
            await run_batch_evaluation(db, limit=limit)
        except Exception as exc:
            logger.error("[SOEval] Background evaluation failed: %s", exc)

    background_tasks.add_task(_run)
    return {"job_started": True, "limit": limit, "message": "Readiness evaluation started in background"}


@router.get("/sales-learning/readiness-evaluations")
async def list_readiness_evaluations(limit: int = Query(20, ge=1, le=100)):
    """Fetch recent evaluation run summaries."""
    from deps import get_db
    from services.sales_order_readiness_evaluator import get_evaluation_runs
    db = get_db()
    runs = await get_evaluation_runs(db, limit=limit)
    return {"runs": runs, "total": len(runs)}


@router.get("/sales-learning/readiness-evaluations/{run_id}")
async def get_readiness_evaluation_details(run_id: str, limit: int = Query(100, ge=1, le=500)):
    """Fetch per-document details for a specific evaluation run."""
    from deps import get_db
    from services.sales_order_readiness_evaluator import get_evaluation_details
    db = get_db()
    details = await get_evaluation_details(db, run_id, limit=limit)
    return {"run_id": run_id, "total": len(details), "details": details}


# =============================================================================
# Sales Order Reviewer Feedback Analytics
# =============================================================================

@router.get("/sales-learning/reviewer-feedback-summary")
async def reviewer_feedback_summary(
    date_from: str = Query(None), date_to: str = Query(None),
    customer_no: str = Query(None), reviewer: str = Query(None),
    model: str = Query(None), readiness_status: str = Query(None),
    assessment: str = Query(None), decision: str = Query(None),
):
    """Aggregate metrics on how the advisory system performs against human feedback."""
    from deps import get_db
    from services.sales_order_feedback_analytics_service import get_feedback_summary
    db = get_db()
    return await get_feedback_summary(
        db, date_from=date_from, date_to=date_to,
        customer_no=customer_no, reviewer=reviewer,
        model=model, readiness_status=readiness_status,
        assessment=assessment, decision=decision,
    )


@router.get("/sales-learning/reviewer-feedback-details")
async def reviewer_feedback_details(
    limit: int = Query(50, ge=1, le=500), skip: int = Query(0, ge=0),
    date_from: str = Query(None), date_to: str = Query(None),
    customer_no: str = Query(None), reviewer: str = Query(None),
    assessment: str = Query(None),
):
    """Individual feedback records with filtering."""
    from deps import get_db
    from services.sales_order_feedback_analytics_service import get_feedback_details
    db = get_db()
    return await get_feedback_details(
        db, limit=limit, skip=skip,
        date_from=date_from, date_to=date_to,
        customer_no=customer_no, reviewer=reviewer,
        assessment=assessment,
    )


@router.get("/sales-learning/reviewer-feedback-by-customer")
async def reviewer_feedback_by_customer(limit: int = Query(30, ge=1, le=100)):
    """Per-customer feedback summary."""
    from deps import get_db
    from services.sales_order_feedback_analytics_service import get_feedback_by_customer
    db = get_db()
    customers = await get_feedback_by_customer(db, limit=limit)
    return {"customers": customers, "total": len(customers)}


# =============================================================================
# Sales Order Disagreement Diagnostics
# =============================================================================

@router.get("/sales-learning/disagreement-diagnostics")
async def disagreement_diagnostics(
    date_from: str = Query(None), date_to: str = Query(None),
    customer_no: str = Query(None), reviewer: str = Query(None),
    model: str = Query(None), readiness_status: str = Query(None),
    assessment: str = Query(None), root_cause: str = Query(None),
):
    """Root-cause analysis of reviewer disagreements for system tuning."""
    from deps import get_db
    from services.sales_order_disagreement_diagnostics_service import run_disagreement_diagnostics
    db = get_db()
    return await run_disagreement_diagnostics(
        db, date_from=date_from, date_to=date_to,
        customer_no=customer_no, reviewer=reviewer,
        model=model, readiness_status=readiness_status,
        assessment=assessment, root_cause=root_cause,
    )


@router.get("/sales-learning/disagreement-diagnostics/examples")
async def disagreement_examples(
    root_cause: str = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """Example disagreement records, optionally filtered by root cause."""
    from deps import get_db
    from services.sales_order_disagreement_diagnostics_service import get_disagreement_examples
    db = get_db()
    examples = await get_disagreement_examples(db, root_cause=root_cause, limit=limit)
    return {"root_cause_filter": root_cause, "total": len(examples), "examples": examples}


# =============================================================================
# Sales Order Confidence Calibration
# =============================================================================

@router.post("/sales-learning/calibrate-confidence")
async def calibrate_confidence_batch(
    background_tasks: BackgroundTasks,
    limit: int = Query(200, ge=1, le=1000),
    sync: bool = Query(False),
):
    """Run confidence calibration on recent reviewed documents."""
    from deps import get_db
    from services.sales_order_confidence_calibration_service import batch_calibrate
    db = get_db()
    if sync:
        return await batch_calibrate(db, limit=limit)
    async def _run():
        try:
            await batch_calibrate(db, limit=limit)
        except Exception as exc:
            logger.error("[SOCalibration] Batch failed: %s", exc)
    background_tasks.add_task(_run)
    return {"job_started": True, "limit": limit}


@router.get("/sales-learning/calibration-comparison")
async def calibration_comparison(limit: int = Query(100, ge=1, le=500)):
    """Compare raw vs calibrated confidence with agreement rates per band."""
    from deps import get_db
    from services.sales_order_confidence_calibration_service import get_calibration_comparison
    db = get_db()
    return await get_calibration_comparison(db, limit=limit)


@router.post("/sales-learning/calibrate-document/{document_id}")
async def calibrate_single_document(document_id: str):
    """Run calibration on a single document and return the result."""
    from deps import get_db
    from services.sales_order_confidence_calibration_service import calibrate_document_review
    db = get_db()
    result = await calibrate_document_review(db, document_id)
    if result.error:
        raise HTTPException(status_code=404, detail=result.error)
    return result.to_dict()
