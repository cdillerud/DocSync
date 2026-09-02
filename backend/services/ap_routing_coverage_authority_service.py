"""Deterministic review-recovery authority for V117 AP routing.

This layer runs *after* the zero-wrong runtime-authority overlay. It may recover
reviewed documents only from evidence that is stronger than vendor-majority or
generic semantic inference:

* explicit current-document DO NOT PAY instructions; or
* repeated same-vendor Accounting labels for the exact current operational
  reference, all agreeing on one canonical route.

It also owns final post-overlay safety boundaries for already-automatic results.
A stable/vendor-majority DO NOT PAY decision is demoted to review when the
current invoice contains clear freight-accessorial evidence, lacks an explicit
stop-pay instruction, and the same vendor has learned Accounting history in a
freight workflow. Likewise, an S&H approval-family destination cannot become
automatic from generic storage/handling semantics when Accounting has never
routed that vendor to that exact S&H destination. These are vetoes only; they
never choose a replacement route.

A runtime-authority veto is final and can never be overridden here. Nothing in
this module writes SharePoint, Mongo, or Business Central.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set

from services.ap_routing_decision_service import (
    DECISION_AUTO_ROUTE,
    DECISION_NEEDS_REVIEW,
    route_is_allowed,
)
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name
from services.ap_routing_runtime_authority_service import (
    decide_ap_route_with_authority_guard as _runtime_decide_ap_route_with_authority_guard,
)


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


def _document_semantic_text(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or document.get("ai_extraction") or {}
    return " ".join(
        [
            str(document.get("file_name") or ""),
            str(document.get("raw_text") or document.get("document_text") or "")[:16000],
            " ".join(f"{key} {value}" for key, value in list(fields.items())[:80]),
        ]
    ).lower()


def _explicit_do_not_pay(document: Dict[str, Any]) -> bool:
    """Require an actual stop-payment instruction, not generic HOLD language."""
    text = _document_semantic_text(document)
    patterns = (
        r"\bdo\s+not\s+pay\b",
        r"\bdon['’]?t\s+pay\b",
        r"\bdont\s+pay\b",
        r"\bdo\s+not\s+process\b",
        r"\bhold\s+payment\b",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _freight_accessorial_intent(document: Dict[str, Any]) -> bool:
    """Recognize current-document freight/accessorial charge semantics.

    These terms are intentionally used only as a *veto* against an unrelated
    exception-workflow auto-route. They never grant a freight destination.
    """
    text = _document_semantic_text(document)
    patterns = (
        r"\byard\s+storage\b",
        r"\bstorage\s+(?:charge|charges|fee|fees|added|invoice|cost|costs)\b",
        r"\baccessorial(?:s|\s+charge|\s+charges)?\b",
        r"\breweigh(?:\s+charge|\s+charges|\s+fee|\s+fees)?\b",
        r"\blayover(?:\s+charge|\s+charges|\s+fee|\s+fees)?\b",
        r"\blumper(?:\s+charge|\s+charges|\s+fee|\s+fees)?\b",
        r"\bredelivery(?:\s+charge|\s+charges|\s+fee|\s+fees)?\b",
        r"\bdemurrage\b",
        r"\bdetention(?:\s+charge|\s+charges|\s+fee|\s+fees)?\b",
        r"\bfreight\s+(?:charge|charges|fee|fees|surcharge|surcharges|adjustment|variance)\b",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _same_vendor_freight_routes(
    document: Dict[str, Any],
    support_examples: List[Dict[str, Any]],
) -> List[str]:
    routes = {
        normalize_route_path(example.get("route_path"))
        for example in _same_vendor_examples(document, support_examples)
    }
    return sorted(
        route
        for route in routes
        if route.startswith("Dropship Not International/Freight")
        or route.startswith("Dropship International/Freight")
    )


def _is_sh_approval_route(route: str) -> bool:
    normalized = normalize_route_path(route)
    return (
        normalized == "S&H Invoices waiting for approval"
        or normalized.startswith("S&H Invoices waiting for approval/")
    )


def _leading_operational_reference(file_name: Any) -> str:
    name = str(file_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", name).strip()
    if not stem or stem[0] in "_-":
        return ""
    first = re.split(r"[_\s]+", stem, maxsplit=1)[0].strip("-").upper()
    if re.fullmatch(r"(?:W\d{4,8}[A-Z]?|WA\d{3,8}[A-Z]?|WTR[A-Z0-9_-]{2,20}|\d{5,7}[A-Z]?)", first):
        return first
    return ""


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
        if re.fullmatch(r"(?:W\d{4,8}[A-Z]?|WA\d{3,8}[A-Z]?|WTR[A-Z0-9_-]{2,20})", token):
            refs.add(token)
    return refs


def _current_operational_references(document: Dict[str, Any], context: Dict[str, Any]) -> Set[str]:
    refs = _context_reference_tokens(context)
    leading = _leading_operational_reference(document.get("file_name"))
    if leading:
        refs.add(leading)
    return refs


def _example_reference_haystack(example: Dict[str, Any]) -> str:
    context = example.get("bc_context") or {}
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
    return " ".join(
        [
            str(example.get("source_route_path") or ""),
            str(example.get("raw_route_path") or ""),
            str(example.get("placement_path") or ""),
            str(example.get("file_name") or ""),
            " ".join(str(value) for value in values),
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
    same_vendor = _same_vendor_examples(document, support_examples)
    for example in same_vendor:
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
        candidates.append({"reference": ref, "route": route, "label_count": count})

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
        "label_count": int(top["label_count"]),
        "matching_references": candidates,
    }


def _has_final_safety_veto(result: Dict[str, Any]) -> bool:
    overlay = result.get("runtime_authority_overlay") or {}
    if overlay.get("action") == "force_review":
        return True
    guard = result.get("authority_guard") or {}
    return guard.get("action") == "force_review"


def _force_review_coverage(
    result: Dict[str, Any],
    *,
    contract: Dict[str, Any],
    blocker: str,
    action: str,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    output = dict(result)
    output["pre_coverage_authority_decision"] = output.get("decision")
    output["pre_coverage_authority_route"] = output.get("route_path")
    output["decision"] = DECISION_NEEDS_REVIEW
    output["route_path"] = normalize_route_path(contract.get("review_route")) if "review_route" in contract else ""
    output["blockers"] = list(output.get("blockers") or []) + [blocker]
    output["reason"] = blocker
    coverage = {
        "action": action,
        "blockers": [blocker],
    }
    if evidence:
        coverage.update(evidence)
    output["coverage_authority"] = coverage
    return output


def _grant_runtime_coverage(
    result: Dict[str, Any],
    *,
    route: str,
    contract: Dict[str, Any],
    action: str,
    reason: str,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    output = dict(result)
    output["pre_coverage_authority_decision"] = output.get("decision")
    output["pre_coverage_authority_route"] = output.get("route_path")
    output["decision"] = DECISION_AUTO_ROUTE
    output["route_path"] = normalize_route_path(route)
    threshold = float(contract.get("auto_route_threshold") or output.get("auto_route_threshold") or 0.92)
    output["confidence"] = max(float(output.get("confidence") or 0.0), threshold)
    output["blockers"] = []
    output["warnings"] = []
    output["reason"] = reason

    coverage = {
        "action": action,
        "granted_route": output["route_path"],
        "blockers": [],
    }
    if evidence:
        coverage.update(evidence)
    output["coverage_authority"] = coverage
    return output


async def decide_ap_route_with_coverage_authority(
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
    """Run zero-wrong authority first, then recover only deterministic reviews."""
    context = bc_context or {}
    support = list(support_examples if support_examples is not None else (examples or []))
    result = await _runtime_decide_ap_route_with_authority_guard(
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

    # Final automatic-state safety boundaries. These rules only demote to review
    # and never select a replacement route.
    if result.get("decision") == DECISION_AUTO_ROUTE:
        route = normalize_route_path(result.get("route_path"))
        freight_routes = _same_vendor_freight_routes(document, support)
        if (
            route == "DO NOT PAY"
            and not _explicit_do_not_pay(document)
            and _freight_accessorial_intent(document)
            and freight_routes
        ):
            return _force_review_coverage(
                result,
                contract=contract,
                blocker=(
                    "current-document freight/accessorial evidence conflicts with "
                    "automatic DO NOT PAY exception-workflow authority"
                ),
                action="force_review_freight_accessorial_dnp_conflict",
                evidence={
                    "freight_accessorial_intent": True,
                    "same_vendor_freight_routes": freight_routes,
                },
            )

        if _is_sh_approval_route(route):
            exact_count = _same_vendor_exact_route_count(document, support, route)
            if exact_count < 1:
                return _force_review_coverage(
                    result,
                    contract=contract,
                    blocker=(
                        "S&H approval workflow requires same-vendor Accounting authority "
                        "for the exact destination before automatic routing"
                    ),
                    action="force_review_sh_approval_without_same_vendor_authority",
                    evidence={
                        "same_vendor_exact_route_label_count": exact_count,
                        "same_vendor_label_count": len(_same_vendor_examples(document, support)),
                    },
                )
        return result

    if result.get("decision") != DECISION_NEEDS_REVIEW:
        return result
    if _has_final_safety_veto(result):
        return result

    # Direct stop-payment language is itself route authority. This intentionally
    # excludes generic HOLD/checking/problem wording.
    if _explicit_do_not_pay(document) and route_is_allowed("DO NOT PAY", contract, context):
        return _grant_runtime_coverage(
            result,
            route="DO NOT PAY",
            contract=contract,
            action="promote_explicit_do_not_pay",
            reason="explicit current-document DO NOT PAY instruction grants deterministic review recovery",
            evidence={"explicit_do_not_pay": True},
        )

    # Accounting may encode project/workflow authority in nested source
    # placement paths. Repeated same-vendor labels for the *exact* current
    # operational reference are stronger than a generic vendor majority.
    consensus = _same_vendor_exact_reference_consensus(document, context, support)
    consensus_route = normalize_route_path(consensus.get("route"))
    if consensus_route and route_is_allowed(consensus_route, contract, context):
        return _grant_runtime_coverage(
            result,
            route=consensus_route,
            contract=contract,
            action="promote_exact_reference_accounting_consensus",
            reason=(
                "repeated same-vendor Accounting labels for exact current reference "
                f"{consensus.get('reference')} agree on {consensus_route}"
            ),
            evidence={"exact_reference_consensus": consensus},
        )

    result["coverage_authority"] = {
        "action": "retain_review",
        "blockers": [],
    }
    return result


# Drop-in name used by the held-out evaluator monkeypatch and future runtime integration.
decide_ap_route_with_authority_guard = decide_ap_route_with_coverage_authority
