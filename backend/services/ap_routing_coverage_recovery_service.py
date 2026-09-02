"""Deterministic second-stage coverage recovery for V117 AP routing.

This layer runs after the established zero-wrong runtime and coverage authority
layers. It does not weaken hard safety vetoes. It recovers only review-state
documents when stronger Accounting evidence is available than the conservative
base guard used:

* repeated same-vendor reference-family consensus, independently confirmed by
  the raw model and full supervised route support;
* repeated same-vendor exact current-reference consensus, including ordinary
  numeric BC references as well as W/WA/WTR references; or
* a narrowly defined semantic-child workflow whose current document contains
  the semantic distinction and whose vendor has repeated labels for that exact
  route.

No rule infers a destination from vendor identity alone. Nothing here writes
SharePoint, Mongo, or Business Central.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set

from services.ap_routing_coverage_authority_service import (
    decide_ap_route_with_authority_guard as _base_coverage_decide,
)
from services.ap_routing_decision_service import (
    DECISION_AUTO_ROUTE,
    DECISION_NEEDS_REVIEW,
    route_is_allowed,
)
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name


_RECOVERABLE_AUTHORITY_BLOCKERS = (
    "multi-route vendor lacks discriminating current-document or authoritative BC context evidence",
    "candidate route family ",
    "specific static child route lacks same-vendor Accounting authority while a contract-valid parent queue also exists",
)

_HARD_AUTHORITY_BLOCKER_FRAGMENTS = (
    "candidate route relies on an exact current reference seen only under a different vendor",
    "explicit stop-pay/incorrect-charge evidence conflicts with proposed payable route",
    "candidate route conflicts with stable same-vendor Accounting workflow",
    "candidate route conflicts with discriminating same-vendor document/context evidence",
    "candidate route conflicts with discriminating route-neutral full-corpus evidence",
    "route is manual/downstream-only",
)

_SEMANTIC_CHILD_PATTERNS = {
    "Vendor Credit Memos/Ball Detention Credits": r"\bdetention\b",
}


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


def _document_semantic_text(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or document.get("ai_extraction") or {}
    return " ".join(
        [
            str(document.get("file_name") or ""),
            str(document.get("raw_text") or document.get("document_text") or "")[:16000],
            " ".join(f"{key} {value}" for key, value in list(fields.items())[:80]),
        ]
    ).lower()


def _reference_family(token: Any) -> str:
    value = str(token or "").strip().upper()
    if re.fullmatch(r"W\d{4,8}[A-Z]?", value):
        return "warehouse"
    if re.fullmatch(r"WA\d{3,8}[A-Z]?", value):
        return "warehouse_assembly"
    if re.fullmatch(r"WTR[A-Z0-9_-]{2,20}", value):
        return "warehouse_transfer"
    if re.fullmatch(r"\d{5,7}[A-Z]?", value):
        return "standard_order"
    return ""


def _leading_reference(file_name: Any) -> str:
    name = str(file_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", name).strip()
    if not stem or stem[0] in "_-":
        return ""
    first = re.split(r"[_\s]+", stem, maxsplit=1)[0].strip("-").upper()
    return first if _reference_family(first) else ""


def _context_reference_tokens(context: Dict[str, Any]) -> Set[str]:
    values: List[Any] = []
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
        value = context.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value:
            values.append(value)

    refs: Set[str] = set()
    for value in values:
        token = str(value or "").strip().upper()
        if _reference_family(token):
            refs.add(token)
    return refs


def _current_reference_family(document: Dict[str, Any], context: Dict[str, Any]) -> str:
    # The document's leading operational reference is direct current-document
    # evidence and therefore outranks an incidental/stale BC candidate.
    leading = _leading_reference(document.get("file_name"))
    family = _reference_family(leading)
    if family:
        return family
    families = {_reference_family(ref) for ref in _context_reference_tokens(context)}
    families.discard("")
    return next(iter(families)) if len(families) == 1 else ""


def _example_reference_family(example: Dict[str, Any]) -> str:
    leading = _leading_reference(example.get("file_name"))
    family = _reference_family(leading)
    if family:
        return family
    context = example.get("bc_context") or {}
    families = {_reference_family(ref) for ref in _context_reference_tokens(context)}
    families.discard("")
    return next(iter(families)) if len(families) == 1 else ""


def _same_vendor_reference_family_consensus(
    document: Dict[str, Any],
    context: Dict[str, Any],
    support_examples: List[Dict[str, Any]],
    *,
    minimum_labels: int = 2,
) -> Dict[str, Any]:
    family = _current_reference_family(document, context)
    if not family:
        return {}

    routes: List[str] = []
    for example in _same_vendor_examples(document, support_examples):
        if _example_reference_family(example) != family:
            continue
        route = normalize_route_path(example.get("route_path"))
        if route:
            routes.append(route)

    if len(routes) < minimum_labels:
        return {}
    counts = Counter(routes)
    if len(counts) != 1:
        return {}
    route, count = counts.most_common(1)[0]
    return {
        "reference_family": family,
        "route": route,
        "label_count": int(count),
    }


def _current_operational_references(document: Dict[str, Any], context: Dict[str, Any]) -> Set[str]:
    refs = _context_reference_tokens(context)
    leading = _leading_reference(document.get("file_name"))
    if leading:
        refs.add(leading)
    return refs


def _example_reference_haystack(example: Dict[str, Any]) -> str:
    context = example.get("bc_context") or {}
    values = sorted(_context_reference_tokens(context))
    return " ".join(
        [
            str(example.get("source_route_path") or ""),
            str(example.get("raw_route_path") or ""),
            str(example.get("placement_path") or ""),
            str(example.get("file_name") or ""),
            " ".join(values),
        ]
    ).upper()


def _same_vendor_exact_reference_consensus(
    document: Dict[str, Any],
    context: Dict[str, Any],
    support_examples: List[Dict[str, Any]],
    *,
    minimum_labels: int = 2,
) -> Dict[str, Any]:
    refs = _current_operational_references(document, context)
    if not refs:
        return {}

    by_ref: Dict[str, List[str]] = defaultdict(list)
    for example in _same_vendor_examples(document, support_examples):
        route = normalize_route_path(example.get("route_path"))
        if not route:
            continue
        haystack = _example_reference_haystack(example)
        for ref in refs:
            if re.search(rf"(?<![A-Z0-9]){re.escape(ref)}(?![A-Z0-9])", haystack):
                by_ref[ref].append(route)

    candidates: List[Dict[str, Any]] = []
    for ref, routes in by_ref.items():
        counts = Counter(routes)
        if len(routes) < minimum_labels or len(counts) != 1:
            continue
        route, count = counts.most_common(1)[0]
        candidates.append({"reference": ref, "route": route, "label_count": int(count)})

    if not candidates:
        return {}
    route_set = {item["route"] for item in candidates}
    if len(route_set) != 1:
        return {}
    candidates.sort(key=lambda item: (-int(item["label_count"]), str(item["reference"])))
    top = candidates[0]
    return {
        "route": top["route"],
        "reference": top["reference"],
        "label_count": top["label_count"],
        "matching_references": candidates,
    }


def _same_vendor_exact_route_count(
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


def _semantic_child_recovery(
    document: Dict[str, Any],
    support_examples: List[Dict[str, Any]],
    raw_model_route: str,
) -> Dict[str, Any]:
    route = normalize_route_path(raw_model_route)
    pattern = _SEMANTIC_CHILD_PATTERNS.get(route)
    if not pattern:
        return {}
    if not re.search(pattern, _document_semantic_text(document), flags=re.IGNORECASE):
        return {}
    count = _same_vendor_exact_route_count(document, support_examples, route)
    if count < 2:
        return {}
    return {
        "route": route,
        "label_count": count,
        "semantic_pattern": pattern,
    }


def _authority_blockers(result: Dict[str, Any]) -> List[str]:
    guard = result.get("authority_guard") or {}
    return [str(item) for item in (guard.get("blockers") or [])]


def _hard_safety_veto(result: Dict[str, Any]) -> bool:
    runtime = result.get("runtime_authority_overlay") or {}
    if runtime.get("action") == "force_review":
        return True
    coverage = result.get("coverage_authority") or {}
    if str(coverage.get("action") or "").startswith("force_review_"):
        return True
    blockers = _authority_blockers(result)
    return any(
        fragment in blocker
        for blocker in blockers
        for fragment in _HARD_AUTHORITY_BLOCKER_FRAGMENTS
    )


def _authority_review_is_recoverable(result: Dict[str, Any]) -> bool:
    blockers = _authority_blockers(result)
    if not blockers:
        return True
    for blocker in blockers:
        if any(fragment in blocker for fragment in _HARD_AUTHORITY_BLOCKER_FRAGMENTS):
            return False
        if not any(fragment in blocker for fragment in _RECOVERABLE_AUTHORITY_BLOCKERS):
            return False
    return True


def _raw_model_route(result: Dict[str, Any]) -> str:
    guard = result.get("authority_guard") or {}
    return normalize_route_path(guard.get("raw_model_route"))


def _raw_model_confidence(result: Dict[str, Any]) -> float:
    guard = result.get("authority_guard") or {}
    try:
        return float(guard.get("raw_model_confidence") or result.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _model_route_compatible(model_route: str, learned_route: str) -> bool:
    model = normalize_route_path(model_route)
    learned = normalize_route_path(learned_route)
    return bool(
        model
        and learned
        and (
            model == learned
            or model.startswith(learned + "/")
        )
    )


def _grant(
    result: Dict[str, Any],
    *,
    route: str,
    contract: Dict[str, Any],
    action: str,
    reason: str,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    output = dict(result)
    output["pre_coverage_recovery_decision"] = output.get("decision")
    output["pre_coverage_recovery_route"] = output.get("route_path")
    output["decision"] = DECISION_AUTO_ROUTE
    output["route_path"] = normalize_route_path(route)
    threshold = float(contract.get("auto_route_threshold") or output.get("auto_route_threshold") or 0.92)
    output["confidence"] = max(float(output.get("confidence") or 0.0), threshold)
    output["blockers"] = []
    output["warnings"] = []
    output["reason"] = reason
    recovery = {
        "action": action,
        "granted_route": output["route_path"],
        "blockers": [],
    }
    if evidence:
        recovery.update(evidence)
    output["coverage_recovery"] = recovery
    return output


async def decide_ap_route_with_coverage_recovery(
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
    context = bc_context or {}
    support = list(support_examples if support_examples is not None else (examples or []))
    result = await _base_coverage_decide(
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

    if result.get("decision") == DECISION_AUTO_ROUTE:
        return result
    if result.get("decision") != DECISION_NEEDS_REVIEW:
        return result
    if _hard_safety_veto(result) or not _authority_review_is_recoverable(result):
        return result

    # Exact current-reference Accounting consensus is the strongest recovery.
    # Unlike the earlier coverage layer, standard numeric BC references are
    # included here in addition to W/WA/WTR references.
    exact = _same_vendor_exact_reference_consensus(document, context, support)
    exact_route = normalize_route_path(exact.get("route"))
    if exact_route and route_is_allowed(exact_route, contract, context):
        return _grant(
            result,
            route=exact_route,
            contract=contract,
            action="promote_extended_exact_reference_consensus",
            reason=(
                "repeated same-vendor Accounting labels for exact current reference "
                f"{exact.get('reference')} agree on {exact_route}"
            ),
            evidence={"exact_reference_consensus": exact},
        )

    # Learn the vendor's route from the current operational reference family,
    # but only when repeated labels for that family are unanimous, the raw model
    # independently agrees with the learned route/family, and full supervised
    # support independently names the same canonical route with margin >= 3.
    family = _same_vendor_reference_family_consensus(document, context, support)
    family_route = normalize_route_path(family.get("route"))
    guard = result.get("authority_guard") or {}
    full_route = normalize_route_path(guard.get("full_support_top_route"))
    full_margin = float(guard.get("full_support_margin") or 0.0)
    raw_route = _raw_model_route(result)
    raw_confidence = _raw_model_confidence(result)
    threshold = float(vendor_auto_threshold or contract.get("auto_route_threshold") or 0.92)
    if (
        family_route
        and int(family.get("label_count") or 0) >= 2
        and full_route == family_route
        and full_margin >= 3.0
        and _model_route_compatible(raw_route, family_route)
        and raw_confidence >= threshold
        and route_is_allowed(family_route, contract, context)
    ):
        return _grant(
            result,
            route=family_route,
            contract=contract,
            action="promote_reference_family_accounting_consensus",
            reason=(
                "repeated same-vendor Accounting labels for reference family "
                f"{family.get('reference_family')} unanimously select {family_route}; "
                "raw model and full supervised support independently agree"
            ),
            evidence={
                "reference_family_consensus": family,
                "raw_model_route": raw_route,
                "raw_model_confidence": raw_confidence,
                "full_support_top_route": full_route,
                "full_support_margin": full_margin,
            },
        )

    # Semantically specific child workflows may recover only when the semantic
    # distinction is present in the current document and the vendor has repeated
    # Accounting labels for that exact child destination.
    semantic_child = _semantic_child_recovery(document, support, raw_route)
    child_route = normalize_route_path(semantic_child.get("route"))
    if (
        child_route
        and raw_confidence >= threshold
        and route_is_allowed(child_route, contract, context)
    ):
        return _grant(
            result,
            route=child_route,
            contract=contract,
            action="promote_semantic_child_accounting_consensus",
            reason=(
                "current-document semantic evidence and repeated same-vendor Accounting "
                f"labels agree on specific child workflow {child_route}"
            ),
            evidence={"semantic_child_consensus": semantic_child},
        )

    result["coverage_recovery"] = {"action": "retain_review", "blockers": []}
    return result


# Drop-in name used by the evaluator monkeypatch and future runtime integration.
decide_ap_route_with_authority_guard = decide_ap_route_with_coverage_recovery
