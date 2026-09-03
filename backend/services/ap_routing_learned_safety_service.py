"""Minimal fail-closed safety envelope for learned AP autonomy.

Safety may demote an earned AI route to review. It must never choose a
replacement route. Broad hazards belong here; vendor-specific templates do not.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from services.ap_routing_decision_service import route_is_allowed
from services.ap_routing_learning_service import normalize_route_path

_STOP_PAY = re.compile(
    r"\b(?:do\s+not\s+pay|don['’]?t\s+pay|dont\s+pay|do\s+not\s+process|hold\s+payment)\b",
    re.IGNORECASE,
)


def _document_text(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    return " ".join(
        [
            str(document.get("file_name") or ""),
            str(document.get("raw_text") or document.get("raw_text_excerpt") or "")[:20000],
            " ".join(str(value) for value in fields.values()),
        ]
    )


def apply_learned_autonomy_safety(
    *,
    document: Dict[str, Any],
    autonomy_decision: Dict[str, Any],
    contract: Dict[str, Any],
    bc_context: Optional[Dict[str, Any]] = None,
    hard_blockers: Iterable[str] = (),
) -> Dict[str, Any]:
    proposed = normalize_route_path(autonomy_decision.get("ai_proposed_route") or "")
    decision = str(autonomy_decision.get("decision") or "needs_review")
    blockers: List[str] = [str(item) for item in hard_blockers if str(item).strip()]

    if decision != "auto_route":
        result = dict(autonomy_decision)
        result["safety_action"] = "preserve_review"
        result["safety_blockers"] = blockers
        result["route_path"] = ""
        return result

    # Safety can only assess the exact AI proposal.
    if not proposed or normalize_route_path(autonomy_decision.get("route_path")) != proposed:
        blockers.append("learned autonomy attempted to alter the AI proposed route")

    if proposed and not route_is_allowed(proposed, contract, bc_context or {}):
        blockers.append(f"AI proposed route is not allowed by current route contract: {proposed}")

    text = _document_text(document)
    if _STOP_PAY.search(text) and proposed.strip().lower() != "do not pay":
        blockers.append("explicit current-document stop-pay instruction conflicts with proposed payable route")

    prediction = autonomy_decision.get("prediction") or {}
    unresolved = list(prediction.get("unresolved") or autonomy_decision.get("model_unresolved") or [])
    if unresolved:
        blockers.append("AI reported unresolved/model-error evidence")

    result = dict(autonomy_decision)
    if blockers:
        result.update(
            {
                "decision": "needs_review",
                "route_path": "",
                "safety_action": "demote_to_review",
                "safety_blockers": blockers,
                "pre_safety_autonomy_tier": autonomy_decision.get("autonomy_tier"),
            }
        )
    else:
        result.update(
            {
                "decision": "auto_route",
                "route_path": proposed,
                "safety_action": "allow_ai_route",
                "safety_blockers": [],
            }
        )
    result["route_preserved"] = result.get("route_path") in {"", proposed}
    return result
