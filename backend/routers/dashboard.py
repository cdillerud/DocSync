"""GPI Document Hub - Dashboard Router"""

from fastapi import APIRouter, Query, Response
from typing import Optional
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from deps import get_db, DEMO_MODE

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# GPI operates on US Central Time
GPI_TZ = ZoneInfo("America/Chicago")


# ==================== PHASE 6: SHADOW MODE INSTRUMENTATION ====================




@router.get("/inbox-stats")
async def get_inbox_stats():
    """Compact stats for the inbox header: ingestion, validation, auto-filing."""
    db = get_db()
    tz = GPI_TZ

    now_ct = datetime.now(tz)
    today_start = now_ct.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start.astimezone(timezone.utc).isoformat()
    seven_days_ago_utc = (today_start - timedelta(days=7)).astimezone(timezone.utc).isoformat()

    # Total docs & today's count
    total = await db.hub_documents.count_documents({})
    # exclude batch_parent docs from ingestion count — they're containers, not individual docs
    today_filter = {"created_utc": {"$gte": today_start_utc}, "status": {"$ne": "batch_parent"}}
    ingested_today = await db.hub_documents.count_documents(today_filter)

    # 7-day daily average (excluding batch parents)
    seven_d_filter = {"created_utc": {"$gte": seven_days_ago_utc}, "status": {"$ne": "batch_parent"}}
    ingested_7d = await db.hub_documents.count_documents(seven_d_filter)
    avg_daily = round(ingested_7d / 7, 1)

    # Auto-validation rate: docs where automation_decision=auto OR auto_cleared=True.
    # IMPORTANT: numerator and denominator must apply the SAME exclusions or
    # the ratio can exceed 100% when batch_parent containers carry an auto
    # status they inherited from their children. Both sides exclude
    # batch_parent here so the rate is well-formed.
    NON_BATCH = {"status": {"$ne": "batch_parent"}}
    auto_processed = await db.hub_documents.count_documents({
        "$and": [
            NON_BATCH,
            {"$or": [
                {"automation_decision": "auto"},
                {"auto_cleared": True},
                {"sales_review_status": "auto_approved"},
            ]},
        ]
    })
    non_batch_total = await db.hub_documents.count_documents(NON_BATCH)
    if non_batch_total > 0:
        raw_rate = (auto_processed / non_batch_total) * 100
        # Defensive clamp at the rounding boundary; only kicks in if the
        # math is already at 100 (e.g. 99.95 -> 100.0 after round).
        auto_rate = round(min(max(raw_rate, 0.0), 100.0), 1)
    else:
        auto_rate = 0

    # Pending review (docs needing human attention — exclude duplicates to match inbox)
    pending_review = await db.hub_documents.count_documents({
        "is_duplicate": {"$ne": True},
        "status": {"$nin": ["Completed", "Posted", "Archived", "batch_parent", "auto_filed"]},
        "workflow_status": {"$in": [
            "NeedsReview", "needs_review", "pending_review",
            "vendor_pending", "bounds_review", "bc_validation_pending",
        ]}
    })
    # Fallback: also count docs just marked with certain statuses
    pending_simple = await db.hub_documents.count_documents({
        "is_duplicate": {"$ne": True},
        "status": {"$in": ["NeedsReview", "needs_review", "pending_review"]},
    })
    pending = max(pending_review, pending_simple)

    # Bounds alerts (active)
    bounds_alerts = await db.hub_documents.count_documents({"bounds_alert": True})

    # Posted to BC (7-day window) — a doc counts as "posted" if we captured
    # evidence of a BC record (any of bc_purchase_invoice_no / bc_record_no /
    # bc_document_no / bc_record_id) within the last 7 days. This matches
    # the actual write paths (see PRD 2026-04-10 field-name migration) and
    # no longer requires a literal status == "Posted" string match.
    posted_to_bc_7d = await db.hub_documents.count_documents({
        "$and": [
            {
                "$or": [
                    {"bc_purchase_invoice_no": {"$exists": True, "$nin": [None, ""]}},
                    {"bc_record_no": {"$exists": True, "$nin": [None, ""]}},
                    {"bc_document_no": {"$exists": True, "$nin": [None, ""]}},
                    {"bc_record_id": {"$exists": True, "$nin": [None, ""]}},
                    {"status": "Posted"},
                ],
            },
            {
                "$or": [
                    {"posted_to_bc_at": {"$gte": seven_days_ago_utc}},
                    {"bc_posted_at": {"$gte": seven_days_ago_utc}},
                    {"posted_at": {"$gte": seven_days_ago_utc}},
                    {"updated_utc": {"$gte": seven_days_ago_utc}},
                ],
            },
        ],
    })
    # Count docs currently queued for posting (ReadyForPost) — status/workflow
    # flags may diverge during retries, so match on either.
    ready_for_post = await db.hub_documents.count_documents({
        "$or": [
            {"status": "ReadyForPost"},
            {"workflow_status": "ready_for_post"},
        ],
    })

    # Avg AI confidence (sampled from last 200 docs for speed)
    conf_docs = await db.hub_documents.find(
        {"ai_confidence": {"$exists": True, "$ne": None}},
        {"_id": 0, "ai_confidence": 1}
    ).sort("created_utc", -1).limit(200).to_list(200)
    if conf_docs:
        avg_conf = round(sum(d["ai_confidence"] for d in conf_docs) / len(conf_docs) * 100, 1)
    else:
        avg_conf = 0

    return {
        "ingested_today": ingested_today,
        "avg_daily_7d": avg_daily,
        "auto_validation_rate": auto_rate,
        "pending_review": pending,
        "bounds_alerts": bounds_alerts,
        "avg_ai_confidence": avg_conf,
        "total_documents": total,
        "posted_to_bc_7d": posted_to_bc_7d,
        "ready_for_post": ready_for_post,
    }


