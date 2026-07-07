"""
Email polling / Graph webhook ingestion engine.

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 10). No logic changed.

NOTE: the background-task lifecycle (_email_polling_task global,
asyncio.create_task(email_polling_worker()) on startup, cancellation on
shutdown) stays in server.py on purpose - that's FastAPI app lifecycle
plumbing, not business logic, and belongs with the app object. Only
email_polling_worker() itself (the loop body) and _email_polling_lock (used
only inside it) moved here. server.py imports email_polling_worker from
this module to start/stop it.

NOTE: on_document_ingested is dead code (defined, never called anywhere -
verified during Group 9). Moved here anyway since it lives in the same
"auto-trigger ingestion" theme; harmless either way.

NOTE on a naming quirk (not a bug): process_incoming_email() and
email_polling_worker() both do `config = await get_email_watcher_config()`,
a local dict that shadows the `from core import config` module import for
the rest of that function's body. This is safe under Python's per-function
scoping - neither function also needs the config *module* in the same
scope - but don't copy this pattern into a function that needs both.
"""
import re
import uuid
import base64
import hashlib
import asyncio
import httpx
import logging
from datetime import datetime, timezone, timedelta

from core.db import db
from core import config
from core.config import (
    EMAIL_POLLING_ENABLED, EMAIL_POLLING_USER, EMAIL_POLLING_INTERVAL_MINUTES,
    EMAIL_POLLING_LOOKBACK_MINUTES, EMAIL_POLLING_MAX_MESSAGES,
    EMAIL_POLLING_MAX_ATTACHMENT_MB, EMAIL_CLIENT_ID,
)
from core.paths import UPLOAD_DIR
from core.job_config import DocumentIntake, DEFAULT_JOB_TYPES
from core.legacy_hub_helpers import get_graph_token, get_email_token
from services.pilot_config import get_pilot_metadata
from services.ingestion_engine import (
    classify_document_with_ai, compute_ap_normalized_fields, lookup_vendor_alias,
    validate_bc_match, make_automation_decision, _internal_intake_document,
)

logger = logging.getLogger(__name__)

async def get_email_watcher_config() -> dict:
    """Load email watcher configuration from database."""
    config = await db.hub_config.find_one({"_key": "email_watcher"}, {"_id": 0})
    if not config:
        return {
            "mailbox_address": "",
            "watch_folder": "Inbox",
            "needs_review_folder": "Needs Review",
            "processed_folder": "Processed",
            "enabled": False,
            "interval_minutes": 5,
            "webhook_subscription_id": None,
            "last_poll_utc": None
        }
    # Ensure interval_minutes has a default
    if "interval_minutes" not in config:
        config["interval_minutes"] = 5
    return config

