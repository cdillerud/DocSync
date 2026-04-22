"""
GPI Document Hub — Shared Feedback Ingest (U4, v2.5.2)
──────────────────────────────────────────────────────

Single cross-domain feedback entry point. Routes inbound reviewer
feedback by `scope_type` to the correct underlying service:

    scope_type="customer"  →  intake_learning_feedback_service.record_feedback_event
                              (suggestion_accepted / rejected, bounds / unmatched events
                               on Sales PO / SO / invoice insights)

    scope_type="vendor"    →  ap_invoice_feedback_service.submit_ap_feedback
                              (reviewer assessment of the AP advisory review)

Legacy endpoints (`/api/intake/insights/feedback`, `/api/ap-advisory/feedback/{id}`)
remain wired for a 30-day dual-write window.

Design:
  • Thin dispatcher — never duplicates domain logic; delegates to the
    existing services so no behavior drifts.
  • Never raises for input errors — returns `{error: str, ...}` so the
    caller can surface the message without a 500.
  • Always writes to the unified `learning_events_v2` log via the
    underlying services (customer) or directly in the AP adapter
    (vendor — closes the telemetry gap for sparklines).
"""

import logging
from typing import Any, Dict, List, Optional

from deps import get_db

logger = logging.getLogger(__name__)

SCOPE_TYPES = {"customer", "vendor"}


async def record_unified_feedback(
    *,
    scope_type: str,
    scope_value: Optional[str] = None,
    # customer (intake) shape
    event_type: Optional[str] = None,
    doc_id: Optional[str] = None,
    staging_id: Optional[str] = None,
    item_no: Optional[str] = None,
    trigger_item: Optional[str] = None,
    # vendor (AP) shape
    document_id: Optional[str] = None,
    reviewer_assessment: Optional[str] = None,
    final_human_decision: Optional[str] = None,
    disagreed_fields: Optional[List[str]] = None,
    notes: Optional[str] = None,
    # shared
    actor: str = "user",
    extra: Optional[Dict[str, Any]] = None,
    db=None,
) -> Dict[str, Any]:
    """Dispatch a feedback event to the correct domain handler.

    Returns whatever the underlying service returns (already
    `_id`-stripped and error-safe). Always includes `scope_type` in
    the response for caller disambiguation.
    """
    if scope_type not in SCOPE_TYPES:
        return {
            "error": f"unknown scope_type '{scope_type}'",
            "known": sorted(SCOPE_TYPES),
        }

    db = db if db is not None else get_db()

    if scope_type == "customer":
        from services.intake_learning_feedback_service import (
            record_feedback_event,
            EVENT_TYPES,
        )
        if not event_type:
            return {
                "error": "event_type is required for scope_type='customer'",
                "known_event_types": sorted(EVENT_TYPES),
                "scope_type": scope_type,
            }
        customer_no = scope_value  # normalize — scope_value IS the customer_no
        res = await record_feedback_event(
            event_type=event_type,
            doc_id=doc_id,
            staging_id=staging_id,
            customer_no=customer_no,
            item_no=item_no,
            trigger_item=trigger_item,
            extra=extra,
            actor=actor,
            db=db,
        )
        res["scope_type"] = scope_type
        return res

    # scope_type == "vendor"
    from services.ap_invoice_feedback_service import submit_ap_feedback
    doc_ref = document_id or doc_id
    if not doc_ref:
        return {
            "error": "document_id is required for scope_type='vendor'",
            "scope_type": scope_type,
        }
    if not reviewer_assessment:
        return {
            "error": "reviewer_assessment is required for scope_type='vendor'",
            "scope_type": scope_type,
        }
    res = await submit_ap_feedback(
        db, doc_ref, actor,
        reviewer_assessment, final_human_decision,
        disagreed_fields, notes,
    )
    if not isinstance(res, dict):
        res = {"result": res}
    if res.get("error"):
        res["scope_type"] = scope_type
        return res

    # Close the telemetry gap (U4.2) — dual-write AP reviewer feedback
    # into the unified learning_events_v2 log so the Cross-domain 7-day
    # sparklines on /intake/learning light up as AP reviewers work the
    # queue. Never blocks the primary ingest.
    try:
        from workflows.core.learning_core.events_service import record_event
        vendor_no = scope_value or res.get("vendor_no") or ""
        await record_event(
            domain="ap_posting",
            event_type=f"ap_review_{reviewer_assessment}",
            scope_type="vendor",
            scope_value=vendor_no or None,
            target={"doc_id": doc_ref},
            applied={
                "final_human_decision": final_human_decision,
                "disagreed_fields": disagreed_fields or [],
            },
            extra={"notes_len": len(notes or "")},
            actor=actor,
            source="ap_invoice_feedback_service",
            db=db,
        )
    except Exception as e:
        logger.debug("[LearningCore.feedback] ap unified write failed: %s", e)

    res["scope_type"] = scope_type
    return res


__all__ = ["record_unified_feedback", "SCOPE_TYPES"]
