"""Compatibility adapter that makes the existing V117 evaluator AI-primary.

The evaluator still calls a function named like the legacy authority guard. This
adapter preserves that call contract while routing through the learned pipeline.
It does not use the legacy deterministic route selector. Selected pure legacy
helpers are reused only to identify universal safety conflicts; they can only
cause review and can never select a replacement route.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional

from services.ap_routing_authority_guard_service import (
    _bc_vendor_mismatch,
    _cross_vendor_exact_reference_dependency,
    _current_reference_family,
    _family_conflict,
    _manual_only_routes,
)
from services.ap_routing_learned_pipeline_service import decide_ap_route_learned
from services.ap_routing_learned_safety_service import apply_learned_autonomy_safety
from services.ap_routing_learning_service import normalize_route_path


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
        model=model,
        llm_send=llm_send,
    )

    # Universal V117 safety evidence remains useful, but only as a veto. None
    # of these helpers may replace the AI route.
    proposed = normalize_route_path(result.get("ai_proposed_route"))
    hard_blockers: List[str] = []
    if proposed in _manual_only_routes(contract):
        hard_blockers.append("AI proposed route is manual-only")
    ref_family = _current_reference_family(document, context)
    if proposed and ref_family and _family_conflict(ref_family, proposed):
        hard_blockers.append(f"reference-family conflict: {ref_family} vs {proposed}")
    if proposed and _bc_vendor_mismatch(document, context):
        hard_blockers.append("authoritative BC vendor context conflicts with current document vendor")
    if proposed and _cross_vendor_exact_reference_dependency(
        document,
        context,
        train,
        proposed,
        {
            "prediction": result.get("prediction") or {},
            "ensemble_reconciliation": {
                "original_prediction": result.get("prediction") or {},
                "original_model_route": proposed,
                "original_model_confidence": result.get("ai_confidence"),
            },
        },
    ):
        hard_blockers.append("cross-vendor exact-reference evidence was relied upon by the AI")

    if hard_blockers:
        result = apply_learned_autonomy_safety(
            document=document,
            autonomy_decision=result,
            contract=contract,
            bc_context=context,
            hard_blockers=hard_blockers,
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
        "hard_safety_blockers": hard_blockers,
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
