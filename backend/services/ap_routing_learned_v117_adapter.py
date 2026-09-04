"""Compatibility adapter that makes the existing V117 evaluator AI-primary.

The evaluator still calls a function named like the legacy authority guard. This
adapter preserves that call contract while routing through the learned pipeline.
All deterministic safety is already applied inside the learned pipeline and may
only demote the AI's exact route to review. No route substitution is allowed.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional

from services.ap_routing_learned_pipeline_service import decide_ap_route_learned


async def decide_ap_route_with_learned_autonomy(
    db,
    *,
    document: Dict[str, Any],
    bc_context: Optional[Dict[str, Any]],
    contract: Dict[str, Any],
    examples: Optional[List[Dict[str, Any]]] = None,
    support_examples: Optional[List[Dict[str, Any]]] = None,
    vendor_auto_threshold: Optional[float] = None,
    model: str = "gemini-2.5-pro",
    llm_send: Optional[Callable[[str, str], Awaitable[Any]]] = None,
    **_: Any,
) -> Dict[str, Any]:
    del db, vendor_auto_threshold
    context = bc_context or {}
    train = list(support_examples or examples or [])
    result = await decide_ap_route_learned(
        document={**document, "bc_context": context},
        bc_context=context,
        contract=contract,
        train_examples=train,
        performance_outcomes=[
            row for row in train
            if row.get("human_resolved") and row.get("ai_proposed_route") and row.get("final_human_route")
        ],
        relevant_limit=8,
        model=model,
        llm_send=llm_send,
    )

    neighborhood = result.get("neighborhood") or {}
    neighbor_routes = [str(route) for route in (neighborhood.get("neighbor_routes") or []) if route]
    scope = str(neighborhood.get("scope") or "")
    same_vendor_count = int(neighborhood.get("neighborhood_count") or 0) if scope == "same_vendor" else 0
    same_vendor_route_count = len(set(neighbor_routes)) if scope == "same_vendor" else 0

    result["confidence"] = float(result.get("ai_confidence") or 0.0)
    result["blockers"] = list(result.get("safety_blockers") or result.get("reasons") or [])
    result["warnings"] = []
    result["contract_version"] = str(contract.get("version") or "unknown")
    result["few_shot_count"] = int(result.get("prompt_example_count") or 0)
    result["authority_guard"] = {
        "action": "learned_" + str(result.get("autonomy_tier") or "review"),
        "blockers": list(result.get("safety_blockers") or result.get("reasons") or []),
        "same_vendor_label_count": same_vendor_count,
        "same_vendor_route_count": same_vendor_route_count,
        "autonomy_score": result.get("autonomy_score"),
        "support_count": result.get("support_count"),
        "contradiction_count": result.get("contradiction_count"),
        "support_share": result.get("support_share"),
        "support_margin": result.get("support_margin"),
        "neighborhood_scope": scope,
        "neighborhood_count": neighborhood.get("neighborhood_count"),
        "neighbor_routes": neighbor_routes,
        "neighbor_ids": neighborhood.get("neighbor_ids") or [],
        "neighbor_scores": neighborhood.get("neighbor_scores") or [],
        "semantic_anchor": neighborhood.get("semantic_anchor"),
        "current_reference_family": neighborhood.get("current_reference_family"),
        "current_semantic_features": neighborhood.get("current_semantic_features") or [],
        "exceptional_workflow_features": neighborhood.get("exceptional_workflow_features") or [],
        "exception_support_count": neighborhood.get("exception_support_count"),
        "exception_mismatch_support_count": neighborhood.get("exception_mismatch_support_count"),
        "exception_support_ready": neighborhood.get("exception_support_ready"),
        "performance": result.get("performance") or {},
        "earned_by": result.get("earned_by"),
        "hard_safety_blockers": list(result.get("safety_blockers") or []),
    }
    result["ensemble_reconciliation"] = {
        "action": "ai_primary_no_route_substitution",
        "original_model_route": result.get("ai_proposed_route"),
        "original_model_confidence": result.get("ai_confidence"),
    }
    result["supervised_route_support"] = {
        "top_route": None,
        "margin": None,
        "strong": None,
        "purpose": "prompt_context_only_not_route_authority",
    }
    result["full_supervised_route_support"] = {
        "top_route": None,
        "margin": None,
        "routes": [],
        "purpose": "learned_autonomy_not_deterministic_route_selection",
    }
    return result


decide_ap_route_with_authority_guard = decide_ap_route_with_learned_autonomy
