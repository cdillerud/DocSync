"""Compatibility adapter that makes the existing V117 evaluator AI-primary.

The evaluator still calls a function named like the legacy authority guard. This
adapter preserves that call contract while routing through the learned pipeline.
It does not use the legacy deterministic route selector.
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
    del db, vendor_auto_threshold  # learned policy owns autonomy thresholds
    train = list(support_examples or examples or [])
    result = await decide_ap_route_learned(
        document={**document, "bc_context": bc_context or {}},
        bc_context=bc_context or {},
        contract=contract,
        train_examples=train,
        performance_outcomes=[
            row for row in train
            if row.get("human_resolved") and row.get("ai_proposed_route") and row.get("final_human_route")
        ],
        model=model,
        llm_send=llm_send,
    )
    result["confidence"] = float(result.get("ai_confidence") or 0.0)
    result["blockers"] = list(result.get("safety_blockers") or result.get("reasons") or [])
    result["warnings"] = []
    result["contract_version"] = str(contract.get("version") or "unknown")
    result["few_shot_count"] = int(result.get("prompt_example_count") or 0)
    result["authority_guard"] = {
        "action": "learned_" + str(result.get("autonomy_tier") or "review"),
        "blockers": list(result.get("safety_blockers") or result.get("reasons") or []),
        "same_vendor_label_count": int(result.get("support_count") or 0) + int(result.get("contradiction_count") or 0),
        "same_vendor_route_count": 1 + (1 if int(result.get("contradiction_count") or 0) else 0),
        "autonomy_score": result.get("autonomy_score"),
        "support_share": result.get("support_share"),
        "performance": result.get("performance") or {},
        "earned_by": result.get("earned_by"),
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


# Deliberate compatibility alias for the monkey-patched evaluator slot.
decide_ap_route_with_authority_guard = decide_ap_route_with_learned_autonomy
