"""Composable AI-primary learned-autonomy AP routing pipeline for V117."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence

from services.ap_routing_ai_primary_service import propose_ap_route_ai_primary
from services.ap_routing_learned_autonomy_service import evaluate_learned_autonomy
from services.ap_routing_learned_safety_service import apply_learned_autonomy_safety
from services.ap_routing_learning_service import normalize_route_path
from services.ap_routing_relevant_learning_service import build_relevant_learning_examples


async def decide_ap_route_learned(
    *,
    document: Dict[str, Any],
    bc_context: Optional[Dict[str, Any]],
    contract: Dict[str, Any],
    train_examples: Sequence[Dict[str, Any]],
    performance_outcomes: Iterable[Dict[str, Any]] = (),
    hard_blockers: Iterable[str] = (),
    relevant_limit: int = 8,
    model: Optional[str] = None,
    llm_send: Optional[Callable[[str, str], Awaitable[Any]]] = None,
) -> Dict[str, Any]:
    """Run AI proposal -> learned authority -> fail-closed safety.

    Prompt examples teach the AI. The independent authority neighborhood decides
    whether the AI's exact proposal has earned autonomy. No stage after the
    model may select a different route.
    """
    prompt_limit = max(1, min(8, int(relevant_limit or 8)))
    relevant: List[Dict[str, Any]] = build_relevant_learning_examples(
        document,
        train_examples,
        limit=prompt_limit,
    )
    kwargs: Dict[str, Any] = {
        "document": document,
        "bc_context": bc_context or {},
        "contract": contract,
        "examples": relevant,
        "llm_send": llm_send,
    }
    if model:
        kwargs["model"] = model
    ai = await propose_ap_route_ai_primary(**kwargs)

    autonomy = evaluate_learned_autonomy(
        document={**document, "bc_context": bc_context or document.get("bc_context") or {}},
        ai_decision=ai,
        train_examples=train_examples,
        performance_outcomes=performance_outcomes,
        relevant_limit=8,
    )
    autonomy["prediction"] = ai.get("prediction") or {}
    autonomy["ai_confidence"] = ai.get("confidence")
    autonomy["ai_reason"] = ai.get("reason")
    autonomy["route_selected_by"] = "ai_model"
    autonomy["supervised_route_substitution"] = False
    autonomy["prompt_example_count"] = len(relevant)
    autonomy["prompt_example_ids"] = [
        str(item.get("fingerprint") or item.get("source_item_id") or item.get("document_id") or item.get("file_name") or "")
        for item in relevant
    ]
    autonomy["prompt_routes"] = [
        normalize_route_path(item.get("route_path"))
        for item in relevant
        if normalize_route_path(item.get("route_path"))
    ]
    autonomy["prompt_example_relevance_scores"] = [
        float(item.get("_learned_relevance_score") or 0.0)
        for item in relevant
    ]

    final = apply_learned_autonomy_safety(
        document=document,
        autonomy_decision=autonomy,
        contract=contract,
        bc_context=bc_context or {},
        hard_blockers=hard_blockers,
        support_examples=train_examples,
    )
    final["ai_primary_router"] = True
    final["learned_autonomy_active"] = True
    final["self_training_blocked"] = True
    final["deterministic_route_substitution"] = False
    return final
