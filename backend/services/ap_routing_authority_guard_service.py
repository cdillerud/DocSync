"""Fail-closed runtime-authority guard for learned AP routing.

The bounded LLM/ensemble remains responsible for interpreting one document, but
runtime authority is granted only after comparing that proposal with the wider
supervised evidence available for the vendor. The guard prevents a small prompt
from turning a cross-workflow reference or generic filename shape into automatic
routing authority while still allowing measured, independent evidence to reduce
manual Accounting sorting.

It performs no SharePoint, Mongo, or Business Central writes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from services.ap_routing_decision_service import (
    DECISION_AUTO_ROUTE,
    DECISION_NEEDS_REVIEW,
    _bc_context_is_resolved,
    _route_requires_bc_context,
    _supervised_route_support,
    decide_ap_route,
    route_is_allowed,
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


def _context_refs(context: Dict[str, Any]) -> Set[str]:
    values: List[Any] = []
    for key in (
        "verified_order_numbers",
        "order_numbers",
        "po_number",
        "bc_document_no",
        "bc_order_number",
    ):
        value = context.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value:
            values.append(value)
    return {str(value).strip().upper() for value in values if str(value).strip()}


def _cross_vendor_exact_reference_dependency(
    document: Dict[str, Any],
    bc_context: Dict[str, Any],
    examples: List[Dict[str, Any]],
    candidate_route: str,
) -> bool:
    """Detect the V116-class risk of borrowing another vendor's exact reference.

    A sparse/new vendor is allowed to use high-confidence model semantics, but a
    coincidental exact PO/order match from a *different* vendor may not become
    automatic authority for that route unless same-vendor evidence also carries
    the same current reference.
    """
    refs = _context_refs(bc_context)
    if not refs:
        return False

    extracted = document.get("extracted_fields") or document.get("ai_extraction") or {}
    current_vendor = normalize_vendor_name(
        document.get("vendor_canonical")
        or document.get("vendor_raw")
        or extracted.get("vendor")
        or extracted.get("vendor_name")
        or ""
    )
    foreign_match = False
    same_vendor_match = False
    route = normalize_route_path(candidate_route)

    for example in examples:
        example_route = normalize_route_path(example.get("route_path"))
        if example_route != route:
            continue
        example_refs = _context_refs(example.get("bc_context") or {})
        if not refs.intersection(example_refs):
            continue
        example_vendor = normalize_vendor_name(
            example.get("vendor_name")
            or example.get("vendor_canonical")
            or ((example.get("extracted_fields") or {}).get("vendor"))
        )
        if current_vendor and example_vendor == current_vendor:
            same_vendor_match = True
        elif example_vendor:
            foreign_match = True

    return foreign_match and not same_vendor_match


def _current_context_support(top: Dict[str, Any]) -> bool:
    return bool(
        int(top.get("exact_bc_reference_matches") or 0) > 0
        or int(top.get("location_matches") or 0) > 0
        or int(top.get("ship_to_matches") or 0) > 0
    )


def _independent_model_full_support_consensus(
    result: Dict[str, Any],
    full_support: Dict[str, Any],
) -> bool:
    """True when the raw LLM and wider train corpus independently pick one route."""
    ensemble = result.get("ensemble_reconciliation") or {}
    original_model_route = normalize_route_path(
        ensemble.get("original_model_route")
        or ((ensemble.get("original_prediction") or {}).get("proposed_route"))
        or ((result.get("prediction") or {}).get("proposed_route"))
    )
    support_route = normalize_route_path(full_support.get("top_route"))
    candidate_route = normalize_route_path(result.get("route_path") or ((result.get("prediction") or {}).get("proposed_route")))
    return bool(
        original_model_route
        and support_route
        and candidate_route
        and original_model_route == support_route == candidate_route
    )


def _authoritative_multi_route_support(
    result: Dict[str, Any],
    support: Dict[str, Any],
) -> bool:
    """Require strong current-context evidence or independent consensus.

    Repeated filename shape alone is not safe when one vendor spans several
    workflows. However, if the raw LLM independently selects the same route as
    the wider supervised corpus, repeated support with a healthy margin may earn
    authority without requiring a location field that Business Central often
    does not populate.
    """
    routes = support.get("routes") or []
    if len(routes) < 2:
        return True

    top = _top_support_row(support)
    if int(top.get("support_count") or 0) < 2:
        return False
    if float(support.get("margin") or 0.0) < 3.0:
        return False
    if _current_context_support(top):
        return True
    return _independent_model_full_support_consensus(result, support)


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


def _promote_full_corpus_consensus(
    result: Dict[str, Any],
    *,
    bc_context: Dict[str, Any],
    contract: Dict[str, Any],
    full_support: Dict[str, Any],
    same_vendor: List[Dict[str, Any]],
    guard: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Promote a review only when repeated train evidence closes its uncertainty.

    This is deliberately narrower than "the model was probably right". It can
    override only low-confidence/weak-bounded-support review states, never model
    unresolved evidence, unresolved BC-required routes, contract failures, or a
    disagreement between the raw model and wider supervised route evidence.
    """
    if result.get("decision") != DECISION_NEEDS_REVIEW:
        return None

    prediction = result.get("prediction") or {}
    route = normalize_route_path(prediction.get("proposed_route"))
    if not route or route in _manual_only_routes(contract):
        return None
    if not route_is_allowed(route, contract, bc_context):
        return None
    if prediction.get("unresolved"):
        return None
    if _route_requires_bc_context(route, contract) and not _bc_context_is_resolved(bc_context):
        return None
    if len(same_vendor) < 2:
        return None

    top_route = normalize_route_path(full_support.get("top_route"))
    top = _top_support_row(full_support)
    if top_route != route or int(top.get("support_count") or 0) < 2:
        return None

    route_count = len(full_support.get("routes") or [])
    if route_count > 1 and not _authoritative_multi_route_support(result, full_support):
        return None

    # Only known conservative governor states may be promoted. Any other blocker
    # remains fail-closed.
    allowed_blocker_prefixes = (
        "variable-vendor route lacks discriminating same-vendor supervised evidence",
    )
    blockers = list(result.get("blockers") or [])
    if any(not str(blocker).startswith(allowed_blocker_prefixes) for blocker in blockers):
        return None

    # A threshold-only review can be promoted by repeated same-vendor labels.
    # The learned route receives the configured threshold as its minimum
    # authority confidence rather than pretending the raw model was more sure.
    output = dict(result)
    threshold = float(contract.get("auto_route_threshold") or result.get("auto_route_threshold") or 0.92)
    output["pre_authority_guard_decision"] = result.get("decision")
    output["pre_authority_guard_route"] = result.get("route_path")
    output["decision"] = DECISION_AUTO_ROUTE
    output["route_path"] = route
    output["confidence"] = max(float(result.get("confidence") or 0.0), threshold)
    output["blockers"] = []
    output["warnings"] = []
    output["reason"] = (
        "full-corpus same-vendor consensus promoted the learned route after bounded review: "
        f"{route} (labels={len(same_vendor)}, support={int(top.get('support_count') or 0)}, "
        f"margin={float(full_support.get('margin') or 0.0):.2f})"
    )
    guard["action"] = "promote_full_corpus_consensus"
    guard["blockers"] = []
    guard["promotion_route"] = route
    guard["promotion_support_count"] = int(top.get("support_count") or 0)
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
    context = bc_context or {}
    result = await decide_ap_route(
        db,
        document=document,
        bc_context=context,
        contract=contract,
        examples=examples,
        vendor_auto_threshold=vendor_auto_threshold,
        model=model,
        llm_send=llm_send,
    )

    evidence_examples = list(support_examples if support_examples is not None else (examples or []))
    same_vendor = _same_vendor_examples(document, evidence_examples)
    full_support = _supervised_route_support(document, context, evidence_examples)
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
        promoted = _promote_full_corpus_consensus(
            result,
            bc_context=context,
            contract=contract,
            full_support=full_support,
            same_vendor=same_vendor,
            guard=guard,
        )
        if promoted is not None:
            return promoted
        result["authority_guard"] = guard
        return result

    blockers: List[str] = []

    if route in _manual_only_routes(contract):
        blockers.append(f"route is manual/downstream-only and cannot receive AI runtime authority: {route}")

    # Sparse/new vendors are not automatically unsafe. The earlier V116 error
    # came from borrowing an exact order reference from another vendor. Block
    # that specific generalized evidence pattern instead of vetoing every vendor
    # with fewer than two labels.
    if _cross_vendor_exact_reference_dependency(document, context, list(examples or []), route):
        blockers.append(
            "candidate route relies on an exact current reference seen only under a different vendor"
        )

    route_count = len(full_support.get("routes") or [])
    if route_count > 1:
        top_route = normalize_route_path(full_support.get("top_route"))
        authoritative = _authoritative_multi_route_support(result, full_support)
        if not authoritative:
            blockers.append(
                "multi-route vendor lacks authoritative current-context or independent model/full-corpus consensus"
            )
        elif top_route and route != top_route:
            blockers.append(
                f"candidate route conflicts with full-corpus same-vendor support: predicted {route}, supervised {top_route}"
            )

    # Filename shape may participate only when the independent raw model and the
    # wider supervised corpus agree. This preserves the V115 benefit while
    # closing the broad Tumalo failure where bounded support alone chose a route.
    if (
        route_count >= 3
        and bounded_ensemble.get("action") == "supervised_route_selected"
        and bounded_signals
        and set(bounded_signals).issubset({"repeated_filename_reference_shape"})
        and not _independent_model_full_support_consensus(result, full_support)
    ):
        blockers.append(
            "bounded supervised ensemble relied only on filename shape without independent full-corpus consensus"
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
