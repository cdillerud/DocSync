"""
GPI Document Hub — Intake Learning Router
─────────────────────────────────────────

Endpoints for the hub-wide Giovanni-style BC + Spiro learning pipeline.
Reads only — never writes to BC.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional

from services.sales_intake_learning_service import (
    run_intake_learning,
    run_intake_learning_for_xls_staging,
    backfill_intake_learning,
    refresh_active_customers,
    get_intake_learning_summary,
)
from services.intake_learning_feedback_service import (
    record_feedback_event,
    get_pattern_health,
    run_pattern_hygiene,
    list_recent_events,
    EVENT_TYPES,
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
    from workflows.inventory.planning.staging import STAGING_COLL
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



# ─────────────────────────────────────────────────────────────
# Phase D — Feedback Loop
# ─────────────────────────────────────────────────────────────

class FeedbackEvent(BaseModel):
    event_type: str = Field(..., description=f"One of {sorted(EVENT_TYPES)}")
    doc_id: Optional[str] = None
    staging_id: Optional[str] = None
    customer_no: Optional[str] = None
    item_no: Optional[str] = None
    trigger_item: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    actor: Optional[str] = "user"


@router.post("/insights/feedback")
async def post_feedback(body: FeedbackEvent):
    """Capture a reviewer feedback event and apply it to the learned pattern.

    Event types:
      • `suggestion_accepted` / `suggestion_rejected` — adjust pattern occurrence / frequency
      • `bounds_violation_confirmed` / `bounds_violation_overridden` — nudge qty envelope
      • `unmatched_item_confirmed_new` / `unmatched_item_mapped` — seed item alias candidates
    """
    if body.event_type not in EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"event_type must be one of {sorted(EVENT_TYPES)}")
    return await record_feedback_event(
        event_type=body.event_type,
        doc_id=body.doc_id,
        staging_id=body.staging_id,
        customer_no=body.customer_no,
        item_no=body.item_no,
        trigger_item=body.trigger_item,
        extra=body.extra,
        actor=body.actor or "user",
    )


@router.get("/learning/pattern-health")
async def pattern_health(limit: int = Query(50, le=500)):
    """Dashboard aggregation of pattern trust / retire / drift counts."""
    return await get_pattern_health(limit=limit)


@router.post("/learning/hygiene")
async def trigger_hygiene():
    """Manually kick the nightly pattern-hygiene pass."""
    return await run_pattern_hygiene()


@router.get("/learning/events")
async def recent_events(
    limit: int = Query(100, le=500),
    event_type: Optional[str] = None,
    customer_no: Optional[str] = None,
):
    """Most recent feedback events (audit feed)."""
    events = await list_recent_events(
        limit=limit, event_type=event_type, customer_no=customer_no,
    )
    return {"total": len(events), "events": events}


# ─────────────────────────────────────────────────────────────
# Phase E — Cold-Start Peer Matching (v2.4.0)
# ─────────────────────────────────────────────────────────────

class PromoteInheritedBody(BaseModel):
    target_customer_no: str
    source_customer_no: str
    item_no: str
    trigger_item: Optional[str] = None
    doc_id: Optional[str] = None


@router.post("/insights/promote-inherited")
async def promote_inherited(body: PromoteInheritedBody):
    """Promote an inherited (peer-matched) suggestion into the target
    customer's own learned pattern. Reviewer-driven — never automatic."""
    from services.cold_start_matcher_service import promote_inherited_suggestion
    result = await promote_inherited_suggestion(
        target_customer_no=body.target_customer_no,
        source_customer_no=body.source_customer_no,
        item_no=body.item_no,
        trigger_item=body.trigger_item,
    )
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/learning/rebuild-fingerprints")
async def rebuild_fingerprints():
    """Force a rebuild of every customer fingerprint. Useful after a
    big BC re-sync or a batch feedback load."""
    from services.cold_start_matcher_service import rebuild_all_fingerprints
    return await rebuild_all_fingerprints()


@router.get("/learning/similar-customers")
async def similar_customers_preview(
    customer_no: Optional[str] = None,
    doc_id: Optional[str] = None,
    top_k: int = Query(3, le=10),
):
    """Preview peer matches for an existing doc or a specific customer's
    own fingerprint. Handy for diagnostics and UI development."""
    from services.cold_start_matcher_service import (
        find_similar_customers, get_or_build_fingerprint,
    )
    db = get_db()
    line_items: list = []
    if doc_id:
        d = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        if d:
            ef = d.get("extracted_fields") or {}
            nf = d.get("normalized_fields") or {}
            extr = d.get("sales_pilot_extraction") or {}
            line_items = (
                extr.get("line_items")
                or nf.get("line_items")
                or ef.get("line_items")
                or []
            )
    elif customer_no:
        # Use the customer's own fingerprint as the query — useful for "who
        # are we most like?" exploration.
        fp = await get_or_build_fingerprint(customer_no)
        # synthesize pseudo-line-items from the fingerprint tokens
        line_items = [{"description": tok} for tok in (fp.get("tf") or {}).keys()]
    matches = await find_similar_customers(
        line_items, top_k=top_k, exclude_customer_no=customer_no, db=db,
    )
    return {"matches": matches, "query_item_count": len(line_items)}
