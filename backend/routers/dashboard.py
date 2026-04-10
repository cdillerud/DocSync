"""GPI Document Hub - Dashboard Router"""

from fastapi import APIRouter, Query, Response
from typing import Optional
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from deps import get_db, DEMO_MODE

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# GPI operates on US Central Time
GPI_TZ = ZoneInfo("America/Chicago")


def _date_filter(date: Optional[str] = None) -> dict:
    """Build a MongoDB filter on created_utc for a given Central Time day.
    Returns {} (match-all) when date is None."""
    if not date:
        return {}
    try:
        day_start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=GPI_TZ)
    except ValueError:
        return {}
    day_start_utc = day_start.astimezone(timezone.utc)
    day_end_utc = day_start_utc + timedelta(days=1)
    return {"created_utc": {"$gte": day_start_utc.isoformat(), "$lt": day_end_utc.isoformat()}}


async def _get_alias_metrics_safe(db, total_docs: int) -> dict:
    """Get alias metrics for the vendor intelligence section."""
    try:
        total_aliases = await db.vendor_aliases.count_documents({})
        auto_learned = await db.vendor_aliases.count_documents({"source": "auto_learned"})
        alias_matched = await db.hub_documents.count_documents({
            "vendor_match_method": {"$in": ["alias", "learned_alias", "alias_match"]},
        })
        alias_rate = round((alias_matched / total_docs * 100), 1) if total_docs > 0 else 0

        top_cursor = db.vendor_aliases.find(
            {"usage_count": {"$gt": 0}},
            {"_id": 0, "alias": 1, "normalized_alias": 1, "vendor_name": 1, "usage_count": 1},
        ).sort("usage_count", -1).limit(5)
        top_aliases = await top_cursor.to_list(5)

        return {
            "total_aliases": total_aliases,
            "auto_learned": auto_learned,
            "alias_match_rate": alias_rate,
            "alias_matched_docs": alias_matched,
            "top_aliases": top_aliases,
        }
    except Exception:
        return {"total_aliases": 0, "auto_learned": 0, "alias_match_rate": 0, "alias_matched_docs": 0, "top_aliases": []}



