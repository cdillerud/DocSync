"""GPI Document Hub - Sales Order Readiness Router

Sales-side counterpart to routers/square9.py's AP cutover readiness
dashboard. Where the AP side compares Hub processing against Square9's
historical output, there is no equivalent external baseline for sales
order automation -- so this tracks the metrics that actually gate
attempt_auto_create_sales_order() in services/auto_post_service.py:
rep-assignment rate, customer match rate, and order/PO reference match
rate (the last of these is the weakest today and the real blocker).

READY_MATCH_RATE_THRESHOLD_PCT below is a PROPOSED threshold, not an
established one like the AP side's 85% (which came from actual Square9
parity requirements). It mirrors that number as a reasonable starting
point since order-match accuracy is the closest sales-side analogue to
AP's document-match accuracy, but should be revisited once there's a
real track record of what match rate correlates with correct BC writes.

This router is entirely read-only against production data: it computes
snapshots from existing collections (hub_documents, sales_readiness_history)
and calls the same real functions the live pipeline uses (never
reimplements their logic), and the dry-run simulation makes no BC calls
and never touches the inside_sales_pilot safety gate.
"""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any, List

from deps import get_db

logger = logging.getLogger("sales_readiness")

router = APIRouter(prefix="/sales/readiness", tags=["Sales Readiness"])

# Proposed, not established -- see module docstring.
READY_MATCH_RATE_THRESHOLD_PCT = 85.0


async def _compute_snapshot(db) -> Dict[str, Any]:
    """Computes one real sales-readiness snapshot from current live data.

    Reuses the exact same aggregation shape as
    routers/inside_sales_pilot.py's match_tier_distribution() and
    get_pilot_status_summary() (bc_prod_validation.* fields) rather than
    inventing a parallel computation, so this dashboard can never drift
    from what the Sales Intake dashboard itself shows.
    """
    base_q = {"inside_sales_pilot": True}
    total_docs = await db.hub_documents.count_documents(base_q)

    # ---- BC customer/order match rates (mirrors get_pilot_status_summary) ----
    bc_pipeline = [
        {"$match": {**base_q, "bc_prod_validation.overall_score": {"$exists": True}}},
        {"$group": {
            "_id": None,
            "total_validated": {"$sum": 1},
            "customer_found": {"$sum": {"$cond": [
                {"$eq": ["$bc_prod_validation.customer_match.found", True]}, 1, 0
            ]}},
            "order_found": {"$sum": {"$cond": [
                {"$eq": ["$bc_prod_validation.order_lookup.found", True]}, 1, 0
            ]}},
        }},
    ]
    bc_result = await db.hub_documents.aggregate(bc_pipeline).to_list(1)
    br = bc_result[0] if bc_result else {}
    total_validated = br.get("total_validated", 0) or 0
    customer_found = br.get("customer_found", 0) or 0
    order_found = br.get("order_found", 0) or 0

    customer_match_pct = round(customer_found / total_validated * 100, 1) if total_validated else 0.0
    order_match_pct = round(order_found / total_validated * 100, 1) if total_validated else 0.0

    # 2026-09-30: this previously hand-copied match_tier_distribution()'s
    # pipeline (a drifted-local-copy bug -- the exact same class already
    # found and fixed 3+ times elsewhere in this codebase today) and had
    # gone stale the moment the real function was fixed to split no_match
    # from no_ref by reason and add a not_validated bucket. Now calls the
    # real function directly so this dashboard can never again disagree
    # with the Sales Intake dashboard showing the same underlying data.
    from routers.inside_sales_pilot import match_tier_distribution as _real_tier_distribution
    tier_result = await _real_tier_distribution()
    buckets = tier_result["buckets"]

    # ---- Rep-assignment rate ----
    review_pipeline = [
        {"$match": base_q},
        {"$group": {"_id": "$sales_review_status", "count": {"$sum": 1}}},
    ]
    review_rows = await db.hub_documents.aggregate(review_pipeline).to_list(20)
    review_counts = {(r["_id"] or "not_evaluated"): r["count"] for r in review_rows}
    assigned = review_counts.get("pending_rep_review", 0) + review_counts.get("auto_approved", 0)
    triage = review_counts.get("triage", 0)
    rep_assignment_rate_pct = round(assigned / total_docs * 100, 1) if total_docs else 0.0

    # ---- SO auto-creation funnel (ground truth, not estimated) ----
    auto_create_attempted = await db.hub_documents.count_documents(
        {**base_q, "auto_create_attempted": True}
    )
    so_created = await db.hub_documents.count_documents(
        {**base_q, "bc_so_number": {"$exists": True, "$nin": [None, ""]}}
    )

    decision = "GO" if order_match_pct >= READY_MATCH_RATE_THRESHOLD_PCT else "NOT_READY"

    return {
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "match_rate_pct": order_match_pct,  # headline number, matches the dashboard's convention (order match = the real gate)
        "min_match_rate_pct": READY_MATCH_RATE_THRESHOLD_PCT,
        "threshold_is_proposed": True,
        "total_pilot_docs": total_docs,
        "total_validated": total_validated,
        "customer_match_pct": customer_match_pct,
        "order_match_pct": order_match_pct,
        "rep_assignment_rate_pct": rep_assignment_rate_pct,
        "rep_assigned_count": assigned,
        "rep_triage_count": triage,
        "tier_buckets": buckets,
        "auto_create_attempted_count": auto_create_attempted,
        "so_created_count": so_created,
    }


