"""
Auto-Clear Reprocess — Re-evaluate auto-clear for documents that were
previously denied due to overly strict rules.

Endpoints:
  POST /api/auto-clear-reprocess/dry-run  — Preview what would be auto-cleared
  POST /api/auto-clear-reprocess/run      — Apply auto-clear to eligible docs
  POST /api/auto-clear-reprocess/force-clear-remaining — Force-clear ALL remaining docs
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from deps import get_db
from services.auto_clear_service import (
    evaluate_auto_clear, get_auto_clear_update, AutoClearDecision
)

logger = logging.getLogger("auto_clear_reprocess")
router = APIRouter(prefix="/auto-clear-reprocess", tags=["Auto-Clear Reprocess"])

_PROTECT_TYPES = ("Inventory_Report", "Sales_Order", "Purchase_Order",
                  "SALES_ORDER", "PURCHASE_ORDER")
_PROTECT_KEYWORDS = ("inventory", "open order", "open release",
                     "warehouse", "stock", "sales-order", "sales order",
                     "purchase-order", "purchase order", "pick-ticket",
                     "pick ticket", "whse receipt", "demand", "forecast")


@router.post("/dry-run")
async def dry_run():
    """Preview how many non-cleared, non-terminal docs would be auto-cleared."""
    db = get_db()

    TERMINAL = ["Completed", "Posted", "Archived", "Duplicate"]
    docs = await db.hub_documents.find(
        {
            "is_duplicate": {"$ne": True},
            "auto_cleared": {"$ne": True},
            "status": {"$nin": TERMINAL},
        },
        {"_id": 0},
    ).to_list(5000)

    would_clear = 0
    by_type = {}
    by_reason = {}

    for doc in docs:
        decision, reason, details = evaluate_auto_clear(doc)
        if decision == AutoClearDecision.CLEARED:
            would_clear += 1
            dt = doc.get("doc_type") or doc.get("document_type") or "unknown"
            by_type.setdefault(dt, 0)
            by_type[dt] += 1
        else:
            by_reason.setdefault(reason[:60], 0)
            by_reason[reason[:60]] += 1

    return {
        "total_evaluated": len(docs),
        "would_auto_clear": would_clear,
        "would_remain": len(docs) - would_clear,
        "by_type": by_type,
        "top_block_reasons": dict(sorted(by_reason.items(), key=lambda x: -x[1])[:15]),
    }


@router.post("/run")
async def run_reprocess():
    """Re-evaluate auto-clear and apply to eligible documents."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    TERMINAL = ["Completed", "Posted", "Archived", "Duplicate"]
    docs = await db.hub_documents.find(
        {
            "is_duplicate": {"$ne": True},
            "auto_cleared": {"$ne": True},
            "status": {"$nin": TERMINAL},
        },
        {"_id": 0},
    ).to_list(5000)

    cleared = 0
    by_type = {}
    by_reason = {}

    for doc in docs:
        decision, reason, details = evaluate_auto_clear(doc)

        # Extended rules for backfill/old docs
        if decision != AutoClearDecision.CLEARED:
            source = (doc.get("source") or "").lower()
            doc_type = doc.get("doc_type") or doc.get("document_type") or ""
            fname = (doc.get("file_name") or "").lower()
            created = doc.get("created_utc") or doc.get("created_at") or ""
            is_old = False
            age_days = 0
            if created:
                try:
                    from datetime import datetime as dt_cls
                    if isinstance(created, str):
                        created_dt = dt_cls.fromisoformat(created.replace("Z", "+00:00"))
                    else:
                        created_dt = created
                    age_days = (datetime.now(timezone.utc) - created_dt).days
                    is_old = age_days >= 14
                except Exception:
                    is_old = False

            is_protected = (
                doc_type in _PROTECT_TYPES
                or any(kw in fname for kw in _PROTECT_KEYWORDS)
            )
            is_unknown_type = not doc_type or doc_type in ("Unknown", "Unknown_Document", "Other")
            is_backfill = source == "backfill"
            is_non_ap = doc_type not in ("AP_Invoice", "AP_INVOICE")

            if is_protected:
                pass  # Never auto-clear operational docs
            elif is_backfill and is_unknown_type:
                decision = AutoClearDecision.CLEARED
                reason = f"Backfill reference doc (type={doc_type or 'none'}, source={source})"
            elif is_old and is_unknown_type:
                decision = AutoClearDecision.CLEARED
                reason = f"Old unprocessed doc ({age_days}d, type={doc_type or 'none'})"
            elif is_old and is_non_ap:
                decision = AutoClearDecision.CLEARED
                reason = f"Old non-AP doc ({age_days}d, type={doc_type})"

        if decision == AutoClearDecision.CLEARED:
            update = get_auto_clear_update(decision, details)
            update["workflow_status"] = "completed"
            update["auto_clear_reason"] = reason
            await db.hub_documents.update_one(
                {"id": doc["id"]},
                {"$set": update},
            )
            cleared += 1
            dt = doc.get("doc_type") or doc.get("document_type") or "unknown"
            by_type.setdefault(dt, 0)
            by_type[dt] += 1
        else:
            by_reason.setdefault(reason[:80], 0)
            by_reason[reason[:80]] += 1

    return {
        "total_evaluated": len(docs),
        "auto_cleared": cleared,
        "remained": len(docs) - cleared,
        "by_type": by_type,
        "top_block_reasons": dict(sorted(by_reason.items(), key=lambda x: -x[1])[:15]),
        "timestamp": now,
    }


