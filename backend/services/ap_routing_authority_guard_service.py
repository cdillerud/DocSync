"""Fail-closed runtime-authority guard for learned AP routing.

The bounded LLM/ensemble remains responsible for interpreting one document, but
runtime authority is granted only after comparing that proposal with the wider
supervised evidence available for the vendor. This layer exists specifically to
prevent a small eight-example prompt from accidentally turning one cross-workflow
PO match or a generic filename shape into automatic routing authority.

It performs no SharePoint, Mongo, or Business Central writes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.ap_routing_decision_service import (
    DECISION_AUTO_ROUTE,
    DECISION_NEEDS_REVIEW,
    _supervised_route_support,
    decide_ap_route,
)
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name


def _review_route(contract: Dict[str, Any]) -> str:
    return normalize_route_path(contract.get("review_route")) if "review_route" in contract else ""


def _manual_only_routes(contract: Dict[str, Any]) -> set[str]:
    return {
        normalize_route_path(route)
        for route in (contract.get("manual_only_routes") or [])
        if normalize_route_path(route)
    }


def _same_vendor_examples(
    document: Dict[str, Any],
    examples: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    extracted = document.get("extracted_fields") or document.get("ai_extraction") or {}
    vendor = (
        document.get("vendor_canonical")
        or document.get("vendor_raw")
        or extracted.get("vendor")
        or extracted.get("vendor_name")
        or ""
    )
    vendor_key = normalize_vendor_name(vendor)
    if not vendor_key:
        return []
    return [
        example
        for example in examples
        if normalize_vendor_name(
            example.get("vendor_name")
            or example.get("vendor_canonical")
            or ((example.get("extracted_fields") or {}).get("vendor"))
        )
        == vendor_key
    ]


def _top_support_row(support: Dict[str, Any]) -> Dict[str, Any]:
    top_route = normalize_route_path(support.get("top_route"))
    for row in support.get("routes") or []:
        if normalize_route_path(row.get("route_path")) == top_route:
            return row
    return {}


def _authoritative_multi_route_support(support: Dict[str, Any]) -> bool:
    """Require current business-context evidence when a vendor spans 3+ routes.

    Repeated filename shape remains useful for the two-route V115 pattern, but
    V116 proved it is not safe by itself once the same vendor participates in
    several different workflows. In that broader case, automatic authority
    requires a repeated top route, a healthy score margin, and at least one
    exact/current business-context match (BC reference, location, or ship-to).
    """
    routes = support.get("routes") or []
    if len(routes) < 3:
        return bool(support.get("strong"))

    top = _top_support_row(support)
    if int(top.get("support_count") or 0) < 2:
        return False
    if float(support.get("margin") or 0.0) < 3.0:
        return False
    return bool(
        int(top.get("exact_bc_reference_matches") or 0) > 0
        or int(top.get("location_matches") or 0) > 0
        or int(top.get("ship_to_matches") or 0) > 0
    )


def _force_review(
    result: Dict[str, Any],
    *,
    contract: Dict[str, Any],
    blockers: List[str],
    guard: Dict[str, Any],
) -> Dict[str, Any]:
    output = dict(result)
    prior_blockers = list(output.get("blockers") or [])
    output["pre_authority_guard_decision"] = output.get("decision")
    output["pre_authority_guard_route"] = output.get("route_path")
    output["decision"] = DECISION_NEEDS_REVIEW
    output["route_path"] = _review_route(contract)
    output["blockers"] = prior_blockers + blockers
    output["reason"] = "; ".join(blockers)
    guard["action"] = "force_review"
    guard["blockers"] = list(blockers)
    output["authority_guard"] = guard
    return output


async def decide_ap_route_with_authority_guard(
    db,
    *,
    document: Dict[str, Any],
    bc_context: Optional[Dict[str, Any]],
    contract: Dict[str, Any],
    examples: Optional[List[Dict[str, Any]]] = None,
    support_examples: Optional[List[Dict[str, Any]]] = None,
    vendor_auto_threshold: Optional[float] = None,
    model: str = "gemini-2.5-pro",
    llm_send=None,
) -> Dict[str, Any]:
    """Run the bounded learner, then grant/deny automatic routing authority.

    `examples` is the small prompt context. `support_examples` may be the larger
    train-only supervised corpus and is never sent to the LLM.
    """
    result = await decide_ap_route(
        db,
        document=document,
        bc_context=bc_context,
        contract=contract,
        examples=examples,
        vendor_auto_threshold=vendor_auto_threshold,
        model=model,
        llm_send=llm_send,
    )

    evidence_examples = list(support_examples if support_examples is not None else (examples or []))
    same_vendor = _same_vendor_examples(document, evidence_examples)
    full_support = _supervised_route_support(document, bc_context or {}, evidence_examples)
    route = normalize_route_path(result.get("route_path"))
    bounded_ensemble = result.get("ensemble_reconciliation") or {}
    bounded_signals = list(bounded_ensemble.get("support_signals") or [])

    guard: Dict[str, Any] = {
        "action": "allow_existing_decision",
        "same_vendor_label_count": len(same_vendor),
        "same_vendor_route_count": len(full_support.get("routes") or []),
        "full_support_top_route": normalize_route_path(full_support.get("top_route")),
        "full_support_margin": float(full_support.get("margin") or 0.0),
        "full_support_strong": bool(full_support.get("strong")),
        "bounded_ensemble_action": bounded_ensemble.get("action"),
        "bounded_support_signals": bounded_signals,
        "manual_only_route": route in _manual_only_routes(contract),
    }
    result["full_supervised_route_support"] = full_support

    if result.get("decision") != DECISION_AUTO_ROUTE:
        result["authority_guard"] = guard
        return result

    blockers: List[str] = []

    if route in _manual_only_routes(contract):
        blockers.append(f"route is manual/downstream-only and cannot receive AI runtime authority: {route}")

    # A single prior label is not enough to grant automatic authority. This
    # directly blocks the V116 Ball/W118374 cross-workflow exact-PO failure while
    # allowing richer cohorts to earn authority from repeated evidence.
    if len(same_vendor) < 2:
        blockers.append(
            f"same-vendor supervised cohort too sparse for auto-route: {len(same_vendor)} label(s); need at least 2"
        )

    route_count = len(full_support.get("routes") or [])
    if route_count > 1:
        top_route = normalize_route_path(full_support.get("top_route"))
        authoritative = _authoritative_multi_route_support(full_support)
        if not authoritative:
            blockers.append(
                "multi-route vendor lacks authoritative current-context support; filename/reference shape alone cannot auto-route"
            )
        elif top_route and route != top_route:
            blockers.append(
                f"candidate route conflicts with full-corpus same-vendor support: predicted {route}, supervised {top_route}"
            )

    # Explicitly close the V116 failure mode where the bounded eight-example
    # ensemble selected a route using only repeated filename shape even though
    # the wider vendor corpus contains three or more legitimate workflows.
    if (
        route_count >= 3
        and bounded_ensemble.get("action") == "supervised_route_selected"
        and bounded_signals
        and set(bounded_signals).issubset({"repeated_filename_reference_shape"})
    ):
        blockers.append(
            "bounded supervised ensemble relied only on filename shape for a vendor spanning three or more routes"
        )

    if blockers:
        return _force_review(
            result,
            contract=contract,
            blockers=blockers,
            guard=guard,
        )

    result["authority_guard"] = guard
    return result
