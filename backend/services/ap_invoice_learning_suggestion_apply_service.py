"""
GPI Document Hub — AP Invoice Learning Suggestion Apply Service

Governed approval / reject / apply workflow for vendor-profile
learning suggestions. All mutations are explicit, audited, and
reversible.

GOVERNED WORKFLOW: No silent or automatic profile changes.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)

VALID_TRANSITIONS = {
    "pending":               {"approved", "rejected"},
    "insufficient_evidence": {"approved", "rejected"},
    "approved":              {"applied", "rejected"},
    "rejected":              {"pending"},
    "applied":               set(),
}


async def approve_ap_suggestion(db, suggestion_id: str, approver: str) -> Dict[str, Any]:
    return await _transition(db, suggestion_id, "approved", approver)


async def reject_ap_suggestion(db, suggestion_id: str, approver: str) -> Dict[str, Any]:
    return await _transition(db, suggestion_id, "rejected", approver)


async def apply_ap_suggestion(db, suggestion_id: str, applier: str) -> Dict[str, Any]:
    """
    Apply an approved suggestion to the vendor's invoice profile.
    Records full before/after audit trail.
    """
    suggestion = await db.ap_learning_suggestions.find_one(
        {"suggestion_id": suggestion_id}, {"_id": 0}
    )
    if not suggestion:
        return {"error": "Suggestion not found"}

    current_status = suggestion.get("status", "pending")
    if current_status != "approved":
        return {"error": f"Cannot apply — suggestion is '{current_status}', must be 'approved'"}

    vendor_no = suggestion.get("vendor_no", "")
    stype = suggestion.get("suggestion_type", "")

    if not vendor_no:
        return {"error": "Suggestion has no vendor_no"}

    profile = await db.vendor_invoice_profiles.find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )
    pre_snapshot = dict(profile) if profile else {}

    if not profile:
        return {"error": f"No profile found for vendor {vendor_no}"}

    mutation_result = await _apply_mutation(db, vendor_no, stype, suggestion, profile)

    if mutation_result.get("error"):
        return mutation_result

    post_profile = await db.vendor_invoice_profiles.find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )
    post_snapshot = dict(post_profile) if post_profile else {}

    now = datetime.now(timezone.utc).isoformat()

    await db.ap_learning_suggestions.update_one(
        {"suggestion_id": suggestion_id},
        {"$set": {
            "status": "applied",
            "applied_by": applier,
            "applied_at": now,
            "updated_at": now,
            "apply_result": mutation_result,
        }}
    )

    audit = {
        "suggestion_id": suggestion_id,
        "suggestion_type": stype,
        "vendor_no": vendor_no,
        "vendor_name": suggestion.get("vendor_name", ""),
        "approved_by": suggestion.get("approved_by"),
        "applied_by": applier,
        "applied_at": now,
        "change_summary": mutation_result.get("summary", ""),
        "no_op": mutation_result.get("no_op", False),
        "pre_change_snapshot": _slim_snapshot(pre_snapshot),
        "post_change_snapshot": _slim_snapshot(post_snapshot),
    }
    await db.ap_learning_apply_audit.insert_one(audit)
    audit.pop("_id", None)

    logger.info(
        "[AP-SuggestionApply] applied: id=%s type=%s vendor=%s by=%s no_op=%s summary=%s",
        suggestion_id, stype, vendor_no, applier,
        mutation_result.get("no_op"), mutation_result.get("summary"),
    )

    return {
        "status": "applied",
        "suggestion_id": suggestion_id,
        "suggestion_type": stype,
        "vendor_no": vendor_no,
        "applied_by": applier,
        "no_op": mutation_result.get("no_op", False),
        "summary": mutation_result.get("summary", ""),
    }


async def _transition(db, suggestion_id: str, target: str, actor: str) -> Dict[str, Any]:
    suggestion = await db.ap_learning_suggestions.find_one(
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

    await db.ap_learning_suggestions.update_one(
        {"suggestion_id": suggestion_id}, {"$set": update}
    )

    logger.info("[AP-SuggestionWorkflow] %s -> %s: id=%s vendor=%s by=%s",
                current, target, suggestion_id, suggestion.get("vendor_no"), actor)

    return {
        "suggestion_id": suggestion_id,
        "previous_status": current,
        "status": target,
        "actor": actor,
    }


async def _apply_mutation(
    db, vendor_no: str, stype: str,
    suggestion: Dict[str, Any], profile: Dict[str, Any],
) -> Dict[str, Any]:

    if stype == "add_vendor_alias":
        alias_value = suggestion.get("vendor_name", vendor_no)
        return await _add_vendor_alias(db, vendor_no, alias_value, profile)

    if stype == "add_accepted_reference_pattern":
        return await _add_accepted_ref(db, vendor_no, profile)

    if stype == "widen_amount_tolerance":
        return await _widen_amount(db, vendor_no, profile)

    if stype == "add_accepted_po_behavior":
        return await _relax_po(db, vendor_no, profile)

    if stype == "increase_vendor_variability":
        return await _increase_variability(db, vendor_no, profile)

    return {"error": f"Unknown suggestion type: {stype}"}


async def _add_vendor_alias(db, vno: str, alias_value: str, profile: Dict) -> Dict:
    existing = profile.get("known_aliases", [])
    norm = alias_value.strip().upper()
    if norm in [a.upper() for a in existing]:
        return {"no_op": True, "summary": f"Alias '{alias_value}' already known"}
    await db.vendor_invoice_profiles.update_one(
        {"vendor_no": vno},
        {"$addToSet": {"known_aliases": alias_value}}
    )
    return {"no_op": False, "summary": f"Added vendor alias '{alias_value}'"}


async def _add_accepted_ref(db, vno: str, profile: Dict) -> Dict:
    current = profile.get("accepted_reference_patterns", [])
    new_pattern = "any"
    if new_pattern in current:
        return {"no_op": True, "summary": "Reference pattern 'any' already accepted"}
    await db.vendor_invoice_profiles.update_one(
        {"vendor_no": vno},
        {"$addToSet": {"accepted_reference_patterns": new_pattern}}
    )
    return {"no_op": False, "summary": "Added 'any' to accepted reference patterns"}


async def _widen_amount(db, vno: str, profile: Dict) -> Dict:
    stats = profile.get("amount_stats") or {}
    old_min = stats.get("min", 0)
    old_max = stats.get("max", 0)
    spread = old_max - old_min if old_max > old_min else max(old_max * 0.5, 100)
    new_min = round(max(0, old_min - spread * 0.15), 2)
    new_max = round(old_max + spread * 0.20, 2)
    await db.vendor_invoice_profiles.update_one(
        {"vendor_no": vno},
        {"$set": {"amount_stats.min": new_min, "amount_stats.max": new_max}}
    )
    return {"no_op": False, "summary": f"Widened amount range from ${old_min}-${old_max} to ${new_min}-${new_max}"}


async def _relax_po(db, vno: str, profile: Dict) -> Dict:
    current = profile.get("po_expected", True)
    if not current:
        return {"no_op": True, "summary": "PO already not expected for this vendor"}
    await db.vendor_invoice_profiles.update_one(
        {"vendor_no": vno},
        {"$set": {"po_expected": False}}
    )
    return {"no_op": False, "summary": "Relaxed PO requirement — vendor now tagged as PO-optional"}


async def _increase_variability(db, vno: str, profile: Dict) -> Dict:
    current = profile.get("vendor_variability_index", 0.5)
    new_val = min(1.0, round(current + 0.15, 4))
    if new_val <= current:
        return {"no_op": True, "summary": f"Variability already at {current}"}
    await db.vendor_invoice_profiles.update_one(
        {"vendor_no": vno},
        {"$set": {"vendor_variability_index": new_val}}
    )
    return {"no_op": False, "summary": f"Increased variability index from {current} to {new_val}"}


def _slim_snapshot(profile: Dict) -> Dict:
    return {k: profile.get(k) for k in (
        "vendor_no", "vendor_name", "bc_invoice_count",
        "posting_confidence", "template_confidence",
        "amount_stats", "po_expected", "known_aliases",
        "accepted_reference_patterns", "vendor_variability_index",
        "default_item_code", "description_pattern",
    ) if k in profile}
