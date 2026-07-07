"""
Mailbox source CRUD + test-connection + manual poll-now endpoints.

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 17). No logic changed.

NOTE: GET /settings/mailbox-sources/polling-status is NOT here - it reads
_dynamic_mailbox_polling_task/_mailbox_last_poll_times, module-level globals
tied to the background worker's lifecycle in server.py (same category as
_email_polling_task kept there in Group 10). Left in server.py for now
rather than relocating those globals under time pressure - flagged in
MIGRATION_PROGRESS.md as a known gap to close later, not a functional risk.
"""
import uuid
import logging
import httpx
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException

from core.db import db
from core.job_config import MailboxSource
from core.legacy_hub_helpers import get_email_token
from services.mailbox_polling_engine import poll_mailbox_for_documents

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

@router.get("/settings/mailbox-sources")
async def list_mailbox_sources():
    """Get all configured mailbox sources."""
    sources = await db.mailbox_sources.find({}, {"_id": 0}).to_list(100)
    return {"mailbox_sources": sources, "total": len(sources)}


@router.get("/settings/mailbox-sources/{mailbox_id}")
async def get_mailbox_source(mailbox_id: str):
    """Get a specific mailbox source by ID."""
    source = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id}, {"_id": 0})
    if not source:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")
    return source

@router.post("/settings/mailbox-sources")
async def create_mailbox_source(source: MailboxSource):
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
    """Delete a mailbox source."""
    existing = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")
    
    await db.mailbox_sources.delete_one({"mailbox_id": mailbox_id})
    
    logger.info("Deleted mailbox source: %s (%s)", existing.get("name"), existing.get("email_address"))
    
    return {"status": "deleted", "mailbox_id": mailbox_id}

@router.post("/settings/mailbox-sources/{mailbox_id}/test-connection")
async def test_mailbox_connection(mailbox_id: str):
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
