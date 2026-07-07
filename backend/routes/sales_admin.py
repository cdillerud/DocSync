"""
Sales mailbox admin endpoints: one-time backfill + migration to unified schema.

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 11). No logic changed.
"""
import uuid
import base64
import hashlib
import logging
import httpx
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Query

from core.db import db
from core.config import SALES_EMAIL_POLLING_USER
from core.legacy_hub_helpers import get_email_token
from services.pilot_config import get_pilot_metadata
from sales_module import ingest_sales_document, check_sales_duplicate, record_sales_mail_log

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

@router.post("/admin/backfill-sales-mailbox")
async def backfill_sales_mailbox(
    days_back: int = Query(30, description="How many days back to search"),
    max_messages: int = Query(50, description="Maximum messages to process"),
    dry_run: bool = Query(False, description="If true, only report what would be processed")
):
    """
    One-time backfill of existing Sales mailbox emails into the Document Hub.
    
    SAFE DESIGN:
    - Read-only Graph access
    - Does NOT mark messages as read
    - Does NOT move or delete messages
    - Uses idempotency (internetMessageId + attachment hash) to prevent duplicates
    - Processes all attachment types (not just PDFs)
    
    Use this to seed Shadow Mode with real production data.
    """
    run_id = uuid.uuid4().hex[:8]
    
    if not SALES_EMAIL_POLLING_USER:
        raise HTTPException(status_code=400, detail="SALES_EMAIL_POLLING_USER not configured in .env")
    
    stats = {
        "run_id": run_id,
        "dry_run": dry_run,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mailbox": SALES_EMAIL_POLLING_USER,
        "days_back": days_back,
        "max_messages": max_messages,
        "messages_found": 0,
        "messages_with_attachments": 0,
        "attachments_found": 0,
        "attachments_ingested": 0,
        "attachments_skipped_duplicate": 0,
        "attachments_skipped_inline": 0,
        "errors": [],
        "ingested_documents": []
    }
    
    logger.info("[SalesBackfill:%s] Starting Sales mailbox backfill (days=%d, max=%d, dry_run=%s)", 
                run_id, days_back, max_messages, dry_run)
    
    try:
        token = await get_email_token()
        if not token:
            stats["errors"].append("Failed to get email token")
            return stats
        
        start_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
        filter_query = f"receivedDateTime ge {start_date}"
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            messages_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/mailFolders/Inbox/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": filter_query,
                    "$select": "id,subject,from,receivedDateTime,internetMessageId,hasAttachments,bodyPreview",
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
            
            messages_with_attachments = [m for m in messages if m.get("hasAttachments")]
            stats["messages_with_attachments"] = len(messages_with_attachments)
            
            logger.info("[SalesBackfill:%s] Found %d messages, %d with attachments", 
                        run_id, len(messages), len(messages_with_attachments))
            
            for msg in messages_with_attachments:
                msg_id = msg.get("id")
                internet_msg_id = msg.get("internetMessageId", msg_id)
                subject = msg.get("subject", "No Subject")
                sender = msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")
                body_preview = msg.get("bodyPreview", "")
                
                try:
                    att_resp = await client.get(
                        f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/messages/{msg_id}/attachments",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$select": "id,name,contentType,size,isInline"}
                    )
                    
                    if att_resp.status_code != 200:
                        stats["errors"].append(f"Failed to fetch attachments for message: {subject[:50]}")
                        continue
                    
                    attachments = att_resp.json().get("value", [])
                    stats["attachments_found"] += len(attachments)
                    
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
                        
                        if dry_run:
                            stats["ingested_documents"].append({
                                "filename": filename,
                                "subject": subject,
                                "sender": sender,
                                "size_bytes": size_bytes,
                                "status": "WOULD_INGEST"
                            })
                            stats["attachments_ingested"] += 1
                            continue
                        
                        # Fetch attachment content
                        try:
                            att_content_resp = await client.get(
                                f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/messages/{msg_id}/attachments/{att_id}",
                                headers={"Authorization": f"Bearer {token}"}
                            )
                            
                            if att_content_resp.status_code != 200:
                                stats["errors"].append(f"Failed to fetch content for {filename}")
                                continue
                            
                            content_b64 = att_content_resp.json().get("contentBytes", "")
                            content_bytes = base64.b64decode(content_b64)
                            content_hash = hashlib.sha256(content_bytes).hexdigest()
                            
                        except Exception as e:
                            stats["errors"].append(f"Error fetching {filename}: {str(e)}")
                            continue
                        
                        # Check idempotency
                        is_dup = await check_sales_duplicate(internet_msg_id, content_hash)
                        if is_dup:
                            stats["attachments_skipped_duplicate"] += 1
                            continue
                        
                        # Ingest document
                        try:
                            result = await ingest_sales_document(
                                file_content=content_bytes,
                                filename=filename,
                                source="backfill",
                                email_sender=sender,
                                email_subject=subject,
                                email_body=body_preview,
                                email_message_id=internet_msg_id,
                                correlation_id=run_id
                            )
                            
                            doc_id = result.get("document_id")
                            
                            await record_sales_mail_log(
                                message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                attachment_hash=content_hash,
                                filename=filename,
                                status="Ingested",
                                document_id=doc_id
                            )
                            
                            stats["attachments_ingested"] += 1
                            stats["ingested_documents"].append({
                                "filename": filename,
                                "document_id": doc_id,
                                "document_type": result.get("document_type"),
                                "subject": subject,
                                "sender": sender,
                                "status": "INGESTED"
                            })
                            
                            logger.info("[SalesBackfill:%s] Ingested %s → %s (%s)", 
                                       run_id, filename, doc_id, result.get("document_type"))
                            
                        except Exception as e:
                            stats["errors"].append(f"Intake failed for {filename}: {str(e)}")
                            logger.error("[SalesBackfill:%s] Intake failed for %s: %s", run_id, filename, str(e))
                
                except Exception as e:
                    stats["errors"].append(f"Error processing message {subject[:30]}: {str(e)}")
    
    except Exception as e:
        stats["errors"].append(f"Backfill error: {str(e)}")
        logger.error("[SalesBackfill:%s] Error: %s", run_id, str(e))
    
    stats["ended_at"] = datetime.now(timezone.utc).isoformat()
    
    logger.info("[SalesBackfill:%s] Complete: found=%d, ingested=%d, skipped_dup=%d, errors=%d",
                run_id, stats["messages_with_attachments"], stats["attachments_ingested"],
                stats["attachments_skipped_duplicate"], len(stats["errors"]))
    
    return stats

