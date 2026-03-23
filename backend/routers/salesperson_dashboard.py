"""
GPI Document Hub - Salesperson Performance Dashboard API

Aggregates Sales Order creation metrics per salesperson:
  - Volume, success rate, avg processing time
  - Customer breakdown per rep
  - Trend data over time
  - Top performers and at-risk accounts
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/salesperson-dashboard", tags=["Salesperson Dashboard"])


@router.get("/overview")
async def get_salesperson_overview(
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
):
    """
    Aggregate SO creation metrics per salesperson.
    Returns a ranked list of reps with volume, success rates, and customer counts.
    """
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Query all sales-type documents in the window
    pipeline = [
        {
            "$match": {
                "$or": [
                    {"doc_type": {"$regex": "sales", "$options": "i"}},
                    {"suggested_job_type": {"$regex": "sales", "$options": "i"}},
                    {"category": "Sales"},
                ],
                "created_utc": {"$gte": cutoff},
            }
        },
        {
            "$project": {
                "_id": 0,
                "id": 1,
                "assigned_salesperson_code": 1,
                "auto_create_attempted": 1,
                "auto_create_success": 1,
                "bc_sales_order_number": 1,
                "bc_posting_status": 1,
                "customer_extracted": 1,
                "extracted_fields.customer": 1,
                "normalized_fields.customer": 1,
                "created_utc": 1,
                "created_in_bc_utc": 1,
                "ai_confidence": 1,
                "classification_confidence": 1,
                "review_status": 1,
                "status": 1,
            }
        },
    ]
    docs = await db.hub_documents.aggregate(pipeline).to_list(5000)

    # Enrich with salesperson names from BC cache
    sp_cache = {}
    sp_records = await db.bc_reference_cache.find(
        {"bc_entity_type": "salesperson"}, {"_id": 0, "code": 1, "name": 1, "email": 1}
    ).to_list(200)
    for sp in sp_records:
        sp_cache[sp.get("code", "")] = {"name": sp.get("name", ""), "email": sp.get("email", "")}

    # Also get customer -> salesperson mapping from cache
    cust_sp_map = {}
    cust_records = await db.bc_reference_cache.find(
        {"bc_entity_type": "customer", "salesperson_code": {"$exists": True, "$ne": ""}},
        {"_id": 0, "bc_customer_name": 1, "displayName": 1, "salesperson_code": 1, "bc_customer_no": 1},
    ).to_list(2000)
    for c in cust_records:
        cust_sp_map[c.get("bc_customer_no") or c.get("bc_customer_name", "")] = c.get("salesperson_code", "")

    # Aggregate per salesperson
    rep_stats = {}
    unassigned = {
        "code": "UNASSIGNED",
        "name": "Unassigned",
        "total_docs": 0,
        "auto_created": 0,
        "auto_attempted": 0,
        "auto_failed": 0,
        "pending_review": 0,
        "customers": set(),
        "processing_times": [],
        "confidence_scores": [],
    }

    for doc in docs:
        sp_code = doc.get("assigned_salesperson_code") or ""

        # If no assigned code, try to derive from customer
        if not sp_code:
            cust = (
                doc.get("customer_extracted")
                or (doc.get("extracted_fields") or {}).get("customer")
                or (doc.get("normalized_fields") or {}).get("customer")
                or ""
            )
            sp_code = cust_sp_map.get(cust, "")

        if not sp_code:
            bucket = unassigned
        else:
            if sp_code not in rep_stats:
                sp_info = sp_cache.get(sp_code, {})
                rep_stats[sp_code] = {
                    "code": sp_code,
                    "name": sp_info.get("name", sp_code),
                    "email": sp_info.get("email", ""),
                    "total_docs": 0,
                    "auto_created": 0,
                    "auto_attempted": 0,
                    "auto_failed": 0,
                    "pending_review": 0,
                    "customers": set(),
                    "processing_times": [],
                    "confidence_scores": [],
                }
            bucket = rep_stats[sp_code]

        bucket["total_docs"] += 1

        if doc.get("auto_create_success"):
            bucket["auto_created"] += 1
        if doc.get("auto_create_attempted"):
            bucket["auto_attempted"] += 1
            if not doc.get("auto_create_success"):
                bucket["auto_failed"] += 1
        if doc.get("review_status") in ("needs_review", "pending"):
            bucket["pending_review"] += 1

        # Customer tracking
        cust_name = (
            doc.get("customer_extracted")
            or (doc.get("extracted_fields") or {}).get("customer")
            or (doc.get("normalized_fields") or {}).get("customer")
        )
        if cust_name:
            bucket["customers"].add(cust_name)

        # Processing time (created -> BC posted)
        if doc.get("created_utc") and doc.get("created_in_bc_utc"):
            try:
                t1 = datetime.fromisoformat(doc["created_utc"].replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(doc["created_in_bc_utc"].replace("Z", "+00:00"))
                delta = (t2 - t1).total_seconds()
                if 0 < delta < 86400 * 7:
                    bucket["processing_times"].append(delta)
            except Exception:
                pass

        conf = doc.get("ai_confidence") or doc.get("classification_confidence") or 0
        if conf > 0:
            bucket["confidence_scores"].append(conf)

    # Build response
    def _serialize(bucket):
        times = bucket["processing_times"]
        confs = bucket["confidence_scores"]
        attempted = bucket["auto_attempted"] or 0
        return {
            "code": bucket["code"],
            "name": bucket.get("name", bucket["code"]),
            "email": bucket.get("email", ""),
            "total_documents": bucket["total_docs"],
            "auto_created": bucket["auto_created"],
            "auto_attempted": attempted,
            "auto_failed": bucket["auto_failed"],
            "success_rate": round(bucket["auto_created"] / attempted * 100, 1) if attempted else 0,
            "pending_review": bucket["pending_review"],
            "unique_customers": len(bucket["customers"]),
            "top_customers": sorted(bucket["customers"])[:10],
            "avg_processing_seconds": round(sum(times) / len(times), 1) if times else None,
            "avg_confidence": round(sum(confs) / len(confs) * 100, 1) if confs else None,
        }

    reps = sorted(
        [_serialize(v) for v in rep_stats.values()],
        key=lambda r: r["total_documents"],
        reverse=True,
    )
    unassigned_data = _serialize(unassigned) if unassigned["total_docs"] > 0 else None

    totals = {
        "total_documents": sum(r["total_documents"] for r in reps) + (unassigned_data["total_documents"] if unassigned_data else 0),
        "total_auto_created": sum(r["auto_created"] for r in reps) + (unassigned_data["auto_created"] if unassigned_data else 0),
        "total_auto_attempted": sum(r["auto_attempted"] for r in reps) + (unassigned_data["auto_attempted"] if unassigned_data else 0),
        "total_pending_review": sum(r["pending_review"] for r in reps) + (unassigned_data["pending_review"] if unassigned_data else 0),
        "active_reps": len(reps),
        "days": days,
    }
    if totals["total_auto_attempted"] > 0:
        totals["overall_success_rate"] = round(totals["total_auto_created"] / totals["total_auto_attempted"] * 100, 1)
    else:
        totals["overall_success_rate"] = 0

    return {
        "totals": totals,
        "salespersons": reps,
        "unassigned": unassigned_data,
    }


@router.get("/trend")
async def get_salesperson_trend(
    days: int = Query(30, ge=7, le=365),
    interval: str = Query("week", regex="^(day|week|month)$"),
):
    """
    SO creation trend over time, broken down by week/month.
    """
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    docs = await db.hub_documents.find(
        {
            "$or": [
                {"doc_type": {"$regex": "sales", "$options": "i"}},
                {"category": "Sales"},
            ],
            "created_utc": {"$gte": cutoff},
        },
        {
            "_id": 0, "created_utc": 1, "auto_create_success": 1,
            "auto_create_attempted": 1, "assigned_salesperson_code": 1,
        },
    ).to_list(10000)

    # Bucket by interval
    buckets = {}
    for doc in docs:
        try:
            dt = datetime.fromisoformat(doc["created_utc"].replace("Z", "+00:00"))
        except Exception:
            continue

        if interval == "day":
            key = dt.strftime("%Y-%m-%d")
        elif interval == "week":
            key = (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
        else:
            key = dt.strftime("%Y-%m")

        if key not in buckets:
            buckets[key] = {"period": key, "total": 0, "auto_created": 0, "auto_attempted": 0}

        buckets[key]["total"] += 1
        if doc.get("auto_create_success"):
            buckets[key]["auto_created"] += 1
        if doc.get("auto_create_attempted"):
            buckets[key]["auto_attempted"] += 1

    trend = sorted(buckets.values(), key=lambda b: b["period"])
    for t in trend:
        t["success_rate"] = round(t["auto_created"] / t["auto_attempted"] * 100, 1) if t["auto_attempted"] else 0

    return {"interval": interval, "days": days, "data": trend}


@router.get("/detail/{salesperson_code}")
async def get_salesperson_detail(
    salesperson_code: str,
    days: int = Query(30, ge=1, le=365),
):
    """
    Detailed view for a specific salesperson: recent documents, customer breakdown, timeline.
    """
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Get salesperson info from cache
    sp_info = await db.bc_reference_cache.find_one(
        {"bc_entity_type": "salesperson", "code": salesperson_code},
        {"_id": 0},
    )

    # Get all their customers
    customers = await db.bc_reference_cache.find(
        {"bc_entity_type": "customer", "salesperson_code": salesperson_code},
        {"_id": 0, "bc_customer_name": 1, "displayName": 1, "bc_customer_no": 1},
    ).to_list(500)
    customer_names = {c.get("displayName") or c.get("bc_customer_name", "") for c in customers}

    # Get documents assigned to this rep
    docs = await db.hub_documents.find(
        {
            "$or": [
                {"assigned_salesperson_code": salesperson_code},
                {"customer_extracted": {"$in": list(customer_names)}},
            ],
            "created_utc": {"$gte": cutoff},
        },
        {
            "_id": 0, "id": 1, "filename": 1, "customer_extracted": 1,
            "bc_sales_order_number": 1, "auto_create_success": 1,
            "auto_create_attempted": 1, "review_status": 1, "status": 1,
            "created_utc": 1, "created_in_bc_utc": 1, "bc_posting_status": 1,
            "ai_confidence": 1,
        },
    ).sort("created_utc", -1).to_list(200)

    # Customer breakdown
    cust_breakdown = {}
    for doc in docs:
        cust = doc.get("customer_extracted", "Unknown")
        if cust not in cust_breakdown:
            cust_breakdown[cust] = {"name": cust, "total": 0, "auto_created": 0, "pending": 0}
        cust_breakdown[cust]["total"] += 1
        if doc.get("auto_create_success"):
            cust_breakdown[cust]["auto_created"] += 1
        if doc.get("review_status") in ("needs_review", "pending"):
            cust_breakdown[cust]["pending"] += 1

    return {
        "salesperson": {
            "code": salesperson_code,
            "name": sp_info.get("name", salesperson_code) if sp_info else salesperson_code,
            "email": sp_info.get("email", "") if sp_info else "",
        },
        "total_customers": len(customers),
        "customer_breakdown": sorted(cust_breakdown.values(), key=lambda c: c["total"], reverse=True),
        "recent_documents": docs[:50],
        "days": days,
    }
