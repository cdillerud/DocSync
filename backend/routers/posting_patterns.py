"""
GPI Document Hub — Posting Pattern Analysis API

Phase 1: Analyze BC posting patterns and build vendor posting profiles.
Phase 2: Template-driven draft PI creation, auto-post settings, ready document queue.
"""
import asyncio
import logging
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Query, BackgroundTasks, Body
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/posting-patterns", tags=["posting-patterns"])


# =============================================================================
# Learning Intelligence API — Proof of AI Learning
# =============================================================================

@router.get("/learning-dashboard")
async def get_learning_dashboard():
    """
    Comprehensive view of what the AI has learned.
    Aggregates data from all learning subsystems:
    - Posting pattern learning events
    - Classification corrections & feedback
    - Label correction patterns (e.g., BOL→PO)
    - Vendor extraction profiles
    - Stable vendor evaluations
    """
    db = get_db()

    # 1. Posting Learning Events — proof of continuous template learning
    total_learning_events = await db.posting_learning_events.count_documents({})
    recent_learning = await db.posting_learning_events.find(
        {}, {"_id": 0, "vendor_no": 1, "posted_at": 1, "line_count": 1, "items_used": 1, "amount": 1}
    ).sort("posted_at", -1).limit(20).to_list(20)

    # Learning events by vendor
    vendor_learning_pipeline = [
        {"$group": {
            "_id": "$vendor_no",
            "events": {"$sum": 1},
            "last_learned": {"$max": "$posted_at"},
            "total_amount": {"$sum": "$amount"},
            "avg_lines": {"$avg": "$line_count"},
        }},
        {"$sort": {"events": -1}},
        {"$limit": 20},
    ]
    vendor_learning = await db.posting_learning_events.aggregate(vendor_learning_pipeline).to_list(20)

    # 2. Classification Corrections — proof of classification learning
    total_corrections = await db.classification_corrections.count_documents({})
    correction_types = await db.classification_corrections.aggregate([
        {"$group": {"_id": "$correction_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]).to_list(20)

    recent_corrections = await db.classification_corrections.find(
        {}, {"_id": 0, "vendor_id": 1, "correction_type": 1, "original_type": 1,
             "corrected_type": 1, "confirmed_at": 1, "source": 1}
    ).sort("confirmed_at", -1).limit(10).to_list(10)

    # 3. Classification Feedback — few-shot examples for LLM
    total_feedback = await db.classification_feedback.count_documents({})

    # 4. Label Corrections — proof of reference intelligence learning (BOL→PO etc.)
    total_label_corrections = await db.reference_label_corrections.count_documents({})
    label_correction_patterns = await db.reference_label_corrections.aggregate([
        {"$group": {
            "_id": {"predicted": "$predicted_label", "correct": "$correct_label"},
            "count": {"$sum": 1},
            "vendors": {"$addToSet": "$vendor_name"},
            "last_seen": {"$max": "$created_at"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]).to_list(10)

    # 5. Posting Template Profiles — how many vendors have learned templates
    total_profiles = await db.posting_pattern_analysis.count_documents({"status": "analyzed"})
    profiles_by_confidence = await db.posting_pattern_analysis.aggregate([
        {"$match": {"status": "analyzed"}},
        {"$group": {
            "_id": "$posting_template.confidence",
            "count": {"$sum": 1},
            "avg_invoices": {"$avg": "$invoices_analyzed"},
        }},
        {"$sort": {"count": -1}},
    ]).to_list(5)

    # Vendors with continuous learning (template updated after initial analysis)
    continuously_learning = await db.posting_pattern_analysis.count_documents({
        "status": "analyzed",
        "continuous_learning_count": {"$gte": 1},
    })

    # 6. Vendor Extraction Profiles — learned extraction biases
    total_extraction_profiles = await db.vendor_extraction_profiles.count_documents({})

    # 7. Vendor Intelligence Profiles — overall vendor knowledge
    total_vendor_profiles = await db.vendor_intelligence_profiles.count_documents({})

    # 8. Auto-draft success tracking
    total_auto_drafted = await db.hub_documents.count_documents({"auto_draft_created": True})
    auto_draft_by_vendor = await db.hub_documents.aggregate([
        {"$match": {"auto_draft_created": True}},
        {"$group": {
            "_id": "$bc_vendor_number",
            "drafts_created": {"$sum": 1},
            "last_draft": {"$max": "$auto_draft_at"},
        }},
        {"$sort": {"drafts_created": -1}},
        {"$limit": 10},
    ]).to_list(10)

    return {
        "summary": {
            "total_learning_events": total_learning_events,
            "total_corrections": total_corrections,
            "total_feedback_examples": total_feedback,
            "total_label_corrections": total_label_corrections,
            "total_posting_profiles": total_profiles,
            "continuously_learning_vendors": continuously_learning,
            "total_extraction_profiles": total_extraction_profiles,
            "total_vendor_profiles": total_vendor_profiles,
            "total_auto_drafted": total_auto_drafted,
        },
        "posting_template_confidence": [
            {"confidence": p["_id"], "vendor_count": p["count"], "avg_invoices_analyzed": round(p.get("avg_invoices") or 0, 1)}
            for p in profiles_by_confidence
        ],
        "vendor_learning_activity": [
            {"vendor_no": v["_id"], "learning_events": v["events"], "last_learned": v["last_learned"],
             "total_amount_learned": round(v.get("total_amount") or 0, 2), "avg_lines_per_invoice": round(v.get("avg_lines") or 0, 1)}
            for v in vendor_learning
        ],
        "label_correction_patterns": [
            {"from_label": p["_id"]["predicted"], "to_label": p["_id"]["correct"],
             "corrections": p["count"], "vendors_affected": len(p.get("vendors", [])),
             "last_seen": p.get("last_seen")}
            for p in label_correction_patterns
        ],
        "correction_types": [{"type": c["_id"], "count": c["count"]} for c in correction_types],
        "recent_learning_events": recent_learning,
        "recent_corrections": recent_corrections,
        "auto_draft_by_vendor": [
            {"vendor_no": d["_id"], "drafts_created": d["drafts_created"], "last_draft": d["last_draft"]}
            for d in auto_draft_by_vendor
        ],
    }



@router.get("/review-queue/badge-count")
async def get_review_queue_badge_count():
    """
    Lightweight endpoint for the nav badge — returns count of drafts needing attention.
    Includes pending reviews + BC-edited drafts (feedback detected changes).
    """
    db = get_db()
    count = await db.hub_documents.count_documents({
        "auto_draft_created": True,
        "draft_review_status": {"$nin": ["approved", "corrected", "feedback_synced"]},
    })
    return {"count": count}



# =============================================================================
# Review Queue — Review / Approve / Correct Auto-Drafted PIs
# =============================================================================

@router.get("/review-queue")
async def get_review_queue(
    status_filter: str = Query("pending", description="Filter: pending, approved, corrected, all"),
    vendor_no: str = Query("", description="Filter by vendor"),
    limit: int = Query(50, le=200),
):
    """
    List auto-drafted Purchase Invoices that need human review.
    Shows documents where auto_draft_created=True with their review status.
    """
    db = get_db()

    match_filter = {"auto_draft_created": True}
    if vendor_no:
        match_filter["$or"] = [
            {"bc_vendor_number": vendor_no},
            {"vendor_no": vendor_no},
        ]

    # Status filter
    if status_filter == "pending":
        match_filter["draft_review_status"] = {"$nin": ["approved", "corrected"]}
    elif status_filter in ("approved", "corrected"):
        match_filter["draft_review_status"] = status_filter

    docs = await db.hub_documents.find(
        match_filter,
        {
            "_id": 0, "id": 1, "filename": 1, "file_name": 1,
            "doc_type": 1, "document_type": 1,
            "bc_vendor_number": 1, "vendor_no": 1, "vendor_canonical": 1,
            "extracted_fields.invoice_number": 1, "extracted_fields.amount": 1,
            "extracted_fields.invoice_date": 1,
            "normalized_fields.invoice_number": 1, "normalized_fields.amount": 1,
            "auto_draft_created": 1, "auto_draft_at": 1,
            "auto_draft_confidence": 1, "auto_draft_bc_record_no": 1,
            "auto_draft_source": 1,
            "draft_review_status": 1, "draft_reviewed_at": 1, "draft_reviewed_by": 1,
            "draft_corrections": 1,
            "bc_purchase_invoice": 1,
            "status": 1, "workflow_status": 1, "created_utc": 1,
        }
    ).sort("auto_draft_at", -1).limit(limit).to_list(limit)

    items = []
    for doc in docs:
        ef = doc.get("extracted_fields") or {}
        nf = doc.get("normalized_fields") or {}
        v_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""

        items.append({
            "id": doc.get("id", ""),
            "filename": doc.get("filename") or doc.get("file_name", ""),
            "vendor_no": v_no,
            "vendor_name": doc.get("vendor_canonical", ""),
            "invoice_number": ef.get("invoice_number") or nf.get("invoice_number", ""),
            "amount": ef.get("amount") or nf.get("amount", ""),
            "invoice_date": ef.get("invoice_date") or nf.get("invoice_date", ""),
            "confidence": doc.get("auto_draft_confidence", ""),
            "bc_record_no": doc.get("auto_draft_bc_record_no", ""),
            "draft_source": doc.get("auto_draft_source", ""),
            "drafted_at": doc.get("auto_draft_at", ""),
            "review_status": doc.get("draft_review_status", "pending"),
            "reviewed_at": doc.get("draft_reviewed_at", ""),
            "reviewed_by": doc.get("draft_reviewed_by", ""),
            "corrections": doc.get("draft_corrections") or [],
        })

    # Summary counts
    total_pending = await db.hub_documents.count_documents({
        "auto_draft_created": True,
        "draft_review_status": {"$nin": ["approved", "corrected"]},
    })
    total_approved = await db.hub_documents.count_documents({
        "auto_draft_created": True,
        "draft_review_status": "approved",
    })
    total_corrected = await db.hub_documents.count_documents({
        "auto_draft_created": True,
        "draft_review_status": "corrected",
    })

    return {
        "count": len(items),
        "items": items,
        "summary": {
            "pending": total_pending,
            "approved": total_approved,
            "corrected": total_corrected,
            "total": total_pending + total_approved + total_corrected,
        },
    }


@router.post("/review-queue/{doc_id}/approve")
async def approve_draft(doc_id: str, reviewer: str = Query("admin")):
    """
    Approve an auto-drafted PI. Marks it as human-verified.
    Creates a positive feedback event so the system learns that this template worked.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "id": 1, "auto_draft_created": 1, "bc_vendor_number": 1, "vendor_no": 1, "auto_draft_confidence": 1, "auto_draft_bc_record_no": 1})
    if not doc:
        return {"success": False, "error": "Document not found"}
    if not doc.get("auto_draft_created"):
        return {"success": False, "error": "Document has no auto-draft to approve"}

    now = datetime.now(timezone.utc).isoformat()
    v_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""

    # Mark as approved
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "draft_review_status": "approved",
            "draft_reviewed_at": now,
            "draft_reviewed_by": reviewer,
        }}
    )

    # Create positive feedback event — template produced correct result
    await db.posting_learning_events.insert_one({
        "vendor_no": v_no,
        "doc_id": doc_id,
        "event_type": "draft_approved",
        "confidence": doc.get("auto_draft_confidence", ""),
        "bc_record_no": doc.get("auto_draft_bc_record_no", ""),
        "reviewer": reviewer,
        "posted_at": now,
        "feedback": "positive",
    })

    logger.info("[Review Queue] Approved draft for %s (vendor=%s) by %s", doc_id[:8], v_no, reviewer)
    return {"success": True, "message": f"Draft approved for {doc_id[:8]}", "review_status": "approved"}


@router.post("/review-queue/{doc_id}/correct")
async def correct_draft(
    doc_id: str,
    corrections: list = Body(..., description="List of corrections: [{field, original, corrected, note}]"),
    reviewer: str = Query("admin"),
):
    """
    Submit corrections for an auto-drafted PI. Records what the human changed
    so the system can learn from mistakes and improve future templates.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "id": 1, "auto_draft_created": 1, "bc_vendor_number": 1, "vendor_no": 1, "auto_draft_confidence": 1, "auto_draft_bc_record_no": 1})
    if not doc:
        return {"success": False, "error": "Document not found"}
    if not doc.get("auto_draft_created"):
        return {"success": False, "error": "Document has no auto-draft to correct"}

    now = datetime.now(timezone.utc).isoformat()
    v_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""

    # Mark as corrected with correction details
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "draft_review_status": "corrected",
            "draft_reviewed_at": now,
            "draft_reviewed_by": reviewer,
            "draft_corrections": corrections,
        }}
    )

    # Create correction feedback event — template needs adjustment
    await db.posting_learning_events.insert_one({
        "vendor_no": v_no,
        "doc_id": doc_id,
        "event_type": "draft_corrected",
        "confidence": doc.get("auto_draft_confidence", ""),
        "bc_record_no": doc.get("auto_draft_bc_record_no", ""),
        "corrections": corrections,
        "reviewer": reviewer,
        "posted_at": now,
        "feedback": "corrective",
    })

    # Also record as classification corrections for the learning dashboard
    for c in corrections:
        await db.classification_corrections.insert_one({
            "doc_id": doc_id,
            "vendor_id": v_no,
            "correction_type": f"draft_{c.get('field', 'unknown')}",
            "original_type": c.get("original", ""),
            "corrected_type": c.get("corrected", ""),
            "source": "review_queue",
            "confirmed_at": now,
            "applied": True,
        })

    logger.info("[Review Queue] Corrected draft for %s (vendor=%s): %d corrections by %s",
                doc_id[:8], v_no, len(corrections), reviewer)
    return {
        "success": True,
        "message": f"Corrections recorded for {doc_id[:8]} — {len(corrections)} fields corrected",
        "review_status": "corrected",
        "corrections_count": len(corrections),
    }


# =============================================================================
# Feedback Loop — BC Draft Sync & Template Adjustment
# =============================================================================

@router.post("/review-queue/{doc_id}/sync-from-bc")
async def sync_draft_from_bc_endpoint(doc_id: str):
    """
    Fetch the current state of an auto-drafted PI from BC.
    Compares original draft lines with what's currently in BC (after human edits).
    If changes are detected, feeds them back into the posting template.
    """
    db = get_db()
    from services.draft_feedback_service import sync_draft_from_bc
    result = await sync_draft_from_bc(doc_id, db)
    return result


@router.post("/review-queue/sync-all")
async def sync_all_drafts(limit: int = Query(50, le=200)):
    """
    Batch sync all auto-drafted PIs from BC.
    Detects human edits and feeds corrections back into posting templates.
    """
    db = get_db()
    from services.draft_feedback_service import process_feedback_batch
    result = await process_feedback_batch(db, limit=limit)
    return result


@router.get("/review-queue/{doc_id}/feedback")
async def get_draft_feedback(doc_id: str):
    """
    Get the feedback details for a specific auto-drafted document.
    Shows what changed between the original draft and BC current state.
    """
    db = get_db()
    doc = await db.hub_documents.find_one(
        {"id": doc_id},
        {
            "_id": 0, "id": 1,
            "original_draft_lines": 1,
            "draft_bc_current_lines": 1,
            "draft_bc_sync": 1,
            "draft_bc_corrections": 1,
            "auto_draft_bc_record_no": 1,
            "auto_draft_confidence": 1,
            "bc_vendor_number": 1, "vendor_no": 1,
        }
    )
    if not doc:
        return {"success": False, "error": "Document not found"}

    sync = doc.get("draft_bc_sync") or {}
    return {
        "success": True,
        "doc_id": doc_id,
        "bc_record_no": doc.get("auto_draft_bc_record_no", ""),
        "vendor_no": doc.get("bc_vendor_number") or doc.get("vendor_no", ""),
        "confidence": doc.get("auto_draft_confidence", ""),
        "last_synced": sync.get("synced_at", ""),
        "bc_status": sync.get("bc_status", ""),
        "changes_detected": sync.get("changes_detected", False),
        "changes_summary": sync.get("changes_summary", ""),
        "original_lines": doc.get("original_draft_lines") or [],
        "current_lines": doc.get("draft_bc_current_lines") or [],
        "corrections": doc.get("draft_bc_corrections") or [],
    }



# =============================================================================
# Continuous Learning Engines — On-Demand Trigger & Status
# =============================================================================

@router.post("/learning/run-all")
async def run_all_learning_engines_endpoint():
    """
    Trigger all continuous learning engines on-demand:
    A. Detect posted drafts in BC and learn from final versions
    B. Propagate corrections across similar vendors
    C. Auto-promote/demote vendor confidence based on approval ratio
    """
    db = get_db()
    from services.continuous_learning_service import run_all_learning_engines
    result = await run_all_learning_engines(db)
    return result


@router.post("/learning/detect-posted")
async def detect_posted_drafts_endpoint(limit: int = Query(100, le=500)):
    """Detect auto-drafted PIs that have been posted in BC and learn from them."""
    db = get_db()
    from services.continuous_learning_service import detect_posted_drafts
    return await detect_posted_drafts(db, limit=limit)


@router.post("/learning/cross-vendor")
async def cross_vendor_learning_endpoint(limit: int = Query(20, le=100)):
    """Propagate corrections from one vendor to similar vendors."""
    db = get_db()
    from services.continuous_learning_service import propagate_cross_vendor_learning
    return await propagate_cross_vendor_learning(db, limit=limit)


@router.post("/learning/auto-promote")
async def auto_promote_confidence_endpoint():
    """Auto-promote/demote vendor confidence based on approval ratio."""
    db = get_db()
    from services.continuous_learning_service import auto_promote_confidence
    return await auto_promote_confidence(db)


@router.get("/learning/extraction-profile/{vendor_no}")
async def get_extraction_profile(vendor_no: str):
    """Get the extraction learning profile for a vendor — shows which fields tend to be wrong."""
    db = get_db()
    from services.continuous_learning_service import get_vendor_extraction_profile
    profile = await get_vendor_extraction_profile(db, vendor_no)
    return profile or {"vendor_no": vendor_no, "total_corrections": 0, "field_corrections": {}}



# Track background analysis status
_analysis_status = {"running": False, "last_result": None, "progress": "idle"}


def get_db():
    from server import db
    return db


def get_bc_service():
    from services.business_central_service import get_bc_service as _get
    return _get()


@router.get("/status")
async def get_posting_pattern_status():
    """Get overall posting pattern analysis status with totals."""
    db = get_db()

    total_profiles = await db.posting_pattern_analysis.count_documents({"status": "analyzed"})
    high_conf = await db.posting_pattern_analysis.count_documents({
        "status": "analyzed",
        "posting_template.confidence": "high"
    })
    medium_conf = await db.posting_pattern_analysis.count_documents({
        "status": "analyzed",
        "posting_template.confidence": "medium"
    })
    low_conf = await db.posting_pattern_analysis.count_documents({
        "status": "analyzed",
        "posting_template.confidence": "low"
    })

    # Aggregate totals across all vendors
    totals_pipeline = [
        {"$match": {"status": "analyzed"}},
        {"$group": {
            "_id": None,
            "total_invoices": {"$sum": "$invoices_analyzed"},
            "total_lines": {"$sum": "$lines_analyzed"},
            "total_learning_events": {"$sum": {"$ifNull": ["$continuous_learning_count", 0]}},
            "total_historical": {"$sum": {"$ifNull": ["$data_sources.historical_posted", 0]}},
            "total_current": {"$sum": {"$ifNull": ["$data_sources.purchase_invoices", 0]}},
        }},
    ]
    totals = {"total_invoices": 0, "total_lines": 0, "total_learning_events": 0,
              "total_historical": 0, "total_current": 0}
    async for row in db.posting_pattern_analysis.aggregate(totals_pipeline):
        totals = {
            "total_invoices": row.get("total_invoices", 0),
            "total_lines": row.get("total_lines", 0),
            "total_learning_events": row.get("total_learning_events", 0),
            "total_historical": row.get("total_historical", 0),
            "total_current": row.get("total_current", 0),
        }

    # Get top 10 vendors by invoice count
    top_vendors = await db.posting_pattern_analysis.find(
        {"status": "analyzed"},
        {"_id": 0, "vendor_no": 1, "vendor_names_seen": 1,
         "invoices_analyzed": 1, "lines_analyzed": 1,
         "posting_template.confidence": 1, "posting_template.consistency_score": 1,
         "amount_stats.mean": 1, "continuous_learning_count": 1, "last_learned_at": 1}
    ).sort("invoices_analyzed", -1).limit(10).to_list(10)

    return {
        "total_profiles": total_profiles,
        "totals": totals,
        "confidence_distribution": {
            "high": high_conf,
            "medium": medium_conf,
            "low": low_conf,
        },
        "top_vendors": [
            {
                "vendor_no": v.get("vendor_no"),
                "vendor_name": (v.get("vendor_names_seen") or ["?"])[0] if v.get("vendor_names_seen") else "?",
                "invoices_analyzed": v.get("invoices_analyzed", 0),
                "lines_analyzed": v.get("lines_analyzed", 0),
                "confidence": v.get("posting_template", {}).get("confidence", "?"),
                "consistency": v.get("posting_template", {}).get("consistency_score", 0),
                "avg_amount": v.get("amount_stats", {}).get("mean", 0),
                "continuous_learns": v.get("continuous_learning_count", 0),
                "last_learned": v.get("last_learned_at", ""),
            }
            for v in top_vendors
        ],
    }


@router.get("/vendor/{vendor_no}")
async def get_vendor_posting_profile(vendor_no: str):
    """Get the full posting profile for a specific vendor."""
    db = get_db()
    from services.posting_pattern_analyzer import get_posting_profile_for_vendor

    profile = await get_posting_profile_for_vendor(db, vendor_no)
    if not profile:
        return {"vendor_no": vendor_no, "status": "not_analyzed",
                "message": "No posting profile found. Run POST /analyze/{vendor_no} first."}
    return profile


@router.post("/analyze/{vendor_no}")
async def analyze_single_vendor(vendor_no: str, limit: int = Query(default=0, le=10000, description="0 = fetch ALL invoices (no cap)")):
    """Analyze posting patterns for a single vendor from BC production data. Default: all invoices."""
    db = get_db()
    bc = get_bc_service()

    from services.posting_pattern_analyzer import analyze_vendor_posting_patterns
    result = await analyze_vendor_posting_patterns(db, bc, vendor_no, limit=limit)
    return result


@router.get("/debug-lines/{vendor_no}")
async def debug_invoice_lines(vendor_no: str):
    """
    Debug endpoint: Get one invoice for a vendor and try to fetch its lines.
    Shows exactly what BC returns so we can fix field mapping.
    """
    db = get_db()
    bc = get_bc_service()

    # Get one invoice
    pi_result = await bc.get_posted_purchase_invoices(vendor_id=vendor_no, limit=1)
    invoices = pi_result.get("invoices", [])

    if not invoices:
        return {"error": "No invoices found", "raw_response": pi_result}

    inv = invoices[0]
    inv_id = inv.get("id", "")

    # Show the invoice fields we got
    result = {
        "invoice_sample": inv,
        "invoice_id": inv_id,
        "line_attempts": {},
    }

    # Try to get lines
    lines = await bc.get_purchase_invoice_lines(inv_id)
    result["lines_found"] = len(lines)
    if lines:
        # Show first line with all its fields
        result["line_sample"] = lines[0]
        result["line_fields"] = list(lines[0].keys())
    else:
        result["line_sample"] = None
        result["line_fields"] = []

    return result


async def _run_top_analysis(top_n: int, force: bool = False):
    """
    Background task: discover ALL vendors from BC posted invoices and analyze each.
    No longer limited to Hub-only vendors — goes straight to BC for the complete picture.
    """
    global _analysis_status
    _analysis_status = {"running": True, "last_result": None, "progress": "discovering vendors from BC..."}
    try:
        db = get_db()
        bc = get_bc_service()
        from services.posting_pattern_analyzer import analyze_vendor_posting_patterns

        # Step 1: Discover ALL unique vendors from BC purchase invoices (ALL statuses)
        # AND from historical posted purchase invoices
        _analysis_status["progress"] = "Discovering vendors from ALL BC invoice sources..."
        discovered_vendors = {}
        skip = 0
        page_size = 500

        # Source 1: purchaseInvoices (all statuses — no filter)
        while True:
            pi_result = await bc.get_posted_purchase_invoices(limit=page_size, skip=skip)
            page = pi_result.get("invoices", [])
            if not page:
                break
            for inv in page:
                vno = inv.get("vendorNumber", "")
                if vno:
                    if vno not in discovered_vendors:
                        discovered_vendors[vno] = {
                            "vendor_no": vno,
                            "vendor_name": inv.get("vendorName", ""),
                            "invoice_count": 0,
                        }
                    discovered_vendors[vno]["invoice_count"] = discovered_vendors[vno].get("invoice_count", 0) + 1
            logger.info("[PostingPatterns] Discovery (purchaseInvoices): scanned %d invoices, found %d unique vendors so far",
                         skip + len(page), len(discovered_vendors))
            if len(page) < page_size:
                break
            skip += len(page)
            # Don't stop early — scan ALL invoices to get accurate counts

        # Source 2: historical postedPurchaseInvoices
        skip = 0
        while True:
            hist_result = await bc.get_historical_posted_purchase_invoices(limit=page_size, skip=skip)
            page = hist_result.get("invoices", [])
            source = hist_result.get("source", "none_available")
            if not page or source == "none_available":
                break
            for inv in page:
                vno = inv.get("vendorNumber", "")
                if vno:
                    if vno not in discovered_vendors:
                        discovered_vendors[vno] = {
                            "vendor_no": vno,
                            "vendor_name": inv.get("vendorName", ""),
                            "invoice_count": 0,
                        }
                    discovered_vendors[vno]["invoice_count"] = discovered_vendors[vno].get("invoice_count", 0) + 1
            logger.info("[PostingPatterns] Discovery (historical %s): scanned %d invoices, found %d unique vendors total",
                         source, skip + len(page), len(discovered_vendors))
            if len(page) < page_size:
                break
            skip += len(page)

        # Also include vendors from Hub profiles that might not have BC invoices yet
        hub_vendors = await db.vendor_invoice_profiles.find(
            {"bc_invoice_count": {"$gte": 1}},
            {"_id": 0, "vendor_no": 1, "vendor_name": 1, "bc_invoice_count": 1}
        ).to_list(500)
        for v in hub_vendors:
            vno = v.get("vendor_no", "")
            if vno and vno not in discovered_vendors:
                discovered_vendors[vno] = {
                    **v,
                    "invoice_count": v.get("bc_invoice_count", 0),
                }

        # Sort by invoice count DESC (highest volume vendors first) and limit to top_n
        all_vendors = sorted(discovered_vendors.values(), key=lambda x: x.get("invoice_count", 0), reverse=True)
        if top_n > 0:
            all_vendors = all_vendors[:top_n]

        _analysis_status["progress"] = f"Found {len(all_vendors)} vendors. Starting analysis..."
        logger.info("[PostingPatterns] Discovered %d total vendors (%d from BC, %d from Hub). Analyzing %d.",
                     len(discovered_vendors), len(discovered_vendors) - len(hub_vendors), len(hub_vendors), len(all_vendors))

        results = {
            "vendors_discovered": len(discovered_vendors),
            "vendors_queued": len(all_vendors),
            "analyzed": 0, "errors": 0, "skipped": 0,
            "vendor_details": [], "error_details": [], "force": force,
        }

        for i, v in enumerate(all_vendors):
            vendor_no = v.get("vendor_no", "")
            if not vendor_no:
                continue
            _analysis_status["progress"] = f"Analyzing {vendor_no} ({i+1}/{len(all_vendors)})"

            # Check if recent analysis exists (skip if < 7 days old, unless force=True)
            if not force:
                from datetime import datetime, timezone
                existing = await db.posting_pattern_analysis.find_one(
                    {"vendor_no": vendor_no, "status": "analyzed"},
                    {"_id": 0, "analyzed_at": 1}
                )
                if existing and existing.get("analyzed_at"):
                    try:
                        dt = datetime.fromisoformat(existing["analyzed_at"].replace("Z", "+00:00"))
                        if (datetime.now(timezone.utc) - dt).days < 7:
                            results["skipped"] += 1
                            continue
                    except (ValueError, TypeError):
                        pass

            try:
                analysis = await analyze_vendor_posting_patterns(db, bc, vendor_no)
                if analysis.get("status") == "analyzed":
                    results["analyzed"] += 1
                    results["vendor_details"].append({
                        "vendor_no": vendor_no,
                        "vendor_name": v.get("vendor_name", ""),
                        "invoices": analysis.get("invoices_analyzed", 0),
                        "lines": analysis.get("lines_analyzed", 0),
                        "confidence": analysis.get("posting_template", {}).get("confidence", "?"),
                        "consistency": analysis.get("consistency", {}).get("overall", 0),
                    })
                else:
                    results["errors"] += 1
                    results["error_details"].append({
                        "vendor_no": vendor_no,
                        "vendor_name": v.get("vendor_name", ""),
                        "status": analysis.get("status", "unknown"),
                        "error": analysis.get("error", "unknown"),
                    })
                    logger.warning("Vendor %s analysis status: %s, error: %s",
                                   vendor_no, analysis.get("status"), analysis.get("error", ""))
            except Exception as e:
                results["errors"] += 1
                results["error_details"].append({
                    "vendor_no": vendor_no,
                    "vendor_name": v.get("vendor_name", ""),
                    "error": str(e),
                })
                logger.error("Failed to analyze vendor %s: %s", vendor_no, str(e))

            # Brief pause to avoid BC API throttling
            await asyncio.sleep(0.5)

        _analysis_status = {"running": False, "last_result": results, "progress": "complete"}
        logger.info("[PostingPatterns] Background analysis complete: discovered=%d, analyzed=%d, errors=%d, skipped=%d",
                     results["vendors_discovered"], results["analyzed"], results["errors"], results["skipped"])

    except Exception as e:
        _analysis_status = {"running": False, "last_result": {"error": str(e)}, "progress": "failed"}
        logger.error("[PostingPatterns] Background analysis failed: %s", str(e))


@router.post("/analyze-top")
async def analyze_top_vendors(
    background_tasks: BackgroundTasks,
    top_n: int = Query(default=50, le=500, description="Number of top vendors to analyze (0 = all)"),
    force: bool = Query(default=False, description="Force re-analysis even if recent data exists"),
):
    """
    Analyze posting patterns for the top N vendors by invoice volume.
    Runs in background to avoid nginx timeout. Check progress via GET /analyze-top/status.
    Use force=true to re-analyze all vendors (bypasses 7-day freshness check).
    """
    global _analysis_status
    if _analysis_status.get("running"):
        return {
            "status": "already_running",
            "progress": _analysis_status.get("progress", ""),
            "message": "Analysis is already in progress. Check GET /analyze-top/status for progress.",
        }

    background_tasks.add_task(_run_top_analysis, top_n, force)
    return {
        "status": "started",
        "vendors_to_analyze": top_n,
        "force": force,
        "message": f"Background analysis started for top {top_n} vendors{' (FORCE re-analysis)' if force else ''}. Check GET /api/posting-patterns/analyze-top/status for progress.",
    }


@router.get("/analyze-top/status")
async def get_analysis_status():
    """Check the status of a background analyze-top job."""
    return _analysis_status



@router.get("/learning-activity")
async def get_learning_activity(vendor_no: str = Query("", description="Filter by vendor"), limit: int = Query(20, le=100)):
    """
    Show recent continuous learning events — proof that the system
    learns from every single successful BC posting.
    """
    db = get_db()
    query = {}
    if vendor_no:
        query["vendor_no"] = vendor_no

    events = await db.posting_learning_events.find(
        query,
        {"_id": 0, "vendor_no": 1, "doc_id": 1, "posted_at": 1,
         "line_count": 1, "items_used": 1, "item_families": 1,
         "ref_patterns": 1, "amount": 1}
    ).sort("posted_at", -1).limit(limit).to_list(limit)

    # Count total learning events per vendor
    pipeline = [
        {"$group": {"_id": "$vendor_no", "count": {"$sum": 1}, "last": {"$max": "$posted_at"}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]
    vendor_counts = {}
    async for row in db.posting_learning_events.aggregate(pipeline):
        if row.get("_id"):
            vendor_counts[row["_id"]] = {"events": row["count"], "last_learned": row.get("last", "")}

    return {
        "total_learning_events": await db.posting_learning_events.count_documents({}),
        "recent_events": events,
        "vendors_learning": vendor_counts,
        "description": "Every successful BC posting teaches the system. These events show exactly what was learned.",
    }


@router.get("/learning-proof/{vendor_no}")
async def posting_learning_proof(vendor_no: str):
    """
    Show exactly what the system has learned about how humans post
    invoices for this vendor — and what the auto-post would do.
    """
    db = get_db()

    profile = await db.posting_pattern_analysis.find_one(
        {"vendor_no": vendor_no, "status": "analyzed"},
        {"_id": 0}
    )

    if not profile:
        return {
            "vendor_no": vendor_no,
            "verdict": "NOT LEARNED",
            "message": "No posting analysis exists. Run POST /analyze/{vendor_no} first.",
        }

    template = profile.get("posting_template", {})
    amount = profile.get("amount_stats", {})
    lines = profile.get("line_patterns", {})
    tax = profile.get("tax_pattern", {})
    consistency = profile.get("consistency", {})

    # Build item breakdown with rates
    item_breakdown = {}
    for item, count in lines.get("top_items", {}).items():
        total = sum(lines.get("line_types", {}).values()) or 1
        item_breakdown[item] = f"{round(count / total * 100)}% ({count}/{total} lines)"

    # Describe reference patterns in human terms
    ref_handling = template.get("reference_handling", {})
    ref_patterns_detail = {}
    for pattern, info in (ref_handling.get("all_patterns") or {}).items():
        if isinstance(info, dict):
            ref_patterns_detail[pattern] = f"{info.get('count', 0)} lines ({info.get('rate', 0)*100:.0f}%)"
        else:
            ref_patterns_detail[pattern] = f"{info} lines"

    proof = {
        "vendor_no": vendor_no,
        "vendor_names": profile.get("vendor_names_seen", []),
        "invoices_studied": profile.get("invoices_analyzed", 0),
        "invoices_with_lines_studied": profile.get("invoices_with_lines_analyzed", 0),
        "lines_studied": profile.get("lines_analyzed", 0),
        "data_sources": profile.get("data_sources", {}),
        "status_distribution": profile.get("status_distribution", {}),
        "what_the_system_learned": {
            "typical_invoice_amount": f"${amount.get('mean', 0):,.2f} (range ${amount.get('min', 0):,.2f}-${amount.get('max', 0):,.2f})",
            "typical_line_count": lines.get("lines_per_invoice", {}).get("median", "?"),
            "primary_items": item_breakdown,
            "primary_gl_accounts": list(lines.get("top_gl_accounts", {}).keys())[:5],
            "charge_items": list(lines.get("charge_items", {}).keys())[:5],
            "description_format": ref_handling.get("description", "unknown"),
            "description_pattern_breakdown": ref_patterns_detail,
            "common_descriptions_sample": list(lines.get("top_descriptions", {}).keys())[:5],
            "units_of_measure": list(lines.get("uom_distribution", {}).keys())[:5],
            "line_tax_codes": list(lines.get("tax_code_distribution", {}).keys())[:5],
            "invoice_level_tax": f"{tax.get('tax_rate_typical', 0)}% tax" if tax.get("invoices_with_tax", 0) > 0 else "Tax-free at invoice level",
            "line_tax_code_detail": template.get("line_tax_code", {}),
            "line_amount_stats": lines.get("line_amount_stats", {}),
            "currency": profile.get("currency_distribution", {}),
            "vendor_invoice_number_usage": f"{profile.get('vendor_invoice_number_rate', 0)*100:.0f}%",
        },
        "consistency": {
            "overall_score": f"{consistency.get('overall', 0)*100:.0f}%",
            "dimensions": {
                "line_count": f"{consistency.get('line_count', 0)*100:.0f}% — same # of lines every time",
                "item_family": f"{consistency.get('item_family', 0)*100:.0f}% — always same item FAMILY (e.g., all FREIGHT variants)",
                "item_dominance": f"{consistency.get('item_dominance', 0)*100:.0f}% — one clear primary item within family",
                "line_type": f"{consistency.get('line_type', 0)*100:.0f}% — always same line type (Item/Account/Charge)",
                "ref_pattern_uniformity": f"{consistency.get('ref_pattern_uniformity', 0)*100:.0f}% — same description format every time",
                "ref_coverage": f"{consistency.get('ref_coverage', 0)*100:.0f}% — lines with structured reference #",
                "tax_uniformity": f"{consistency.get('tax_uniformity', 0)*100:.0f}% — always same tax code",
                "uom_uniformity": f"{consistency.get('uom_uniformity', 0)*100:.0f}% — always same unit of measure",
            },
            "item_families_detected": consistency.get("item_families_seen", {}),
            "informational": {
                "exact_item_choice": f"{consistency.get('exact_item_choice', 0)*100:.0f}% — exact same item every time (variants are expected)",
                "amount_tightness": f"{consistency.get('amount_tightness', 0)*100:.0f}% — dollar range tightness (not weighted)",
            },
            "interpretation": (
                "HIGHLY PREDICTABLE — safe for auto-posting"
                if consistency.get("overall", 0) >= 0.8 else
                "MOSTLY PREDICTABLE — good candidate with review"
                if consistency.get("overall", 0) >= 0.6 else
                "VARIABLE — needs human review for each invoice"
                if consistency.get("overall", 0) >= 0.4 else
                "UNPREDICTABLE — not suitable for automation"
            ),
        },
        "auto_post_template": {
            "confidence": template.get("confidence", "?"),
            "consistency_score": template.get("consistency_score", 0),
            "would_create": {
                "currency": template.get("recommended_currency", "USD"),
                "line_count": template.get("typical_line_count", 1),
                "uom": template.get("uom", ""),
                "tax_handling": template.get("tax_handling", "?"),
                "line_tax_code": template.get("line_tax_code", {}),
                "line_templates": template.get("line_templates", []),
                "reference_handling": template.get("reference_handling", {}),
                "description2_usage": template.get("description2_usage", {}),
            },
        },
        "variability_profile": template.get("variability_profile", {}),
        "item_families": consistency.get("item_families_seen", {}),
        "verdict": (
            f"LEARNED ({template.get('confidence', '?').upper()} confidence, "
            f"{consistency.get('overall', 0)*100:.0f}% consistent)"
            if profile.get("invoices_analyzed", 0) >= 3 else "INSUFFICIENT DATA"
        ),
    }

    return proof


# =============================================================================
# Phase 2: Auto-Post Settings, Draft Preview, Ready Queue
# =============================================================================

@router.get("/settings")
async def get_auto_post_settings():
    """Get current auto-post configuration settings."""
    db = get_db()
    settings = await db.auto_post_settings.find_one({"_id": "global"}) or {}
    return {
        "auto_post_enabled": settings.get("auto_post_enabled", False),
        "min_confidence": settings.get("min_confidence", "high"),
        "min_invoices_analyzed": settings.get("min_invoices_analyzed", 10),
        "require_po_match": settings.get("require_po_match", True),
        "allowed_vendors": settings.get("allowed_vendors", []),
        "blocked_vendors": settings.get("blocked_vendors", []),
        "updated_at": settings.get("updated_at", ""),
        "updated_by": settings.get("updated_by", ""),
    }


@router.put("/settings")
async def update_auto_post_settings(
    auto_post_enabled: Optional[bool] = Body(None),
    min_confidence: Optional[str] = Body(None),
    min_invoices_analyzed: Optional[int] = Body(None),
    require_po_match: Optional[bool] = Body(None),
    allowed_vendors: Optional[list] = Body(None),
    blocked_vendors: Optional[list] = Body(None),
):
    """Update auto-post configuration settings."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    update_fields = {"updated_at": now, "updated_by": "admin"}
    if auto_post_enabled is not None:
        update_fields["auto_post_enabled"] = auto_post_enabled
    if min_confidence is not None and min_confidence in ("high", "medium", "low"):
        update_fields["min_confidence"] = min_confidence
    if min_invoices_analyzed is not None:
        update_fields["min_invoices_analyzed"] = max(1, min_invoices_analyzed)
    if require_po_match is not None:
        update_fields["require_po_match"] = require_po_match
    if allowed_vendors is not None:
        update_fields["allowed_vendors"] = allowed_vendors
    if blocked_vendors is not None:
        update_fields["blocked_vendors"] = blocked_vendors

    await db.auto_post_settings.update_one(
        {"_id": "global"},
        {"$set": update_fields},
        upsert=True,
    )

    return {"status": "updated", **update_fields}


@router.get("/ready-queue")
async def get_ready_queue(
    limit: int = Query(50, le=200),
    vendor_no: str = Query("", description="Filter by vendor"),
    confidence: str = Query("", description="Filter by template confidence: high, medium, low"),
):
    """
    List documents that are ReadyForPost with their posting template info.
    This is the queue of invoices ready for auto-posting or manual draft creation.
    """
    db = get_db()

    match_filter = {
        "$or": [
            {"status": "ReadyForPost"},
            {"workflow_status": "ready_for_post"},
        ]
    }
    if vendor_no:
        match_filter["$or"] = [
            {"bc_vendor_number": vendor_no},
            {"vendor_no": vendor_no},
        ]

    docs = await db.hub_documents.find(
        match_filter,
        {
            "_id": 0, "id": 1, "filename": 1, "file_name": 1,
            "doc_type": 1, "suggested_job_type": 1, "document_type": 1,
            "bc_vendor_number": 1, "vendor_no": 1, "vendor_canonical": 1,
            "extracted_fields.invoice_number": 1, "extracted_fields.amount": 1,
            "extracted_fields.invoice_date": 1,
            "normalized_fields.invoice_number": 1, "normalized_fields.amount": 1,
            "suggested_posting_template": 1, "posting_profile_confidence": 1,
            "bc_purchase_invoice": 1, "auto_post_reason": 1,
            "status": 1, "workflow_status": 1, "created_utc": 1,
        }
    ).sort("created_utc", -1).limit(limit).to_list(limit)

    # Enrich with posting profiles
    enriched = []
    for doc in docs:
        v_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""
        profile = None
        if v_no:
            profile = await db.posting_pattern_analysis.find_one(
                {"vendor_no": v_no, "status": "analyzed"},
                {"_id": 0, "posting_template": 1, "invoices_analyzed": 1}
            )

        template = profile.get("posting_template", {}) if profile else (doc.get("suggested_posting_template") or {})
        template_confidence = template.get("confidence", "none")

        # Apply confidence filter
        if confidence and template_confidence != confidence:
            continue

        ef = doc.get("extracted_fields") or {}
        nf = doc.get("normalized_fields") or {}

        enriched.append({
            "id": doc.get("id", ""),
            "filename": doc.get("filename") or doc.get("file_name", ""),
            "vendor_no": v_no,
            "vendor_name": doc.get("vendor_canonical", ""),
            "invoice_number": ef.get("invoice_number") or nf.get("invoice_number", ""),
            "amount": ef.get("amount") or nf.get("amount", ""),
            "invoice_date": ef.get("invoice_date") or nf.get("invoice_date", ""),
            "template_confidence": template_confidence,
            "template_line_count": template.get("typical_line_count", 0),
            "template_gl_accounts": [lt.get("account_number", "") for lt in template.get("line_templates", []) if lt.get("type") == "Account"],
            "has_draft": bool(doc.get("bc_purchase_invoice")),
            "draft_no": (doc.get("bc_purchase_invoice") or {}).get("bc_record_no", ""),
            "status": doc.get("status") or doc.get("workflow_status", ""),
            "created_utc": doc.get("created_utc", ""),
        })

    return {
        "count": len(enriched),
        "documents": enriched,
    }


@router.post("/draft-preview/{doc_id}")
async def preview_draft_pi(doc_id: str):
    """
    Preview what a Draft Purchase Invoice would look like for this document
    using the vendor's posting template. Does NOT create anything in BC.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": "Document not found"}

    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""
    if not vendor_no:
        return {"error": "No vendor number resolved", "doc_id": doc_id}

    # Load posting template
    profile = await db.posting_pattern_analysis.find_one(
        {"vendor_no": vendor_no, "status": "analyzed"},
        {"_id": 0}
    )

    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    template = profile.get("posting_template", {}) if profile else {}

    # Build the preview of what would be created
    invoice_number = ef.get("invoice_number") or nf.get("invoice_number") or ""
    invoice_date = ef.get("invoice_date") or nf.get("invoice_date") or ""
    amount = ef.get("amount") or nf.get("amount") or ""
    po_number = ef.get("po_number") or nf.get("po_number") or doc.get("po_number_clean", "")

    # Build preview lines from template
    preview_lines = []
    if template.get("line_templates"):
        for lt in template["line_templates"]:
            line = {
                "lineType": lt.get("type", "Account"),
                "lineObjectNumber": lt.get("account_number") or lt.get("item_number", ""),
                "description": "",
                "quantity": 1,
                "unitCost": 0,
                "usage_rate": lt.get("usage_rate", 0),
            }
            # Construct description based on reference pattern
            ref_handling = template.get("reference_handling", {})
            ref_pattern = ref_handling.get("pattern", "")
            if ref_pattern == "freight_prefix_plus_ref" and po_number:
                line["description"] = f"FREIGHT {po_number}"
            elif ref_pattern == "bol_in_description" and po_number:
                line["description"] = po_number
            else:
                line["description"] = f"Per invoice {invoice_number}" if invoice_number else "Invoice line"

            # Try to compute amount from extracted total
            try:
                total = float(str(amount).replace("$", "").replace(",", "").strip())
                line["unitCost"] = total
            except (ValueError, TypeError):
                pass

            preview_lines.append(line)
    else:
        # Fallback: single line with total amount
        try:
            total = float(str(amount).replace("$", "").replace(",", "").strip())
        except (ValueError, TypeError):
            total = 0
        preview_lines.append({
            "lineType": "Account",
            "lineObjectNumber": "",
            "description": f"Per invoice {invoice_number}" if invoice_number else "Invoice line",
            "quantity": 1,
            "unitCost": total,
        })

    return {
        "doc_id": doc_id,
        "vendor_no": vendor_no,
        "vendor_name": doc.get("vendor_canonical", ""),
        "template_confidence": template.get("confidence", "none"),
        "invoices_studied": profile.get("invoices_analyzed", 0) if profile else 0,
        "preview": {
            "vendorNumber": vendor_no,
            "vendorInvoiceNumber": invoice_number,
            "invoiceDate": invoice_date,
            "currency": template.get("recommended_currency", "USD"),
            "taxHandling": template.get("tax_handling", "unknown"),
            "lines": preview_lines,
        },
        "template_details": {
            "line_templates": template.get("line_templates", []),
            "reference_handling": template.get("reference_handling", {}),
            "description2_usage": template.get("description2_usage", {}),
        },
        "already_has_draft": bool(doc.get("bc_purchase_invoice")),
        "existing_draft_no": (doc.get("bc_purchase_invoice") or {}).get("bc_record_no", ""),
    }


@router.post("/create-draft/{doc_id}")
async def create_draft_from_template(doc_id: str, force: bool = Query(False)):
    """
    Create a Draft Purchase Invoice in BC using the vendor's posting template.
    This uses the learned posting patterns to build lines that match human behavior.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": "Document not found", "success": False}

    # Check if already has a draft
    existing = doc.get("bc_purchase_invoice")
    if existing and not force:
        return {
            "success": True,
            "already_exists": True,
            "bc_record_no": existing.get("bc_record_no", ""),
            "message": "Draft PI already exists. Use force=true to re-create.",
        }

    # Delegate to existing create_purchase_invoice_from_document
    try:
        from routers.gpi_integration import create_purchase_invoice_from_document
        result = await create_purchase_invoice_from_document(doc_id, vendor_no_override="", force=force)
        return result
    except Exception as e:
        logger.error("Failed to create draft PI for %s: %s", doc_id, str(e))
        return {"success": False, "error": str(e)}


@router.post("/auto-draft-queue")
async def run_auto_draft_queue(limit: int = Query(50, le=200)):
    """
    Process the ReadyForPost queue through the confidence gate.
    Automatically creates DRAFT Purchase Invoices for qualifying documents
    (high-confidence vendor templates, min invoices met, vendor not blocked).

    Safety: Only creates DRAFT PIs. Never posts to the ledger.
    """
    db = get_db()
    from services.ap_auto_post_service import process_auto_draft_queue
    result = await process_auto_draft_queue(db, limit=limit)
    return result


@router.post("/bc-sync-item/{item_number}")
async def sync_item_to_sandbox(
    item_number: str,
    description: str = Query("", description="Item description (auto-detected from Production if blank)"),
):
    """
    Look up an item in BC Production and create it in the Sandbox if missing.
    Ensures template-driven items (like FREIGHT-DS) exist in both environments.
    """
    import httpx
    import os

    BC_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"
    BC_TENANT_ID = os.environ.get("TENANT_ID", "")
    BC_READ_ENV = os.environ.get("BC_READ_ENVIRONMENT") or os.environ.get("BC_ENVIRONMENT", "Production")
    BC_WRITE_ENV = os.environ.get("BC_WRITE_ENVIRONMENT") or os.environ.get("BC_SANDBOX_ENVIRONMENT", "Sandbox_11_3_2025")

    if not BC_TENANT_ID:
        return {"error": "BC credentials not configured"}

    from services.gpi_integration_service import _get_token, _resolve_company_id, REQUEST_TIMEOUT

    token = await _get_token()
    company_id = await _resolve_company_id()

    # Step 1: Check if item already exists in Sandbox
    sandbox_url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENV}/api/v2.0/companies({company_id})/items"
    existing_item_id = None
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.get(sandbox_url, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/json"
        }, params={"$filter": f"number eq '{item_number}'"})
        if resp.status_code == 200:
            existing = resp.json().get("value", [])
            if existing:
                existing_item_id = existing[0].get("id", "")
                if not description:
                    # Item exists but may need updating — delete and re-create with full props
                    etag = existing[0].get("@odata.etag", "")
                    del_url = f"{sandbox_url}({existing_item_id})"
                    del_headers = {
                        "Authorization": f"Bearer {token}",
                        "If-Match": etag or "*",
                    }
                    del_resp = await client.delete(del_url, headers=del_headers)
                    if del_resp.status_code in (200, 204):
                        logger.info("Deleted incomplete item %s from Sandbox for re-sync", item_number)
                    else:
                        return {"status": "already_exists", "item": item_number, "id": existing_item_id,
                                "note": "Item exists. Pass description param to skip re-create."}

    # Step 2: Look up item in Production for its properties
    prod_item = None
    try:
        bc = get_bc_service()
        from services.business_central_service import BC_API_BASE as _base, BC_TENANT_ID as _tid, get_bc_token
        prod_token = await get_bc_token(environment=BC_READ_ENV)
        prod_cid = await bc._get_company_id(environment=BC_READ_ENV)
        prod_url = f"{_base}/{_tid}/{BC_READ_ENV}/api/v2.0/companies({prod_cid})/items"
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(prod_url, headers={
                "Authorization": f"Bearer {prod_token}", "Accept": "application/json"
            }, params={"$filter": f"number eq '{item_number}'"})
            if resp.status_code == 200:
                items = resp.json().get("value", [])
                if items:
                    prod_item = items[0]
    except Exception as e:
        logger.warning("Could not look up item in Production: %s", e)

    item_desc = description or (prod_item.get("displayName", "") if prod_item else item_number)
    item_type = (prod_item.get("type", "Service") if prod_item else "Service")

    # Step 3: Create the item in Sandbox with all relevant properties from Production
    create_payload = {
        "number": item_number,
        "displayName": item_desc,
        "type": item_type,
    }
    # Copy posting group fields from Production item if available
    if prod_item:
        for field in ("generalProductPostingGroupId", "generalProductPostingGroupCode",
                       "inventoryPostingGroupId", "inventoryPostingGroupCode",
                       "itemCategoryCode", "unitOfMeasureCode", "unitOfMeasureId",
                       "taxGroupCode", "taxGroupId", "baseUnitOfMeasureCode",
                       "genProdPostingGroupCode"):
            val = prod_item.get(field)
            if val and val != "00000000-0000-0000-0000-000000000000":
                create_payload[field] = val

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.post(sandbox_url, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }, json=create_payload)

        if resp.status_code in (200, 201):
            created = resp.json()
            created_id = created.get("id", "")

            # Step 4: Copy posting groups from a known working item in Sandbox (e.g. FREIGHT)
            # The standard create may not accept posting group fields directly
            if created_id:
                # Find a reference item that works (FREIGHT or any existing item)
                ref_item_code = os.environ.get("BC_DEFAULT_ITEM_CODE", "FREIGHT")
                ref_resp = await client.get(sandbox_url, headers={
                    "Authorization": f"Bearer {token}", "Accept": "application/json"
                }, params={"$filter": f"number eq '{ref_item_code}'"})
                ref_posting_group = None
                ref_etag = None
                if ref_resp.status_code == 200:
                    ref_items = ref_resp.json().get("value", [])
                    if ref_items:
                        ref_posting_group = ref_items[0].get("generalProductPostingGroupCode", "")

                # Also get the etag for the newly created item
                get_resp = await client.get(f"{sandbox_url}({created_id})", headers={
                    "Authorization": f"Bearer {token}", "Accept": "application/json"
                })
                if get_resp.status_code == 200:
                    ref_etag = get_resp.json().get("@odata.etag", "")

                # PATCH the posting group onto the new item
                if ref_posting_group and ref_etag:
                    patch_resp = await client.patch(
                        f"{sandbox_url}({created_id})",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                            "If-Match": ref_etag,
                        },
                        json={"generalProductPostingGroupCode": ref_posting_group}
                    )
                    if patch_resp.status_code in (200, 204):
                        logger.info("Patched %s with generalProductPostingGroupCode=%s", item_number, ref_posting_group)
                        return {
                            "status": "created",
                            "item": item_number,
                            "id": created_id,
                            "displayName": created.get("displayName", ""),
                            "type": created.get("type", ""),
                            "generalProductPostingGroupCode": ref_posting_group,
                            "source": "cloned_from_production" if prod_item else "created_new",
                            "posting_group_patched": True,
                        }
                    else:
                        pg_err = patch_resp.text[:300]
                        logger.warning("Failed to patch posting group on %s: %s", item_number, pg_err)

            return {
                "status": "created",
                "item": item_number,
                "id": created_id,
                "displayName": created.get("displayName", ""),
                "type": created.get("type", ""),
                "source": "cloned_from_production" if prod_item else "created_new",
                "posting_group_patched": False,
                "warning": "Posting group may need manual setup",
            }
        else:
            try:
                err = resp.json().get("error", {}).get("message", resp.text[:300])
            except Exception:
                err = resp.text[:300]
            return {"status": "error", "item": item_number, "error": err}



@router.get("/auto-draft-eligibility/{doc_id}")
async def check_document_draft_eligibility(doc_id: str):
    """Check if a specific document qualifies for auto-draft PI creation."""
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": "Document not found", "eligible": False}

    from services.ap_auto_post_service import check_auto_draft_eligibility
    eligibility = await check_auto_draft_eligibility(doc, db)
    return eligibility


@router.get("/compare-draft/{draft_no}")
async def compare_draft_vs_production(
    draft_no: str,
    vendor_no: str = Query("", description="Vendor number (auto-detected from draft if blank)"),
    prod_count: int = Query(3, le=10, description="Number of production PIs to compare against"),
):
    """
    Compare an auto-drafted PI (in Sandbox) against actual posted PIs (in Production)
    for the same vendor. Shows header and line-by-line comparison.
    """
    import httpx
    import os

    bc = get_bc_service()
    db = get_db()

    BC_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"
    BC_TENANT_ID = os.environ.get("TENANT_ID", "")
    BC_WRITE_ENV = os.environ.get("BC_WRITE_ENVIRONMENT") or os.environ.get("BC_SANDBOX_ENVIRONMENT", "Sandbox_11_3_2025")
    BC_READ_ENV = os.environ.get("BC_READ_ENVIRONMENT") or os.environ.get("BC_ENVIRONMENT", "Production")

    if not BC_TENANT_ID:
        return {"error": "BC credentials not configured"}

    # Step 1: Fetch the draft PI header from Sandbox by number
    from services.gpi_integration_service import _get_token, _resolve_company_id, REQUEST_TIMEOUT
    token = await _get_token()
    company_id = await _resolve_company_id()

    sandbox_url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENV}/api/v2.0/companies({company_id})/purchaseInvoices"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.get(sandbox_url, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/json"
        }, params={"$filter": f"number eq '{draft_no}'"})
        if resp.status_code != 200:
            return {"error": f"Failed to fetch draft PI {draft_no}: {resp.status_code}", "detail": resp.text[:300]}
        drafts = resp.json().get("value", [])
        if not drafts:
            return {"error": f"Draft PI {draft_no} not found in Sandbox"}
        draft = drafts[0]

    draft_vendor = vendor_no or draft.get("vendorNumber", "")
    draft_system_id = draft.get("id", "")

    # Step 2: Fetch draft PI lines from Sandbox
    draft_lines = []
    if draft_system_id:
        lines_url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENV}/api/v2.0/companies({company_id})/purchaseInvoices({draft_system_id})/purchaseInvoiceLines"
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(lines_url, headers={
                "Authorization": f"Bearer {token}", "Accept": "application/json"
            })
            if resp.status_code == 200:
                draft_lines = resp.json().get("value", [])

    # Step 3: Fetch production PIs for the same vendor
    prod_pis = []
    if draft_vendor:
        result = await bc.get_posted_purchase_invoices(vendor_id=draft_vendor, limit=prod_count)
        prod_invoices = result.get("invoices", [])

        # Also check historical posted
        if len(prod_invoices) < prod_count:
            hist = await bc.get_historical_posted_purchase_invoices(vendor_id=draft_vendor, limit=prod_count)
            prod_invoices.extend(hist.get("invoices", [])[:prod_count - len(prod_invoices)])

        # Fetch lines for each production PI
        for pi in prod_invoices[:prod_count]:
            pi_id = pi.get("id", "")
            pi_lines = []
            if pi_id:
                try:
                    pi_lines = await bc.get_purchase_invoice_lines(pi_id)
                except Exception:
                    pass
            prod_pis.append({
                "number": pi.get("number", ""),
                "vendor_invoice_no": pi.get("vendorInvoiceNumber", ""),
                "invoice_date": pi.get("invoiceDate", ""),
                "status": pi.get("status", ""),
                "total_excl_tax": pi.get("totalAmountExcludingTax", 0),
                "total_incl_tax": pi.get("totalAmountIncludingTax", 0),
                "line_count": len(pi_lines),
                "lines": [
                    {
                        "line_no": l.get("sequence", l.get("lineNo", idx)),
                        "type": l.get("lineObjectNumber", l.get("lineType", "")),
                        "account_no": l.get("accountId", l.get("lineObjectNumber", "")),
                        "description": l.get("description", ""),
                        "quantity": l.get("quantity", 0),
                        "unit_cost": l.get("unitCost", l.get("directUnitCost", 0)),
                        "amount": l.get("totalAmount", l.get("lineAmount", l.get("amount", 0))),
                    }
                    for idx, l in enumerate(pi_lines)
                ],
            })

    # Step 4: Build comparison summary
    draft_summary = {
        "number": draft.get("number", ""),
        "vendor_no": draft_vendor,
        "vendor_name": draft.get("vendorName", ""),
        "vendor_invoice_no": draft.get("vendorInvoiceNumber", ""),
        "invoice_date": draft.get("invoiceDate", ""),
        "posting_date": draft.get("postingDate", ""),
        "status": draft.get("status", "Draft"),
        "total_excl_tax": draft.get("totalAmountExcludingTax", 0),
        "total_incl_tax": draft.get("totalAmountIncludingTax", 0),
        "line_count": len(draft_lines),
        "lines": [
            {
                "line_no": l.get("sequence", l.get("lineNo", idx)),
                "type": l.get("lineObjectNumber", l.get("lineType", "")),
                "account_no": l.get("accountId", l.get("lineObjectNumber", "")),
                "description": l.get("description", ""),
                "quantity": l.get("quantity", 0),
                "unit_cost": l.get("unitCost", l.get("directUnitCost", 0)),
                "amount": l.get("totalAmount", l.get("lineAmount", l.get("amount", 0))),
            }
            for idx, l in enumerate(draft_lines)
        ],
    }

    # Score: how similar is the draft to production patterns?
    match_notes = []
    if prod_pis:
        avg_prod_lines = sum(p["line_count"] for p in prod_pis) / len(prod_pis)
        if draft_summary["line_count"] == 0 and avg_prod_lines > 0:
            match_notes.append(f"Draft has 0 lines but production averages {avg_prod_lines:.0f} lines — lines may not have been added yet")
        elif abs(draft_summary["line_count"] - avg_prod_lines) <= 1:
            match_notes.append(f"Line count matches production (draft={draft_summary['line_count']}, prod avg={avg_prod_lines:.0f})")
        else:
            match_notes.append(f"Line count differs (draft={draft_summary['line_count']}, prod avg={avg_prod_lines:.0f})")

    return {
        "draft": draft_summary,
        "production_samples": prod_pis,
        "production_count": len(prod_pis),
        "vendor_no": draft_vendor,
        "match_notes": match_notes,
    }


@router.get("/vendor-summary")
async def get_vendor_posting_summary(limit: int = Query(50, le=200)):
    """
    Get a summary of all analyzed vendors with their posting profiles,
    document counts, and auto-post readiness.
    """
    db = get_db()

    # All analyzed profiles
    profiles = await db.posting_pattern_analysis.find(
        {"status": "analyzed"},
        {"_id": 0, "vendor_no": 1, "vendor_names_seen": 1, "invoices_analyzed": 1,
         "lines_analyzed": 1, "invoices_with_lines_analyzed": 1,
         "posting_template": 1, "amount_stats": 1, "consistency": 1,
         "analyzed_at": 1, "tax_pattern": 1, "line_patterns": 1}
    ).sort("invoices_analyzed", -1).limit(limit).to_list(limit)

    # Count ready docs per vendor
    pipeline = [
        {"$match": {"$or": [{"status": "ReadyForPost"}, {"workflow_status": "ready_for_post"}]}},
        {"$group": {
            "_id": {"$ifNull": ["$bc_vendor_number", "$vendor_no"]},
            "count": {"$sum": 1},
        }},
    ]
    ready_counts = {}
    async for row in db.hub_documents.aggregate(pipeline):
        if row.get("_id"):
            ready_counts[row["_id"]] = row["count"]

    # Get auto-post settings
    settings = await db.auto_post_settings.find_one({"_id": "global"}) or {}

    vendors = []
    for p in profiles:
        v_no = p.get("vendor_no", "")
        template = p.get("posting_template", {})
        amount_stats = p.get("amount_stats", {})
        line_patterns = p.get("line_patterns", {})
        consistency = p.get("consistency", {})

        vendors.append({
            "vendor_no": v_no,
            "vendor_name": (p.get("vendor_names_seen") or ["?"])[0],
            "invoices_analyzed": p.get("invoices_analyzed", 0),
            "lines_analyzed": p.get("lines_analyzed", 0),
            "invoices_with_lines": p.get("invoices_with_lines_analyzed", 0),
            "confidence": template.get("confidence", "low"),
            "consistency_score": round(consistency.get("overall", 0) * 100),
            "typical_line_count": template.get("typical_line_count", 0),
            "tax_handling": template.get("tax_handling", "unknown"),
            "currency": template.get("recommended_currency", "USD"),
            "avg_amount": amount_stats.get("mean", 0),
            "top_gl_accounts": list(line_patterns.get("top_gl_accounts", {}).keys())[:3],
            "top_items": list(line_patterns.get("top_items", {}).keys())[:3],
            "ready_docs": ready_counts.get(v_no, 0),
            "analyzed_at": p.get("analyzed_at", ""),
            "reference_pattern": template.get("reference_handling", {}).get("pattern", ""),
            "auto_post_eligible": (
                settings.get("auto_post_enabled", False) and
                template.get("confidence", "low") in _confidence_at_or_above(settings.get("min_confidence", "high")) and
                p.get("invoices_analyzed", 0) >= settings.get("min_invoices_analyzed", 10) and
                v_no not in settings.get("blocked_vendors", [])
            ),
        })

    return {
        "count": len(vendors),
        "vendors": vendors,
        "settings": {
            "auto_post_enabled": settings.get("auto_post_enabled", False),
            "min_confidence": settings.get("min_confidence", "high"),
            "min_invoices_analyzed": settings.get("min_invoices_analyzed", 10),
        },
        "ready_total": sum(ready_counts.values()),
    }


def _confidence_at_or_above(min_level: str) -> list:
    """Return confidence levels at or above the given minimum."""
    levels = ["low", "medium", "high"]
    try:
        idx = levels.index(min_level)
        return levels[idx:]
    except ValueError:
        return ["high"]


# =============================================================================
# Invoice Trace: Human vs AI Side-by-Side Comparison
# =============================================================================

@router.get("/trace/{vendor_no}")
async def trace_invoice_comparison(
    vendor_no: str,
    invoice_index: int = Query(0, ge=0, description="Which invoice to trace (0 = most recent)"),
    mode: str = Query("trace", description="'trace' = AI can see human's items (optimistic). 'production' = AI uses only template (realistic)."),
):
    """
    Trace a REAL posted invoice for a vendor from BC Production and compare
    how the human actually posted it vs what our AI template would generate.
    Returns a side-by-side diff with matches, mismatches, and gaps.
    """
    db = get_db()
    bc = get_bc_service()
    import re

    # 1. Load our learned posting template for this vendor
    profile = await db.posting_pattern_analysis.find_one(
        {"vendor_no": vendor_no, "status": "analyzed"},
        {"_id": 0}
    )

    template = profile.get("posting_template", {}) if profile else {}

    # 2. Fetch real invoices from BC for this vendor
    try:
        pi_result = await bc.get_posted_purchase_invoices(
            vendor_id=vendor_no, limit=invoice_index + 5, skip=0
        )
    except Exception as e:
        return {"error": f"Failed to fetch invoices from BC: {str(e)}", "vendor_no": vendor_no}

    invoices = pi_result.get("invoices", [])

    # Also try historical endpoint
    if not invoices or len(invoices) <= invoice_index:
        try:
            hist_result = await bc.get_historical_posted_purchase_invoices(
                vendor_id=vendor_no, limit=invoice_index + 5, skip=0
            )
            hist_invoices = hist_result.get("invoices", [])
            seen = {inv.get("id") for inv in invoices}
            for inv in hist_invoices:
                if inv.get("id") not in seen:
                    invoices.append(inv)
        except Exception:
            pass

    if not invoices:
        return {
            "error": "No invoices found for this vendor in BC",
            "vendor_no": vendor_no,
            "has_profile": bool(profile),
        }

    if invoice_index >= len(invoices):
        return {
            "error": f"Only {len(invoices)} invoices available. Max index: {len(invoices) - 1}",
            "vendor_no": vendor_no,
            "total_available": len(invoices),
        }

    # 3. Get the target invoice and its lines
    invoice = invoices[invoice_index]
    inv_id = invoice.get("id", "")

    try:
        human_lines = await bc.get_purchase_invoice_lines(inv_id)
    except Exception as e:
        human_lines = []
        logger.warning("Failed to get lines for traced invoice %s: %s", inv_id, str(e))

    # 4. Build the "human posted" summary
    human_summary = _build_line_summary(human_lines)

    # 5. Build what our AI template WOULD generate
    # Extract the BOL/reference from what the human actually typed in descriptions
    # (the BOL is NOT the invoice number — it's embedded in the line descriptions)
    human_ref_info = _extract_reference_from_human_lines(human_lines)

    ef = {
        "invoice_number": invoice.get("vendorInvoiceNumber", ""),
        "amount": invoice.get("totalAmountExcludingTax") or invoice.get("totalAmountIncludingTax", 0),
        "invoice_date": invoice.get("invoiceDate", ""),
        "reference_number": human_ref_info.get("ref", ""),
        "detected_pattern": human_ref_info.get("pattern", ""),
    }
    if mode == "trace":
        # Trace mode: AI can see human's structure (optimistic comparison)
        ef["per_line_refs"] = human_ref_info.get("per_line_refs", [])
        ef["trace_human_line_count"] = len(human_lines)
    # else: production mode — AI uses only template, no peeking
    ai_lines = _simulate_template_lines(template, ef)
    ai_summary = _build_line_summary(ai_lines)

    # 6. Compute the diff
    comparison = _compute_trace_diff(human_lines, human_summary, ai_lines, ai_summary, template)

    return {
        "vendor_no": vendor_no,
        "vendor_name": invoice.get("vendorName", ""),
        "mode": mode,
        "invoice_index": invoice_index,
        "total_invoices_available": len(invoices),
        "invoice": {
            "id": inv_id,
            "number": invoice.get("number", ""),
            "vendor_invoice_number": invoice.get("vendorInvoiceNumber", ""),
            "invoice_date": invoice.get("invoiceDate", ""),
            "due_date": invoice.get("dueDate", ""),
            "status": invoice.get("status", ""),
            "total_excl_tax": invoice.get("totalAmountExcludingTax", 0),
            "total_incl_tax": invoice.get("totalAmountIncludingTax", 0),
            "total_tax": invoice.get("totalTaxAmount", 0),
            "currency": invoice.get("currencyCode", "USD"),
        },
        "human_posted": {
            "line_count": len(human_lines),
            "lines": [
                {
                    "line_type": ln.get("lineType", ""),
                    "item_or_account": ln.get("lineObjectNumber", ""),
                    "description": ln.get("description", ""),
                    "description2": ln.get("description2", ""),
                    "quantity": ln.get("quantity", 0),
                    "unit_cost": ln.get("unitCost", 0),
                    "net_amount": ln.get("netAmount") or ln.get("lineAmount", 0),
                    "tax_code": ln.get("taxCode", ""),
                    "uom": ln.get("unitOfMeasureCode", ""),
                }
                for ln in human_lines
            ],
            "summary": human_summary,
        },
        "ai_would_post": {
            "line_count": len(ai_lines),
            "lines": [
                {
                    "line_type": ln.get("lineType", ""),
                    "item_or_account": ln.get("lineObjectNumber", ""),
                    "description": ln.get("description", ""),
                    "quantity": ln.get("quantity", 0),
                    "unit_cost": ln.get("unitCost", 0),
                    "net_amount": ln.get("netAmount", 0),
                    "tax_code": ln.get("taxCode", ""),
                    "uom": ln.get("uom", ""),
                }
                for ln in ai_lines
            ],
            "summary": ai_summary,
            "template_confidence": template.get("confidence", "none"),
            "template_consistency": template.get("consistency_score", 0),
        },
        "comparison": comparison,
        "has_profile": bool(profile),
        "profile_invoices_studied": profile.get("invoices_analyzed", 0) if profile else 0,
    }


@router.get("/trace/{vendor_no}/list")
async def list_traceable_invoices(vendor_no: str, limit: int = Query(20, le=100)):
    """List available invoices for tracing for a vendor."""
    bc = get_bc_service()

    try:
        pi_result = await bc.get_posted_purchase_invoices(vendor_id=vendor_no, limit=limit)
    except Exception as e:
        return {"error": str(e), "vendor_no": vendor_no, "invoices": []}

    invoices = pi_result.get("invoices", [])
    return {
        "vendor_no": vendor_no,
        "count": len(invoices),
        "invoices": [
            {
                "index": i,
                "number": inv.get("number", ""),
                "vendor_invoice_number": inv.get("vendorInvoiceNumber", ""),
                "invoice_date": inv.get("invoiceDate", ""),
                "status": inv.get("status", ""),
                "total": inv.get("totalAmountExcludingTax") or inv.get("totalAmountIncludingTax", 0),
            }
            for i, inv in enumerate(invoices)
        ],
    }


@router.get("/trace/{vendor_no}/batch")
async def batch_trace_invoices(
    vendor_no: str,
    count: int = Query(5, ge=1, le=20, description="Number of invoices to trace"),
    mode: str = Query("trace", description="'trace' = optimistic (AI sees human items). 'production' = realistic (template only)."),
):
    """
    Run the trace comparison across multiple invoices for a vendor and return
    aggregate statistics. This is the key metric — average match rate across
    a sample of invoices tells you how well the template generalizes.
    """
    db = get_db()
    bc = get_bc_service()

    # Load template
    profile = await db.posting_pattern_analysis.find_one(
        {"vendor_no": vendor_no, "status": "analyzed"},
        {"_id": 0}
    )
    template = profile.get("posting_template", {}) if profile else {}

    # Fetch invoices
    try:
        pi_result = await bc.get_posted_purchase_invoices(
            vendor_id=vendor_no, limit=count, skip=0
        )
    except Exception as e:
        return {"error": f"Failed to fetch invoices: {str(e)}", "vendor_no": vendor_no}

    invoices = pi_result.get("invoices", [])
    if not invoices:
        return {"error": "No invoices found", "vendor_no": vendor_no}

    # Run trace for each invoice
    results = []
    dim_totals = {}
    import re

    for idx, invoice in enumerate(invoices[:count]):
        inv_id = invoice.get("id", "")
        try:
            human_lines = await bc.get_purchase_invoice_lines(inv_id)
        except Exception:
            human_lines = []

        if not human_lines:
            results.append({
                "index": idx,
                "number": invoice.get("number", ""),
                "vendor_invoice_number": invoice.get("vendorInvoiceNumber", ""),
                "match_rate": None,
                "note": "No line data",
            })
            continue

        human_summary = _build_line_summary(human_lines)
        human_ref_info = _extract_reference_from_human_lines(human_lines)
        ef = {
            "invoice_number": invoice.get("vendorInvoiceNumber", ""),
            "amount": invoice.get("totalAmountExcludingTax") or invoice.get("totalAmountIncludingTax", 0),
            "invoice_date": invoice.get("invoiceDate", ""),
            "reference_number": human_ref_info.get("ref", ""),
            "detected_pattern": human_ref_info.get("pattern", ""),
        }
        if mode == "trace":
            ef["per_line_refs"] = human_ref_info.get("per_line_refs", [])
            ef["trace_human_line_count"] = len(human_lines)
        ai_lines = _simulate_template_lines(template, ef)
        ai_summary = _build_line_summary(ai_lines)
        comparison = _compute_trace_diff(human_lines, human_summary, ai_lines, ai_summary, template)

        match_rate = comparison.get("match_rate", 0)
        results.append({
            "index": idx,
            "number": invoice.get("number", ""),
            "vendor_invoice_number": invoice.get("vendorInvoiceNumber", ""),
            "match_rate": match_rate,
            "verdict": comparison.get("verdict", ""),
            "line_alignment_avg": comparison.get("line_alignment", {}).get("avg_score", 0),
            "dimension_scores": comparison.get("dimension_scores", {}),
        })

        # Accumulate dimension scores for averaging
        for dim, data in comparison.get("dimension_scores", {}).items():
            if dim not in dim_totals:
                dim_totals[dim] = {"total": 0, "count": 0, "weight": data.get("weight", 0)}
            dim_totals[dim]["total"] += data.get("score", 0)
            dim_totals[dim]["count"] += 1

    # Compute averages
    valid = [r for r in results if r["match_rate"] is not None]
    avg_match = round(sum(r["match_rate"] for r in valid) / max(len(valid), 1)) if valid else 0
    avg_alignment = round(sum(r.get("line_alignment_avg", 0) for r in valid) / max(len(valid), 1)) if valid else 0
    avg_dims = {}
    for dim, data in dim_totals.items():
        avg_dims[dim] = {
            "avg_score": round(data["total"] / max(data["count"], 1)),
            "weight": data["weight"],
        }

    return {
        "vendor_no": vendor_no,
        "vendor_name": (invoices[0].get("vendorName", "") if invoices else ""),
        "mode": mode,
        "invoices_traced": len(valid),
        "invoices_skipped": len(results) - len(valid),
        "avg_match_rate": avg_match,
        "avg_line_alignment": avg_alignment,
        "avg_dimension_scores": avg_dims,
        "per_invoice": results,
        "template_confidence": template.get("confidence", "none"),
        "profile_invoices_studied": profile.get("invoices_analyzed", 0) if profile else 0,
        "verdict": (
            f"STRONG — avg {avg_match}% match across {len(valid)} invoices"
            if avg_match >= 85
            else f"GOOD — avg {avg_match}% match, some dimensions need tuning"
            if avg_match >= 70
            else f"FAIR — avg {avg_match}% match, significant gaps remain"
            if avg_match >= 50
            else f"WEAK — avg {avg_match}% match, template needs more training data"
        ),
    }


def _build_line_summary(lines: list) -> dict:
    """Summarize invoice lines into comparable dimensions."""
    if not lines:
        return {"line_count": 0, "line_types": {}, "items": {}, "gl_accounts": {},
                "descriptions": [], "tax_codes": {}, "uoms": {}, "total_amount": 0}

    from collections import Counter
    line_types = Counter()
    items = Counter()
    gl_accounts = Counter()
    descriptions = []
    tax_codes = Counter()
    uoms = Counter()
    total_amount = 0

    for ln in lines:
        lt = ln.get("lineType", "unknown")
        line_types[lt] += 1
        obj = ln.get("lineObjectNumber") or ln.get("item_or_account", "")
        if obj:
            if lt == "Item":
                items[obj] += 1
            elif lt == "Account":
                gl_accounts[obj] += 1
        desc = ln.get("description", "")
        if desc:
            descriptions.append(desc)
        tc = ln.get("taxCode", "")
        if tc:
            tax_codes[tc] += 1
        uom = ln.get("unitOfMeasureCode") or ln.get("uom", "")
        if uom:
            uoms[uom] += 1
        amt = ln.get("netAmount") or ln.get("lineAmount") or ln.get("unitCost", 0) or 0
        try:
            total_amount += float(amt)
        except (ValueError, TypeError):
            pass

    return {
        "line_count": len(lines),
        "line_types": dict(line_types),
        "items": dict(items),
        "gl_accounts": dict(gl_accounts),
        "descriptions": descriptions,
        "tax_codes": dict(tax_codes),
        "uoms": dict(uoms),
        "total_amount": round(total_amount, 2),
    }


def _extract_reference_from_human_lines(human_lines: list) -> dict:
    """
    Extract BOL/reference numbers from ALL human-posted line descriptions.
    Returns the primary reference, the dominant pattern, AND per-line references
    so multi-product invoices can assign the right description to each AI line.
    """
    import re
    per_line_refs = []  # {"ref", "pattern", "item", "line_idx"}
    pattern_counts = {}

    for idx, line in enumerate(human_lines):
        desc = (line.get("description") or "").strip()
        item = line.get("lineObjectNumber", "")
        if not desc:
            per_line_refs.append({"ref": "", "pattern": "", "item": item, "line_idx": idx, "raw_desc": ""})
            continue
        ref_info = {"ref": "", "pattern": "", "item": item, "line_idx": idx, "raw_desc": desc}

        # "FREIGHT 49785" → freight_prefix_plus_ref
        m = re.match(r'^(?:FREIGHT|FRT|Freight)\s+(.+)', desc, re.IGNORECASE)
        if m:
            ref_info["ref"] = m.group(1).strip()
            ref_info["pattern"] = "freight_prefix_plus_ref"
        # "PO 12345" → po_prefix_plus_ref
        elif re.match(r'^PO[#\s]+(.+)', desc, re.IGNORECASE):
            m = re.match(r'^PO[#\s]+(.+)', desc, re.IGNORECASE)
            ref_info["ref"] = m.group(1).strip()
            ref_info["pattern"] = "po_prefix_plus_ref"
        # "W110700" → order_number_ref
        elif re.match(r'^([A-Z]\d{4,})$', desc.strip(), re.IGNORECASE):
            m = re.match(r'^([A-Z]\d{4,})$', desc.strip(), re.IGNORECASE)
            ref_info["ref"] = m.group(1)
            ref_info["pattern"] = "order_number_ref"
        # Pure number "46133" → bol_in_description
        elif re.match(r'^(\d{4,7})$', desc.strip()):
            ref_info["ref"] = re.match(r'^(\d{4,7})$', desc.strip()).group(1)
            ref_info["pattern"] = "bol_in_description"
        # Embedded reference
        elif re.search(r'(\d{4,7})', desc):
            ref_info["ref"] = re.search(r'(\d{4,7})', desc).group(1)
            ref_info["pattern"] = "embedded_ref"
        # Descriptive text (e.g., "Energy Surcharge", "Z-PALLET", etc.)
        else:
            ref_info["pattern"] = "descriptive_text"

        if ref_info["pattern"] and ref_info["pattern"] != "descriptive_text":
            pattern_counts[ref_info["pattern"]] = pattern_counts.get(ref_info["pattern"], 0) + 1

        per_line_refs.append(ref_info)

    # Determine the dominant reference and pattern
    primary_ref = ""
    primary_pattern = ""
    if pattern_counts:
        primary_pattern = max(pattern_counts, key=pattern_counts.get)
    # Use the first ref that matches the dominant pattern (or first ref found)
    for plr in per_line_refs:
        if plr["ref"]:
            if not primary_ref:
                primary_ref = plr["ref"]
            if plr["pattern"] == primary_pattern:
                primary_ref = plr["ref"]
                break

    return {
        "ref": primary_ref,
        "pattern": primary_pattern,
        "per_line_refs": per_line_refs,
        "all_unique_refs": list({plr["ref"] for plr in per_line_refs if plr["ref"]}),
    }


def _simulate_template_lines(template: dict, extracted_fields: dict) -> list:
    """
    Simulate what the AI would generate using the posting template.

    Key rules:
    - Respect typical_line_count — emit that many lines
    - Single-line vendors: primary items only (simple freight pattern)
    - Multi-line vendors: emit ALL structural items with proper descriptions,
      quantities, and amounts from the learned metadata
    - Use the BOL/reference number (not invoice number) for freight patterns
    - Add Comment line placeholders where the template shows them
    """
    if not template or not template.get("line_templates"):
        # No template — fallback single line
        try:
            amount = float(str(extracted_fields.get("amount", 0)).replace("$", "").replace(",", "").strip())
        except (ValueError, TypeError):
            amount = 0
        return [{
            "lineType": "Account",
            "lineObjectNumber": "",
            "description": f"Per invoice {extracted_fields.get('invoice_number', '')}",
            "quantity": 1,
            "unitCost": amount,
            "netAmount": amount,
            "taxCode": "",
            "uom": template.get("uom", ""),
        }]

    invoice_number = extracted_fields.get("invoice_number", "")
    reference_number = extracted_fields.get("reference_number", "") or invoice_number
    try:
        total_amount = float(str(extracted_fields.get("amount", 0)).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        total_amount = 0

    ref_handling = template.get("reference_handling", {})
    # Use the pattern detected from the human's actual line if available (trace mode),
    # otherwise fall back to the template's dominant pattern
    ref_pattern = extracted_fields.get("detected_pattern", "") or ref_handling.get("pattern", "")
    line_tax = template.get("line_tax_code", {})
    typical_count = int(template.get("typical_line_count", 1) or 1)
    all_templates = template.get("line_templates", [])

    per_line_refs = extracted_fields.get("per_line_refs", None)
    trace_human_count = extracted_fields.get("trace_human_line_count", 0)

    # --- Single-line vendors: primary only, simple pattern ---
    # BUT: in trace mode, if the human used more lines, go multi-line instead
    # ALSO: if the vendor has high-presence surcharges, bump to multi-line
    has_high_presence_surcharges = any(
        lt.get("slot_type") == "surcharge" and lt.get("invoice_presence_rate", 0) >= 0.50
        for lt in all_templates
    )
    effective_typical = typical_count
    if has_high_presence_surcharges and typical_count <= 1:
        # Surcharges with ≥50% presence should always be emitted alongside the primary
        surcharge_count = sum(
            1 for lt in all_templates
            if lt.get("slot_type") == "surcharge" and lt.get("invoice_presence_rate", 0) >= 0.50
        )
        effective_typical = max(typical_count, 1 + surcharge_count)

    if effective_typical <= 1 and trace_human_count <= 1:
        eligible = [lt for lt in all_templates if lt.get("rank") == "primary"]
        if not eligible:
            eligible = sorted(all_templates, key=lambda x: x.get("usage_rate", 0), reverse=True)[:1]
        eligible = eligible[:1]
        return _build_lines_from_templates(
            eligible, total_amount, ref_pattern, reference_number,
            invoice_number, line_tax, template, single_line=True,
            per_line_refs=per_line_refs,
        )

    # --- Multi-line vendors: emit structural skeleton + product slots ---
    # Categorize template items by their structural role
    structural = []  # Always present, always the same (zero-cost or constant)
    surcharges = []  # Always present, small variable cost
    product_candidates = []  # Variable product lines (SKU changes per order)
    other = []  # Everything else

    for lt in all_templates:
        st = lt.get("slot_type", "unknown")
        if st in ("structural_zero", "structural_constant"):
            structural.append(lt)
        elif st == "surcharge":
            surcharges.append(lt)
        elif st in ("variable_product", "structural_variable"):
            product_candidates.append(lt)
        else:
            other.append(lt)

    # Build the line list:
    # 1. All structural items (packaging, tracking — always present)
    # 2. All surcharges (energy, freight surcharges)
    # 3. Product slots — selection depends on mode:
    #    TRACE MODE: Use the human's actual product item(s) from this invoice
    #    PRODUCTION MODE: Use co-occurrence/alternate heuristic
    # 4. Fill remaining with other frequent items or comments
    selected = []
    selected.extend(structural)
    selected.extend(surcharges)

    trace_human_count = extracted_fields.get("trace_human_line_count", 0)
    comment_slots_needed = 0
    per_line_refs = extracted_fields.get("per_line_refs", [])

    if trace_human_count > 0 and per_line_refs:
        # --- TRACE MODE: Use the human's actual items for product slots ---
        # Instead of guessing which product SKU to use, look at what the human actually
        # used and find it in our template. This prevents adding wrong alternates.
        selected_ids = {(lt.get("item_number") or lt.get("account_number", "")) for lt in selected}
        human_items = [plr.get("item", "") for plr in per_line_refs]

        for h_item in human_items:
            if not h_item:
                comment_slots_needed += 1
                continue
            if h_item in selected_ids:
                continue
            # Find this item in template
            match = next(
                (lt for lt in all_templates
                 if (lt.get("item_number") or lt.get("account_number", "")) == h_item
                 and lt not in selected),
                None,
            )
            if match:
                selected.append(match)
                selected_ids.add(h_item)
            # If not in template, it's a genuine gap — don't substitute with wrong item
    else:
        # --- PRODUCTION MODE: probabilistic selection ---
        # Split product candidates by co-occurrence pattern
        co_occurring = [p for p in product_candidates if p.get("invoice_presence_rate", 0) >= 0.50]
        alternates = [p for p in product_candidates if p.get("invoice_presence_rate", 0) < 0.50]

        selected.extend(co_occurring)  # Include ALL high-presence items
        if alternates and len(selected) < typical_count:
            selected.append(alternates[0])  # Include at most 1 alternate

        # If no product candidates, try non-zero optional items
        if not co_occurring and not alternates and len(selected) < typical_count:
            non_zero_others = [o for o in other if not o.get("is_zero_cost", False)]
            if non_zero_others:
                selected.append(non_zero_others[0])

    # Add zero-cost optional items (like Z-POP) as structural fillers
    if len(selected) < max(effective_typical, trace_human_count):
        zero_others = [o for o in other if o.get("is_zero_cost", False) and o not in selected]
        for zo in zero_others:
            if len(selected) >= max(effective_typical, trace_human_count):
                break
            selected.append(zo)

    # Cap at target count
    target_count = max(effective_typical, trace_human_count - comment_slots_needed) if trace_human_count > 0 else effective_typical
    selected = selected[:target_count]

    lines = _build_lines_from_templates(
        selected, total_amount, ref_pattern, reference_number,
        invoice_number, line_tax, template, single_line=False,
        per_line_refs=per_line_refs,
    )

    # Add Comment line placeholders if the vendor typically uses them
    # In trace mode, match the actual number of comment lines from the human invoice
    comment_info = template.get("comment_lines", {})
    typical_comments = comment_info.get("typical_count", 0)
    trace_comment_count = comment_slots_needed if trace_human_count > 0 else 0
    target_comments = max(typical_comments, trace_comment_count)
    if target_comments > 0:
        target_total = max(effective_typical, trace_human_count)
        room = target_total - len(lines)
        top_descs = comment_info.get("top_descriptions", [])
        for i in range(min(target_comments, room)):
            lines.append({
                "lineType": "Comment",
                "lineObjectNumber": "",
                "description": top_descs[i] if i < len(top_descs) else "",
                "quantity": 0,
                "unitCost": 0,
                "netAmount": 0,
                "taxCode": "",
                "uom": "",
            })

    return lines


def _build_lines_from_templates(
    templates, total_amount, ref_pattern, reference_number,
    invoice_number, line_tax, full_template, single_line=False,
    per_line_refs=None,
):
    """
    Build simulated lines from template entries with proper metadata.

    Key improvement: each line gets the RIGHT description based on its structural role:
    - Zero-cost structural items → always use common_description (e.g., "Z-PALLET")
    - Surcharge items → use common_description (e.g., "Energy Surcharge")
    - Primary/variable product → use reference-based description
    - Multi-product: distribute per-line refs across variable product slots
    """
    import re as _re
    lines = []

    # Separate value-carrying items from zero-cost structural items
    value_items = [t for t in templates if not t.get("is_zero_cost", False)]

    # Calculate known surcharge amounts (small-value items like ENERGY-DS)
    # The PRIMARY value carrier is the one with the highest typical cost
    if len(value_items) > 1:
        value_items_sorted = sorted(value_items, key=lambda x: x.get("typical_unit_cost", 0) * max(x.get("typical_qty", 1), 1), reverse=True)
        primary_value = value_items_sorted[0]
        surcharge_total = sum(
            (v.get("typical_unit_cost", 0) or 0) * max(v.get("typical_qty", 1), 1)
            for v in value_items_sorted[1:]
        )
    elif value_items:
        primary_value = value_items[0]
        surcharge_total = 0
    else:
        primary_value = None
        surcharge_total = 0

    # Primary product line gets: total_amount - surcharges
    primary_amount = max(total_amount - surcharge_total, 0)

    # For multi-product invoices: try to match AI template items to human line refs
    # This allows each variable_product line to get the correct description from
    # the human's actual line for that item (trace accuracy improvement)
    item_to_human_desc = {}
    if per_line_refs:
        for plr in per_line_refs:
            item_key = plr.get("item", "")
            if item_key and plr.get("raw_desc"):
                item_to_human_desc[item_key] = plr["raw_desc"]

    # Track which variable product slots get references (for multi-product)
    variable_slot_idx = 0
    all_refs = list({plr.get("ref", "") for plr in (per_line_refs or []) if plr.get("ref")}) if per_line_refs else []

    for lt in templates:
        is_zero = lt.get("is_zero_cost", False)
        is_primary = (lt is primary_value) if primary_value else (lt == templates[0])
        slot_type = lt.get("slot_type", "unknown")

        # Use the metadata-enriched description if available
        common_desc = lt.get("common_description", "")
        has_variable_desc = lt.get("unique_descriptions", 0) > 10
        item_id = lt.get("account_number") or lt.get("item_number", "")

        # === DESCRIPTION LOGIC ===
        # Priority hierarchy depends on the STRUCTURAL ROLE of the line:
        #
        # 1. Zero-cost structural items (Z-PALLET, Z-POP) → ALWAYS use common_description
        #    These items have a fixed, known name. The reference doesn't apply to them.
        #
        # 2. Surcharge items (ENERGY-DS, etc.) → ALWAYS use common_description
        #    These are known, named charges. They don't carry the BOL/PO reference.
        #
        # 3. Primary/variable product lines → use reference-based description
        #    This is where the BOL, PO#, order number goes.
        #
        # 4. In trace mode, if we have the human's actual description for this item,
        #    use it directly (highest fidelity match).

        if is_zero:
            # STRUCTURAL ZERO — always use the known item description
            desc = common_desc or item_id or "—"
        elif slot_type == "surcharge":
            # SURCHARGE — always use the known surcharge description
            desc = common_desc or item_id or "Surcharge"
        elif slot_type in ("structural_constant",):
            # STRUCTURAL CONSTANT — fixed known line
            desc = common_desc or item_id or "—"
        else:
            # VARIABLE / PRIMARY — this line carries the reference
            # In trace mode, try to match to the human's exact description for this item
            human_exact = item_to_human_desc.get(item_id, "")
            if human_exact:
                desc = human_exact
            elif reference_number:
                ref = reference_number
                # For multi-product: try to assign different refs to different variable slots
                if len(all_refs) > 1 and variable_slot_idx < len(all_refs):
                    ref = all_refs[variable_slot_idx]
                if ref_pattern == "freight_prefix_plus_ref":
                    desc = f"Freight {ref}"
                elif ref_pattern == "po_prefix_plus_ref":
                    desc = f"PO {ref}"
                else:
                    desc = ref
            elif has_variable_desc and common_desc:
                desc = common_desc
            elif common_desc:
                desc = common_desc
            else:
                desc = f"Per invoice {invoice_number}" if invoice_number else "Invoice line"
            variable_slot_idx += 1

        # === AMOUNT LOGIC ===
        if is_zero:
            line_amount = 0
            line_qty = lt.get("typical_qty", 1) or 1
            line_unit_cost = 0
        elif is_primary:
            # Primary value carrier gets total minus surcharges
            line_amount = round(primary_amount, 2)
            line_qty = lt.get("typical_qty", 1) or 1
            line_unit_cost = round(line_amount / max(line_qty, 1), 5) if line_qty else line_amount
        else:
            # Surcharge / secondary value item — use typical cost
            typical_cost = lt.get("typical_unit_cost", 0) or 0
            line_qty = lt.get("typical_qty", 1) or 1
            line_unit_cost = typical_cost
            line_amount = round(line_qty * typical_cost, 2)

        line = {
            "lineType": lt.get("type", "Item"),
            "lineObjectNumber": item_id,
            "description": desc,
            "quantity": line_qty,
            "unitCost": line_unit_cost if not is_zero else 0,
            "netAmount": line_amount,
            "taxCode": lt.get("tax_code", "") or line_tax.get("code", ""),
            "uom": lt.get("uom", "") or full_template.get("uom", ""),
        }
        lines.append(line)

    return lines


def _compute_trace_diff(human_lines, human_summary, ai_lines, ai_summary, template) -> dict:
    """
    Compute a WEIGHTED, multi-dimensional comparison between human and AI postings.

    Instead of binary match/mismatch counting (which gives coarse 14%-per-dimension jumps),
    each dimension gets a 0.0–1.0 score and a weight. The overall match_rate is the
    weighted average × 100.

    Dimensions and weights:
      - Items/GL accounts (25%): Jaccard with item-family partial credit
      - Total amount (20%): Tolerance-based (±1% = 1.0, ±5% = 0.8, etc.)
      - Description pattern (20%): Normalized comparison per-line
      - Line count (10%): Partial credit for close counts
      - Line type (10%): Dominant type match
      - Tax code (10%): Match/no-match
      - UOM (5%): Match/no-match

    Also includes LINE-BY-LINE ALIGNMENT showing which AI line pairs with which
    human line and how well each pair matches.
    """
    import re as _re

    matches = []
    mismatches = []
    gaps = []
    dim_scores = {}

    # --- Helper: extract item family ---
    def _item_family(item_no: str) -> str:
        m = _re.match(r'^([A-Z]+(?:-[A-Z]+)*?)(?:-(DS|WH|IN|OUT|INTL?))?$', item_no, _re.IGNORECASE)
        if m:
            return m.group(1).upper()
        m = _re.match(r'^([A-Z]+)', item_no, _re.IGNORECASE)
        return m.group(1).upper() if m else item_no.upper()

    # --- Helper: normalize description for comparison ---
    def _norm_desc(desc: str) -> str:
        return _re.sub(r'\s+', ' ', desc.strip().upper())

    # --- Helper: extract numeric reference from description ---
    def _desc_ref(desc: str) -> str:
        m = _re.search(r'(\d{4,7})', desc)
        return m.group(1) if m else ""

    # --- Helper: description prefix pattern ---
    def _desc_prefix(desc: str) -> str:
        upper = desc.strip().upper()
        for prefix in ["FREIGHT", "FRT", "PO", "INV"]:
            if upper.startswith(prefix):
                return prefix
        if _re.match(r'^\d{4,7}$', upper):
            return "NUMERIC_REF"
        if _re.match(r'^[A-Z]\d{4,}$', upper):
            return "ORDER_REF"
        return "TEXT"

    # ========== 1. LINE COUNT (weight: 0.10) ==========
    h_count = human_summary.get("line_count", 0)
    a_count = ai_summary.get("line_count", 0)
    if h_count == a_count:
        lc_score = 1.0
        matches.append({"dimension": "Line Count", "value": str(h_count), "verdict": "MATCH"})
    else:
        diff = abs(h_count - a_count)
        lc_score = max(0, 1.0 - (diff * 0.3))  # -30% per line off
        verdict = "CLOSE" if diff <= 1 else "MISMATCH"
        mismatches.append({
            "dimension": "Line Count", "human": str(h_count), "ai": str(a_count),
            "verdict": verdict, "note": f"Off by {diff} line{'s' if diff > 1 else ''}",
        })
    dim_scores["line_count"] = {"score": round(lc_score, 3), "weight": 0.10}

    # ========== 2. LINE TYPE (weight: 0.10) ==========
    h_types = human_summary.get("line_types", {})
    a_types = ai_summary.get("line_types", {})
    dominant_h = max(h_types, key=h_types.get) if h_types else "none"
    dominant_a = max(a_types, key=a_types.get) if a_types else "none"
    if dominant_h == dominant_a:
        lt_score = 1.0
        matches.append({"dimension": "Line Type", "value": dominant_h, "verdict": "MATCH"})
    else:
        lt_score = 0.2
        mismatches.append({
            "dimension": "Line Type", "human": str(h_types), "ai": str(a_types), "verdict": "MISMATCH",
        })
    dim_scores["line_type"] = {"score": round(lt_score, 3), "weight": 0.10}

    # ========== 3. ITEMS/GL ACCOUNTS (weight: 0.25) — Jaccard + family credit ==========
    h_items = set(human_summary.get("items", {}).keys())
    h_gls = set(human_summary.get("gl_accounts", {}).keys())
    a_items = set(ai_summary.get("items", {}).keys())
    a_gls = set(ai_summary.get("gl_accounts", {}).keys())
    h_all = h_items | h_gls
    a_all = a_items | a_gls

    exact_common = h_all & a_all
    h_only = h_all - a_all
    a_only = a_all - h_all

    # Family matching for remaining items
    family_matches_list = []
    h_remaining = set(h_only)
    a_remaining = set(a_only)
    for h_item in sorted(h_remaining):
        h_fam = _item_family(h_item)
        for a_item in sorted(a_remaining):
            if _item_family(a_item) == h_fam:
                family_matches_list.append(f"{h_item}~{a_item}")
                h_remaining.discard(h_item)
                a_remaining.discard(a_item)
                break

    total_unique = len(h_all | a_all) or 1
    # Exact matches count as 1.0, family matches as 0.85, unmatched as 0
    item_score_numerator = len(exact_common) * 1.0 + len(family_matches_list) * 0.85
    items_score = round(item_score_numerator / total_unique, 3)

    if exact_common:
        matches.append({"dimension": "Items/GL Accounts", "value": ", ".join(sorted(exact_common)), "verdict": "MATCH"})
    if family_matches_list:
        matches.append({
            "dimension": "Items (Same Family)", "value": ", ".join(family_matches_list),
            "verdict": "MATCH", "note": "Same item family, different routing variant",
        })
    if h_remaining:
        mismatches.append({
            "dimension": "Items/GL (Human Only)", "human": ", ".join(sorted(h_remaining)),
            "ai": "—", "verdict": "GAP",
            "note": "Human used these but AI template doesn't include them",
        })
    if a_remaining:
        mismatches.append({
            "dimension": "Items/GL (AI Only)", "human": "—",
            "ai": ", ".join(sorted(a_remaining)), "verdict": "GAP",
            "note": "AI template includes these but human didn't use them on this invoice",
        })
    dim_scores["items_gl"] = {"score": items_score, "weight": 0.25}

    # ========== 4. DESCRIPTION PATTERN (weight: 0.20) ==========
    h_descs = human_summary.get("descriptions", [])
    a_descs = ai_summary.get("descriptions", [])
    if h_descs and a_descs:
        # Compare the dominant pattern AND the reference content
        h_prefixes = [_desc_prefix(d) for d in h_descs]
        a_prefixes = [_desc_prefix(d) for d in a_descs]
        h_dom = max(set(h_prefixes), key=h_prefixes.count) if h_prefixes else ""
        a_dom = max(set(a_prefixes), key=a_prefixes.count) if a_prefixes else ""

        pattern_match = (h_dom == a_dom)
        # Check reference match on primary lines (ignoring zero-cost lines)
        h_refs = [_desc_ref(d) for d in h_descs if _desc_ref(d)]
        a_refs = [_desc_ref(d) for d in a_descs if _desc_ref(d)]
        ref_match = bool(h_refs and a_refs and set(h_refs) & set(a_refs))

        # Also check for case-insensitive exact matches on non-empty descriptions
        exact_desc_matches = sum(
            1 for hd in h_descs for ad in a_descs
            if _norm_desc(hd) == _norm_desc(ad)
        )

        if pattern_match and ref_match:
            desc_score = 1.0
            matches.append({
                "dimension": "Description Pattern",
                "value": f"Both use '{h_dom}' pattern with matching reference",
                "verdict": "MATCH",
                "human_example": h_descs[0][:60],
                "ai_example": a_descs[0][:60],
            })
        elif exact_desc_matches > 0:
            desc_score = 0.9
            matches.append({
                "dimension": "Description",
                "value": f"{exact_desc_matches} exact description match(es)",
                "verdict": "MATCH",
            })
        elif pattern_match:
            desc_score = 0.7
            matches.append({
                "dimension": "Description Pattern",
                "value": f"Both use '{h_dom}' pattern (refs differ)",
                "verdict": "MATCH",
                "note": "Same structural pattern but different reference content",
            })
        elif ref_match:
            desc_score = 0.5
            mismatches.append({
                "dimension": "Description Pattern",
                "human": f"{h_dom}: {h_descs[0][:40]}",
                "ai": f"{a_dom}: {a_descs[0][:40]}",
                "verdict": "CLOSE",
                "note": "Same reference number but different formatting pattern",
            })
        else:
            desc_score = 0.1
            mismatches.append({
                "dimension": "Description Pattern",
                "human": h_descs[0][:60] if h_descs else "—",
                "ai": a_descs[0][:60] if a_descs else "—",
                "verdict": "MISMATCH",
            })
    elif not h_descs and not a_descs:
        desc_score = 1.0
    else:
        desc_score = 0.0
        gaps.append({"dimension": "Description", "note": "One side has descriptions, the other doesn't"})
    dim_scores["description"] = {"score": round(desc_score, 3), "weight": 0.20}

    # ========== 5. TAX CODE (weight: 0.10) ==========
    h_tax = human_summary.get("tax_codes", {})
    a_tax = ai_summary.get("tax_codes", {})
    if h_tax and a_tax:
        h_top_tax = max(h_tax, key=h_tax.get)
        a_top_tax = max(a_tax, key=a_tax.get)
        if h_top_tax == a_top_tax:
            tax_score = 1.0
            matches.append({"dimension": "Tax Code", "value": h_top_tax, "verdict": "MATCH"})
        else:
            tax_score = 0.0
            mismatches.append({
                "dimension": "Tax Code", "human": h_top_tax, "ai": a_top_tax, "verdict": "MISMATCH",
            })
    elif h_tax and not a_tax:
        tax_score = 0.0
        gaps.append({"dimension": "Tax Code", "note": f"Human used {list(h_tax.keys())} but AI has no tax code"})
    elif not h_tax and not a_tax:
        tax_score = 1.0
        matches.append({"dimension": "Tax Code", "value": "None (both)", "verdict": "MATCH"})
    else:
        tax_score = 0.5  # AI has tax code, human doesn't — partial
    dim_scores["tax_code"] = {"score": round(tax_score, 3), "weight": 0.10}

    # ========== 6. UOM (weight: 0.05) ==========
    h_uom = human_summary.get("uoms", {})
    a_uom = ai_summary.get("uoms", {})
    if h_uom and a_uom:
        h_top_uom = max(h_uom, key=h_uom.get)
        a_top_uom = max(a_uom, key=a_uom.get)
        if h_top_uom == a_top_uom:
            uom_score = 1.0
            matches.append({"dimension": "UOM", "value": h_top_uom, "verdict": "MATCH"})
        else:
            uom_score = 0.0
            mismatches.append({"dimension": "UOM", "human": h_top_uom, "ai": a_top_uom, "verdict": "MISMATCH"})
    elif not h_uom and not a_uom:
        uom_score = 1.0
    else:
        uom_score = 0.3
    dim_scores["uom"] = {"score": round(uom_score, 3), "weight": 0.05}

    # ========== 7. TOTAL AMOUNT (weight: 0.20) ==========
    h_amt = human_summary.get("total_amount", 0)
    a_amt = ai_summary.get("total_amount", 0)
    if h_amt > 0 and a_amt > 0:
        diff_pct = abs(h_amt - a_amt) / max(h_amt, 1) * 100
        if diff_pct < 1:
            amt_score = 1.0
            matches.append({"dimension": "Total Amount", "value": f"${h_amt:,.2f}", "verdict": "MATCH"})
        elif diff_pct < 5:
            amt_score = 0.85
            mismatches.append({
                "dimension": "Total Amount", "human": f"${h_amt:,.2f}", "ai": f"${a_amt:,.2f}",
                "verdict": "CLOSE", "note": f"{diff_pct:.1f}% difference",
            })
        elif diff_pct < 15:
            amt_score = 0.5
            mismatches.append({
                "dimension": "Total Amount", "human": f"${h_amt:,.2f}", "ai": f"${a_amt:,.2f}",
                "verdict": "MISMATCH", "note": f"{diff_pct:.1f}% difference",
            })
        else:
            amt_score = 0.1
            mismatches.append({
                "dimension": "Total Amount", "human": f"${h_amt:,.2f}", "ai": f"${a_amt:,.2f}",
                "verdict": "MISMATCH", "note": f"{diff_pct:.1f}% difference",
            })
    elif h_amt == 0 and a_amt == 0:
        amt_score = 1.0
        matches.append({"dimension": "Total Amount", "value": "$0.00", "verdict": "MATCH"})
    else:
        amt_score = 0.0
    dim_scores["amount"] = {"score": round(amt_score, 3), "weight": 0.20}

    # ========== OVERALL WEIGHTED SCORE ==========
    total_weight = sum(d["weight"] for d in dim_scores.values())
    match_rate = round(
        sum(d["score"] * d["weight"] for d in dim_scores.values()) / max(total_weight, 0.01) * 100
    )

    # ========== LINE-BY-LINE ALIGNMENT ==========
    line_alignment = _align_lines(human_lines, ai_lines)

    return {
        "match_rate": match_rate,
        "total_dimensions": len(dim_scores),
        "dimension_scores": {k: {"score": round(v["score"] * 100), "weight": round(v["weight"] * 100)} for k, v in dim_scores.items()},
        "matches": matches,
        "mismatches": mismatches,
        "gaps": gaps,
        "line_alignment": line_alignment,
        "verdict": (
            "EXCELLENT — AI closely replicates human behavior" if match_rate >= 85
            else "GOOD — AI captures most patterns, minor gaps" if match_rate >= 70
            else "FAIR — AI captures core structure, some differences" if match_rate >= 50
            else "NEEDS WORK — Significant differences between human and AI" if match_rate >= 30
            else "POOR — AI template doesn't match human posting behavior"
        ),
    }


def _align_lines(human_lines: list, ai_lines: list) -> dict:
    """
    Line-by-line alignment: pair each AI line with the best-matching human line.

    Uses greedy matching with multi-factor scoring:
      - Item/GL exact match: +0.35
      - Item/GL family match: +0.25
      - Same line type: +0.10
      - Description similarity: +0.25
      - Amount closeness: +0.20
      - Same tax code: +0.05
      - Same UOM: +0.05

    Returns per-pair scores and an average alignment score.
    """
    import re as _re

    def _item_family(item_no: str) -> str:
        m = _re.match(r'^([A-Z]+(?:-[A-Z]+)*?)(?:-(DS|WH|IN|OUT|INTL?))?$', item_no, _re.IGNORECASE)
        if m:
            return m.group(1).upper()
        m = _re.match(r'^([A-Z]+)', item_no, _re.IGNORECASE)
        return m.group(1).upper() if m else item_no.upper()

    def _desc_sim(d1: str, d2: str) -> float:
        """0-1 description similarity."""
        d1n = _re.sub(r'\s+', ' ', d1.strip().upper())
        d2n = _re.sub(r'\s+', ' ', d2.strip().upper())
        if d1n == d2n:
            return 1.0
        # Check if same prefix pattern
        p1 = d1n.split()[0] if d1n else ""
        p2 = d2n.split()[0] if d2n else ""
        if p1 == p2 and p1:
            # Same prefix — check if reference portion matches
            r1 = _re.search(r'(\d{4,7})', d1n)
            r2 = _re.search(r'(\d{4,7})', d2n)
            if r1 and r2 and r1.group(1) == r2.group(1):
                return 0.95
            return 0.5
        # Check for shared numeric reference
        r1 = _re.search(r'(\d{4,7})', d1n)
        r2 = _re.search(r'(\d{4,7})', d2n)
        if r1 and r2 and r1.group(1) == r2.group(1):
            return 0.6
        return 0.1

    if not human_lines or not ai_lines:
        return {"pairs": [], "avg_score": 0, "unmatched_human": len(human_lines), "unmatched_ai": len(ai_lines)}

    # Build scoring matrix
    scores = []
    for ai_idx, ai_ln in enumerate(ai_lines):
        for h_idx, h_ln in enumerate(human_lines):
            s = 0.0
            ai_item = ai_ln.get("lineObjectNumber", "")
            h_item = h_ln.get("lineObjectNumber", "")

            # Item/GL match
            if ai_item and h_item:
                if ai_item == h_item:
                    s += 0.35
                elif _item_family(ai_item) == _item_family(h_item):
                    s += 0.25
            elif not ai_item and not h_item:
                s += 0.15  # Both empty — weak match

            # Line type
            if ai_ln.get("lineType") == h_ln.get("lineType"):
                s += 0.10

            # Description
            ai_desc = ai_ln.get("description", "")
            h_desc = h_ln.get("description", "")
            if ai_desc and h_desc:
                s += 0.25 * _desc_sim(ai_desc, h_desc)

            # Amount
            ai_amt = ai_ln.get("netAmount") or ai_ln.get("unitCost", 0) or 0
            h_amt = h_ln.get("netAmount") or h_ln.get("lineAmount") or h_ln.get("unitCost", 0) or 0
            if isinstance(ai_amt, (int, float)) and isinstance(h_amt, (int, float)):
                if ai_amt == 0 and h_amt == 0:
                    s += 0.20  # Both zero-cost
                elif max(ai_amt, h_amt) > 0:
                    ratio = min(ai_amt, h_amt) / max(ai_amt, h_amt, 0.01)
                    s += 0.20 * max(0, ratio)

            # Tax code
            if ai_ln.get("taxCode") == h_ln.get("taxCode"):
                s += 0.05

            # UOM
            ai_uom = ai_ln.get("uom") or ai_ln.get("unitOfMeasureCode", "")
            h_uom = h_ln.get("uom") or h_ln.get("unitOfMeasureCode", "")
            if ai_uom and h_uom and ai_uom == h_uom:
                s += 0.05

            scores.append((round(s, 3), ai_idx, h_idx))

    # Greedy matching: best pairs first
    scores.sort(key=lambda x: -x[0])
    used_h = set()
    used_a = set()
    pairs = []
    for s, ai_idx, h_idx in scores:
        if ai_idx in used_a or h_idx in used_h:
            continue
        h_ln = human_lines[h_idx]
        a_ln = ai_lines[ai_idx]
        pairs.append({
            "human_idx": h_idx,
            "ai_idx": ai_idx,
            "score": round(s * 100),
            "human_item": h_ln.get("lineObjectNumber", ""),
            "ai_item": a_ln.get("lineObjectNumber", ""),
            "human_desc": (h_ln.get("description") or "")[:50],
            "ai_desc": (a_ln.get("description") or "")[:50],
            "human_amount": h_ln.get("netAmount") or h_ln.get("lineAmount") or h_ln.get("unitCost", 0) or 0,
            "ai_amount": a_ln.get("netAmount") or a_ln.get("unitCost", 0) or 0,
        })
        used_a.add(ai_idx)
        used_h.add(h_idx)

    # Sort pairs by human index for readability
    pairs.sort(key=lambda p: p["human_idx"])

    unmatched_h = len(human_lines) - len(used_h)
    unmatched_a = len(ai_lines) - len(used_a)
    avg_score = round(sum(p["score"] for p in pairs) / max(len(pairs), 1))

    return {
        "pairs": pairs,
        "avg_score": avg_score,
        "unmatched_human": unmatched_h,
        "unmatched_ai": unmatched_a,
    }



# =============================================================================
# Per-Document Intelligence — Real-time AI Learning Pulse
# =============================================================================

@router.get("/learning-pulse")
async def get_learning_pulse():
    """
    Real-time pulse of how the AI is learning from every document.
    Shows outcomes, confidence calibration, top vendors, and validation gaps.
    """
    from deps import get_db
    from services.per_document_learning_service import get_learning_pulse as _get_pulse
    db = get_db()
    return await _get_pulse(db)


@router.get("/learning-pulse/vendor/{vendor_no}")
async def get_vendor_learning_profile(vendor_no: str):
    """
    Complete per-document learning profile for a specific vendor.
    Shows intelligence, field accuracy, confidence calibration, gaps.
    """
    from deps import get_db
    from services.per_document_learning_service import get_vendor_learning_profile as _get_profile
    db = get_db()
    profile = await _get_profile(db, vendor_no)
    if not profile:
        return {"vendor_no": vendor_no, "message": "No learning data yet"}
    return profile


@router.get("/learning-pulse/confidence-calibration")
async def get_confidence_calibration():
    """
    How well-calibrated is the AI's confidence?
    Shows accuracy per confidence band — globally, per vendor, per doc type.
    """
    from deps import get_db
    from services.per_document_learning_service import get_confidence_calibration_report
    db = get_db()
    return await get_confidence_calibration_report(db)


@router.post("/learning-pulse/backfill")
async def backfill_per_document_learning(
    limit: int = Query(500, description="Max documents to process"),
    background_tasks: BackgroundTasks = None,
):
    """
    Backfill per-document learning for existing documents.
    Runs through recent documents and extracts learning signals.
    """
    from deps import get_db
    from services.per_document_learning_service import learn_from_document
    db = get_db()

    async def _backfill():
        docs = await db.hub_documents.find(
            {"status": {"$exists": True}},
            {"_id": 0, "id": 1}
        ).sort("updated_utc", -1).limit(limit).to_list(limit)

        processed = 0
        errors = 0
        for doc in docs:
            try:
                await learn_from_document(db, doc["id"], trigger="backfill")
                processed += 1
            except Exception as e:
                errors += 1
                logger.warning("[Backfill] Error for %s: %s", doc.get("id", "")[:8], e)

        logger.info("[Backfill] Per-document learning backfill: %d processed, %d errors", processed, errors)
        return {"processed": processed, "errors": errors}

    if background_tasks:
        background_tasks.add_task(_backfill)
        return {"message": f"Backfill started for up to {limit} documents", "async": True}
    else:
        result = await _backfill()
        return result



@router.post("/intelligence/recalibrate-confidence")
async def recalibrate_confidence_bands():
    """
    Recalibrate confidence bands using effective confidence (extraction-adjusted).
    
    Rebuilds the global confidence_calibration from scratch, using 
    compute_effective_confidence() so docs with high AI confidence but 
    poor extraction get placed in honest (lower) bands.
    """
    from deps import get_db
    from services.per_document_learning_service import compute_effective_confidence
    db = get_db()

    async def _recalibrate():
        import time
        start = time.time()

        # Reset calibration
        await db.confidence_calibration.delete_many({"calibration_id": "global"})

        # Process all documents with ai_confidence
        cursor = db.hub_documents.find(
            {"ai_confidence": {"$exists": True, "$gt": 0}},
            {
                "_id": 0, "id": 1, "ai_confidence": 1,
                "extracted_fields": 1, "vendor_canonical": 1,
                "bc_vendor_number": 1, "vendor_resolution": 1,
                "status": 1, "automation_decision": 1,
                "auto_cleared": 1, "workflow_status": 1,
            },
        ).batch_size(200)

        total = 0
        band_counts = {}
        async for doc in cursor:
            try:
                eff_conf = compute_effective_confidence(doc)
                
                # Determine band
                if eff_conf < 0.50:
                    band = "0_50"
                elif eff_conf < 0.70:
                    band = "50_70"
                elif eff_conf < 0.85:
                    band = "70_85"
                elif eff_conf < 0.95:
                    band = "85_95"
                else:
                    band = "95_100"

                # Determine outcome
                status = (doc.get("status") or "").lower()
                decision = (doc.get("automation_decision") or "").lower()
                is_correct = (
                    status in ("completed", "posted", "linkedtobc", "storedinsp", "archived", "validationpassed")
                    or decision in ("approved", "auto_process", "auto_clear")
                    or doc.get("auto_cleared")
                )

                inc_ops = {f"bands.{band}.total": 1}
                if is_correct:
                    inc_ops[f"bands.{band}.correct"] = 1
                else:
                    inc_ops[f"bands.{band}.incorrect"] = 1

                await db.confidence_calibration.update_one(
                    {"calibration_id": "global"},
                    {"$inc": inc_ops, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}},
                    upsert=True,
                )

                # Also store effective confidence on the document
                raw_conf = float(doc.get("ai_confidence") or 0)
                penalty = round(raw_conf - eff_conf, 4) if raw_conf > eff_conf else 0
                await db.hub_documents.update_one(
                    {"id": doc["id"]},
                    {"$set": {
                        "effective_confidence": eff_conf,
                        "confidence_penalty_applied": penalty,
                    }},
                )

                band_counts[band] = band_counts.get(band, 0) + 1
                total += 1
            except Exception as e:
                logger.warning("[Recalibrate] Error on doc %s: %s", str(doc.get("id", ""))[:8], str(e))

        duration = round(time.time() - start, 1)
        logger.info("[Recalibrate] Done: %d docs in %.1fs. Bands: %s", total, duration, band_counts)

        # Read back the calibration for the response
        cal = await db.confidence_calibration.find_one(
            {"calibration_id": "global"}, {"_id": 0}
        )
        bands_result = {}
        for band_name in ["0_50", "50_70", "70_85", "85_95", "95_100"]:
            bd = (cal or {}).get("bands", {}).get(band_name, {})
            t = bd.get("total", 0)
            c = bd.get("correct", 0)
            bands_result[band_name] = {
                "total": t,
                "correct": c,
                "accuracy": round(c / t, 4) if t > 0 else 0,
            }

        return {
            "status": "completed",
            "documents_processed": total,
            "duration_seconds": duration,
            "band_distribution": band_counts,
            "calibration": bands_result,
        }

    # Run synchronously — fast enough for production volumes (<10s for ~3K docs)
    return await _recalibrate()



# =============================================================================
# Deep Learning Engine — Advanced Intelligence APIs
# =============================================================================

@router.get("/deep-learning/summary")
async def get_deep_learning_summary():
    """Complete summary of all 5 deep learning engines."""
    from deps import get_db
    from services.deep_learning_engine import get_deep_learning_summary as _get_summary
    db = get_db()
    return await _get_summary(db)


@router.get("/deep-learning/extraction-patterns/{vendor_no}")
async def get_extraction_patterns(vendor_no: str):
    """Get learned extraction patterns for a specific vendor."""
    from deps import get_db
    db = get_db()
    pattern = await db.extraction_patterns.find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )
    if not pattern:
        return {"vendor_no": vendor_no, "message": "No extraction patterns learned yet"}
    return pattern


@router.get("/deep-learning/extraction-hints/{vendor_no}")
async def get_extraction_hints(vendor_no: str):
    """Get extraction hints for the AI pipeline based on learned patterns."""
    from deps import get_db
    from services.deep_learning_engine import get_extraction_hints_for_vendor
    db = get_db()
    return await get_extraction_hints_for_vendor(db, vendor_no)


@router.post("/deep-learning/find-similar/{doc_id}")
async def find_similar_documents(doc_id: str):
    """Find documents most similar to a given document."""
    from deps import get_db
    from services.deep_learning_engine import find_similar_documents as _find_similar
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": "Document not found"}
    results = await _find_similar(db, doc)
    return {"doc_id": doc_id, "similar_documents": results}


@router.post("/deep-learning/self-correction/run")
async def run_self_correction(
    sample_size: int = Query(50, description="Number of documents to audit"),
):
    """Run a self-correction audit — spot-check auto-filed decisions."""
    from deps import get_db
    from services.deep_learning_engine import run_self_correction_audit
    db = get_db()
    return await run_self_correction_audit(db, sample_size)


@router.get("/deep-learning/self-correction/history")
async def get_self_correction_history():
    """Get history of self-correction audits."""
    from deps import get_db
    from services.deep_learning_engine import get_self_correction_history as _get_history
    db = get_db()
    return await _get_history(db)


@router.get("/deep-learning/vendor-maturity/{vendor_no}")
async def get_vendor_maturity(vendor_no: str):
    """Get multi-dimensional maturity score for a vendor."""
    from deps import get_db
    from services.deep_learning_engine import compute_vendor_maturity
    db = get_db()
    return await compute_vendor_maturity(db, vendor_no)


@router.post("/deep-learning/vendor-maturity/compute-all")
async def compute_all_maturity(background_tasks: BackgroundTasks):
    """Compute maturity scores for all vendors."""
    from deps import get_db
    from services.deep_learning_engine import compute_all_vendor_maturity
    db = get_db()

    async def _compute():
        return await compute_all_vendor_maturity(db)

    background_tasks.add_task(_compute)
    return {"message": "Computing maturity scores for all vendors", "async": True}


@router.post("/deep-learning/predict-readiness/{doc_id}")
async def predict_document_readiness(doc_id: str):
    """Predict whether a document will need human review."""
    from deps import get_db
    from services.deep_learning_engine import predict_and_store
    db = get_db()
    return await predict_and_store(db, doc_id)


# =============================================================================
# Advanced Learning Engine — 7 Intelligence Layer APIs
# =============================================================================

@router.get("/advanced-learning/summary")
async def get_advanced_learning_summary():
    """Complete summary of all 7 advanced learning engines."""
    from deps import get_db
    from services.advanced_learning_engine import get_advanced_learning_summary as _get_summary
    db = get_db()
    return await _get_summary(db)


@router.get("/advanced-learning/line-items/{vendor_no}")
async def get_line_item_suggestions(vendor_no: str):
    """Get learned line item patterns/GL suggestions for a vendor."""
    from deps import get_db
    from services.advanced_learning_engine import get_line_item_suggestions as _get_suggestions
    db = get_db()
    suggestions = await _get_suggestions(db, vendor_no)
    return {"vendor_no": vendor_no, "suggestions": suggestions}


@router.get("/advanced-learning/predict-next/{vendor_no}")
async def predict_next_document(vendor_no: str):
    """Predict what document type will arrive next from a vendor."""
    from deps import get_db
    from services.advanced_learning_engine import predict_next_document as _predict
    db = get_db()
    return await _predict(db, vendor_no)


@router.get("/advanced-learning/amount-check/{vendor_no}")
async def check_amount_anomaly(vendor_no: str, amount: float = Query(...)):
    """Check if an invoice amount is anomalous for a vendor."""
    from deps import get_db
    from services.advanced_learning_engine import check_amount_anomaly as _check
    db = get_db()
    return await _check(db, vendor_no, amount)


@router.get("/advanced-learning/correction-replays")
async def get_correction_replays():
    """Get history of correction replays."""
    from deps import get_db
    from services.advanced_learning_engine import get_replay_history
    db = get_db()
    return await get_replay_history(db)


@router.get("/advanced-learning/field-predictions/{doc_id}")
async def get_field_predictions(doc_id: str):
    """Use learned correlations to predict doc type from field values."""
    from deps import get_db
    from services.advanced_learning_engine import get_field_predictions as _predict
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": "Document not found"}
    predictions = await _predict(db, doc)
    return {"doc_id": doc_id, "predictions": predictions}


@router.get("/advanced-learning/volume-prediction")
async def get_volume_prediction():
    """Predict tomorrow's inbox volume."""
    from deps import get_db
    from services.advanced_learning_engine import predict_volume
    db = get_db()
    return await predict_volume(db)


@router.post("/advanced-learning/backfill")
async def backfill_advanced_learning(
    limit: int = Query(500),
    background_tasks: BackgroundTasks = None,
):
    """Backfill all 7 advanced learning engines from existing documents."""
    from deps import get_db
    from services.advanced_learning_engine import run_advanced_learning
    db = get_db()

    async def _backfill():
        docs = await db.hub_documents.find(
            {"status": {"$exists": True}},
            {"_id": 0, "id": 1}
        ).sort("updated_utc", -1).limit(limit).to_list(limit)

        processed = 0
        for doc in docs:
            try:
                await run_advanced_learning(db, doc["id"], trigger="backfill")
                processed += 1
            except Exception:
                pass

        logger.info("[AdvancedBackfill] %d documents processed", processed)
        return {"processed": processed}

    if background_tasks:
        background_tasks.add_task(_backfill)
        return {"message": f"Advanced learning backfill started for up to {limit} documents", "async": True}
    result = await _backfill()
    return result



# =============================================================================
# Gap Closer Intelligence APIs
# =============================================================================

@router.get("/gap-closer/status")
async def get_gap_closer_status():
    """
    Status of all 4 gap closers — how much intelligence is available
    to close each validation gap.
    """
    from deps import get_db
    from services.gap_closer_service import get_confidence_band_accuracy
    db = get_db()

    # GAP 1: Confidence band calibration
    bands = {}
    for conf, band_name in [(0.25, "0-50%"), (0.60, "50-70%"), (0.77, "70-85%"), (0.90, "85-95%"), (0.97, "95-100%")]:
        result = await get_confidence_band_accuracy(db, conf)
        bands[band_name] = {
            "accuracy": result.get("accuracy"),
            "samples": result.get("total_samples", 0),
            "triggers_review": result.get("should_review", False),
            "reason": result.get("reason", ""),
        }

    # GAP 2: PO intelligence (count vendors with extraction patterns)
    po_vendors = await db.extraction_patterns.count_documents({"field_presence.po_number": {"$exists": True}})
    po_flow_events = await db.document_flow_sequences.count_documents(
        {"doc_type": {"$in": ["Purchase_Order", "PO"]}}
    )

    # GAP 3: Customer intelligence
    cust_pipeline = [
        {"$match": {"validation_results.checks": {"$elemMatch": {"check_name": "customer_match", "passed": True}}}},
        {"$count": "total"},
    ]
    cust_history = await db.hub_documents.aggregate(cust_pipeline).to_list(1)
    customer_history_count = cust_history[0]["total"] if cust_history else 0

    # GAP 4: Sales order flow intelligence
    so_flow_count = await db.document_flow_sequences.count_documents(
        {"doc_type": {"$in": ["Sales_Order", "Shipping_Document", "BOL"]}}
    )
    so_matched = await db.hub_documents.count_documents(
        {"validation_results.matched_sales_order": {"$exists": True}}
    )

    # Validation gap counts — count directly from hub_documents for accuracy
    # Split into blocking (required=true or unset) and advisory (required=false) gaps
    gap_check_names = ["po_validation", "customer_match", "sales_order_match", "vendor_match", "duplicate_check", "extraction_quality_gate"]
    gap_counts = {}
    advisory_counts = {}
    for check_name in gap_check_names:
        # Total failed checks
        total = await db.hub_documents.count_documents({
            "validation_results.checks": {
                "$elemMatch": {"check_name": check_name, "passed": False}
            },
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
        })
        # Advisory: required explicitly set to false
        advisory = await db.hub_documents.count_documents({
            "validation_results.checks": {
                "$elemMatch": {"check_name": check_name, "passed": False, "required": False}
            },
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
        })
        blocking = total - advisory
        if blocking > 0:
            gap_counts[check_name] = blocking
        if advisory > 0:
            advisory_counts[check_name] = advisory

    # GAP 5: Duplicate Intelligence
    try:
        from services.duplicate_intelligence_service import get_duplicate_intelligence_summary
        dup_summary = await get_duplicate_intelligence_summary(db)
        dup_intel_summary = {
            "status": "active",
            "vendors_with_intel": dup_summary.get("vendors_with_intel", 0),
            "global_false_positive_rate": dup_summary.get("global_false_positive_rate", 0),
            "safe_to_clear_vendors": dup_summary.get("safe_to_clear_vendors", 0),
            "currently_blocked": dup_summary.get("currently_blocked_by_duplicate", 0),
            "action": "Learns from false-positive duplicate flags and auto-clears unreliable vendor duplicates",
        }
    except Exception:
        dup_intel_summary = {"status": "initializing"}

    # GAP 6: Amount Anomaly Detection
    try:
        amount_vendors = await db.amount_patterns.count_documents({"count": {"$gte": 3}})
        active_anomalies = await db.amount_patterns.count_documents({"latest_is_anomaly": True})
        amount_anomaly_summary = {
            "status": "active",
            "vendors_with_patterns": amount_vendors,
            "active_anomalies": active_anomalies,
            "action": "Detects unusual amounts per vendor and routes high-severity anomalies to review",
        }
    except Exception:
        amount_anomaly_summary = {"status": "initializing"}

    # GAP 7: Auto-Escalation Intelligence
    try:
        from services.escalation_intelligence_service import get_escalation_summary
        esc_summary = await get_escalation_summary(db)
        escalation_summary = {
            "status": "active",
            "combinations_tracked": esc_summary.get("total_combinations_tracked", 0),
            "always_escalate": esc_summary.get("always_escalate", 0),
            "fully_automated": esc_summary.get("fully_automated", 0),
            "action": "Pre-routes vendor+doc_type combos with consistent failures to manual review",
        }
    except Exception:
        escalation_summary = {"status": "initializing"}

    # GAP 8: Extraction Quality Gate — count docs resolved vs remaining
    extraction_gate_resolved = await db.hub_documents.count_documents({"extraction_gap_resolved_via": {"$exists": True}})
    extraction_gate_downgraded = await db.hub_documents.count_documents({"extraction_gate_downgraded": True})
    extraction_gate_blocking = gap_counts.get("extraction_quality_gate", 0)

    # GAP 9: Enhanced Vendor Match stats
    enhanced_vendor_resolved = await db.hub_documents.count_documents({"vendor_enhanced_match_via": {"$exists": True}})
    vendor_alias_count = await db.vendor_aliases.count_documents({})

    # GAP 10: Enhanced PO Revalidation stats
    po_enhanced_resolved = await db.hub_documents.count_documents({"po_enhanced_resolved_via": {"$exists": True}})
    po_downgraded = await db.hub_documents.count_documents({"po_gate_downgraded": True})

    return {
        "gap_1_confidence_calibration": {
            "status": "active",
            "bands": bands,
            "action": "Auto-routes unreliable confidence bands to human review",
        },
        "gap_2_po_matching": {
            "status": "active",
            "vendors_with_po_patterns": po_vendors,
            "po_flow_events": po_flow_events,
            "gap_count": gap_counts.get("po_validation", 0) + gap_counts.get("po_match", 0),
            "action": "Expands PO candidates with fuzzy matching + vendor patterns + document flow",
        },
        "gap_3_customer_matching": {
            "status": "active",
            "historical_matches": customer_history_count,
            "gap_count": gap_counts.get("customer_match", 0),
            "action": "Suggests customers from vendor history when direct match fails",
        },
        "gap_4_sales_order_matching": {
            "status": "active",
            "flow_events": so_flow_count,
            "historical_so_matches": so_matched,
            "gap_count": gap_counts.get("sales_order_match", 0),
            "action": "Cross-references document flow to find SO matches via fuzzy + historical lookup",
        },
        "gap_5_duplicate_intelligence": dup_intel_summary,
        "gap_6_amount_anomaly": amount_anomaly_summary,
        "gap_7_escalation_intelligence": escalation_summary,
        "gap_8_extraction_quality": {
            "status": "active",
            "blocking_count": extraction_gate_blocking,
            "resolved_by_filename": extraction_gate_resolved,
            "downgraded_to_advisory": extraction_gate_downgraded,
            "action": "Filename parsing, batch context inheritance, smart advisory downgrade for empty docs",
        },
        "gap_9_enhanced_vendor_match": {
            "status": "active",
            "blocking_count": gap_counts.get("vendor_match", 0),
            "enhanced_resolved": enhanced_vendor_resolved,
            "total_aliases": vendor_alias_count,
            "action": "Cross-doc inference, email domain mapping, aggressive first-word matching",
        },
        "gap_10_enhanced_po": {
            "status": "active",
            "blocking_count": gap_counts.get("po_validation", 0),
            "enhanced_resolved": po_enhanced_resolved,
            "downgraded_to_advisory": po_downgraded,
            "action": "Profile relaxation (< 30% PO rate), broader ref matching, doc-type downgrade",
        },
        "total_validation_gaps": gap_counts,
        "advisory_validation_gaps": advisory_counts,
    }


# =============================================================================
# Duplicate Intelligence API
# =============================================================================

@router.get("/duplicate-intelligence")
async def get_duplicate_intelligence():
    """Get duplicate intelligence summary — false-positive learning."""
    from deps import get_db
    from services.duplicate_intelligence_service import get_duplicate_intelligence_summary
    db = get_db()
    return await get_duplicate_intelligence_summary(db)


@router.post("/duplicate-intelligence/batch-clear")
async def batch_clear_safe_duplicates(limit: int = Query(100)):
    """Auto-clear duplicate flags for vendors with unreliable duplicate detection."""
    from deps import get_db
    from services.duplicate_intelligence_service import batch_auto_clear_safe_duplicates
    db = get_db()
    return await batch_auto_clear_safe_duplicates(db, limit=limit)


# =============================================================================
# Escalation Intelligence API
# =============================================================================

@router.get("/escalation-intelligence")
async def get_escalation_intelligence():
    """Get escalation intelligence summary — which vendor+doc_type combos always fail."""
    from deps import get_db
    from services.escalation_intelligence_service import get_escalation_summary
    db = get_db()
    return await get_escalation_summary(db)


@router.get("/po-gap-breakdown")
async def get_po_gap_breakdown():
    """Break down PO validation gaps by vendor — which vendors have the most PO failures."""
    from deps import get_db
    db = get_db()

    pipeline = [
        {"$match": {
            "validation_results.checks": {
                "$elemMatch": {"check_name": "po_validation", "passed": False}
            },
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
        }},
        {"$group": {
            "_id": {
                "vendor": {"$ifNull": ["$bc_vendor_number", {"$ifNull": ["$vendor_no", "unknown"]}]},
                "vendor_name": {"$ifNull": ["$vendor_name", ""]},
            },
            "count": {"$sum": 1},
            "sample_pos": {"$addToSet": "$extracted_fields.po_number"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]

    results = await db.hub_documents.aggregate(pipeline).to_list(20)
    vendors = []
    for r in results:
        vendor_info = r.get("_id", {})
        sample_pos = [p for p in (r.get("sample_pos") or []) if p][:5]
        vendors.append({
            "vendor_no": vendor_info.get("vendor", "unknown"),
            "vendor_name": vendor_info.get("vendor_name", ""),
            "gap_count": r.get("count", 0),
            "sample_po_numbers": sample_pos,
        })

    total_po_gaps = sum(v["gap_count"] for v in vendors)
    return {
        "total_po_gaps": total_po_gaps,
        "by_vendor": vendors,
    }


@router.get("/po-format-intelligence")
async def get_po_format_intelligence():
    """Get PO format learning summary — which transformations work per vendor."""
    from deps import get_db
    from services.po_format_learning_service import get_po_format_summary
    db = get_db()
    return await get_po_format_summary(db)


# =============================================================================
# On-Demand Intelligence Backfill
# =============================================================================

@router.post("/intelligence/backfill")
async def run_intelligence_backfill():
    """
    On-demand: Run all intelligence backfills immediately.
    - Duplicate outcome backfill (completed docs with dup flag → false positive)
    - Escalation outcome backfill (all completed/posted docs → success/failure tracking)
    - Vendor maturity recompute
    - Duplicate batch-clear
    """
    from deps import get_db
    db = get_db()
    results = {}

    # 1. Escalation backfill
    try:
        from services.escalation_intelligence_service import record_automation_outcome
        recent_docs = await db.hub_documents.find(
            {
                "status": {"$in": ["Completed", "Posted", "Auto-Draft", "Linked", "Filed", "Needs Review", "Review", "Rejected"]},
                "escalation_tracked": {"$ne": True},
            },
            {"_id": 0, "id": 1, "bc_vendor_number": 1, "vendor_no": 1, "matched_vendor_no": 1,
             "document_type": 1, "suggested_job_type": 1, "status": 1}
        ).limit(500).to_list(500)

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
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {"escalation_tracked": True}})
            tracked += 1
        results["escalation_backfill"] = {"tracked": tracked, "found": len(recent_docs)}
    except Exception as e:
        results["escalation_backfill"] = {"error": str(e)}

    # 2. Duplicate outcome backfill
    try:
        from services.duplicate_intelligence_service import record_duplicate_outcome
        dup_docs = await db.hub_documents.find(
            {
                "possible_duplicate": True,
                "status": {"$in": ["Completed", "Posted", "Auto-Draft", "Linked", "Filed"]},
                "duplicate_outcome_tracked": {"$ne": True},
            },
            {"_id": 0, "id": 1, "bc_vendor_number": 1, "vendor_no": 1, "matched_vendor_no": 1}
        ).limit(500).to_list(500)

        dup_tracked = 0
        for d in dup_docs:
            vendor = d.get("bc_vendor_number") or d.get("vendor_no") or d.get("matched_vendor_no") or ""
            doc_id = d.get("id", "")
            if not vendor:
                continue
            await record_duplicate_outcome(
                db, doc_id=doc_id, vendor_no=vendor,
                was_flagged_duplicate=True,
                actual_outcome="false_positive",
                resolution_source="backfill_completed",
            )
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {"duplicate_outcome_tracked": True}})
            dup_tracked += 1
        results["duplicate_backfill"] = {"tracked": dup_tracked, "found": len(dup_docs)}
    except Exception as e:
        results["duplicate_backfill"] = {"error": str(e)}

    # 3. Vendor maturity recompute
    try:
        from services.deep_learning_engine import compute_all_vendor_maturity
        maturity = await compute_all_vendor_maturity(db)
        results["vendor_maturity"] = {
            "computed": maturity.get("computed", 0),
            "levels": maturity.get("levels", {}),
        }
    except Exception as e:
        results["vendor_maturity"] = {"error": str(e)}

    # 4. Duplicate batch-clear
    try:
        from services.duplicate_intelligence_service import batch_auto_clear_safe_duplicates
        clear = await batch_auto_clear_safe_duplicates(db, limit=200)
        results["duplicate_clear"] = clear
    except Exception as e:
        results["duplicate_clear"] = {"error": str(e)}

    # 5. Force-refresh vendor profiles for top PO gap vendors BEFORE re-validation.
    # This ensures profiles reflect the latest BC cache data (e.g., after a cache sync).
    try:
        from services.vendor_invoice_profile_service import build_vendor_profile
        po_gap_vendors = await db.hub_documents.aggregate([
            {"$match": {
                "validation_results.checks": {"$elemMatch": {"check_name": "po_validation", "passed": False}},
                "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
            }},
            {"$group": {
                "_id": {"$ifNull": ["$bc_vendor_number", {"$ifNull": ["$vendor_no", "unknown"]}]},
                "gap_count": {"$sum": 1},
            }},
            {"$sort": {"gap_count": -1}},
            {"$limit": 15},
        ]).to_list(15)

        refreshed = 0
        vendor_po_profiles = []
        for vg in po_gap_vendors:
            vendor_no = vg["_id"]
            if vendor_no == "unknown":
                vendor_po_profiles.append({"vendor_no": "unknown", "gaps": vg["gap_count"], "profile": "no vendor match"})
                continue
            # Force rebuild from latest cache data
            profile = await build_vendor_profile(db, vendor_no, force_refresh=True)
            refreshed += 1
            cache_count = await db.bc_reference_cache.count_documents({
                "bc_vendor_no": vendor_no,
                "bc_entity_type": {"$in": ["posted_purchase_invoice", "draft_purchase_invoice"]},
            })
            cache_with_po = await db.bc_reference_cache.count_documents({
                "bc_vendor_no": vendor_no,
                "bc_entity_type": {"$in": ["posted_purchase_invoice", "draft_purchase_invoice"]},
                "bc_order_number": {"$exists": True, "$nin": [None, ""]},
            })
            vendor_po_profiles.append({
                "vendor_no": vendor_no,
                "gaps": vg["gap_count"],
                "po_expected": profile.get("po_expected", True) if profile else True,
                "bc_cache_invoices": cache_count,
                "bc_cache_with_po": cache_with_po,
                "po_rate": round(cache_with_po / max(cache_count, 1), 3) if cache_count else None,
            })
        results["vendor_profile_refresh"] = {"refreshed": refreshed, "profiles": vendor_po_profiles}
    except Exception as e:
        results["vendor_profile_refresh"] = {"error": str(e)}

    # 6. PO Gap Re-validation — now uses freshly refreshed vendor profiles
    try:
        results["po_revalidation"] = await _batch_revalidate_po_gaps(db, limit=1000)
    except Exception as e:
        results["po_revalidation"] = {"error": str(e)}

    # 7. Customer Match Re-validation — aliases, vendor→customer history, cache
    try:
        from services.validation_backfill_service import batch_revalidate_customer_gaps
        results["customer_revalidation"] = await batch_revalidate_customer_gaps(db, limit=500)
    except Exception as e:
        results["customer_revalidation"] = {"error": str(e)}

    # 8. Sales Order Match Re-validation — cache-first SO lookup, normalization
    try:
        from services.validation_backfill_service import batch_revalidate_so_gaps
        results["so_revalidation"] = await batch_revalidate_so_gaps(db, limit=500)
    except Exception as e:
        results["so_revalidation"] = {"error": str(e)}

    # 9. Vendor Match Re-validation — re-run with latest aliases + email domain
    try:
        from services.validation_backfill_service import batch_revalidate_vendor_gaps
        results["vendor_revalidation"] = await batch_revalidate_vendor_gaps(db, limit=500)
    except Exception as e:
        results["vendor_revalidation"] = {"error": str(e)}

    # 10. Duplicate Check Re-validation — smart duplicate clearing
    try:
        from services.validation_backfill_service import batch_revalidate_duplicate_gaps
        results["duplicate_revalidation"] = await batch_revalidate_duplicate_gaps(db, limit=200)
    except Exception as e:
        results["duplicate_revalidation"] = {"error": str(e)}

    # 11. Extraction Quality Gate Re-validation — filename parsing, batch context, smart downgrade
    try:
        from services.validation_backfill_service import batch_revalidate_extraction_gaps
        results["extraction_revalidation"] = await batch_revalidate_extraction_gaps(db, limit=500)
    except Exception as e:
        results["extraction_revalidation"] = {"error": str(e)}

    # 11b. Force-downgrade any remaining blocking extraction quality gate failures
    try:
        from services.validation_backfill_service import force_downgrade_extraction_gate
        results["extraction_force_downgrade"] = await force_downgrade_extraction_gate(db)
    except Exception as e:
        results["extraction_force_downgrade"] = {"error": str(e)}

    # 12. Enhanced Vendor Match — cross-doc inference, email domain, aggressive matching
    try:
        from services.validation_backfill_service import enhanced_vendor_match_backfill
        results["vendor_enhanced_match"] = await enhanced_vendor_match_backfill(db, limit=500)
    except Exception as e:
        results["vendor_enhanced_match"] = {"error": str(e)}

    # 13. Enhanced PO Revalidation — profile relaxation, broader ref matching, doc type downgrade
    try:
        from services.validation_backfill_service import enhanced_po_revalidation
        results["po_enhanced_revalidation"] = await enhanced_po_revalidation(db, limit=500)
    except Exception as e:
        results["po_enhanced_revalidation"] = {"error": str(e)}

    # 14. Gap Log Cleanup — remove stale entries for resolved/archived docs
    try:
        stale_cleaned = 0
        gap_log_entries = await db.validation_gap_log.find(
            {}, {"_id": 0, "doc_id": 1, "failure_checks": 1}
        ).limit(2000).to_list(2000)
        for entry in gap_log_entries:
            doc_id = entry.get("doc_id", "")
            if not doc_id:
                continue
            doc = await db.hub_documents.find_one(
                {"id": doc_id},
                {"_id": 0, "status": 1, "validation_results.checks": 1}
            )
            if not doc:
                await db.validation_gap_log.delete_many({"doc_id": doc_id})
                stale_cleaned += 1
                continue
            if doc.get("status") in ("Completed", "Posted", "Deleted", "Archived"):
                await db.validation_gap_log.delete_many({"doc_id": doc_id})
                stale_cleaned += 1
                continue
            # Check if the specific failure checks are now passing
            checks = (doc.get("validation_results") or {}).get("checks", [])
            check_map = {c.get("check_name"): c.get("passed", False) for c in checks}
            failures = entry.get("failure_checks", "")
            if isinstance(failures, str):
                failures = [failures]
            all_resolved = all(check_map.get(f, False) for f in failures if f)
            if all_resolved:
                await db.validation_gap_log.delete_many({"doc_id": doc_id})
                stale_cleaned += 1
        results["gap_log_cleanup"] = {"stale_removed": stale_cleaned, "checked": len(gap_log_entries)}
    except Exception as e:
        results["gap_log_cleanup"] = {"error": str(e)}

    return results


async def _batch_revalidate_po_gaps(db, limit: int = 200) -> dict:
    """
    Re-run PO matching on documents with po_validation gaps.
    
    TWO-PASS approach:
      Pass 1: Check vendor profile — if po_expected=False, resolve as PO_SKIP
      Pass 2: For remaining docs, use enhanced PO intelligence to find matching POs
    """
    import httpx
    import logging
    logger = logging.getLogger("po_revalidation")

    # Find docs with failed po_validation checks that aren't already completed
    po_gap_docs = await db.hub_documents.find(
        {
            "validation_results.checks": {
                "$elemMatch": {"check_name": "po_validation", "passed": False}
            },
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
        },
        {
            "_id": 0, "id": 1, "bc_vendor_number": 1, "vendor_no": 1, "matched_vendor_no": 1,
            "vendor_name": 1, "matched_vendor_name": 1,
            "extracted_fields": 1, "validation_results": 1,
        }
    ).limit(limit).to_list(limit)

    if not po_gap_docs:
        return {"found": 0, "resolved": 0, "skipped_by_profile": 0, "message": "No PO validation gaps found"}

    # ── PASS 1: Vendor profile check (po_expected=False → auto-resolve) ──
    from services.vendor_invoice_profile_service import get_or_build_profile

    # Pre-load vendor profiles for all unique vendors in the gap docs
    vendor_nos = set()
    for doc in po_gap_docs:
        vn = doc.get("bc_vendor_number") or doc.get("vendor_no") or doc.get("matched_vendor_no") or ""
        if vn:
            vendor_nos.add(vn)

    # Also collect vendor names for docs without vendor_no — these need reverse lookup
    vendor_name_to_no = {}
    for doc in po_gap_docs:
        vn = doc.get("bc_vendor_number") or doc.get("vendor_no") or doc.get("matched_vendor_no") or ""
        if not vn:
            name = doc.get("vendor_name") or doc.get("matched_vendor_name") or ""
            if name and name not in vendor_name_to_no:
                vendor_name_to_no[name] = None

    # Reverse lookup: vendor display name → vendor_no via bc_reference_cache or vendor_invoice_profiles
    for vname in list(vendor_name_to_no.keys()):
        try:
            # Check profiles for matching vendor_name
            prof = await db.vendor_invoice_profiles.find_one(
                {"$or": [
                    {"vendor_name": {"$regex": re.escape(vname), "$options": "i"}},
                    {"vendor_no": vname.upper()},
                    {"vendor_no": vname},
                ]},
                {"_id": 0, "vendor_no": 1}
            )
            if prof and prof.get("vendor_no"):
                vendor_name_to_no[vname] = prof["vendor_no"]
                vendor_nos.add(prof["vendor_no"])
                continue
            # Check BC vendors list
            cache_match = await db.bc_reference_cache.find_one(
                {"bc_vendor_name": {"$regex": re.escape(vname), "$options": "i"}, "bc_entity_type": "vendor"},
                {"_id": 0, "bc_vendor_no": 1}
            )
            if cache_match and cache_match.get("bc_vendor_no"):
                vendor_name_to_no[vname] = cache_match["bc_vendor_no"]
                vendor_nos.add(cache_match["bc_vendor_no"])
        except Exception:
            pass

    vendor_profiles = {}
    for vn in vendor_nos:
        try:
            profile = await get_or_build_profile(db, vn)
            vendor_profiles[vn] = profile
        except Exception as e:
            logger.debug("[PO-Reval] Profile load error for %s: %s", vn, e)

    resolved = 0
    skipped_by_profile = 0
    errors = 0
    remaining_docs = []

    for doc in po_gap_docs:
        doc_id = doc.get("id", "")
        vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or doc.get("matched_vendor_no") or ""
        validation = doc.get("validation_results") or {}

        # If no vendor_no, try reverse lookup from vendor_name
        if not vendor_no:
            vname = doc.get("vendor_name") or doc.get("matched_vendor_name") or ""
            resolved_vn = vendor_name_to_no.get(vname)
            if resolved_vn:
                vendor_no = resolved_vn
                # Also update the document with the resolved vendor
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {"bc_vendor_number": vendor_no, "vendor_resolved_via": "po_backfill_name_lookup"}}
                )
                logger.info("[PO-Reval] doc=%s resolved vendor from name '%s' → %s", doc_id[:8], vname, vendor_no)

        if not vendor_no:
            remaining_docs.append(doc)
            continue

        profile = vendor_profiles.get(vendor_no)
        po_expected = profile.get("po_expected", True) if profile else True

        # Also check PO format learning — very low match rate means POs aren't standard for this vendor
        po_intel = await db.po_format_intelligence.find_one(
            {"vendor_no": vendor_no}, {"_id": 0}
        )
        low_match_rate = False
        if po_intel and po_intel.get("total_po_attempts", 0) >= 10:
            if po_intel.get("match_rate", 1.0) < 0.10:
                low_match_rate = True

        if not po_expected or low_match_rate:
            # Vendor doesn't use POs — resolve the gap by skipping PO validation
            reason = "vendor profile: po_expected=False" if not po_expected else f"PO match rate {po_intel.get('match_rate', 0):.1%} < 10%"
            new_checks = [
                ch for ch in validation.get("checks", [])
                if ch.get("check_name") != "po_validation"
            ]
            new_checks.append({
                "check_name": "po_validation",
                "passed": True,
                "details": f"PO validation skipped — vendor learned to not require POs ({reason})",
                "required": False,
            })

            all_passed = all(ch.get("passed", True) for ch in new_checks)

            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "validation_results.checks": new_checks,
                    "validation_results.all_passed": all_passed,
                    "po_revalidated_at": _now(),
                    "po_revalidated_via": "vendor_profile_learning",
                }}
            )
            await db.validation_gap_log.delete_many({"doc_id": doc_id, "failure_checks": "po_validation"})

            resolved += 1
            skipped_by_profile += 1
            logger.info(
                "[PO-Reval] doc=%s vendor=%s — RESOLVED via profile (%s)",
                doc_id[:8], vendor_no, reason,
            )
        else:
            remaining_docs.append(doc)

    # ── PASS 2: Cache-first PO lookup + BC API matching for remaining docs ──
    bc_resolved = 0
    cache_resolved = 0
    unknown_resolved = 0

    # ── PASS 2a: Try to resolve "unknown" vendor docs first ──
    still_remaining = []
    for doc in remaining_docs:
        doc_id = doc.get("id", "")
        vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or doc.get("matched_vendor_no") or ""
        extracted = doc.get("extracted_fields") or {}
        validation = doc.get("validation_results") or {}

        if vendor_no:
            still_remaining.append(doc)
            continue

        # Try to resolve unknown vendor from extracted fields
        resolved_vendor = None
        try:
            vendor_name = extracted.get("vendor") or extracted.get("vendor_name") or ""
            sender_email = extracted.get("sender_email") or extracted.get("_sender_email") or ""
            file_name = extracted.get("_file_name") or doc.get("file_name") or ""

            # Try vendor name match via aliases
            if vendor_name:
                from services.unified_vendor_matcher import match_vendor_unified
                match = await match_vendor_unified(db, vendor_name, 0.70)
                if match.get("matched") and match.get("best_match"):
                    resolved_vendor = match["best_match"].get("vendor_number") or match.get("bc_vendor_number")
                    if resolved_vendor:
                        await db.hub_documents.update_one(
                            {"id": doc_id},
                            {"$set": {"bc_vendor_number": resolved_vendor, "vendor_resolved_via": "backfill_rematch"}}
                        )
                        logger.info("[PO-Reval] Resolved unknown vendor '%s' → %s", vendor_name, resolved_vendor)
                        unknown_resolved += 1

            # Try email domain match
            if not resolved_vendor and sender_email and "@" in sender_email:
                domain = sender_email.split("@")[1].lower()
                domain_match = await db.sender_domain_mappings.find_one(
                    {"domain": domain}, {"_id": 0, "vendor_no": 1}
                )
                if domain_match and domain_match.get("vendor_no"):
                    resolved_vendor = domain_match["vendor_no"]
                    await db.hub_documents.update_one(
                        {"id": doc_id},
                        {"$set": {"bc_vendor_number": resolved_vendor, "vendor_resolved_via": "backfill_email_domain"}}
                    )
                    logger.info("[PO-Reval] Resolved unknown vendor via email domain '%s' → %s", domain, resolved_vendor)
                    unknown_resolved += 1
        except Exception as e:
            logger.debug("[PO-Reval] Unknown vendor resolution failed for %s: %s", doc_id[:8], e)

        # If we resolved the vendor, check if PO is expected
        if resolved_vendor:
            try:
                profile = await get_or_build_profile(db, resolved_vendor)
                if profile and not profile.get("po_expected", True):
                    new_checks = [ch for ch in validation.get("checks", []) if ch.get("check_name") != "po_validation"]
                    new_checks.append({
                        "check_name": "po_validation",
                        "passed": True,
                        "details": f"PO validation skipped — resolved vendor {resolved_vendor} learned to not require POs",
                        "required": False,
                    })
                    all_passed = all(ch.get("passed", True) for ch in new_checks)
                    await db.hub_documents.update_one(
                        {"id": doc_id},
                        {"$set": {"validation_results.checks": new_checks, "validation_results.all_passed": all_passed,
                                  "po_revalidated_at": _now(), "po_revalidated_via": "unknown_vendor_resolution"}}
                    )
                    await db.validation_gap_log.delete_many({"doc_id": doc_id, "failure_checks": "po_validation"})
                    resolved += 1
                    skipped_by_profile += 1
                    continue
            except Exception:
                pass
            # Re-add with resolved vendor for pass 2b
            doc["bc_vendor_number"] = resolved_vendor
        still_remaining.append(doc)

    remaining_docs = still_remaining

    # ── PASS 2b: Cache-first PO lookup + BC API ──
    if remaining_docs:
        try:
            from services.bc_access import get_bc_adapter
            adapter = get_bc_adapter()
            token = await adapter.get_token()
            if not token:
                return {
                    "found": len(po_gap_docs), "resolved": resolved,
                    "skipped_by_profile": skipped_by_profile, "cache_resolved": cache_resolved,
                    "unknown_resolved": unknown_resolved,
                    "error": "Cannot get BC token for pass 2",
                }
            company_id = await adapter.get_company_id(token)
            if not company_id:
                return {
                    "found": len(po_gap_docs), "resolved": resolved,
                    "skipped_by_profile": skipped_by_profile, "cache_resolved": cache_resolved,
                    "unknown_resolved": unknown_resolved,
                    "error": "Cannot get BC company ID for pass 2",
                }
        except Exception as e:
            return {
                "found": len(po_gap_docs), "resolved": resolved,
                "skipped_by_profile": skipped_by_profile, "cache_resolved": cache_resolved,
                "unknown_resolved": unknown_resolved,
                "error": f"BC access failed for pass 2: {e}",
            }

        from services.gap_closer_service import enhance_po_candidates
        from services.bc_reference_cache_service import normalize_document_no

        async with httpx.AsyncClient(timeout=15.0) as c:
            for doc in remaining_docs:
                doc_id = doc.get("id", "")
                vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or doc.get("matched_vendor_no") or ""
                extracted = doc.get("extracted_fields") or {}
                validation = doc.get("validation_results") or {}

                # Gather all PO candidates from the document
                original_candidates = []
                for field in ["po_number", "order_number", "reference_number", "purchase_order"]:
                    val = extracted.get(field, "")
                    if val and str(val).strip():
                        original_candidates.append(str(val).strip())

                if not original_candidates and not vendor_no:
                    continue

                try:
                    # Expand PO candidates with enhanced intelligence
                    expanded = await enhance_po_candidates(db, vendor_no, original_candidates)

                    # Also apply PO format learning transformations
                    try:
                        from services.po_format_learning_service import get_smart_po_candidates
                        for base_po in original_candidates[:3]:
                            smart = await get_smart_po_candidates(db, vendor_no, base_po)
                            for s in smart:
                                if s not in expanded:
                                    expanded.append(s)
                    except Exception:
                        pass

                    # ── NEW: Learn vendor's PO format from BC cache and try to transform ──
                    if vendor_no:
                        try:
                            # Get sample POs from cache for this vendor
                            cached_vendor_pos = await db.bc_reference_cache.find(
                                {"bc_vendor_no": vendor_no, "bc_entity_type": "purchase_order"},
                                {"_id": 0, "bc_document_no": 1}
                            ).limit(20).to_list(20)
                            cached_po_numbers = [r["bc_document_no"] for r in cached_vendor_pos if r.get("bc_document_no")]

                            if cached_po_numbers:
                                # For each original candidate, try to find a cached PO that shares digits
                                for cand in original_candidates[:5]:
                                    cand_digits = re.sub(r'[^0-9]', '', cand)
                                    if len(cand_digits) >= 4:
                                        for cached_po in cached_po_numbers:
                                            cached_digits = re.sub(r'[^0-9]', '', cached_po)
                                            # Substring match: candidate digits appear in cached PO
                                            if cand_digits in cached_digits or cached_digits in cand_digits:
                                                if cached_po not in expanded:
                                                    expanded.append(cached_po)
                                            # Same digits, different format
                                            elif cand_digits == cached_digits and cached_po not in expanded:
                                                expanded.append(cached_po)
                        except Exception:
                            pass

                    # Deduplicate against already-tried POs
                    already_tried = set()
                    for check in validation.get("checks", []):
                        if check.get("check_name") == "po_validation":
                            details = check.get("details", "")
                            if "'" in details:
                                parts = details.split("'")
                                if len(parts) >= 2:
                                    already_tried.add(parts[1])

                    new_candidates = [p for p in expanded if p not in already_tried]
                    if not new_candidates:
                        continue

                    # ── NEW: Cache-first PO lookup (much faster than BC API) ──
                    matched_po = None
                    for candidate in new_candidates:
                        try:
                            normalized = normalize_document_no(candidate)
                            if not normalized:
                                continue
                            cache_hit = await db.bc_reference_cache.find_one(
                                {
                                    "$or": [
                                        {"normalized_document_no": normalized, "bc_entity_type": "purchase_order"},
                                        {"bc_document_no": candidate.strip(), "bc_entity_type": "purchase_order"},
                                    ]
                                },
                                {"_id": 0, "bc_document_no": 1}
                            )
                            if cache_hit:
                                matched_po = cache_hit.get("bc_document_no", candidate)
                                logger.info("[PO-Reval] Cache hit for PO '%s' → %s", candidate, matched_po)
                                cache_resolved += 1
                                break
                        except Exception:
                            continue

                    # Fallback: BC API lookup for candidates not in cache
                    if not matched_po:
                        for candidate in new_candidates[:10]:
                            try:
                                resp = await c.get(
                                    adapter.api_url("purchaseOrders", company_id),
                                    headers={"Authorization": f"Bearer {token}"},
                                    params={"$filter": f"number eq '{candidate.replace(chr(39), chr(39)+chr(39))}'"},
                                )
                                if resp.status_code == 200:
                                    pos = resp.json().get("value", [])
                                    if pos:
                                        matched_po = candidate
                                        break
                            except Exception:
                                continue

                    if matched_po:
                        new_checks = [
                            ch for ch in validation.get("checks", [])
                            if ch.get("check_name") != "po_validation"
                        ]
                        new_checks.append({
                            "check_name": "po_validation",
                            "passed": True,
                            "details": f"Found PO: {matched_po} (re-validated via enhanced intelligence)",
                            "required": True,
                        })

                        all_passed = all(ch.get("passed", True) for ch in new_checks)

                        await db.hub_documents.update_one(
                            {"id": doc_id},
                            {"$set": {
                                "validation_results.checks": new_checks,
                                "validation_results.all_passed": all_passed,
                                "validation_results.po_match": True,
                                "validation_results.matched_po": matched_po,
                                "po_revalidated_at": _now(),
                                "po_revalidated_via": "intelligence_backfill",
                                "extracted_fields.po_number": matched_po,
                            }}
                        )
                        await db.validation_gap_log.delete_many({"doc_id": doc_id, "failure_checks": "po_validation"})

                        resolved += 1
                        bc_resolved += 1
                        logger.info(
                            "[PO-Reval] doc=%s vendor=%s — RESOLVED with PO '%s'",
                            doc_id[:8], vendor_no, matched_po,
                        )
                except Exception as e:
                    errors += 1
                    logger.debug("[PO-Reval] Error for %s: %s", doc_id[:8], e)

    logger.info(
        "[PO-Reval] Batch complete: %d found, %d resolved (%d profile, %d cache, %d BC, %d unknown-vendor-resolved), %d errors",
        len(po_gap_docs), resolved, skipped_by_profile, cache_resolved, bc_resolved - cache_resolved, unknown_resolved, errors,
    )
    return {
        "found": len(po_gap_docs),
        "resolved": resolved,
        "skipped_by_profile": skipped_by_profile,
        "cache_resolved": cache_resolved,
        "bc_matched": bc_resolved,
        "unknown_vendor_resolved": unknown_resolved,
        "errors": errors,
    }


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

