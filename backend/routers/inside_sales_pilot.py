"""
GPI Document Hub — Inside Sales Pilot Router

Endpoints for managing and reviewing the controlled Inside Sales
ingestion pilot (mkoch, nhannover mailboxes).
"""

import logging
from fastapi import APIRouter, Query
from typing import Optional
from deps import get_db
from services.inside_sales_pilot_service import (
    INSIDE_SALES_PILOT_ENABLED,
    INSIDE_SALES_PILOT_MAILBOXES,
    INSIDE_SALES_PILOT_INTERVAL_MINUTES,
    poll_inside_sales_pilot_mailbox,
    get_pilot_documents,
    get_pilot_run_history,
    get_pilot_status_summary,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/inside-sales-pilot", tags=["Inside Sales Pilot"])


@router.get("/status")
async def pilot_status():
    """
    Get the current Inside Sales pilot configuration and dashboard summary.
    """
    db = get_db()
    summary = await get_pilot_status_summary(db)
    return summary


@router.post("/poll-now")
async def trigger_pilot_poll(mailbox: Optional[str] = Query(None)):
    """
    Manually trigger a pilot poll run.

    If `mailbox` is provided, polls only that mailbox.
    Otherwise polls all configured pilot mailboxes.
    """
    if not INSIDE_SALES_PILOT_ENABLED:
        return {
            "error": "Inside Sales pilot is disabled. "
            "Set INSIDE_SALES_PILOT_ENABLED=true in .env to enable."
        }

    results = []
    mailboxes = [mailbox] if mailbox else INSIDE_SALES_PILOT_MAILBOXES
    for mb in mailboxes:
        stats = await poll_inside_sales_pilot_mailbox(mb)
        results.append(stats)
    return {"poll_results": results}


@router.get("/documents")
async def list_pilot_documents(
    mailbox: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """
    List documents ingested by the Inside Sales pilot.
    Filterable by mailbox and doc_type.
    """
    db = get_db()
    return await get_pilot_documents(db, mailbox=mailbox, doc_type=doc_type,
                                     skip=skip, limit=limit)


@router.get("/runs")
async def list_pilot_runs(limit: int = Query(20, ge=1, le=100)):
    """
    Get recent polling run history with stats.
    """
    db = get_db()
    runs = await get_pilot_run_history(db, limit=limit)
    return {"runs": runs, "count": len(runs)}


@router.get("/logs")
async def list_pilot_logs(
    run_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    mailbox: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """
    Get detailed pilot ingestion logs for debugging and review.
    """
    db = get_db()
    query = {}
    if run_id:
        query["run_id"] = run_id
    if status:
        query["status"] = status
    if mailbox:
        query["mailbox"] = mailbox

    logs = (
        await db.inside_sales_pilot_log.find(query, {"_id": 0})
        .sort("timestamp", -1)
        .limit(limit)
        .to_list(limit)
    )
    return {"logs": logs, "count": len(logs)}


@router.get("/extraction-review")
async def review_extractions(
    mailbox: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Review structured extraction results from pilot documents.
    Shows what data the system was able to pull from each document.
    """
    db = get_db()
    query = {
        "inside_sales_pilot": True,
        "sales_pilot_extraction": {"$exists": True, "$ne": None},
    }
    if mailbox:
        query["pilot_mailbox"] = mailbox

    total = await db.hub_documents.count_documents(query)
    docs = (
        await db.hub_documents.find(
            query,
            {
                "_id": 0,
                "id": 1,
                "file_name": 1,
                "doc_type": 1,
                "email_sender": 1,
                "email_subject": 1,
                "pilot_mailbox": 1,
                "sales_pilot_extraction": 1,
                "ai_confidence": 1,
                "created_utc": 1,
            },
        )
        .sort("created_utc", -1)
        .skip(skip)
        .limit(limit)
        .to_list(limit)
    )
    return {"total": total, "documents": docs}



@router.post("/smart-reclassify")
async def smart_reclassify(
    dry_run: bool = Query(True, description="Preview changes without applying"),
    quality_threshold: int = Query(25, ge=0, le=100),
):
    """
    Auto-reclassify pilot documents that aren't real sales orders.

    Uses filename/subject pattern matching + extraction quality scoring.
    Default is dry_run=true (preview only).  Set dry_run=false to apply.
    """
    from services.pilot_smart_reclassifier import smart_reclassify_pilot_docs
    return await smart_reclassify_pilot_docs(
        quality_threshold=quality_threshold,
        dry_run=dry_run,
    )



@router.post("/re-extract-all")
async def re_extract_all_pilot_docs():
    """
    Re-run structured extraction + BC validation on ALL pilot documents
    using the latest improved logic.  Also fixes workflow status to
    pilot_review for any pilot docs that were incorrectly exported.
    """
    db = get_db()
    docs = await db.hub_documents.find(
        {"inside_sales_pilot": True},
        {"_id": 0, "id": 1, "file_name": 1, "email_sender": 1,
         "email_subject": 1, "pilot_mailbox": 1, "workflow_status": 1},
    ).to_list(500)

    from services.inside_sales_pilot_service import _extract_sales_fields
    from services.bc_prod_validator import validate_document_against_bc

    results = {"total": len(docs), "re_extracted": 0, "re_validated": 0,
               "status_fixed": 0, "errors": []}
    for doc in docs:
        try:
            body = ""
            ext = await _extract_sales_fields(
                db, doc["id"], doc.get("file_name", ""),
                doc.get("email_subject", ""), body, doc.get("email_sender", ""),
            )
            if ext:
                results["re_extracted"] += 1
            # Re-validate against BC
            await validate_document_against_bc(doc["id"])
            results["re_validated"] += 1
            # Fix workflow status — pilot docs should never be "exported" or "completed"
            ws = doc.get("workflow_status", "")
            if ws in ("exported", "completed", "validated", "posted", "ready_to_post"):
                await db.hub_documents.update_one(
                    {"id": doc["id"]},
                    {"$set": {
                        "workflow_status": "pilot_review",
                        "status": "PilotReview",
                        "square9_stage": "pilot_observation",
                        "bc_create_ready": False,
                        "auto_create_so_blocked": True,
                        "pilot_note": "Ingest-only pilot — no BC writes, no workflow progression",
                    }},
                )
                results["status_fixed"] += 1
        except Exception as e:
            results["errors"].append(f"{doc['id'][:8]}: {e}")
    return results


# ── BC Production Validation Endpoints ──────────────────────

@router.post("/validate/{doc_id}")
async def validate_single_document(doc_id: str):
    """
    Run BC Production cross-validation on a single pilot document.
    Read-only — never writes to BC.
    """
    from services.bc_prod_validator import validate_document_against_bc
    result = await validate_document_against_bc(doc_id)
    return result


@router.post("/validate-all")
async def validate_all_documents():
    """
    Run BC Production cross-validation on all pilot documents
    that haven't been validated yet.
    """
    from services.bc_prod_validator import validate_all_pilot_documents
    result = await validate_all_pilot_documents()
    return result


@router.get("/validation-results")
async def list_validation_results(
    mailbox: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """
    List pilot documents with their BC Production validation results.
    """
    db = get_db()
    query = {
        "inside_sales_pilot": True,
        "bc_prod_validation": {"$exists": True, "$ne": None},
    }
    if mailbox:
        query["pilot_mailbox"] = mailbox

    total = await db.hub_documents.count_documents(query)
    docs = (
        await db.hub_documents.find(
            query,
            {
                "_id": 0,
                "id": 1,
                "file_name": 1,
                "doc_type": 1,
                "email_sender": 1,
                "pilot_mailbox": 1,
                "sales_pilot_extraction": 1,
                "bc_prod_validation": 1,
                "created_utc": 1,
            },
        )
        .sort("created_utc", -1)
        .skip(skip)
        .limit(limit)
        .to_list(limit)
    )
    return {"total": total, "documents": docs}


# ── Sales Corpus Validation (existing 1000+ docs) ───────────

@router.post("/validate-sales-corpus")
async def validate_sales_corpus_batch(
    batch_size: int = Query(100, ge=10, le=500),
):
    """
    Run BC Production cross-validation on existing sales documents
    (NOT pilot docs).  Processes in batches — call repeatedly until
    `remaining` reaches 0.

    Read-only — never writes to BC.
    """
    from services.bc_prod_validator import validate_sales_corpus
    result = await validate_sales_corpus(batch_size=batch_size)
    return result


@router.get("/corpus-validation-summary")
async def corpus_validation_summary():
    """
    Comprehensive validation summary comparing:
    - Existing sales corpus (1000+ docs)
    - Inside Sales pilot (mkoch/nhannover)

    Shows customer match rates, order match rates, score distribution,
    top customers, and side-by-side comparison.
    """
    db = get_db()
    from services.bc_prod_validator import get_corpus_validation_summary
    return await get_corpus_validation_summary(db)


# ── Spiro CRM Integration Endpoints ─────────────────────────

@router.post("/spiro-match/{doc_id}")
async def spiro_match_single(doc_id: str):
    """Match a single document against Spiro CRM (company + quotes)."""
    from services.spiro_service import match_document_to_spiro
    return await match_document_to_spiro(doc_id)


@router.post("/spiro-match-all")
async def spiro_match_all(force: bool = Query(False, description="Re-match all docs, even already matched")):
    """Run Spiro matching on all unmatched pilot sales documents."""
    from services.spiro_service import match_all_pilot_documents
    return await match_all_pilot_documents(force=force)


@router.get("/spiro-results")
async def spiro_match_results(
    mailbox: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """List pilot documents with their Spiro match results."""
    db = get_db()
    query = {
        "inside_sales_pilot": True,
        "spiro_match": {"$exists": True, "$ne": None},
    }
    if mailbox:
        query["pilot_mailbox"] = mailbox

    total = await db.hub_documents.count_documents(query)
    docs = (
        await db.hub_documents.find(
            query,
            {
                "_id": 0,
                "id": 1,
                "file_name": 1,
                "doc_type": 1,
                "email_sender": 1,
                "pilot_mailbox": 1,
                "spiro_match": 1,
                "sales_pilot_extraction": 1,
                "created_utc": 1,
            },
        )
        .sort("created_utc", -1)
        .skip(skip)
        .limit(limit)
        .to_list(limit)
    )
    return {"total": total, "documents": docs}


@router.get("/spiro-search")
async def spiro_company_search(name: str = Query(..., min_length=2)):
    """Search Spiro companies by name (for manual lookup)."""
    from services.spiro_service import search_company
    results = await search_company(name)
    return {"results": results, "count": len(results)}



@router.get("/spiro-bc-crossref")
async def spiro_bc_cross_reference():
    """
    Spiro ↔ BC cross-reference dashboard.

    Shows which customers exist in both systems, which are Spiro-only
    (pipeline leakage), which are BC-only (CRM gap), ISR coverage,
    and opportunity pipeline value.
    """
    db = get_db()
    from services.spiro_bc_cross_ref_service import build_cross_reference_dashboard
    return await build_cross_reference_dashboard(db)


# ── Sales Order Rules Engine Endpoints ───────────────────────

@router.post("/so-rules-evaluate/{doc_id}")
async def evaluate_single_so(doc_id: str):
    """
    Run the Sales Order Rules Engine on a single document.

    Evaluates against all 11 business rules and returns structured
    stage, compliance, blocking issues, and recommended next action.
    """
    from services.so_rules_engine import evaluate_sales_order
    return await evaluate_sales_order(doc_id)


@router.post("/so-rules-evaluate-all")
async def evaluate_all_sos():
    """
    Run the Sales Order Rules Engine on all pilot sales documents.
    """
    from services.so_rules_engine import evaluate_all_pilot_sales_orders
    return await evaluate_all_pilot_sales_orders()


@router.get("/so-rules-results")
async def so_rules_results(
    stage: Optional[str] = Query(None),
    compliance: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """
    List pilot documents with their SO Rules Engine evaluation results.
    Filterable by stage and compliance status.
    """
    db = get_db()
    query = {
        "inside_sales_pilot": True,
        "so_rules_evaluation": {"$exists": True, "$ne": None},
    }
    if stage:
        query["so_rules_evaluation.stage"] = stage
    if compliance:
        query["so_rules_evaluation.compliance_status"] = compliance

    total = await db.hub_documents.count_documents(query)
    docs = (
        await db.hub_documents.find(
            query,
            {
                "_id": 0,
                "id": 1,
                "file_name": 1,
                "doc_type": 1,
                "email_sender": 1,
                "pilot_mailbox": 1,
                "so_rules_evaluation": 1,
                "created_utc": 1,
            },
        )
        .sort("created_utc", -1)
        .skip(skip)
        .limit(limit)
        .to_list(limit)
    )
    return {"total": total, "documents": docs}
