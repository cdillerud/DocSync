"""Bounded TRAIN-only aggregate context for the AI-primary AP router.

The eight raw examples in the model prompt are deliberately small and local.
This service complements them with compact statistics from the full human TRAIN
set so the model can learn GPI workflow granularity without turning those
statistics into deterministic routing authority.

This module never proposes, selects, authorizes, or substitutes a route. It only
summarizes human-labelled evidence for the AI prompt.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Sequence

from services.ap_routing_learned_features_service import (
    feature_similarity,
    reference_family,
    semantic_features,
)
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name
from services.ap_routing_relevant_learning_service import (
    is_train_human_example,
    learned_relevance_score,
)


def _document_vendor(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    return normalize_vendor_name(
        document.get("vendor_name")
        or document.get("vendor_canonical")
        or fields.get("vendor")
        or fields.get("vendor_name")
        or ""
    )


def _document_type(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    return str(
        document.get("document_type")
        or document.get("suggested_job_type")
        or fields.get("document_type")
        or ""
    ).strip().lower()


def _row_vendor(row: Dict[str, Any]) -> str:
    fields = row.get("extracted_fields") or {}
    return normalize_vendor_name(
        row.get("vendor_name")
        or row.get("normalized_vendor")
        or fields.get("vendor")
        or ""
    )


def _row_type(row: Dict[str, Any]) -> str:
    return str(row.get("document_type") or row.get("suggested_job_type") or "").strip().lower()


def _bounded_route_counts(rows: Sequence[Dict[str, Any]], *, limit: int = 12) -> List[Dict[str, Any]]:
    counts = Counter(
        normalize_route_path(row.get("route_path") or row.get("final_human_route"))
        for row in rows
        if normalize_route_path(row.get("route_path") or row.get("final_human_route"))
    )
    return [
        {"route_path": route, "count": count}
        for route, count in counts.most_common(max(1, int(limit)))
    ]


def _dynamic_route_usage(
    rows: Sequence[Dict[str, Any]],
    *,
    contract: Dict[str, Any],
    limit_children: int = 6,
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for spec in contract.get("dynamic_routes") or []:
        prefix = normalize_route_path(spec.get("prefix"))
        if not prefix:
            continue
        parent_count = 0
        child_counts: Counter[str] = Counter()
        for row in rows:
            route = normalize_route_path(row.get("route_path") or row.get("final_human_route"))
            if route == prefix:
                parent_count += 1
            elif route.startswith(prefix + "/"):
                child_counts[route] += 1
        if not parent_count and not child_counts:
            continue
        result.append(
            {
                "prefix": prefix,
                "parent_count": parent_count,
                "dynamic_child_count": sum(child_counts.values()),
                "dynamic_children": [
                    {"route_path": route, "count": count}
                    for route, count in child_counts.most_common(max(1, int(limit_children)))
                ],
            }
        )
    return result


def build_train_learning_context(
    document: Dict[str, Any],
    train_examples: Sequence[Dict[str, Any]],
    *,
    contract: Dict[str, Any],
    neighborhood_limit: int = 24,
    route_limit: int = 12,
) -> Dict[str, Any]:
    """Summarize full human TRAIN evidence for prompt context only.

    The output intentionally contains observed route distributions but never a
    recommended route or an authority decision. The model must still interpret
    the current document, and the independent learned-authority/safety layers
    still decide whether the model's exact proposal can act automatically.
    """
    eligible = [dict(row) for row in train_examples if is_train_human_example(row)]
    vendor = _document_vendor(document)
    doc_type = _document_type(document)
    current_ref = reference_family(document)
    current_semantics = semantic_features(document)

    same_vendor = [row for row in eligible if vendor and _row_vendor(row) == vendor]
    same_vendor_same_type = [
        row for row in same_vendor
        if not doc_type or not _row_type(row) or _row_type(row) == doc_type
    ]
    same_reference = [
        row for row in eligible
        if current_ref != "descriptor_or_none" and reference_family(row) == current_ref
    ]

    ranked: List[Dict[str, Any]] = []
    for source in eligible:
        row = dict(source)
        row["_context_relevance_score"] = learned_relevance_score(document, row)
        row["_context_feature_similarity"] = feature_similarity(document, row)
        ranked.append(row)
    ranked.sort(key=lambda row: float(row.get("_context_relevance_score") or 0.0), reverse=True)
    nearest = ranked[: max(1, int(neighborhood_limit))]

    route_stats: Dict[str, Dict[str, Any]] = {}
    for row in nearest:
        route = normalize_route_path(row.get("route_path") or row.get("final_human_route"))
        if not route:
            continue
        stat = route_stats.setdefault(
            route,
            {
                "route_path": route,
                "support_count": 0,
                "best_relevance_score": 0.0,
                "same_vendor_count": 0,
                "same_document_type_count": 0,
                "reference_family_match_count": 0,
                "shared_semantic_features": Counter(),
            },
        )
        stat["support_count"] += 1
        score = float(row.get("_context_relevance_score") or 0.0)
        stat["best_relevance_score"] = max(float(stat["best_relevance_score"]), score)
        if vendor and _row_vendor(row) == vendor:
            stat["same_vendor_count"] += 1
        if doc_type and _row_type(row) == doc_type:
            stat["same_document_type_count"] += 1
        if current_ref != "descriptor_or_none" and reference_family(row) == current_ref:
            stat["reference_family_match_count"] += 1
        shared = set((row.get("_context_feature_similarity") or {}).get("shared_semantic_features") or [])
        for feature in shared:
            stat["shared_semantic_features"][str(feature)] += 1

    route_observations: List[Dict[str, Any]] = []
    ordered_stats = sorted(
        route_stats.values(),
        key=lambda item: (float(item["best_relevance_score"]), int(item["support_count"])),
        reverse=True,
    )[: max(1, int(route_limit))]
    for stat in ordered_stats:
        route_observations.append(
            {
                "route_path": stat["route_path"],
                "support_count": int(stat["support_count"]),
                "best_relevance_score": round(float(stat["best_relevance_score"]), 4),
                "same_vendor_count": int(stat["same_vendor_count"]),
                "same_document_type_count": int(stat["same_document_type_count"]),
                "reference_family_match_count": int(stat["reference_family_match_count"]),
                "shared_semantic_features": [
                    {"feature": feature, "count": count}
                    for feature, count in stat["shared_semantic_features"].most_common(8)
                ],
            }
        )

    return {
        "purpose": "TRAIN_HUMAN_PROMPT_CONTEXT_ONLY_NOT_ROUTING_AUTHORITY",
        "eligible_train_example_count": len(eligible),
        "current_vendor": vendor,
        "current_document_type": doc_type,
        "current_reference_family": current_ref,
        "current_semantic_features": sorted(current_semantics),
        "same_vendor_example_count": len(same_vendor),
        "same_vendor_route_counts": _bounded_route_counts(same_vendor, limit=route_limit),
        "same_vendor_same_type_example_count": len(same_vendor_same_type),
        "same_vendor_same_type_route_counts": _bounded_route_counts(
            same_vendor_same_type, limit=route_limit
        ),
        "same_reference_family_example_count": len(same_reference),
        "same_reference_family_route_counts": _bounded_route_counts(
            same_reference, limit=route_limit
        ),
        "nearest_human_route_observations": route_observations,
        "dynamic_route_usage_same_vendor": _dynamic_route_usage(
            same_vendor, contract=contract
        ),
        "dynamic_route_usage_nearest": _dynamic_route_usage(
            nearest, contract=contract
        ),
    }
