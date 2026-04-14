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
