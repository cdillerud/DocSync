"""
Graph webhook + email polling HTTP endpoints.

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 10). No logic changed. The actual
processing logic (process_incoming_email, poll_mailbox_for_attachments,
backfill logic) lives in services/email_polling_engine.py; this module is
the thin HTTP layer over it.
"""
from datetime import datetime, timezone, timedelta
import uuid
import base64
import hashlib
import logging
import httpx
from fastapi import APIRouter, Query
from starlette.responses import PlainTextResponse

from core.db import db
from core.config import (
    EMAIL_POLLING_ENABLED, EMAIL_POLLING_INTERVAL_MINUTES, EMAIL_POLLING_USER,
    EMAIL_POLLING_LOOKBACK_MINUTES, EMAIL_POLLING_MAX_MESSAGES,
    EMAIL_POLLING_MAX_ATTACHMENT_MB, EMAIL_CLIENT_ID,
)
from core.legacy_hub_helpers import get_email_token
from services.ingestion_engine import _internal_intake_document
from services.email_polling_engine import (
    process_incoming_email, poll_mailbox_for_attachments,
)

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

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


@router.post("/email-polling/trigger")
async def trigger_email_poll():
    """
    Manually trigger an email poll run (for testing).
    Returns the poll run statistics.
    """
    if not EMAIL_POLLING_ENABLED:
        return {"error": "EMAIL_POLLING_ENABLED is false. Set to true to enable polling."}
    
    stats = await poll_mailbox_for_attachments()
    return stats


