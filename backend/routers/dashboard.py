"""GPI Document Hub - Dashboard Router"""

from fastapi import APIRouter, Query, Response
from typing import Optional
from datetime import datetime, timezone, timedelta
from deps import get_db, DEMO_MODE

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def get_dashboard_stats():
    db = get_db()
    total = await db.hub_documents.count_documents({})
    by_status = {}
    for s in ["Received", "Classified", "LinkedToBC", "Exception", "Completed"]:
        by_status[s] = await db.hub_documents.count_documents({"status": s})
    by_type = {}
    for t in ["SalesOrder", "SalesInvoice", "PurchaseInvoice", "PurchaseOrder", "Shipment", "Receipt", "Other"]:
        count = await db.hub_documents.count_documents({"document_type": t})
        if count > 0:
            by_type[t] = count
    recent_workflows = await db.hub_workflow_runs.find({}, {"_id": 0}).sort("started_utc", -1).limit(10).to_list(10)
    failed_workflows = await db.hub_workflow_runs.find({"status": "Failed"}, {"_id": 0}).sort("started_utc", -1).limit(10).to_list(10)
    return {
        "total_documents": total, "by_status": by_status, "by_type": by_type,
        "recent_workflows": recent_workflows, "failed_workflows": failed_workflows,
        "demo_mode": DEMO_MODE
    }



@router.get("/workflow-intelligence")
async def get_workflow_intelligence_stats():
    """
    Comprehensive workflow intelligence metrics.
    Provides insights into vendor matching, validation success, processing efficiency,
    and automation performance across the entire document processing pipeline.
    """
    db = get_db()
    
    # ============== VENDOR INTELLIGENCE ==============
    # Vendor match statistics by source
    vendor_match_pipeline = [
        {"$match": {"vendor_canonical": {"$exists": True, "$ne": None}}},
        {"$group": {
            "_id": {"$ifNull": ["$unified_vendor_match.sources_checked", ["unknown"]]},
            "count": {"$sum": 1}
        }}
    ]
    
    # Get vendor match method distribution
    match_method_pipeline = [
        {"$match": {"validation_results.match_method": {"$exists": True}}},
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
        "$or": [
            {"extracted_data.is_freight_carrier": True},
            {"unified_vendor_match.is_freight_carrier": True},
            {"validation_results.checks": {"$elemMatch": {"is_freight_carrier": True}}}
        ]
    })
    
    # ============== ACTION REQUIRED QUEUES ==============
    # 1. Needs Vendor Review - AP invoices with no vendor match
    needs_vendor_review = await db.hub_documents.count_documents({
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
        "validation_results": {"$exists": True}
    })
    
    validation_passed = await db.hub_documents.count_documents({
        "validation_results.all_passed": True
    })
    
    validation_failed = await db.hub_documents.count_documents({
        "validation_results.all_passed": False
    })
    
    # Validation failure reasons
    failure_reasons_pipeline = [
        {"$match": {"validation_results.all_passed": False}},
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
        {"$group": {
            "_id": {"$ifNull": ["$workflow_status", "unknown"]},
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}}
    ]
    by_workflow_status = await db.hub_documents.aggregate(workflow_status_pipeline).to_list(30)
    
    # Auto-clear statistics
    auto_cleared = await db.hub_documents.count_documents({"auto_cleared": True})
    
    # Processing success (documents that reached Completed/Posted/Archived)
    processing_complete = await db.hub_documents.count_documents({
        "status": {"$in": ["Completed", "Posted", "Archived", "LinkedToBC"]}
    })
    
    # Documents stuck (Exception status or auto_escalated)
    stuck_docs = await db.hub_documents.count_documents({
        "$or": [
            {"status": "Exception"},
            {"auto_escalated": True}
        ]
    })
    
    # Average retry count for documents
    retry_stats_pipeline = [
        {"$match": {"retry_count": {"$gt": 0}}},
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
        "$or": [
            {"bc_record_id": {"$exists": True, "$ne": None}},
            {"bc_document_id": {"$exists": True, "$ne": None}},
            {"status": "LinkedToBC"}
        ]
    })
    
    # Documents posted to BC
    bc_posted = await db.hub_documents.count_documents({
        "$or": [
            {"bc_posting_status": "posted"},
            {"status": "Posted"}
        ]
    })
    
    # BC posting failures
    bc_post_failed = await db.hub_documents.count_documents({
        "bc_posting_status": {"$in": ["failed", "error"]}
    })
    
    # ============== SHAREPOINT ARCHIVAL ==============
    # Documents archived to SharePoint
    sp_archived = await db.hub_documents.count_documents({
        "sharepoint_item_id": {"$exists": True, "$ne": None}
    })
    
    # Folder routing distribution
    folder_routing_pipeline = [
        {"$match": {"sharepoint_folder_path": {"$exists": True, "$ne": None}}},
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
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    
    daily_trend_pipeline = [
        {"$match": {"created_utc": {"$gte": seven_days_ago}}},
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
    total_docs = await db.hub_documents.count_documents({})
    docs_with_vendor = await db.hub_documents.count_documents({"vendor_canonical": {"$exists": True, "$ne": None}})
    
    # Calculate success rates
    validation_rate = round((validation_passed / total_validated * 100) if total_validated > 0 else 0, 1)
    processing_rate = round((processing_complete / total_docs * 100) if total_docs > 0 else 0, 1)
    vendor_rate = round((docs_with_vendor / total_docs * 100) if total_docs > 0 else 0, 1)
    
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_documents": total_docs,
        
        # Action Required Queues - clear, actionable counts
        "action_required": {
            "needs_vendor_review": needs_vendor_review,
            "needs_po_match": needs_po_match,
            "needs_approval": needs_approval,
            "total_action_needed": needs_vendor_review + needs_po_match + needs_approval
        },
        
        "vendor_intelligence": {
            "total_with_vendor": docs_with_vendor,
            "vendor_extraction_rate": vendor_rate,
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
            "spiro_freight_carriers": spiro_freight_carriers
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


