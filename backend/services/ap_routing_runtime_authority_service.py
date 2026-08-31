"""Final fail-closed runtime-authority overlay for AP routing.

V117 exposed a live unsafe case where an Evergreen invoice whose filename began
with warehouse order W118614 was auto-routed to Tooling Invoices because the
base authority guard treats warehouse-vs-special as non-conflicting and the
held-out train split had no corroborating Evergreen examples.

This overlay does not turn warehouse numbering into a route rule. It only vetoes
a sparse Tooling Invoices auto-route when the current document carries an
explicit warehouse-family reference and there is not repeated same-vendor
Accounting evidence that this vendor legitimately uses Tooling Invoices.

No SharePoint, Mongo, or Business Central writes occur here.
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


def _same_vendor_tooling_support(
    document: Dict[str, Any],
    support_examples: List[Dict[str, Any]],
) -> int:
    vendor_key = normalize_vendor_name(_document_vendor(document))
    if not vendor_key:
        return 0
    return sum(
        1
        for example in support_examples
        if normalize_vendor_name(_example_vendor(example)) == vendor_key
        and normalize_route_path(example.get("route_path")) == "Tooling Invoices"
    )


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
    warehouse_refs = _warehouse_reference_tokens(document, context)
    same_vendor_tooling = _same_vendor_tooling_support(document, support)

    # A warehouse-prefixed order/reference plus a generic "tooling charge"
    # interpretation is not enough to grant Tooling runtime authority. Require
    # repeated same-vendor Accounting evidence; otherwise fail closed to review.
    if route == "Tooling Invoices" and warehouse_refs and same_vendor_tooling < 2:
        blocker = (
            "warehouse-prefixed current reference requires repeated same-vendor "
            "Accounting evidence before Tooling Invoices may auto-route"
        )
        output = dict(result)
        output["pre_runtime_authority_decision"] = output.get("decision")
        output["pre_runtime_authority_route"] = output.get("route_path")
        output["decision"] = DECISION_NEEDS_REVIEW
        output["route_path"] = normalize_route_path(contract.get("review_route")) if "review_route" in contract else ""
        output["blockers"] = list(output.get("blockers") or []) + [blocker]
        output["reason"] = blocker
        guard = dict(output.get("authority_guard") or {})
        guard["action"] = "force_review"
        guard["blockers"] = list(guard.get("blockers") or []) + [blocker]
        guard["warehouse_reference_tokens"] = sorted(warehouse_refs)
        guard["same_vendor_tooling_label_count"] = same_vendor_tooling
        output["authority_guard"] = guard
        output["runtime_authority_overlay"] = {
            "action": "force_review",
            "blockers": [blocker],
            "warehouse_reference_tokens": sorted(warehouse_refs),
            "same_vendor_tooling_label_count": same_vendor_tooling,
        }
        return output

    return result


# Drop-in name used by the held-out evaluator monkeypatch and future runtime integration.
decide_ap_route_with_authority_guard = decide_ap_route_with_runtime_authority