@router.get("/email-polling/status")
async def get_email_polling_status():
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
    """Get mail intake logs for debugging."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = {"processed_at": {"$gte": cutoff}}
    if status:
        query["status"] = status
    
    logs = await db.mail_intake_log.find(
        query, {"_id": 0}
    ).sort("processed_at", -1).limit(limit).to_list(limit)
    
    return {"logs": logs, "count": len(logs)}


@router.post("/admin/backfill-ap-mailbox")
async def backfill_ap_mailbox(
    days_back: int = Query(7, description="How many days back to search"),
    max_messages: int = Query(25, description="Maximum messages to process"),
    dry_run: bool = Query(False, description="If true, only report what would be processed"),
    mailbox: str = Query(None, description="Mailbox to poll (defaults to EMAIL_POLLING_USER)")
):
    """
    One-time backfill of existing AP mailbox emails into the Document Hub.
    
    SAFE DESIGN:
    - Read-only Graph access
    - Does NOT mark messages as read
    - Does NOT move or delete messages
    - Uses idempotency (internetMessageId + attachment hash) to prevent duplicates
    - Only processes PDF attachments, skips inline images
    
    Use this to seed Shadow Mode with real production data.
    """
    run_id = uuid.uuid4().hex[:8]
    
    stats = {
        "run_id": run_id,
        "dry_run": dry_run,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "days_back": days_back,
        "max_messages": max_messages,
        "messages_found": 0,
        "messages_with_attachments": 0,
        "attachments_found": 0,
        "attachments_ingested": 0,
        "attachments_skipped_duplicate": 0,
        "attachments_skipped_inline": 0,
        "attachments_skipped_non_pdf": 0,
        "errors": [],
        "ingested_documents": []
    }
    
    logger.info("[Backfill:%s] Starting AP mailbox backfill (days=%d, max=%d, dry_run=%s)", 
                run_id, days_back, max_messages, dry_run)
    
    # Use specified mailbox or default to EMAIL_POLLING_USER
    target_mailbox = mailbox or EMAIL_POLLING_USER
    stats["mailbox"] = target_mailbox
    
    try:
        # Get email token (uses EMAIL_CLIENT_ID/SECRET)
        token = await get_email_token()
        if not token:
            stats["errors"].append("Failed to get email token")
            return stats
        
        # Calculate date range
        start_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
        
        # Query messages with attachments in date range
        filter_query = f"receivedDateTime ge {start_date}"
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            messages_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{target_mailbox}/mailFolders/Inbox/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": filter_query,
                    "$select": "id,subject,from,receivedDateTime,internetMessageId,hasAttachments",
                    "$top": max_messages,
                    "$orderby": "receivedDateTime desc"
                }
            )
            
            if messages_resp.status_code != 200:
                error_msg = f"Graph API error {messages_resp.status_code}: {messages_resp.text[:200]}"
                stats["errors"].append(error_msg)
                return stats
            
            messages = messages_resp.json().get("value", [])
            stats["messages_found"] = len(messages)
            
            # Filter to only messages with attachments
            messages_with_attachments = [m for m in messages if m.get("hasAttachments")]
            stats["messages_with_attachments"] = len(messages_with_attachments)
            
            logger.info("[Backfill:%s] Found %d messages, %d with attachments", 
                        run_id, len(messages), len(messages_with_attachments))
            
            # Process each message
            for msg in messages_with_attachments:
                msg_id = msg.get("id")
                internet_msg_id = msg.get("internetMessageId", "")
                subject = msg.get("subject", "")
                sender = msg.get("from", {}).get("emailAddress", {}).get("address", "")
                received = msg.get("receivedDateTime", "")
                
                logger.info("[Backfill:%s] Processing message: %s", run_id, subject[:50])
                
                try:
                    # Fetch attachments list
                    att_resp = await client.get(
                        f"https://graph.microsoft.com/v1.0/users/{target_mailbox}/messages/{msg_id}/attachments",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$select": "id,name,contentType,size,isInline"}
                    )
                    
                    if att_resp.status_code != 200:
                        stats["errors"].append(f"Failed to fetch attachments for {subject[:30]}")
                        continue
                    
                    attachments = att_resp.json().get("value", [])
                    stats["attachments_found"] += len(attachments)
                    
                    for att in attachments:
                        att_id = att.get("id")
                        filename = att.get("name", "unknown")
                        content_type = att.get("contentType", "")
                        is_inline = att.get("isInline", False)
                        
                        # Skip inline images
                        if is_inline or content_type.startswith("image/"):
                            stats["attachments_skipped_inline"] += 1
                            continue
                        
                        # Only process PDFs
                        if not filename.lower().endswith(".pdf") and "pdf" not in content_type.lower():
                            stats["attachments_skipped_non_pdf"] += 1
                            continue
                        
                        # Fetch attachment content for hash calculation
                        att_content_resp = await client.get(
                            f"https://graph.microsoft.com/v1.0/users/{target_mailbox}/messages/{msg_id}/attachments/{att_id}",
                            headers={"Authorization": f"Bearer {token}"}
                        )
                        
                        if att_content_resp.status_code != 200:
                            stats["errors"].append(f"Failed to fetch {filename}")
                            continue
                        
                        content_b64 = att_content_resp.json().get("contentBytes", "")
                        content_bytes = base64.b64decode(content_b64)
                        content_hash = hashlib.sha256(content_bytes).hexdigest()
                        
                        # Check idempotency - have we already processed this attachment?
                        # Primary key: internetMessageId + attachment_hash (handles forwarded copies correctly)
                        # Fallback: message_id + attachment_id (Graph-specific IDs)
                        existing = await db.mail_intake_log.find_one({
                            "$or": [
                                {"internet_message_id": internet_msg_id, "attachment_hash": content_hash},
                                {"message_id": msg_id, "attachment_id": att_id}
                            ]
                        })
                        
                        if existing:
                            stats["attachments_skipped_duplicate"] += 1
                            logger.info("[Backfill:%s] Skipping duplicate: %s", run_id, filename)
                            continue
                        
                        # DRY RUN: Just report what would be processed
                        if dry_run:
                            stats["attachments_ingested"] += 1
                            stats["ingested_documents"].append({
                                "filename": filename,
                                "subject": subject,
                                "sender": sender,
                                "received": received,
                                "size_bytes": len(content_bytes),
                                "hash": content_hash[:16] + "...",
                                "status": "WOULD_INGEST"
                            })
                            continue
                        
                        # ACTUAL INGESTION
                        try:
                            result = await _internal_intake_document(
                                file_content=content_bytes,
                                filename=filename,
                                content_type="application/pdf",
                                source="backfill",
                                sender=sender,
                                subject=subject,
                                email_id=msg_id
                            )
                            
                            doc_id = result.get("document", {}).get("id", "unknown")
                            
                            # Log to mail_intake_log for idempotency
                            await db.mail_intake_log.insert_one({
                                "message_id": msg_id,
                                "internet_message_id": internet_msg_id,
                                "attachment_id": att_id,
                                "attachment_hash": content_hash,
                                "filename": filename,
                                "document_id": doc_id,
                                "status": "Ingested",
                                "source": "backfill",
                                "processed_at": datetime.now(timezone.utc).isoformat()
                            })
                            
                            stats["attachments_ingested"] += 1
                            stats["ingested_documents"].append({
                                "filename": filename,
                                "document_id": doc_id,
                                "subject": subject,
                                "sender": sender,
                                "status": "INGESTED"
                            })
                            
                            logger.info("[Backfill:%s] Ingested %s → %s", run_id, filename, doc_id)
                            
                        except Exception as e:
                            stats["errors"].append(f"Intake failed for {filename}: {str(e)}")
                            logger.error("[Backfill:%s] Intake failed for %s: %s", run_id, filename, str(e))
                    
                except Exception as e:
                    stats["errors"].append(f"Error processing message {subject[:30]}: {str(e)}")
            
    except Exception as e:
        stats["errors"].append(f"Backfill error: {str(e)}")
        logger.error("[Backfill:%s] Error: %s", run_id, str(e))
    
    stats["ended_at"] = datetime.now(timezone.utc).isoformat()
    
    logger.info("[Backfill:%s] Complete: found=%d, ingested=%d, skipped_dup=%d, errors=%d",
                run_id, stats["messages_with_attachments"], stats["attachments_ingested"],
                stats["attachments_skipped_duplicate"], len(stats["errors"]))
    
    return stats

