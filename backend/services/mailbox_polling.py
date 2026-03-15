"""
GPI Document Hub - Mailbox Polling Service

Email polling orchestration: poll Graph API, extract attachments,
deduplicate, and hand off to the intake pipeline.
Extracted from server.py during Final Orchestration Extraction pass.

Dependencies:
  - deps: get_db()
  - services.graph_access: get_email_token()
  - server._internal_intake_document: core intake pipeline (next extraction target)
"""

import base64
import hashlib
import logging
import uuid
from datetime import datetime, timezone, timedelta

import httpx

import deps
from services.graph_access import get_email_token

logger = logging.getLogger(__name__)


async def poll_mailbox_for_documents(mailbox_address: str, default_category: str = "AP", source_id: str = None):
    """
    Unified mailbox polling function that ingests documents into the main hub_documents collection.
    """
    run_id = uuid.uuid4().hex[:8]
    db = deps.get_db()

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

                        # Ingest through unified pipeline (remains in server.py)
                        import server
                        result = await server._internal_intake_document(
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
