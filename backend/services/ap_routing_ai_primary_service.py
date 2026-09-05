"""AI-primary AP route proposal.

Unlike the legacy V117 decision path, this service does not replace the model's
route with a supervised-consensus route. Human examples inform the prompt; the
AI still owns the proposed route. Learned autonomy and the safety envelope may
only grant authority or abstain afterward.
"""

from __future__ import annotations

import json
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


def _prompt_learning_example(example: Dict[str, Any]) -> Dict[str, Any]:
    """Expose the bounded semantics that made a human example relevant."""
    row = dict(example)
    extracted = dict(example.get("extracted_fields") or {})
    excerpt = str(example.get("raw_text_excerpt") or example.get("raw_text") or "")[:1600]
    row["key_evidence"] = {
        "extracted_fields": extracted,
        "semantic_excerpt": excerpt,
    }
    return row


def _augment_prompt_with_train_context(prompt: str, learning_context: Optional[Dict[str, Any]]) -> str:
    """Add bounded full-TRAIN statistics and exact workflow-granularity rules.

    `build_route_prompt` remains shared with the legacy bounded router. The
    AI-primary path enriches only its own prompt, keeping the new learned context
    isolated from deterministic/runtime authority code.
    """
    if not learning_context:
        return prompt
    marker = "INPUT:\n"
    if marker not in prompt:
        return prompt
    prefix, payload_text = prompt.split(marker, 1)
    try:
        payload = json.loads(payload_text)
    except Exception:
        return prompt
    payload["train_learning_context"] = learning_context
    learned_rules = (
        "Additional TRAIN-learning rules:\n"
        "9. train_learning_context summarizes HUMAN TRAIN labels only. It is prompt context, not automatic authority. "
        "Use it to resolve GPI workflow granularity and to avoid inventing a route pattern from one example.\n"
        "10. A verified BC/order reference does NOT by itself justify a dynamic child such as "
        "Dropship International/<reference> or Warehouse International/<reference>. Propose a dynamic child only when "
        "the TRAIN context shows comparable human labels using dynamic children under that prefix. If the comparable "
        "human pattern uses the parent, keep the parent.\n"
        "11. Process-state leaves such as 'Ready to process Purch Inv' and 'Sales Order not posted' are GPI workflow "
        "states. BC open/posted/receipt status alone is insufficient; require comparable human-labelled evidence for "
        "that exact leaf.\n"
        "12. Do not stop at a generic workflow parent when comparable human labels consistently use a specific child. "
        "Use the exact observed leaf when the evidence supports it; otherwise lower confidence and list the ambiguity "
        "in unresolved instead of inventing a child.\n"
        "13. DO NOT PAY is exceptional. Do not infer it merely from a generic correction, a sales-shipment match, a "
        "missing/mismatched PO, a credit memo, or unrelated historical DNP examples. Require current stop-pay/invalidation "
        "evidence or a highly comparable human-labelled pattern.\n"
        "14. A credit memo by itself does not imply DO NOT PAY or a specialized credit-memo child. The current document "
        "purpose and learned human workflow decide the exact queue.\n"
        "15. WTR/WA/W reference families are structural workflow evidence. Do not collapse a transfer/assembly/warehouse "
        "pattern into a generic return, freight, or special-handling interpretation when human labels show a more specific "
        "GPI workflow.\n\n"
    )
    return prefix + learned_rules + marker + json.dumps(payload, ensure_ascii=False, default=str)


async def propose_ap_route_ai_primary(
    *,
    document: Dict[str, Any],
    bc_context: Optional[Dict[str, Any]],
    contract: Dict[str, Any],
    examples: List[Dict[str, Any]],
    learning_context: Optional[Dict[str, Any]] = None,
    model: str = DEFAULT_MODEL,
    llm_send: Optional[Callable[[str, str], Awaitable[Any]]] = None,
) -> Dict[str, Any]:
    """Ask the model for a route and preserve that route exactly for audit.

    No deterministic or supervised service may substitute another route here.
    The raw examples and full-TRAIN summary are prompt evidence only.
    """
    evidence = _document_evidence(document)
    context = bc_context or {}
    prompt_examples = [_prompt_learning_example(item) for item in examples[:8]]
    support = _supervised_route_support(document, context, prompt_examples)
    prompt = build_route_prompt(
        document,
        context,
        prompt_examples,
        contract,
        supervised_support=support,
    )
    prompt = _augment_prompt_with_train_context(prompt, learning_context)
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
        "few_shot_count": len(prompt_examples),
        "few_shot_routes": sorted(
            {
                normalize_route_path(item.get("route_path"))
                for item in prompt_examples
                if normalize_route_path(item.get("route_path"))
            }
        ),
        "prompt_semantic_excerpt_count": sum(
            1
            for item in prompt_examples
            if str((item.get("key_evidence") or {}).get("semantic_excerpt") or "").strip()
        ),
        "train_learning_context_active": bool(learning_context),
        "train_learning_context_example_count": int(
            (learning_context or {}).get("eligible_train_example_count") or 0
        ),
        "supervised_route_support_for_prompt_only": support,
        "route_selected_by": "ai_model",
        "supervised_route_substitution": False,
    }
