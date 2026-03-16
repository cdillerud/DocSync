"""
Auto-Clear Reprocess — Re-evaluate auto-clear for documents that were
previously denied due to overly strict rules.

Endpoints:
  POST /api/auto-clear-reprocess/dry-run  — Preview what would be auto-cleared
  POST /api/auto-clear-reprocess/run      — Apply auto-clear to eligible docs
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
        # Rule 1: Standard auto-clear evaluation
        decision, reason, details = evaluate_auto_clear(doc)

        # Rule 2: Backfill docs or old unprocessed Unknown docs → auto-clear
        if decision != AutoClearDecision.CLEARED:
            source = (doc.get("source") or "").lower()
            doc_type = doc.get("doc_type") or doc.get("document_type") or ""
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

            is_unknown_type = not doc_type or doc_type in ("Unknown", "Unknown_Document", "Other")
            is_backfill = source == "backfill"
            is_non_ap = doc_type not in ("AP_Invoice", "AP_INVOICE")

            if is_backfill and is_unknown_type:
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
