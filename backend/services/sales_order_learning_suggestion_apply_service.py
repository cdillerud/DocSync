"""
GPI Document Hub — Sales Order Learning Suggestion Apply Service

Governed approval / reject / apply workflow for customer-profile
learning suggestions. All mutations are explicit, audited, and
reversible.

GOVERNED WORKFLOW: No silent or automatic profile changes.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

VALID_TRANSITIONS = {
    "pending":              {"approved", "rejected"},
    "insufficient_evidence": {"approved", "rejected"},
    "approved":             {"applied", "rejected"},
    "rejected":             {"pending"},  # allow un-reject
    "applied":              set(),        # terminal
}


async def approve_suggestion(db, suggestion_id: str, approver: str) -> Dict[str, Any]:
    """Move a suggestion to approved status."""
    return await _transition(db, suggestion_id, "approved", approver)


async def reject_suggestion(db, suggestion_id: str, approver: str) -> Dict[str, Any]:
    """Move a suggestion to rejected status."""
    return await _transition(db, suggestion_id, "rejected", approver)


async def apply_suggestion(db, suggestion_id: str, applier: str) -> Dict[str, Any]:
    """
    Apply an approved suggestion to the customer's posting profile.
    Records full before/after audit trail.
    """
    suggestion = await db.so_learning_suggestions.find_one(
        {"suggestion_id": suggestion_id}, {"_id": 0}
    )
    if not suggestion:
        return {"error": "Suggestion not found"}

    current_status = suggestion.get("status", "pending")
    if current_status != "approved":
        return {"error": f"Cannot apply — suggestion is '{current_status}', must be 'approved'"}

    customer_no = suggestion.get("customer_no", "")
    stype = suggestion.get("suggestion_type", "")
    change = suggestion.get("proposed_profile_change", {})

    if not customer_no:
        return {"error": "Suggestion has no customer_no"}

    # Load current profile (pre-change snapshot)
    profile = await db.customer_posting_profiles.find_one(
        {"customer_no": customer_no}, {"_id": 0}
    )
    pre_snapshot = dict(profile) if profile else {}

    if not profile:
        return {"error": f"No profile found for customer {customer_no}"}

    # Apply the targeted mutation
    mutation_result = await _apply_mutation(db, customer_no, stype, change, profile)

    if mutation_result.get("error"):
        return mutation_result

    # Load post-change profile
    post_profile = await db.customer_posting_profiles.find_one(
        {"customer_no": customer_no}, {"_id": 0}
    )
    post_snapshot = dict(post_profile) if post_profile else {}

    now = datetime.now(timezone.utc).isoformat()

    # Update suggestion status
    await db.so_learning_suggestions.update_one(
        {"suggestion_id": suggestion_id},
        {"$set": {
            "status": "applied",
            "applied_by": applier,
            "applied_at": now,
            "updated_at": now,
            "apply_result": mutation_result,
        }}
    )

    # Store audit record
    audit = {
        "suggestion_id": suggestion_id,
        "suggestion_type": stype,
        "customer_no": customer_no,
        "approved_by": suggestion.get("approved_by"),
        "applied_by": applier,
        "applied_at": now,
        "change_summary": mutation_result.get("summary", ""),
        "no_op": mutation_result.get("no_op", False),
        "pre_change_snapshot": _slim_snapshot(pre_snapshot),
        "post_change_snapshot": _slim_snapshot(post_snapshot),
    }
    await db.so_learning_apply_audit.insert_one(audit)
    audit.pop("_id", None)

    logger.info(
        "[SuggestionApply] applied: id=%s type=%s customer=%s by=%s no_op=%s summary=%s",
        suggestion_id, stype, customer_no, applier,
        mutation_result.get("no_op"), mutation_result.get("summary"),
    )

    # U6 — emit unified event so apply actions surface in Learning Ops
    try:
        from services.learning_core.events_service import record_event
        await record_event(
            domain="sales_intake",
            event_type="so_suggestion_applied",
            scope_type="customer",
            scope_value=customer_no,
            target={
                "suggestion_id": suggestion_id,
                "suggestion_type": stype,
            },
            applied={
                "no_op": mutation_result.get("no_op", False),
                "summary": mutation_result.get("summary", ""),
            },
            actor=applier,
            source="sales_order_learning_suggestion_apply_service",
            db=db,
        )
    except Exception as e:
        logger.debug("[SuggestionApply] unified event tick failed: %s", e)

    return {
        "status": "applied",
        "suggestion_id": suggestion_id,
        "suggestion_type": stype,
        "customer_no": customer_no,
        "applied_by": applier,
        "no_op": mutation_result.get("no_op", False),
        "summary": mutation_result.get("summary", ""),
    }


# =============================================================================
# State transitions
# =============================================================================

async def _transition(db, suggestion_id: str, target: str, actor: str) -> Dict[str, Any]:
    suggestion = await db.so_learning_suggestions.find_one(
        {"suggestion_id": suggestion_id}, {"_id": 0}
    )
    if not suggestion:
        return {"error": "Suggestion not found"}

    current = suggestion.get("status", "pending")
    allowed = VALID_TRANSITIONS.get(current, set())

    if target not in allowed:
        return {"error": f"Cannot transition from '{current}' to '{target}'. Allowed: {sorted(allowed) if allowed else 'none (terminal)'}"}

    now = datetime.now(timezone.utc).isoformat()
    update: Dict[str, Any] = {"status": target, "updated_at": now}

    if target == "approved":
        update["approved_by"] = actor
        update["approved_at"] = now
    elif target == "rejected":
        update["rejected_by"] = actor
        update["rejected_at"] = now

    await db.so_learning_suggestions.update_one(
        {"suggestion_id": suggestion_id}, {"$set": update}
    )

    logger.info("[SuggestionWorkflow] %s → %s: id=%s customer=%s by=%s",
                current, target, suggestion_id, suggestion.get("customer_no"), actor)

    # U6 — tick the unified learning log so reviewer activity on SO
    # suggestions shows up in the Learning Ops leaderboard + weekly digest.
    # Never blocks the primary transition.
    try:
        from services.learning_core.events_service import record_event
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
            source="sales_order_learning_suggestion_apply_service",
            db=db,
        )
    except Exception as e:
        logger.debug("[SuggestionWorkflow] unified event tick failed: %s", e)

    return {
        "suggestion_id": suggestion_id,
        "previous_status": current,
        "status": target,
        "actor": actor,
    }


# =============================================================================
# Profile mutations (per suggestion type)
# =============================================================================

async def _apply_mutation(
    db, customer_no: str, stype: str,
    change: Dict[str, Any], profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply a single targeted mutation. Returns summary."""

    if stype == "add_alternate_ship_to":
        return await _add_to_list(db, customer_no, "alternate_ship_tos", change.get("value", ""), profile)

    if stype == "add_occasional_valid_item":
        return await _add_to_list(db, customer_no, "occasional_valid_items", change.get("value", ""), profile)

    if stype == "add_alternate_uom_for_item":
        return await _add_uom_for_item(db, customer_no, change.get("item", ""), change.get("uom", ""), profile)

    if stype == "widen_order_value_tolerance":
        return await _widen_amount_range(db, customer_no, profile)

    if stype == "revise_po_pattern":
        return await _revise_po(db, customer_no, profile)

    if stype == "increase_variability_tolerance":
        return await _increase_variability(db, customer_no, change.get("current", 0), profile)

    return {"error": f"Unknown suggestion type: {stype}"}


