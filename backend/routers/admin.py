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
         "template_confidence": 1, "typical_order_value": 1, "common_items": 1,
         "item_diversity_score": 1, "customer_variability_index": 1,
         "profile_richness_score": 1, "item_frequency_bands": 1}
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


# =============================================================================
# Post-Tuning Calibration & Impact Review
# =============================================================================

@router.get("/sales-learning/post-tuning-review")
async def post_tuning_review(
    date_from: str = Query(None), date_to: str = Query(None),
    customer_no: str = Query(None), reviewer: str = Query(None),
    model: str = Query(None), profile_state: str = Query(None),
    readiness_status: str = Query(None), assessment: str = Query(None),
):
    """Comprehensive post-tuning impact analysis."""
    from deps import get_db
    from services.sales_order_post_tuning_review_service import run_post_tuning_review
    db = get_db()
    return await run_post_tuning_review(
        db, date_from=date_from, date_to=date_to,
        customer_no=customer_no, reviewer=reviewer,
        model=model, profile_state=profile_state,
        readiness_status=readiness_status, assessment=assessment,
    )


@router.get("/sales-learning/post-tuning-review/details")
async def post_tuning_review_details(
    limit: int = Query(50, ge=1, le=500), skip: int = Query(0, ge=0),
    date_from: str = Query(None), date_to: str = Query(None),
):
    """Individual feedback records enriched with tuning context."""
    from deps import get_db
    from services.sales_order_post_tuning_review_service import get_post_tuning_details
    db = get_db()
    return await get_post_tuning_details(db, limit=limit, skip=skip,
                                         date_from=date_from, date_to=date_to)


# =============================================================================
# Strong-Profile Validation Review
# =============================================================================

@router.get("/sales-learning/strong-profile-review")
async def strong_profile_review(
    date_from: str = Query(None), date_to: str = Query(None),
    customer_no: str = Query(None), reviewer: str = Query(None),
    model: str = Query(None), readiness_status: str = Query(None),
    disagreement_field: str = Query(None),
):
    """Validate strong-profile tuning impact with pre/post comparison."""
    from deps import get_db
    from services.sales_order_strong_profile_review_service import run_strong_profile_review
    db = get_db()
    return await run_strong_profile_review(
        db, date_from=date_from, date_to=date_to,
        customer_no=customer_no, reviewer=reviewer,
        model=model, readiness_status=readiness_status,
        disagreement_field=disagreement_field,
    )


@router.get("/sales-learning/strong-profile-review/details")
async def strong_profile_review_details(
    limit: int = Query(50, ge=1, le=500), skip: int = Query(0, ge=0),
    date_from: str = Query(None), date_to: str = Query(None),
    customer_no: str = Query(None),
):
    """Individual strong-profile feedback records with enrichment."""
    from deps import get_db
    from services.sales_order_strong_profile_review_service import get_strong_profile_details
    db = get_db()
    return await get_strong_profile_details(db, limit=limit, skip=skip,
                                            date_from=date_from, date_to=date_to,
                                            customer_no=customer_no)


# =============================================================================
# Feedback-to-Learning Pipeline
# =============================================================================

@router.post("/sales-learning/generate-learning-suggestions")
async def gen_learning_suggestions(
    background_tasks: BackgroundTasks,
    customer_no: str = Query(None),
    limit: int = Query(50, ge=1, le=500),
    sync: bool = Query(False),
):
    """Generate candidate profile-learning suggestions from reviewer feedback."""
    from deps import get_db
    from services.unified_learning_service import generate_suggestions, SALES_CONFIG
    db = get_db()
    if sync:
        return await generate_suggestions(db, SALES_CONFIG, limit=limit)
    async def _run():
        try:
            await generate_suggestions(db, SALES_CONFIG, limit=limit)
        except Exception as exc:
            logger.error("[FeedbackLearning] Background generation failed: %s", exc)
    background_tasks.add_task(_run)
    return {"job_started": True, "customer_no": customer_no, "limit": limit}