async def subscribe_to_mailbox_notifications(mailbox_address: str, webhook_url: str) -> dict:
    """
    Create a Microsoft Graph subscription for email notifications.
    """
    if config.DEMO_MODE or not config.GRAPH_CLIENT_ID:
        return {"status": "demo", "message": "Running in demo mode"}
    
    try:
        token = await get_graph_token()
        
        # Create subscription for new messages
        subscription_payload = {
            "changeType": "created",
            "notificationUrl": webhook_url,
            "resource": f"users/{mailbox_address}/mailFolders/Inbox/messages",
            "expirationDateTime": (datetime.now(timezone.utc).replace(hour=23, minute=59) + timedelta(days=2)).isoformat() + "Z",
            "clientState": "gpi-document-hub-secret"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as c:
            resp = await c.post(
                "https://graph.microsoft.com/v1.0/subscriptions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=subscription_payload
            )
            
            if resp.status_code in (200, 201):
                data = resp.json()
                return {
                    "status": "ok",
                    "subscription_id": data.get("id"),
                    "expiration": data.get("expirationDateTime")
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create subscription (HTTP {resp.status_code}): {resp.text[:500]}"
                }
    
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def fetch_email_with_attachments(email_id: str, mailbox_address: str) -> dict:
    """Fetch a specific email and its attachments from Graph API."""
    if config.DEMO_MODE or not config.GRAPH_CLIENT_ID:
        return {"status": "demo", "email": None, "attachments": []}
    
    try:
        token = await get_graph_token()
        
        async with httpx.AsyncClient(timeout=60.0) as c:
            # Get email details
            email_resp = await c.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{email_id}",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if email_resp.status_code != 200:
                return {"status": "error", "message": f"Failed to fetch email: {email_resp.status_code}"}
            
            email_data = email_resp.json()
            
            # Get attachments
            attachments_resp = await c.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{email_id}/attachments",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            attachments = []
            if attachments_resp.status_code == 200:
                for att in attachments_resp.json().get("value", []):
                    if att.get("@odata.type") == "#microsoft.graph.fileAttachment":
                        attachments.append({
                            "id": att.get("id"),
                            "name": att.get("name"),
                            "content_type": att.get("contentType"),
                            "size": att.get("size"),
                            "content_bytes": att.get("contentBytes")  # Base64 encoded
                        })
            
            return {
                "status": "ok",
                "email": {
                    "id": email_data.get("id"),
                    "subject": email_data.get("subject"),
                    "sender": email_data.get("from", {}).get("emailAddress", {}).get("address"),
                    "received_utc": email_data.get("receivedDateTime"),
                    "has_attachments": email_data.get("hasAttachments", False)
                },
                "attachments": attachments
            }
    
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def move_email_to_folder(email_id: str, mailbox_address: str, folder_name: str) -> dict:
    """Move an email to a specific folder."""
    if config.DEMO_MODE or not config.GRAPH_CLIENT_ID:
        return {"status": "demo"}
    
    try:
        token = await get_graph_token()
        
        async with httpx.AsyncClient(timeout=30.0) as c:
            # First, find the folder ID
            folders_resp = await c.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if folders_resp.status_code != 200:
                return {"status": "error", "message": f"Failed to list folders: {folders_resp.status_code}"}
            
            folder_id = None
            for folder in folders_resp.json().get("value", []):
                if folder.get("displayName") == folder_name:
                    folder_id = folder.get("id")
                    break
            
            if not folder_id:
                # Create the folder if it doesn't exist
                create_resp = await c.post(
                    f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    },
                    json={"displayName": folder_name}
                )
                if create_resp.status_code in (200, 201):
                    folder_id = create_resp.json().get("id")
                else:
                    return {"status": "error", "message": f"Failed to create folder: {create_resp.status_code}"}
            
            # Move the email
            move_resp = await c.post(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{email_id}/move",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json={"destinationId": folder_id}
            )
            
            if move_resp.status_code in (200, 201):
                return {"status": "ok", "folder": folder_name}
            else:
                return {"status": "error", "message": f"Failed to move email: {move_resp.status_code}"}
    
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ==================== AUTOMATIC WORKFLOW TRIGGER ====================

