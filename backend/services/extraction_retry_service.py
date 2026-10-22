"""Retry AI field extraction for recent documents that came out empty.

On 2026-09-21/22 an exhausted AI budget made extraction fail for 205 AP
documents; intake finalized them as Completed/Unknown with no invoice
number, amount or vendor, and nothing retried them. This sweep finds
recent AP-lane documents with nothing extracted and reprocesses them
(document_reprocess_service.reprocess_document, reclassify=True), which is
idempotent: no SharePoint re-upload, no BC records. Each document is tried
at most MAX_ATTEMPTS times; the sweep stops early when extraction keeps
failing (the provider is still down).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
STOP_AFTER_CONSECUTIVE_EMPTY = 5


def _has_extraction(fields) -> bool:
    """Any AI-extracted value. Keys starting with "_" are added later by PO
    resolution (_po_all_candidates), so they do not count: 162 of the 205
    outage documents carried only those."""
    return any(v not in (None, "", [], {}, False)
               for k, v in (fields or {}).items() if not str(k).startswith("_"))


async def retry_failed_extractions(db, days: int = 30, limit: int = 60, delay_seconds: float = 2.0) -> Dict[str, Any]:
    from services.document_reprocess_service import reprocess_document

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = {
        "created_utc": {"$gte": since},
        "mailbox_category": "AP",
        "status": {"$nin": ["batch_parent", "Posted"]},
        "is_duplicate": {"$ne": True},
        "file_content_b64": {"$exists": True, "$ne": None},
        "amount_float": None,
        "invoice_number_clean": {"$in": [None, ""]},
        "$or": [{"extraction_retry_count": {"$exists": False}}, {"extraction_retry_count": {"$lt": MAX_ATTEMPTS}}],
    }
    ids = []
    async for d in db.hub_documents.find(query, {"_id": 0, "id": 1, "extracted_fields": 1}):
        if not _has_extraction(d.get("extracted_fields")):
            ids.append(d["id"])
            if len(ids) >= limit:
                break
    stats = {"candidates": len(ids), "recovered": 0, "still_empty": 0, "errors": 0, "stopped_early": False}
    empty_streak = 0
    for doc_id in ids:
        try:
            await reprocess_document(doc_id, reclassify=True)
        except Exception as exc:
            stats["errors"] += 1
            logger.warning("[ExtractionRetry] %s failed: %r", doc_id[:8], exc)
        doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "extracted_fields": 1})
        recovered = _has_extraction((doc or {}).get("extracted_fields"))
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$inc": {"extraction_retry_count": 1},
             "$set": {"extraction_retry_at": datetime.now(timezone.utc).isoformat(),
                      "extraction_retry_recovered": bool(recovered)}})
        if recovered:
            stats["recovered"] += 1
            empty_streak = 0
        else:
            stats["still_empty"] += 1
            empty_streak += 1
            if empty_streak >= STOP_AFTER_CONSECUTIVE_EMPTY:
                stats["stopped_early"] = True
                break
        await asyncio.sleep(delay_seconds)
    logger.info("[ExtractionRetry] %s", stats)
    return stats


async def retry_po_lines(db, days: int = 21, limit: int = 10, delay_seconds: float = 2.0) -> Dict[str, Any]:
    """Customer POs read without any line items (the extractor sometimes
    returns a one-sentence "items" summary instead: House "Gamer 19723.PDF",
    Horseshoe P0030235). One AI re-read each; 29 such POs 2026-09-01..10-21,
    the House one came back with its line on the first retry."""
    from services.document_reprocess_service import reprocess_document
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    # Sales orders only: BOLs, labels and pick tickets filed under a customer
    # PO have no lines to find (20 of 22 non-recoveries, 2026-10-21).
    query = {"created_utc": {"$gte": since}, "sales_link.role": "customer_po", "document_type": "Sales_Order",
             "status": {"$ne": "batch_parent"}, "file_content_b64": {"$exists": True, "$ne": None},
             "$or": [{"extracted_fields.line_items": {"$exists": False}}, {"extracted_fields.line_items": {"$size": 0}},
                     {"extracted_fields.line_items": None}],
             "line_retry_count": {"$exists": False}}
    ids = [d["id"] async for d in db.hub_documents.find(query, {"_id": 0, "id": 1}).sort([("created_utc", -1)]).limit(limit)]
    stats = {"candidates": len(ids), "recovered": 0, "still_none": 0, "errors": 0}
    for doc_id in ids:
        try:
            await reprocess_document(doc_id, reclassify=True)
        except Exception as exc:
            stats["errors"] += 1
            logger.warning("[POLineRetry] %s failed: %r", doc_id[:8], exc)
        doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "extracted_fields.line_items": 1})
        got = bool(((doc or {}).get("extracted_fields") or {}).get("line_items"))
        stats["recovered" if got else "still_none"] += 1
        await db.hub_documents.update_one({"id": doc_id}, {"$set": {"line_retry_count": 1, "line_retry_at": datetime.now(timezone.utc).isoformat(),
                                                                     "line_retry_recovered": got}})
        await asyncio.sleep(delay_seconds)
    logger.info("[POLineRetry] %s", stats)
    return stats
