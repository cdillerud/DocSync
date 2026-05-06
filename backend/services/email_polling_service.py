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
# Mailbox category normalization
# =========================================================================
# Source-lane synonyms — keep mapping conservative. We only normalize known
# aliases; anything else is passed through verbatim with a warning so the
# operator can see whether mailbox_sources has a typo or a new lane that
# downstream code does not yet handle. ``mailbox_category`` represents the
# intake LANE the document arrived through; it is NOT a forced doc_type.
_MAILBOX_CATEGORY_ALIASES = {
    "BILLING": "AP",
    "ACCOUNTS PAYABLE": "AP",
    "ACCOUNTS_PAYABLE": "AP",
    "AP_INTAKE": "AP",
    "AP": "AP",
    "AR": "Sales",
    "ACCOUNTS RECEIVABLE": "Sales",
    "ACCOUNTS_RECEIVABLE": "Sales",
    "SALES": "Sales",
    "PURCHASE": "Purchase",
    "PURCHASING": "Purchase",
    "PO": "Purchase",
    "OPERATIONS": "Operations",
    "OPS": "Operations",
    "WAREHOUSE": "Operations",
    "SHIPPING": "Operations",
}

_KNOWN_CATEGORIES = {"AP", "Sales", "Purchase", "Operations"}


def normalize_mailbox_category(raw: Optional[str]) -> Optional[str]:
    """Normalize a mailbox-source category value.

    Maps known synonyms (Billing → AP, AR → Sales, etc.) so downstream code
    sees a stable canonical lane name regardless of how the operator spelled
    it in ``mailbox_sources``. Unknown values pass through unchanged but are
    logged at WARNING level so misconfigurations surface immediately.
    """
    if raw is None:
        return None
    key = str(raw).strip()
    if not key:
        return None
    canon = _MAILBOX_CATEGORY_ALIASES.get(key.upper())
    if canon:
        return canon
    if key in _KNOWN_CATEGORIES:
        return key
    logger.warning(
        "[MailboxCategory] Unknown mailbox category %r encountered; "
        "passing through verbatim. Add an alias in normalize_mailbox_category "
        "or fix the mailbox_sources record if this is a typo.",
        raw,
    )
    return key


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

async def ensure_mail_intake_indexes():
    """Create idempotency indexes on mail_intake_log. Safe to call repeatedly.

    The unique `(internet_message_id, attachment_hash)` index is the
    ultimate backstop against concurrent-poller dup inserts — writes that
    collide raise DuplicateKeyError which callers treat as "already seen".
    The partial filter skips rows missing either field so legacy/skipped
    entries don't fight the index.
    """
    db = get_db()
    try:
        await db.mail_intake_log.create_index(
            [("internet_message_id", 1), ("attachment_hash", 1)],
            unique=True,
            partialFilterExpression={
                "internet_message_id": {"$type": "string", "$gt": ""},
                "attachment_hash": {"$type": "string", "$gt": ""},
            },
            name="uniq_msgid_hash",
        )
    except Exception as e:  # noqa: BLE001 — collection may predate fix
        logger.warning("ensure_mail_intake_indexes: uniq_msgid_hash failed: %s", e)
    # Lookup indexes used by check_duplicate_mail_intake fallback paths.
    for keys, name in (
        ([("internet_message_id", 1), ("filename", 1)], "msgid_filename"),
        ([("internet_message_id", 1), ("attachment_name", 1)], "msgid_attname"),
        ([("attachment_hash", 1), ("status", 1)], "hash_status"),
    ):
        try:
            await db.mail_intake_log.create_index(keys, name=name)
        except Exception as e:  # noqa: BLE001
            logger.debug("ensure_mail_intake_indexes: %s failed: %s", name, e)