@router.get("/sales-learning/learning-suggestions")
async def list_learning_suggestions(
    customer_no: str = Query(None),
    suggestion_type: str = Query(None),
    status: str = Query(None),
    min_confidence: float = Query(None),
    date_from: str = Query(None), date_to: str = Query(None),
    limit: int = Query(50, ge=1, le=500), skip: int = Query(0, ge=0),
):
    """Fetch learning suggestions with filters."""
    from deps import get_db
    from services.unified_learning_service import get_suggestions, SALES_CONFIG
    db = get_db()
    return await get_suggestions(
        db, SALES_CONFIG, entity_no=customer_no, suggestion_type=suggestion_type,
        status=status, limit=limit, skip=skip,
    )


@router.get("/sales-learning/learning-suggestions/{suggestion_id}")
async def get_learning_suggestion(suggestion_id: str):
    """Fetch a single suggestion by ID."""
    from deps import get_db
    from services.unified_learning_service import get_suggestion_by_id, SALES_CONFIG
    db = get_db()
    result = await get_suggestion_by_id(db, SALES_CONFIG, suggestion_id)
    if not result:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return result


# =============================================================================
# Learning Suggestion Approval / Apply Workflow
# =============================================================================

@router.post("/sales-learning/learning-suggestions/{suggestion_id}/approve")
async def approve_learning_suggestion(suggestion_id: str):
    """Approve a pending learning suggestion."""
    from deps import get_db
    from services.sales_order_learning_suggestion_apply_service import approve_suggestion
    db = get_db()
    result = await approve_suggestion(db, suggestion_id, approver="admin")
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/sales-learning/learning-suggestions/{suggestion_id}/reject")
async def reject_learning_suggestion(suggestion_id: str):
    """Reject a pending or approved suggestion."""
    from deps import get_db
    from services.unified_learning_service import reject_suggestion, SALES_CONFIG
    db = get_db()
    result = await reject_suggestion(db, SALES_CONFIG, suggestion_id, approver="admin")
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/sales-learning/learning-suggestions/{suggestion_id}/apply")
async def apply_learning_suggestion(suggestion_id: str):
    """Apply an approved suggestion to the customer profile."""
    from deps import get_db
    from services.unified_learning_service import apply_suggestion, SALES_CONFIG
    db = get_db()
    result = await apply_suggestion(db, SALES_CONFIG, suggestion_id, applier="admin")
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


# =============================================================================
# Learning Apply-Impact Review
# =============================================================================

@router.get("/sales-learning/learning-impact-review")
async def learning_impact_review(
    date_from: str = Query(None), date_to: str = Query(None),
    customer_no: str = Query(None), suggestion_type: str = Query(None),
    applied_by: str = Query(None),
):
    """Measure whether applied suggestions improved future advisory quality."""
    from deps import get_db
    from services.unified_learning_service import run_impact_review, SALES_CONFIG
    db = get_db()
    return await run_impact_review(
        db, SALES_CONFIG, date_from=date_from, date_to=date_to,
        entity_no=customer_no, suggestion_type=suggestion_type,
        applied_by=applied_by,
    )


@router.get("/sales-learning/learning-impact-review/details")
async def learning_impact_details(
    limit: int = Query(50, ge=1, le=500), skip: int = Query(0, ge=0),
    customer_no: str = Query(None), suggestion_type: str = Query(None),
):
    """Per-suggestion apply audit detail records."""
    from deps import get_db
    from services.unified_learning_service import get_impact_details, SALES_CONFIG
    db = get_db()
    return await get_impact_details(db, SALES_CONFIG, limit=limit, skip=skip,
                                    entity_no=customer_no, suggestion_type=suggestion_type)


# =============================================================================
# Profile Drift & Change History
# =============================================================================

@router.get("/sales-learning/profile-drift")
async def profile_drift_summary(
    date_from: str = Query(None), date_to: str = Query(None),
    customer_no: str = Query(None), drift_risk: str = Query(None),
    suggestion_type: str = Query(None), applied_by: str = Query(None),
):
    """Profile drift summary across all customers with applied changes."""
    from deps import get_db
    from services.sales_order_profile_drift_service import get_profile_drift_summary
    db = get_db()
    return await get_profile_drift_summary(
        db, date_from=date_from, date_to=date_to,
        customer_no=customer_no, drift_risk=drift_risk,
        suggestion_type=suggestion_type, applied_by=applied_by,
    )


