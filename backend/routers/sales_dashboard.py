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

SALES_ELIGIBLE_TYPES = {"Sales_Order", "SalesOrder", "Order_Confirmation", "PurchaseOrder"}

# Sales review statuses used by the Inside Sales Rep Review flow
REVIEW_STATUSES = {
    "pending_rep_review",   # Assigned to rep, waiting for review
    "approved",             # Rep approved → ready for BC SO creation
    "flagged",              # Rep flagged → needs attention
    "auto_approved",        # High confidence, auto-sent to BC
    "triage",               # No rep found, needs manual assignment
}


def _assess_readiness(doc: dict) -> dict:
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

    # Customer resolution
    customer_no = (nf.get("bc_customer_no") or nf.get("customer_number")
                   or ef.get("customer_number") or "")
    customer_name = (nf.get("customer_name") or ef.get("customer_name")
                     or ef.get("company_name") or doc.get("vendor_name") or "")
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
        assessment = _assess_readiness(doc)

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
         "bc_sales_order": 1, "vendor_name": 1, "document_type": 1}
    ).to_list(500)

    counts = {"ready": 0, "ready_warnings": 0, "needs_review": 0, "already_created": 0, "total": len(all_docs)}
    for doc in all_docs:
        a = _assess_readiness(doc)
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
        assessment = _assess_readiness(doc)
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
        assessment = _assess_readiness(doc)
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


@router.post("/seed-review-data")
async def seed_review_data():
    """Seed test data for the Inside Sales Rep Review feature.
    Creates sample sales documents with rep assignments for development/testing.
    """
    db = get_db()

    now = datetime.now(timezone.utc)
    reps = [
        {"email": "jsmith@gamerpackaging.com", "name": "John Smith", "code": "JS"},
        {"email": "mgarcia@gamerpackaging.com", "name": "Maria Garcia", "code": "MG"},
        {"email": "bwilson@gamerpackaging.com", "name": "Bob Wilson", "code": "BW"},
    ]

    customers = [
        {"no": "C-1001", "name": "Bragg Live Food Products, LLC"},
        {"no": "C-1002", "name": "Palmer's (ET Browne)"},
        {"no": "C-1003", "name": "Karlin Foods International"},
        {"no": "C-1004", "name": "House of Wines"},
        {"no": "C-1005", "name": "Wing Nien Foods"},
    ]

    sample_docs = []
    statuses = ["pending_rep_review", "pending_rep_review", "pending_rep_review", "flagged", "approved"]
    doc_types = list(SALES_ELIGIBLE_TYPES)

    for i in range(15):
        rep = reps[i % len(reps)]
        cust = customers[i % len(customers)]
        status = statuses[i % len(statuses)]
        doc_type = doc_types[i % len(doc_types)]
        created = (now - timedelta(hours=i * 6)).isoformat()
        amount = round(1000 + (i * 2345.67), 2)

        doc = {
            "id": str(uuid.uuid4()),
            "file_name": f"PO-{10000 + i}-{cust['name'].split()[0]}.pdf",
            "document_type": doc_type,
            "created_utc": created,
            "updated_utc": created,
            "capture_channel": "email" if i % 2 == 0 else "SHADOW_PILOT_UPLOAD",
            "status": "ready" if status == "approved" else "pending",
            "assigned_rep_email": rep["email"],
            "assigned_rep_name": rep["name"],
            "assigned_salesperson_code": rep["code"],
            "sales_review_status": status,
            "flag_notes": "Customer requested different ship date" if status == "flagged" else "",
            "sales_review_history": [],
            "extracted_fields": {
                "po_number": f"PO-{10000 + i}",
                "customer_name": cust["name"],
                "order_date": (now - timedelta(days=i)).strftime("%m/%d/%y"),
                "amount": str(amount),
                "line_items": [{"item": f"PKG-{j}", "qty": 1000 * (j + 1)} for j in range(i % 4 + 1)],
            },
            "normalized_fields": {
                "bc_customer_no": cust["no"],
                "customer_name": cust["name"],
                "po_number": f"PO-{10000 + i}",
                "amount": amount,
            },
            "vendor_name": cust["name"],
            "ai_confidence": round(0.7 + (i % 4) * 0.08, 2),
        }
        sample_docs.append(doc)

    # Add 3 unassigned docs for the triage queue
    for i in range(3):
        cust = customers[i]
        created = (now - timedelta(hours=i * 3 + 1)).isoformat()
        doc = {
            "id": str(uuid.uuid4()),
            "file_name": f"UNKNOWN-ORDER-{i + 1}.pdf",
            "document_type": "Sales_Order",
            "created_utc": created,
            "updated_utc": created,
            "capture_channel": "email",
            "status": "pending",
            "assigned_rep_email": "",
            "assigned_rep_name": "",
            "sales_review_status": "triage",
            "flag_notes": "",
            "sales_review_history": [],
            "extracted_fields": {
                "po_number": f"UNK-{9000 + i}",
                "customer_name": cust["name"],
                "amount": str(round(500 + i * 750, 2)),
                "line_items": [{"item": "PKG-X", "qty": 500}],
            },
            "normalized_fields": {
                "customer_name": cust["name"],
                "amount": round(500 + i * 750, 2),
            },
            "vendor_name": cust["name"],
            "ai_confidence": 0.55,
        }
        sample_docs.append(doc)

    # Clear existing seeded data and insert fresh
    await db.hub_documents.delete_many({"document_type": {"$in": list(SALES_ELIGIBLE_TYPES)}})
    if sample_docs:
        await db.hub_documents.insert_many(sample_docs)

    logger.info("[SalesReview] Seeded %d review documents", len(sample_docs))
    return {
        "status": "success",
        "seeded_count": len(sample_docs),
        "reps": [r["email"] for r in reps],
        "statuses": {"pending_rep_review": 9, "flagged": 3, "approved": 3, "triage": 3},
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
