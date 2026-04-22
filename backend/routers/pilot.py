"""GPI Document Hub - Pilot Mode Router

BC Sandbox simulation, re-ingestion, daily metrics.
All operations are READ-ONLY observation mode.
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Query, Body, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Optional, List
from deps import get_db
from services.pilot_config import PILOT_MODE_ENABLED, CURRENT_PILOT_PHASE, get_pilot_status
from services.pilot_summary import DAILY_PILOT_EMAIL_ENABLED, PILOT_SUMMARY_RECIPIENTS, PILOT_SUMMARY_CRON_HOUR_UTC
from services.vendor_name_helpers import normalize_vendor_name, VENDOR_ALIAS_MAP

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pilot", tags=["Pilot"])


class MailboxSource(BaseModel):
    """Configuration for a document intake mailbox source."""
    mailbox_id: Optional[str] = None
    name: str
    email_address: str
    category: str = "AP"
    enabled: bool = True
    polling_interval_minutes: int = 5
    watch_folder: str = "Inbox"
    needs_review_folder: str = "Needs Review"
    processed_folder: str = "Processed"
    description: Optional[str] = None
    created_utc: Optional[str] = None
    updated_utc: Optional[str] = None


@router.get("/status")
async def get_pilot_status_endpoint():
    """
    Get current pilot mode status and configuration.
    """
    return get_pilot_status()


@router.get("/daily-metrics")
async def get_pilot_daily_metrics(
    phase: str = Query(default=CURRENT_PILOT_PHASE, description="Pilot phase to query"),
    date: Optional[str] = Query(default=None, description="Specific date (YYYY-MM-DD) or None for all")
):
    """
    Get daily metrics for the shadow pilot.
    
    Includes:
    - Document counts per doc_type
    - Classification method breakdown (deterministic vs AI)
    - Stuck document counts (>24h in status)
    - Vendor extraction rates
    - Export rates
    """
    db = get_db()
    # Build date filter
    date_match = {}
    if date:
        date_start = f"{date}T00:00:00"
        date_end = f"{date}T23:59:59"
        date_match = {"pilot_date": {"$gte": date_start, "$lte": date_end}}
    
    # Base match for pilot documents
    base_match = {"pilot_phase": phase, **date_match}
    
    # Total counts by doc_type
    doc_type_pipeline = [
        {"$match": base_match},
        {"$group": {
            "_id": {"$ifNull": ["$doc_type", "OTHER"]},
            "count": {"$sum": 1}
        }}
    ]
    doc_type_results = await db.hub_documents.aggregate(doc_type_pipeline).to_list(20)
    by_doc_type = {r["_id"]: r["count"] for r in doc_type_results}
    
    # Classification method breakdown
    classification_pipeline = [
        {"$match": base_match},
        {"$group": {
            "_id": {"$ifNull": ["$classification_method", "unknown"]},
            "count": {"$sum": 1}
        }}
    ]
    classification_results = await db.hub_documents.aggregate(classification_pipeline).to_list(20)
    by_classification = {r["_id"]: r["count"] for r in classification_results}
    
    # Deterministic vs AI counts
    deterministic_count = sum(c for k, c in by_classification.items() if k.startswith("deterministic"))
    ai_count = sum(c for k, c in by_classification.items() if k.startswith("ai:"))
    other_count = sum(c for k, c in by_classification.items() if not k.startswith("deterministic") and not k.startswith("ai:"))
    
    # Stuck documents (>24h in status)
    now = datetime.now(timezone.utc)
    threshold_24h = (now - timedelta(hours=24)).isoformat()
    
    stuck_statuses = ["vendor_pending", "bc_validation_pending", "extracted", "validation_pending"]
    stuck_pipeline = [
        {"$match": {
            **base_match,
            "workflow_status": {"$in": stuck_statuses},
            "workflow_status_updated_utc": {"$lt": threshold_24h}
        }},
        {"$group": {
            "_id": "$workflow_status",
            "count": {"$sum": 1}
        }}
    ]
    stuck_results = await db.hub_documents.aggregate(stuck_pipeline).to_list(20)
    stuck_by_status = {r["_id"]: r["count"] for r in stuck_results}
    
    # Vendor extraction rate for AP_INVOICE
    ap_total_pipeline = [
        {"$match": {**base_match, "doc_type": "AP_INVOICE"}},
        {"$count": "total"}
    ]
    ap_total_result = await db.hub_documents.aggregate(ap_total_pipeline).to_list(1)
    ap_total = ap_total_result[0]["total"] if ap_total_result else 0
    
    ap_vendor_pipeline = [
        {"$match": {
            **base_match,
            "doc_type": "AP_INVOICE",
            "$or": [
                {"vendor_no": {"$exists": True, "$ne": None}},
                {"vendor_canonical": {"$exists": True, "$ne": None}}
            ]
        }},
        {"$count": "with_vendor"}
    ]
    ap_vendor_result = await db.hub_documents.aggregate(ap_vendor_pipeline).to_list(1)
    ap_with_vendor = ap_vendor_result[0]["with_vendor"] if ap_vendor_result else 0
    
    vendor_extraction_rate = (ap_with_vendor / ap_total * 100) if ap_total > 0 else 0
    
    # Export rate
    exported_pipeline = [
        {"$match": {**base_match, "workflow_status": "exported"}},
        {"$count": "exported"}
    ]
    exported_result = await db.hub_documents.aggregate(exported_pipeline).to_list(1)
    exported_count = exported_result[0]["exported"] if exported_result else 0
    
    total_docs = sum(by_doc_type.values())
    export_rate = (exported_count / total_docs * 100) if total_docs > 0 else 0
    
    # Documents missing required fields
    missing_fields_pipeline = [
        {"$match": {
            **base_match,
            "$or": [
                {"$and": [
                    {"doc_type": "AP_INVOICE"},
                    {"$or": [
                        {"vendor_name": {"$exists": False}},
                        {"vendor_name": None},
                        {"invoice_number_clean": {"$exists": False}},
                        {"invoice_number_clean": None}
                    ]}
                ]},
                {"$and": [
                    {"doc_type": "SALES_INVOICE"},
                    {"$or": [
                        {"customer_no": {"$exists": False}},
                        {"customer_no": None}
                    ]}
                ]}
            ]
        }},
        {"$group": {
            "_id": "$doc_type",
            "count": {"$sum": 1}
        }}
    ]
    missing_results = await db.hub_documents.aggregate(missing_fields_pipeline).to_list(20)
    missing_by_type = {r["_id"]: r["count"] for r in missing_results}
    
    return {
        "phase": phase,
        "date": date or "all",
        "query_timestamp": now.isoformat(),
        "summary": {
            "total_documents": total_docs,
            "deterministic_classified": deterministic_count,
            "ai_classified": ai_count,
            "other_classified": other_count,
            "ai_usage_rate": (ai_count / total_docs * 100) if total_docs > 0 else 0,
            "vendor_extraction_rate": vendor_extraction_rate,
            "export_rate": export_rate
        },
        "by_doc_type": by_doc_type,
        "by_classification_method": by_classification,
        "stuck_documents": {
            "total": sum(stuck_by_status.values()),
            "by_status": stuck_by_status
        },
        "missing_required_fields": missing_by_type,
        "exported_count": exported_count
    }


@router.get("/logs")
async def get_pilot_logs(
    phase: str = Query(default=CURRENT_PILOT_PHASE, description="Pilot phase to query"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    doc_type: Optional[str] = Query(default=None, description="Filter by doc_type"),
    classification_method: Optional[str] = Query(default=None, description="Filter by classification_method")
):
    """
    Get pilot ingestion logs for audit purposes.
    
    Returns documents ingested during the pilot with classification details.
    """
    # Build match
    match = {"pilot_phase": phase}
    if doc_type:
        match["doc_type"] = doc_type
    if classification_method:
        if classification_method == "deterministic":
            match["classification_method"] = {"$regex": "^deterministic"}
        elif classification_method == "ai":
            match["classification_method"] = {"$regex": "^ai:"}
        else:
            match["classification_method"] = classification_method
    
    # Count total
    total = await db.hub_documents.count_documents(match)
    
    # Fetch paginated results
    skip = (page - 1) * page_size
    cursor = db.hub_documents.find(
        match,
        {
            "_id": 0,
            "id": 1,
            "file_name": 1,
            "doc_type": 1,
            "source_system": 1,
            "capture_channel": 1,
            "classification_method": 1,
            "ai_classification": 1,
            "workflow_status": 1,
            "pilot_phase": 1,
            "pilot_date": 1,
            "created_utc": 1,
            "workflow_status_updated_utc": 1
        }
    ).sort("pilot_date", -1).skip(skip).limit(page_size)
    
    docs = await cursor.to_list(page_size)
    
    # Add computed fields
    for doc in docs:
        # Calculate time to status initialization
        if doc.get("pilot_date") and doc.get("workflow_status_updated_utc"):
            try:
                pilot_dt = datetime.fromisoformat(doc["pilot_date"].replace("Z", "+00:00"))
                status_dt = datetime.fromisoformat(doc["workflow_status_updated_utc"].replace("Z", "+00:00"))
                doc["time_to_status_initialization_ms"] = int((status_dt - pilot_dt).total_seconds() * 1000)
            except:
                doc["time_to_status_initialization_ms"] = None
    
    return {
        "phase": phase,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
        "logs": docs
    }


@router.get("/accuracy")
async def get_pilot_accuracy_report(
    phase: str = Query(default=CURRENT_PILOT_PHASE, description="Pilot phase to query")
):
    """
    Get pilot accuracy report.
    
    Includes:
    - Incorrect classifications (manually corrected)
    - Misrouted workflow statuses
    - Documents with missing required metadata
    - Time-in-status distribution
    """
    base_match = {"pilot_phase": phase}
    
    # Find manually corrected documents (where doc_type was changed after initial classification)
    # These would have multiple entries in workflow_history with different doc_types
    # For now, we look for documents with classification_override or manual_correction fields
    corrected_pipeline = [
        {"$match": {
            **base_match,
            "$or": [
                {"classification_override": {"$exists": True}},
                {"manual_doc_type_correction": {"$exists": True}}
            ]
        }},
        {"$project": {
            "_id": 0,
            "id": 1,
            "file_name": 1,
            "original_doc_type": "$ai_classification.suggested_type",
            "corrected_doc_type": "$doc_type",
            "correction_reason": "$classification_override_reason"
        }}
    ]
    corrected_docs = await db.hub_documents.aggregate(corrected_pipeline).to_list(100)
    
    # Time-in-status distribution
    now = datetime.now(timezone.utc)
    time_distribution_pipeline = [
        {"$match": base_match},
        {"$addFields": {
            "status_age_hours": {
                "$divide": [
                    {"$subtract": [now, {"$dateFromString": {"dateString": "$workflow_status_updated_utc"}}]},
                    3600000  # Convert ms to hours
                ]
            }
        }},
        {"$bucket": {
            "groupBy": "$status_age_hours",
            "boundaries": [0, 1, 4, 8, 24, 48, 168, 999999],
            "default": "unknown",
            "output": {
                "count": {"$sum": 1},
                "statuses": {"$push": "$workflow_status"}
            }
        }}
    ]
    
    try:
        time_distribution = await db.hub_documents.aggregate(time_distribution_pipeline).to_list(20)
    except Exception as e:
        logger.warning(f"Time distribution aggregation failed: {e}")
        time_distribution = []
    
    # Format time buckets
    time_buckets = {
        "0-1h": 0,
        "1-4h": 0,
        "4-8h": 0,
        "8-24h": 0,
        "24-48h": 0,
        "48h-1w": 0,
        ">1w": 0
    }
    
    bucket_labels = ["0-1h", "1-4h", "4-8h", "8-24h", "24-48h", "48h-1w", ">1w"]
    for i, bucket in enumerate(time_distribution):
        if i < len(bucket_labels):
            time_buckets[bucket_labels[i]] = bucket.get("count", 0)
    
    # Overall accuracy score (documents correctly classified on first pass)
    total_docs = await db.hub_documents.count_documents(base_match)
    corrected_count = len(corrected_docs)
    accuracy_score = ((total_docs - corrected_count) / total_docs * 100) if total_docs > 0 else 100
    
    return {
        "phase": phase,
        "report_timestamp": now.isoformat(),
        "accuracy_score": round(accuracy_score, 2),
        "total_documents": total_docs,
        "corrected_documents": corrected_count,
        "corrections": corrected_docs[:50],  # Limit to 50
        "time_in_status_distribution": time_buckets,
        "stall_warnings": {
            "description": "Documents in actionable status > 24 hours",
            "threshold_hours": 24
        }
    }


@router.get("/trend")
async def get_pilot_trend_data(
    phase: str = Query(default=CURRENT_PILOT_PHASE, description="Pilot phase to query"),
    days: int = Query(default=14, ge=1, le=30, description="Number of days to include")
):
    """
    Get daily trend data for pilot documents.
    
    Returns daily counts by doc_type for charting.
    """
    # Calculate date range
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    pipeline = [
        {"$match": {
            "pilot_phase": phase,
            "pilot_date": {"$gte": start_date.isoformat()}
        }},
        {"$addFields": {
            "date": {"$substr": ["$pilot_date", 0, 10]}
        }},
        {"$group": {
            "_id": {
                "date": "$date",
                "doc_type": {"$ifNull": ["$doc_type", "OTHER"]}
            },
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id.date": 1}}
    ]
    
    results = await db.hub_documents.aggregate(pipeline).to_list(500)
    
    # Organize by date
    trend_data = {}
    all_doc_types = set()
    
    for r in results:
        date = r["_id"]["date"]
        doc_type = r["_id"]["doc_type"]
        count = r["count"]
        
        if date not in trend_data:
            trend_data[date] = {}
        trend_data[date][doc_type] = count
        all_doc_types.add(doc_type)
    
    # Fill in missing dates and doc_types
    current = start_date
    while current <= end_date:
        date_str = current.strftime("%Y-%m-%d")
        if date_str not in trend_data:
            trend_data[date_str] = {}
        for dt in all_doc_types:
            if dt not in trend_data[date_str]:
                trend_data[date_str][dt] = 0
        current += timedelta(days=1)
    
    # Convert to array format for charting
    chart_data = []
    for date in sorted(trend_data.keys()):
        entry = {"date": date, **trend_data[date]}
        chart_data.append(entry)
    
    return {
        "phase": phase,
        "days": days,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "doc_types": sorted(list(all_doc_types)),
        "trend": chart_data
    }


@router.post("/send-daily-summary")
async def trigger_daily_pilot_summary():
    """
    Manually trigger the daily pilot summary email.
    
    Only allowed when pilot mode is enabled.
    
    Returns:
        Summary data and email send result
    """
    if not PILOT_MODE_ENABLED:
        raise HTTPException(
            status_code=400,
            detail="Pilot mode is disabled. Cannot send daily summary."
        )
    
    from services.email_service import get_email_service
    
    email_service = get_email_service()
    result = await send_daily_pilot_summary(db, email_service)
    
    return result


@router.get("/email-logs")
async def get_pilot_email_logs(
    limit: int = Query(default=20, ge=1, le=100),
    skip: int = Query(default=0, ge=0)
):
    """
    Get logs of sent pilot summary emails.
    
    Useful for verifying email content during the shadow pilot.
    """
    cursor = db.email_logs.find(
        {"subject": {"$regex": "Pilot Summary", "$options": "i"}},
        {"_id": 0}
    ).sort("sent_at", -1).skip(skip).limit(limit)
    
    logs = await cursor.to_list(limit)
    total = await db.email_logs.count_documents(
        {"subject": {"$regex": "Pilot Summary", "$options": "i"}}
    )
    
    return {
        "total": total,
        "logs": logs
    }


@router.get("/email-config")
async def get_pilot_email_config():
    """
    Get current pilot email configuration.
    """
    return {
        "daily_email_enabled": DAILY_PILOT_EMAIL_ENABLED,
        "recipients": PILOT_SUMMARY_RECIPIENTS,
        "cron_hour_utc": PILOT_SUMMARY_CRON_HOUR_UTC,
        "pilot_mode_enabled": PILOT_MODE_ENABLED,
        "current_phase": CURRENT_PILOT_PHASE
    }


# Daily pilot summary scheduler
async def _daily_pilot_summary_scheduler():
    """
    Background task that sends daily pilot summary emails.
    
    Runs continuously, checking every minute if it's time to send.
    Sends at PILOT_SUMMARY_CRON_HOUR_UTC (default: 13:00 UTC = 7 AM CST).
    """
    from services.email_service import get_email_service
    
    last_sent_date = None
    
    while True:
        try:
            now = datetime.now(timezone.utc)
            current_date = now.strftime("%Y-%m-%d")
            current_hour = now.hour
            
            # Check if it's time to send and we haven't sent today
            should_send = (
                PILOT_MODE_ENABLED and
                DAILY_PILOT_EMAIL_ENABLED and
                current_hour == PILOT_SUMMARY_CRON_HOUR_UTC and
                last_sent_date != current_date
            )
            
            if should_send:
                logger.info("Daily pilot summary cron triggered")
                email_service = get_email_service()
                result = await send_daily_pilot_summary(db, email_service)
                
                if result.get("sent"):
                    last_sent_date = current_date
                    logger.info(f"Daily pilot summary sent successfully: {result.get('message_id')}")
                else:
                    logger.warning(f"Daily pilot summary not sent: {result.get('reason')}")
            
            # Sleep for 60 seconds before checking again
            await asyncio.sleep(60)
            
        except asyncio.CancelledError:
            logger.info("Daily pilot summary scheduler cancelled")
            break
        except Exception as e:
            logger.error(f"Error in daily pilot summary scheduler: {e}")
            await asyncio.sleep(60)  # Wait before retrying


# ==================== WORKFLOW METRICS ====================

@router.get("/workflows/ap_invoice/metrics")
async def get_ap_workflow_metrics(days: int = Query(30)):
    db = get_db()
    """
    Get workflow metrics for AP_Invoice documents.
    Includes counts per status and time-in-status averages.
    """
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # Status counts
    status_pipeline = [
        {"$match": {"document_type": "AP_Invoice", "created_utc": {"$gte": cutoff_date}}},
        {"$group": {"_id": "$workflow_status", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}
    ]
    status_results = await db.hub_documents.aggregate(status_pipeline).to_list(100)
    status_counts = {r["_id"] or "none": r["count"] for r in status_results}
    
    # Daily workflow status changes
    daily_pipeline = [
        {"$match": {"document_type": "AP_Invoice", "created_utc": {"$gte": cutoff_date}}},
        {"$unwind": {"path": "$workflow_history", "preserveNullAndEmptyArrays": True}},
        {"$addFields": {
            "history_date": {"$substr": ["$workflow_history.timestamp", 0, 10]}
        }},
        {"$group": {
            "_id": {"date": "$history_date", "to_status": "$workflow_history.to_status"},
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id.date": -1}}
    ]
    daily_results = await db.hub_documents.aggregate(daily_pipeline).to_list(1000)
    
    # Group by date
    daily_by_date = {}
    for r in daily_results:
        date = r["_id"]["date"]
        status = r["_id"]["to_status"]
        if date and status:
            if date not in daily_by_date:
                daily_by_date[date] = {}
            daily_by_date[date][status] = r["count"]
    
    return {
        "period_days": days,
        "status_counts": status_counts,
        "total_documents": sum(status_counts.values()),
        "exception_queue_count": sum(
            status_counts.get(s, 0) for s in WorkflowEngine.get_exception_statuses()
        ),
        "daily_transitions": daily_by_date,
        "all_statuses": WorkflowEngine.get_all_statuses()
    }


# ==================== MAILBOX SOURCES CRUD ====================

@router.get("/settings/mailbox-sources")
async def list_mailbox_sources():
    db = get_db()
    """Get all configured mailbox sources."""
    sources = await db.mailbox_sources.find({}, {"_id": 0}).to_list(100)
    return {"mailbox_sources": sources, "total": len(sources)}

@router.get("/settings/mailbox-sources/polling-status")
async def get_mailbox_polling_status():
    db = get_db()
    """Get the status of the dynamic mailbox polling worker."""
    global _dynamic_mailbox_polling_task, _mailbox_last_poll_times
    
    worker_running = _dynamic_mailbox_polling_task is not None and not _dynamic_mailbox_polling_task.done()
    
    # Get all mailbox sources with their last poll times
    sources = await db.mailbox_sources.find({}, {"_id": 0}).to_list(100)
    
    mailbox_statuses = []
    for source in sources:
        mailbox_id = source.get("mailbox_id")
        last_poll = _mailbox_last_poll_times.get(mailbox_id)
        
        mailbox_statuses.append({
            "mailbox_id": mailbox_id,
            "name": source.get("name"),
            "email_address": source.get("email_address"),
            "enabled": source.get("enabled", True),
            "polling_interval_minutes": source.get("polling_interval_minutes", 5),
            "last_poll_utc": last_poll.isoformat() if last_poll else None,
            "next_poll_in_seconds": max(0, (source.get("polling_interval_minutes", 5) * 60) - 
                                        ((datetime.now(timezone.utc) - last_poll).total_seconds() if last_poll else 0))
                                   if last_poll else None
        })
    
    return {
        "worker_running": worker_running,
        "mailboxes": mailbox_statuses,
        "legacy_ap_polling_enabled": EMAIL_POLLING_ENABLED,
        "legacy_sales_polling_enabled": SALES_EMAIL_POLLING_ENABLED
    }

@router.get("/settings/mailbox-sources/{mailbox_id}")
async def get_mailbox_source(mailbox_id: str):
    db = get_db()
    """Get a specific mailbox source by ID."""
    source = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id}, {"_id": 0})
    if not source:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")
    return source

@router.post("/settings/mailbox-sources")
async def create_mailbox_source(source: MailboxSource):
    db = get_db()
    """Create a new mailbox source."""
    now = datetime.now(timezone.utc).isoformat()
    
    # Generate ID if not provided
    mailbox_id = source.mailbox_id or f"mailbox_{uuid.uuid4().hex[:8]}"
    
    # Check for duplicate email address
    existing = await db.mailbox_sources.find_one({"email_address": source.email_address})
    if existing:
        raise HTTPException(status_code=400, detail=f"Mailbox {source.email_address} already exists")
    
    doc = source.model_dump()
    doc["mailbox_id"] = mailbox_id
    doc["created_utc"] = now
    doc["updated_utc"] = now
    
    await db.mailbox_sources.insert_one(doc)
    
    logger.info("Created mailbox source: %s (%s)", source.name, source.email_address)
    
    # Return without _id
    return await get_mailbox_source(mailbox_id)

@router.put("/settings/mailbox-sources/{mailbox_id}")
async def update_mailbox_source(mailbox_id: str, source: MailboxSource):
    db = get_db()
    """Update an existing mailbox source."""
    existing = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")
    
    now = datetime.now(timezone.utc).isoformat()
    update_data = source.model_dump()
    update_data["mailbox_id"] = mailbox_id  # Preserve original ID
    update_data["created_utc"] = existing.get("created_utc")  # Preserve creation date
    update_data["updated_utc"] = now
    
    await db.mailbox_sources.update_one(
        {"mailbox_id": mailbox_id},
        {"$set": update_data}
    )
    
    logger.info("Updated mailbox source: %s", mailbox_id)
    
    return await get_mailbox_source(mailbox_id)

@router.delete("/settings/mailbox-sources/{mailbox_id}")
async def delete_mailbox_source(mailbox_id: str):
    db = get_db()
    """Delete a mailbox source."""
    existing = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")
    
    await db.mailbox_sources.delete_one({"mailbox_id": mailbox_id})
    
    logger.info("Deleted mailbox source: %s (%s)", existing.get("name"), existing.get("email_address"))
    
    return {"status": "deleted", "mailbox_id": mailbox_id}

@router.post("/settings/mailbox-sources/{mailbox_id}/test-connection")
async def test_mailbox_connection(mailbox_id: str):
    db = get_db()
    """Test connection to a mailbox source."""
    source = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id}, {"_id": 0})
    if not source:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")
    
    email_address = source.get("email_address")
    
    try:
        token = await get_email_token()
        if not token:
            return {"status": "error", "message": "Failed to get email token - check Graph API credentials"}
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Try to access the mailbox
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{email_address}/mailFolders/Inbox",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if resp.status_code == 200:
                folder_info = resp.json()
                return {
                    "status": "success",
                    "message": f"Connected successfully to {email_address}",
                    "folder_name": folder_info.get("displayName"),
                    "unread_count": folder_info.get("unreadItemCount"),
                    "total_count": folder_info.get("totalItemCount")
                }
            elif resp.status_code == 404:
                return {"status": "error", "message": f"Mailbox {email_address} not found or no access"}
            else:
                return {"status": "error", "message": f"Graph API error: {resp.status_code} - {resp.text[:200]}"}
    
    except Exception as e:
        return {"status": "error", "message": f"Connection test failed: {str(e)}"}

@router.post("/settings/mailbox-sources/{mailbox_id}/poll-now")
async def poll_mailbox_now(mailbox_id: str):
    db = get_db()
    """Manually trigger polling for a specific mailbox."""
    source = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id}, {"_id": 0})
    if not source:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")
    
    email_address = source.get("email_address")
    category = source.get("category", "AP")
    
    # Use the unified email polling function
    try:
        stats = await poll_mailbox_for_documents(
            mailbox_address=email_address,
            default_category=category,
            source_id=mailbox_id
        )
        return stats
    except Exception as e:
        logger.error("Manual poll failed for %s: %s", mailbox_id, str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def poll_mailbox_for_documents(mailbox_address: str, default_category: str = "AP", source_id: str = None):
    db = get_db()
    """
    Unified mailbox polling function that ingests documents into the main hub_documents collection.
    """
    run_id = uuid.uuid4().hex[:8]
    
    stats = {
        "run_id": run_id,
        "mailbox": mailbox_address,
        "source_id": source_id,
        "default_category": default_category,
        "messages_detected": 0,
        "attachments_ingested": 0,
        "attachments_skipped_dup": 0,
        "attachments_skipped_inline": 0,
        "attachments_failed": 0,
        "errors": [],
        "started_at": datetime.now(timezone.utc).isoformat()
    }
    
    logger.info("[MailboxPoll:%s] Starting poll for %s (category=%s)", run_id, mailbox_address, default_category)
    
    try:
        token = await get_email_token()
        if not token:
            stats["errors"].append("Failed to get email token")
            return stats
        
        # Look back 1 hour for new emails
        lookback_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            messages_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders/Inbox/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": f"receivedDateTime ge {lookback_time}",
                    "$select": "id,subject,from,receivedDateTime,internetMessageId,hasAttachments,bodyPreview",
                    "$top": 25,
                    "$orderby": "receivedDateTime asc"
                }
            )
            
            if messages_resp.status_code != 200:
                stats["errors"].append(f"Graph API error: {messages_resp.status_code}")
                return stats
            
            messages = messages_resp.json().get("value", [])
            stats["messages_detected"] = len([m for m in messages if m.get("hasAttachments")])
            
            for msg in messages:
                if not msg.get("hasAttachments"):
                    continue
                
                msg_id = msg.get("id")
                internet_msg_id = msg.get("internetMessageId", msg_id)
                subject = msg.get("subject", "No Subject")
                sender = msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")
                body_preview = msg.get("bodyPreview", "")
                
                # Get attachments
                att_resp = await client.get(
                    f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{msg_id}/attachments",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"$select": "id,name,contentType,size,isInline"}
                )
                
                if att_resp.status_code != 200:
                    continue
                
                attachments = att_resp.json().get("value", [])
                
                for att in attachments:
                    att_id = att.get("id")
                    filename = att.get("name", "unknown")
                    content_type = att.get("contentType", "")
                    is_inline = att.get("isInline", False)
                    size_bytes = att.get("size", 0)
                    
                    # Skip inline images and tiny files
                    if is_inline or content_type.startswith("image/") or size_bytes < 1000:
                        stats["attachments_skipped_inline"] += 1
                        continue
                    
                    # Check for duplicates
                    existing = await db.mail_intake_log.find_one({
                        "internet_message_id": internet_msg_id,
                        "attachment_name": filename
                    })
                    if existing:
                        stats["attachments_skipped_dup"] += 1
                        continue
                    
                    # Fetch attachment content
                    try:
                        att_content_resp = await client.get(
                            f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{msg_id}/attachments/{att_id}",
                            headers={"Authorization": f"Bearer {token}"}
                        )
                        
                        if att_content_resp.status_code != 200:
                            stats["attachments_failed"] += 1
                            continue
                        
                        content_b64 = att_content_resp.json().get("contentBytes", "")
                        content_bytes = base64.b64decode(content_b64)
                        content_hash = hashlib.sha256(content_bytes).hexdigest()
                        
                        # Ingest through unified pipeline
                        result = await _internal_intake_document(
                            file_content=content_bytes,
                            filename=filename,
                            source="email",
                            sender=sender,
                            subject=subject,
                            email_id=internet_msg_id,
                            content_type=content_type
                        )
                        
                        # Log the intake
                        await db.mail_intake_log.insert_one({
                            "internet_message_id": internet_msg_id,
                            "attachment_name": filename,
                            "attachment_hash": content_hash,
                            "document_id": result.get("document_id"),
                            "mailbox_source": mailbox_address,
                            "source_id": source_id,
                            "status": "Ingested",
                            "created_utc": datetime.now(timezone.utc).isoformat()
                        })
                        
                        stats["attachments_ingested"] += 1
                        
                    except Exception as e:
                        stats["attachments_failed"] += 1
                        stats["errors"].append(f"Failed to process {filename}: {str(e)}")
    
    except Exception as e:
        stats["errors"].append(f"Poll error: {str(e)}")
        logger.error("[MailboxPoll:%s] Error: %s", run_id, str(e))
    
    stats["completed_at"] = datetime.now(timezone.utc).isoformat()
    
    logger.info("[MailboxPoll:%s] Complete: ingested=%d, skipped_dup=%d, failed=%d",
                run_id, stats["attachments_ingested"], stats["attachments_skipped_dup"], stats["attachments_failed"])
    
    return stats


# ==================== VENDOR ALIAS ENGINE ====================

class VendorAlias(BaseModel):
    alias_string: str
    vendor_no: str
    vendor_name: Optional[str] = None
    confidence_override: Optional[float] = None  # If set, use this instead of calculated
    notes: Optional[str] = None

@router.get("/aliases/vendors")
async def get_vendor_aliases():
    db = get_db()
    """Get all vendor aliases."""
    aliases = await db.vendor_aliases.find({}, {"_id": 0}).to_list(500)
    return {"aliases": aliases, "count": len(aliases)}

@router.post("/aliases/vendors")
async def create_vendor_alias(alias: VendorAlias):
    db = get_db()
    """Create a new vendor alias mapping."""
    alias_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # Normalize the alias string for matching
    normalized = normalize_vendor_name(alias.alias_string)
    
    # Check for existing alias
    existing = await db.vendor_aliases.find_one({
        "$or": [
            {"alias_string": alias.alias_string},
            {"normalized_alias": normalized}
        ]
    })
    
    if existing:
        raise HTTPException(status_code=400, detail=f"Alias already exists for '{alias.alias_string}'")
    
    alias_doc = {
        "alias_id": alias_id,
        "alias_string": alias.alias_string,
        "normalized_alias": normalized,
        "vendor_no": alias.vendor_no,
        "vendor_name": alias.vendor_name,
        "confidence_override": alias.confidence_override,
        "notes": alias.notes,
        "created_by": "system",  # Could be user ID in future
        "created_at": now,
        "usage_count": 0,
        "last_used_at": None
    }
    
    await db.vendor_aliases.insert_one(alias_doc)
    
    # Update global alias map
    VENDOR_ALIAS_MAP[alias.alias_string] = alias.vendor_name or alias.vendor_no
    VENDOR_ALIAS_MAP[normalized] = alias.vendor_name or alias.vendor_no
    
    return {"alias_id": alias_id, "message": "Alias created successfully"}

@router.delete("/aliases/vendors/{alias_id}")
async def delete_vendor_alias(alias_id: str):
    db = get_db()
    """Delete a vendor alias."""
    result = await db.vendor_aliases.delete_one({"alias_id": alias_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Alias not found")
    return {"message": "Alias deleted"}

@router.get("/aliases/vendors/suggest")
async def suggest_alias_creation(vendor_name: str, resolved_vendor_no: str, resolved_vendor_name: str):
    db = get_db()
    """
    Called when user manually resolves a vendor match.
    Returns suggestion to save as alias.
    """
    normalized = normalize_vendor_name(vendor_name)
    
    # Check if alias already exists
    existing = await db.vendor_aliases.find_one({
        "$or": [
            {"alias_string": vendor_name},
            {"normalized_alias": normalized}
        ]
    }, {"_id": 0})
    
    if existing:
        return {
            "suggest_alias": False,
            "reason": "Alias already exists",
            "existing_alias": existing
        }
    
    return {
        "suggest_alias": True,
        "suggested_alias": {
            "alias_string": vendor_name,
            "normalized_alias": normalized,
            "vendor_no": resolved_vendor_no,
            "vendor_name": resolved_vendor_name
        },
        "message": f"Would you like to save '{vendor_name}' as an alias for '{resolved_vendor_name}'?"
    }

# Update resolve endpoint to increment alias usage
async def record_alias_usage(alias_string: str):
    db = get_db()
    """Record when an alias is used for matching."""
    await db.vendor_aliases.update_one(
        {"alias_string": alias_string},
        {
            "$inc": {"usage_count": 1},
            "$set": {"last_used_at": datetime.now(timezone.utc).isoformat()}
        }
    )

# ==================== AUTOMATION METRICS ENGINE ====================

# ==================== BC SIMULATION API (Phase 2 Shadow Pilot) ====================

from services.bc_simulation_service import (
    simulate_export_ap_invoice, simulate_create_purchase_invoice,
    simulate_attach_pdf, simulate_sales_invoice_export, simulate_po_linkage,
    run_full_export_simulation, calculate_simulation_summary,
    get_simulation_service_status, SimulationResult, SimulationType, SimulationStatus
)
from workflows.core.engine import SimulationHistoryEntry


@router.get("/simulation/status")
async def get_pilot_simulation_status():
    """Get BC simulation service status."""
    return get_simulation_service_status()


@router.post("/simulation/document/{doc_id}/run")
async def run_simulation_for_document(doc_id: str):
    db = get_db()
    """
    Run full BC export simulation for a document.
    
    This simulates all applicable BC operations based on doc_type
    and stores results in workflow history and simulation_results collection.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Run full simulation - use 'id' as 'document_id' for simulation
    doc_for_sim = {**doc, "document_id": doc_id}
    simulation_results = run_full_export_simulation(doc_for_sim)
    
    # Convert SimulationResult objects to clean dicts
    # Use JSON round-trip to ensure 100% serializable output
    import json as json_lib
    results_dict = {}
    for sim_key, sim_result in simulation_results.items():
        result_dict = sim_result.to_dict()
        # JSON round-trip to ensure clean dict
        clean_result = json_lib.loads(json_lib.dumps(result_dict))
        results_dict[sim_key] = clean_result
    
    # Create workflow history entry (also JSON-clean)
    history_entry_raw = SimulationHistoryEntry.create_batch_simulation_entry(
        document_id=doc_id,
        simulation_results=results_dict
    )
    history_entry = json_lib.loads(json_lib.dumps(history_entry_raw))
    
    # Store simulation results in dedicated collection
    for sim_type, result in results_dict.items():
        db_copy = json_lib.loads(json_lib.dumps(result))
        db_copy["_collection_timestamp"] = datetime.now(timezone.utc).isoformat()
        await db.pilot_simulation_results.insert_one(db_copy)
    
    # Update document with simulation results and history
    results_for_db = json_lib.loads(json_lib.dumps(results_dict))
    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$push": {"workflow_history": history_entry},
            "$set": {
                "last_simulation_results": results_for_db,
                "last_simulation_timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
    )
    
    # Calculate summary
    would_succeed = all(r.get("would_succeed_in_production") for r in results_dict.values())
    
    # Return clean dict (another JSON round-trip for safety)
    response_results = json_lib.loads(json_lib.dumps(results_dict))
    
    return {
        "document_id": doc_id,
        "doc_type": doc.get("doc_type"),
        "simulations_run": len(response_results),
        "all_would_succeed": would_succeed,
        "results": response_results,
        "history_entry_added": True
    }