@router.get("/latest")
async def get_latest_sales_readiness():
    """Most recent sales-order readiness snapshot."""
    db = get_db()
    latest = await db.sales_readiness_history.find_one(
        {}, {"_id": 0}, sort=[("recorded_utc", -1)]
    )
    if not latest:
        raise HTTPException(
            status_code=404,
            detail="No sales readiness snapshots recorded yet. POST /api/sales/readiness/run to record one.",
        )
    return latest


@router.get("/history")
async def get_sales_readiness_history(limit: int = Query(200, ge=1, le=1000)):
    """Chronological history of sales readiness snapshots, oldest first, for trend charting."""
    db = get_db()
    cursor = db.sales_readiness_history.find(
        {}, {"_id": 0}
    ).sort("recorded_utc", 1).limit(limit)
    history = await cursor.to_list(length=limit)
    return {"count": len(history), "history": history}


@router.post("/run")
async def run_sales_readiness_check():
    """Computes a fresh snapshot now and records it.

    Unlike the AP side's readiness check, this is fast (direct MongoDB
    aggregates against already-computed bc_prod_validation fields, no
    external comparison or subprocess), so it runs synchronously instead
    of the AP page's background-subprocess-plus-poll pattern.
    """
    db = get_db()
    snapshot = await _compute_snapshot(db)
    await db.sales_readiness_history.insert_one(dict(snapshot))
    return snapshot


@router.get("/dry-run")
async def dry_run_so_auto_creation(limit: int = Query(500, ge=1, le=5000)):
    """Read-only simulation: if the inside_sales_pilot safety gate were
    not blocking auto-creation, what would happen right now?

    Calls the REAL check_sales_order_eligibility() and the real
    rep-assignment/match state already on each document -- never
    reimplements that logic, never calls BC, never touches the actual
    safety gate. Purely reports what the existing logic would decide.
    """
    from services.auto_post_service import check_sales_order_eligibility

    db = get_db()
    docs = await db.hub_documents.find(
        {"inside_sales_pilot": True},
        {
            "_id": 0, "id": 1, "file_name": 1, "doc_type": 1, "document_type": 1,
            "sales_review_status": 1, "assigned_rep_email": 1,
            "bc_prod_validation": 1, "inside_sales_pilot": 1,
        },
    ).to_list(limit)

    would_create = 0
    blocked_by_pilot_gate = 0
    blocked_other = 0
    blocked_reasons: Dict[str, int] = {}
    samples: List[Dict[str, Any]] = []

    for doc in docs:
        eligible, reason = check_sales_order_eligibility(doc)

        # The pilot gate is what's actually stopping every one of these
        # today -- simulate "what if that specific check didn't apply"
        # by re-checking eligibility on a copy with inside_sales_pilot
        # cleared, WITHOUT writing that change anywhere or calling BC.
        sim_doc = dict(doc)
        sim_doc["inside_sales_pilot"] = False
        sim_doc.pop("ingestion_source", None)
        sim_doc.pop("source", None)
        sim_eligible, sim_reason = check_sales_order_eligibility(sim_doc)

        if not eligible and "Inside Sales Pilot" in (reason or ""):
            blocked_by_pilot_gate += 1

        if sim_eligible:
            would_create += 1
            if len(samples) < 25:
                samples.append({
                    "file_name": doc.get("file_name"),
                    "sales_review_status": doc.get("sales_review_status"),
                    "would_be_eligible": True,
                })
        else:
            blocked_other += 1
            blocked_reasons[sim_reason] = blocked_reasons.get(sim_reason, 0) + 1

    return {
        "computed_utc": datetime.now(timezone.utc).isoformat(),
        "total_checked": len(docs),
        "currently_blocked_by_pilot_gate": blocked_by_pilot_gate,
        "would_be_eligible_if_gate_removed": would_create,
        "would_still_be_blocked_other_reasons": blocked_other,
        "other_block_reasons": blocked_reasons,
        "sample_would_create": samples,
        "note": "Simulation only -- no BC calls made, no documents modified, the real safety gate is untouched.",
    }