async def on_document_ingested(doc_id: str, source: str = "unknown"):
    """
    Triggered automatically after every successful document ingestion.
    Runs validation workflow and creates audit trail.
    
    Called by all ingestion paths:
    - Manual upload
    - Email polling  
    - Backfill
    - API upload
    
    Safety: Does NOT create BC drafts in Phase 7 (controlled by ENABLE_CREATE_DRAFT_HEADER flag)
    """
    run_id = uuid.uuid4().hex[:8]
    correlation_id = uuid.uuid4().hex[:8]
    started_at = datetime.now(timezone.utc)
    
    logger.info("[Workflow:%s] Auto-triggered for doc %s (source: %s)", run_id, doc_id, source)
    
    try:
        # Get document
        doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        if not doc:
            logger.error("[Workflow:%s] Document not found: %s", run_id, doc_id)
            return
        
        old_status = doc.get("status", "Unknown")
        job_type = doc.get("suggested_job_type", "AP_Invoice")
        extracted_fields = doc.get("extracted_fields", {})
        
        # Get job config
        job_configs = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
        if not job_configs:
            job_configs = DEFAULT_JOB_TYPES.get(job_type, DEFAULT_JOB_TYPES["AP_Invoice"])
        
        # Run BC validation
        validation_results = await validate_bc_match(job_type, extracted_fields, job_configs)
        
        # Make automation decision
        confidence = doc.get("ai_confidence", 0.0)
        decision, reasoning, decision_metadata = make_automation_decision(job_configs, confidence, validation_results)
        
        # Determine new status based on decision
        new_status = old_status
        if decision == "auto_link" and validation_results.get("all_passed"):
            new_status = "ReadyToLink"
        elif decision == "needs_review":
            new_status = "NeedsReview"
        elif decision == "manual":
            new_status = "NeedsReview"
        elif decision == "exception":
            new_status = "Exception"
        
        # Update document
        update_data = {
            "validation_results": validation_results,
            "automation_decision": decision,
            "match_method": validation_results.get("match_method", "none"),
            "match_score": validation_results.get("match_score", 0.0),
            "vendor_candidates": decision_metadata.get("vendor_candidates", []),
            "customer_candidates": decision_metadata.get("customer_candidates", []),
            "warnings": decision_metadata.get("warnings", []),
            "status": new_status,
            "workflow_state": "Validated",
            "updated_utc": datetime.now(timezone.utc).isoformat()
        }
        
        await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
        
        # Create workflow audit trail entry
        duration = (datetime.now(timezone.utc) - started_at).total_seconds()
        
        await db.hub_workflow_runs.insert_one({
            "run_id": run_id,
            "correlation_id": correlation_id,
            "document_id": doc_id,
            "workflow_type": "auto_validation",
            "source": source,
            "status": "Completed",
            "started_at": started_at.isoformat(),
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(duration, 2),
            "steps": [
                {
                    "step": "Validation",
                    "status": "Completed",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "details": {
                        "old_status": old_status,
                        "new_status": new_status,
                        "match_method": validation_results.get("match_method", "none"),
                        "match_score": validation_results.get("match_score", 0.0),
                        "automation_decision": decision,
                        "reasoning": reasoning
                    }
                }
            ]
        })
        
        logger.info("[Workflow:%s] Complete: %s → %s (decision: %s, score: %.2f)", 
                    run_id, old_status, new_status, decision, validation_results.get("match_score", 0.0))
        
    except Exception as e:
        # Log error but don't fail silently - create an error audit entry
        logger.error("[Workflow:%s] Error processing doc %s: %s", run_id, doc_id, str(e))
        
        try:
            await db.hub_workflow_runs.insert_one({
                "run_id": run_id,
                "correlation_id": correlation_id,
                "document_id": doc_id,
                "workflow_type": "auto_validation",
                "source": source,
                "status": "Failed",
                "started_at": started_at.isoformat(),
                "ended_at": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
                "steps": []
            })
        except:
            pass  # Don't let audit logging failure mask the original error


