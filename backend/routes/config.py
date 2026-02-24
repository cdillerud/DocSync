"""
GPI Document Hub - Config Router

System settings, mailbox sources, and configuration.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid

router = APIRouter(prefix="/config", tags=["config"])

# Database - set by main app
db = None

def set_db(database):
    global db
    db = database


# ==================== MODELS ====================

class MailboxSource(BaseModel):
    name: str
    email_address: str
    category: str = "AP"  # AP, Sales, Operations
    enabled: bool = True
    poll_interval_minutes: int = 15


class SystemConfig(BaseModel):
    demo_mode: bool = True
    auto_classification: bool = True
    auto_workflow: bool = True
    email_polling_enabled: bool = True


# ==================== MAILBOX SOURCES ====================

@router.get("/mailboxes")
async def list_mailboxes():
    """List all configured mailbox sources."""
    mailboxes = await db.mailbox_sources.find({}, {"_id": 0}).to_list(50)
    return {"mailboxes": mailboxes}


@router.get("/mailboxes/{mailbox_id}")
async def get_mailbox(mailbox_id: str):
    """Get a single mailbox configuration."""
    mailbox = await db.mailbox_sources.find_one({"id": mailbox_id}, {"_id": 0})
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    return mailbox


@router.post("/mailboxes")
async def create_mailbox(source: MailboxSource):
    """Create a new mailbox source."""
    mailbox_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    mailbox = {
        "id": mailbox_id,
        **source.model_dump(),
        "last_poll_utc": None,
        "documents_ingested": 0,
        "created_utc": now,
        "updated_utc": now
    }
    
    await db.mailbox_sources.insert_one(mailbox)
    mailbox.pop("_id", None)
    
    return mailbox


@router.put("/mailboxes/{mailbox_id}")
async def update_mailbox(mailbox_id: str, source: MailboxSource):
    """Update a mailbox configuration."""
    existing = await db.mailbox_sources.find_one({"id": mailbox_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    
    update = {
        **source.model_dump(),
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }
    
    await db.mailbox_sources.update_one({"id": mailbox_id}, {"$set": update})
    
    updated = await db.mailbox_sources.find_one({"id": mailbox_id}, {"_id": 0})
    return updated


@router.delete("/mailboxes/{mailbox_id}")
async def delete_mailbox(mailbox_id: str):
    """Delete a mailbox source."""
    result = await db.mailbox_sources.delete_one({"id": mailbox_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    
    return {"message": "Mailbox deleted", "id": mailbox_id}


@router.post("/mailboxes/{mailbox_id}/poll")
async def trigger_mailbox_poll(mailbox_id: str):
    """Manually trigger a mailbox poll."""
    mailbox = await db.mailbox_sources.find_one({"id": mailbox_id}, {"_id": 0})
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    
    # This would trigger the actual polling
    # For now, return acknowledgment
    return {
        "message": "Poll triggered",
        "mailbox_id": mailbox_id,
        "email": mailbox.get("email_address")
    }


# ==================== VENDOR ALIASES ====================

@router.get("/vendor-aliases")
async def list_vendor_aliases():
    """List all vendor aliases."""
    aliases = await db.vendor_aliases.find({}, {"_id": 0}).to_list(500)
    return {"aliases": aliases}


@router.post("/vendor-aliases")
async def create_vendor_alias(
    alias_string: str,
    canonical_vendor_no: str,
    canonical_vendor_name: str
):
    """Create a new vendor alias."""
    alias_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # Check if alias already exists
    existing = await db.vendor_aliases.find_one(
        {"alias_string": {"$regex": f"^{alias_string}$", "$options": "i"}}
    )
    if existing:
        raise HTTPException(status_code=400, detail="Alias already exists")
    
    alias = {
        "id": alias_id,
        "alias_string": alias_string,
        "alias_normalized": alias_string.lower().strip(),
        "canonical_vendor_no": canonical_vendor_no,
        "canonical_vendor_name": canonical_vendor_name,
        "usage_count": 0,
        "created_utc": now,
        "updated_utc": now
    }
    
    await db.vendor_aliases.insert_one(alias)
    alias.pop("_id", None)
    
    return alias


@router.delete("/vendor-aliases/{alias_id}")
async def delete_vendor_alias(alias_id: str):
    """Delete a vendor alias."""
    result = await db.vendor_aliases.delete_one({"id": alias_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Alias not found")
    
    return {"message": "Alias deleted", "id": alias_id}


# ==================== SYSTEM CONFIG ====================

@router.get("/system")
async def get_system_config():
    """Get system configuration."""
    config = await db.hub_config.find_one({"type": "system"}, {"_id": 0})
    
    if not config:
        # Return defaults
        return {
            "demo_mode": True,
            "auto_classification": True,
            "auto_workflow": True,
            "email_polling_enabled": True
        }
    
    return config


@router.put("/system")
async def update_system_config(config: SystemConfig):
    """Update system configuration."""
    now = datetime.now(timezone.utc).isoformat()
    
    update = {
        "type": "system",
        **config.model_dump(),
        "updated_utc": now
    }
    
    await db.hub_config.update_one(
        {"type": "system"},
        {"$set": update},
        upsert=True
    )
    
    return update


@router.get("/health")
async def health_check():
    """System health check."""
    try:
        # Check DB connection
        await db.command("ping")
        db_status = "healthy"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "database": db_status,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
