"""Nearest-neighbor human authority for AI-primary AP routing.

The AI owns the proposed route. This module measures whether nearby TRAIN-only
human decisions support that exact route strongly enough to earn autonomy. It
never chooses or substitutes a route.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from services.ap_routing_learned_features_service import reference_family, semantic_features
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name
from services.ap_routing_relevant_learning_service import (
    LABEL_SOURCE_REVIEWER_CONFIRMATION,
    is_train_human_example,
    learned_relevance_score,
)


def _vendor(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    return normalize_vendor_name(
        document.get("vendor_name")
        or document.get("vendor_canonical")
        or fields.get("vendor")
        or ""
    )


def _doc_type(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    return str(
        document.get("document_type")
        or document.get("suggested_job_type")
        or fields.get("document_type")
        or ""
    ).strip().lower()


def _row_vendor(row: Dict[str, Any]) -> str:
    return normalize_vendor_name(row.get("vendor_name") or row.get("normalized_vendor") or "")


def _row_type(row: Dict[str, Any]) -> str:
    return str(row.get("document_type") or row.get("suggested_job_type") or "").strip().lower()


def _label_multiplier(row: Dict[str, Any]) -> float:
    source = str(row.get("label_source") or row.get("source") or "").lower()
    if source == "reviewer_correction":
        return 3.0
    if source == LABEL_SOURCE_REVIEWER_CONFIRMATION:
        return 1.5
    return 1.0


def summarize_authority_neighborhood(
    *,
    document: Dict[str, Any],
    proposed_route: str,
    train_examples: Sequence[Dict[str, Any]],
    limit: int = 8,
    relevance_window: float = 4.0,
) -> Dict[str, Any]:
    proposed = normalize_route_path(proposed_route)
    vendor = _vendor(document)
    doc_type = _doc_type(document)
    eligible: List[Dict[str, Any]] = []

    for source in train_examples:
        if not is_train_human_example(source):
            continue
        row = dict(source)
        row["_authority_relevance_score"] = learned_relevance_score(document, row)
        eligible.append(row)

    same_vendor = [
        row for row in eligible
        if vendor and _row_vendor(row) == vendor
        and (not doc_type or not _row_type(row) or _row_type(row) == doc_type)
    ]

    current_semantics = semantic_features(document)
    current_ref = reference_family(document)
    structural_refs = {"wtr_reference", "wa_reference", "w_reference", "numeric_reference", "alpha_reference"}
    semantic_anchor = bool(current_semantics or current_ref in structural_refs)

    # Local history is preferred when it is large enough to describe a pattern.
    # Otherwise use a cross-vendor semantic neighborhood so generic workflows
    # can be learned rather than requiring one hard-coded rule per vendor.
    if len(same_vendor) >= 3:
        scope = "same_vendor"
        pool = same_vendor
        minimum_support = 3
        minimum_share = 0.80
        minimum_margin = 1.0
    else:
        scope = "semantic_cross_vendor"
        pool = [
            row for row in eligible
            if not doc_type or not _row_type(row) or _row_type(row) == doc_type
        ]
        minimum_support = 5
        minimum_share = 0.92
        minimum_margin = 1.5

    ranked = sorted(pool, key=lambda row: float(row.get("_authority_relevance_score") or 0.0), reverse=True)
    best_score = float(ranked[0].get("_authority_relevance_score") or 0.0) if ranked else 0.0
    neighborhood = [
        row for row in ranked
        if float(row.get("_authority_relevance_score") or 0.0) >= best_score - relevance_window
    ][: max(1, int(limit))]

    weighted = []
    for row in neighborhood:
        score = float(row.get("_authority_relevance_score") or 0.0)
        # Relative relevance is deliberately bounded. Labels closest to the
        # current document count more, while one outlier can never dominate.
        relative = max(0.5, min(5.0, score - (best_score - relevance_window) + 0.5))
        weight = relative * _label_multiplier(row)
        weighted.append((row, weight))

    support = [(row, weight) for row, weight in weighted if normalize_route_path(row.get("route_path")) == proposed]
    contradictions = [(row, weight) for row, weight in weighted if normalize_route_path(row.get("route_path")) != proposed]
    support_weight = sum(weight for _, weight in support)
    contradiction_weight = sum(weight for _, weight in contradictions)
    total_weight = support_weight + contradiction_weight
    share = support_weight / total_weight if total_weight else 0.0
    best_support = max((float(row.get("_authority_relevance_score") or 0.0) for row, _ in support), default=0.0)
    best_contradiction = max((float(row.get("_authority_relevance_score") or 0.0) for row, _ in contradictions), default=0.0)
    margin = best_support - best_contradiction if contradictions else best_support
    correction_contradictions = sum(
        1
        for row, _ in contradictions
        if str(row.get("label_source") or "").lower() == "reviewer_correction"
    )

    authority_ready = bool(
        proposed
        and len(support) >= minimum_support
        and share >= minimum_share
        and margin >= minimum_margin
        and correction_contradictions == 0
        and (scope == "same_vendor" or semantic_anchor)
    )

    return {
        "scope": scope,
        "proposed_route": proposed,
        "eligible_count": len(eligible),
        "same_vendor_candidate_count": len(same_vendor),
        "neighborhood_count": len(neighborhood),
        "support_count": len(support),
        "contradiction_count": len(contradictions),
        "support_weight": round(support_weight, 4),
        "contradiction_weight": round(contradiction_weight, 4),
        "support_share": round(share, 4),
        "best_relevance_score": round(best_score, 4),
        "best_support_score": round(best_support, 4),
        "best_contradiction_score": round(best_contradiction, 4),
        "support_margin": round(margin, 4),
        "reviewer_correction_contradictions": correction_contradictions,
        "minimum_support": minimum_support,
        "minimum_support_share": minimum_share,
        "minimum_support_margin": minimum_margin,
        "semantic_anchor": semantic_anchor,
        "current_reference_family": current_ref,
        "current_semantic_features": sorted(current_semantics),
        "authority_ready": authority_ready,
        "neighbor_routes": [normalize_route_path(row.get("route_path")) for row in neighborhood],
        "neighbor_ids": [
            str(row.get("fingerprint") or row.get("source_item_id") or row.get("document_id") or row.get("file_name") or "")
            for row in neighborhood
        ],
        "neighbor_scores": [round(float(row.get("_authority_relevance_score") or 0.0), 4) for row in neighborhood],
    }
