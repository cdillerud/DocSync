"""
Job type configuration + email watcher settings endpoints.

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 12). No logic changed.
"""
import logging
from fastapi import APIRouter, HTTPException, Query

from core.db import db
from core.job_config import DEFAULT_JOB_TYPES, JobTypeConfig, EmailWatchConfig
from services.email_polling_engine import get_email_watcher_config, subscribe_to_mailbox_notifications

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

@router.get("/settings/job-types")
async def get_job_types():
    """Get all job type configurations."""
    job_types = await db.hub_job_types.find({}, {"_id": 0}).to_list(100)
    
    # Merge with defaults for any missing types
    result = dict(DEFAULT_JOB_TYPES)
    for jt in job_types:
        result[jt["job_type"]] = jt
    
    return {"job_types": list(result.values())}

@router.get("/settings/job-types/{job_type}")
async def get_job_type(job_type: str):
    """Get a specific job type configuration."""
    jt = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
    if not jt:
        jt = DEFAULT_JOB_TYPES.get(job_type)
        if not jt:
            raise HTTPException(status_code=404, detail="Job type not found")
    return jt

@router.put("/settings/job-types/{job_type}")
async def update_job_type(job_type: str, config: JobTypeConfig):
    """Update a job type configuration."""
    update_data = config.model_dump()
    update_data["job_type"] = job_type
    
    await db.hub_job_types.update_one(
        {"job_type": job_type},
        {"$set": update_data},
        upsert=True
    )
    
    return await get_job_type(job_type)

@router.get("/settings/email-watcher")
async def get_email_watcher_settings():
    """Get email watcher configuration."""
    return await get_email_watcher_config()

@router.put("/settings/email-watcher")
async def update_email_watcher_settings(config: EmailWatchConfig):
    """Update email watcher configuration."""
    update_data = config.model_dump()
    update_data["_key"] = "email_watcher"
    
    logger.info("Saving email watcher config: %s", update_data)
    
    result = await db.hub_config.update_one(
        {"_key": "email_watcher"},
        {"$set": update_data},
        upsert=True
    )
    
    logger.info("MongoDB update result: matched=%s, modified=%s", result.matched_count, result.modified_count)
    
    return await get_email_watcher_config()

@router.post("/settings/email-watcher/subscribe")
async def subscribe_email_watcher(webhook_url: str = Query(...)):
    """Create Graph subscription for email notifications."""
    config = await get_email_watcher_config()
    
    if not config.get("mailbox_address"):
        raise HTTPException(status_code=400, detail="Mailbox address not configured")
    
    result = await subscribe_to_mailbox_notifications(config["mailbox_address"], webhook_url)
    
    if result.get("status") == "ok":
        await db.hub_config.update_one(
            {"_key": "email_watcher"},
            {"$set": {
                "webhook_subscription_id": result.get("subscription_id"),
                "webhook_expiration": result.get("expiration")
            }}
        )
    
    return result
