"""
Sales mailbox polling engine (background worker + poll logic).

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 11). No logic changed.

NOTE: same pattern as services/email_polling_engine.py - the background-task
lifecycle (_sales_polling_task global, asyncio.create_task on startup,
cancellation on shutdown) stays in server.py since that's app lifecycle
plumbing. Only the loop body (_sales_email_polling_worker) and the actual
poll logic (run_sales_email_poll) moved here.
"""
import uuid
import base64
import hashlib
import asyncio
import httpx
import logging
from datetime import datetime, timezone, timedelta

from core.db import db
from core.config import (
    SALES_EMAIL_POLLING_USER, SALES_EMAIL_POLLING_ENABLED,
    SALES_EMAIL_POLLING_INTERVAL_MINUTES,
    EMAIL_POLLING_LOOKBACK_MINUTES, EMAIL_POLLING_MAX_MESSAGES,
)
from core.legacy_hub_helpers import get_email_token
from sales_module import ingest_sales_document, check_sales_duplicate, record_sales_mail_log

logger = logging.getLogger(__name__)

async def run_sales_email_poll():
    """
    Poll the Sales intake mailbox for new documents.
    
    Similar to AP email polling but routes to Sales document pipeline.
    All documents classified and stored, none auto-processed.
    """
    run_id = str(uuid.uuid4())[:8]
    
    if not SALES_EMAIL_POLLING_USER:
        return {"skipped": True, "reason": "SALES_EMAIL_POLLING_USER not configured"}
    
    stats = {
        "run_id": run_id,
        "mailbox": SALES_EMAIL_POLLING_USER,
        "messages_detected": 0,
        "attachments_ingested": 0,
        "attachments_skipped_dup": 0,
        "attachments_skipped_inline": 0,
        "attachments_failed": 0,
        "errors": [],
        "started_at": datetime.now(timezone.utc).isoformat()
    }
    
    try:
        logger.info("[SalesPoll:%s] Starting poll for %s", run_id, SALES_EMAIL_POLLING_USER)
        
        # Get email access token
        token = await get_email_token()
        if not token:
            stats["errors"].append("Failed to get email access token")
            return stats
        
        # Calculate lookback window
        lookback = EMAIL_POLLING_LOOKBACK_MINUTES
        buffer_time = (datetime.now(timezone.utc) - timedelta(minutes=lookback)).isoformat()
        filter_query = f"receivedDateTime ge {buffer_time}"
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Query messages
            messages_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/mailFolders/Inbox/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": filter_query,
                    "$select": "id,subject,from,receivedDateTime,internetMessageId,hasAttachments,bodyPreview",
                    "$top": EMAIL_POLLING_MAX_MESSAGES,
                    "$orderby": "receivedDateTime asc"
                }
            )
            
            if messages_resp.status_code != 200:
                stats["errors"].append(f"Graph API error: {messages_resp.status_code}")
                return stats
            
            messages = messages_resp.json().get("value", [])
            stats["messages_detected"] = len(messages)
            
            for msg in messages:
                msg_id = msg.get("id")
                has_attachments = msg.get("hasAttachments", False)
                
                if not has_attachments:
                    continue
                
                internet_msg_id = msg.get("internetMessageId", msg_id)
                subject = msg.get("subject", "No Subject")
                sender = msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")
                body_preview = msg.get("bodyPreview", "")
                
                try:
                    # Fetch attachments
                    att_resp = await client.get(
                        f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/messages/{msg_id}/attachments",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$select": "id,name,contentType,size,isInline"}
                    )
                    
                    if att_resp.status_code != 200:
                        stats["errors"].append(f"Failed to fetch attachments for {msg_id}")
                        continue
                    
                    attachments = att_resp.json().get("value", [])
                    
                    for att in attachments:
                        att_id = att.get("id")
                        filename = att.get("name", "unknown")
                        content_type = att.get("contentType", "")
                        is_inline = att.get("isInline", False)
                        size_bytes = att.get("size", 0)
                        
                        # Skip inline images and signatures
                        if is_inline or content_type.startswith("image/"):
                            stats["attachments_skipped_inline"] += 1
                            continue
                        
                        # Skip very small files (likely signatures)
                        if size_bytes < 1000:
                            stats["attachments_skipped_inline"] += 1
                            continue
                        
                        # Fetch attachment content
                        try:
                            att_content_resp = await client.get(
                                f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/messages/{msg_id}/attachments/{att_id}",
                                headers={"Authorization": f"Bearer {token}"}
                            )
                            if att_content_resp.status_code != 200:
                                stats["attachments_failed"] += 1
                                continue
                            content_b64 = att_content_resp.json().get("contentBytes", "")
                        except Exception as e:
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Error fetching {filename}: {str(e)}")
                            continue
                        
                        content_bytes = base64.b64decode(content_b64)
                        content_hash = hashlib.sha256(content_bytes).hexdigest()
                        
                        # Check idempotency
                        is_dup = await check_sales_duplicate(internet_msg_id, content_hash)
                        if is_dup:
                            stats["attachments_skipped_dup"] += 1
                            continue
                        
                        # Ingest document
                        try:
                            result = await ingest_sales_document(
                                file_content=content_bytes,
                                filename=filename,
                                source="email",
                                email_sender=sender,
                                email_subject=subject,
                                email_body=body_preview,
                                email_message_id=internet_msg_id,
                                correlation_id=run_id
                            )
                            
                            # Log intake
                            await record_sales_mail_log(
                                message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                attachment_hash=content_hash,
                                filename=filename,
                                status="Ingested",
                                document_id=result.get("document_id")
                            )
                            
                            stats["attachments_ingested"] += 1
                            logger.info("[SalesPoll:%s] Ingested: %s -> %s", run_id, filename, result.get("document_type"))
                            
                        except Exception as e:
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Ingestion failed for {filename}: {str(e)}")
                            await record_sales_mail_log(
                                message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                attachment_hash=content_hash,
                                filename=filename,
                                status="Failed",
                                error=str(e)
                            )
                            
                except Exception as e:
                    stats["errors"].append(f"Error processing message {msg_id}: {str(e)}")
                    
    except Exception as e:
        stats["errors"].append(f"Poll run failed: {str(e)}")
        logger.error("[SalesPoll:%s] Run failed: %s", run_id, str(e))
    
    stats["completed_at"] = datetime.now(timezone.utc).isoformat()
    
    # Record poll run - make a copy to avoid _id mutation affecting response
    stats_to_store = {**stats}
    await db.sales_mail_poll_runs.insert_one(stats_to_store)
    
    logger.info("[SalesPoll:%s] Complete: detected=%d, ingested=%d, skipped_dup=%d, skipped_inline=%d, failed=%d",
                run_id, stats["messages_detected"], stats["attachments_ingested"],
                stats["attachments_skipped_dup"], stats["attachments_skipped_inline"], stats["attachments_failed"])
    
    return stats


async def _sales_email_polling_worker():
    """Background worker that polls sales mailbox periodically."""
    while True:
        try:
            if SALES_EMAIL_POLLING_ENABLED and SALES_EMAIL_POLLING_USER:
                await run_sales_email_poll()
        except Exception as e:
            logger.error("Sales email polling worker error: %s", str(e))
        
        await asyncio.sleep(SALES_EMAIL_POLLING_INTERVAL_MINUTES * 60)