async def process_incoming_email(email_id: str, mailbox_address: str):
    """Process a new incoming email with attachments."""
    config = await get_email_watcher_config()
    
    if not config.get("enabled"):
        logger.info("Email watcher disabled, skipping email %s", email_id)
        return
    
    # Fetch email and attachments
    email_data = await fetch_email_with_attachments(email_id, mailbox_address)
    
    if email_data.get("status") != "ok":
        logger.error("Failed to fetch email %s: %s", email_id, email_data.get("message"))
        return
    
    email = email_data.get("email", {})
    attachments = email_data.get("attachments", [])
    
    if not attachments:
        logger.info("Email %s has no attachments, skipping", email_id)
        return
    
    # Process each attachment
    for attachment in attachments:
        try:
            # Decode attachment content
            content_bytes = base64.b64decode(attachment.get("content_bytes", ""))
            
            # Create intake request
            intake = DocumentIntake(
                source="email",
                sender=email.get("sender"),
                subject=email.get("subject"),
                attachment_name=attachment.get("name"),
                content_hash=hashlib.sha256(content_bytes).hexdigest(),
                email_id=email_id,
                email_received_utc=email.get("received_utc")
            )
            
            # Save attachment temporarily
            temp_id = str(uuid.uuid4())
            temp_path = UPLOAD_DIR / temp_id
            temp_path.write_bytes(content_bytes)
            
            # Process through intake workflow
            doc_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            
            # Create document record
            doc = {
                "id": doc_id,
                "source": "email",
                "file_name": attachment.get("name"),
                "sha256_hash": intake.content_hash,
                "file_size": len(content_bytes),
                "content_type": attachment.get("content_type"),
                "email_sender": intake.sender,
                "email_subject": intake.subject,
                "email_id": email_id,
                "email_received_utc": intake.email_received_utc,
                "status": "Received",
                "created_utc": now,
                "updated_utc": now,
                # Pilot metadata (added if pilot mode enabled)
                **get_pilot_metadata()
            }
            await db.hub_documents.insert_one(doc)
            
            # Move temp file to permanent location
            perm_path = UPLOAD_DIR / doc_id
            temp_path.rename(perm_path)
            
            # Run classification
            classification = await classify_document_with_ai(str(perm_path), attachment.get("name"))
            
            suggested_type = classification.get("suggested_job_type", "Unknown")
            confidence = classification.get("confidence", 0.0)
            extracted_fields = classification.get("extracted_fields", {})
            
            # Phase 8: Compute normalized fields including invoice_date and line_items
            normalized_fields = compute_ap_normalized_fields(extracted_fields)
            
            # Phase 7: Vendor alias lookup
            vendor_alias_result = await lookup_vendor_alias(normalized_fields.get("vendor_normalized"))
            
            # Get job config and validate
            job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
            if not job_configs:
                job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])
            
            validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)
            decision, reasoning = make_automation_decision(job_configs, confidence, validation_results)
            
            # Update document with ALL extracted data including invoice_date and line_items
            new_status = "NeedsReview" if decision == "needs_review" else "Classified"
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "suggested_job_type": suggested_type,
                "document_type": suggested_type,
                "ai_confidence": confidence,
                "extracted_fields": extracted_fields,
                # Phase 8: Flat normalized fields for BC posting
                "vendor_raw": normalized_fields.get("vendor_raw"),
                "vendor_normalized": normalized_fields.get("vendor_normalized"),
                "invoice_number_raw": normalized_fields.get("invoice_number_raw"),
                "invoice_number_clean": normalized_fields.get("invoice_number_clean"),
                "amount_raw": normalized_fields.get("amount_raw"),
                "amount_float": normalized_fields.get("amount_float"),
                "due_date_raw": normalized_fields.get("due_date_raw"),
                "due_date_iso": normalized_fields.get("due_date_iso"),
                "po_number_raw": normalized_fields.get("po_number_raw"),
                "po_number_clean": normalized_fields.get("po_number_clean"),
                # CRITICAL: Invoice date and line items for automatic BC posting
                "invoice_date": normalized_fields.get("invoice_date"),
                "invoice_date_raw": normalized_fields.get("invoice_date_raw"),
                "line_items": normalized_fields.get("line_items", []),
                # Vendor matching
                "vendor_canonical": vendor_alias_result.get("vendor_canonical"),
                "vendor_match_method": vendor_alias_result.get("vendor_match_method"),
                # Validation
                "validation_results": validation_results,
                "automation_decision": decision,
                "status": new_status,
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }})
            
            # Move email to appropriate folder
            if decision == "needs_review":
                await move_email_to_folder(email_id, mailbox_address, config.get("needs_review_folder", "Needs Review"))
            else:
                await move_email_to_folder(email_id, mailbox_address, config.get("processed_folder", "Processed"))
            
            logger.info("Processed email attachment: doc_id=%s, type=%s, decision=%s", doc_id, suggested_type, decision)
            
        except Exception as e:
            logger.error("Failed to process attachment from email %s: %s", email_id, str(e))

# ==================== PHASE 7 C1: EMAIL POLLING (OBSERVATION INFRASTRUCTURE) ====================
# This is NOT a product feature - it is data collection plumbing for shadow mode.
# Scope: Poll → Ingest → Log → Metrics. No BC writes, no folder moves.

# Global state for polling worker
_email_polling_lock = asyncio.Lock()

