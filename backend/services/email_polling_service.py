"""
GPI Document Hub - Email Polling Service

Extracted from server.py — authoritative implementation of:
  - Email watcher configuration (get_email_watcher_config)
  - Graph API mailbox subscriptions (subscribe_to_mailbox_notifications)
  - Email fetching (fetch_email_with_attachments)
  - Email folder management (move_email_to_folder)
  - Mail intake logging (record_mail_intake_log, check_duplicate_mail_intake)
  - Attachment filtering (should_skip_attachment)
  - Mailbox polling (poll_mailbox_for_attachments, poll_mailbox_for_documents)
  - Background polling workers (email_polling_worker, dynamic_mailbox_polling_worker,
    _sales_email_polling_worker, run_sales_email_poll)

All functions use deps.get_db() for database access and
services.config_service for token management.
"""

import asyncio
import base64
import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from deps import (
    get_db,
    DEMO_MODE,
    EMAIL_POLLING_ENABLED,
    EMAIL_POLLING_INTERVAL_MINUTES,
    EMAIL_POLLING_USER,
    EMAIL_POLLING_LOOKBACK_MINUTES,
    EMAIL_POLLING_MAX_MESSAGES,
    EMAIL_POLLING_MAX_ATTACHMENT_MB,
    SALES_EMAIL_POLLING_ENABLED,
    SALES_EMAIL_POLLING_USER,
    SALES_EMAIL_POLLING_INTERVAL_MINUTES,
    GRAPH_CLIENT_ID,
)

logger = logging.getLogger(__name__)

# ── Skip patterns for attachments (inline images, signatures) ──
SKIP_CONTENT_TYPES = {'image/gif', 'image/x-icon', 'image/bmp'}
SKIP_FILENAME_PATTERNS = [
    r'^image\d+\.(png|jpg|gif)$',
    r'^signature',
    r'^logo',
    r'\.vcf$',
]

# ── Global state for polling workers ──
_email_polling_lock = asyncio.Lock()
_dynamic_mailbox_polling_task = None
_mailbox_last_poll_times = {}


# =========================================================================
# Email Watcher Config
# =========================================================================

async def get_email_watcher_config() -> dict:
    """Load email watcher configuration from database."""
    db = get_db()
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
            "last_poll_utc": None,
        }
    if "interval_minutes" not in config:
        config["interval_minutes"] = 5
    return config


# =========================================================================
# Graph API Helpers
# =========================================================================