@router.post("/force-clear-remaining")
async def force_clear_remaining():
    """Force-clear all remaining non-terminal, non-duplicate pending docs."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    TERMINAL = ["Completed", "Posted", "Archived", "Duplicate", "FileMissing"]
    result = await db.hub_documents.update_many(
        {
            "is_duplicate": {"$ne": True},
            "auto_cleared": {"$ne": True},
            "file_missing": {"$ne": True},
            "status": {"$nin": TERMINAL},
        },
        {"$set": {
            "auto_cleared": True,
            "auto_clear_decision": "cleared",
            "auto_clear_reason": "Manual bulk clear",
            "workflow_status": "completed",
            "status": "Completed",
            "auto_clear_timestamp": now,
        }},
    )

    return {
        "cleared": result.modified_count,
        "timestamp": now,
    }


# ─── Junk Document Types ──────────────────────────────────────
_JUNK_DOC_TYPES = {
    "Unknown_Sales", "Unknown", "Unknown_Document",
}
_JUNK_FILE_EXTENSIONS = {
    ".mp4", ".mp3", ".wav", ".avi", ".mov", ".wmv",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".heic",
    ".docx", ".pptx",
}
_PRESERVE_DOC_TYPES = {
    "Sales_Order", "Purchase_Order", "AP_Invoice", "AP_INVOICE",
    "AR_Invoice", "Inventory_Report", "Freight_Document",
    "Shipping_Document", "Remittance", "REMITTANCE",
    "Order_Confirmation", "BOL", "Packing_List", "Bill_of_Lading",
    "Return_Request", "Sales_Quote", "Sales_Shipping_Document",
    "Quality_Issue", "Quality_Doc", "QUALITY_DOC",
    "Shipping_Request", "Shipping_Schedule", "Contract",
    "Credit_Memo", "Statement", "STATEMENT",
    "Pick_Ticket", "Warehouse_Document",
}


def _is_junk(doc):
    """Determine if a document is junk based on type, confidence, and file extension."""
    doc_type = doc.get("doc_type") or doc.get("document_type") or ""
    file_name = doc.get("file_name") or doc.get("original_file_name") or ""

    # Never touch preserved types
    if doc_type in _PRESERVE_DOC_TYPES:
        return False, "preserved type"

    # Check file extension
    ext = ""
    if "." in file_name:
        ext = "." + file_name.rsplit(".", 1)[-1].lower()

    # Junk by type + low confidence
    ai_class = doc.get("ai_classification") or {}
    confidence = ai_class.get("confidence") or doc.get("classification_confidence") or doc.get("confidence") or 0
    if isinstance(confidence, str):
        confidence = float(confidence.replace("%", "")) / 100 if "%" in confidence else float(confidence)
    confidence = float(confidence)

    if doc_type in _JUNK_DOC_TYPES and confidence <= 0.40:
        return True, f"junk_type ({doc_type} at {confidence:.0%})"

    # Junk by file extension (non-document files)
    if ext in _JUNK_FILE_EXTENSIONS and doc_type in _JUNK_DOC_TYPES:
        return True, f"non_document_file ({ext}, type={doc_type})"

    # Email body entries with no file (subject lines)
    if not file_name or file_name.startswith("Re:") or file_name.startswith("FW:") or file_name.startswith("RE:"):
        if doc_type in _JUNK_DOC_TYPES or (not doc_type or doc_type == "Unknown"):
            return True, f"email_body_entry (no document file)"

    return False, "not_junk"


@router.post("/clear-junk/dry-run")
async def dry_run_clear_junk():
    """Preview which documents would be classified as junk and cleared."""
    db = get_db()
    TERMINAL = ["Completed", "Posted", "Archived", "Duplicate", "FileMissing"]

    docs = await db.hub_documents.find(
        {"status": {"$nin": TERMINAL}},
        {"_id": 0, "id": 1, "file_name": 1, "original_file_name": 1,
         "doc_type": 1, "document_type": 1, "ai_classification": 1,
         "classification_confidence": 1, "confidence": 1,
         "source_email": 1, "sender_email": 1},
    ).to_list(5000)

    would_clear = []
    would_keep = []

    for doc in docs:
        is_junk, reason = _is_junk(doc)
        entry = {
            "id": doc.get("id", ""),
            "file_name": doc.get("file_name") or doc.get("original_file_name", ""),
            "doc_type": doc.get("doc_type") or doc.get("document_type", ""),
            "reason": reason,
        }
        if is_junk:
            would_clear.append(entry)
        else:
            would_keep.append(entry)

    by_reason = {}
    for d in would_clear:
        r = d["reason"].split("(")[0].strip()
        by_reason.setdefault(r, 0)
        by_reason[r] += 1

    by_type_keep = {}
    for d in would_keep:
        t = d["doc_type"] or "unknown"
        by_type_keep.setdefault(t, 0)
        by_type_keep[t] += 1

    return {
        "total_evaluated": len(docs),
        "would_clear": len(would_clear),
        "would_keep": len(would_keep),
        "clear_by_reason": dict(sorted(by_reason.items(), key=lambda x: -x[1])),
        "keep_by_type": dict(sorted(by_type_keep.items(), key=lambda x: -x[1])),
        "sample_junk": would_clear[:20],
    }


@router.post("/clear-junk/run")
async def run_clear_junk():
    """Clear all junk documents while preserving operational docs."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    TERMINAL = ["Completed", "Posted", "Archived", "Duplicate", "FileMissing"]

    docs = await db.hub_documents.find(
        {"status": {"$nin": TERMINAL}},
        {"_id": 0},
    ).to_list(5000)

    cleared = 0
    by_reason = {}

    for doc in docs:
        is_junk, reason = _is_junk(doc)
        if not is_junk:
            continue

        await db.hub_documents.update_one(
            {"id": doc["id"]},
            {"$set": {
                "auto_cleared": True,
                "auto_clear_decision": "cleared",
                "auto_clear_reason": f"junk: {reason}",
                "workflow_status": "completed",
                "status": "Completed",
                "auto_clear_timestamp": now,
                "queue_visible": False,
                "updated_utc": now,
            }},
        )
        cleared += 1
        r = reason.split("(")[0].strip()
        by_reason.setdefault(r, 0)
        by_reason[r] += 1

    return {
        "cleared": cleared,
        "by_reason": dict(sorted(by_reason.items(), key=lambda x: -x[1])),
        "timestamp": now,
    }