# Skip patterns for attachments (inline images, signatures)
SKIP_CONTENT_TYPES = {'image/gif', 'image/x-icon', 'image/bmp'}
SKIP_FILENAME_PATTERNS = [
    r'^image\d+\.(png|jpg|gif)$',  # Inline images
    r'^signature',  # Email signatures
    r'^logo',  # Company logos
    r'\.vcf$',  # Contact cards
]


async def record_mail_intake_log(
    message_id: str,
    internet_message_id: str,
    attachment_id: str,
    attachment_hash: str,
    filename: str,
    status: str,
    sharepoint_doc_id: str = None,
    error: str = None
):
    """Record mail intake for idempotency and observability."""
    log_entry = {
        "id": str(uuid.uuid4()),
        "message_id": message_id,
        "internet_message_id": internet_message_id,
        "attachment_id": attachment_id,
        "attachment_hash": attachment_hash,
        "filename": filename,
        "status": status,  # Processed, SkippedDuplicate, SkippedInline, Error
        "sharepoint_doc_id": sharepoint_doc_id,
        "error": error,
        "processed_at": datetime.now(timezone.utc).isoformat()
    }
    await db.mail_intake_log.insert_one(log_entry)
    return log_entry


async def check_duplicate_mail_intake(internet_message_id: str, attachment_hash: str, message_id: str = None, attachment_id: str = None) -> bool:
    """Check if this attachment was already processed (idempotency).
    
    Primary key: internetMessageId + attachment_hash
    Fallback: message_id + attachment_id (Graph-specific IDs)
    """
    query = {"$or": [
        {"internet_message_id": internet_message_id, "attachment_hash": attachment_hash}
    ]}
    if message_id and attachment_id:
        query["$or"].append({"message_id": message_id, "attachment_id": attachment_id})
    
    existing = await db.mail_intake_log.find_one(query)
    return existing is not None


def should_skip_attachment(filename: str, content_type: str, size_bytes: int) -> tuple:
    """Determine if attachment should be skipped (inline images, signatures, too large)."""
    # Check content type
    if content_type and content_type.lower() in SKIP_CONTENT_TYPES:
        return (True, f"Skipped content type: {content_type}")
    
    # Check filename patterns
    if filename:
        for pattern in SKIP_FILENAME_PATTERNS:
            if re.match(pattern, filename.lower()):
                return (True, f"Skipped filename pattern: {filename}")
    
    # Check size limit
    max_size = EMAIL_POLLING_MAX_ATTACHMENT_MB * 1024 * 1024
    if size_bytes > max_size:
        return (True, f"Skipped size: {size_bytes / 1024 / 1024:.1f}MB > {EMAIL_POLLING_MAX_ATTACHMENT_MB}MB limit")
    
    return (False, None)