@router.get("/daily-ingestion")
async def get_daily_ingestion(date: Optional[str] = None):
    """
    Get document ingestion stats for a specific day.
    Defaults to today (Central Time). Pass date=YYYY-MM-DD for other days.
    """
    db = get_db()

    if date:
        try:
            day_start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=GPI_TZ)
        except ValueError:
            day_start = datetime.now(GPI_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        day_start = datetime.now(GPI_TZ).replace(hour=0, minute=0, second=0, microsecond=0)

    # Convert to UTC for DB queries (dates stored as UTC ISO strings)
    day_start_utc = day_start.astimezone(timezone.utc)
    day_end_utc = day_start_utc + timedelta(days=1)
    day_str_start = day_start_utc.isoformat()
    day_str_end = day_end_utc.isoformat()

    date_filter = {"created_utc": {"$gte": day_str_start, "$lt": day_str_end}}

    total = await db.hub_documents.count_documents(date_filter)

    # By source
    source_pipeline = [
        {"$match": date_filter},
        {"$group": {"_id": {"$ifNull": ["$source", "unknown"]}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    by_source = {r["_id"]: r["count"] for r in await db.hub_documents.aggregate(source_pipeline).to_list(20)}

    # By document type
    type_pipeline = [
        {"$match": date_filter},
        {"$group": {"_id": {"$ifNull": ["$document_type", "Unknown"]}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    by_type = {r["_id"]: r["count"] for r in await db.hub_documents.aggregate(type_pipeline).to_list(30)}

    # By hour
    hour_pipeline = [
        {"$match": date_filter},
        {"$addFields": {"hour_str": {"$substr": ["$created_utc", 11, 2]}}},
        {"$group": {"_id": "$hour_str", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    by_hour_raw = await db.hub_documents.aggregate(hour_pipeline).to_list(24)
    by_hour = [{"hour": int(r["_id"]), "count": r["count"]} for r in by_hour_raw if r["_id"]]

    # By status
    status_pipeline = [
        {"$match": date_filter},
        {"$group": {"_id": {"$ifNull": ["$status", "Unknown"]}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    by_status = {r["_id"]: r["count"] for r in await db.hub_documents.aggregate(status_pipeline).to_list(20)}

    # By sender (top 10)
    sender_pipeline = [
        {"$match": {**date_filter, "email_sender": {"$exists": True, "$ne": None, "$ne": ""}}},
        {"$group": {"_id": "$email_sender", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    by_sender = [{"sender": r["_id"], "count": r["count"]} for r in await db.hub_documents.aggregate(sender_pipeline).to_list(10)]

    # Recent documents (last 50)
    recent = await db.hub_documents.find(
        date_filter,
        {"_id": 0, "id": 1, "file_name": 1, "document_type": 1, "source": 1,
         "status": 1, "workflow_status": 1, "created_utc": 1, "email_sender": 1,
         "vendor_canonical": 1, "matched_vendor_name": 1},
    ).sort("created_utc", -1).limit(50).to_list(50)

    return {
        "date": day_start.strftime("%Y-%m-%d"),
        "total": total,
        "by_source": by_source,
        "by_type": by_type,
        "by_hour": by_hour,
        "by_status": by_status,
        "top_senders": by_sender,
        "recent_documents": recent,
    }


@router.get("/stats")
async def get_dashboard_stats(date: Optional[str] = None):
    db = get_db()
    df = _date_filter(date)
    total = await db.hub_documents.count_documents(df)
    by_status = {}
    for s in ["Received", "Classified", "LinkedToBC", "Exception", "Completed"]:
        by_status[s] = await db.hub_documents.count_documents({**df, "status": s})
    by_type = {}
    for t in ["AP_Invoice", "AR_Invoice", "Remittance", "Freight_Document", "Sales_Order",
              "Sales_PO", "Sales_Quote", "Order_Confirmation", "Purchase_Order",
              "Warehouse_Receipt", "Shipping_Document", "Inventory_Report",
              "Quality_Issue", "Return_Request", "Unknown_Document"]:
        count = await db.hub_documents.count_documents({**df, "document_type": t})
        if count > 0:
            by_type[t] = count
    recent_workflows = await db.hub_workflow_runs.find({}, {"_id": 0}).sort("started_utc", -1).limit(10).to_list(10)
    failed_workflows = await db.hub_workflow_runs.find({"status": "Failed"}, {"_id": 0}).sort("started_utc", -1).limit(10).to_list(10)
    # Routing status counts
    routing_pipeline = [
        {"$match": {**df}},
        {"$group": {
            "_id": "$routing_status",
            "count": {"$sum": 1},
            "avg_score": {"$avg": "$routing_score"},
        }},
    ]
    routing_raw = await db.hub_documents.aggregate(routing_pipeline).to_list(10)
    routing_counts = {}
    for r in routing_raw:
        key = r["_id"] or "unrouted"
        routing_counts[key] = {"count": r["count"], "avg_score": round(r.get("avg_score") or 0, 1)}

    # Catalog sync health
    try:
        from services.bc_catalog_sync_service import get_catalog_health
        catalog_health = await get_catalog_health(db)
    except Exception:
        catalog_health = None

    return {
        "total_documents": total, "by_status": by_status, "by_type": by_type,
        "recent_workflows": recent_workflows, "failed_workflows": failed_workflows,
        "demo_mode": DEMO_MODE,
        "routing_summary": routing_counts,
        "catalog_sync_health": catalog_health,
    }



@router.get("/workflow-intelligence")
async def get_workflow_intelligence_stats(date: Optional[str] = None):
    """
    Comprehensive workflow intelligence metrics.
    Provides insights into vendor matching, validation success, processing efficiency,
    and automation performance across the entire document processing pipeline.
    Optionally filtered to a single Central Time day via ?date=YYYY-MM-DD.
    """
    db = get_db()
    df = _date_filter(date)
    
    # ============== VENDOR INTELLIGENCE ==============
    # Get vendor match method distribution
    match_method_pipeline = [
        {"$match": {**df, "validation_results.match_method": {"$exists": True}}},
        {"$group": {
            "_id": "$validation_results.match_method",
            "count": {"$sum": 1},
            "avg_score": {"$avg": "$validation_results.match_score"}
        }},
        {"$sort": {"count": -1}}
    ]
    match_method_results = await db.hub_documents.aggregate(match_method_pipeline).to_list(20)
    
    # Vendor matches from cached collection
    cached_matches_pipeline = [
        {"$group": {
            "_id": "$source",
            "count": {"$sum": 1},
            "avg_score": {"$avg": "$score"}
        }}
    ]
    cached_by_source = await db.vendor_matches.aggregate(cached_matches_pipeline).to_list(10)
    
    # Freight carrier detection stats
    freight_docs = await db.hub_documents.count_documents({
        **df,
        "$or": [
            {"extracted_data.is_freight_carrier": True},
            {"unified_vendor_match.is_freight_carrier": True},
            {"validation_results.checks": {"$elemMatch": {"is_freight_carrier": True}}}
        ]
    })
    
    # ============== ACTION REQUIRED QUEUES ==============
    # 1. Needs Vendor Review - AP invoices with no vendor match
    needs_vendor_review = await db.hub_documents.count_documents({
        **df,
        "doc_type": {"$in": ["AP_Invoice", "AP_INVOICE", "Remittance", "REMITTANCE"]},
        "$or": [
            {"validation_results.match_method": "none"},
            {"validation_results.match_method": {"$exists": False}},
            {"vendor_canonical": {"$exists": False}},
            {"vendor_canonical": None}
        ],
        "status": {"$nin": ["Completed", "Archived", "Posted", "Deleted"]}
    })
    
    # 2. Needs PO Match - Shipping docs missing PO link
    needs_po_match = await db.hub_documents.count_documents({
        **df,
        "doc_type": {"$in": ["BOL", "Packing_List", "Shipping_Document", "SHIPPING", "Freight_Document"]},
        "$or": [
            {"po_number_clean": {"$exists": False}},
            {"po_number_clean": None},
            {"po_number_clean": ""},
            {"bc_record_id": {"$exists": False}},
            {"bc_record_id": None}
        ],
        "status": {"$nin": ["Completed", "Archived", "Posted", "Deleted"]}
    })
    
    # 3. Needs Approval - Validated but awaiting human sign-off
    needs_approval = await db.hub_documents.count_documents({
        **df,
        "validation_results.all_passed": True,
        "status": {"$nin": ["Completed", "Archived", "Posted", "Deleted"]},
        "$or": [
            {"workflow_status": "ready_for_approval"},
            {"workflow_status": "validated"},
            {"workflow_status": "ready_for_post"},
            # Also include docs that passed validation but haven't been posted
            {"$and": [
                {"bc_record_id": {"$exists": True}},
                {"bc_posting_status": {"$nin": ["posted", "completed"]}}
            ]}
        ]
    })
    
    # ============== VALIDATION SUCCESS ==============
    # Overall validation rates
    total_validated = await db.hub_documents.count_documents({
        **df, "validation_results": {"$exists": True}
    })
    
    validation_passed = await db.hub_documents.count_documents({
        **df, "validation_results.all_passed": True
    })
    
    validation_failed = await db.hub_documents.count_documents({
        **df, "validation_results.all_passed": False
    })
    
    # Validation failure reasons
    failure_reasons_pipeline = [
        {"$match": {**df, "validation_results.all_passed": False}},
        {"$unwind": "$validation_results.checks"},
        {"$match": {"validation_results.checks.passed": False}},
        {"$group": {
            "_id": "$validation_results.checks.check_name",
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}}
    ]
    failure_reasons = await db.hub_documents.aggregate(failure_reasons_pipeline).to_list(20)
    
    # ============== PROCESSING EFFICIENCY ==============
    # Documents by workflow status
    workflow_status_pipeline = [
        {"$match": {**df}},
        {"$group": {
            "_id": {"$ifNull": ["$workflow_status", "unknown"]},
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}}
    ]
    by_workflow_status = await db.hub_documents.aggregate(workflow_status_pipeline).to_list(30)
    
    # Auto-clear statistics
    auto_cleared = await db.hub_documents.count_documents({**df, "auto_cleared": True})
    
    # Processing success (documents that reached Completed/Posted/Archived)
    processing_complete = await db.hub_documents.count_documents({
        **df, "status": {"$in": ["Completed", "Posted", "Archived", "LinkedToBC"]}
    })
    
    # Documents stuck (Exception status or auto_escalated)
    stuck_docs = await db.hub_documents.count_documents({
        **df,
        "$or": [
            {"status": "Exception"},
            {"auto_escalated": True}
        ]
    })
    
    # Average retry count for documents
    retry_stats_pipeline = [
        {"$match": {**df, "retry_count": {"$gt": 0}}},
        {"$group": {
            "_id": None,
            "avg_retries": {"$avg": "$retry_count"},
            "max_retries": {"$max": "$retry_count"},
            "total_retries": {"$sum": "$retry_count"},
            "docs_with_retries": {"$sum": 1}
        }}
    ]
    retry_stats = await db.hub_documents.aggregate(retry_stats_pipeline).to_list(1)
    retry_data = retry_stats[0] if retry_stats else {"avg_retries": 0, "max_retries": 0, "total_retries": 0, "docs_with_retries": 0}
    
    # ============== BC INTEGRATION SUCCESS ==============
    # Documents linked to BC
    bc_linked = await db.hub_documents.count_documents({
        **df,
        "$or": [
            {"bc_record_id": {"$exists": True, "$ne": None}},
            {"bc_document_id": {"$exists": True, "$ne": None}},
            {"status": "LinkedToBC"}
        ]
    })
    
    # Documents posted to BC
    bc_posted = await db.hub_documents.count_documents({
        **df,
        "$or": [
            {"bc_posting_status": "posted"},
            {"status": "Posted"}
        ]
    })
    
    # BC posting failures
    bc_post_failed = await db.hub_documents.count_documents({
        **df, "bc_posting_status": {"$in": ["failed", "error"]}
    })
    
    # ============== SHAREPOINT ARCHIVAL ==============
    # Documents archived to SharePoint
    sp_archived = await db.hub_documents.count_documents({
        **df, "sharepoint_item_id": {"$exists": True, "$ne": None}
    })
    
    # Folder routing distribution
    folder_routing_pipeline = [
        {"$match": {**df, "sharepoint_folder_path": {"$exists": True, "$ne": None}}},
        {"$group": {
            "_id": "$sharepoint_folder_path",
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]
    folder_distribution = await db.hub_documents.aggregate(folder_routing_pipeline).to_list(10)
    
    # ============== DOCUMENT SOURCES ==============
    # Ingestion source breakdown
    source_pipeline = [
        {"$match": {**df}},
        {"$group": {
            "_id": {"$ifNull": ["$source", "unknown"]},
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}}
    ]
    by_source = await db.hub_documents.aggregate(source_pipeline).to_list(20)
    
    # ============== SPIRO INTEGRATION ==============
    spiro_companies = await db.spiro_companies.count_documents({})
    spiro_freight_carriers = await db.spiro_companies.count_documents({
        "$or": [
            {"industry": {"$regex": "freight|transport|logistics", "$options": "i"}},
            {"is_freight": True}
        ]
    })
    
    # ============== TIME-BASED TRENDS (Last 7 days) ==============
    from datetime import timedelta
    seven_days_ago = (datetime.now(GPI_TZ) - timedelta(days=7)).astimezone(timezone.utc).isoformat()
    
    daily_trend_pipeline = [
        {"$match": {**df} if df else {"created_utc": {"$gte": seven_days_ago}}},
        {"$addFields": {
            "date": {"$substr": ["$created_utc", 0, 10]}
        }},
        {"$group": {
            "_id": "$date",
            "total": {"$sum": 1},
            "validated": {"$sum": {"$cond": [{"$eq": ["$validation_results.all_passed", True]}, 1, 0]}},
            "exceptions": {"$sum": {"$cond": [{"$eq": ["$status", "Exception"]}, 1, 0]}}
        }},
        {"$sort": {"_id": 1}}
    ]
    daily_trends = await db.hub_documents.aggregate(daily_trend_pipeline).to_list(7)
    
    # Calculate totals
    total_docs = await db.hub_documents.count_documents(df)
    docs_with_vendor = await db.hub_documents.count_documents({**df, "vendor_canonical": {"$exists": True, "$ne": None}})
    
    # Calculate success rates
    validation_rate = round((validation_passed / total_validated * 100) if total_validated > 0 else 0, 1)
    processing_rate = round((processing_complete / total_docs * 100) if total_docs > 0 else 0, 1)

    # ============== ACCURATE VENDOR KPI (vendor-applicable denominator) ==============
    # Vendor-applicable = document types where vendor resolution is expected
    VENDOR_APPLICABLE_TYPES = [
        "AP_Invoice", "AP_INVOICE", "PurchaseInvoice", "PurchaseOrder",
        "Remittance", "REMITTANCE", "Credit_Memo", "CREDIT_MEMO",
        "Purchase_Invoice", "PURCHASE_INVOICE",
    ]
    vendor_applicable_filter = {
        **df,
        "$or": [
            {"doc_type": {"$in": VENDOR_APPLICABLE_TYPES}},
            {"suggested_job_type": {"$in": VENDOR_APPLICABLE_TYPES}},
            # Include any doc that already has vendor_resolution (it was attempted)
            {"vendor_resolution.status": {"$exists": True}},
        ]
    }
    vendor_applicable_total = await db.hub_documents.count_documents(vendor_applicable_filter)

    # Auto-resolved: resolved by system without human override
    AUTO_RESOLVE_METHODS = [
        "alias_match", "bc_exact_match", "bc_search", "fuzzy_match",
        "alias", "learned_alias", "exact_name", "normalized",
        "sender_email", "sender_domain", "extracted_field",
    ]
    vendor_auto_resolved_total = await db.hub_documents.count_documents({
        "$and": [
            vendor_applicable_filter,
            {
                "vendor_match_method": {"$in": AUTO_RESOLVE_METHODS},
                "$or": [
                    {"vendor_resolution.reviewed_override": {"$ne": True}},
                    {"vendor_resolution.reviewed_override": {"$exists": False}},
                ],
            },
        ]
    })

    # Final resolved: vendor resolved at final state (any method, including human override)
    vendor_final_resolved_total = await db.hub_documents.count_documents({
        **vendor_applicable_filter,
        "vendor_canonical": {"$exists": True, "$ne": None},
    })

    # Needs vendor review: applicable docs currently unresolved or fuzzy_candidate
    vendor_needs_review_total = await db.hub_documents.count_documents({
        "$and": [
            vendor_applicable_filter,
            {
                "$or": [
                    {"vendor_canonical": {"$exists": False}},
                    {"vendor_canonical": None},
                    {"vendor_match_method": "fuzzy_candidate"},
                    {"vendor_resolution.status": "needs_review"},
                ],
                "status": {"$nin": ["Completed", "Archived", "Posted", "Deleted"]},
            },
        ]
    })

    vendor_auto_resolve_rate = round(
        (vendor_auto_resolved_total / vendor_applicable_total * 100) if vendor_applicable_total > 0 else 0, 1
    )
    vendor_final_resolved_rate = round(
        (vendor_final_resolved_total / vendor_applicable_total * 100) if vendor_applicable_total > 0 else 0, 1
    )

    # Method breakdown for applicable docs only
    vendor_method_pipeline = [
        {"$match": vendor_applicable_filter},
        {"$group": {"_id": "$vendor_match_method", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    vendor_method_raw = await db.hub_documents.aggregate(vendor_method_pipeline).to_list(20)
    vendor_by_method = {r["_id"]: r["count"] for r in vendor_method_raw if r["_id"]}
    
    # ============== ROUTING STATUS (Auto-Clear Gate) ==============
    routing_pipeline = [
        {"$match": {**df, "routing_status": {"$exists": True, "$ne": None}}},
        {"$group": {
            "_id": "$routing_status",
            "count": {"$sum": 1},
            "avg_score": {"$avg": "$routing_score"},
        }},
    ]
    routing_raw = await db.hub_documents.aggregate(routing_pipeline).to_list(10)
    routing_counts = {}
    for r in routing_raw:
        if r["_id"]:
            routing_counts[r["_id"]] = {
                "count": r["count"],
                "avg_score": round(r.get("avg_score") or 0, 1),
            }
    total_routed = sum(v["count"] for v in routing_counts.values())

    # ============== READINESS STATUS ==============
    readiness_status_pipeline = [
        {"$match": {**df}},
        {"$group": {"_id": "$readiness.status", "count": {"$sum": 1}}},
    ]
    readiness_raw = await db.hub_documents.aggregate(readiness_status_pipeline).to_list(10)
    readiness_by_status = {r["_id"]: r["count"] for r in readiness_raw if r["_id"]}
    no_readiness = total_docs - sum(readiness_by_status.values())

    readiness_action_pipeline = [
        {"$match": {**df, "readiness.recommended_action": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$readiness.recommended_action", "count": {"$sum": 1}}},
    ]
    readiness_action_raw = await db.hub_documents.aggregate(readiness_action_pipeline).to_list(10)
    readiness_by_action = {r["_id"]: r["count"] for r in readiness_action_raw if r["_id"]}

    readiness_conf_pipeline = [
        {"$match": {**df, "readiness.confidence": {"$exists": True}}},
        {"$group": {"_id": "$readiness.status", "avg_confidence": {"$avg": "$readiness.confidence"}}},
    ]
    readiness_conf_raw = await db.hub_documents.aggregate(readiness_conf_pipeline).to_list(10)
    readiness_confidence = {r["_id"]: round(r["avg_confidence"], 3) for r in readiness_conf_raw if r["_id"]}

    readiness_block_pipeline = [
        {"$match": {**df, "readiness.blocking_reasons": {"$exists": True, "$ne": []}}},
        {"$unwind": "$readiness.blocking_reasons"},
        {"$group": {"_id": "$readiness.blocking_reasons", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    readiness_block_raw = await db.hub_documents.aggregate(readiness_block_pipeline).to_list(10)
    top_blocking = [{"reason": r["_id"], "count": r["count"]} for r in readiness_block_raw if r["_id"]]

    readiness_warn_pipeline = [
        {"$match": {**df, "readiness.warning_reasons": {"$exists": True, "$ne": []}}},
        {"$unwind": "$readiness.warning_reasons"},
        {"$group": {"_id": "$readiness.warning_reasons", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    readiness_warn_raw = await db.hub_documents.aggregate(readiness_warn_pipeline).to_list(10)
    top_warnings = [{"reason": r["_id"], "count": r["count"]} for r in readiness_warn_raw if r["_id"]]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_documents": total_docs,
        
        # Routing Summary (Auto-Clear Gate)
        "routing_summary": {
            "total_routed": total_routed,
            "counts": routing_counts,
        },
        
        # Action Required Queues - clear, actionable counts
        "action_required": {
            "needs_vendor_review": needs_vendor_review,
            "needs_po_match": needs_po_match,
            "needs_approval": needs_approval,
            "total_action_needed": needs_vendor_review + needs_po_match + needs_approval
        },
        
        "vendor_intelligence": {
            "total_with_vendor": docs_with_vendor,
            # Accurate vendor KPIs with vendor-applicable denominator
            "vendor_applicable_total": vendor_applicable_total,
            "vendor_auto_resolved_total": vendor_auto_resolved_total,
            "vendor_auto_resolve_rate": vendor_auto_resolve_rate,
            "vendor_final_resolved_total": vendor_final_resolved_total,
            "vendor_final_resolved_rate": vendor_final_resolved_rate,
            "vendor_needs_review_total": vendor_needs_review_total,
            "vendor_by_method": vendor_by_method,
            # Legacy compat (deprecated — use above instead)
            "vendor_extraction_rate": vendor_final_resolved_rate,
            "needs_vendor_review": needs_vendor_review,
            "freight_carriers_detected": freight_docs,
            "match_methods": {
                item["_id"]: {
                    "count": item["count"],
                    "avg_score": round(item.get("avg_score", 0) * 100, 1) if item.get("avg_score") else 0
                } for item in match_method_results if item["_id"]
            },
            "matches_by_source": {
                item["_id"]: {
                    "count": item["count"],
                    "avg_score": round(item.get("avg_score", 0) * 100, 1) if item.get("avg_score") else 0
                } for item in cached_by_source if item["_id"]
            },
            "cached_vendor_matches": await db.vendor_matches.count_documents({}),
            "spiro_companies_available": spiro_companies,
            "spiro_freight_carriers": spiro_freight_carriers,
            "alias_metrics": await _get_alias_metrics_safe(db, vendor_applicable_total),
        },
        
        "validation_metrics": {
            "total_validated": total_validated,
            "passed": validation_passed,
            "failed": validation_failed,
            "pass_rate": validation_rate,
            "failure_reasons": {item["_id"]: item["count"] for item in failure_reasons if item["_id"]}
        },
        
        "processing_metrics": {
            "completed": processing_complete,
            "stuck": stuck_docs,
            "auto_cleared": auto_cleared,
            "success_rate": processing_rate,
            "retry_stats": {
                "avg_retries": round(retry_data.get("avg_retries", 0), 1),
                "max_retries": retry_data.get("max_retries", 0),
                "total_retries": retry_data.get("total_retries", 0),
                "docs_requiring_retry": retry_data.get("docs_with_retries", 0)
            },
            "by_workflow_status": {item["_id"]: item["count"] for item in by_workflow_status if item["_id"]}
        },
        
        "bc_integration": {
            "linked_to_bc": bc_linked,
            "posted_to_bc": bc_posted,
            "post_failures": bc_post_failed,
            "link_rate": round((bc_linked / total_docs * 100) if total_docs > 0 else 0, 1)
        },
        
        "sharepoint_archival": {
            "documents_archived": sp_archived,
            "archive_rate": round((sp_archived / total_docs * 100) if total_docs > 0 else 0, 1),
            "top_folders": {item["_id"]: item["count"] for item in folder_distribution if item["_id"]}
        },
        
        # Readiness Summary (Document Readiness Engine)
        "readiness_summary": {
            "by_status": readiness_by_status,
            "by_action": readiness_by_action,
            "no_readiness_data": no_readiness,
            "confidence_by_status": readiness_confidence,
            "top_blocking_reasons": top_blocking,
            "top_warning_reasons": top_warnings,
        },

        "ingestion_sources": {item["_id"]: item["count"] for item in by_source if item["_id"]},
        
        "daily_trends": [
            {
                "date": item["_id"],
                "total": item["total"],
                "validated": item["validated"],
                "exceptions": item["exceptions"]
            } for item in daily_trends
        ]
    }



@router.get("/document-types")
async def get_document_types_dashboard(
    source_system: Optional[str] = Query(None, description="Filter by source_system: SQUARE9, ZETADOCS, GPI_HUB_NATIVE"),
    doc_type: Optional[str] = Query(None, description="Filter to specific doc_type"),
    classification: Optional[str] = Query(None, description="Filter by classification method: deterministic, ai, all")
):
    """
    Document Type Dashboard API.
    Returns comprehensive metrics per doc_type:
    - Total counts and workflow status breakdown
    - Field extraction rates (vendor, invoice_number, amount, po_number, due_date)
    - Match method distribution (exact, normalized, alias, fuzzy, manual, none)
    """
    db = get_db()
    # Normalize classification filter
    classification_filter = classification if classification in ("deterministic", "ai") else None
    
    from services.dashboard_helpers import aggregate_document_types_data
    data = await aggregate_document_types_data(source_system, doc_type, classification_filter)
    
    by_type = data["by_type"]
    source_systems = data["source_systems"]
    
    # Remove doc_types with 0 documents unless specifically filtered
    if not doc_type:
        by_type = {k: v for k, v in by_type.items() if v["total"] > 0}
    
    # Calculate totals
    grand_total = sum(v["total"] for v in by_type.values())
    
    # Calculate classification totals across all doc_types
    total_deterministic = sum(v.get("classification_counts", {}).get("deterministic", 0) for v in by_type.values())
    total_ai = sum(v.get("classification_counts", {}).get("ai", 0) for v in by_type.values())
    total_other = sum(v.get("classification_counts", {}).get("other", 0) for v in by_type.values())
    
    return {
        "by_type": by_type,
        "filters": {
            "source_system": source_system,
            "doc_type": doc_type,
            "classification": classification_filter
        },
        "source_systems_available": source_systems,
        "doc_types_available": list(by_type.keys()),
        "classification_methods_available": ["all", "deterministic", "ai"],
        "grand_total": grand_total,
        "classification_totals": {
            "deterministic": total_deterministic,
            "ai": total_ai,
            "other": total_other
        }
    }



@router.get("/document-types/export")
async def export_document_types_dashboard(
    source_system: Optional[str] = Query(None, description="Filter by source_system"),
    doc_type: Optional[str] = Query(None, description="Filter by doc_type"),
    classification: Optional[str] = Query(None, description="Filter by classification method: deterministic, ai, all"),
    format: str = Query("csv", description="Export format (csv)")
):
    """
    Export Document Type Dashboard data as CSV.
    Reuses the same aggregation logic as /api/dashboard/document-types.
    
    Returns one row per (doc_type, status) combination with all metrics.
    """
    db = get_db()
    # Normalize classification filter
    classification_filter = classification if classification in ("deterministic", "ai") else None
    
    from services.dashboard_helpers import aggregate_document_types_data
    data = await aggregate_document_types_data(source_system, doc_type, classification_filter)
    
    by_type = data["by_type"]
    source_system_filter = data["source_system_filter"] or "ALL"
    classification_filter_label = classification_filter or "ALL"
    
    # Remove empty doc_types unless specifically filtered
    if not doc_type:
        by_type = {k: v for k, v in by_type.items() if v["total"] > 0}
    
    # Prepare CSV output
    output = io.StringIO()
    
    fieldnames = [
        'doc_type',
        'source_system',
        'classification_filter',
        'total',
        'status',
        'status_count',
        'vendor_extraction_rate',
        'invoice_number_extraction_rate',
        'amount_extraction_rate',
        'po_number_extraction_rate',
        'due_date_extraction_rate',
        'match_exact',
        'match_normalized',
        'match_alias',
        'match_fuzzy',
        'match_manual',
        'match_none',
        'classification_deterministic',
        'classification_ai',
        'classification_other',
        'ai_assisted_count',
        'ai_suggested_but_rejected_count'
    ]
    
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    
    # Flatten data: one row per (doc_type, status) combination
    for dt, type_data in sorted(by_type.items()):
        extraction = type_data.get("extraction", {})
        match_methods = type_data.get("match_methods", {})
        classification_counts = type_data.get("classification_counts", {})
        
        # Common fields for all rows of this doc_type
        common_fields = {
            'doc_type': dt,
            'source_system': source_system_filter,
            'classification_filter': classification_filter_label,
            'total': type_data.get("total", 0),
            'vendor_extraction_rate': extraction.get("vendor", {}).get("rate", 0),
            'invoice_number_extraction_rate': extraction.get("invoice_number", {}).get("rate", 0),
            'amount_extraction_rate': extraction.get("amount", {}).get("rate", 0),
            'po_number_extraction_rate': extraction.get("po_number", {}).get("rate", 0),
            'due_date_extraction_rate': extraction.get("due_date", {}).get("rate", 0),
            'match_exact': match_methods.get("exact", 0),
            'match_normalized': match_methods.get("normalized", 0),
            'match_alias': match_methods.get("alias", 0),
            'match_fuzzy': match_methods.get("fuzzy", 0),
            'match_manual': match_methods.get("manual", 0),
            'match_none': match_methods.get("none", 0),
            'classification_deterministic': classification_counts.get("deterministic", 0),
            'classification_ai': classification_counts.get("ai", 0),
            'classification_other': classification_counts.get("other", 0),
            'ai_assisted_count': type_data.get("ai_assisted_count", 0),
            'ai_suggested_but_rejected_count': type_data.get("ai_suggested_but_rejected_count", 0)
        }
        
        # Get all statuses for this doc_type
        status_counts = type_data.get("status_counts", {})
        
        if not status_counts:
            # If no status counts, write one row with just the doc_type info
            writer.writerow({**common_fields, 'status': '', 'status_count': 0})
        else:
            # Write one row per status
            for status, count in sorted(status_counts.items()):
                writer.writerow({**common_fields, 'status': status, 'status_count': count})
    
    csv_content = output.getvalue()
    output.close()
    
    # Generate filename with timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"document_types_dashboard_{timestamp}.csv"
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


# ==================== SHAREPOINT FOLDER STRUCTURE (Accounting) ====================


@router.get("/routing-summary")
async def get_routing_summary():
    """Get document routing status summary (Auto-Clear Gate metrics)."""
    from services.document_routing_service import get_routing_summary as _get_routing_summary
    return await _get_routing_summary()


@router.get("/email-stats")
async def get_email_stats():
    """Get email processing statistics."""
    db = get_db()
    total_email = await db.hub_documents.count_documents({"source": "email"})
    needs_review = await db.hub_documents.count_documents({"source": "email", "status": "NeedsReview"})
    auto_linked = await db.hub_documents.count_documents({"source": "email", "status": "LinkedToBC"})
    stored_sp = await db.hub_documents.count_documents({"source": "email", "status": "StoredInSP"})
    
    # Get by job type
    by_job_type = {}
    from models.document_types import DEFAULT_JOB_TYPES
    for jt in DEFAULT_JOB_TYPES.keys():
        count = await db.hub_documents.count_documents({"source": "email", "suggested_job_type": jt})
        if count > 0:
            by_job_type[jt] = count
    
    # Recent email documents
    recent = await db.hub_documents.find(
        {"source": "email"},
        {"_id": 0}
    ).sort("created_utc", -1).limit(10).to_list(10)
    
    return {
        "total_email_documents": total_email,
        "needs_review": needs_review,
        "auto_linked": auto_linked,
        "stored_sp": stored_sp,
        "by_job_type": by_job_type,
        "recent": recent
    }

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

    # Auto-validation rate: docs where automation_decision=auto OR auto_cleared=True
    auto_processed = await db.hub_documents.count_documents({
        "$or": [
            {"automation_decision": "auto"},
            {"auto_cleared": True},
            {"sales_review_status": "auto_approved"},
        ]
    })
    non_batch_total = await db.hub_documents.count_documents({"status": {"$ne": "batch_parent"}})
    auto_rate = round((auto_processed / non_batch_total * 100), 1) if non_batch_total > 0 else 0

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
    }


@router.get("/inbox-metrics")
async def get_inbox_metrics(
    scope: str = Query("all", description="Tab scope: all, accounting, sales, processed, exceptions, po_pending"),
):
    """Detailed breakdown of documents for the active tab scope."""
    db = get_db()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    TERMINAL_STATUSES = [
        "Completed", "Posted", "Archived", "completed", "posted", "archived",
        "FileMissing", "batch_parent", "Validated", "validated", "ValidationPassed",
        "ReadyForPost", "ready_for_post", "AutoFiled", "auto_filed", "LinkedToBC",
        "Exception", "exception",
    ]
    DONE_WF = ["completed", "validation_passed", "processed", "ready_for_approval",
               "exported", "file_missing", "exception_review", "po_pending"]

    AP_TYPES = ["AP_INVOICE", "AP_Invoice", "AP Invoice", "FREIGHT_INVOICE",
                "Freight Invoice", "CREDIT_MEMO", "Credit Memo"]
    SALES_TYPES = ["SALES_ORDER", "Sales Order", "PURCHASE_ORDER", "Purchase Order",
                   "SHIPPING", "Shipping", "BOL"]

    # ── Build scope-specific filter ──
    if scope == "exceptions":
        base_filter = {
            "$and": [
                {"is_duplicate": {"$ne": True}},
                {"workflow_status": "exception_review"},
            ]
        }
    elif scope == "po_pending":
        base_filter = {
            "$and": [
                {"is_duplicate": {"$ne": True}},
                {"workflow_status": "po_pending"},
            ]
        }
    elif scope == "processed":
        base_filter = {
            "$and": [
                {"is_duplicate": {"$ne": True}},
                {"$or": [
                    {"status": {"$in": TERMINAL_STATUSES}},
                    {"workflow_status": {"$in": DONE_WF}},
                    {"auto_cleared": True},
                ]},
            ]
        }
    else:
        # Active inbox (all / accounting / sales)
        base_filter = {
            "$and": [
                {"is_duplicate": {"$ne": True}},
                {"$or": [{"auto_cleared": {"$ne": True}}, {"auto_cleared": {"$exists": False}}]},
                {"status": {"$nin": TERMINAL_STATUSES}},
                {"$or": [
                    {"workflow_status": {"$nin": DONE_WF}},
                    {"workflow_status": {"$exists": False}},
                ]},
            ]
        }
        # Narrow by doc type for accounting/sales tabs
        if scope == "accounting":
            base_filter["$and"].append(
                {"$or": [{"doc_type": {"$in": AP_TYPES}}, {"document_type": {"$in": AP_TYPES}}]}
            )
        elif scope == "sales":
            base_filter["$and"].append(
                {"$or": [{"doc_type": {"$in": SALES_TYPES}}, {"document_type": {"$in": SALES_TYPES}}]}
            )

    inbox_filter = base_filter

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


@router.get("/insights-trends")
async def get_insights_trends(days: int = Query(30, le=90)):
    """
    Daily trending data for the Insights page:
    ingestion volume, auto-validation rate, AI confidence, vendor resolve rate.
    """
    db = get_db()
    tz = GPI_TZ
    cutoff = (datetime.now(tz) - timedelta(days=days)).astimezone(timezone.utc).isoformat()

    # Daily aggregation: total, auto-processed, validated, avg confidence
    pipeline = [
        {"$match": {"created_utc": {"$gte": cutoff}, "status": {"$ne": "batch_parent"}}},
        {"$addFields": {"day": {"$substr": ["$created_utc", 0, 10]}}},
        {"$group": {
            "_id": "$day",
            "total": {"$sum": 1},
            "auto_processed": {"$sum": {"$cond": [
                {"$or": [
                    {"$eq": ["$automation_decision", "auto"]},
                    {"$eq": ["$auto_cleared", True]},
                    {"$eq": ["$sales_review_status", "auto_approved"]},
                ]}, 1, 0
            ]}},
            "validated": {"$sum": {"$cond": [
                {"$eq": [{"$ifNull": ["$validation_results.all_passed", False]}, True]},
                1, 0
            ]}},
            "exceptions": {"$sum": {"$cond": [{"$eq": ["$status", "Exception"]}, 1, 0]}},
            "avg_confidence": {"$avg": {"$ifNull": ["$ai_confidence", None]}},
            "vendor_resolved": {"$sum": {"$cond": [
                {"$and": [
                    {"$ne": [{"$ifNull": ["$vendor_canonical", None]}, None]},
                    {"$ne": ["$vendor_canonical", ""]},
                ]}, 1, 0
            ]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    daily_raw = await db.hub_documents.aggregate(pipeline).to_list(days)

    daily = []
    for d in daily_raw:
        total = d["total"]
        daily.append({
            "date": d["_id"],
            "ingested": total,
            "auto_rate": round((d["auto_processed"] / total * 100) if total > 0 else 0, 1),
            "validation_rate": round((d["validated"] / total * 100) if total > 0 else 0, 1),
            "exception_rate": round((d["exceptions"] / total * 100) if total > 0 else 0, 1),
            "ai_confidence": round((d["avg_confidence"] or 0) * 100, 1),
            "vendor_resolve_rate": round((d["vendor_resolved"] / total * 100) if total > 0 else 0, 1),
        })

    # Bakeoff accuracy snapshots (latest runs)
    bakeoff_runs = await db.intake_benchmark_runs.find(
        {"status": {"$in": ["completed", "active"]}},
        {"_id": 0, "id": 1, "name": 1, "created_at": 1, "summary.total_docs": 1,
         "summary.avg_folder_score": 1, "summary.folder_accuracy_pct": 1,
         "summary.avg_extraction_score": 1}
    ).sort("created_at", -1).limit(10).to_list(10)

    return {
        "daily": daily,
        "bakeoff_runs": bakeoff_runs,
        "period_days": days,
    }


@router.get("/ap-metrics")
async def get_ap_metrics():
    """AP Invoice posting metrics: submitted, failed, pending, timing, errors."""
    db = get_db()

    AP_TYPES = ["AP_Invoice", "AP_INVOICE", "Purchase_Invoice", "PURCHASE_INVOICE", "PurchaseInvoice"]

    total_ap = await db.hub_documents.count_documents({"document_type": {"$in": AP_TYPES}})
    posted = await db.hub_documents.count_documents({
        "document_type": {"$in": AP_TYPES},
        "bc_posting_status": "posted",
    })
    failed = await db.hub_documents.count_documents({
        "document_type": {"$in": AP_TYPES},
        "bc_posting_status": "failed",
    })
    pending_review = await db.hub_documents.count_documents({
        "document_type": {"$in": AP_TYPES},
        "bc_posting_status": {"$nin": ["posted", "failed"]},
        "status": {"$nin": ["Completed", "Posted", "Archived", "batch_parent"]},
    })

    # Validation pass rate
    validated = await db.hub_documents.count_documents({
        "document_type": {"$in": AP_TYPES},
        "validation_results.all_passed": True,
    })
    validation_rate = round((validated / total_ap * 100) if total_ap > 0 else 0, 1)

    # Average time from ingestion to BC posting (for posted docs)
    posted_docs = await db.hub_documents.find(
        {"document_type": {"$in": AP_TYPES}, "bc_posting_status": "posted",
         "created_utc": {"$exists": True}, "bc_posted_at": {"$exists": True}},
        {"_id": 0, "created_utc": 1, "bc_posted_at": 1}
    ).limit(100).to_list(100)
    avg_time_hours = 0
    if posted_docs:
        deltas = []
        for d in posted_docs:
            try:
                created = datetime.fromisoformat(d["created_utc"].replace("Z", "+00:00"))
                posted_at = datetime.fromisoformat(d["bc_posted_at"].replace("Z", "+00:00"))
                delta_h = (posted_at - created).total_seconds() / 3600
                if delta_h > 0:
                    deltas.append(delta_h)
            except Exception:
                pass
        if deltas:
            avg_time_hours = round(sum(deltas) / len(deltas), 1)

    # Error breakdown (top reasons)
    error_pipeline = [
        {"$match": {"document_type": {"$in": AP_TYPES}, "bc_posting_status": "failed", "bc_posting_error": {"$exists": True}}},
        {"$group": {"_id": "$bc_posting_error", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    errors_raw = await db.hub_documents.aggregate(error_pipeline).to_list(5)
    error_breakdown = [{"reason": e["_id"][:80], "count": e["count"]} for e in errors_raw if e["_id"]]

    return {
        "total_ap": total_ap,
        "posted_to_bc": posted,
        "failed": failed,
        "pending_review": pending_review,
        "validation_rate": validation_rate,
        "avg_time_to_post_hours": avg_time_hours,
        "success_rate": round((posted / total_ap * 100) if total_ap > 0 else 0, 1),
        "error_breakdown": error_breakdown,
    }
