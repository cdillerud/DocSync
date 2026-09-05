"""High-specificity TRAIN-human anchor authority for AI-primary AP routing.

Nearest-neighbor authority intentionally requires local density. That is safe but
can underuse human knowledge when the current document carries a rare,
route-neutral workflow anchor that spans vendors or document types. This module
provides a second, deliberately tiny authority path for only the strongest
structural/semantic anchors.

It never chooses a route. It can only confirm whether the AI's exact proposed
route has unanimous human TRAIN support for the current anchor.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Sequence

from services.ap_routing_learned_features_service import reference_family, semantic_features
from services.ap_routing_learning_service import normalize_route_path
from services.ap_routing_relevant_learning_service import is_train_human_example


# Keep this set intentionally narrow. Generic concepts such as freight, return,
# storage, inventory, credit, W/numeric order references, etc. are NOT specific
# enough to grant authority across vendors/document types.
HIGH_SPECIFICITY_SEMANTIC_ANCHORS = frozenset({"explicit_stop_pay"})
HIGH_SPECIFICITY_REFERENCE_ANCHORS = frozenset({"wtr_reference", "wa_reference"})


def _row_id(row: Dict[str, Any]) -> str:
    return str(
        row.get("fingerprint")
        or row.get("source_item_id")
        or row.get("document_id")
        or row.get("file_name")
        or ""
    )


def _label_source(row: Dict[str, Any]) -> str:
    return str(row.get("label_source") or row.get("source") or "").strip().lower()


def _rows_for_anchor(
    rows: Sequence[Dict[str, Any]],
    *,
    anchor_type: str,
    anchor: str,
) -> List[Dict[str, Any]]:
    if anchor_type == "semantic":
        return [row for row in rows if anchor in semantic_features(row)]
    if anchor_type == "reference_family":
        return [row for row in rows if reference_family(row) == anchor]
    return []


def summarize_high_specificity_anchor_authority(
    *,
    document: Dict[str, Any],
    proposed_route: str,
    train_examples: Sequence[Dict[str, Any]],
    minimum_support: int = 5,
) -> Dict[str, Any]:
    """Measure unanimous human support for the AI's exact route and current anchor."""
    proposed = normalize_route_path(proposed_route)
    eligible = [dict(row) for row in train_examples if is_train_human_example(row)]

    current_semantics = semantic_features(document)
    current_reference = reference_family(document)
    anchors: List[Dict[str, str]] = [
        {"type": "semantic", "anchor": feature}
        for feature in sorted(current_semantics.intersection(HIGH_SPECIFICITY_SEMANTIC_ANCHORS))
    ]
    if current_reference in HIGH_SPECIFICITY_REFERENCE_ANCHORS:
        anchors.append({"type": "reference_family", "anchor": current_reference})

    measurements: List[Dict[str, Any]] = []
    for current in anchors:
        matched = _rows_for_anchor(
            eligible,
            anchor_type=current["type"],
            anchor=current["anchor"],
        )
        route_counts = Counter(
            normalize_route_path(row.get("route_path") or row.get("final_human_route"))
            for row in matched
            if normalize_route_path(row.get("route_path") or row.get("final_human_route"))
        )
        support = [
            row
            for row in matched
            if normalize_route_path(row.get("route_path") or row.get("final_human_route")) == proposed
        ]
        contradictions = [
            row
            for row in matched
            if normalize_route_path(row.get("route_path") or row.get("final_human_route")) != proposed
        ]
        correction_contradictions = [
            row for row in contradictions if _label_source(row) == "reviewer_correction"
        ]
        authority_ready = bool(
            proposed
            and len(support) >= max(1, int(minimum_support))
            and len(contradictions) == 0
            and len(correction_contradictions) == 0
        )
        measurements.append(
            {
                "anchor_type": current["type"],
                "anchor": current["anchor"],
                "matched_human_count": len(matched),
                "support_count": len(support),
                "contradiction_count": len(contradictions),
                "reviewer_correction_contradictions": len(correction_contradictions),
                "route_counts": [
                    {"route_path": route, "count": count}
                    for route, count in route_counts.most_common(8)
                ],
                "support_example_ids": [_row_id(row) for row in support[:8]],
                "contradiction_example_ids": [_row_id(row) for row in contradictions[:8]],
                "minimum_support": max(1, int(minimum_support)),
                "authority_ready": authority_ready,
            }
        )

    earned = [measurement for measurement in measurements if measurement["authority_ready"]]
    earned.sort(
        key=lambda measurement: (
            int(measurement["support_count"]),
            -int(measurement["contradiction_count"]),
        ),
        reverse=True,
    )
    best = earned[0] if earned else None
    return {
        "purpose": "CONFIRM_AI_EXACT_ROUTE_ONLY_NO_ROUTE_SELECTION",
        "proposed_route": proposed,
        "current_high_specificity_anchors": anchors,
        "measurements": measurements,
        "authority_ready": bool(best),
        "earned_anchor_type": best.get("anchor_type") if best else "",
        "earned_anchor": best.get("anchor") if best else "",
        "support_count": int(best.get("support_count") or 0) if best else 0,
        "contradiction_count": int(best.get("contradiction_count") or 0) if best else 0,
        "minimum_support": max(1, int(minimum_support)),
    }
