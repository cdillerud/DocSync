"""TRAIN-only corroboration authority for AI-primary AP routing.

The nearest-neighbor authority is intentionally strict and can abstain when one
high-scoring contradiction ties a much larger human pattern. This module adds a
second learned authority view over route-neutral TRAIN slices. It never selects
or substitutes a route. It can only confirm the AI's exact proposal when a
sufficiently large, high-purity human slice corroborates that proposal.

This is deliberately different from vendor frequency. A slice must include the
current document type plus either the same vendor alone at high purity, the same
vendor and structural reference family, or a route-neutral cross-vendor
workflow signature. Sparse/global route popularity cannot earn autonomy.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Sequence

from services.ap_routing_learned_features_service import reference_family, semantic_features
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name
from services.ap_routing_relevant_learning_service import is_train_human_example


DNP = "DO NOT PAY"
STRUCTURAL_REFERENCE_FAMILIES = frozenset(
    {"w_reference", "wtr_reference", "wa_reference", "numeric_reference", "alpha_reference"}
)
DISCRIMINATING_SEMANTICS = frozenset(
    {
        "detention",
        "dunnage",
        "inventory",
        "reconciliation",
        "cost_variance",
        "quality_or_claim",
        "storage_accessorial",
    }
)


def _vendor(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    return normalize_vendor_name(
        document.get("vendor_name")
        or document.get("vendor_canonical")
        or fields.get("vendor")
        or fields.get("vendor_name")
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
    fields = row.get("extracted_fields") or {}
    return normalize_vendor_name(
        row.get("vendor_name")
        or row.get("normalized_vendor")
        or fields.get("vendor")
        or ""
    )


def _row_type(row: Dict[str, Any]) -> str:
    return str(row.get("document_type") or row.get("suggested_job_type") or "").strip().lower()


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


def _is_dynamic_child(route: str, contract: Dict[str, Any]) -> bool:
    normalized = normalize_route_path(route)
    for spec in contract.get("dynamic_routes") or []:
        prefix = normalize_route_path(spec.get("prefix"))
        if prefix and normalized.startswith(prefix + "/"):
            return True
    return False


def _measurement(
    *,
    name: str,
    rows: Sequence[Dict[str, Any]],
    proposed: str,
    confidence: float,
    minimum_support: int,
    minimum_purity: float,
    minimum_confidence: float,
    hard_blocked: bool,
) -> Dict[str, Any]:
    matched = [dict(row) for row in rows]
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
    purity = len(support) / len(matched) if matched else 0.0
    counts = Counter(
        normalize_route_path(row.get("route_path") or row.get("final_human_route"))
        for row in matched
        if normalize_route_path(row.get("route_path") or row.get("final_human_route"))
    )
    ready = bool(
        not hard_blocked
        and proposed
        and confidence >= minimum_confidence
        and len(support) >= minimum_support
        and purity >= minimum_purity
        and len(correction_contradictions) == 0
    )
    return {
        "slice": name,
        "matched_human_count": len(matched),
        "support_count": len(support),
        "contradiction_count": len(contradictions),
        "reviewer_correction_contradictions": len(correction_contradictions),
        "purity": round(purity, 4),
        "minimum_support": int(minimum_support),
        "minimum_purity": float(minimum_purity),
        "minimum_confidence": float(minimum_confidence),
        "route_counts": [
            {"route_path": route, "count": count}
            for route, count in counts.most_common(8)
        ],
        "support_example_ids": [_row_id(row) for row in support[:8]],
        "contradiction_example_ids": [_row_id(row) for row in contradictions[:8]],
        "authority_ready": ready,
    }


def summarize_train_corroboration_authority(
    *,
    document: Dict[str, Any],
    proposed_route: str,
    confidence: float,
    train_examples: Sequence[Dict[str, Any]],
    contract: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Confirm an exact AI proposal from high-purity route-neutral TRAIN slices."""
    proposed = normalize_route_path(proposed_route)
    contract = contract or {}
    confidence = float(confidence or 0.0)
    eligible = [dict(row) for row in train_examples if is_train_human_example(row)]
    vendor = _vendor(document)
    doc_type = _doc_type(document)
    current_ref = reference_family(document)
    current_semantics = semantic_features(document)
    dynamic_child = _is_dynamic_child(proposed, contract)

    hard_blockers: List[str] = []
    manual_only = {
        normalize_route_path(route)
        for route in (contract.get("manual_only_routes") or [])
        if normalize_route_path(route)
    }
    if proposed in manual_only:
        hard_blockers.append("AI proposal is manual-only")
    if "reversal_or_void" in current_semantics:
        hard_blockers.append("transaction reversal/void requires exception-matched neighborhood authority")
    if proposed == DNP and "explicit_stop_pay" not in current_semantics:
        hard_blockers.append("TRAIN corroboration cannot grant DO NOT PAY without explicit current stop-pay evidence")
    if "explicit_stop_pay" in current_semantics and proposed != DNP:
        hard_blockers.append("explicit current stop-pay evidence conflicts with payable AI proposal")

    same_vendor_same_type = [
        row
        for row in eligible
        if vendor
        and _row_vendor(row) == vendor
        and (not doc_type or _row_type(row) == doc_type)
    ]

    measurements: List[Dict[str, Any]] = []

    # Large same-vendor/same-document-type patterns may corroborate the exact
    # AI route even when one equally relevant counterexample makes the nearest
    # neighbor relevance margin zero. The human majority must still be strong.
    measurements.append(
        _measurement(
            name="same_vendor_same_document_type",
            rows=same_vendor_same_type,
            proposed=proposed,
            confidence=confidence,
            minimum_support=5 if not dynamic_child else 3,
            minimum_purity=0.90 if not dynamic_child else 1.0,
            minimum_confidence=0.90 if not dynamic_child else 0.98,
            hard_blocked=bool(hard_blockers),
        )
    )

    if current_ref in STRUCTURAL_REFERENCE_FAMILIES:
        same_ref = [
            row for row in same_vendor_same_type if reference_family(row) == current_ref
        ]
        measurements.append(
            _measurement(
                name="same_vendor_same_document_type_reference_family",
                rows=same_ref,
                proposed=proposed,
                confidence=confidence,
                minimum_support=5 if not dynamic_child else 3,
                minimum_purity=0.85 if not dynamic_child else 1.0,
                minimum_confidence=0.90 if not dynamic_child else 0.98,
                hard_blocked=bool(hard_blockers),
            )
        )

    semantic_signature = current_semantics.intersection(DISCRIMINATING_SEMANTICS)
    if semantic_signature:
        same_semantics = [
            row
            for row in same_vendor_same_type
            if semantic_signature.issubset(semantic_features(row))
        ]
        measurements.append(
            _measurement(
                name="same_vendor_same_document_type_semantic_signature",
                rows=same_semantics,
                proposed=proposed,
                confidence=confidence,
                minimum_support=3,
                minimum_purity=0.90,
                minimum_confidence=0.95,
                hard_blocked=bool(hard_blockers),
            )
        )

    # Cross-vendor corroboration is allowed only for a route-neutral structural
    # family plus document type and a discriminating semantic signature. This
    # cannot devolve into global route popularity.
    if (
        current_ref in STRUCTURAL_REFERENCE_FAMILIES
        and semantic_signature
        and doc_type
        and not dynamic_child
        and proposed != DNP
    ):
        cross_workflow = [
            row
            for row in eligible
            if _row_type(row) == doc_type
            and reference_family(row) == current_ref
            and semantic_signature.issubset(semantic_features(row))
        ]
        measurements.append(
            _measurement(
                name="cross_vendor_document_type_reference_semantics",
                rows=cross_workflow,
                proposed=proposed,
                confidence=confidence,
                minimum_support=8,
                minimum_purity=0.95,
                minimum_confidence=0.98,
                hard_blocked=bool(hard_blockers),
            )
        )

    earned = [row for row in measurements if row.get("authority_ready")]
    earned.sort(
        key=lambda row: (
            float(row.get("purity") or 0.0),
            int(row.get("support_count") or 0),
            int(row.get("matched_human_count") or 0),
        ),
        reverse=True,
    )
    best = earned[0] if earned else None
    return {
        "purpose": "CONFIRM_AI_EXACT_ROUTE_FROM_TRAIN_CORROBORATION_ONLY",
        "proposed_route": proposed,
        "confidence": confidence,
        "eligible_train_example_count": len(eligible),
        "current_vendor": vendor,
        "current_document_type": doc_type,
        "current_reference_family": current_ref,
        "current_semantic_features": sorted(current_semantics),
        "dynamic_child": dynamic_child,
        "hard_blockers": hard_blockers,
        "measurements": measurements,
        "authority_ready": bool(best),
        "earned_slice": str(best.get("slice") or "") if best else "",
        "support_count": int(best.get("support_count") or 0) if best else 0,
        "contradiction_count": int(best.get("contradiction_count") or 0) if best else 0,
        "purity": float(best.get("purity") or 0.0) if best else 0.0,
    }
