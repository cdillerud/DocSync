"""GPI Document Hub - Admin Router"""

import uuid
import logging
from fastapi import APIRouter, HTTPException, Body, Query, BackgroundTasks
from datetime import datetime, timezone
from deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/backfill-ap-mailbox")
async def backfill_ap_mailbox(
    background_tasks: BackgroundTasks,
    days_back: int = Query(7, description="How many days back to search"),
    max_messages: int = Query(25, description="Maximum messages to process"),
    dry_run: bool = Query(False, description="If true, only report what would be processed"),
    mailbox: str = Query(None, description="Mailbox to poll (defaults to EMAIL_POLLING_USER)")
):
    """Backfill AP documents from email mailbox."""
    from services.email_service import get_email_service
    email_service = get_email_service()
    if not email_service:
        raise HTTPException(status_code=503, detail="Email service not initialized")
    result = await email_service.poll_ap_mailbox(
        days_back=days_back, max_messages=max_messages, dry_run=dry_run, mailbox=mailbox
    )
    return result


@router.post("/backfill-sales-mailbox")
async def backfill_sales_mailbox(
    background_tasks: BackgroundTasks,
    days_back: int = Query(30, description="How many days back to search"),
    max_messages: int = Query(50, description="Maximum messages to process"),
    dry_run: bool = Query(False, description="If true, only report what would be processed")
):
    """Backfill sales documents from email mailbox."""
    from services.email_service import get_email_service
    email_service = get_email_service()
    if not email_service:
        raise HTTPException(status_code=503, detail="Email service not initialized")
    result = await email_service.poll_sales_mailbox(
        days_back=days_back, max_messages=max_messages, dry_run=dry_run
    )
    return result


@router.post("/migrate-sales-to-unified")
async def migrate_sales_documents_to_unified():
    """
    One-time migration to move sales_documents into the main hub_documents collection.
    Documents from sales_documents will be copied to hub_documents with category='Sales'.
    Duplicates (by document_id) will be skipped.
    """
    db = get_db()
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
        sales_docs = await db.sales_documents.find({}, {"_id": 0}).to_list(1000)
        stats["sales_documents_found"] = len(sales_docs)
        logger.info("[Migration:%s] Found %d sales documents to migrate", run_id, len(sales_docs))

        for sdoc in sales_docs:
            doc_id = sdoc.get("document_id")
            existing = await db.hub_documents.find_one({"id": doc_id})
            if existing:
                stats["skipped_duplicate"] += 1
                continue

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
                "document_type": sdoc.get("document_type"),
                "category": "Sales",
                "suggested_job_type": sdoc.get("document_type"),
                "ai_confidence": sdoc.get("ai_confidence"),
                "extracted_fields": sdoc.get("extracted_fields", {}),
                "status": sdoc.get("status", "NeedsReview"),
                "workflow_state": sdoc.get("workflow_state", "Classified"),
                "created_utc": sdoc.get("created_utc", now),
                "updated_utc": now,
                "migrated_from": "sales_documents",
                "migrated_at": now,
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
    except Exception as e:
        stats["errors"].append(f"Migration error: {str(e)}")
        logger.error("[Migration:%s] Error: %s", run_id, str(e))

    return stats