@router.post("/simulation/ap-invoice/{doc_id}")
async def simulate_ap_invoice_export(doc_id: str):
    db = get_db()
    """Simulate AP invoice export to BC."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if doc.get("doc_type") != "AP_INVOICE":
        raise HTTPException(status_code=400, detail=f"Document is {doc.get('doc_type')}, not AP_INVOICE")
    
    doc_for_sim = {**doc, "document_id": doc_id}
    result = simulate_export_ap_invoice(doc_for_sim)
    result_dict = result.to_dict()
    
    # Store result (deep copy to avoid _id mutation)
    result_copy = copy.deepcopy(result_dict)
    result_copy["_collection_timestamp"] = datetime.now(timezone.utc).isoformat()
    await db.pilot_simulation_results.insert_one(result_copy)
    
    # Add to workflow history
    history_entry = SimulationHistoryEntry.create_simulation_entry(result_dict)
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$push": {"workflow_history": history_entry}}
    )
    
    return result_dict


@router.post("/simulation/sales-invoice/{doc_id}")
async def simulate_sales_invoice_export_endpoint(doc_id: str):
    db = get_db()
    """Simulate sales invoice export to BC."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if doc.get("doc_type") != "SALES_INVOICE":
        raise HTTPException(status_code=400, detail=f"Document is {doc.get('doc_type')}, not SALES_INVOICE")
    
    doc_for_sim = {**doc, "document_id": doc_id}
    result = simulate_sales_invoice_export(doc_for_sim)
    result_dict = result.to_dict()
    
    # Store result (deep copy to avoid _id mutation)
    result_copy = copy.deepcopy(result_dict)
    result_copy["_collection_timestamp"] = datetime.now(timezone.utc).isoformat()
    await db.pilot_simulation_results.insert_one(result_copy)
    
    # Add to workflow history
    history_entry = SimulationHistoryEntry.create_simulation_entry(result_dict)
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$push": {"workflow_history": history_entry}}
    )
    
    return result_dict


