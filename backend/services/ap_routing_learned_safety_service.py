"""Minimal fail-closed safety envelope for learned AP autonomy.

Safety may demote an earned AI route to review. It must never choose a
replacement route. Broad hazards belong here; vendor-specific templates do not.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from services.ap_routing_decision_service import route_is_allowed
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name

_STOP_PAY = re.compile(
    r"\b(?:do\s+not\s+pay|don['’]?t\s+pay|dont\s+pay|do\s+not\s+process|hold\s+payment)\b",
    re.IGNORECASE,
)


def _document_text(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    return " ".join(
        [
            str(document.get("file_name") or ""),
            str(document.get("raw_text") or document.get("raw_text_excerpt") or "")[:20000],
            " ".join(str(value) for value in fields.values()),
        ]
    )


def _document_vendor(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or document.get("ai_extraction") or {}
    return str(
        document.get("vendor_name")
        or document.get("vendor_canonical")
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
        or ""
    ).strip()


def _example_id(example: Dict[str, Any]) -> str:
    return str(
        example.get("fingerprint")
        or example.get("document_id")
        or example.get("source_item_id")
        or ""
    ).strip()


def _context_refs(context: Dict[str, Any]) -> Set[str]:
    values: List[Any] = []
    live = context.get("live_bc_context") or {}
    for source in (context, live):
        for key in (
            "routing_verified_order_numbers",
            "verified_order_numbers",
            "order_numbers",
            "po_number",
            "bc_document_no",
            "bc_order_number",
            "shipment_number",
        ):
            value = source.get(key)
            if isinstance(value, (list, tuple, set)):
                values.extend(value)
            elif value:
                values.append(value)
    return {str(value).strip().upper() for value in values if str(value).strip()}


def _leading_reference_from_filename(file_name: Any) -> str:
    name = str(file_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", name).strip()
    if not stem or stem[0] in "_-":
        return ""
    first = re.split(r"[_\s]+", stem, maxsplit=1)[0].strip("-")
    return first.upper()


def _reference_family(value: Any) -> str:
    token = str(value or "").strip().upper()
    if not token:
        return ""
    if re.fullmatch(r"W\d{4,8}[A-Z]?", token):
        return "warehouse"
    if re.fullmatch(r"WA\d{3,8}[A-Z]?", token):
        return "warehouse_assembly"
    if re.fullmatch(r"WTR[A-Z0-9_-]{2,20}", token):
        return "warehouse_transfer"
    if re.fullmatch(r"\d{5,7}[A-Z]?", token):
        return "standard_order"
    return ""


def _current_reference_family(document: Dict[str, Any], context: Dict[str, Any]) -> str:
    for ref in sorted(_context_refs(context)):
        family = _reference_family(ref)
        if family:
            return family
    return _reference_family(_leading_reference_from_filename(document.get("file_name")))


def _route_family(route: Any) -> str:
    value = normalize_route_path(route)
    if value.startswith("Warehouse International") or value.startswith("Warehouse Not International"):
        return "warehouse"
    if value.startswith("Dropship International") or value.startswith("Dropship Not International"):
        return "dropship"
    return "special"


def _family_conflict(reference_family: str, route: str) -> bool:
    family = _route_family(route)
    if reference_family in {"warehouse", "warehouse_assembly", "warehouse_transfer"}:
        return family == "dropship"
    if reference_family == "standard_order":
        return family == "warehouse"
    return False


def _context_vendor_name(context: Dict[str, Any]) -> str:
    live = context.get("live_bc_context") or {}
    for value in (
        context.get("bc_vendor_name"),
        context.get("vendor_name"),
        live.get("bc_vendor_name"),
        live.get("vendor_name"),
    ):
        if value:
            return str(value)
    for match in context.get("matches") or []:
        if isinstance(match, dict):
            value = match.get("bc_vendor_name") or match.get("vendor_name")
            if value:
                return str(value)
    return ""


def _context_is_resolved(context: Dict[str, Any]) -> bool:
    status = str(context.get("status") or context.get("resolution_status") or "").lower()
    return status in {"resolved", "resolved_shipment", "matched", "verified"} or bool(
        context.get("bc_record_id") or context.get("verified_order_numbers")
    )


def _vendors_conflict(left: str, right: str) -> bool:
    a = normalize_vendor_name(left)
    b = normalize_vendor_name(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return False
    a_tokens = {token for token in a.split() if len(token) >= 4}
    b_tokens = {token for token in b.split() if len(token) >= 4}
    return bool(a_tokens and b_tokens and not a_tokens.intersection(b_tokens))


def _prediction_payload(autonomy_decision: Dict[str, Any]) -> Dict[str, Any]:
    return autonomy_decision.get("prediction") or {}


def _model_bc_refs(autonomy_decision: Dict[str, Any]) -> Set[str]:
    return {
        str(value).strip().upper()
        for value in (_prediction_payload(autonomy_decision).get("bc_refs_used") or [])
        if str(value).strip()
    }


def _model_matched_ids(autonomy_decision: Dict[str, Any]) -> Set[str]:
    return {
        str(value)
        for value in (_prediction_payload(autonomy_decision).get("matched_example_ids") or [])
        if str(value)
    }


def _cross_vendor_exact_reference_dependency(
    *,
    document: Dict[str, Any],
    proposed_route: str,
    autonomy_decision: Dict[str, Any],
    bc_context: Dict[str, Any],
    support_examples: Sequence[Dict[str, Any]],
) -> bool:
    refs = _context_refs(bc_context)
    if not refs:
        return False

    current_vendor = normalize_vendor_name(_document_vendor(document))
    model_refs = _model_bc_refs(autonomy_decision)
    model_ids = _model_matched_ids(autonomy_decision)
    foreign_ids: Set[str] = set()
    same_vendor_match = False
    foreign_match = False

    for example in support_examples:
        if normalize_route_path(example.get("route_path")) != proposed_route:
            continue
        example_refs = _context_refs(example.get("bc_context") or {})
        if not refs.intersection(example_refs):
            continue
        example_vendor = normalize_vendor_name(_example_vendor(example))
        if current_vendor and example_vendor == current_vendor:
            same_vendor_match = True
        elif example_vendor:
            foreign_match = True
            example_id = _example_id(example)
            if example_id:
                foreign_ids.add(example_id)

    if same_vendor_match or not foreign_match:
        return False

    relied_on_ref = bool(refs.intersection(model_refs))
    relied_on_foreign_example = bool(foreign_ids.intersection(model_ids))
    return relied_on_ref or relied_on_foreign_example


def derive_universal_safety_blockers(
    *,
    document: Dict[str, Any],
    autonomy_decision: Dict[str, Any],
    contract: Dict[str, Any],
    bc_context: Optional[Dict[str, Any]] = None,
    support_examples: Sequence[Dict[str, Any]] = (),
) -> List[str]:
    """Return broad V117 blockers without selecting any route.

    These are intentionally route-neutral safety boundaries learned from prior
    held-out failures. They may only force review.
    """
    context = bc_context or {}
    proposed = normalize_route_path(autonomy_decision.get("ai_proposed_route") or "")
    blockers: List[str] = []

    manual_only = {
        normalize_route_path(route)
        for route in (contract.get("manual_only_routes") or [])
        if normalize_route_path(route)
    }
    if proposed and proposed in manual_only:
        blockers.append("AI proposed a manual-only route")

    reference_family = _current_reference_family(document, context)
    if proposed and reference_family and _family_conflict(reference_family, proposed):
        blockers.append(
            f"current reference family {reference_family} conflicts with AI route family {_route_family(proposed)}"
        )

    # A resolved BC vendor mismatch is relevant only to logistics routes. This
    # avoids the old failure mode where an unrelated BC match poisoned special
    # Accounting queues that do not depend on order context.
    context_vendor = _context_vendor_name(context)
    if (
        proposed
        and _route_family(proposed) in {"warehouse", "dropship"}
        and _context_is_resolved(context)
        and _vendors_conflict(_document_vendor(document), context_vendor)
    ):
        blockers.append("resolved Business Central vendor conflicts with current document vendor")

    if proposed and _cross_vendor_exact_reference_dependency(
        document=document,
        proposed_route=proposed,
        autonomy_decision=autonomy_decision,
        bc_context=context,
        support_examples=support_examples,
    ):
        blockers.append("AI relied on foreign-vendor exact-reference evidence without same-vendor authority")

    return blockers


def apply_learned_autonomy_safety(
    *,
    document: Dict[str, Any],
    autonomy_decision: Dict[str, Any],
    contract: Dict[str, Any],
    bc_context: Optional[Dict[str, Any]] = None,
    hard_blockers: Iterable[str] = (),
    support_examples: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    proposed = normalize_route_path(autonomy_decision.get("ai_proposed_route") or "")
    decision = str(autonomy_decision.get("decision") or "needs_review")
    blockers: List[str] = [str(item) for item in hard_blockers if str(item).strip()]
    blockers.extend(
        derive_universal_safety_blockers(
            document=document,
            autonomy_decision=autonomy_decision,
            contract=contract,
            bc_context=bc_context,
            support_examples=support_examples,
        )
    )
    blockers = list(dict.fromkeys(blockers))

    if decision != "auto_route":
        result = dict(autonomy_decision)
        result["safety_action"] = "preserve_review"
        result["safety_blockers"] = blockers
        result["route_path"] = ""
        return result

    # Safety can only assess the exact AI proposal.
    if not proposed or normalize_route_path(autonomy_decision.get("route_path")) != proposed:
        blockers.append("learned autonomy attempted to alter the AI proposed route")

    if proposed and not route_is_allowed(proposed, contract, bc_context or {}):
        blockers.append(f"AI proposed route is not allowed by current route contract: {proposed}")

    text = _document_text(document)
    if _STOP_PAY.search(text) and proposed.strip().lower() != "do not pay":
        blockers.append("explicit current-document stop-pay instruction conflicts with proposed payable route")

    prediction = autonomy_decision.get("prediction") or {}
    unresolved = list(prediction.get("unresolved") or autonomy_decision.get("model_unresolved") or [])
    if unresolved:
        blockers.append("AI reported unresolved/model-error evidence")

    blockers = list(dict.fromkeys(blockers))
    result = dict(autonomy_decision)
    if blockers:
        result.update(
            {
                "decision": "needs_review",
                "route_path": "",
                "safety_action": "demote_to_review",
                "safety_blockers": blockers,
                "pre_safety_autonomy_tier": autonomy_decision.get("autonomy_tier"),
            }
        )
    else:
        result.update(
            {
                "decision": "auto_route",
                "route_path": proposed,
                "safety_action": "allow_ai_route",
                "safety_blockers": [],
            }
        )
    result["route_preserved"] = result.get("route_path") in {"", proposed}
    return result
