"""Nearest-neighbor human authority for AI-primary AP routing.

The AI owns the proposed route. This module measures whether nearby TRAIN-only
human decisions support that exact route strongly enough to earn autonomy. It
never chooses or substitutes a route.
"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any, Dict, List, Sequence

from services.ap_routing_learned_features_service import reference_family, semantic_features
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name
from services.ap_routing_relevant_learning_service import (
    LABEL_SOURCE_REVIEWER_CONFIRMATION,
    is_train_human_example,
    learned_relevance_score,
)


# Only transaction-reversal semantics require exception-matched human support.
# Explicit stop-pay remains governed by the existing safety envelope, and
# replacement/offset remains a route-neutral relevance feature. Keeping those
# concerns separate preserves established DNP autonomy while preventing an
# ordinary transaction neighborhood from authorizing a reversal/void document.
EXCEPTIONAL_WORKFLOW_FEATURES = frozenset({"reversal_or_void"})

# Exact-reference authority is intentionally stricter than the broad
# fail-closed safety reference set. Only a resolved winning BC PO/document is
# eligible to earn authority. Legacy verified_order_numbers remain useful for
# read-only diagnostics but can never earn exact-reference autonomy by itself.
_STRICT_VERIFIED_BC_REF = re.compile(
    r"^(?:"
    r"\d{4,7}(?:[-/]\d{1,3})?"
    r"|[A-Z]{1,3}-?\d{3,7}[A-Z]?(?:[-/]\d{1,3})?"
    r"|\d{5,7}[A-Z_]\w{0,3}"
    r")$"
)
_VERIFIED_CONTEXT_STATUSES = frozenset({"resolved", "resolved_shipment", "matched", "verified"})


def _normalize_bc_ref_values(values: Sequence[Any]) -> set[str]:
    refs = set()
    for value in values:
        token = str(value or "").strip().upper()
        if token and _STRICT_VERIFIED_BC_REF.fullmatch(token):
            refs.add(token)
    return refs


def _resolved_winning_bc_refs(context: Dict[str, Any]) -> set[str]:
    """Return only authoritative resolver-winning BC references.

    This deliberately excludes alternate matches and legacy verified-order
    collections. It is the only reference source allowed to earn exact-reference
    autonomy.
    """
    if not context:
        return set()

    status = str(context.get("status") or context.get("resolution_status") or "").strip().lower()
    live = context.get("live_bc_context") or {}
    if status and status not in _VERIFIED_CONTEXT_STATUSES:
        return set()
    if status not in _VERIFIED_CONTEXT_STATUSES and not str(live.get("bc_document_no") or "").strip():
        return set()

    values: List[Any] = []
    for source, keys in (
        (context, ("po_number", "bc_document_no", "bc_order_number")),
        (live, ("bc_document_no", "bc_order_number")),
    ):
        for key in keys:
            value = source.get(key)
            if isinstance(value, (list, tuple, set)):
                values.extend(value)
            elif value:
                values.append(value)
    return _normalize_bc_ref_values(values)


def _verified_bc_refs(context: Dict[str, Any]) -> set[str]:
    """Diagnostic exact-reference set with legacy fallback.

    Resolved contexts use only the winning BC reference. Older/status-less test
    or snapshot contexts may fall back to verified_order_numbers for diagnostics,
    but that fallback is never used by summarize_exact_reference_authority().
    """
    if not context:
        return set()

    status = str(context.get("status") or context.get("resolution_status") or "").strip().lower()
    if status and status not in _VERIFIED_CONTEXT_STATUSES:
        return set()

    winner_refs = _resolved_winning_bc_refs(context)
    if winner_refs:
        return winner_refs

    verified_values = context.get("verified_order_numbers") or []
    if not isinstance(verified_values, (list, tuple, set)):
        verified_values = [verified_values] if verified_values else []
    return _normalize_bc_ref_values(list(verified_values))


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


def _payable_vendor_identity_is_required(document: Dict[str, Any]) -> bool:
    doc_type = _doc_type(document).replace("-", "_").replace(" ", "_")
    return bool(
        doc_type in {"ap_invoice", "invoice", "vendor_invoice", "credit_memo", "vendor_credit_memo"}
        or "invoice" in doc_type
        or "credit_memo" in doc_type
    )


def _label_multiplier(row: Dict[str, Any]) -> float:
    source = str(row.get("label_source") or row.get("source") or "").lower()
    if source == "reviewer_correction":
        return 3.0
    if source == LABEL_SOURCE_REVIEWER_CONFIRMATION:
        return 1.5
    return 1.0


def summarize_exact_reference_authority(
    *,
    document: Dict[str, Any],
    proposed_route: str,
    confidence: float,
    train_examples: Sequence[Dict[str, Any]],
    minimum_support: int = 4,
    minimum_confidence: float = 0.98,
) -> Dict[str, Any]:
    """Measure unanimity on one resolved winning BC reference.

    This corroborator can only confirm the AI's exact proposed route. It never
    selects a route. Every matching TRAIN row must independently resolve to the
    same winning BC reference. For payable documents, at least one matching
    support must share the current payable vendor so foreign-reference history
    cannot independently earn authority.
    """
    proposed = normalize_route_path(proposed_route)
    current_refs = _resolved_winning_bc_refs(document.get("bc_context") or {})
    current_vendor = _vendor(document)
    payable_vendor_required = _payable_vendor_identity_is_required(document)

    eligible = [dict(row) for row in train_examples if is_train_human_example(row)]
    matched_rows = [
        row
        for row in eligible
        if current_refs.intersection(_resolved_winning_bc_refs(row.get("bc_context") or {}))
    ] if current_refs else []
    support_rows = [
        row for row in matched_rows
        if normalize_route_path(row.get("route_path")) == proposed
    ]
    contradiction_rows = [
        row for row in matched_rows
        if normalize_route_path(row.get("route_path")) != proposed
    ]
    route_counter = Counter(
        normalize_route_path(row.get("route_path")) or "unknown"
        for row in matched_rows
    )
    same_vendor_support_count = sum(
        1
        for row in support_rows
        if current_vendor and _row_vendor(row) == current_vendor
    )
    vendor_identity_ready = bool(
        not payable_vendor_required
        or (current_vendor and same_vendor_support_count >= 1)
    )
    unanimous = bool(
        matched_rows
        and len(support_rows) == len(matched_rows)
        and not contradiction_rows
    )
    authority_ready = bool(
        proposed
        and len(current_refs) == 1
        and float(confidence or 0.0) >= float(minimum_confidence)
        and len(support_rows) >= int(minimum_support)
        and unanimous
        and vendor_identity_ready
    )

    return {
        "purpose": "CONFIRM_AI_EXACT_ROUTE_FROM_RESOLVED_WINNING_BC_REFERENCE_ONLY",
        "route_neutral": True,
        "proposed_route": proposed,
        "current_refs": sorted(current_refs),
        "current_ref_count": len(current_refs),
        "match_count": len(matched_rows),
        "support_count": len(support_rows),
        "contradiction_count": len(contradiction_rows),
        "route_counts": [
            {"route_path": route, "count": count}
            for route, count in sorted(route_counter.items(), key=lambda item: (-item[1], item[0]))
        ],
        "same_vendor_support_count": same_vendor_support_count,
        "payable_vendor_identity_required": payable_vendor_required,
        "vendor_identity_ready": vendor_identity_ready,
        "unanimous": unanimous,
        "minimum_support": int(minimum_support),
        "minimum_confidence": float(minimum_confidence),
        "confidence": float(confidence or 0.0),
        "authority_ready": authority_ready,
    }


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

    # Read-only diagnostic: measure exact BC PO/order agreement across TRAIN
    # human labels. Unlike summarize_exact_reference_authority(), this retains a
    # legacy verified_order_numbers fallback for backward-compatible telemetry.
    current_exact_refs = _verified_bc_refs(document.get("bc_context") or {})
    exact_reference_rows = [
        row
        for row in eligible
        if current_exact_refs.intersection(_verified_bc_refs(row.get("bc_context") or {}))
    ] if current_exact_refs else []
    exact_reference_route_counter = Counter(
        normalize_route_path(row.get("route_path")) or "unknown"
        for row in exact_reference_rows
    )
    exact_reference_support_count = sum(
        1
        for row in exact_reference_rows
        if normalize_route_path(row.get("route_path")) == proposed
    )
    exact_reference_contradiction_count = len(exact_reference_rows) - exact_reference_support_count
    exact_reference_route_counts = [
        {"route_path": route, "count": count}
        for route, count in sorted(
            exact_reference_route_counter.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]

    same_vendor = [
        row for row in eligible
        if vendor and _row_vendor(row) == vendor
        and (not doc_type or not _row_type(row) or _row_type(row) == doc_type)
    ]

    current_semantics = semantic_features(document)
    exceptional_semantics = current_semantics.intersection(EXCEPTIONAL_WORKFLOW_FEATURES)
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

    def support_matches_current_exception(row: Dict[str, Any]) -> bool:
        if not exceptional_semantics:
            return True
        return exceptional_semantics.issubset(semantic_features(row))

    proposed_rows = [
        (row, weight)
        for row, weight in weighted
        if normalize_route_path(row.get("route_path")) == proposed
    ]
    support = [
        (row, weight)
        for row, weight in proposed_rows
        if support_matches_current_exception(row)
    ]
    exception_mismatch_support = [
        (row, weight)
        for row, weight in proposed_rows
        if not support_matches_current_exception(row)
    ]
    contradictions = [
        (row, weight)
        for row, weight in weighted
        if normalize_route_path(row.get("route_path")) != proposed
    ]

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

    exception_support_ready = bool(
        not exceptional_semantics
        or len(support) >= minimum_support
    )

    authority_ready = bool(
        proposed
        and len(support) >= minimum_support
        and share >= minimum_share
        and margin >= minimum_margin
        and correction_contradictions == 0
        and exception_support_ready
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
        "exact_reference_current_ref_count": len(current_exact_refs),
        "exact_reference_match_count": len(exact_reference_rows),
        "exact_reference_support_count": exact_reference_support_count,
        "exact_reference_contradiction_count": exact_reference_contradiction_count,
        "exact_reference_route_counts": exact_reference_route_counts,
        "exceptional_workflow_features": sorted(exceptional_semantics),
        "exception_support_count": len(support) if exceptional_semantics else 0,
        "exception_mismatch_support_count": len(exception_mismatch_support),
        "exception_support_ready": exception_support_ready,
        "authority_ready": authority_ready,
        "neighbor_routes": [normalize_route_path(row.get("route_path")) for row in neighborhood],
        "neighbor_ids": [
            str(row.get("fingerprint") or row.get("source_item_id") or row.get("document_id") or row.get("file_name") or "")
            for row in neighborhood
        ],
        "neighbor_scores": [round(float(row.get("_authority_relevance_score") or 0.0), 4) for row in neighborhood],
    }
