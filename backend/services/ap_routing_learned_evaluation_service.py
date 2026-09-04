"""V117 evaluation for AI-primary learned autonomy.

Promotion remains based only on automatic-route accuracy/coverage. Raw AI
proposal accuracy is shadow telemetry so model learning can be improved without
confusing a correct suggestion with an authorized automatic action.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Awaitable, Callable, Dict, List, Optional

from services.ap_routing_decision_service import DECISION_AUTO_ROUTE
from services.ap_routing_evaluation_service import split_train_holdout, summarize_evaluation
from services.ap_routing_learned_v117_adapter import decide_ap_route_with_learned_autonomy
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name

DEFAULT_FEW_SHOT_LIMIT = 8


def _document_from_example(example: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": example.get("document_id") or example.get("source_item_id"),
        "file_name": example.get("file_name"),
        "document_type": example.get("document_type"),
        "suggested_job_type": example.get("document_type"),
        "confidence": example.get("classification_confidence"),
        "vendor_canonical": example.get("vendor_name"),
        "vendor_name": example.get("vendor_name"),
        "extracted_fields": example.get("extracted_fields") or {},
        "normalized_fields": example.get("normalized_fields") or {},
        "raw_text": example.get("raw_text_excerpt") or example.get("raw_text") or "",
        "learned_feature_schema": example.get("learned_feature_schema"),
        "learned_semantic_features": example.get("learned_semantic_features") or [],
    }


async def evaluate_holdout_learned(
    *,
    examples: List[Dict[str, Any]],
    contract: Dict[str, Any],
    llm_send: Optional[Callable[[str, str], Awaitable[Any]]] = None,
    model: str = "gemini-2.5-pro",
    vendor_auto_thresholds: Optional[Dict[str, float]] = None,
    few_shot_limit: int = DEFAULT_FEW_SHOT_LIMIT,
) -> Dict[str, Any]:
    """Evaluate untouched holdout with AI-primary shadow + autonomy metrics."""
    del vendor_auto_thresholds
    train, holdout = split_train_holdout(examples)
    rows: List[Dict[str, Any]] = []
    prompt_limit = max(1, min(8, int(few_shot_limit or DEFAULT_FEW_SHOT_LIMIT)))

    for test in holdout:
        vendor = str(test.get("vendor_name") or "")
        vendor_key = normalize_vendor_name(vendor)
        result = await decide_ap_route_with_learned_autonomy(
            None,
            document=_document_from_example(test),
            bc_context=test.get("bc_context") or {},
            contract=contract,
            examples=[],
            support_examples=train,
            model=model,
            llm_send=llm_send,
            relevant_limit=prompt_limit,
        )
        expected = normalize_route_path(test.get("route_path"))
        predicted = normalize_route_path(result.get("route_path"))
        ai_proposed = normalize_route_path(
            result.get("ai_proposed_route")
            or ((result.get("prediction") or {}).get("proposed_route"))
        )
        auto = result.get("decision") == DECISION_AUTO_ROUTE
        correct = predicted == expected if auto else False
        ai_correct = bool(ai_proposed and ai_proposed == expected)
        ensemble = result.get("ensemble_reconciliation") or {}
        authority_guard = result.get("authority_guard") or {}
        prompt_routes = [str(route) for route in (result.get("prompt_routes") or []) if route]

        rows.append(
            {
                "example_id": test.get("fingerprint") or test.get("source_item_id"),
                "file_name": test.get("file_name"),
                "vendor_name": vendor,
                "normalized_vendor": vendor_key,
                "document_type": test.get("document_type"),
                "expected_route": expected,
                "predicted_route": predicted,
                "decision": result.get("decision"),
                "confidence": result.get("confidence"),
                "auto_routed": auto,
                "auto_route_correct": correct,
                "reason": result.get("reason"),
                "few_shot_count": int(result.get("prompt_example_count") or 0),
                "few_shot_routes": sorted(set(prompt_routes)),
                "prompt_routes_ordered": prompt_routes,
                "prompt_example_ids": result.get("prompt_example_ids") or [],
                "prompt_example_relevance_scores": result.get("prompt_example_relevance_scores") or [],
                "ai_proposed_route": ai_proposed,
                "ai_proposal_correct": ai_correct,
                "ai_proposal_confidence": result.get("ai_confidence"),
                "ai_reason": result.get("ai_reason"),
                "supervised_top_route": None,
                "supervised_margin": None,
                "supervised_strong": None,
                "full_supervised_top_route": None,
                "full_supervised_margin": None,
                "full_supervised_route_count": 0,
                "ensemble_action": ensemble.get("action"),
                "original_model_route": ai_proposed,
                "original_model_confidence": result.get("ai_confidence"),
                "authority_guard_action": authority_guard.get("action"),
                "authority_guard_blockers": authority_guard.get("blockers") or [],
                "same_vendor_label_count": authority_guard.get("same_vendor_label_count"),
                "same_vendor_route_count": authority_guard.get("same_vendor_route_count"),
                "neighborhood_scope": authority_guard.get("neighborhood_scope"),
                "neighborhood_count": authority_guard.get("neighborhood_count"),
                "neighborhood_support_count": authority_guard.get("support_count"),
                "neighborhood_contradiction_count": authority_guard.get("contradiction_count"),
                "neighborhood_support_share": authority_guard.get("support_share"),
                "neighborhood_support_margin": authority_guard.get("support_margin"),
                "neighborhood_routes": authority_guard.get("neighbor_routes") or [],
                "neighborhood_scores": authority_guard.get("neighbor_scores") or [],
                "current_semantic_features": authority_guard.get("current_semantic_features") or [],
                "exceptional_workflow_features": authority_guard.get("exceptional_workflow_features") or [],
                "exception_support_count": authority_guard.get("exception_support_count"),
                "exception_mismatch_support_count": authority_guard.get("exception_mismatch_support_count"),
                "exception_support_ready": authority_guard.get("exception_support_ready"),
                "learned_feature_schema": test.get("learned_feature_schema"),
                "earned_by": authority_guard.get("earned_by"),
                "autonomy_score": authority_guard.get("autonomy_score"),
                "hard_safety_blockers": authority_guard.get("hard_safety_blockers") or [],
            }
        )

    summary = summarize_evaluation(rows, train_count=len(train), holdout_count=len(holdout))
    ai_rows = [row for row in rows if row.get("ai_proposed_route")]
    ai_correct_rows = [row for row in ai_rows if row.get("ai_proposal_correct")]
    wrong_ai = [row for row in ai_rows if not row.get("ai_proposal_correct")]
    summary.update(
        {
            "routing_architecture": "AI_PRIMARY_LEARNED_AUTONOMY",
            "ai_proposal_count": len(ai_rows),
            "ai_proposal_correct_count": len(ai_correct_rows),
            "wrong_ai_proposal_count": len(wrong_ai),
            "ai_proposal_accuracy": (
                round(len(ai_correct_rows) / len(ai_rows), 4) if ai_rows else None
            ),
            "wrong_ai_proposal_examples": wrong_ai[:25],
            "actual_prompt_limit": prompt_limit,
        }
    )

    confidence_bands = []
    for threshold in (0.85, 0.90, 0.95, 0.98, 1.0):
        eligible = [
            row for row in ai_rows
            if float(row.get("ai_proposal_confidence") or 0.0) >= threshold
        ]
        correct_band = [row for row in eligible if row.get("ai_proposal_correct")]
        confidence_bands.append(
            {
                "minimum_confidence": threshold,
                "proposal_count": len(eligible),
                "correct_count": len(correct_band),
                "proposal_accuracy": round(len(correct_band) / len(eligible), 4) if eligible else None,
            }
        )
    summary["ai_proposal_confidence_bands"] = confidence_bands

    by_route = Counter(row.get("expected_route") or "unknown" for row in rows)
    summary["ai_shadow_expected_route_counts"] = dict(by_route)
    return summary


# Deliberately expose the conventional evaluator name for controller imports.
evaluate_holdout = evaluate_holdout_learned
