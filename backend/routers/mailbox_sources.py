"""GPI Document Hub - Mailbox Sources Router (Domain 3)

Extracted from server.py. Manages mailbox source CRUD and polling operations.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings/mailbox-sources", tags=["Mailbox Sources"])


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


@router.get("")
async def list_mailbox_sources():
    """Get all configured mailbox sources."""
    db = get_db()
    sources = await db.mailbox_sources.find({}, {"_id": 0}).to_list(100)
    return {"mailbox_sources": sources, "total": len(sources)}


@router.get("/polling-status")
async def get_mailbox_polling_status():
    """Get the status of the dynamic mailbox polling worker."""
    import server
    from deps import EMAIL_POLLING_ENABLED, SALES_EMAIL_POLLING_ENABLED

    db = get_db()
    task = server._dynamic_mailbox_polling_task
    poll_times = server._mailbox_last_poll_times

    worker_running = task is not None and not task.done()

    sources = await db.mailbox_sources.find({}, {"_id": 0}).to_list(100)

    mailbox_statuses = []
    for source in sources:
        mailbox_id = source.get("mailbox_id")
        last_poll = poll_times.get(mailbox_id)

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


@router.get("/{mailbox_id}")
async def get_mailbox_source(mailbox_id: str):
    """Get a specific mailbox source by ID."""
    db = get_db()
    source = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id}, {"_id": 0})
    if not source:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")
    return source


@router.post("")
async def create_mailbox_source(source: MailboxSource):
    """Create a new mailbox source."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    mailbox_id = source.mailbox_id or f"mailbox_{uuid.uuid4().hex[:8]}"

    existing = await db.mailbox_sources.find_one({"email_address": source.email_address})
    if existing:
        raise HTTPException(status_code=400, detail=f"Mailbox {source.email_address} already exists")

    doc = source.model_dump()
    doc["mailbox_id"] = mailbox_id
    doc["created_utc"] = now
    doc["updated_utc"] = now

    await db.mailbox_sources.insert_one(doc)

    logger.info("Created mailbox source: %s (%s)", source.name, source.email_address)

    return await get_mailbox_source(mailbox_id)


@router.put("/{mailbox_id}")
async def update_mailbox_source(mailbox_id: str, source: MailboxSource):
    """Update an existing mailbox source."""
    db = get_db()
    existing = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    update_data = source.model_dump()
    update_data["mailbox_id"] = mailbox_id
    update_data["created_utc"] = existing.get("created_utc")
    update_data["updated_utc"] = now

    await db.mailbox_sources.update_one(
        {"mailbox_id": mailbox_id},
        {"$set": update_data}
    )

    logger.info("Updated mailbox source: %s", mailbox_id)

    return await get_mailbox_source(mailbox_id)


@router.delete("/{mailbox_id}")
async def delete_mailbox_source(mailbox_id: str):
    """Delete a mailbox source."""
    db = get_db()
    existing = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")

    await db.mailbox_sources.delete_one({"mailbox_id": mailbox_id})

    logger.info("Deleted mailbox source: %s (%s)", existing.get("name"), existing.get("email_address"))

    return {"status": "deleted", "mailbox_id": mailbox_id}


@router.post("/{mailbox_id}/test-connection")
async def test_mailbox_connection(mailbox_id: str):
    """Test connection to a mailbox source."""
    from services.config_service import get_email_token

    db = get_db()
    source = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id}, {"_id": 0})
    if not source:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")

    email_address = source.get("email_address")

    try:
        token = await get_email_token()
        if not token:
            return {"status": "error", "message": "Failed to get email token - check Graph API credentials"}

        async with httpx.AsyncClient(timeout=30.0) as client:
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


@router.post("/{mailbox_id}/poll-now")
async def poll_mailbox_now(mailbox_id: str):
    """Manually trigger polling for a specific mailbox."""
    from server import poll_mailbox_for_documents

    db = get_db()
    source = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id}, {"_id": 0})
    if not source:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")

    email_address = source.get("email_address")
    category = source.get("category", "AP")

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
