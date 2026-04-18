"""
GPI Document Hub — Intake Learning Router
─────────────────────────────────────────

Endpoints for the hub-wide Giovanni-style BC + Spiro learning pipeline.
Reads only — never writes to BC.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from services.sales_intake_learning_service import (
    run_intake_learning,
    run_intake_learning_for_xls_staging,
    backfill_intake_learning,
    refresh_active_customers,
    get_intake_learning_summary,
)
from deps import get_db

router = APIRouter(prefix="/intake", tags=["intake-learning"])


@router.post("/learning/run/{doc_id}")
async def run_learning_for_document(doc_id: str, force: bool = False):
    """Manually (re-)run intake learning on a single hub document."""
    result = await run_intake_learning(doc_id, force=force)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/learning/run-xls/{staging_id}")
async def run_learning_for_xls(staging_id: str, force: bool = False):
    """Manually (re-)run intake learning on an inventory XLS staging record."""
    result = await run_intake_learning_for_xls_staging(staging_id, force=force)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/insights/{doc_id}")
async def get_document_insights(doc_id: str):
    """Return persisted intake_insights for a hub document."""
    db = get_db()
    doc = await db.hub_documents.find_one(
        {"id": doc_id},
        {"_id": 0, "id": 1, "doc_type": 1, "file_name": 1, "intake_insights": 1},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "doc_id": doc_id,
        "doc_type": doc.get("doc_type"),
        "file_name": doc.get("file_name"),
        "intake_insights": doc.get("intake_insights"),
    }


@router.get("/insights-xls/{staging_id}")
async def get_xls_insights(staging_id: str):
    """Return persisted intake_insights for an XLS staging record."""
    db = get_db()
    from services.inventory_xls_staging_service import STAGING_COLL
    staging = await db[STAGING_COLL].find_one(
        {"id": staging_id},
        {"_id": 0, "id": 1, "filename": 1, "intake_insights": 1},
    )
    if not staging:
        raise HTTPException(status_code=404, detail="Staging record not found")
    return {
        "staging_id": staging_id,
        "filename": staging.get("filename"),
        "intake_insights": staging.get("intake_insights"),
    }


@router.post("/learning/backfill")
async def backfill_learning(
    limit: int = Query(500, le=5000),
    only_missing: bool = Query(True),
):
    """Backfill intake learning across all eligible hub docs + XLS staging.

    By default only processes docs that don't yet have `intake_insights`.
    Pass `only_missing=false` to force re-run on every doc.
    """
    return await backfill_intake_learning(limit=limit, only_missing=only_missing)


@router.post("/learning/refresh-active")
async def refresh_active(
    lookback_hours: int = Query(24, ge=1, le=720),
    max_customers: int = Query(100, le=500),
    refresh_docs: bool = Query(True),
):
    """Re-learn for customers whose BC posted orders changed recently.

    Designed to run daily (via scheduler) OR on-demand when you post a
    batch of orders to BC and want the hub to pick up the fresh patterns
    right away. Read-only against BC.
    """
    return await refresh_active_customers(
        lookback_hours=lookback_hours,
        max_customers=max_customers,
        refresh_docs=refresh_docs,
    )


@router.get("/learning/summary")
async def learning_summary():
    """Dashboard-level metrics for intake-learning coverage across the hub."""
    return await get_intake_learning_summary()


@router.get("/flagged")
async def list_flagged_documents(
    limit: int = Query(50, le=500),
    customer_no: Optional[str] = None,
):
    """List hub documents where intake learning found actionable issues
    (qty bounds violation, suggested lines, or unmatched items)."""
    db = get_db()
    q = {"intake_insights.has_actionable_findings": True}
    if customer_no:
        q["intake_insights.customer_no"] = customer_no
    docs = await db.hub_documents.find(
        q,
        {
            "_id": 0, "id": 1, "file_name": 1, "doc_type": 1,
            "email_sender": 1, "created_utc": 1,
            "intake_insights": 1,
        },
    ).sort("created_utc", -1).limit(limit).to_list(limit)
    return {"total": len(docs), "documents": docs}
