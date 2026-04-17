"""
Sales Dashboard Router — Orders Awaiting Review + Inside Sales Rep Review

Provides a lightweight, role-oriented API for the Sales dashboard:
  GET  /sales-dashboard/queue        — all sales-eligible docs with readiness status
  GET  /sales-dashboard/summary      — summary counts only (fast)
  GET  /sales-dashboard/reps         — list available sales reps for dropdown
  GET  /sales-dashboard/my-queue     — docs assigned to a specific rep
  GET  /sales-dashboard/triage-queue — docs with no rep assigned
  POST /sales-dashboard/queue/{id}/approve — rep approves doc
  POST /sales-dashboard/queue/{id}/flag    — rep flags doc with notes
  POST /sales-dashboard/queue/{id}/assign  — manually assign rep to doc
  POST /sales-dashboard/seed-review-data   — seed test data for dev
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Query, Body
from pydantic import BaseModel
from deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sales-dashboard", tags=["Sales Dashboard"])

SALES_ELIGIBLE_TYPES = {"Sales_Order", "SalesOrder", "Order_Confirmation", "PurchaseOrder", "Purchase_Order"}

# Sales review statuses used by the Inside Sales Rep Review flow
REVIEW_STATUSES = {
    "pending_rep_review",   # Assigned to rep, waiting for review
    "approved",             # Rep approved → ready for BC SO creation
    "flagged",              # Rep flagged → needs attention
    "auto_approved",        # High confidence, auto-sent to BC
    "triage",               # No rep found, needs manual assignment
}


async def _assess_readiness(doc: dict) -> dict:
    """Lightweight readiness assessment without running full preflight.
    Returns {status, readiness, warnings, customer_no, customer_name, ...}.
    """
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}

    # Already created?
    bc_so = doc.get("bc_sales_order")
    if bc_so:
        return {
            "status": "already_created",
            "readiness": "created",
            "bc_record_no": bc_so.get("bc_record_no", ""),
            "bc_created_at": bc_so.get("created_at", ""),
            "bc_lines_added": bc_so.get("lines_added", 0),
            "bc_lines_total": bc_so.get("lines_total", 0),
            "customer_no": bc_so.get("customer_no", ""),
            "customer_name": bc_so.get("customer_name", ""),
            "external_doc_no": bc_so.get("external_doc_no", ""),
            "order_date": bc_so.get("order_date", ""),
            "amount": (doc.get("normalized_fields") or {}).get("amount") or (doc.get("extracted_fields") or {}).get("amount"),
            "line_count": bc_so.get("lines_total", 0),
            "warnings": [],
            "blocking_issues": [],
        }

    warnings = []
    blocking = []

    # ── Customer resolution: use the unified service ──
    from services.entity_resolution_service import resolve_customer
    cr = await resolve_customer(doc)
    customer_no = cr.customer_no
    customer_name = cr.customer_name

    if not customer_no:
        blocking.append("Customer not resolved")

    # External doc / PO
    external_doc_no = ef.get("po_number") or nf.get("po_number") or ""
    if not external_doc_no:
        warnings.append("No PO number")

    # Line items
    line_items = ef.get("line_items") or []
    has_lines = len(line_items) > 0
    amount = nf.get("amount") or ef.get("amount")
    if not has_lines and not amount:
        blocking.append("No line items or amount")
    elif not has_lines:
        warnings.append("No line items (amount-only fallback)")

    # Order date
    order_date = ef.get("order_date") or nf.get("order_date") or ""
    if not order_date:
        warnings.append("No order date")

    # Determine status
    if blocking:
        status = "needs_review"
        readiness = "blocked"
    elif warnings:
        status = "ready_warnings"
        readiness = "ready_with_warnings"
    else:
        status = "ready"
        readiness = "ready"

    return {
        "status": status,
        "readiness": readiness,
        "customer_no": customer_no,
        "customer_name": customer_name,
        "external_doc_no": external_doc_no,
        "order_date": order_date,
        "amount": amount,
        "line_count": len(line_items),
        "bc_record_no": "",
        "bc_created_at": "",
        "bc_lines_added": 0,
        "bc_lines_total": 0,
        "warnings": warnings,
        "blocking_issues": blocking,
    }


@router.get("/queue")
async def sales_queue(
    status: str = Query("", description="Filter: ready|ready_warnings|needs_review|already_created"),
    customer: str = Query("", description="Filter by customer name (partial match)"),
    search: str = Query("", description="Search filename/PO/customer"),
    has_bc_order: str = Query("", description="yes|no — filter by created status"),
    sort: str = Query("created_desc", description="Sort: created_desc|created_asc|amount_desc|amount_asc"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """Return sales-eligible documents with lightweight readiness assessment."""
    db = get_db()

    # Base query: only sales-eligible document types
    query = {"document_type": {"$in": list(SALES_ELIGIBLE_TYPES)}}

    # Pre-filter by BC order existence
    if has_bc_order == "yes":
        query["bc_sales_order"] = {"$exists": True, "$ne": None}
    elif has_bc_order == "no":
        query["$or"] = [
            {"bc_sales_order": {"$exists": False}},
            {"bc_sales_order": None},
        ]

    # Text search
    if search:
        query["$or"] = [
            {"file_name": {"$regex": search, "$options": "i"}},
            {"extracted_fields.po_number": {"$regex": search, "$options": "i"}},
            {"normalized_fields.customer_name": {"$regex": search, "$options": "i"}},
            {"extracted_fields.customer_name": {"$regex": search, "$options": "i"}},
            {"vendor_name": {"$regex": search, "$options": "i"}},
        ]

    if customer:
        cust_filter = {"$regex": customer, "$options": "i"}
        if "$or" in query:
            existing_or = query.pop("$or")
            query["$and"] = [
                {"$or": existing_or},
                {"$or": [
                    {"normalized_fields.customer_name": cust_filter},
                    {"extracted_fields.customer_name": cust_filter},
                    {"extracted_fields.company_name": cust_filter},
                    {"vendor_name": cust_filter},
                ]},
            ]
        else:
            query["$or"] = [
                {"normalized_fields.customer_name": cust_filter},
                {"extracted_fields.customer_name": cust_filter},
                {"extracted_fields.company_name": cust_filter},
                {"vendor_name": cust_filter},
            ]

    # Sort
    sort_map = {
        "created_desc": [("created_utc", -1)],
        "created_asc": [("created_utc", 1)],
        "amount_desc": [("normalized_fields.amount", -1)],
        "amount_asc": [("normalized_fields.amount", 1)],
    }
    sort_spec = sort_map.get(sort, [("created_utc", -1)])

    total = await db.hub_documents.count_documents(query)
    cursor = db.hub_documents.find(query, {"_id": 0}).sort(sort_spec).skip(skip).limit(limit)
    docs = await cursor.to_list(limit)

    # Assess readiness for each doc
    items = []
    for doc in docs:
        assessment = await _assess_readiness(doc)

        # Post-filter by status if requested
        if status and assessment["status"] != status:
            continue

        items.append({
            "id": doc.get("id", ""),
            "file_name": doc.get("file_name", ""),
            "document_type": doc.get("document_type", ""),
            "created_utc": doc.get("created_utc", ""),
            "capture_channel": doc.get("capture_channel", ""),
            **assessment,
        })

    # Summary counts (from full dataset, not paginated)
    summary = await _compute_summary(db)

    return {
        "items": items,
        "total": total,
        "filtered_count": len(items),
        "skip": skip,
        "limit": limit,
        "summary": summary,
    }


@router.get("/summary")
async def sales_summary():
    """Fast summary counts for dashboard cards."""
    db = get_db()
    return await _compute_summary(db)


async def _compute_summary(db) -> dict:
    """Compute summary counts across all sales-eligible docs."""
    query = {"document_type": {"$in": list(SALES_ELIGIBLE_TYPES)}}
    all_docs = await db.hub_documents.find(
        query,
        {"_id": 0, "id": 1, "extracted_fields": 1, "normalized_fields": 1,
         "bc_sales_order": 1, "vendor_name": 1, "document_type": 1,
         "sales_pilot_extraction": 1, "bc_prod_validation": 1,
         "spiro_match": 1, "vendor_canonical": 1, "matched_customer_no": 1,
         "customer_no": 1, "inside_sales_pilot": 1, "batch_parent_id": 1,
         "validation_results": 1, "customer_extracted": 1, "source": 1}
    ).to_list(500)

    counts = {"ready": 0, "ready_warnings": 0, "needs_review": 0, "already_created": 0, "total": len(all_docs)}
    for doc in all_docs:
        a = await _assess_readiness(doc)
        counts[a["status"]] = counts.get(a["status"], 0) + 1

    return counts


@router.delete("/queue/clear")
async def clear_sales_queue():
    """
    Remove all sales-eligible documents from hub_documents.
    This clears the Sales Orders queue completely.
    """
    db = get_db()
    query = {"document_type": {"$in": list(SALES_ELIGIBLE_TYPES)}}
    result = await db.hub_documents.delete_many(query)
    deleted = result.deleted_count
    logger.info("Cleared sales queue: %d documents removed", deleted)
    return {"deleted": deleted, "message": f"Cleared {deleted} sales documents from queue"}


# ═══════════════════════════════════════════════════════════════════
# INSIDE SALES REP REVIEW — New endpoints
# ═══════════════════════════════════════════════════════════════════

class FlagRequest(BaseModel):
    notes: str = ""

class AssignRequest(BaseModel):
    rep_email: str
    rep_name: str = ""


@router.get("/reps")
async def list_reps():
    """List available sales reps from BC cache + overrides.
    Used to populate the 'Select Rep' dropdown.
    """
    db = get_db()
    reps = []
    seen_emails = set()

    # 1. From BC salesperson cache
    sp_records = await db.bc_reference_cache.find(
        {"bc_entity_type": "salesperson"},
        {"_id": 0, "code": 1, "name": 1, "email": 1},
    ).to_list(200)
    for sp in sp_records:
        email = sp.get("email", "")
        if email and email not in seen_emails:
            reps.append({
                "rep_email": email,
                "rep_name": sp.get("name", ""),
                "salesperson_code": sp.get("code", ""),
                "source": "bc_cache",
            })
            seen_emails.add(email)

    # 2. From customer_rep_overrides
    overrides = await db.customer_rep_overrides.find(
        {"active": True}, {"_id": 0}
    ).to_list(500)
    for ov in overrides:
        email = ov.get("rep_email", "")
        if email and email not in seen_emails:
            reps.append({
                "rep_email": email,
                "rep_name": ov.get("rep_name", ""),
                "salesperson_code": ov.get("salesperson_code", ""),
                "source": "override",
            })
            seen_emails.add(email)

    # 3. From documents that already have an assigned rep
    pipeline = [
        {"$match": {"assigned_rep_email": {"$exists": True, "$ne": ""}}},
        {"$group": {
            "_id": "$assigned_rep_email",
            "rep_name": {"$first": "$assigned_rep_name"},
        }},
    ]
    from_docs = await db.hub_documents.aggregate(pipeline).to_list(100)
    for d in from_docs:
        email = d["_id"]
        if email and email not in seen_emails:
            reps.append({
                "rep_email": email,
                "rep_name": d.get("rep_name") or "",
                "salesperson_code": "",
                "source": "document",
            })
            seen_emails.add(email)

    reps.sort(key=lambda r: r["rep_name"] or r["rep_email"])
    return {"reps": reps, "count": len(reps)}


@router.get("/my-queue")
async def my_queue(
    rep_email: str = Query(..., description="Rep email to filter by"),
    status: str = Query("", description="Filter: pending_rep_review|approved|flagged"),
    search: str = Query("", description="Search filename/PO/customer"),
    sort: str = Query("created_desc"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """Return documents assigned to a specific sales rep."""
    db = get_db()

    query = {
        "document_type": {"$in": list(SALES_ELIGIBLE_TYPES)},
        "assigned_rep_email": rep_email,
    }

    if status:
        query["sales_review_status"] = status

    if search:
        query["$or"] = [
            {"file_name": {"$regex": search, "$options": "i"}},
            {"extracted_fields.po_number": {"$regex": search, "$options": "i"}},
            {"normalized_fields.customer_name": {"$regex": search, "$options": "i"}},
            {"extracted_fields.customer_name": {"$regex": search, "$options": "i"}},
            {"vendor_name": {"$regex": search, "$options": "i"}},
        ]

    sort_map = {
        "created_desc": [("created_utc", -1)],
        "created_asc": [("created_utc", 1)],
        "amount_desc": [("normalized_fields.amount", -1)],
        "amount_asc": [("normalized_fields.amount", 1)],
    }
    sort_spec = sort_map.get(sort, [("created_utc", -1)])

    total = await db.hub_documents.count_documents(query)
    cursor = db.hub_documents.find(query, {"_id": 0}).sort(sort_spec).skip(skip).limit(limit)
    docs = await cursor.to_list(limit)

    items = []
    for doc in docs:
        assessment = await _assess_readiness(doc)
        items.append({
            "id": doc.get("id", ""),
            "file_name": doc.get("file_name", ""),
            "document_type": doc.get("document_type", ""),
            "created_utc": doc.get("created_utc", ""),
            "capture_channel": doc.get("capture_channel", ""),
            "assigned_rep_email": doc.get("assigned_rep_email", ""),
            "assigned_rep_name": doc.get("assigned_rep_name", ""),
            "sales_review_status": doc.get("sales_review_status", "pending_rep_review"),
            "flag_notes": doc.get("flag_notes", ""),
            **assessment,
        })

    # Summary counts for this rep
    rep_summary = {"pending_rep_review": 0, "approved": 0, "flagged": 0, "total": total}
    count_pipeline = [
        {"$match": {"document_type": {"$in": list(SALES_ELIGIBLE_TYPES)}, "assigned_rep_email": rep_email}},
        {"$group": {"_id": "$sales_review_status", "count": {"$sum": 1}}},
    ]
    for r in await db.hub_documents.aggregate(count_pipeline).to_list(10):
        key = r["_id"] or "pending_rep_review"
        if key in rep_summary:
            rep_summary[key] = r["count"]

    return {
        "items": items,
        "total": total,
        "filtered_count": len(items),
        "skip": skip,
        "limit": limit,
        "rep_email": rep_email,
        "summary": rep_summary,
    }


@router.get("/triage-queue")
async def triage_queue(
    search: str = Query("", description="Search filename/PO/customer"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """Return sales-eligible documents with no rep assigned (triage queue)."""
    db = get_db()

    query = {
        "document_type": {"$in": list(SALES_ELIGIBLE_TYPES)},
        "$or": [
            {"assigned_rep_email": {"$exists": False}},
            {"assigned_rep_email": ""},
            {"assigned_rep_email": None},
        ],
    }

    # Also include those explicitly in triage status
    query_triage = {
        "document_type": {"$in": list(SALES_ELIGIBLE_TYPES)},
        "sales_review_status": "triage",
    }

    combined_query = {"$or": [query, query_triage]}

    if search:
        combined_query = {
            "$and": [
                combined_query,
                {"$or": [
                    {"file_name": {"$regex": search, "$options": "i"}},
                    {"extracted_fields.po_number": {"$regex": search, "$options": "i"}},
                    {"vendor_name": {"$regex": search, "$options": "i"}},
                ]},
            ]
        }

    total = await db.hub_documents.count_documents(combined_query)
    cursor = db.hub_documents.find(combined_query, {"_id": 0}).sort([("created_utc", -1)]).skip(skip).limit(limit)
    docs = await cursor.to_list(limit)

    items = []
    for doc in docs:
        assessment = await _assess_readiness(doc)
        items.append({
            "id": doc.get("id", ""),
            "file_name": doc.get("file_name", ""),
            "document_type": doc.get("document_type", ""),
            "created_utc": doc.get("created_utc", ""),
            "capture_channel": doc.get("capture_channel", ""),
            "sales_review_status": doc.get("sales_review_status", "triage"),
            **assessment,
        })

    return {"items": items, "total": total, "filtered_count": len(items), "skip": skip, "limit": limit}


@router.post("/queue/{doc_id}/approve")
async def approve_document(doc_id: str):
    """Rep approves a document → mark as approved, ready for BC SO creation."""
    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "id": 1, "sales_review_status": 1})
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Document not found")

    now = datetime.now(timezone.utc).isoformat()
    action_entry = {
        "action": "approved",
        "at": now,
        "by": "rep",
    }

    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "sales_review_status": "approved",
                "approved_at": now,
                "updated_utc": now,
            },
            "$push": {"sales_review_history": action_entry},
        },
    )

    logger.info("[SalesReview] Document %s APPROVED", doc_id)
    return {"status": "approved", "doc_id": doc_id, "approved_at": now}


@router.post("/queue/{doc_id}/flag")
async def flag_document(doc_id: str, body: FlagRequest):
    """Rep flags a document for attention → stays in queue with notes."""
    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "id": 1})
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Document not found")

    now = datetime.now(timezone.utc).isoformat()
    action_entry = {
        "action": "flagged",
        "at": now,
        "by": "rep",
        "notes": body.notes,
    }

    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "sales_review_status": "flagged",
                "flag_notes": body.notes,
                "flagged_at": now,
                "updated_utc": now,
            },
            "$push": {"sales_review_history": action_entry},
        },
    )

    logger.info("[SalesReview] Document %s FLAGGED: %s", doc_id, body.notes[:100])
    return {"status": "flagged", "doc_id": doc_id, "notes": body.notes, "flagged_at": now}


@router.post("/queue/{doc_id}/assign")
async def assign_document(doc_id: str, body: AssignRequest):
    """Manually assign a rep to a document (triage action)."""
    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "id": 1})
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Document not found")

    now = datetime.now(timezone.utc).isoformat()
    action_entry = {
        "action": "assigned",
        "at": now,
        "rep_email": body.rep_email,
        "rep_name": body.rep_name,
    }

    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "assigned_rep_email": body.rep_email,
                "assigned_rep_name": body.rep_name,
                "sales_review_status": "pending_rep_review",
                "updated_utc": now,
            },
            "$push": {"sales_review_history": action_entry},
        },
    )

    logger.info("[SalesReview] Document %s ASSIGNED to %s <%s>", doc_id, body.rep_name, body.rep_email)
    return {"status": "assigned", "doc_id": doc_id, "rep_email": body.rep_email, "rep_name": body.rep_name}


class ReviewActionRequest(BaseModel):
    action: str  # "approve" or "flag"
    reason: str = ""


@router.post("/review/{doc_id}")
async def review_document(doc_id: str, body: ReviewActionRequest):
    """Unified review action endpoint for the SalesOrderReviewPage.
    Supports both approve and flag actions in a single endpoint.
    """
    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "id": 1, "sales_review_status": 1})
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Document not found")

    now = datetime.now(timezone.utc).isoformat()

    if body.action == "approve":
        action_entry = {
            "action": "approved",
            "at": now,
            "by": "rep",
        }
        await db.hub_documents.update_one(
            {"id": doc_id},
            {
                "$set": {
                    "sales_review_status": "approved",
                    "approved_at": now,
                    "updated_utc": now,
                },
                "$push": {"sales_review_history": action_entry},
            },
        )
        logger.info("[SalesReview] Document %s APPROVED via review endpoint", doc_id)
        return {"status": "approved", "doc_id": doc_id, "approved_at": now}

    elif body.action == "flag":
        action_entry = {
            "action": "flagged",
            "at": now,
            "by": "rep",
            "notes": body.reason,
        }
        await db.hub_documents.update_one(
            {"id": doc_id},
            {
                "$set": {
                    "sales_review_status": "flagged",
                    "sales_flag_reason": body.reason,
                    "flag_notes": body.reason,
                    "flagged_at": now,
                    "updated_utc": now,
                },
                "$push": {"sales_review_history": action_entry},
            },
        )
        logger.info("[SalesReview] Document %s FLAGGED via review endpoint: %s", doc_id, body.reason[:100])
        return {"status": "flagged", "doc_id": doc_id, "reason": body.reason, "flagged_at": now}

    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Invalid action: {body.action}. Must be 'approve' or 'flag'.")


@router.post("/seed-review-data")
async def seed_review_data():
    """Seed rich, production-realistic demo data for the Inside Sales Rep Review feature.
    Creates realistic sales documents, rep assignments, overrides, and audit trails.
    """
    db = get_db()
    import random
    random.seed(42)  # Reproducible demo data

    now = datetime.now(timezone.utc)

    # ── Sales Reps ──
    reps = [
        {"email": "jsmith@gamerpackaging.com", "name": "John Smith", "code": "JS", "region": "West Coast"},
        {"email": "mgarcia@gamerpackaging.com", "name": "Maria Garcia", "code": "MG", "region": "Southwest"},
        {"email": "bwilson@gamerpackaging.com", "name": "Bob Wilson", "code": "BW", "region": "Midwest"},
        {"email": "lchen@gamerpackaging.com", "name": "Lisa Chen", "code": "LC", "region": "Northeast"},
    ]

    # ── Real GPI customers (realistic packaging industry names) ──
    customers = [
        {"no": "C-10147", "name": "Bragg Live Food Products, LLC", "city": "Santa Barbara, CA", "rep_idx": 0},
        {"no": "C-10203", "name": "Palmer's (ET Browne Drug Co.)", "city": "Englewood Cliffs, NJ", "rep_idx": 3},
        {"no": "C-10089", "name": "Karlin Foods International", "city": "Vernon, CA", "rep_idx": 0},
        {"no": "C-10312", "name": "House of Wines Inc.", "city": "City of Industry, CA", "rep_idx": 0},
        {"no": "C-10455", "name": "Wing Nien Foods Mfg.", "city": "San Francisco, CA", "rep_idx": 0},
        {"no": "C-10521", "name": "Pacific Coast Producers", "city": "Woodland, CA", "rep_idx": 1},
        {"no": "C-10678", "name": "Bob's Red Mill Natural Foods", "city": "Milwaukie, OR", "rep_idx": 2},
        {"no": "C-10734", "name": "Huy Fong Foods Inc.", "city": "Irwindale, CA", "rep_idx": 1},
        {"no": "C-10802", "name": "Spectrum Brands (United Pet)", "city": "Blacksburg, VA", "rep_idx": 2},
        {"no": "C-10999", "name": "Nature's Path Foods", "city": "Richmond, BC", "rep_idx": 3},
        {"no": "C-11023", "name": "Stonewall Kitchen", "city": "York, ME", "rep_idx": 3},
        {"no": "C-11150", "name": "Tillamook Creamery", "city": "Tillamook, OR", "rep_idx": 2},
        {"no": "C-10250", "name": "Giovanni Food Co., Inc.", "city": "Baldwinsville, NY", "rep_idx": 3},
    ]

    # ── Realistic PO scenarios ──
    scenarios = [
        # (status, flag_notes, channel, hours_ago, confidence, doc_type)
        # John Smith's queue — mix of pending, flagged, approved
        {"rep": 0, "cust": 0, "status": "pending_rep_review", "flag": "", "channel": "email",
         "hours": 2, "conf": 0.92, "type": "PurchaseOrder", "po": "PO-2026-4471",
         "amount": 18750.00, "lines": 4, "ship": "Drop Ship"},
        {"rep": 0, "cust": 2, "status": "pending_rep_review", "flag": "", "channel": "email",
         "hours": 5, "conf": 0.88, "type": "Sales_Order", "po": "SO-KF-8832",
         "amount": 42100.50, "lines": 8, "ship": "Warehouse"},
        {"rep": 0, "cust": 3, "status": "flagged",
         "flag": "Customer called — wants to change ship-to from Vernon warehouse to new Rancho Cucamonga facility. Need updated address before creating SO.",
         "channel": "email", "hours": 8, "conf": 0.85, "type": "PurchaseOrder", "po": "HW-PO-1122",
         "amount": 7890.00, "lines": 2, "ship": "Drop Ship"},
        {"rep": 0, "cust": 4, "status": "pending_rep_review", "flag": "", "channel": "SHADOW_PILOT_UPLOAD",
         "hours": 12, "conf": 0.94, "type": "Order_Confirmation", "po": "WNF-OC-5567",
         "amount": 31200.00, "lines": 6, "ship": "Drop Ship"},
        {"rep": 0, "cust": 0, "status": "approved", "flag": "", "channel": "email",
         "hours": 26, "conf": 0.96, "type": "PurchaseOrder", "po": "PO-2026-4398",
         "amount": 12450.00, "lines": 3, "ship": "Warehouse"},
        {"rep": 0, "cust": 2, "status": "approved", "flag": "", "channel": "email",
         "hours": 48, "conf": 0.91, "type": "Sales_Order", "po": "SO-KF-8790",
         "amount": 56780.25, "lines": 12, "ship": "Warehouse"},
        {"rep": 0, "cust": 4, "status": "flagged",
         "flag": "PO amount doesn't match quote Q-2026-889. Customer quoted $24,500 but PO shows $26,100. Need to verify with buyer before approving.",
         "channel": "email", "hours": 36, "conf": 0.87, "type": "PurchaseOrder", "po": "WNF-PO-3301",
         "amount": 26100.00, "lines": 5, "ship": "Drop Ship"},

        # Maria Garcia's queue
        {"rep": 1, "cust": 5, "status": "pending_rep_review", "flag": "", "channel": "email",
         "hours": 1, "conf": 0.93, "type": "PurchaseOrder", "po": "PCP-45821",
         "amount": 89500.00, "lines": 15, "ship": "Warehouse"},
        {"rep": 1, "cust": 7, "status": "pending_rep_review", "flag": "", "channel": "email",
         "hours": 3, "conf": 0.90, "type": "Sales_Order", "po": "HFF-SO-2026-112",
         "amount": 145000.00, "lines": 22, "ship": "Warehouse"},
        {"rep": 1, "cust": 5, "status": "flagged",
         "flag": "Rush order — customer needs delivery by Friday. Standard lead time is 10 days. Check if we have stock in LA warehouse.",
         "channel": "SHADOW_PILOT_UPLOAD", "hours": 6, "conf": 0.89, "type": "PurchaseOrder", "po": "PCP-45799-RUSH",
         "amount": 34200.00, "lines": 4, "ship": "Drop Ship"},
        {"rep": 1, "cust": 7, "status": "approved", "flag": "", "channel": "email",
         "hours": 30, "conf": 0.95, "type": "PurchaseOrder", "po": "HFF-PO-2026-098",
         "amount": 67800.00, "lines": 10, "ship": "Warehouse"},
        {"rep": 1, "cust": 7, "status": "pending_rep_review", "flag": "", "channel": "email",
         "hours": 4, "conf": 0.91, "type": "Order_Confirmation", "po": "HFF-OC-2026-115",
         "amount": 52300.00, "lines": 8, "ship": "Drop Ship"},

        # Bob Wilson's queue
        {"rep": 2, "cust": 6, "status": "pending_rep_review", "flag": "", "channel": "email",
         "hours": 2, "conf": 0.96, "type": "PurchaseOrder", "po": "BRM-PO-78234",
         "amount": 28900.00, "lines": 6, "ship": "Warehouse"},
        {"rep": 2, "cust": 8, "status": "pending_rep_review", "flag": "", "channel": "email",
         "hours": 7, "conf": 0.82, "type": "Sales_Order", "po": "SB-UP-2026-445",
         "amount": 19600.00, "lines": 3, "ship": "Drop Ship"},
        {"rep": 2, "cust": 11, "status": "flagged",
         "flag": "Duplicate PO? We received TC-PO-9921 last week and it was already approved. Customer may have re-sent. Verify before creating a second SO.",
         "channel": "email", "hours": 10, "conf": 0.78, "type": "PurchaseOrder", "po": "TC-PO-9921",
         "amount": 41500.00, "lines": 7, "ship": "Warehouse"},
        {"rep": 2, "cust": 6, "status": "approved", "flag": "", "channel": "email",
         "hours": 52, "conf": 0.94, "type": "PurchaseOrder", "po": "BRM-PO-78190",
         "amount": 15300.00, "lines": 4, "ship": "Warehouse"},
        {"rep": 2, "cust": 11, "status": "pending_rep_review", "flag": "", "channel": "SHADOW_PILOT_UPLOAD",
         "hours": 14, "conf": 0.86, "type": "Order_Confirmation", "po": "TC-OC-2026-330",
         "amount": 73200.00, "lines": 11, "ship": "Warehouse"},

        # Lisa Chen's queue
        {"rep": 3, "cust": 1, "status": "pending_rep_review", "flag": "", "channel": "email",
         "hours": 1, "conf": 0.91, "type": "PurchaseOrder", "po": "PLM-PO-2026-5544",
         "amount": 95400.00, "lines": 18, "ship": "Warehouse"},
        {"rep": 3, "cust": 9, "status": "pending_rep_review", "flag": "", "channel": "email",
         "hours": 4, "conf": 0.88, "type": "Sales_Order", "po": "NP-SO-CA-7721",
         "amount": 63100.00, "lines": 9, "ship": "Drop Ship"},
        {"rep": 3, "cust": 10, "status": "flagged",
         "flag": "New customer — no BC record yet. Need to create customer card in Business Central before we can generate the Sales Order. AR team notified.",
         "channel": "email", "hours": 9, "conf": 0.84, "type": "PurchaseOrder", "po": "SK-PO-NEW-001",
         "amount": 8750.00, "lines": 2, "ship": "Drop Ship"},
        {"rep": 3, "cust": 1, "status": "approved", "flag": "", "channel": "email",
         "hours": 40, "conf": 0.97, "type": "PurchaseOrder", "po": "PLM-PO-2026-5501",
         "amount": 112000.00, "lines": 24, "ship": "Warehouse"},
        {"rep": 3, "cust": 9, "status": "pending_rep_review", "flag": "", "channel": "SHADOW_PILOT_UPLOAD",
         "hours": 16, "conf": 0.90, "type": "Order_Confirmation", "po": "NP-OC-CA-7718",
         "amount": 47800.00, "lines": 7, "ship": "Warehouse"},

        # Giovanni Food Co. — mirrors real PO-61312
        {"rep": 3, "cust": 12, "status": "pending_rep_review", "flag": "", "channel": "email",
         "hours": 3, "conf": 0.98, "type": "Purchase_Order", "po": "PO-61312",
         "amount": 14568.43, "lines": 1, "ship": "Outbound Freight"},
        {"rep": 3, "cust": 12, "status": "pending_rep_review", "flag": "", "channel": "email",
         "hours": 3, "conf": 0.97, "type": "Purchase_Order", "po": "PO-61325",
         "amount": 22340.00, "lines": 2, "ship": "Outbound Freight"},
        {"rep": 3, "cust": 12, "status": "flagged",
         "flag": "Batch PO 61312-61361 received as single PDF (47 pages). Need to split and verify each PO against BC. PO-61340 line items don't match quote.",
         "channel": "email", "hours": 5, "conf": 0.95, "type": "Purchase_Order", "po": "PO-61340",
         "amount": 8925.00, "lines": 1, "ship": "Outbound Freight"},
    ]

    # ── Build documents ──
    sample_docs = []
    item_names = [
        "12oz Clear PET Bottle", "16oz HDPE Jar", "Shrink Sleeve Label (4-color)",
        "Corrugated Shipper 24-ct", "6-pack Carrier", "Tamper-Evident Cap 38mm",
        "Custom Printed Film Roll", "Stand-Up Pouch 8oz", "Clamshell Blister Pack",
        "Kraft Mailer Box 10x8x4", "Poly Bag 2mil", "Foam Cushion Insert",
        "Glass Bottle 750ml", "Metal Tin 4oz Round", "Paperboard Folding Carton",
        "Corrugated Display Shipper", "Blister Card 6x9", "Vacuum Pouch 12x16",
    ]

    for s in scenarios:
        rep = reps[s["rep"]]
        cust = customers[s["cust"]]
        created = (now - timedelta(hours=s["hours"])).isoformat()

        # Build realistic line items
        num_lines = s["lines"]
        line_total = s["amount"]
        lines = []
        for li in range(num_lines):
            item = item_names[(s["cust"] + li) % len(item_names)]
            qty = random.choice([500, 1000, 2000, 2500, 5000, 10000, 15000, 25000])
            unit_price = round(line_total / num_lines / qty * random.uniform(0.8, 1.2), 4)
            lines.append({
                "line_no": li + 1,
                "item_no": f"PKG-{1000 + (s['cust'] * 10 + li)}",
                "description": item,
                "quantity": qty,
                "unit_price": unit_price,
                "line_amount": round(qty * unit_price, 2),
                "uom": "EA",
            })

        history = []
        if s["status"] == "approved":
            history.append({"action": "auto_assigned", "at": (now - timedelta(hours=s["hours"] + 2)).isoformat(),
                            "by": "system", "rep_email": rep["email"], "source": "bc_cache"})
            history.append({"action": "approved", "at": (now - timedelta(hours=s["hours"] - 4)).isoformat(),
                            "by": rep["email"]})
        elif s["status"] == "flagged":
            history.append({"action": "auto_assigned", "at": (now - timedelta(hours=s["hours"] + 1)).isoformat(),
                            "by": "system", "rep_email": rep["email"], "source": "bc_cache"})
            history.append({"action": "flagged", "at": (now - timedelta(hours=s["hours"] - 1)).isoformat(),
                            "by": rep["email"], "notes": s["flag"]})
        else:
            history.append({"action": "auto_assigned", "at": created,
                            "by": "system", "rep_email": rep["email"], "source": "bc_cache"})

        doc = {
            "id": str(uuid.uuid4()),
            "file_name": f"{s['po']}.pdf",
            "document_type": s["type"],
            "created_utc": created,
            "updated_utc": created,
            "capture_channel": s["channel"],
            "email_sender": f"purchasing@{cust['name'].split()[0].lower().replace(',','').replace('.','')}.com",
            "status": "ready" if s["status"] == "approved" else "pending",
            "assigned_rep_email": rep["email"],
            "assigned_rep_name": rep["name"],
            "assigned_salesperson_code": rep["code"],
            "sales_review_status": s["status"],
            "rep_assignment_source": "bc_cache",
            "rep_assigned_utc": created,
            "flag_notes": s["flag"],
            "sales_review_history": history,
            "extracted_fields": {
                "po_number": s["po"],
                "customer_name": cust["name"],
                "customer_no": cust["no"],
                "order_date": (now - timedelta(hours=s["hours"])).strftime("%m/%d/%Y"),
                "amount": str(s["amount"]),
                "ship_to_city": cust["city"],
                "shipping_method": s["ship"],
                "line_items": lines,
                "buyer_name": random.choice(["Sarah Johnson", "Mike Torres", "Amy Lee", "David Park", "Rachel Kim"]),
                "buyer_email": f"buyer@{cust['name'].split()[0].lower().replace(',','').replace('.','')}.com",
            },
            "normalized_fields": {
                "bc_customer_no": cust["no"],
                "customer_name": cust["name"],
                "po_number": s["po"],
                "amount": s["amount"],
            },
            "vendor_name": cust["name"],
            "vendor_canonical": cust["name"],
            "ai_confidence": s["conf"],
        }
        sample_docs.append(doc)

    # ── Triage docs (no rep assigned — realistic scenarios) ──
    triage_scenarios = [
        {"cust_name": "Valley Fresh Produce Co.", "po": "VFP-PO-2026-001", "amount": 14200.00,
         "lines": 3, "hours": 3, "conf": 0.76,
         "sender": "orders@valleyfreshproduce.com",
         "note": "New customer — no existing record in BC. Email came from unknown domain."},
        {"cust_name": "Artisan Spice Traders", "po": "AST-8844", "amount": 6500.00,
         "lines": 2, "hours": 7, "conf": 0.81,
         "sender": "procurement@artisanspice.com",
         "note": "Customer name not in system. Possibly a DBA of an existing account."},
        {"cust_name": "Green Valley Organics", "po": "GVO-PO-45123", "amount": 38900.00,
         "lines": 7, "hours": 1, "conf": 0.88,
         "sender": "ap@greenvalleyorganics.com",
         "note": "High-value order from unrecognized sender. Could be a sub-brand of Nature's Path."},
        {"cust_name": "Coastal Beverage Group", "po": "CBG-2026-REQ-112", "amount": 72000.00,
         "lines": 14, "hours": 5, "conf": 0.72,
         "sender": "purchasing@coastalbev.com",
         "note": "Large order, unclear which territory. Customer has locations in CA and TX."},
        {"cust_name": "Heritage Foods International", "po": "", "amount": 22350.00,
         "lines": 5, "hours": 11, "conf": 0.65,
         "sender": "info@heritagefoods.co",
         "note": "No PO number found in document. Appears to be an informal order via email body."},
    ]

    for ts in triage_scenarios:
        created = (now - timedelta(hours=ts["hours"])).isoformat()
        lines = []
        for li in range(ts["lines"]):
            item = item_names[(li * 3) % len(item_names)]
            qty = random.choice([1000, 2500, 5000])
            lines.append({
                "line_no": li + 1,
                "item_no": f"PKG-{9000 + li}",
                "description": item,
                "quantity": qty,
                "unit_price": round(ts["amount"] / ts["lines"] / qty, 4),
                "line_amount": round(ts["amount"] / ts["lines"], 2),
                "uom": "EA",
            })

        doc = {
            "id": str(uuid.uuid4()),
            "file_name": f"{ts['po'] or 'EMAIL-ORDER'}-{ts['cust_name'].split()[0]}.pdf",
            "document_type": "PurchaseOrder" if ts["po"] else "Sales_Order",
            "created_utc": created,
            "updated_utc": created,
            "capture_channel": "email",
            "email_sender": ts["sender"],
            "status": "pending",
            "assigned_rep_email": "",
            "assigned_rep_name": "",
            "sales_review_status": "triage",
            "flag_notes": "",
            "sales_review_history": [
                {"action": "routed_to_triage", "at": created, "by": "system",
                 "reason": "no_rep_found", "note": ts["note"]},
            ],
            "extracted_fields": {
                "po_number": ts["po"],
                "customer_name": ts["cust_name"],
                "amount": str(ts["amount"]),
                "line_items": lines,
            },
            "normalized_fields": {
                "customer_name": ts["cust_name"],
                "amount": ts["amount"],
            },
            "vendor_name": ts["cust_name"],
            "ai_confidence": ts["conf"],
        }
        sample_docs.append(doc)

    # ── Clear and insert ──
    await db.hub_documents.delete_many({"document_type": {"$in": list(SALES_ELIGIBLE_TYPES)}})
    if sample_docs:
        await db.hub_documents.insert_many(sample_docs)

    # ── Seed customer→rep overrides for the assigned customers ──
    await db.customer_rep_overrides.delete_many({})
    overrides = []
    for cust in customers:
        rep = reps[cust["rep_idx"]]
        overrides.append({
            "id": str(uuid.uuid4()),
            "customer_no": cust["no"],
            "customer_name": cust["name"],
            "rep_email": rep["email"],
            "rep_name": rep["name"],
            "salesperson_code": rep["code"],
            "active": True,
            "created_utc": now.isoformat(),
            "updated_utc": now.isoformat(),
        })
    if overrides:
        await db.customer_rep_overrides.insert_many(overrides)

    # Count by status
    counts = {}
    for d in sample_docs:
        st = d["sales_review_status"]
        counts[st] = counts.get(st, 0) + 1

    logger.info("[SalesReview] Seeded %d review documents + %d rep overrides", len(sample_docs), len(overrides))
    return {
        "status": "success",
        "seeded_count": len(sample_docs),
        "reps": [{"name": r["name"], "email": r["email"], "region": r["region"]} for r in reps],
        "rep_overrides_seeded": len(overrides),
        "status_breakdown": counts,
        "customers": len(customers),
        "triage_docs": len(triage_scenarios),
    }


@router.post("/run-auto-assign")
async def run_auto_assign():
    """Run the sales auto-assignment pipeline on all sales-eligible documents
    that don't yet have a rep assigned. Useful for re-processing historical data.
    """
    db = get_db()
    from services.sales_auto_assign import auto_assign_sales_rep

    query = {
        "document_type": {"$in": list(SALES_ELIGIBLE_TYPES)},
        "$or": [
            {"assigned_rep_email": {"$exists": False}},
            {"assigned_rep_email": ""},
            {"assigned_rep_email": None},
            {"sales_review_status": "triage"},
        ],
    }

    docs = await db.hub_documents.find(query, {"_id": 0}).to_list(1000)
    results = {"assigned": 0, "triage": 0, "skipped": 0, "errors": 0}

    for doc in docs:
        try:
            result = await auto_assign_sales_rep(db, doc["id"], doc)
            if result and result.get("assigned"):
                results["assigned"] += 1
            elif result:
                results["triage"] += 1
            else:
                results["skipped"] += 1
        except Exception as e:
            logger.warning("Auto-assign error for %s: %s", doc.get("id", "?")[:8], str(e))
            results["errors"] += 1

    return {"status": "completed", "processed": len(docs), **results}


class RepOverrideRequest(BaseModel):
    customer_no: str = ""
    customer_name: str = ""
    rep_email: str
    rep_name: str = ""
    salesperson_code: str = ""
    override_type: str = "rep_assignment"
    reason: str = ""
    notes: str = ""
    expires_at: Optional[str] = None


@router.get("/rep-overrides")
async def list_rep_overrides(
    active_only: bool = Query(True),
    override_type: str = Query(None),
    rep_email: str = Query(None),
    customer_no: str = Query(None),
):
    """List customer→rep manual overrides with filters."""
    db = get_db()
    match: dict = {}
    if active_only:
        match["active"] = True
    if override_type:
        match["override_type"] = override_type
    if rep_email:
        match["rep_email"] = rep_email
    if customer_no:
        match["customer_no"] = customer_no

    overrides = await db.customer_rep_overrides.find(
        match, {"_id": 0}
    ).sort([("customer_name", 1)]).to_list(500)

    # Mark expired ones
    now = datetime.now(timezone.utc).isoformat()
    for o in overrides:
        exp = o.get("expires_at")
        if exp and exp < now:
            o["expired"] = True

    return {"overrides": overrides, "count": len(overrides)}


@router.post("/rep-overrides")
async def create_rep_override(body: RepOverrideRequest):
    """Create or update a customer→rep override. Used by admins to manually
    map customers to sales reps for auto-assignment."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    if not body.customer_no and not body.customer_name:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Either customer_no or customer_name is required")

    # Upsert by customer_no or customer_name
    filter_q = {}
    if body.customer_no:
        filter_q["customer_no"] = body.customer_no
    else:
        filter_q["customer_name"] = body.customer_name

    override_doc = {
        "customer_no": body.customer_no,
        "customer_name": body.customer_name,
        "rep_email": body.rep_email,
        "rep_name": body.rep_name,
        "salesperson_code": body.salesperson_code,
        "override_type": body.override_type,
        "reason": body.reason,
        "notes": body.notes,
        "expires_at": body.expires_at,
        "active": True,
        "updated_utc": now,
        "updated_by": "admin",
    }

    result = await db.customer_rep_overrides.update_one(
        filter_q,
        {"$set": override_doc, "$setOnInsert": {"id": str(uuid.uuid4()), "created_utc": now}},
        upsert=True,
    )

    action = "updated" if result.matched_count > 0 else "created"
    logger.info("[RepOverride] %s: %s → %s <%s>", action, body.customer_name or body.customer_no, body.rep_name, body.rep_email)
    return {"status": action, "customer": body.customer_name or body.customer_no, "rep_email": body.rep_email}


@router.delete("/rep-overrides/{customer_no}")
async def delete_rep_override(customer_no: str):
    """Deactivate a customer→rep override."""
    db = get_db()
    result = await db.customer_rep_overrides.update_one(
        {"customer_no": customer_no},
        {"$set": {"active": False, "updated_utc": datetime.now(timezone.utc).isoformat()}},
    )
    if result.matched_count == 0:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Override not found")
    return {"status": "deactivated", "customer_no": customer_no}
