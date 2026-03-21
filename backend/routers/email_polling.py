"""GPI Document Hub - Email Polling & Graph Webhook Router"""

import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Body, Query, Request, BackgroundTasks
from deps import (
    get_db,
    EMAIL_POLLING_ENABLED,
    EMAIL_POLLING_INTERVAL_MINUTES,
    EMAIL_POLLING_USER,
    EMAIL_POLLING_LOOKBACK_MINUTES,
    EMAIL_POLLING_MAX_MESSAGES,
    EMAIL_POLLING_MAX_ATTACHMENT_MB,
    EMAIL_CLIENT_ID,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Email Polling"])


@router.post("/email-polling/trigger")
async def trigger_email_poll():
    """
    Manually trigger an email poll run (for testing).
    Returns the poll run statistics.
    """
    if not EMAIL_POLLING_ENABLED:
        return {"error": "EMAIL_POLLING_ENABLED is false. Set to true to enable polling."}
    
    from server import poll_mailbox_for_attachments
    stats = await poll_mailbox_for_attachments()
    return stats



@router.get("/email-polling/status")
async def get_email_polling_status():
    db = get_db()
    """Get current email polling configuration and recent run stats."""
    # Get last 24 hours of runs
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent_runs = await db.mail_poll_runs.find(
        {"started_at": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("started_at", -1).limit(10).to_list(10)
    
    # Aggregate stats for last 24h (use new field names, fallback to old for compatibility)
    total_detected = sum(r.get("messages_detected", r.get("messages_scanned", 0)) for r in recent_runs)
    total_ingested = sum(r.get("attachments_ingested", r.get("attachments_processed", 0)) for r in recent_runs)
    total_skipped_dup = sum(r.get("attachments_skipped_duplicate", 0) for r in recent_runs)
    total_skipped_inline = sum(r.get("attachments_skipped_inline", 0) for r in recent_runs)
    total_failed = sum(r.get("attachments_failed", 0) for r in recent_runs)
    
    # Get watermark
    watermark_doc = await db.hub_settings.find_one({"type": "email_poll_watermark"}, {"_id": 0})
    watermark = watermark_doc.get("last_received_datetime") if watermark_doc else None
    
    return {
        "config": {
            "enabled": EMAIL_POLLING_ENABLED,
            "mode": "passive_tap",  # Read-only, no mailbox mutations
            "interval_minutes": EMAIL_POLLING_INTERVAL_MINUTES,
            "user": EMAIL_POLLING_USER or "(not configured)",
            "lookback_minutes": EMAIL_POLLING_LOOKBACK_MINUTES,
            "max_messages_per_run": EMAIL_POLLING_MAX_MESSAGES,
            "max_attachment_mb": EMAIL_POLLING_MAX_ATTACHMENT_MB,
            "email_app_configured": bool(EMAIL_CLIENT_ID)
        },
        "last_24h": {
            "runs_count": len(recent_runs),
            "messages_detected": total_detected,
            "attachments_ingested": total_ingested,
            "attachments_skipped_duplicate": total_skipped_dup,
            "attachments_skipped_inline": total_skipped_inline,
            "attachments_failed": total_failed
        },
        "watermark": watermark,
        "recent_runs": recent_runs[:5],
        "health": "healthy" if total_failed == 0 else ("degraded" if total_failed < total_ingested else "unhealthy"),
        "permissions_required": "Mail.Read (application, read-only)"
    }



@router.get("/email-polling/logs")
async def get_mail_intake_logs(days: int = Query(1), status: str = Query(None), limit: int = Query(100)):
    db = get_db()
    """Get mail intake logs for debugging."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = {"processed_at": {"$gte": cutoff}}
    if status:
        query["status"] = status
    
    logs = await db.mail_intake_log.find(
        query, {"_id": 0}
    ).sort("processed_at", -1).limit(limit).to_list(limit)
    
    return {"logs": logs, "count": len(logs)}



@router.post("/graph/webhook")
async def graph_webhook(request_data: dict = None):
    """
    Microsoft Graph webhook endpoint for email notifications.
    Handles both validation and notification requests.
    """
    # Handle validation request (Graph sends this when creating subscription)
    if request_data and "validationToken" in request_data:
        return request_data["validationToken"]
    
    # Handle notification
    if request_data and "value" in request_data:
        for notification in request_data.get("value", []):
            # Verify client state
            if notification.get("clientState") != "gpi-document-hub-secret":
                logger.warning("Invalid client state in webhook notification")
                continue
            
            resource = notification.get("resource", "")
            change_type = notification.get("changeType", "")
            
            if change_type == "created" and "/messages/" in resource:
                # Extract email ID and mailbox from resource
                # Resource format: users/{mailbox}/mailFolders/Inbox/messages/{emailId}
                parts = resource.split("/")
                if len(parts) >= 6:
                    mailbox = parts[1]
                    email_id = parts[-1]
                    
                    # Queue for processing (in production, use a proper queue)
                    logger.info("New email notification: mailbox=%s, email_id=%s", mailbox, email_id)
                    
                    # Process the email
                    await process_incoming_email(email_id, mailbox)
    
    return {"status": "ok"}


@router.get("/graph/webhook")
async def graph_webhook_validation(validationToken: str = Query(None)):
    """Handle Graph subscription validation (GET request)."""
    if validationToken:
        from starlette.responses import PlainTextResponse
        return PlainTextResponse(content=validationToken)
    return {"status": "ready"}