# Statuses that prove we actually ingested (vs. skipped inline / error).
_PROCESSED_STATUSES = ("Processed", "Ingested", "SkippedDuplicate", "Skipped_Duplicate")


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
    """Record mail intake for idempotency and observability.

    Writes BOTH `filename` and `attachment_name` so the other
    (dynamic mailbox) poller can dedup against our rows and vice versa.
    DuplicateKeyError from the unique index is swallowed — that just
    means another worker already recorded this exact attachment.
    """
    db = get_db()
    log_entry = {
        "id": str(uuid.uuid4()),
        "message_id": message_id,
        "internet_message_id": internet_message_id,
        "attachment_id": attachment_id,
        "attachment_hash": attachment_hash,
        "filename": filename,
        "attachment_name": filename,  # schema-unify with dynamic poller
        "status": status,
        "sharepoint_doc_id": sharepoint_doc_id,
        "error": error,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await db.mail_intake_log.insert_one(log_entry)
    except Exception as e:  # noqa: BLE001
        # DuplicateKeyError → another worker already recorded this one.
        if "DuplicateKey" in type(e).__name__ or "E11000" in str(e):
            logger.info(
                "record_mail_intake_log: dedup hit on uniq index for %s (%s)",
                filename, (attachment_hash or "")[:12],
            )
        else:
            raise
    return log_entry


async def check_duplicate_mail_intake(
    internet_message_id: str, attachment_hash: str,
    message_id: str = None, attachment_id: str = None,
    filename: str = None,
) -> bool:
    """Check if this attachment was already processed (idempotency).

    Matches across BOTH legacy schemas (static poller wrote `filename`,
    dynamic poller wrote `attachment_name`) so cross-worker ingestion
    correctly dedups. Hash-based match is primary and sufficient on its
    own even if filename differs.
    """
    db = get_db()
    clauses = []
    if internet_message_id and attachment_hash:
        clauses.append({
            "internet_message_id": internet_message_id,
            "attachment_hash": attachment_hash,
        })
    if message_id and attachment_id:
        clauses.append({"message_id": message_id, "attachment_id": attachment_id})
    if internet_message_id and filename:
        # Catch legacy rows that lack hash (e.g. inline-skipped)
        clauses.append({"internet_message_id": internet_message_id, "filename": filename})
        clauses.append({"internet_message_id": internet_message_id, "attachment_name": filename})
    # Global hash-only fallback: same content already ingested from a
    # different message (e.g. same attachment forwarded twice).
    if attachment_hash:
        clauses.append({
            "attachment_hash": attachment_hash,
            "status": {"$in": list(_PROCESSED_STATUSES)},
        })
    if not clauses:
        return False
    query = clauses[0] if len(clauses) == 1 else {"$or": clauses}
    existing = await db.mail_intake_log.find_one(query, {"_id": 0, "id": 1})
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

        # Strict cursor: receivedDateTime gt watermark_time (no 5-min back-buffer).
        # The 5-minute back-buffer combined with $top=25 + asc-order created an
        # infinite-loop trap: when 25+ messages exist inside a 5-minute window,
        # max(batch.receivedDateTime) == current watermark, so the watermark
        # never advanced and the same 25 messages were re-fetched forever.
        # See: hub-ap-intake@gamerpackaging.com, stuck at 2026-04-09T21:02:12Z.
        watermark_doc = await db.hub_settings.find_one({"type": "email_poll_watermark"}, {"_id": 0})
        if watermark_doc and watermark_doc.get("last_received_datetime"):
            watermark_time = watermark_doc["last_received_datetime"]
        else:
            watermark_time = (datetime.now(timezone.utc) - timedelta(minutes=EMAIL_POLLING_LOOKBACK_MINUTES)).isoformat()

        filter_query = f"receivedDateTime gt {watermark_time}"
        stats["watermark_in"] = watermark_time

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

                        if await check_duplicate_mail_intake(
                            internet_msg_id, att_hash, filename=filename,
                        ):
                            await record_mail_intake_log(
                                message_id=msg_id, internet_message_id=internet_msg_id,
                                attachment_id=att_id, attachment_hash=att_hash,
                                filename=filename, status="SkippedDuplicate",
                            )
                            stats["attachments_skipped_duplicate"] += 1
                            continue

                        try:
                            # Lazy import to avoid circular dependency
                            from services.document_handlers import intake_document_from_bytes
                            resolved_category = normalize_mailbox_category("AP")
                            logger.info(
                                "[Intake:legacy_ap] mailbox=%s configured_category=%s resolved_category=%s filename=%s",
                                EMAIL_POLLING_USER, "AP", resolved_category, filename,
                            )
                            intake_result = await intake_document_from_bytes(
                                file_content=content_bytes, filename=filename,
                                content_type=content_type, source="email_poll",
                                email_id=msg_id, subject=subject, sender=sender,
                                mailbox_category=resolved_category,
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

            # Update watermark with stalled-watermark protection.
            # Strict gt-cursor semantics: watermark must STRICTLY advance. If the
            # entire batch is duplicates AND max(receivedDateTime) <= current
            # watermark, that means the upstream filter is paginating on equality
            # — record stalled_watermark so it surfaces visibly instead of silent
            # infinite looping. With strict `gt` filtering this should not happen
            # in practice, but we audit it as a defense-in-depth canary.
            if messages:
                newest_received = max(msg.get("receivedDateTime", "") for msg in messages)
                if newest_received and newest_received > watermark_time:
                    await db.hub_settings.update_one(
                        {"type": "email_poll_watermark"},
                        {"$set": {"last_received_datetime": newest_received, "updated_utc": datetime.now(timezone.utc).isoformat()}},
                        upsert=True,
                    )
                    stats["watermark_out"] = newest_received
                    stats["watermark_advanced"] = True
                else:
                    # Watermark could not advance — duplicates blocking forward progress.
                    stats["watermark_out"] = watermark_time
                    stats["watermark_advanced"] = False
                    stats["stalled_watermark"] = {
                        "mailbox": EMAIL_POLLING_USER,
                        "watermark_in": watermark_time,
                        "max_seen": newest_received,
                        "batch_size": len(messages),
                        "duplicates": stats["attachments_skipped_duplicate"],
                        "ingested": stats["attachments_ingested"],
                    }
                    logger.warning(
                        "[EmailPoll:%s] STALLED WATERMARK mailbox=%s watermark=%s max_seen=%s batch=%d duplicates=%d",
                        run_id, EMAIL_POLLING_USER, watermark_time, newest_received,
                        len(messages), stats["attachments_skipped_duplicate"],
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
        "status": "running", "graph_http_status": None,
    }

    logger.info("[MailboxPoll:%s] Starting poll for %s (category=%s)", run_id, mailbox_address, default_category)

    try:
        from services.config_service import get_email_token
        token = await get_email_token()
        if not token:
            stats["errors"].append("Failed to get email token")
            stats["status"] = "failed_token"
        else:
            # Per-mailbox watermark — keeps us from re-examining the same 1h
            # window every 60 seconds (root cause of the 10×/day dup bug).
            watermark_key = f"mailbox_watermark:{mailbox_address}"
            wm_doc = await db.hub_settings.find_one({"type": watermark_key}, {"_id": 0})
            if wm_doc and wm_doc.get("last_received_datetime"):
                try:
                    wm_dt = datetime.fromisoformat(
                        wm_doc["last_received_datetime"].replace("Z", "+00:00")
                    )
                    lookback_time = (wm_dt - timedelta(minutes=5)).isoformat()
                except Exception:
                    lookback_time = wm_doc["last_received_datetime"]
            else:
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
                stats["graph_http_status"] = messages_resp.status_code
                if messages_resp.status_code != 200:
                    body_excerpt = (messages_resp.text or "")[:500]
                    stats["errors"].append(
                        f"Graph API error: HTTP {messages_resp.status_code} body={body_excerpt}"
                    )
                    stats["status"] = "failed_graph"
                else:
                    stats["status"] = "ok"
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

                                # ── Unified dedup ─────────────────────────────
                                # Hash-first: catches the same file from the same
                                # message AND the same content forwarded twice.
                                # Also matches rows written by the static AP
                                # poller (cross-worker protection).
                                if await check_duplicate_mail_intake(
                                    internet_msg_id, content_hash, filename=filename,
                                ):
                                    await record_mail_intake_log(
                                        message_id=msg_id,
                                        internet_message_id=internet_msg_id,
                                        attachment_id=att_id,
                                        attachment_hash=content_hash,
                                        filename=filename,
                                        status="SkippedDuplicate",
                                    )
                                    stats["attachments_skipped_dup"] += 1
                                    continue

                                hash_dup = await db.hub_documents.find_one(
                                    {"sha256_hash": content_hash, "is_duplicate": {"$ne": True}},
                                    {"_id": 0, "id": 1},
                                )
                                if hash_dup:
                                    await record_mail_intake_log(
                                        message_id=msg_id,
                                        internet_message_id=internet_msg_id,
                                        attachment_id=att_id,
                                        attachment_hash=content_hash,
                                        filename=filename,
                                        status="SkippedDuplicate",
                                        sharepoint_doc_id=hash_dup["id"],
                                    )
                                    stats["attachments_skipped_dup"] += 1
                                    continue

                                # Lazy import to avoid circular dependency
                                from services.document_handlers import intake_document_from_bytes
                                resolved_category = normalize_mailbox_category(default_category)
                                logger.info(
                                    "[Intake:dynamic] mailbox_id=%s mailbox=%s configured_category=%s resolved_category=%s filename=%s",
                                    source_id, mailbox_address, default_category, resolved_category, filename,
                                )
                                result = await intake_document_from_bytes(
                                    file_content=content_bytes, filename=filename,
                                    source="email", sender=sender, subject=subject,
                                    email_id=internet_msg_id, content_type=content_type,
                                    mailbox_category=resolved_category,
                                )

                                doc_id = (
                                    result.get("document_id")
                                    or result.get("document", {}).get("id")
                                )
                                await record_mail_intake_log(
                                    message_id=msg_id,
                                    internet_message_id=internet_msg_id,
                                    attachment_id=att_id,
                                    attachment_hash=content_hash,
                                    filename=filename,
                                    status="Processed",
                                    sharepoint_doc_id=doc_id,
                                )
                                stats["attachments_ingested"] += 1

                            except Exception as e:
                                stats["attachments_failed"] += 1
                                stats["errors"].append(f"Failed to process {filename}: {str(e)}")

                    # Advance per-mailbox watermark so we don't replay the same
                    # 1-hour window every minute.
                    if messages:
                        newest_received = max(m.get("receivedDateTime", "") for m in messages)
                        if newest_received:
                            await db.hub_settings.update_one(
                                {"type": watermark_key},
                                {"$set": {
                                    "last_received_datetime": newest_received,
                                    "mailbox_address": mailbox_address,
                                    "updated_utc": datetime.now(timezone.utc).isoformat(),
                                }},
                                upsert=True,
                            )

    except Exception as e:
        stats["errors"].append(f"Poll error: {str(e)}")
        stats["status"] = "failed_exception"
        logger.error("[MailboxPoll:%s] Error: %s", run_id, str(e))

    stats["completed_at"] = datetime.now(timezone.utc).isoformat()

    # Persist EVERY poll (success or failure) so silent swallow can't
    # happen again. Cutover-readiness probes rely on this audit trail.
    try:
        await db.mail_poll_runs.insert_one({k: v for k, v in stats.items()})
    except Exception as e:  # noqa: BLE001 — audit trail must not break poll loop
        logger.error("[MailboxPoll:%s] Failed to persist run stats: %s", run_id, str(e))

    if stats["status"] == "ok":
        logger.info(
            "[MailboxPoll:%s] Complete: mailbox=%s category=%s ingested=%d skipped_dup=%d failed=%d",
            run_id, mailbox_address, default_category,
            stats["attachments_ingested"], stats["attachments_skipped_dup"], stats["attachments_failed"],
        )
    else:
        logger.error(
            "[MailboxPoll:%s] FAILED: mailbox=%s category=%s status=%s graph_http=%s errors=%s",
            run_id, mailbox_address, default_category, stats["status"],
            stats["graph_http_status"], stats["errors"][:3],
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
