"""AI-primary AP route proposal.

Unlike the legacy V117 decision path, this service does not replace the model's
route with a supervised-consensus route. Human examples inform the prompt; the
AI still owns the proposed route. Learned autonomy and the safety envelope may
only grant authority or abstain afterward.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from services.ap_routing_decision_service import (
    DEFAULT_MODEL,
    RoutePrediction,
    _default_llm_send,
    _document_evidence,
    _supervised_route_support,
    build_route_prompt,
    parse_route_prediction,
)
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name

logger = logging.getLogger(__name__)


async def propose_ap_route_ai_primary(
    *,
    document: Dict[str, Any],
    bc_context: Optional[Dict[str, Any]],
    contract: Dict[str, Any],
    examples: List[Dict[str, Any]],
    model: str = DEFAULT_MODEL,
    llm_send: Optional[Callable[[str, str], Awaitable[Any]]] = None,
) -> Dict[str, Any]:
    """Ask the model for a route and preserve that route exactly for audit.

    No deterministic or supervised service may substitute another route here.
    The support summary is supplied to the prompt as evidence only.
    """
    evidence = _document_evidence(document)
    context = bc_context or {}
    support = _supervised_route_support(document, context, examples)
    prompt = build_route_prompt(
        document,
        context,
        examples,
        contract,
        supervised_support=support,
    )
    sender = llm_send or _default_llm_send
    try:
        raw = await sender(prompt, model)
        prediction = parse_route_prediction(raw, model=model)
    except Exception as exc:
        logger.exception("AI-primary AP routing model call failed")
        prediction = RoutePrediction(
            proposed_route="",
            confidence=0.0,
            evidence=[],
            reasoning_summary="routing model failure",
            bc_refs_used=[],
            unresolved=[f"model_error:{type(exc).__name__}"],
            matched_example_ids=[],
            model=model,
        )

    proposed = normalize_route_path(prediction.proposed_route)
    return {
        "decision": "ai_proposal",
        "proposed_route": proposed,
        "route_path": proposed,
        "confidence": float(prediction.confidence),
        "reason": prediction.reasoning_summary,
        "evidence": list(prediction.evidence),
        "blockers": list(prediction.unresolved),
        "prediction": prediction.to_dict(),
        "vendor_name": evidence.get("vendor_name") or "",
        "normalized_vendor": normalize_vendor_name(evidence.get("vendor_name") or ""),
        "document_type": evidence.get("document_type") or "",
        "few_shot_count": len(examples),
        "few_shot_routes": sorted(
            {
                normalize_route_path(item.get("route_path"))
                for item in examples
                if normalize_route_path(item.get("route_path"))
            }
        ),
        "supervised_route_support_for_prompt_only": support,
        "route_selected_by": "ai_model",
        "supervised_route_substitution": False,
    }