async def subscribe_to_mailbox_notifications(mailbox_address: str, webhook_url: str) -> dict:
    """Create a Microsoft Graph subscription for email notifications."""
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return {"status": "demo", "message": "Running in demo mode"}

    try:
        from services.config_service import get_graph_token
        token = await get_graph_token()

        subscription_payload = {
            "changeType": "created",
            "notificationUrl": webhook_url,
            "resource": f"users/{mailbox_address}/mailFolders/Inbox/messages",
            "expirationDateTime": (
                datetime.now(timezone.utc).replace(hour=23, minute=59) + timedelta(days=2)
            ).isoformat() + "Z",
            "clientState": "gpi-document-hub-secret",
        }

        async with httpx.AsyncClient(timeout=30.0) as c:
            resp = await c.post(
                "https://graph.microsoft.com/v1.0/subscriptions",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=subscription_payload,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                return {"status": "ok", "subscription_id": data.get("id"), "expiration": data.get("expirationDateTime")}
            return {"status": "error", "message": f"Failed to create subscription (HTTP {resp.status_code}): {resp.text[:500]}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def fetch_email_with_attachments(email_id: str, mailbox_address: str) -> dict:
    """Fetch a specific email and its attachments from Graph API."""
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return {"status": "demo", "email": None, "attachments": []}

    try:
        from services.config_service import get_graph_token
        token = await get_graph_token()

        async with httpx.AsyncClient(timeout=60.0) as c:
            email_resp = await c.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{email_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if email_resp.status_code != 200:
                return {"status": "error", "message": f"Failed to fetch email: {email_resp.status_code}"}
            email_data = email_resp.json()

            attachments_resp = await c.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{email_id}/attachments",
                headers={"Authorization": f"Bearer {token}"},
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
                            "content_bytes": att.get("contentBytes"),
                        })

            return {
                "status": "ok",
                "email": {
                    "id": email_data.get("id"),
                    "subject": email_data.get("subject"),
                    "sender": email_data.get("from", {}).get("emailAddress", {}).get("address"),
                    "received_utc": email_data.get("receivedDateTime"),
                    "has_attachments": email_data.get("hasAttachments", False),
                },
                "attachments": attachments,
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def move_email_to_folder(email_id: str, mailbox_address: str, folder_name: str) -> dict:
    """Move an email to a specific folder."""
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return {"status": "demo"}

    try:
        from services.config_service import get_graph_token
        token = await get_graph_token()

        async with httpx.AsyncClient(timeout=30.0) as c:
            folders_resp = await c.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders",
                headers={"Authorization": f"Bearer {token}"},
            )
            if folders_resp.status_code != 200:
                return {"status": "error", "message": f"Failed to list folders: {folders_resp.status_code}"}

            folder_id = None
            for folder in folders_resp.json().get("value", []):
                if folder.get("displayName") == folder_name:
                    folder_id = folder.get("id")
                    break

            if not folder_id:
                create_resp = await c.post(
                    f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"displayName": folder_name},
                )
                if create_resp.status_code in (200, 201):
                    folder_id = create_resp.json().get("id")
                else:
                    return {"status": "error", "message": f"Failed to create folder: {create_resp.status_code}"}

            move_resp = await c.post(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{email_id}/move",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"destinationId": folder_id},
            )
            if move_resp.status_code in (200, 201):
                return {"status": "ok", "folder": folder_name}
            return {"status": "error", "message": f"Failed to move email: {move_resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# =========================================================================
# Mail Intake Logging & Dedup
# =========================================================================

async def record_mail_intake_log(
    message_id: str,
    internet_message_id: str,
    attachment_id: str,
    attachment_hash: str,
    filename: str,
    status: str,
    sharepoint_doc_id: str = None,
    error: str = None,
):
    """Record mail intake for idempotency and observability."""
    db = get_db()
    log_entry = {
        "id": str(uuid.uuid4()),
        "message_id": message_id,
        "internet_message_id": internet_message_id,
        "attachment_id": attachment_id,
        "attachment_hash": attachment_hash,
        "filename": filename,
        "status": status,
        "sharepoint_doc_id": sharepoint_doc_id,
        "error": error,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.mail_intake_log.insert_one(log_entry)
    return log_entry


async def check_duplicate_mail_intake(
    internet_message_id: str, attachment_hash: str,
    message_id: str = None, attachment_id: str = None,
) -> bool:
    """Check if this attachment was already processed (idempotency)."""
    db = get_db()
    query = {"$or": [
        {"internet_message_id": internet_message_id, "attachment_hash": attachment_hash}
    ]}
    if message_id and attachment_id:
        query["$or"].append({"message_id": message_id, "attachment_id": attachment_id})
    existing = await db.mail_intake_log.find_one(query)
    return existing is not None


def should_skip_attachment(filename: str, content_type: str, size_bytes: int) -> tuple:
    """Determine if attachment should be skipped."""
    if content_type and content_type.lower() in SKIP_CONTENT_TYPES:
        return (True, f"Skipped content type: {content_type}")
    if filename:
        for pattern in SKIP_FILENAME_PATTERNS:
            if re.match(pattern, filename.lower()):
                return (True, f"Skipped filename pattern: {filename}")
    max_size = EMAIL_POLLING_MAX_ATTACHMENT_MB * 1024 * 1024
    if size_bytes > max_size:
        return (True, f"Skipped size: {size_bytes / 1024 / 1024:.1f}MB > {EMAIL_POLLING_MAX_ATTACHMENT_MB}MB limit")
    return (False, None)


# =========================================================================
# Polling Functions
# =========================================================================

async def poll_mailbox_for_attachments():
    """
    Passive Graph 'Tap' - READ-ONLY polling.
    Reads inbox, ingests attachments, logs results. No mailbox mutations.
    """
    if not EMAIL_POLLING_ENABLED:
        return {"skipped": True, "reason": "EMAIL_POLLING_ENABLED is false"}
    if not EMAIL_POLLING_USER:
        return {"skipped": True, "reason": "EMAIL_POLLING_USER not configured"}
    if DEMO_MODE:
        return {"skipped": True, "reason": "Demo mode - no real polling"}

    db = get_db()
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
        "errors": [],
    }

    try:
        from services.config_service import get_email_token
        token = await get_email_token()
        if not token:
            stats["errors"].append("Failed to get Email token")
            return stats

        watermark_doc = await db.hub_settings.find_one({"type": "email_poll_watermark"}, {"_id": 0})
        if watermark_doc and watermark_doc.get("last_received_datetime"):
            watermark_time = watermark_doc["last_received_datetime"]
            try:
                watermark_dt = datetime.fromisoformat(watermark_time.replace('Z', '+00:00'))
                buffer_time = (watermark_dt - timedelta(minutes=5)).isoformat()
            except Exception:
                buffer_time = watermark_time
        else:
            buffer_time = (datetime.now(timezone.utc) - timedelta(minutes=EMAIL_POLLING_LOOKBACK_MINUTES)).isoformat()

        filter_query = f"receivedDateTime ge {buffer_time}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            messages_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{EMAIL_POLLING_USER}/mailFolders/Inbox/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": filter_query,
                    "$select": "id,subject,from,receivedDateTime,internetMessageId,hasAttachments",
                    "$top": EMAIL_POLLING_MAX_MESSAGES,
                    "$orderby": "receivedDateTime asc",
                },
            )
            if messages_resp.status_code != 200:
                error_msg = f"Graph API error {messages_resp.status_code}: {messages_resp.text[:200]}"
                logger.error("[EmailPoll:%s] %s", run_id, error_msg)
                stats["errors"].append(error_msg)
                return stats

            messages = messages_resp.json().get("value", [])
            messages_with_attachments = [m for m in messages if m.get("hasAttachments")]
            stats["messages_detected"] = len(messages_with_attachments)
            logger.info("[EmailPoll:%s] Detected %d messages with attachments (out of %d total)",
                        run_id, len(messages_with_attachments), len(messages))

            for msg in messages_with_attachments:
                msg_id = msg["id"]
                internet_msg_id = msg.get("internetMessageId", msg_id)
                subject = msg.get("subject", "No Subject")
                sender = msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")

                try:
                    att_resp = await client.get(
                        f"https://graph.microsoft.com/v1.0/users/{EMAIL_POLLING_USER}/messages/{msg_id}/attachments",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$select": "id,name,contentType,size"},
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

                        skip, skip_reason = should_skip_attachment(filename, content_type, size_bytes)
                        if skip:
                            await record_mail_intake_log(
                                message_id=msg_id, internet_message_id=internet_msg_id,
                                attachment_id=att_id, attachment_hash="",
                                filename=filename, status="SkippedInline", error=skip_reason,
                            )
                            stats["attachments_skipped_inline"] += 1
                            continue

                        try:
                            att_content_resp = await client.get(
                                f"https://graph.microsoft.com/v1.0/users/{EMAIL_POLLING_USER}/messages/{msg_id}/attachments/{att_id}",
                                headers={"Authorization": f"Bearer {token}"},
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

                        try:
                            content_bytes = base64.b64decode(content_b64)
                            att_hash = hashlib.sha256(content_bytes).hexdigest()
                        except Exception as e:
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Failed to decode {filename}: {str(e)}")
                            continue

                        if await check_duplicate_mail_intake(internet_msg_id, att_hash):
                            await record_mail_intake_log(
                                message_id=msg_id, internet_message_id=internet_msg_id,
                                attachment_id=att_id, attachment_hash=att_hash,
                                filename=filename, status="SkippedDuplicate",
                            )
                            stats["attachments_skipped_duplicate"] += 1
                            continue

                        try:
                            # Lazy import to avoid circular dependency
                            from server import _internal_intake_document
                            intake_result = await _internal_intake_document(
                                file_content=content_bytes, filename=filename,
                                content_type=content_type, source="email_poll",
                                email_id=msg_id, subject=subject, sender=sender,
                            )
                            doc_id = intake_result.get("document", {}).get("id")
                            await record_mail_intake_log(
                                message_id=msg_id, internet_message_id=internet_msg_id,
                                attachment_id=att_id, attachment_hash=att_hash,
                                filename=filename, status="Processed", sharepoint_doc_id=doc_id,
                            )
                            stats["attachments_ingested"] += 1
                            logger.info("[EmailPoll:%s] Ingested %s -> doc %s", run_id, filename, doc_id)
                        except Exception as e:
                            await record_mail_intake_log(
                                message_id=msg_id, internet_message_id=internet_msg_id,
                                attachment_id=att_id, attachment_hash=att_hash,
                                filename=filename, status="Error", error=str(e),
                            )
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Intake failed for {filename}: {str(e)}")
                except Exception as e:
                    stats["errors"].append(f"Failed processing message {msg_id}: {str(e)}")

            # Update watermark
            if messages:
                newest_received = max(msg.get("receivedDateTime", "") for msg in messages)
                if newest_received:
                    await db.hub_settings.update_one(
                        {"type": "email_poll_watermark"},
                        {"$set": {"last_received_datetime": newest_received, "updated_utc": datetime.now(timezone.utc).isoformat()}},
                        upsert=True,
                    )
    except Exception as e:
        stats["errors"].append(f"Poll run failed: {str(e)}")
        logger.error("[EmailPoll:%s] Run failed: %s", run_id, str(e))

    stats["ended_at"] = datetime.now(timezone.utc).isoformat()
    stats_to_store = stats.copy()
    await db.mail_poll_runs.insert_one(stats_to_store)

    logger.info(
        "[EmailPoll:%s] Complete: detected=%d, ingested=%d, skipped_dup=%d, skipped_inline=%d, failed=%d",
        run_id, stats["messages_detected"], stats["attachments_ingested"],
        stats["attachments_skipped_duplicate"], stats["attachments_skipped_inline"], stats["attachments_failed"],
    )
    return stats


async def email_polling_worker():
    """Background worker that polls mailbox at configured interval."""
    logger.info("Email polling worker started (interval: %d minutes)", EMAIL_POLLING_INTERVAL_MINUTES)
    while True:
        try:
            config = await get_email_watcher_config()
            interval = config.get("interval_minutes", EMAIL_POLLING_INTERVAL_MINUTES)
            async with _email_polling_lock:
                if config.get("enabled", True) and EMAIL_POLLING_ENABLED:
                    await poll_mailbox_for_attachments()
        except Exception as e:
            logger.error("Email polling worker error: %s", str(e))
        try:
            config = await get_email_watcher_config()
            interval = config.get("interval_minutes", EMAIL_POLLING_INTERVAL_MINUTES)
        except Exception:
            interval = EMAIL_POLLING_INTERVAL_MINUTES
        await asyncio.sleep(interval * 60)


# =========================================================================
# Sales Email Polling
# =========================================================================

async def run_sales_email_poll():
    """Poll the Sales intake mailbox for new documents."""
    from sales_module import (
        ingest_sales_document, check_sales_duplicate, record_sales_mail_log,
    )

    run_id = str(uuid.uuid4())[:8]
    if not SALES_EMAIL_POLLING_USER:
        return {"skipped": True, "reason": "SALES_EMAIL_POLLING_USER not configured"}

    db = get_db()
    stats = {
        "run_id": run_id, "mailbox": SALES_EMAIL_POLLING_USER,
        "messages_detected": 0, "attachments_ingested": 0,
        "attachments_skipped_dup": 0, "attachments_skipped_inline": 0,
        "attachments_failed": 0, "errors": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        logger.info("[SalesPoll:%s] Starting poll for %s", run_id, SALES_EMAIL_POLLING_USER)
        from services.config_service import get_email_token
        token = await get_email_token()
        if not token:
            stats["errors"].append("Failed to get email access token")
            return stats

        lookback = EMAIL_POLLING_LOOKBACK_MINUTES
        buffer_time = (datetime.now(timezone.utc) - timedelta(minutes=lookback)).isoformat()
        filter_query = f"receivedDateTime ge {buffer_time}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            messages_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/mailFolders/Inbox/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": filter_query,
                    "$select": "id,subject,from,receivedDateTime,internetMessageId,hasAttachments,bodyPreview",
                    "$top": EMAIL_POLLING_MAX_MESSAGES,
                    "$orderby": "receivedDateTime asc",
                },
            )
            if messages_resp.status_code != 200:
                stats["errors"].append(f"Graph API error: {messages_resp.status_code}")
                return stats

            messages = messages_resp.json().get("value", [])
            stats["messages_detected"] = len(messages)

            for msg in messages:
                if not msg.get("hasAttachments"):
                    continue
                msg_id = msg.get("id")
                internet_msg_id = msg.get("internetMessageId", msg_id)
                subject = msg.get("subject", "No Subject")
                sender = msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")
                body_preview = msg.get("bodyPreview", "")

                try:
                    att_resp = await client.get(
                        f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/messages/{msg_id}/attachments",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$select": "id,name,contentType,size,isInline"},
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

                        if is_inline or content_type.startswith("image/") or size_bytes < 1000:
                            stats["attachments_skipped_inline"] += 1
                            continue

                        try:
                            att_content_resp = await client.get(
                                f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/messages/{msg_id}/attachments/{att_id}",
                                headers={"Authorization": f"Bearer {token}"},
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

                        is_dup = await check_sales_duplicate(internet_msg_id, content_hash)
                        if is_dup:
                            stats["attachments_skipped_dup"] += 1
                            continue

                        try:
                            result = await ingest_sales_document(
                                file_content=content_bytes, filename=filename,
                                source="email", email_sender=sender, email_subject=subject,
                                email_body=body_preview, email_message_id=internet_msg_id,
                                correlation_id=run_id,
                            )
                            await record_sales_mail_log(
                                message_id=msg_id, internet_message_id=internet_msg_id,
                                attachment_id=att_id, attachment_hash=content_hash,
                                filename=filename, status="Ingested",
                                document_id=result.get("document_id"),
                            )
                            stats["attachments_ingested"] += 1
                            logger.info("[SalesPoll:%s] Ingested: %s -> %s", run_id, filename, result.get("document_type"))
                        except Exception as e:
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Ingestion failed for {filename}: {str(e)}")
                            await record_sales_mail_log(
                                message_id=msg_id, internet_message_id=internet_msg_id,
                                attachment_id=att_id, attachment_hash=content_hash,
                                filename=filename, status="Failed", error=str(e),
                            )
                except Exception as e:
                    stats["errors"].append(f"Error processing message {msg_id}: {str(e)}")

    except Exception as e:
        stats["errors"].append(f"Poll run failed: {str(e)}")
        logger.error("[SalesPoll:%s] Run failed: %s", run_id, str(e))

    stats["completed_at"] = datetime.now(timezone.utc).isoformat()
    stats_to_store = {**stats}
    await db.sales_mail_poll_runs.insert_one(stats_to_store)
    logger.info(
        "[SalesPoll:%s] Complete: detected=%d, ingested=%d, skipped_dup=%d, skipped_inline=%d, failed=%d",
        run_id, stats["messages_detected"], stats["attachments_ingested"],
        stats["attachments_skipped_dup"], stats["attachments_skipped_inline"], stats["attachments_failed"],
    )
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


# =========================================================================
# Unified Mailbox Polling (Dynamic UI-configured mailboxes)
# =========================================================================

async def poll_mailbox_for_documents(mailbox_address: str, default_category: str = "AP", source_id: str = None):
    """Unified mailbox polling function that ingests documents into hub_documents."""
    db = get_db()
    run_id = uuid.uuid4().hex[:8]

    stats = {
        "run_id": run_id, "mailbox": mailbox_address, "source_id": source_id,
        "default_category": default_category, "messages_detected": 0,
        "attachments_ingested": 0, "attachments_skipped_dup": 0,
        "attachments_skipped_inline": 0, "attachments_failed": 0,
        "errors": [], "started_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info("[MailboxPoll:%s] Starting poll for %s (category=%s)", run_id, mailbox_address, default_category)

    try:
        from services.config_service import get_email_token
        token = await get_email_token()
        if not token:
            stats["errors"].append("Failed to get email token")
            return stats

        lookback_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        async with httpx.AsyncClient(timeout=60.0) as client:
            messages_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders/Inbox/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": f"receivedDateTime ge {lookback_time}",
                    "$select": "id,subject,from,receivedDateTime,internetMessageId,hasAttachments,bodyPreview",
                    "$top": 25,
                    "$orderby": "receivedDateTime asc",
                },
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

                att_resp = await client.get(
                    f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{msg_id}/attachments",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"$select": "id,name,contentType,size,isInline"},
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

                    if is_inline or content_type.startswith("image/") or size_bytes < 1000:
                        stats["attachments_skipped_inline"] += 1
                        continue

                    existing = await db.mail_intake_log.find_one({
                        "internet_message_id": internet_msg_id,
                        "attachment_name": filename,
                    })
                    if existing:
                        stats["attachments_skipped_dup"] += 1
                        continue

                    try:
                        att_content_resp = await client.get(
                            f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{msg_id}/attachments/{att_id}",
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        if att_content_resp.status_code != 200:
                            stats["attachments_failed"] += 1
                            continue

                        content_b64 = att_content_resp.json().get("contentBytes", "")
                        content_bytes = base64.b64decode(content_b64)
                        content_hash = hashlib.sha256(content_bytes).hexdigest()

                        hash_dup = await db.hub_documents.find_one(
                            {"sha256_hash": content_hash, "is_duplicate": {"$ne": True}},
                            {"_id": 0, "id": 1},
                        )
                        if hash_dup:
                            await db.mail_intake_log.insert_one({
                                "internet_message_id": internet_msg_id,
                                "attachment_name": filename,
                                "attachment_hash": content_hash,
                                "document_id": hash_dup["id"],
                                "mailbox_source": mailbox_address,
                                "source_id": source_id,
                                "status": "Skipped_Duplicate",
                                "created_utc": datetime.now(timezone.utc).isoformat(),
                            })
                            stats["attachments_skipped_dup"] += 1
                            continue

                        # Lazy import to avoid circular dependency
                        from server import _internal_intake_document
                        result = await _internal_intake_document(
                            file_content=content_bytes, filename=filename,
                            source="email", sender=sender, subject=subject,
                            email_id=internet_msg_id, content_type=content_type,
                        )

                        await db.mail_intake_log.insert_one({
                            "internet_message_id": internet_msg_id,
                            "attachment_name": filename,
                            "attachment_hash": content_hash,
                            "document_id": result.get("document_id"),
                            "mailbox_source": mailbox_address,
                            "source_id": source_id,
                            "status": "Ingested",
                            "created_utc": datetime.now(timezone.utc).isoformat(),
                        })
                        stats["attachments_ingested"] += 1

                    except Exception as e:
                        stats["attachments_failed"] += 1
                        stats["errors"].append(f"Failed to process {filename}: {str(e)}")

    except Exception as e:
        stats["errors"].append(f"Poll error: {str(e)}")
        logger.error("[MailboxPoll:%s] Error: %s", run_id, str(e))

    stats["completed_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(
        "[MailboxPoll:%s] Complete: ingested=%d, skipped_dup=%d, failed=%d",
        run_id, stats["attachments_ingested"], stats["attachments_skipped_dup"], stats["attachments_failed"],
    )
    return stats


async def dynamic_mailbox_polling_worker():
    """Background worker that polls all enabled mailbox sources from the database."""
    global _mailbox_last_poll_times
    logger.info("[DynamicMailboxWorker] Starting dynamic mailbox polling worker")
    await asyncio.sleep(30)

    while True:
        try:
            db = get_db()
            mailbox_sources = await db.mailbox_sources.find({"enabled": True}, {"_id": 0}).to_list(100)
            now = datetime.now(timezone.utc)

            for mailbox in mailbox_sources:
                mailbox_id = mailbox.get("mailbox_id")
                email_address = mailbox.get("email_address")
                interval_minutes = mailbox.get("polling_interval_minutes", 5)
                category = mailbox.get("category", "AP")
                if not email_address:
                    continue

                last_poll = _mailbox_last_poll_times.get(mailbox_id)
                if last_poll:
                    elapsed = (now - last_poll).total_seconds() / 60
                    if elapsed < interval_minutes:
                        continue

                logger.info("[DynamicMailboxWorker] Polling %s (%s)", mailbox.get("name"), email_address)
                try:
                    await poll_mailbox_for_documents(
                        mailbox_address=email_address,
                        default_category=category,
                        source_id=mailbox_id,
                    )
                    _mailbox_last_poll_times[mailbox_id] = now
                except Exception as e:
                    logger.error("[DynamicMailboxWorker] Error polling %s: %s", email_address, str(e))

            await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info("[DynamicMailboxWorker] Polling worker cancelled")
            break
        except Exception as e:
            logger.error("[DynamicMailboxWorker] Worker error: %s", str(e))
            await asyncio.sleep(60)
