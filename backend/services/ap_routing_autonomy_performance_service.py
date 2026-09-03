"""Performance calibration for learned AP routing autonomy.

Autonomy is calibrated from historical AI-versus-human outcomes. Static route
frequency is not performance evidence. Only human-resolved outcomes count.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List

from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name


def _document_vendor(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    return normalize_vendor_name(
        document.get("vendor_name")
        or document.get("vendor_canonical")
        or fields.get("vendor")
        or ""
    )


def _document_type(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    return str(
        document.get("document_type")
        or document.get("suggested_job_type")
        or fields.get("document_type")
        or "unknown"
    ).strip().lower()


def _order_family(document: Dict[str, Any]) -> str:
    context = document.get("bc_context") or {}
    return str(
        context.get("order_family")
        or context.get("order_type")
        or context.get("route_family")
        or "unknown"
    ).strip().lower()


def learned_pattern_signature(document: Dict[str, Any], proposed_route: str) -> str:
    """Stable pattern key for measuring AI performance without using truth labels."""
    return "|".join(
        [
            _document_vendor(document) or "unknown_vendor",
            _document_type(document),
            _order_family(document),
            normalize_route_path(proposed_route) or "no_route",
        ]
    )


def wilson_lower_bound(correct: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    p = correct / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    centre = p + z2 / (2.0 * total)
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * total)) / total)
    return max(0.0, min(1.0, (centre - margin) / denominator))


def normalize_performance_outcome(outcome: Dict[str, Any]) -> Dict[str, Any] | None:
    """Normalize one outcome, rejecting unresolved/self-generated pseudo-truth."""
    if not outcome.get("human_resolved"):
        return None
    proposed = normalize_route_path(
        outcome.get("ai_proposed_route")
        or outcome.get("proposed_route")
        or ((outcome.get("prediction") or {}).get("proposed_route"))
    )
    final = normalize_route_path(outcome.get("final_human_route") or outcome.get("route_path"))
    if not proposed or not final:
        return None
    document = {
        "vendor_name": outcome.get("vendor_name") or outcome.get("normalized_vendor") or "",
        "document_type": outcome.get("document_type") or "",
        "bc_context": outcome.get("bc_context") or {},
        "extracted_fields": outcome.get("extracted_fields") or {},
    }
    return {
        "pattern_signature": learned_pattern_signature(document, proposed),
        "ai_proposed_route": proposed,
        "final_human_route": final,
        "correct": proposed == final,
        "resolved_at": str(outcome.get("resolved_at") or outcome.get("updated_at") or ""),
        "label_source": str(outcome.get("label_source") or ""),
    }


def summarize_pattern_performance(
    *,
    document: Dict[str, Any],
    proposed_route: str,
    outcomes: Iterable[Dict[str, Any]],
    minimum_observations: int = 5,
) -> Dict[str, Any]:
    signature = learned_pattern_signature(document, proposed_route)
    normalized: List[Dict[str, Any]] = []
    for raw in outcomes:
        item = normalize_performance_outcome(raw)
        if item and item["pattern_signature"] == signature:
            normalized.append(item)

    observations = len(normalized)
    correct = sum(1 for item in normalized if item["correct"])
    wrong = observations - correct
    accuracy = (correct / observations) if observations else None
    lower = wilson_lower_bound(correct, observations) if observations else 0.0

    # V117 policy is deliberately strict: a recorded wrong human-resolved
    # outcome suspends earned autonomy for this exact learned pattern. Later
    # rehabilitation can be implemented with a versioned pattern epoch rather
    # than forgetting the error.
    suspended = wrong > 0
    return {
        "pattern_signature": signature,
        "observations": observations,
        "correct": correct,
        "wrong": wrong,
        "accuracy": accuracy,
        "wilson_lower_bound": lower,
        "minimum_observations": int(minimum_observations),
        "sufficient_observations": observations >= minimum_observations,
        "suspended": suspended,
        "suspension_reason": "historical human-resolved AI error" if suspended else "",
    }