@router.post("/admin/migrate-sales-to-unified")
async def migrate_sales_documents_to_unified():
    """
    One-time migration to move sales_documents into the main hub_documents collection.
    This unifies all documents into a single pipeline with category-based routing.
    
    Documents from sales_documents will be:
    - Copied to hub_documents with category="Sales"
    - Original sales_documents collection will NOT be deleted (kept for reference)
    - Duplicates (by document_id) will be skipped
    """
    run_id = uuid.uuid4().hex[:8]
    
    stats = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "sales_documents_found": 0,
        "migrated": 0,
        "skipped_duplicate": 0,
        "errors": [],
        "migrated_documents": []
    }
    
    try:
        # Get all sales documents
        sales_docs = await db.sales_documents.find({}, {"_id": 0}).to_list(1000)
        stats["sales_documents_found"] = len(sales_docs)
        
        logger.info("[Migration:%s] Found %d sales documents to migrate", run_id, len(sales_docs))
        
        for sdoc in sales_docs:
            doc_id = sdoc.get("document_id")
            
            # Check if already exists in hub_documents
            existing = await db.hub_documents.find_one({"id": doc_id})
            if existing:
                stats["skipped_duplicate"] += 1
                continue
            
            # Map sales document to hub_documents schema
            now = datetime.now(timezone.utc).isoformat()
            
            hub_doc = {
                "id": doc_id,
                "source": sdoc.get("source", "email"),
                "file_name": sdoc.get("file_name"),
                "sha256_hash": sdoc.get("file_hash"),
                "file_size": sdoc.get("file_size"),
                "content_type": "application/octet-stream",
                "email_sender": sdoc.get("email_sender"),
                "email_subject": sdoc.get("email_subject"),
                "email_id": sdoc.get("email_message_id"),
                "email_received_utc": sdoc.get("created_utc"),
                "sharepoint_drive_id": None,
                "sharepoint_item_id": None,
                "sharepoint_web_url": None,
                "sharepoint_share_link_url": None,
                "document_type": sdoc.get("document_type"),
                "category": "Sales",
                "suggested_job_type": sdoc.get("document_type"),
                "ai_confidence": sdoc.get("ai_confidence"),
                "extracted_fields": sdoc.get("extracted_fields", {}),
                "validation_results": None,
                "automation_decision": "manual",
                "bc_record_type": None,
                "bc_company_id": None,
                "bc_record_id": None,
                "bc_document_no": None,
                "status": sdoc.get("status", "NeedsReview"),
                "workflow_state": sdoc.get("workflow_state", "Classified"),
                "validation_errors": sdoc.get("validation_errors", []),
                "validation_warnings": sdoc.get("validation_warnings", []),
                "created_utc": sdoc.get("created_utc", now),
                "updated_utc": now,
                "last_error": None,
                "classification_reasoning": sdoc.get("classification_reasoning"),
                "customer_id_sales": sdoc.get("customer_id"),
                "customer_name_extracted": sdoc.get("customer_name_extracted"),
                "correlation_id": sdoc.get("correlation_id"),
                "migrated_from": "sales_documents",
                "migrated_at": now,
                # Pilot metadata (added if pilot mode enabled)
                **get_pilot_metadata()
            }
            
            try:
                await db.hub_documents.insert_one(hub_doc)
                stats["migrated"] += 1
                stats["migrated_documents"].append({
                    "document_id": doc_id,
                    "document_type": sdoc.get("document_type"),
                    "file_name": sdoc.get("file_name")
                })
            except Exception as e:
                stats["errors"].append(f"Failed to migrate {doc_id}: {str(e)}")
        
        stats["ended_at"] = datetime.now(timezone.utc).isoformat()
        
        logger.info("[Migration:%s] Complete: found=%d, migrated=%d, skipped=%d, errors=%d",
                   run_id, stats["sales_documents_found"], stats["migrated"],
                   stats["skipped_duplicate"], len(stats["errors"]))
        
    except Exception as e:
        stats["errors"].append(f"Migration error: {str(e)}")
        logger.error("[Migration:%s] Error: %s", run_id, str(e))
    
    return stats
