"""
GPI Document Hub — Unified Learning Stack

Suggestion lifecycle (generate / list / approve / reject / apply) behind the
AI Learning page. Only the Sales Order pipeline (SALES_CONFIG) is wired: the
AP advisory surface that used an AP config had no UI and was removed in Round
5c (2026-09-24), along with the unused calibration, drift, hotspot, impact and
diagnostics analytics for both pipelines.

GOVERNED WORKFLOW: No silent or automatic profile changes.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class LearningConfig:
    """Pipeline-specific configuration for the unified learning stack."""
    entity_type: str              # "vendor" or "customer"
    entity_field: str             # "vendor_no" or "customer_no"
    entity_name_field: str        # "vendor_name" or "customer_name"
    suggestions_collection: str   # "ap_learning_suggestions" or "so_learning_suggestions"
    feedback_collection: str      # "ap_reviewer_feedback" or "so_reviewer_feedback"
    profile_collection: str       # "vendor_invoice_profiles" or "customer_posting_profiles"
    audit_collection: str         # "ap_learning_apply_audit" or "so_learning_apply_audit"
    label: str = ""               # "AP Invoice" or "Sales Order" (display)


SALES_CONFIG = LearningConfig(
    entity_type="customer",
    entity_field="customer_no",
    entity_name_field="customer_name",
    suggestions_collection="so_learning_suggestions",
    feedback_collection="so_reviewer_feedback",
    profile_collection="customer_posting_profiles",
    audit_collection="so_learning_apply_audit",
    label="Sales Order",
)


# ═══════════════════════════════════════════════════════════════════════════
# Suggestion Lifecycle (approve / reject / apply)
# ═══════════════════════════════════════════════════════════════════════════

VALID_TRANSITIONS = {
    "pending":               {"approved", "rejected"},
    "insufficient_evidence": {"approved", "rejected"},
    "approved":              {"applied", "rejected"},
    "rejected":              {"pending"},
    "applied":               set(),
}


async def approve_suggestion(
    db, cfg: LearningConfig, suggestion_id: str, approver: str,
) -> Dict[str, Any]:
    """Move a suggestion to approved status."""
    return await _transition(db, cfg, suggestion_id, "approved", approver)


async def reject_suggestion(
    db, cfg: LearningConfig, suggestion_id: str, approver: str,
) -> Dict[str, Any]:
    """Move a suggestion to rejected status."""
    return await _transition(db, cfg, suggestion_id, "rejected", approver)


async def apply_suggestion(
    db, cfg: LearningConfig, suggestion_id: str, applier: str,
) -> Dict[str, Any]:
    """
    Apply an approved suggestion to the entity's profile.

    Delegates to the pipeline's own mutation handlers rather than a
    generic flat $set: Sales' (_add_to_list / _add_uom_for_item /
    _widen_amount_range / _revise_po / _increase_variability) compute the change from live
    profile state and no-op safely when nothing needs to change --
    a stored flat "mutation" snapshot cannot do either of those.
    Each delegate records its own before/after audit trail.
    """
    if cfg.label == "Sales Order":
        from services.sales_order_learning_suggestion_apply_service import apply_suggestion as _apply_so_suggestion
        return await _apply_so_suggestion(db, suggestion_id, applier)

    return {"error": f"apply_suggestion: no handler wired for pipeline '{cfg.label}'"}


async def _transition(
    db, cfg: LearningConfig, suggestion_id: str, target: str, actor: str,
) -> Dict[str, Any]:
    """Generic state transition for suggestion lifecycle."""
    coll = db[cfg.suggestions_collection]
    suggestion = await coll.find_one({"suggestion_id": suggestion_id}, {"_id": 0})
    if not suggestion:
        return {"error": "Suggestion not found"}

    current = suggestion.get("status", "pending")
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        return {"error": f"Cannot transition from '{current}' to '{target}'. Allowed: {allowed}"}

    now = datetime.now(timezone.utc).isoformat()
    update = {"status": target, f"{target}_by": actor, f"{target}_at": now, "updated_at": now}
    await coll.update_one({"suggestion_id": suggestion_id}, {"$set": update})

    logger.info("[Learning] %s suggestion %s: %s → %s by %s", cfg.label, suggestion_id, current, target, actor)

    # Same learning-log event the old Sales-only transition wrote. Never blocks.
    if cfg is SALES_CONFIG:
        try:
            from workflows.core.learning_core.events_service import record_event
            await record_event(
                domain="sales_intake",
                event_type=f"so_suggestion_{target}",
                scope_type="customer",
                scope_value=suggestion.get("customer_no"),
                target={
                    "suggestion_id": suggestion_id,
                    "suggestion_type": suggestion.get("suggestion_type"),
                },
                applied={"from_status": current, "to_status": target},
                actor=actor,
                source="unified_learning_service",
                db=db,
            )
        except Exception as e:
            logger.debug("[Learning] event tick failed: %s", e)
    return {"status": target, "suggestion_id": suggestion_id, "previous": current}


# ═══════════════════════════════════════════════════════════════════════════
# Feedback Analysis & Suggestion Generation
# ═══════════════════════════════════════════════════════════════════════════

async def generate_suggestions(
    db, cfg: LearningConfig, limit: int = 100,
) -> Dict[str, Any]:
    """
    Analyze reviewer feedback and generate candidate profile-learning
    suggestions for this pipeline.

    Delegates to the pipeline's own purpose-built pattern analyzer
    (Sales: ship-to / item / UOM / amount / PO / variability signals, with
    drift-risk-aware thresholds). The analyzer emits the specific
    suggestion_type values its own apply-side handler knows how to
    act on -- a generic "field disagreed N times" signal does not
    carry enough information to safely produce a profile change.
    """
    if cfg.label == "Sales Order":
        from services.sales_order_feedback_learning_service import generate_learning_suggestions as _generate_so_suggestions
        return await _generate_so_suggestions(db, limit=limit)

    return {"error": f"generate_suggestions: no analyzer wired for pipeline '{cfg.label}'"}


async def get_suggestions(
    db, cfg: LearningConfig,
    status: Optional[str] = None,
    entity_no: Optional[str] = None,
    suggestion_type: Optional[str] = None,
    limit: int = 50, skip: int = 0,
) -> Dict[str, Any]:
    """Retrieve suggestions with optional filters."""
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    if entity_no:
        query[cfg.entity_field] = entity_no
    if suggestion_type:
        query["suggestion_type"] = suggestion_type

    coll = db[cfg.suggestions_collection]
    total = await coll.count_documents(query)
    items = await coll.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)

    return {"total": total, "showing": len(items), "suggestions": items}
