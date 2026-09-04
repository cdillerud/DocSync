"""Relevant TRAIN-only human learning retrieval for AP routing.

This module selects examples for the AI. It does not select a route.
Only human-resolved Gamer Accounting evidence is eligible. Unreviewed AI
predictions and held-out examples are explicitly excluded.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Sequence

from services.ap_routing_learned_features_service import feature_similarity
from services.ap_routing_learning_service import (
    LABEL_SOURCE_ACCOUNTING_TEMP,
    LABEL_SOURCE_REVIEWER_CORRECTION,
    normalize_route_path,
    normalize_vendor_name,
    score_example_similarity,
)

LABEL_SOURCE_REVIEWER_CONFIRMATION = "reviewer_confirmation"
HUMAN_AUTHORITY_SOURCES = {
    LABEL_SOURCE_ACCOUNTING_TEMP,
    LABEL_SOURCE_REVIEWER_CORRECTION,
    LABEL_SOURCE_REVIEWER_CONFIRMATION,
}


def _document_vendor(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    return str(
        document.get("vendor_name")
        or document.get("vendor_canonical")
        or fields.get("vendor")
        or ""
    )


def _document_type(document: Dict[str, Any]) -> str:
    return str(
        document.get("document_type")
        or document.get("suggested_job_type")
        or (document.get("extracted_fields") or {}).get("document_type")
        or ""
    )


def is_train_human_example(example: Dict[str, Any]) -> bool:
    """Return True only for human-authoritative TRAIN evidence."""
    source = str(example.get("label_source") or example.get("source") or "").lower()
    if source not in HUMAN_AUTHORITY_SOURCES:
        return False
    if example.get("active") is False:
        return False
    if bool(example.get("is_holdout")):
        return False
    split = str(example.get("split") or example.get("evaluation_split") or "").lower()
    if split in {"holdout", "test", "validation"}:
        return False
    if bool(example.get("ai_generated")) and not bool(example.get("human_resolved")):
        return False
    return bool(normalize_route_path(example.get("route_path") or example.get("final_human_route")))


def _authority_bonus(example: Dict[str, Any]) -> float:
    source = str(example.get("label_source") or example.get("source") or "").lower()
    if source == LABEL_SOURCE_REVIEWER_CORRECTION:
        return 6.0
    if source == LABEL_SOURCE_REVIEWER_CONFIRMATION:
        return 3.0
    return 1.0


def _same_vendor(document: Dict[str, Any], example: Dict[str, Any]) -> bool:
    wanted = normalize_vendor_name(_document_vendor(document))
    found = normalize_vendor_name(
        example.get("vendor_name") or example.get("normalized_vendor") or ""
    )
    return bool(wanted and found and wanted == found)


def _same_document_type(document: Dict[str, Any], example: Dict[str, Any]) -> bool:
    wanted = _document_type(document).strip().lower()
    found = str(example.get("document_type") or example.get("suggested_job_type") or "").strip().lower()
    return bool(wanted and found and wanted == found)


def learned_relevance_score(document: Dict[str, Any], example: Dict[str, Any]) -> float:
    """Route-neutral relevance used for prompt retrieval and authority neighborhoods."""
    score = score_example_similarity(
        example,
        vendor_name=_document_vendor(document),
        document_type=_document_type(document),
        bc_context=document.get("bc_context") or {},
        file_name=str(document.get("file_name") or ""),
        raw_text=str(document.get("raw_text") or document.get("raw_text_excerpt") or ""),
        extracted_fields=document.get("extracted_fields") or {},
    )
    score += float(feature_similarity(document, example).get("score") or 0.0)
    score += _authority_bonus(example)
    if _same_vendor(document, example):
        score += 4.0
    if _same_document_type(document, example):
        score += 2.0
    return round(score, 4)


def build_relevant_learning_examples(
    current_document: Dict[str, Any],
    examples: Sequence[Dict[str, Any]],
    *,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """Return the strongest TRAIN examples plus a small boundary contrast set.

    Prompt retrieval and autonomy authority are intentionally separate. This
    function teaches the AI. A different service independently decides whether
    the AI's exact route has earned authority.
    """
    if limit <= 0:
        return []

    eligible = [dict(e) for e in examples if is_train_human_example(e)]
    if not eligible:
        return []

    for row in eligible:
        row["_learned_relevance_score"] = learned_relevance_score(current_document, row)
        row["_learned_same_vendor"] = _same_vendor(current_document, row)
        row["_learned_same_document_type"] = _same_document_type(current_document, row)
        row["_learned_feature_similarity"] = feature_similarity(current_document, row)

    ranked = sorted(
        eligible,
        key=lambda row: (
            row["_learned_relevance_score"],
            str(row.get("label_source") or "") == LABEL_SOURCE_REVIEWER_CORRECTION,
        ),
        reverse=True,
    )

    selected: List[Dict[str, Any]] = []
    seen = set()

    def add(row: Dict[str, Any]) -> None:
        key = str(
            row.get("fingerprint")
            or row.get("source_item_id")
            or row.get("document_id")
            or f"{row.get('file_name')}|{row.get('route_path')}|{len(seen)}"
        )
        if key in seen or len(selected) >= limit:
            return
        seen.add(key)
        selected.append(row)

    # The AI should mostly see the nearest learned cases, not a miniature route
    # catalog. With limit=8 this reserves six slots for strongest similarity.
    core_limit = max(1, min(limit, int(round(limit * 0.75))))
    for row in ranked:
        add(row)
        if len(selected) >= core_limit:
            break

    # Add at most two strongest same-vendor route contrasts. This teaches the
    # decision boundary without letting deliberately contradictory examples
    # dominate the prompt.
    same_vendor_rows = [row for row in ranked if row.get("_learned_same_vendor")]
    selected_routes = {normalize_route_path(row.get("route_path")) for row in selected}
    contrast_budget = min(2, max(0, limit - len(selected)))
    for row in same_vendor_rows:
        if contrast_budget <= 0 or len(selected) >= limit:
            break
        route = normalize_route_path(row.get("route_path"))
        if not route or route in selected_routes:
            continue
        before = len(selected)
        add(row)
        if len(selected) > before:
            selected_routes.add(route)
            contrast_budget -= 1

    # Reviewer corrections are valuable boundary cases. Only use remaining
    # capacity so a correction cannot evict the most relevant current pattern.
    for row in ranked:
        if len(selected) >= limit:
            break
        if str(row.get("label_source") or "") == LABEL_SOURCE_REVIEWER_CORRECTION:
            add(row)

    for row in ranked:
        add(row)
        if len(selected) >= limit:
            break

    return selected