@router.get("/inbox-metrics")
async def get_inbox_metrics(
    scope: str = Query("all", description="Tab scope: all, accounting, sales, processed, exceptions, po_pending"),
):
    """Detailed breakdown of documents for the active tab scope."""
    from routers.queue_constants import (
        TERMINAL_STATUSES, DONE_WORKFLOW_STATUSES, AP_TYPES, SALES_TYPES,
        build_inbox_filter,
    )
    db = get_db()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # ── Build scope-specific filter ──
    if scope == "exceptions":
        inbox_filter = {
            "$and": [
                {"is_duplicate": {"$ne": True}},
                {"workflow_status": "exception_review"},
            ]
        }
    elif scope == "po_pending":
        inbox_filter = {
            "$and": [
                {"is_duplicate": {"$ne": True}},
                {"workflow_status": "po_pending"},
            ]
        }
    elif scope == "processed":
        inbox_filter = {
            "$and": [
                {"is_duplicate": {"$ne": True}},
                {"$or": [
                    {"status": {"$in": TERMINAL_STATUSES}},
                    {"workflow_status": {"$in": DONE_WORKFLOW_STATUSES}},
                    {"auto_cleared": True},
                ]},
            ]
        }
    else:
        # Active inbox — uses the EXACT same filter as the documents endpoint
        inbox_filter = build_inbox_filter(include_cleared=False)
        # Narrow by doc type for accounting/sales tabs
        if scope == "accounting":
            inbox_filter["$and"].append(
                {"$or": [{"doc_type": {"$in": AP_TYPES}}, {"document_type": {"$in": AP_TYPES}}]}
            )
        elif scope == "sales":
            inbox_filter["$and"].append(
                {"$or": [{"doc_type": {"$in": SALES_TYPES}}, {"document_type": {"$in": SALES_TYPES}}]}
            )

    # ── 1. By Status ──
    status_pipeline = [
        {"$match": inbox_filter},
        {"$group": {"_id": {"$ifNull": ["$workflow_status", "unknown"]}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    status_raw = await db.hub_documents.aggregate(status_pipeline).to_list(50)
    by_status = {r["_id"]: r["count"] for r in status_raw}

    # ── 2. By Document Type ──
    type_pipeline = [
        {"$match": inbox_filter},
        {"$group": {"_id": {"$ifNull": [
            {"$ifNull": ["$doc_type", "$document_type"]},
            "Unknown"
        ]}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    type_raw = await db.hub_documents.aggregate(type_pipeline).to_list(50)
    by_type = {r["_id"]: r["count"] for r in type_raw}

    # ── 3. By Age ──
    one_hour_ago = (now - timedelta(hours=1)).isoformat()
    one_day_ago = (now - timedelta(hours=24)).isoformat()
    three_days_ago = (now - timedelta(days=3)).isoformat()

    age_pipeline = [
        {"$match": inbox_filter},
        {"$addFields": {"created": {"$ifNull": ["$created_utc", now_iso]}}},
        {"$group": {
            "_id": None,
            "lt_1h": {"$sum": {"$cond": [{"$gte": ["$created", one_hour_ago]}, 1, 0]}},
            "1h_24h": {"$sum": {"$cond": [
                {"$and": [{"$lt": ["$created", one_hour_ago]}, {"$gte": ["$created", one_day_ago]}]}, 1, 0
            ]}},
            "24h_3d": {"$sum": {"$cond": [
                {"$and": [{"$lt": ["$created", one_day_ago]}, {"$gte": ["$created", three_days_ago]}]}, 1, 0
            ]}},
            "gt_3d": {"$sum": {"$cond": [{"$lt": ["$created", three_days_ago]}, 1, 0]}},
        }},
    ]
    age_raw = await db.hub_documents.aggregate(age_pipeline).to_list(1)
    by_age = age_raw[0] if age_raw else {"lt_1h": 0, "1h_24h": 0, "24h_3d": 0, "gt_3d": 0}
    by_age.pop("_id", None)

    # ── 4. By Vendor (top 10) ──
    vendor_pipeline = [
        {"$match": inbox_filter},
        {"$group": {"_id": {"$ifNull": [
            {"$ifNull": ["$vendor_canonical", "$vendor_normalized"]},
            "Unknown"
        ]}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    vendor_raw = await db.hub_documents.aggregate(vendor_pipeline).to_list(10)
    by_vendor = [{"vendor": r["_id"] or "Unknown", "count": r["count"]} for r in vendor_raw]

    # ── 5. By Blocker Reason ──
    blocker_pipeline = [
        {"$match": inbox_filter},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "no_vendor": {"$sum": {"$cond": [
                {"$and": [
                    {"$in": [{"$ifNull": ["$vendor_canonical", ""]}, ["", None]]},
                    {"$in": [{"$ifNull": ["$vendor_normalized", ""]}, ["", None]]},
                ]}, 1, 0
            ]}},
            "no_po": {"$sum": {"$cond": [
                {"$and": [
                    {"$in": [{"$ifNull": ["$po_number_clean", ""]}, ["", None]]},
                    {"$in": [{"$ifNull": ["$po_number_raw", ""]}, ["", None]]},
                ]}, 1, 0
            ]}},
            "low_confidence": {"$sum": {"$cond": [
                {"$lt": [{"$ifNull": ["$ai_confidence", 0]}, 0.5]}, 1, 0
            ]}},
            "duplicate_flag": {"$sum": {"$cond": [
                {"$eq": [{"$ifNull": ["$possible_duplicate", False]}, True]}, 1, 0
            ]}},
            "no_extraction": {"$sum": {"$cond": [
                {"$in": [{"$ifNull": ["$extracted_fields", None]}, [None, {}]]}, 1, 0
            ]}},
            "validation_failed": {"$sum": {"$cond": [
                {"$eq": [{"$ifNull": ["$validation_results.all_passed", True]}, False]}, 1, 0
            ]}},
        }},
    ]
    blocker_raw = await db.hub_documents.aggregate(blocker_pipeline).to_list(1)
    by_blocker = blocker_raw[0] if blocker_raw else {
        "total": 0, "no_vendor": 0, "no_po": 0, "low_confidence": 0,
        "duplicate_flag": 0, "no_extraction": 0, "validation_failed": 0,
    }
    by_blocker.pop("_id", None)

    total_inbox = sum(by_status.values()) if by_status else 0

    return {
        "total_inbox": total_inbox,
        "by_status": by_status,
        "by_type": by_type,
        "by_age": by_age,
        "by_vendor": by_vendor,
        "by_blocker": by_blocker,
    }


@router.get("/ap-metrics")
async def get_ap_metrics():
    """AP Invoice posting metrics: submitted, failed, pending, timing, errors.

    Field-name correctness (see PRD 2026-04-10 BC field-name migration
    and the matching logic in `/inbox-stats`):
    - AP docs are identified by `doc_type` (case-insensitive). The
      legacy `document_type` field is rarely populated in the current
      corpus and was producing a 52x undercount on this card.
    - "Posted to BC" uses the canonical signal set already used by
      `/inbox-stats`: presence of bc_purchase_invoice_no /
      bc_record_no / bc_document_no / bc_record_id, OR status=="Posted".
      `bc_posting_status` is auto-post-pipeline-only and is NOT
      required.
    - "Failed" uses bc_posting_status=="failed" OR a non-empty
      bc_posting_error OR final_state=="auto_post_failed",
      AND the doc has NOT also reached a posted signal (so a doc
      that failed once and then succeeded counts as posted, not
      failed).
    - `success_rate = posted / (posted + failed)` -- attempts that
      succeeded -- never `posted / total_ap` (which is coverage).
    """
    db = get_db()

    AP_TYPE_FILTER = {
        "doc_type": {"$regex": r"^(ap[_-]?invoice|purchase[_-]?invoice)$",
                     "$options": "i"}
    }
    POSTED_SIGNAL = {"$or": [
        {"bc_purchase_invoice_no": {"$exists": True, "$nin": [None, ""]}},
        {"bc_record_no":           {"$exists": True, "$nin": [None, ""]}},
        {"bc_document_no":         {"$exists": True, "$nin": [None, ""]}},
        {"bc_record_id":           {"$exists": True, "$nin": [None, ""]}},
        {"status": "Posted"},
    ]}
    FAILED_SIGNAL = {"$or": [
        {"bc_posting_status": "failed"},
        {"bc_posting_error":  {"$exists": True, "$nin": [None, ""]}},
        {"final_state":       "auto_post_failed"},
    ]}

    total_ap = await db.hub_documents.count_documents(AP_TYPE_FILTER)

    posted = await db.hub_documents.count_documents(
        {"$and": [AP_TYPE_FILTER, POSTED_SIGNAL]})

    # Failed = matches a failure signal AND has NOT reached a posted
    # signal. Prevents double-counting docs that failed-then-succeeded.
    failed = await db.hub_documents.count_documents({"$and": [
        AP_TYPE_FILTER, FAILED_SIGNAL, {"$nor": [POSTED_SIGNAL]},
    ]})

    pending_review = await db.hub_documents.count_documents({"$and": [
        AP_TYPE_FILTER,
        {"$nor": [POSTED_SIGNAL]},
        {"$nor": [FAILED_SIGNAL]},
        {"status": {"$nin": ["Completed", "Archived", "batch_parent"]}},
    ]})

    # Validation pass rate
    validated = await db.hub_documents.count_documents({"$and": [
        AP_TYPE_FILTER, {"validation_results.all_passed": True},
    ]})
    validation_rate = round((validated / total_ap * 100) if total_ap > 0 else 0, 1)

    # Average time from ingestion to BC posting (for posted docs)
    posted_docs = await db.hub_documents.find(
        {"$and": [
            AP_TYPE_FILTER, POSTED_SIGNAL,
            {"created_utc": {"$exists": True, "$nin": [None, ""]}},
        ]},
        {"_id": 0, "created_utc": 1, "bc_posted_at": 1,
         "posted_to_bc_at": 1, "posted_at": 1, "updated_utc": 1}
    ).limit(200).to_list(200)
    avg_time_hours = 0
    if posted_docs:
        deltas = []
        for d in posted_docs:
            posted_ts = (d.get("bc_posted_at") or d.get("posted_to_bc_at")
                         or d.get("posted_at") or d.get("updated_utc"))
            if not posted_ts:
                continue
            try:
                created = datetime.fromisoformat(d["created_utc"].replace("Z", "+00:00"))
                posted_at = datetime.fromisoformat(posted_ts.replace("Z", "+00:00"))
                delta_h = (posted_at - created).total_seconds() / 3600
                if delta_h > 0:
                    deltas.append(delta_h)
            except Exception:
                pass
        if deltas:
            avg_time_hours = round(sum(deltas) / len(deltas), 1)

    # Error breakdown (top reasons) -- keyed off the fast-access summary
    # projection `bc_posting_error`. Excludes docs that later reached a
    # posted signal so we don't surface stale errors for recovered docs.
    error_pipeline = [
        {"$match": {"$and": [
            AP_TYPE_FILTER,
            {"bc_posting_error": {"$exists": True, "$nin": [None, ""]}},
            {"$nor": [POSTED_SIGNAL]},
        ]}},
        {"$group": {"_id": "$bc_posting_error", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    errors_raw = await db.hub_documents.aggregate(error_pipeline).to_list(5)
    error_breakdown = [{"reason": (e["_id"] or "")[:80], "count": e["count"]}
                       for e in errors_raw if e["_id"]]

    # Attempts = posted + failed. Success rate is the fraction of
    # attempts that succeeded -- NOT coverage over total_ap.
    attempts = posted + failed
    success_rate = round((posted / attempts * 100) if attempts > 0 else 0, 1)

    return {
        "total_ap": total_ap,
        "posted_to_bc": posted,
        "failed": failed,
        "pending_review": pending_review,
        "validation_rate": validation_rate,
        "avg_time_to_post_hours": avg_time_hours,
        "success_rate": success_rate,
        "error_breakdown": error_breakdown,
    }
