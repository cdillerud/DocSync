"""
Sales Dashboard Router — Orders Awaiting Review

Provides a lightweight, role-oriented API for the Sales dashboard:
  GET /sales-dashboard/queue   — filtered list of sales-eligible docs with readiness status
  GET /sales-dashboard/summary — summary counts only (fast)
"""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Query
from deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sales-dashboard", tags=["Sales Dashboard"])

SALES_ELIGIBLE_TYPES = {"Sales_Order", "SalesOrder", "Order_Confirmation", "PurchaseOrder"}


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