@router.get("/sales-learning/profile-drift/{customer_id}")
async def profile_drift_detail(customer_id: str):
    """Detailed drift analysis for a single customer."""
    from deps import get_db
    from services.sales_order_profile_drift_service import get_customer_drift_detail
    db = get_db()
    return await get_customer_drift_detail(db, customer_id)


@router.get("/sales-learning/profile-change-history/{customer_id}")
async def profile_change_history(customer_id: str, limit: int = Query(50, ge=1, le=200)):
    """Full change history with pre/post snapshots."""
    from deps import get_db
    from services.sales_order_profile_drift_service import get_change_history
    db = get_db()
    return await get_change_history(db, customer_id, limit=limit)


# =============================================================================
# Customer Hotspot Review
# =============================================================================

@router.get("/sales-learning/customer-hotspots")
async def customer_hotspots(
    date_from: str = Query(None), date_to: str = Query(None),
    rep: str = Query(None), severity: str = Query(None),
    root_cause: str = Query(None), customer_no: str = Query(None),
    limit: int = Query(30, ge=1, le=100),
):
    """Rank customers by advisory friction with root-cause diagnosis."""
    from deps import get_db
    from services.sales_order_customer_hotspot_review_service import get_customer_hotspots
    db = get_db()
    return await get_customer_hotspots(
        db, date_from=date_from, date_to=date_to,
        rep=rep, severity=severity, root_cause=root_cause,
        customer_no=customer_no, limit=limit,
    )


@router.get("/sales-learning/customer-hotspots/{customer_id}")
async def customer_hotspot_detail(customer_id: str):
    """Detailed hotspot analysis for one customer."""
    from deps import get_db
    from services.sales_order_customer_hotspot_review_service import get_customer_hotspot_detail
    db = get_db()
    result = await get_customer_hotspot_detail(db, customer_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# =============================================================================
# Maturity Checkpoint & Reusability
# =============================================================================

@router.get("/sales-learning/maturity-checkpoint")
async def maturity_checkpoint():
    """Overall maturity assessment of the SO advisory/learning system."""
    from deps import get_db
    from services.sales_order_maturity_checkpoint_service import run_maturity_checkpoint
    db = get_db()
    return await run_maturity_checkpoint(db)


@router.get("/sales-learning/maturity-checkpoint/reusability")
async def maturity_reusability():
    """Component reusability inventory and next-workflow recommendation."""
    from deps import get_db
    from services.sales_order_maturity_checkpoint_service import get_reusability_review
    db = get_db()
    return await get_reusability_review(db)


# =============================================================================
# Unified Learning Summary (Cross-Pipeline View)
# =============================================================================

@router.get("/unified-learning/summary")
async def unified_learning_summary():
    """Cross-pipeline learning summary — powers the AI Learning Intelligence dashboard."""
    from deps import get_db
    from services.unified_learning_service import get_unified_learning_summary
    db = get_db()
    return await get_unified_learning_summary(db)



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
    limit: int = Query(2000, ge=1, le=20000),
    min_count: int = Query(2, ge=2, le=100,
                           description="Only flag groups with at least this many dupes"),
):
    """Find groups of docs with identical (file_name + vendor_canonical
    [+ ingestion day]). Catches email-poller dedup misses — e.g. the
    GAMMIN_AR_20260316.xls that arrived 12 times in one day."""
    from services.admin.triage_tools_service import duplicate_scan
    return await duplicate_scan(
        same_day=same_day, limit=limit, min_count=min_count,
    )


@router.post("/duplicate-docs/resolve")
async def duplicate_docs_resolve(
    execute: bool = Query(False, description="Required True to mutate"),
    keep: str = Query("oldest", description="'oldest' | 'newest'"),
    same_day: bool = Query(True),
    limit: int = Query(2000, ge=1, le=20000),
    actor: str = Query("admin"),
):
    """Mark all-but-one doc per duplicate group as `duplicate_of=<keeper>`,
    status=Completed, queue_visible=false. Dry-run by default."""
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
