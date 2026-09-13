"""Composable AI-primary learned-autonomy AP routing pipeline for V117."""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence

from services.ap_routing_ai_primary_service import propose_ap_route_ai_primary
from services.ap_routing_learned_autonomy_service import evaluate_learned_autonomy
from services.ap_routing_learned_safety_service import apply_learned_autonomy_safety
from services.ap_routing_learning_service import normalize_route_path
from services.ap_routing_relevant_learning_service import build_relevant_learning_examples
from services.ap_routing_train_context_service import build_train_learning_context


_STRONG_LEADING_REFERENCE = re.compile(
    r"^(?:WTR[A-Z0-9_-]{2,20}|WA\d{3,8}[A-Z]?|W\d{4,8}[A-Z]?|\d{5,7}[A-Z]?)$",
    re.IGNORECASE,
)


def _leading_filename_reference(file_name: Any) -> str:
    """Return a strong leading business reference when the filename has one."""
    name = str(file_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", name).strip()
    if not stem or stem[0] in "_-":
        return ""
    first = re.split(r"[_\s]+", stem, maxsplit=1)[0].strip("-").upper()
    return first if _STRONG_LEADING_REFERENCE.fullmatch(first) else ""


def _exact_reference_filename_alignment_blocker(
    document: Dict[str, Any],
    autonomy_decision: Dict[str, Any],
) -> str:
    """Fail closed when exact-reference authority conflicts with filename identity.

    This is a safety veto only. It cannot choose a route or create authority.
    Exact-reference consensus is unusually strong, so when the current document
    itself exposes a strong leading order/warehouse reference, the BC reference
    that earned authority must agree with it. This prevents date-like resolver
    winners (for example 091026 -> 91026) from earning autonomy for a different
    leading order such as 119065.
    """
    if str(autonomy_decision.get("earned_by") or "") != "exact_reference_human_consensus":
        return ""
    leading = _leading_filename_reference(document.get("file_name"))
    if not leading:
        return ""
    exact = autonomy_decision.get("exact_reference_authority") or {}
    current_refs = {
        str(value or "").strip().upper()
        for value in (exact.get("current_refs") or [])
        if str(value or "").strip()
    }
    if leading in current_refs:
        return ""
    refs_text = ",".join(sorted(current_refs)) if current_refs else "none"
    return (
        "exact-reference authority winning BC reference "
        + refs_text
        + " conflicts with current filename leading reference "
        + leading
    )


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

    Prompt examples teach the AI. A bounded full-TRAIN summary supplements those
    examples with human workflow distributions and granularity. The independent
    authority layer then decides whether the AI's exact route has earned action.
    No stage after the model may select a different route.
    """
    prompt_limit = max(1, min(8, int(relevant_limit or 8)))
    document_with_context = {
        **document,
        "bc_context": bc_context or document.get("bc_context") or {},
    }
    relevant: List[Dict[str, Any]] = build_relevant_learning_examples(
        document_with_context,
        train_examples,
        limit=prompt_limit,
    )
    learning_context = build_train_learning_context(
        document_with_context,
        train_examples,
        contract=contract,
    )
    kwargs: Dict[str, Any] = {
        "document": document,
        "bc_context": bc_context or {},
        "contract": contract,
        "examples": relevant,
        "learning_context": learning_context,
        "llm_send": llm_send,
    }
    if model:
        kwargs["model"] = model
    ai = await propose_ap_route_ai_primary(**kwargs)

    autonomy = evaluate_learned_autonomy(
        document=document_with_context,
        ai_decision=ai,
        train_examples=train_examples,
        contract=contract,
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
    autonomy["train_learning_context_active"] = True
    autonomy["train_learning_context_example_count"] = int(
        learning_context.get("eligible_train_example_count") or 0
    )
    autonomy["train_learning_context_current_reference_family"] = learning_context.get(
        "current_reference_family"
    )
    autonomy["train_learning_context_current_semantic_features"] = learning_context.get(
        "current_semantic_features"
    ) or []

    combined_hard_blockers = [str(item) for item in hard_blockers if str(item).strip()]
    exact_reference_alignment_blocker = _exact_reference_filename_alignment_blocker(
        document,
        autonomy,
    )
    if exact_reference_alignment_blocker:
        combined_hard_blockers.append(exact_reference_alignment_blocker)

    final = apply_learned_autonomy_safety(
        document=document,
        autonomy_decision=autonomy,
        contract=contract,
        bc_context=bc_context or {},
        hard_blockers=combined_hard_blockers,
        support_examples=train_examples,
    )
    final["ai_primary_router"] = True
    final["learned_autonomy_active"] = True
    final["self_training_blocked"] = True
    final["deterministic_route_substitution"] = False
    return final