async def _add_to_list(db, cno: str, field: str, value: str, profile: Dict) -> Dict:
    existing = profile.get(field, [])
    if value in existing:
        return {"no_op": True, "summary": f"'{value}' already in {field}"}
    await db.customer_posting_profiles.update_one(
        {"customer_no": cno},
        {"$addToSet": {field: value}}
    )
    return {"no_op": False, "summary": f"Added '{value}' to {field}"}


async def _add_uom_for_item(db, cno: str, item: str, uom: str, profile: Dict) -> Dict:
    alt_map = profile.get("alternate_valid_uoms_by_item", {})
    existing_uoms = alt_map.get(item, [])
    if uom in existing_uoms:
        return {"no_op": True, "summary": f"UOM '{uom}' already valid for item '{item}'"}
    key = f"alternate_valid_uoms_by_item.{item}"
    await db.customer_posting_profiles.update_one(
        {"customer_no": cno},
        {"$addToSet": {key: uom}}
    )
    return {"no_op": False, "summary": f"Added UOM '{uom}' as valid alternate for item '{item}'"}


async def _widen_amount_range(db, cno: str, profile: Dict) -> Dict:
    ar = profile.get("amount_range", {"min": 0, "max": 0})
    old_min, old_max = ar.get("min", 0), ar.get("max", 0)
    spread = old_max - old_min if old_max > old_min else old_max * 0.5
    new_min = round(max(0, old_min - spread * 0.15), 2)
    new_max = round(old_max + spread * 0.20, 2)
    await db.customer_posting_profiles.update_one(
        {"customer_no": cno},
        {"$set": {"amount_range": {"min": new_min, "max": new_max}}}
    )
    return {"no_op": False, "summary": f"Widened amount range from ${old_min}-${old_max} to ${new_min}-${new_max}"}


async def _revise_po(db, cno: str, profile: Dict) -> Dict:
    current = profile.get("po_number_pattern", "unknown")
    # Broaden to accept any format
    await db.customer_posting_profiles.update_one(
        {"customer_no": cno},
        {"$set": {"po_number_pattern": "any"}}
    )
    return {"no_op": False, "summary": f"Relaxed PO pattern from '{current}' to 'any'"}


async def _increase_variability(db, cno: str, current: float, profile: Dict) -> Dict:
    actual_current = profile.get("customer_variability_index", current)
    new_val = min(1.0, round(actual_current + 0.15, 4))
    if new_val <= actual_current:
        return {"no_op": True, "summary": f"Variability already at {actual_current}"}
    await db.customer_posting_profiles.update_one(
        {"customer_no": cno},
        {"$set": {"customer_variability_index": new_val}}
    )
    return {"no_op": False, "summary": f"Increased variability index from {actual_current} to {new_val}"}


def _slim_snapshot(profile: Dict) -> Dict:
    """Extract key fields for audit without storing the entire profile."""
    return {k: profile.get(k) for k in (
        "customer_no", "invoices_analyzed", "template_confidence",
        "common_items", "occasional_valid_items", "alternate_valid_uoms_by_item",
        "alternate_ship_tos", "amount_range", "po_number_pattern",
        "customer_variability_index", "profile_richness_score",
    ) if k in profile}
