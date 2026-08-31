"""Fail-closed runtime-authority guard for learned AP routing.

The bounded LLM remains responsible for interpreting one document, but automatic
routing authority is granted only when that proposal is compatible with the
wider supervised Accounting evidence and current Business Central/order context.

V117 principles
---------------
* A vendor may have one stable workflow or many legitimate workflows.
* Stable same-vendor evidence may correct a generic model interpretation.
* Variable vendors require discriminating current-document/context evidence;
  vendor frequency or generic filename shape alone can never grant authority.
* Route-neutral lexical similarity may discriminate workflows, but route labels
  are never used as input text features.
* Current order/reference family is a safety signal, not a routing rule.
* Cross-vendor exact-reference collisions are blocked only when the model
  actually relied on that foreign reference/example.
* Irrelevant BC matches may not poison a non-BC-dependent route forever.
* Nothing in this module writes SharePoint, Mongo, or Business Central.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from services.ap_routing_decision_service import (
    DECISION_AUTO_ROUTE,
    DECISION_NEEDS_REVIEW,
    _bc_context_is_resolved,
    _route_requires_bc_context,
    _supervised_route_support,
    decide_ap_route,
    route_is_allowed,
)
from services.ap_routing_learning_service import (
    normalize_route_path,
    normalize_vendor_name,
    score_example_similarity,
)


def _review_route(contract: Dict[str, Any]) -> str:
    return normalize_route_path(contract.get("review_route")) if "review_route" in contract else ""


def _manual_only_routes(contract: Dict[str, Any]) -> set[str]:
    return {
        normalize_route_path(route)
        for route in (contract.get("manual_only_routes") or [])
        if normalize_route_path(route)
    }


def _document_vendor(document: Dict[str, Any]) -> str:
    extracted = document.get("extracted_fields") or document.get("ai_extraction") or {}
    return str(
        document.get("vendor_canonical")
        or document.get("vendor_raw")
        or extracted.get("vendor")
        or extracted.get("vendor_name")
        or ""
    ).strip()


def _document_type(document: Dict[str, Any]) -> str:
    return str(document.get("document_type") or document.get("suggested_job_type") or "").strip()


def _example_vendor(example: Dict[str, Any]) -> str:
    return str(
        example.get("vendor_name")
        or example.get("vendor_canonical")
        or ((example.get("extracted_fields") or {}).get("vendor"))
        or ""
    ).strip()


def _example_id(example: Dict[str, Any]) -> str:
    return str(
        example.get("fingerprint")
        or example.get("document_id")
        or example.get("source_item_id")
        or ""
    )


def _same_vendor_examples(
    document: Dict[str, Any],
    examples: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    vendor_key = normalize_vendor_name(_document_vendor(document))
    if not vendor_key:
        return []
    return [
        example
        for example in examples
        if normalize_vendor_name(_example_vendor(example)) == vendor_key
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
        "routing_verified_order_numbers",
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


def _leading_reference_from_filename(file_name: Any) -> str:
    name = str(file_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", name).strip()
    if not stem or stem[0] in "_-":
        return ""
    first = re.split(r"[_\s]+", stem, maxsplit=1)[0].strip("-")
    return first.upper()


def _reference_family_value(value: Any) -> str:
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
        family = _reference_family_value(ref)
        if family:
            return family
    return _reference_family_value(_leading_reference_from_filename(document.get("file_name")))


def _example_reference_family(example: Dict[str, Any]) -> str:
    context = example.get("bc_context") or {}
    for ref in sorted(_context_refs(context)):
        family = _reference_family_value(ref)
        if family:
            return family
    return _reference_family_value(_leading_reference_from_filename(example.get("file_name")))


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


def _vendor_names_conflict(left: str, right: str) -> bool:
    a = normalize_vendor_name(left)
    b = normalize_vendor_name(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return False
    a_tokens = {token for token in a.split() if len(token) >= 4}
    b_tokens = {token for token in b.split() if len(token) >= 4}
    return bool(a_tokens and b_tokens and not a_tokens.intersection(b_tokens))


def _bc_vendor_mismatch(document: Dict[str, Any], context: Dict[str, Any]) -> bool:
    return _vendor_names_conflict(_document_vendor(document), _context_vendor_name(context))


def _prediction_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    ensemble = result.get("ensemble_reconciliation") or {}
    original = ensemble.get("original_prediction") or {}
    if original:
        return original
    return result.get("prediction") or {}


def _raw_model_route(result: Dict[str, Any]) -> str:
    ensemble = result.get("ensemble_reconciliation") or {}
    return normalize_route_path(
        ensemble.get("original_model_route")
        or ((_prediction_payload(result)).get("proposed_route"))
    )


def _raw_model_confidence(result: Dict[str, Any]) -> float:
    ensemble = result.get("ensemble_reconciliation") or {}
    value = ensemble.get("original_model_confidence")
    if value is None:
        value = (_prediction_payload(result)).get("confidence")
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _model_unresolved(result: Dict[str, Any]) -> List[str]:
    return [str(item) for item in ((_prediction_payload(result)).get("unresolved") or [])]


def _model_bc_refs(result: Dict[str, Any]) -> Set[str]:
    return {
        str(value).strip().upper()
        for value in ((_prediction_payload(result)).get("bc_refs_used") or [])
        if str(value).strip()
    }


def _model_matched_ids(result: Dict[str, Any]) -> Set[str]:
    return {
        str(value)
        for value in ((_prediction_payload(result)).get("matched_example_ids") or [])
        if str(value)
    }


def _semantic_route_support(
    document: Dict[str, Any],
    context: Dict[str, Any],
    examples: List[Dict[str, Any]],
    *,
    same_vendor_only: bool,
) -> Dict[str, Any]:
    current_vendor = _document_vendor(document)
    current_vendor_key = normalize_vendor_name(current_vendor)
    current_type = _document_type(document)
    current_ref_family = _current_reference_family(document, context)
    current_file = str(document.get("file_name") or "")
    current_raw = str(document.get("raw_text") or document.get("document_text") or "")
    current_fields = document.get("extracted_fields") or document.get("ai_extraction") or {}

    rows: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "route_path": "",
            "support_count": 0,
            "best_score": 0.0,
            "reference_family_matches": 0,
            "top_example_ids": [],
        }
    )

    for example in examples:
        example_vendor_key = normalize_vendor_name(_example_vendor(example))
        if same_vendor_only:
            if not current_vendor_key or example_vendor_key != current_vendor_key:
                continue
            score_vendor = current_vendor
        else:
            score_vendor = ""

        route = normalize_route_path(example.get("route_path"))
        if not route:
            continue
        score = score_example_similarity(
            example,
            vendor_name=score_vendor,
            document_type=current_type,
            bc_context=context,
            file_name=current_file,
            raw_text=current_raw,
            extracted_fields=current_fields,
        )
        ref_match = bool(
            current_ref_family
            and _example_reference_family(example) == current_ref_family
        )
        if ref_match:
            score += 3.0

        row = rows[route]
        row["route_path"] = route
        row["support_count"] += 1
        row["best_score"] = max(float(row["best_score"]), round(float(score), 4))
        if ref_match:
            row["reference_family_matches"] += 1
        example_id = _example_id(example)
        if example_id and len(row["top_example_ids"]) < 4:
            row["top_example_ids"].append(example_id)

    ranked = sorted(
        rows.values(),
        key=lambda row: (
            float(row["best_score"]) + min(1.5, max(0, int(row["support_count"]) - 1) * 0.25),
            int(row["support_count"]),
        ),
        reverse=True,
    )
    top = ranked[0] if ranked else {}
    second = ranked[1] if len(ranked) > 1 else {}
    margin = round(float(top.get("best_score") or 0.0) - float(second.get("best_score") or 0.0), 4)
    threshold = 7.5 if same_vendor_only else 5.0
    discriminating = bool(
        top
        and float(top.get("best_score") or 0.0) >= threshold
        and (len(ranked) == 1 or margin >= 1.0)
    )
    return {
        "top_route": normalize_route_path(top.get("route_path")),
        "top_score": float(top.get("best_score") or 0.0),
        "second_route": normalize_route_path(second.get("route_path")),
        "second_score": float(second.get("best_score") or 0.0),
        "margin": margin,
        "discriminating": discriminating,
        "route_count": len(ranked),
        "routes": ranked[:10],
    }


def _stable_vendor_route(same_vendor: List[Dict[str, Any]]) -> Tuple[str, int]:
    routes = [normalize_route_path(item.get("route_path")) for item in same_vendor]
    routes = [route for route in routes if route]
    unique = sorted(set(routes))
    if len(unique) == 1 and len(routes) >= 3:
        return unique[0], len(routes)
    return "", len(routes)


def _payment_hold_intent(document: Dict[str, Any]) -> bool:
    fields = document.get("extracted_fields") or document.get("ai_extraction") or {}
    text = " ".join(
        [
            str(document.get("file_name") or ""),
            str(document.get("raw_text") or document.get("document_text") or "")[:12000],
            " ".join(f"{key} {value}" for key, value in list(fields.items())[:60]),
        ]
    ).lower()
    patterns = (
        "do not pay",
        "don't pay",
        "dont pay",
        "cost is wrong",
        "price is wrong",
        "incorrect cost",
        "incorrect price",
        "double bill",
        "double billed",
        "duplicate invoice",
        "hold payment",
        "do not process",
        "payment dispute",
    )
    return any(pattern in text for pattern in patterns)


def _current_context_support(top: Dict[str, Any]) -> bool:
    return bool(
        int(top.get("exact_bc_reference_matches") or 0) > 0
        or int(top.get("location_matches") or 0) > 0
        or int(top.get("ship_to_matches") or 0) > 0
    )


def _cross_vendor_exact_reference_dependency(
    document: Dict[str, Any],
    bc_context: Dict[str, Any],
    examples: List[Dict[str, Any]],
    candidate_route: str,
    result: Dict[str, Any],
) -> bool:
    """Block only when the model actually relied on a foreign exact reference.

    REV3 showed that merely *having* a colliding reference somewhere in the
    bounded context can veto a correct sparse-vendor decision. V117 requires
    model reliance (cited BC ref or matched foreign example) before blocking.
    """
    refs = _context_refs(bc_context)
    if not refs:
        return False

    current_vendor = normalize_vendor_name(_document_vendor(document))
    route = normalize_route_path(candidate_route)
    model_refs = _model_bc_refs(result)
    model_ids = _model_matched_ids(result)
    foreign_ids: Set[str] = set()
    same_vendor_match = False
    foreign_match = False

    for example in examples:
        if normalize_route_path(example.get("route_path")) != route:
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
    cited_foreign_ref = bool(refs.intersection(model_refs))
    matched_foreign_example = bool(foreign_ids.intersection(model_ids))
    return cited_foreign_ref or matched_foreign_example


def _promotable_unresolved(
    result: Dict[str, Any],
    *,
    context_vendor_mismatch: bool,
) -> bool:
    unresolved = _model_unresolved(result)
    if not unresolved:
        return True
    for item in unresolved:
        text = item.lower()
        if "model_error:" in text:
            return False
        bc_related = any(
            token in text
            for token in (
                "business central",
                "bc context",
                "posted_sales",
                "purchase order",
                " po ",
                "vendor",
            )
        )
        if context_vendor_mismatch and bc_related:
            continue
        return False
    return True


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


def _grant_route(
    result: Dict[str, Any],
    *,
    route: str,
    contract: Dict[str, Any],
    guard: Dict[str, Any],
    action: str,
    reason: str,
    confidence: Optional[float] = None,
) -> Dict[str, Any]:
    output = dict(result)
    output["pre_authority_guard_decision"] = output.get("decision")
    output["pre_authority_guard_route"] = output.get("route_path")
    output["decision"] = DECISION_AUTO_ROUTE
    output["route_path"] = normalize_route_path(route)
    threshold = float(contract.get("auto_route_threshold") or output.get("auto_route_threshold") or 0.92)
    output["confidence"] = max(float(confidence if confidence is not None else output.get("confidence") or 0.0), threshold)
    output["blockers"] = []
    output["warnings"] = []
    output["reason"] = reason
    guard["action"] = action
    guard["blockers"] = []
    guard["granted_route"] = output["route_path"]
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
    """Run bounded AI routing, then grant/deny automatic runtime authority."""
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
    semantic_same = _semantic_route_support(document, context, same_vendor, same_vendor_only=True)
    semantic_global = _semantic_route_support(document, context, evidence_examples, same_vendor_only=False)
    stable_route, stable_count = _stable_vendor_route(same_vendor)
    current_ref_family = _current_reference_family(document, context)
    context_vendor_mismatch = _bc_vendor_mismatch(document, context)
    route = normalize_route_path(result.get("route_path"))
    raw_model_route = _raw_model_route(result)
    raw_model_confidence = _raw_model_confidence(result)
    threshold = float(vendor_auto_threshold or contract.get("auto_route_threshold") or 0.92)

    guard: Dict[str, Any] = {
        "action": "allow_existing_decision",
        "same_vendor_label_count": len(same_vendor),
        "same_vendor_route_count": len(full_support.get("routes") or []),
        "full_support_top_route": normalize_route_path(full_support.get("top_route")),
        "full_support_margin": float(full_support.get("margin") or 0.0),
        "semantic_same_vendor": semantic_same,
        "semantic_global": semantic_global,
        "stable_vendor_route": stable_route,
        "stable_vendor_label_count": stable_count,
        "current_reference_family": current_ref_family,
        "bc_vendor_mismatch": context_vendor_mismatch,
        "raw_model_route": raw_model_route,
        "raw_model_confidence": raw_model_confidence,
        "manual_only_route": route in _manual_only_routes(contract),
    }
    result["full_supervised_route_support"] = full_support

    # ------------------------------------------------------------------
    # Review-state recovery: increase automation only from explicit evidence.
    # ------------------------------------------------------------------
    if result.get("decision") != DECISION_AUTO_ROUTE:
        promotable_unresolved = _promotable_unresolved(
            result,
            context_vendor_mismatch=context_vendor_mismatch,
        )

        # Stable same-vendor workflows: three or more Accounting labels all
        # agree. A high-confidence raw model agreement can be promoted; a very
        # strong semantic match can also correct a generic model interpretation.
        if stable_route and route_is_allowed(stable_route, contract, context):
            if (
                raw_model_route == stable_route
                and raw_model_confidence >= threshold
                and promotable_unresolved
                and (not _route_requires_bc_context(stable_route, contract) or _bc_context_is_resolved(context))
            ):
                return _grant_route(
                    result,
                    route=stable_route,
                    contract=contract,
                    guard=guard,
                    action="promote_stable_vendor_model_consensus",
                    reason=f"stable same-vendor Accounting workflow and raw model agree on {stable_route}",
                    confidence=raw_model_confidence,
                )
            if (
                semantic_same.get("discriminating")
                and semantic_same.get("top_route") == stable_route
                and float(semantic_same.get("top_score") or 0.0) >= 8.0
                and promotable_unresolved
            ):
                return _grant_route(
                    result,
                    route=stable_route,
                    contract=contract,
                    guard=guard,
                    action="promote_stable_vendor_semantic_consensus",
                    reason=f"stable same-vendor Accounting labels and route-neutral document evidence select {stable_route}",
                    confidence=max(raw_model_confidence, threshold),
                )

        # Variable vendors: allow promotion only when route-neutral same-vendor
        # evidence discriminates the current workflow and independently agrees
        # with the raw model. This is the anti-Tumalo-majority rule.
        if (
            len(full_support.get("routes") or []) > 1
            and semantic_same.get("discriminating")
            and raw_model_route
            and raw_model_route == semantic_same.get("top_route")
            and raw_model_confidence >= threshold
            and route_is_allowed(raw_model_route, contract, context)
            and promotable_unresolved
            and not _family_conflict(current_ref_family, raw_model_route)
        ):
            if not _route_requires_bc_context(raw_model_route, contract) or _bc_context_is_resolved(context):
                return _grant_route(
                    result,
                    route=raw_model_route,
                    contract=contract,
                    guard=guard,
                    action="promote_variable_vendor_semantic_consensus",
                    reason=(
                        "raw model and discriminating same-vendor route-neutral evidence agree on "
                        f"{raw_model_route}"
                    ),
                    confidence=raw_model_confidence,
                )

        # Sparse/new vendor recovery: high-confidence model + route-neutral
        # cross-vendor evidence may automate a non-conflicting route. This is
        # intentionally weaker than same-vendor authority and never overrides a
        # family conflict or unresolved BC-required route.
        if (
            len(same_vendor) < 2
            and semantic_global.get("discriminating")
            and raw_model_route
            and raw_model_route == semantic_global.get("top_route")
            and raw_model_confidence >= threshold
            and route_is_allowed(raw_model_route, contract, context)
            and promotable_unresolved
            and not _family_conflict(current_ref_family, raw_model_route)
        ):
            if not _route_requires_bc_context(raw_model_route, contract) or _bc_context_is_resolved(context):
                return _grant_route(
                    result,
                    route=raw_model_route,
                    contract=contract,
                    guard=guard,
                    action="promote_sparse_vendor_semantic_consensus",
                    reason=f"raw model and route-neutral full-corpus evidence agree on {raw_model_route}",
                    confidence=raw_model_confidence,
                )

        result["authority_guard"] = guard
        return result

    # ------------------------------------------------------------------
    # Automatic-state safety: zero wrong auto-routes remains non-negotiable.
    # ------------------------------------------------------------------
    blockers: List[str] = []

    if route in _manual_only_routes(contract):
        blockers.append(f"route is manual/downstream-only and cannot receive AI runtime authority: {route}")

    # Explicit stop-pay language cannot silently escape a learned DO NOT PAY
    # workflow. Stable same-vendor evidence may safely correct it; otherwise it
    # falls to review rather than guessing another payable queue.
    hold_intent = _payment_hold_intent(document)
    if hold_intent and route != "DO NOT PAY":
        if (
            stable_route == "DO NOT PAY"
            and route_is_allowed("DO NOT PAY", contract, context)
            and semantic_same.get("top_route") == "DO NOT PAY"
        ):
            return _grant_route(
                result,
                route="DO NOT PAY",
                contract=contract,
                guard=guard,
                action="override_stop_pay_stable_consensus",
                reason="explicit stop-pay/incorrect-charge evidence agrees with stable same-vendor Accounting labels",
                confidence=max(raw_model_confidence, threshold),
            )
        blockers.append("explicit stop-pay/incorrect-charge evidence conflicts with proposed payable route")

    # A stable same-vendor workflow may not be ignored by a generic model. For
    # safety we auto-correct only with discriminating semantic evidence; otherwise
    # the disagreement goes to review.
    if stable_route and route != stable_route:
        if (
            semantic_same.get("discriminating")
            and semantic_same.get("top_route") == stable_route
            and float(semantic_same.get("top_score") or 0.0) >= 8.0
            and route_is_allowed(stable_route, contract, context)
        ):
            return _grant_route(
                result,
                route=stable_route,
                contract=contract,
                guard=guard,
                action="override_stable_vendor_semantic_consensus",
                reason=f"stable same-vendor Accounting labels and route-neutral evidence select {stable_route}",
                confidence=max(raw_model_confidence, threshold),
            )
        blockers.append(
            f"candidate route conflicts with stable same-vendor Accounting workflow: predicted {route}, stable {stable_route}"
        )

    # A current order-family conflict is a veto, not a route selector. It catches
    # the unsafe Tumalo Warehouse selection for a standard order without turning
    # the numbering convention into a one-step routing rule.
    if _family_conflict(current_ref_family, route):
        blockers.append(
            f"candidate route family {_route_family(route)} conflicts with current reference family {current_ref_family}"
        )

    if _cross_vendor_exact_reference_dependency(
        document,
        context,
        list(examples or []),
        route,
        result,
    ):
        blockers.append("candidate route relies on an exact current reference seen only under a different vendor")

    route_count = len(full_support.get("routes") or [])
    if route_count > 1:
        # Current-document semantic evidence is the preferred discriminator for
        # variable vendors. Generic vendor majority / filename-shape consensus is
        # intentionally insufficient even if the LLM happens to agree with it.
        if semantic_same.get("discriminating"):
            semantic_route = normalize_route_path(semantic_same.get("top_route"))
            if semantic_route and route != semantic_route:
                blockers.append(
                    "candidate route conflicts with discriminating same-vendor document/context evidence: "
                    f"predicted {route}, semantic support {semantic_route}"
                )
        else:
            top = _top_support_row(full_support)
            top_route = normalize_route_path(full_support.get("top_route"))
            context_authoritative = bool(
                top_route
                and route == top_route
                and int(top.get("support_count") or 0) >= 2
                and float(full_support.get("margin") or 0.0) >= 3.0
                and _current_context_support(top)
            )
            if not context_authoritative:
                blockers.append(
                    "multi-route vendor lacks discriminating current-document or authoritative BC context evidence"
                )

    # Sparse vendors may use the LLM, but a strong route-neutral full-corpus
    # disagreement is a veto. This catches generic-purpose interpretations that
    # conflict with the closest actual Accounting workflows.
    if len(same_vendor) < 2 and semantic_global.get("discriminating"):
        global_route = normalize_route_path(semantic_global.get("top_route"))
        if global_route and route != global_route and _route_family(route) != _route_family(global_route):
            blockers.append(
                "candidate route conflicts with discriminating route-neutral full-corpus evidence: "
                f"predicted {route}, semantic support {global_route}"
            )

    if blockers:
        return _force_review(result, contract=contract, blockers=blockers, guard=guard)

    guard["blockers"] = []
    result["authority_guard"] = guard
    return result