async def poll_mailbox_for_attachments():
    """
    Phase C1 (Revised): Passive Graph "Tap" - READ-ONLY.
    
    This is a shadow listener that does NOT modify the mailbox in any way.
    Zetadocs/Square9 continues to own the inbox state.
    
    Process flow:
    1. Get watermark (last seen receivedDateTime)
    2. Query messages received after watermark (with overlap buffer)
    3. For each message with attachments:
       - Check idempotency log (skip duplicates)
       - Store in SharePoint first (durability)
       - Process through intake pipeline
       - Log result
    4. Update watermark
    
    Permissions: Mail.Read only (application permission)
    
    What this does NOT do:
    - Mark messages as read
    - Add categories
    - Move messages
    - Delete anything
    """
    if not EMAIL_POLLING_ENABLED:
        return {"skipped": True, "reason": "EMAIL_POLLING_ENABLED is false"}
    
    if not EMAIL_POLLING_USER:
        return {"skipped": True, "reason": "EMAIL_POLLING_USER not configured"}
    
    if config.DEMO_MODE:
        return {"skipped": True, "reason": "Demo mode - no real polling"}
    
    run_id = str(uuid.uuid4())[:8]
    logger.info("[EmailPoll:%s] Starting passive tap for %s", run_id, EMAIL_POLLING_USER)
    
    stats = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "messages_detected": 0,
        "attachments_ingested": 0,
        "attachments_skipped_duplicate": 0,
        "attachments_skipped_inline": 0,
        "attachments_failed": 0,
        "errors": []
    }
    
    try:
        # Get Email token (uses EMAIL_CLIENT_ID/SECRET if configured)
        token = await get_email_token()
        if not token:
            stats["errors"].append("Failed to get Email token")
            return stats
        
        # Get watermark from settings (last seen receivedDateTime)
        watermark_doc = await db.hub_settings.find_one({"type": "email_poll_watermark"}, {"_id": 0})
        
        if watermark_doc and watermark_doc.get("last_received_datetime"):
            # Use watermark with 5-minute overlap buffer for safety
            watermark_time = watermark_doc["last_received_datetime"]
            try:
                watermark_dt = datetime.fromisoformat(watermark_time.replace('Z', '+00:00'))
                buffer_time = (watermark_dt - timedelta(minutes=5)).isoformat()
            except Exception:
                buffer_time = watermark_time
        else:
            # First run: look back N minutes
            buffer_time = (datetime.now(timezone.utc) - timedelta(minutes=EMAIL_POLLING_LOOKBACK_MINUTES)).isoformat()
        
        # Query messages received after watermark
        # Note: hasAttachments filter combined with orderby can cause InefficientFilter error
        # So we filter by date only and check attachments client-side
        filter_query = f"receivedDateTime ge {buffer_time}"
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            messages_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{EMAIL_POLLING_USER}/mailFolders/Inbox/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": filter_query,
                    "$select": "id,subject,from,receivedDateTime,internetMessageId,hasAttachments",
                    "$top": EMAIL_POLLING_MAX_MESSAGES,
                    "$orderby": "receivedDateTime asc"
                }
            )
            
            if messages_resp.status_code != 200:
                error_msg = f"Graph API error {messages_resp.status_code}: {messages_resp.text[:200]}"
                logger.error("[EmailPoll:%s] %s", run_id, error_msg)
                stats["errors"].append(error_msg)
                return stats
            
            messages = messages_resp.json().get("value", [])
            # Filter to only messages with attachments (client-side filter)
            messages_with_attachments = [m for m in messages if m.get("hasAttachments")]
            stats["messages_detected"] = len(messages_with_attachments)
            
            logger.info("[EmailPoll:%s] Detected %d messages with attachments (out of %d total)", run_id, len(messages_with_attachments), len(messages))
            
            # Process each message
            for msg in messages_with_attachments:
                msg_id = msg["id"]
                internet_msg_id = msg.get("internetMessageId", msg_id)
                subject = msg.get("subject", "No Subject")
                sender = msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")
                
                try:
                    # Fetch attachments list (without contentBytes - not allowed in list query)
                    att_resp = await client.get(
                        f"https://graph.microsoft.com/v1.0/users/{EMAIL_POLLING_USER}/messages/{msg_id}/attachments",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$select": "id,name,contentType,size"}
                    )
                    
                    if att_resp.status_code != 200:
                        stats["errors"].append(f"Failed to fetch attachments for {msg_id}")
                        continue
                    
                    attachments = att_resp.json().get("value", [])
                    
                    for att in attachments:
                        att_id = att.get("id")
                        filename = att.get("name", "unknown")
                        content_type = att.get("contentType", "")
                        size_bytes = att.get("size", 0)
                        
                        # Skip check
                        should_skip, skip_reason = should_skip_attachment(filename, content_type, size_bytes)
                        if should_skip:
                            await record_mail_intake_log(
                                message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                attachment_hash="",
                                filename=filename,
                                status="SkippedInline",
                                error=skip_reason
                            )
                            stats["attachments_skipped_inline"] += 1
                            continue
                        
                        # Fetch individual attachment content
                        try:
                            att_content_resp = await client.get(
                                f"https://graph.microsoft.com/v1.0/users/{EMAIL_POLLING_USER}/messages/{msg_id}/attachments/{att_id}",
                                headers={"Authorization": f"Bearer {token}"}
                            )
                            if att_content_resp.status_code != 200:
                                stats["attachments_failed"] += 1
                                stats["errors"].append(f"Failed to fetch content for {filename}")
                                continue
                            content_b64 = att_content_resp.json().get("contentBytes", "")
                        except Exception as e:
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Error fetching {filename}: {str(e)}")
                            continue
                        
                        # Decode content and hash
                        try:
                            content_bytes = base64.b64decode(content_b64)
                            att_hash = hashlib.sha256(content_bytes).hexdigest()
                        except Exception as e:
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Failed to decode {filename}: {str(e)}")
                            continue
                        
                        # Idempotency check
                        if await check_duplicate_mail_intake(internet_msg_id, att_hash):
                            await record_mail_intake_log(
                                message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                attachment_hash=att_hash,
                                filename=filename,
                                status="SkippedDuplicate"
                            )
                            stats["attachments_skipped_duplicate"] += 1
                            continue
                        
                        # Process through intake pipeline
                        try:
                            intake_result = await _internal_intake_document(
                                file_content=content_bytes,
                                filename=filename,
                                content_type=content_type,
                                source="email_poll",
                                email_id=msg_id,
                                subject=subject,
                                sender=sender
                            )
                            
                            doc_id = intake_result.get("document", {}).get("id")
                            
                            await record_mail_intake_log(
                                message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                attachment_hash=att_hash,
                                filename=filename,
                                status="Processed",
                                sharepoint_doc_id=doc_id
                            )
                            stats["attachments_ingested"] += 1
                            
                            logger.info("[EmailPoll:%s] Ingested %s → doc %s", run_id, filename, doc_id)
                            
                        except Exception as e:
                            await record_mail_intake_log(
                                message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                attachment_hash=att_hash,
                                filename=filename,
                                status="Error",
                                error=str(e)
                            )
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Intake failed for {filename}: {str(e)}")
                    
                    # NO mailbox mutations - we are read-only
                    # Idempotency log is the source of truth, not mailbox state
                
                except Exception as e:
                    stats["errors"].append(f"Failed processing message {msg_id}: {str(e)}")
            
            # Update watermark to newest receivedDateTime seen
            if messages:
                newest_received = max(msg.get("receivedDateTime", "") for msg in messages)
                if newest_received:
                    await db.hub_settings.update_one(
                        {"type": "email_poll_watermark"},
                        {"$set": {
                            "last_received_datetime": newest_received,
                            "updated_utc": datetime.now(timezone.utc).isoformat()
                        }},
                        upsert=True
                    )
        
    except Exception as e:
        stats["errors"].append(f"Poll run failed: {str(e)}")
        logger.error("[EmailPoll:%s] Run failed: %s", run_id, str(e))
    
    stats["ended_at"] = datetime.now(timezone.utc).isoformat()
    
    # Store run stats (make a copy since insert_one adds _id)
    stats_to_store = stats.copy()
    await db.mail_poll_runs.insert_one(stats_to_store)
    
    logger.info(
        "[EmailPoll:%s] Complete: detected=%d, ingested=%d, skipped_dup=%d, skipped_inline=%d, failed=%d",
        run_id, stats["messages_detected"], stats["attachments_ingested"],
        stats["attachments_skipped_duplicate"], stats["attachments_skipped_inline"], stats["attachments_failed"]
    )
    
    return stats


async def email_polling_worker():
    """Background worker that polls mailbox at configured interval."""
    logger.info("Email polling worker started (interval: %d minutes)", EMAIL_POLLING_INTERVAL_MINUTES)
    
    while True:
        try:
            # Get current interval from config (allows runtime adjustment)
            config = await get_email_watcher_config()
            interval = config.get("interval_minutes", EMAIL_POLLING_INTERVAL_MINUTES)
            
            # Check if polling is enabled
            async with _email_polling_lock:
                if config.get("enabled", True) and EMAIL_POLLING_ENABLED:
                    await poll_mailbox_for_attachments()
        except Exception as e:
            logger.error("Email polling worker error: %s", str(e))
        
        # Get interval again in case it changed
        try:
            config = await get_email_watcher_config()
            interval = config.get("interval_minutes", EMAIL_POLLING_INTERVAL_MINUTES)
        except:
            interval = EMAIL_POLLING_INTERVAL_MINUTES
        
        # Wait for next interval
        await asyncio.sleep(interval * 60)