@router.post("/simulation/po-linkage/{doc_id}")
async def simulate_po_linkage_endpoint(doc_id: str):
    db = get_db()
    """Simulate PO linkage in BC."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc_for_sim = {**doc, "document_id": doc_id}
    result = simulate_po_linkage(doc_for_sim)
    result_dict = result.to_dict()
    
    # Store result (deep copy to avoid _id mutation)
    result_copy = copy.deepcopy(result_dict)
    result_copy["_collection_timestamp"] = datetime.now(timezone.utc).isoformat()
    await db.pilot_simulation_results.insert_one(result_copy)
    
    # Add to workflow history
    history_entry = SimulationHistoryEntry.create_simulation_entry(result_dict)
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$push": {"workflow_history": history_entry}}
    )
    
    return result_dict


@router.post("/simulation/attachment/{doc_id}")
async def simulate_attachment_endpoint(doc_id: str):
    db = get_db()
    """Simulate PDF attachment to BC record."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc_for_sim = {**doc, "document_id": doc_id}
    result = simulate_attach_pdf(doc_for_sim)
    result_dict = result.to_dict()
    
    # Store result (deep copy to avoid _id mutation)
    result_copy = copy.deepcopy(result_dict)
    result_copy["_collection_timestamp"] = datetime.now(timezone.utc).isoformat()
    await db.pilot_simulation_results.insert_one(result_copy)
    
    # Add to workflow history
    history_entry = SimulationHistoryEntry.create_simulation_entry(result_dict)
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$push": {"workflow_history": history_entry}}
    )
    
    return result_dict


