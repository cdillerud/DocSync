"""
GPI Document Hub — Sales Order Learning Service

Reads existing BC sales orders and builds customer posting profiles,
mirroring what posting_pattern_analyzer.py does for AP vendors.

Collections used:
  - customer_posting_profiles  (one doc per customer_no)
  - sales_posting_learning_events  (append-only event log)
  - sales_learning_jobs  (background job status)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MIN_ORDERS_FOR_PROFILE = 3


# =============================================================================
# 1. Per-customer analysis
# =============================================================================


# =============================================================================
# 2. Bulk BC backfill
# =============================================================================


# =============================================================================
# 3. Incremental learning (called after each posted SO)
# =============================================================================


# =============================================================================
# 4. Detect posted sales order drafts
# =============================================================================

async def detect_posted_sales_drafts(db) -> Dict[str, Any]:
    """
    Find GPI-created SO drafts and check their BC status.
    If posted, mark as learned and record positive completion event.
    """
    docs = await db.hub_documents.find(
        {
            "so_draft_created": True,
            "draft_review_status": {"$nin": ["feedback_synced"]},
        },
        {"_id": 0, "id": 1, "customer_no": 1, "bc_sales_order": 1}
    ).limit(100).to_list(100)

    results = {"checked": 0, "posted_found": 0, "errors": 0}

    for doc_stub in docs:
        doc_id = doc_stub.get("id", "")
        if not doc_id:
            continue
        results["checked"] += 1

        try:
            bc_so = doc_stub.get("bc_sales_order") or {}
            bc_status = bc_so.get("status", "")

            if bc_status.lower() in ("open", "released", "posted"):
                results["posted_found"] += 1

                customer_no = doc_stub.get("customer_no", "")
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "draft_review_status": "feedback_synced",
                        "so_draft_posted_in_bc": True,
                        "so_draft_posted_detected_at": datetime.now(timezone.utc).isoformat(),
                    }}
                )

                await db.sales_posting_learning_events.insert_one({
                    "customer_no": customer_no,
                    "doc_id": doc_id,
                    "event_type": "so_draft_posted_in_bc",
                    "posted_at": datetime.now(timezone.utc).isoformat(),
                    "feedback": "positive_completion",
                    "bc_status": bc_status,
                })

        except Exception as exc:
            results["errors"] += 1
            logger.warning("[SalesLearning] Error checking SO draft %s: %s", doc_id[:8], exc)

    logger.info("[SalesLearning] SO draft detection: checked=%d, posted=%d",
                results["checked"], results["posted_found"])
    return results


# =============================================================================
# Helpers
# =============================================================================


