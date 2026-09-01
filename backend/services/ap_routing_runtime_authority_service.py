"""Final fail-closed runtime-authority overlay for AP routing.

The bounded router may propose any destination allowed by the versioned routing
contract, but contract validity is not the same thing as learned runtime
authority. This overlay protects sparse/high-risk cases that should remain in
review until Accounting evidence demonstrates the more-specific workflow.

V117 runtime-authority boundaries
---------------------------------
* Warehouse-prefixed documents cannot auto-route to Tooling Invoices without
  repeated same-vendor Accounting Tooling evidence.
* A dynamic order-specific route may be contract-valid from a verified BC
  reference, but it cannot auto-route without same-vendor Accounting evidence
  for that exact dynamic destination.
* When both a parent queue and a more-specific static child are valid contract
  routes, the child cannot be selected without same-vendor Accounting evidence
  for that exact child.
* Rhonda - Issues is an exception workflow, not a generic semantic bucket; a
  vendor with no learned Rhonda - Issues history fails closed to review.
* Semantically specific exception children such as Ball Detention Credits need
  current-document semantic evidence; vendor history alone cannot specialize a
  generic credit memo into that workflow.
* An exact current warehouse/order reference found in same-vendor Accounting
  source-placement evidence under a different canonical workflow vetoes a
  vendor-majority override.

These are authority vetoes only. They never infer the replacement route and do
not write SharePoint, Mongo, or Business Central.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from services.ap_routing_authority_guard_service import (
    decide_ap_route_with_authority_guard as _base_decide_ap_route_with_authority_guard,
)
from services.ap_routing_decision_service import DECISION_AUTO_ROUTE, DECISION_NEEDS_REVIEW
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name


def _document_vendor(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or document.get("ai_extraction") or {}
    return str(
        document.get("vendor_canonical")
        or document.get("vendor_raw")
        or fields.get("vendor")
        or fields.get("vendor_name")
        or ""
    ).strip()


def _example_vendor(example: Dict[str, Any]) -> str:
    fields = example.get("extracted_fields") or {}
    return str(
        example.get("vendor_name")
        or example.get("vendor_canonical")
        or fields.get("vendor")
        or fields.get("vendor_name")
        or ""
    ).strip()


def _same_vendor_examples(
    document: Dict[str, Any],
    support_examples: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    vendor_key = normalize_vendor_name(_document_vendor(document))
    if not vendor_key:
        return []
    return [
        example
        for example in support_examples
        if normalize_vendor_name(_example_vendor(example)) == vendor_key
    ]


def _same_vendor_route_support(
    document: Dict[str, Any],
    support_examples: List[Dict[str, Any]],
    route: str,
) -> int:
    target = normalize_route_path(route)
    return sum(
        1
        for example in _same_vendor_examples(document, support_examples)
        if normalize_route_path(example.get("route_path")) == target
    )


def _normalized_static_routes(contract: Dict[str, Any]) -> Set[str]:
    return {
        normalize_route_path(route)
        for route in (contract.get("static_routes") or [])
        if normalize_route_path(route)
    }


def _dynamic_route_prefix(route: str, contract: Dict[str, Any]) -> str:
    normalized = normalize_route_path(route)
    if not normalized or normalized in _normalized_static_routes(contract):
        return ""
    for rule in contract.get("dynamic_routes") or []:
        prefix = normalize_route_path((rule or {}).get("prefix"))
        if prefix and normalized.startswith(prefix + "/"):
            return prefix
    return ""


def _static_parent_route(route: str, contract: Dict[str, Any]) -> str:
    normalized = normalize_route_path(route)
    static_routes = _normalized_static_routes(contract)
    if normalized not in static_routes or "/" not in normalized:
        return ""
    parts = normalized.split("/")
    for end in range(len(parts) - 1, 0, -1):
        parent = "/".join(parts[:end])
        if parent in static_routes:
            return parent
    return ""


def _is_sparse_exception_workflow(route: str) -> bool:
    normalized = normalize_route_path(route)
    return normalized == "Rhonda - Issues" or normalized.startswith("Rhonda - Issues/")


def _document_semantic_text(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or document.get("ai_extraction") or {}
    return " ".join(
        [
            str(document.get("file_name") or ""),
            str(document.get("raw_text") or document.get("document_text") or "")[:16000],
            " ".join(f"{key} {value}" for key, value in list(fields.items())[:80]),
        ]
    ).lower()


def _specific_child_semantics_supported(route: str, document: Dict[str, Any]) -> bool:
    normalized = normalize_route_path(route)
    if normalized == "Vendor Credit Memos/Ball Detention Credits":
        return bool(re.search(r"\bdetention\b", _document_semantic_text(document)))
    return True


def _warehouse_reference_tokens(document: Dict[str, Any], context: Dict[str, Any]) -> Set[str]:
    values: List[Any] = []
    fields = document.get("extracted_fields") or document.get("ai_extraction") or {}
    for source in (context, fields):
        for key in (
            "routing_verified_order_numbers",
            "verified_order_numbers",
            "order_numbers",
            "po_number",
            "bc_document_no",
            "bc_order_number",
            "order_number",
            "reference_number",
        ):
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, list):
                values.extend(value)
            elif value:
                values.append(value)

    filename = str(document.get("file_name") or "").upper()
    values.extend(
        re.findall(
            r"(?<![A-Z0-9])(?:W\d{4,8}[A-Z]?|WA\d{3,8}[A-Z]?|WTR[A-Z0-9_-]{2,20})(?![A-Z0-9])",
            filename,
        )
    )

    warehouse: Set[str] = set()
    for value in values:
        text = str(value or "").upper()
        for token in re.findall(
            r"(?<![A-Z0-9])(?:W\d{4,8}[A-Z]?|WA\d{3,8}[A-Z]?|WTR[A-Z0-9_-]{2,20})(?![A-Z0-9])",
            text,
        ):
            warehouse.add(token)
    return warehouse


def _same_vendor_exact_reference_routes(
    document: Dict[str, Any],
    context: Dict[str, Any],
    support_examples: List[Dict[str, Any]],
) -> Dict[str, Set[str]]:
    refs = _warehouse_reference_tokens(document, context)
    if not refs:
        return {}

    matches: Dict[str, Set[str]] = {ref: set() for ref in refs}
    for example in _same_vendor_examples(document, support_examples):
        route = normalize_route_path(example.get("route_path"))
        if not route:
            continue
        example_context = example.get("bc_context") or {}
        haystack = " ".join(
            [
                str(example.get("source_route_path") or ""),
                str(example.get("raw_route_path") or ""),
                str(example.get("placement_path") or ""),
                str(example.get("file_name") or ""),
                " ".join(str(value) for value in (example_context.get("verified_order_numbers") or [])),
                str(example_context.get("po_number") or ""),
                str(example_context.get("bc_order_number") or ""),
            ]
        ).upper()
        for ref in refs:
            if re.search(rf"(?<![A-Z0-9]){re.escape(ref)}(?![A-Z0-9])", haystack):
                matches[ref].add(route)

    return {ref: routes for ref, routes in matches.items() if routes}


def _force_review_runtime(
    result: Dict[str, Any],
    *,
    contract: Dict[str, Any],
    blocker: str,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    output = dict(result)
    output["pre_runtime_authority_decision"] = output.get("decision")
    output["pre_runtime_authority_route"] = output.get("route_path")
    output["decision"] = DECISION_NEEDS_REVIEW
    output["route_path"] = (
        normalize_route_path(contract.get("review_route"))
        if "review_route" in contract
        else ""
    )
    output["blockers"] = list(output.get("blockers") or []) + [blocker]
    output["reason"] = blocker

    guard = dict(output.get("authority_guard") or {})
    guard["action"] = "force_review"
    guard["blockers"] = list(guard.get("blockers") or []) + [blocker]
    if evidence:
        guard.update(evidence)
    output["authority_guard"] = guard

    overlay = {
        "action": "force_review",
        "blockers": [blocker],
    }
    if evidence:
        overlay.update(evidence)
    output["runtime_authority_overlay"] = overlay
    return output


async def decide_ap_route_with_runtime_authority(
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
    """Run the V117 base authority guard, then apply final sparse-risk vetoes."""
    context = bc_context or {}
    support = list(support_examples if support_examples is not None else (examples or []))
    result = await _base_decide_ap_route_with_authority_guard(
        db,
        document=document,
        bc_context=context,
        contract=contract,
        examples=examples,
        support_examples=support_examples,
        vendor_auto_threshold=vendor_auto_threshold,
        model=model,
        llm_send=llm_send,
    )

    if result.get("decision") != DECISION_AUTO_ROUTE:
        return result

    route = normalize_route_path(result.get("route_path"))
    same_vendor_count = len(_same_vendor_examples(document, support))
    same_vendor_exact_route = _same_vendor_route_support(document, support, route)
    dynamic_prefix = _dynamic_route_prefix(route, contract)
    static_parent = _static_parent_route(route, contract)

    # A semantically specific child workflow needs current-document evidence for
    # the semantic distinction encoded in that child. Repeated vendor history
    # cannot turn an ordinary credit memo into a detention-credit workflow.
    if not _specific_child_semantics_supported(route, document):
        return _force_review_runtime(
            result,
            contract=contract,
            blocker=(
                "specific child workflow lacks current-document semantic evidence "
                "for the specialization"
            ),
            evidence={
                "specific_child_route": route,
                "same_vendor_label_count": same_vendor_count,
                "same_vendor_exact_route_label_count": same_vendor_exact_route,
            },
        )

    # Exact current references embedded in Accounting's same-vendor source
    # placements are stronger than vendor-majority consensus. If that exact
    # reference has learned a different canonical workflow, veto the proposal.
    exact_reference_routes = _same_vendor_exact_reference_routes(document, context, support)
    conflicting_reference_routes = {
        ref: sorted(routes)
        for ref, routes in exact_reference_routes.items()
        if route not in routes
    }
    if conflicting_reference_routes:
        return _force_review_runtime(
            result,
            contract=contract,
            blocker=(
                "exact current reference has same-vendor Accounting source-placement "
                "evidence for a different canonical workflow"
            ),
            evidence={
                "same_vendor_exact_reference_routes": conflicting_reference_routes,
                "same_vendor_label_count": same_vendor_count,
            },
        )

    # Dynamic route validation proves only that the leaf is contract-valid and,
    # where required, tied to a verified BC reference. It does not prove that
    # Accounting uses that order-specific child workflow for this vendor.
    if dynamic_prefix and same_vendor_exact_route < 1:
        return _force_review_runtime(
            result,
            contract=contract,
            blocker=(
                "contract-valid dynamic route lacks same-vendor Accounting "
                "authority for the exact order-specific destination"
            ),
            evidence={
                "dynamic_route_prefix": dynamic_prefix,
                "same_vendor_label_count": same_vendor_count,
                "same_vendor_exact_route_label_count": same_vendor_exact_route,
            },
        )

    # When Accounting exposes both a parent queue and a more-specific static
    # child, generic model semantics are insufficient to choose the child. One
    # same-vendor child label is the minimum evidence boundary; this is a veto,
    # not a rule that selects the child.
    if static_parent and same_vendor_exact_route < 1:
        return _force_review_runtime(
            result,
            contract=contract,
            blocker=(
                "specific static child route lacks same-vendor Accounting "
                "authority while a contract-valid parent queue also exists"
            ),
            evidence={
                "static_parent_route": static_parent,
                "same_vendor_label_count": same_vendor_count,
                "same_vendor_exact_route_label_count": same_vendor_exact_route,
            },
        )

    # Rhonda - Issues represents an explicit exception workflow. Words such as
    # hold/checking/problem are not enough to create authority for a new vendor.
    if _is_sparse_exception_workflow(route) and same_vendor_exact_route < 1:
        return _force_review_runtime(
            result,
            contract=contract,
            blocker=(
                "exception workflow Rhonda - Issues requires same-vendor "
                "Accounting evidence before automatic routing"
            ),
            evidence={
                "same_vendor_label_count": same_vendor_count,
                "same_vendor_exact_route_label_count": same_vendor_exact_route,
            },
        )

    warehouse_refs = _warehouse_reference_tokens(document, context)
    same_vendor_tooling = _same_vendor_route_support(document, support, "Tooling Invoices")

    # A warehouse-prefixed order/reference plus a generic "tooling charge"
    # interpretation is not enough to grant Tooling runtime authority. Require
    # repeated same-vendor Accounting evidence; otherwise fail closed to review.
    if route == "Tooling Invoices" and warehouse_refs and same_vendor_tooling < 2:
        return _force_review_runtime(
            result,
            contract=contract,
            blocker=(
                "warehouse-prefixed current reference requires repeated same-vendor "
                "Accounting evidence before Tooling Invoices may auto-route"
            ),
            evidence={
                "warehouse_reference_tokens": sorted(warehouse_refs),
                "same_vendor_tooling_label_count": same_vendor_tooling,
            },
        )

    return result


# Drop-in name used by the held-out evaluator monkeypatch and future runtime integration.
decide_ap_route_with_authority_guard = decide_ap_route_with_runtime_authority