@router.get("/simulation-results")
async def get_simulation_results(
    doc_type: str = Query(None),
    simulation_type: str = Query(None),
    would_succeed: bool = Query(None),
    limit: int = Query(100, le=500),
    skip: int = Query(0)
):
    """
    Get simulation results from the pilot.
    
    Filter by doc_type, simulation_type, or success status.
    """
    query = {}
    
    if doc_type:
        # Get document IDs for this doc_type
        doc_ids = await db.hub_documents.distinct("document_id", {"doc_type": doc_type})
        query["document_id"] = {"$in": doc_ids}
    
    if simulation_type:
        query["simulation_type"] = simulation_type
    
    if would_succeed is not None:
        query["would_succeed_in_production"] = would_succeed
    
    cursor = db.pilot_simulation_results.find(query, {"_id": 0}).sort("timestamp", -1).skip(skip).limit(limit)
    results = await cursor.to_list(limit)
    
    total = await db.pilot_simulation_results.count_documents(query)
    
    return {
        "results": results,
        "total": total,
        "limit": limit,
        "skip": skip,
        "filters": {
            "doc_type": doc_type,
            "simulation_type": simulation_type,
            "would_succeed": would_succeed
        }
    }


@router.get("/simulation-summary")
async def get_simulation_summary(
    doc_type: str = Query(None),
    days: int = Query(14, ge=1, le=90)
):
    """
    Get summary statistics for simulation results.
    
    Shows success rates, failure reasons, and breakdown by type.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    query = {"timestamp": {"$gte": cutoff.isoformat()}}
    
    if doc_type:
        doc_ids = await db.hub_documents.distinct("document_id", {"doc_type": doc_type})
        query["document_id"] = {"$in": doc_ids}
    
    # Get all results for the period
    cursor = db.pilot_simulation_results.find(query, {"_id": 0})
    results = await cursor.to_list(10000)
    
    # Calculate summary
    summary = calculate_simulation_summary(results)
    
    # Add time range info
    summary["period_days"] = days
    summary["cutoff_date"] = cutoff.isoformat()
    summary["doc_type_filter"] = doc_type
    
    # Get unique documents simulated
    unique_docs = set(r.get("document_id") for r in results)
    summary["unique_documents_simulated"] = len(unique_docs)
    
    return summary


@router.post("/simulation/batch")
async def run_batch_simulation(
    doc_type: str = Query(...),
    status: str = Query(None),
    limit: int = Query(50, le=200)
):
    """
    Run simulation for a batch of documents.
    
    Useful for running simulations on all documents of a type.
    """
    query = {"doc_type": doc_type}
    if status:
        query["workflow_status"] = status
    
    # Get documents
    cursor = db.hub_documents.find(query, {"_id": 0}).limit(limit)
    docs = await cursor.to_list(limit)
    
    results = []
    for doc in docs:
        doc_id = doc.get("id")
        try:
            doc_for_sim = {**doc, "document_id": doc_id}
            simulation_results = run_full_export_simulation(doc_for_sim)
            results_dict = {k: v.to_dict() for k, v in simulation_results.items()}
            
            # Store results (deep copy to avoid _id mutation)
            for sim_type, result in results_dict.items():
                result_copy = copy.deepcopy(result)
                result_copy["_collection_timestamp"] = datetime.now(timezone.utc).isoformat()
                await db.pilot_simulation_results.insert_one(result_copy)
            
            # Update document
            history_entry = SimulationHistoryEntry.create_batch_simulation_entry(
                document_id=doc_id,
                simulation_results=results_dict
            )
            await db.hub_documents.update_one(
                {"id": doc_id},
                {
                    "$push": {"workflow_history": history_entry},
                    "$set": {
                        "last_simulation_results": results_dict,
                        "last_simulation_timestamp": datetime.now(timezone.utc).isoformat()
                    }
                }
            )
            
            would_succeed = all(r.get("would_succeed_in_production") for r in results_dict.values())
            results.append({
                "document_id": doc_id,
                "simulations_run": len(results_dict),
                "all_would_succeed": would_succeed
            })
        except Exception as e:
            results.append({
                "document_id": doc_id,
                "error": str(e)
            })
    
    succeeded = sum(1 for r in results if r.get("all_would_succeed"))
    
    return {
        "doc_type": doc_type,
        "documents_processed": len(results),
        "all_would_succeed": succeeded,
        "would_have_failures": len(results) - succeeded,
        "results": results
    }


# ==================== SIMULATION METRICS API ====================

from services.simulation_metrics_service import (
    SimulationMetricsService, 
    normalize_failure_reason,
    FailureReasonCode
)

# Create singleton metrics service
_simulation_metrics_service = None

def get_simulation_metrics_service():
    global _simulation_metrics_service
    if _simulation_metrics_service is None:
        _simulation_metrics_service = SimulationMetricsService(db)
    return _simulation_metrics_service


@router.get("/simulation/metrics")
async def get_simulation_metrics(
    days: int = Query(14, ge=1, le=90),
    doc_type: str = Query(None),
    source_system: str = Query(None)
):
    """
    Get global simulation metrics summary.
    
    Returns success/failure counts grouped by doc_type, failure_reason,
    source_system, and workflow_status.
    """
    service = get_simulation_metrics_service()
    metrics = await service.get_global_metrics(
        days=days,
        doc_type_filter=doc_type,
        source_system_filter=source_system
    )
    return metrics


@router.get("/simulation/metrics/failures")
async def get_simulation_failure_details(
    failure_reason: str = Query(None, description="Normalized failure reason code"),
    doc_type: str = Query(None),
    limit: int = Query(50, le=200)
):
    """
    Get detailed list of failed simulations.
    
    Filter by failure_reason code (e.g., VENDOR_NOT_FOUND, MISSING_REQUIRED_FIELDS).
    """
    service = get_simulation_metrics_service()
    return await service.get_failure_details(
        failure_reason=failure_reason,
        doc_type=doc_type,
        limit=limit
    )


@router.get("/simulation/metrics/successes")
async def get_simulation_success_details(
    doc_type: str = Query(None),
    limit: int = Query(50, le=200)
):
    """
    Get detailed list of successful simulations.
    """
    service = get_simulation_metrics_service()
    return await service.get_success_details(doc_type=doc_type, limit=limit)


@router.get("/simulation/metrics/trend")
async def get_simulation_trend(
    days: int = Query(14, ge=1, le=90),
    granularity: str = Query("day", regex="^(day|hour)$")
):
    """
    Get simulation trend data over time for charting.
    """
    service = get_simulation_metrics_service()
    return await service.get_trend_data(days=days, granularity=granularity)


@router.get("/simulation/metrics/pending")
async def get_documents_pending_simulation(
    doc_type: str = Query(None),
    workflow_status: str = Query(None),
    limit: int = Query(100, le=500)
):
    """
    Get documents that haven't been simulated yet.
    """
    service = get_simulation_metrics_service()
    return await service.get_documents_needing_simulation(
        doc_type=doc_type,
        workflow_status=workflow_status,
        limit=limit
    )


@router.get("/simulation/failure-reasons")
async def get_failure_reason_codes():
    """
    Get list of all normalized failure reason codes.
    """
    return {
        "failure_reason_codes": [
            {"code": e.value, "description": e.value.replace("_", " ").title()}
            for e in FailureReasonCode
        ]
    }


# ==================== BATCH RE-INGEST API ====================

# Global state for tracking re-ingest progress
_reingest_state = {
    "running": False,
    "total": 0,
    "processed": 0,
    "current_batch": 0,
    "total_batches": 0,
    "successes": 0,
    "failures": 0,
    "errors": [],
    "started_at": None,
    "completed_at": None
}


@router.get("/reingest/status")
async def get_reingest_status():
    """Get current re-ingest job status."""
    return _reingest_state


@router.post("/reingest/start")
async def start_batch_reingest(
    background_tasks: BackgroundTasks,
    batch_size: int = Query(50, ge=10, le=100),
    doc_type_filter: str = Query(None, description="Optional: only re-ingest specific doc_type")
):
    """
    Start batch re-ingest of all documents.
    
    This will:
    1. Reset workflow_status to initial state
    2. Re-run document classification
    3. Run workflow engine
    4. Run BC simulations
    
    Processes in batches to avoid timeout.
    """
    global _reingest_state
    
    if _reingest_state["running"]:
        raise HTTPException(status_code=409, detail="Re-ingest already in progress")
    
    # Count documents to process
    query = {}
    if doc_type_filter:
        query["doc_type"] = doc_type_filter
    
    total_docs = await db.hub_documents.count_documents(query)
    
    if total_docs == 0:
        return {"message": "No documents to re-ingest", "total": 0}
    
    # Initialize state
    _reingest_state = {
        "running": True,
        "total": total_docs,
        "processed": 0,
        "current_batch": 0,
        "total_batches": (total_docs + batch_size - 1) // batch_size,
        "successes": 0,
        "failures": 0,
        "errors": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "batch_size": batch_size,
        "doc_type_filter": doc_type_filter
    }
    
    # Start background task
    background_tasks.add_task(
        run_batch_reingest,
        batch_size=batch_size,
        doc_type_filter=doc_type_filter
    )
    
    return {
        "message": "Re-ingest started",
        "total_documents": total_docs,
        "batch_size": batch_size,
        "total_batches": _reingest_state["total_batches"],
        "status_endpoint": "/api/pilot/reingest/status"
    }


async def run_batch_reingest(batch_size: int, doc_type_filter: str = None):
    db = get_db()
    """Background task to run batch re-ingest."""
    global _reingest_state
    
    try:
        query = {}
        if doc_type_filter:
            query["doc_type"] = doc_type_filter
        
        # Get all document IDs
        cursor = db.hub_documents.find(query, {"_id": 0, "id": 1})
        all_docs = await cursor.to_list(10000)
        doc_ids = [d["id"] for d in all_docs]
        
        # Process in batches
        for batch_num in range(0, len(doc_ids), batch_size):
            batch_ids = doc_ids[batch_num:batch_num + batch_size]
            _reingest_state["current_batch"] = (batch_num // batch_size) + 1
            
            for doc_id in batch_ids:
                try:
                    await reingest_single_document(doc_id)
                    _reingest_state["successes"] += 1
                except Exception as e:
                    _reingest_state["failures"] += 1
                    if len(_reingest_state["errors"]) < 20:  # Keep max 20 errors
                        _reingest_state["errors"].append({
                            "document_id": doc_id,
                            "error": str(e)
                        })
                
                _reingest_state["processed"] += 1
            
            # Small delay between batches to prevent overload
            await asyncio.sleep(0.5)
        
        _reingest_state["completed_at"] = datetime.now(timezone.utc).isoformat()
        _reingest_state["running"] = False
        
    except Exception as e:
        _reingest_state["running"] = False
        _reingest_state["errors"].append({"global_error": str(e)})
        _reingest_state["completed_at"] = datetime.now(timezone.utc).isoformat()


async def reingest_single_document(doc_id: str):
    db = get_db()
    """
    Re-ingest a single document:
    1. Reset workflow status
    2. Re-classify
    3. Run workflow
    4. Run simulation
    """
    # Get document
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise ValueError(f"Document {doc_id} not found")
    
    # Import classification and workflow functions
    from workflows.core.engine import DocType, WorkflowStatus
    from services.bc_simulation_service import run_full_export_simulation
    
    # Step 1: Determine doc_type from existing data or re-classify
    doc_type = doc.get("doc_type", "OTHER")
    
    # If doc_type is missing or OTHER, try to classify based on content
    if doc_type in [None, "OTHER", ""]:
        # Simple rule-based classification based on existing fields
        if doc.get("vendor_canonical") or doc.get("vendor_raw"):
            if doc.get("po_number"):
                doc_type = "PURCHASE_ORDER"
            else:
                doc_type = "AP_INVOICE"
        elif doc.get("customer_number"):
            doc_type = "SALES_INVOICE"
        else:
            doc_type = "OTHER"
    
    # Step 2: Initial workflow status is always "captured"
    initial_status = WorkflowStatus.CAPTURED.value
    
    # Step 3: Create reset workflow history entry
    reset_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "workflow_reset",
        "actor": "batch_reingest",
        "from_status": doc.get("workflow_status"),
        "to_status": initial_status,
        "note": "Document re-ingested during batch reset"
    }
    
    # Step 4: Run simulation
    doc_for_sim = {**doc, "document_id": doc_id, "doc_type": doc_type}
    simulation_results = run_full_export_simulation(doc_for_sim)
    
    # Convert simulation results to dicts
    import json as json_lib
    results_dict = {}
    for sim_key, sim_result in simulation_results.items():
        result_dict = sim_result.to_dict()
        clean_result = json_lib.loads(json_lib.dumps(result_dict))
        results_dict[sim_key] = clean_result
    
    # Store simulation results
    for sim_type, result in results_dict.items():
        result_copy = json_lib.loads(json_lib.dumps(result))
        result_copy["_collection_timestamp"] = datetime.now(timezone.utc).isoformat()
        result_copy["_reingest_batch"] = True
        await db.pilot_simulation_results.insert_one(result_copy)
    
    # Step 5: Create simulation history entry
    from workflows.core.engine import SimulationHistoryEntry
    sim_history_entry = SimulationHistoryEntry.create_batch_simulation_entry(
        document_id=doc_id,
        simulation_results=results_dict
    )
    
    # Step 6: Determine workflow status based on simulation results
    all_would_succeed = all(r.get("would_succeed_in_production") for r in results_dict.values())
    
    # Set workflow status based on doc_type and simulation result
    if doc_type == "AP_INVOICE":
        if all_would_succeed:
            new_status = WorkflowStatus.READY_FOR_APPROVAL.value
        else:
            new_status = WorkflowStatus.DATA_CORRECTION_PENDING.value
    elif doc_type == "SALES_INVOICE":
        if all_would_succeed:
            new_status = "validated"
        else:
            new_status = "validation_failed"
    elif doc_type == "PURCHASE_ORDER":
        if all_would_succeed:
            new_status = "matched"
        else:
            new_status = "unmatched"
    else:
        new_status = initial_status
    
    # Step 7: Update document
    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "doc_type": doc_type,
                "workflow_status": new_status,
                "last_simulation_results": results_dict,
                "last_simulation_timestamp": datetime.now(timezone.utc).isoformat(),
                "reingest_timestamp": datetime.now(timezone.utc).isoformat(),
                "pilot_phase": "shadow_pilot_v1",
                "pilot_date": datetime.now(timezone.utc).isoformat()
            },
            "$push": {
                "workflow_history": {
                    "$each": [reset_entry, sim_history_entry]
                }
            }
        }
    )


@router.post("/reingest/stop")
async def stop_reingest():
    """Stop the running re-ingest job."""
    global _reingest_state
    
    if not _reingest_state["running"]:
        return {"message": "No re-ingest job running"}
    
    _reingest_state["running"] = False
    _reingest_state["completed_at"] = datetime.now(timezone.utc).isoformat()
    
    return {
        "message": "Re-ingest stopped",
        "processed": _reingest_state["processed"],
        "total": _reingest_state["total"]
    }


# ==================== FILE INGESTION API ====================
