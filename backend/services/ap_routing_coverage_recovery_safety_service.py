"""Final safety and high-precision recovery boundary for V117 coverage work.

This layer sits on top of the additive coverage-recovery service. It neutralizes
recovery/override classes that proved unsafe in measured held-out data while
preserving useful deterministic reference-family gains. It may also recover an
explicit current-document stop-pay command to DO NOT PAY when no hard authority
conflict is present.

Measured V117 findings encoded here:
* ordinary numeric BC references can be incidental/stale and may not grant an
  automatic route through the extended exact-reference recovery path;
* a generic credit memo may not be auto-routed to DO NOT PAY from vendor-majority
  evidence when that vendor also has learned Vendor Credit Memo workflows, unless
  the current document itself contains an explicit stop-pay instruction;
* current-document semantic words plus repeated same-vendor child-route history
  are not sufficient by themselves to grant a specific child workflow. The
  measured Ball detention false-positive proved that semantic-child recovery
  needs another independent discriminator before it can be automatic;
* an explicit current-document stop-pay instruction may never be overridden by a
  learned payable vendor workflow;
* stable-vendor semantic overrides are not sufficient automatic authority for
  non-AP operational documents, where extracted vendor identity may describe a
  referenced supplier/customer rather than the workflow owner; and
* a strong imperative stop-pay command may recover a review only when the review
  is caused by soft ambiguity. Cross-vendor/reference-family/dynamic-route hard
  conflicts remain fail-closed.

This service performs no SharePoint, Mongo, or Business Central writes.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from services.ap_routing_coverage_recovery_service import (
    decide_ap_route_with_authority_guard as _base_recovery_decide,
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
    key = normalize_vendor_name(_document_vendor(document))
    if not key:
        return []
    return [
        example
        for example in support_examples
        if normalize_vendor_name(_example_vendor(example)) == key
    ]


def _document_text(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or document.get("ai_extraction") or {}
    return " ".join(
        [
            str(document.get("file_name") or ""),
            str(document.get("raw_text") or document.get("document_text") or "")[:16000],
            " ".join(f"{key} {value}" for key, value in list(fields.items())[:80]),
        ]
    ).lower()


def _explicit_stop_pay(document: Dict[str, Any]) -> bool:
    text = _document_text(document)
    patterns = (
        r"\bdo\s+not\s+pay\b",
        r"\bdon['’]?t\s+pay\b",
        r"\bdont\s+pay\b",
        r"\bdo\s+not\s+process\b",
        r"\bhold\s+payment\b",
        r"\binvoice\s+not\s+paid\b",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _explicit_stop_pay_command(document: Dict[str, Any]) -> bool:
    """Return True only for imperative/current instructions safe enough to recover."""
    text = _document_text(document)
    patterns = (
        r"\bdo\s+not\s+pay\b",
        r"\bdon['’]?t\s+pay\b",
        r"\bdont\s+pay\b",
        r"\bdo\s+not\s+process\b",
        r"\bhold\s+payment\b",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _normalized_document_type(document: Dict[str, Any]) -> str:
    value = str(document.get("document_type") or document.get("suggested_job_type") or "")
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _is_credit_memo(document: Dict[str, Any]) -> bool:
    return _normalized_document_type(document) in {"credit_memo", "vendor_credit_memo"}


def _same_vendor_credit_workflow_routes(
    document: Dict[str, Any],
    support_examples: List[Dict[str, Any]],
) -> List[str]:
    routes = {
        normalize_route_path(example.get("route_path"))
        for example in _same_vendor_examples(document, support_examples)
    }
    return sorted(route for route in routes if route.startswith("Vendor Credit Memos"))


def _review_has_hard_authority_conflict(result: Dict[str, Any]) -> bool:
    guard = result.get("authority_guard") or {}
    evidence = [
        str(result.get("reason") or ""),
        *[str(value) for value in (result.get("blockers") or [])],
        *[str(value) for value in (guard.get("blockers") or [])],
    ]
    combined = " | ".join(evidence).lower()
    hard_fragments = (
        "exact current reference seen only under a different vendor",
        "cross-vendor",
        "candidate route family",
        "reference family conflicts",
        "contract-valid dynamic route lacks",
        "specific static child route lacks",
        "route requires resolved business central/order context",
        "warehouse tooling",
    )
    return any(fragment in combined for fragment in hard_fragments)


def _force_review(
    result: Dict[str, Any],
    *,
    contract: Dict[str, Any],
    blocker: str,
    action: str,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    output = dict(result)
    output["pre_recovery_safety_decision"] = output.get("decision")
    output["pre_recovery_safety_route"] = output.get("route_path")
    output["decision"] = DECISION_NEEDS_REVIEW
    output["route_path"] = normalize_route_path(contract.get("review_route")) if "review_route" in contract else ""
    output["blockers"] = list(output.get("blockers") or []) + [blocker]
    output["reason"] = blocker
    safety = {
        "action": action,
        "blockers": [blocker],
    }
    if evidence:
        safety.update(evidence)
    output["coverage_recovery_safety"] = safety
    return output


def _promote_explicit_stop_pay_review(result: Dict[str, Any]) -> Dict[str, Any]:
    output = dict(result)
    output["pre_recovery_safety_decision"] = output.get("decision")
    output["pre_recovery_safety_route"] = output.get("route_path")
    output["decision"] = DECISION_AUTO_ROUTE
    output["route_path"] = "DO NOT PAY"
    try:
        current_confidence = float(output.get("confidence") or 0.0)
    except (TypeError, ValueError):
        current_confidence = 0.0
    output["confidence"] = max(current_confidence, 0.99)
    output["blockers"] = []
    output["reason"] = "explicit current-document stop-pay command grants deterministic final recovery"
    output["coverage_recovery_safety"] = {
        "action": "promote_explicit_stop_pay_review_recovery",
        "blockers": [],
        "explicit_stop_pay": True,
    }
    return output


async def decide_ap_route_with_recovery_safety(
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
    support = list(support_examples if support_examples is not None else (examples or []))
    result = await _base_recovery_decide(
        db,
        document=document,
        bc_context=bc_context or {},
        contract=contract,
        examples=examples,
        support_examples=support_examples,
        vendor_auto_threshold=vendor_auto_threshold,
        model=model,
        llm_send=llm_send,
    )

    strong_stop_pay = _explicit_stop_pay_command(document)
    if result.get("decision") != DECISION_AUTO_ROUTE:
        if strong_stop_pay and not _review_has_hard_authority_conflict(result):
            return _promote_explicit_stop_pay_review(result)
        return result

    route = normalize_route_path(result.get("route_path"))
    guard = result.get("authority_guard") or {}
    guard_action = str(guard.get("action") or "")
    document_type = _normalized_document_type(document)

    # A strong explicit stop-pay command already routed to DO NOT PAY outranks
    # downstream recovery demotions such as ordinary numeric exact-reference
    # safety. This preserves direct current-document authority without weakening
    # any hard blocker because the base decision is already automatic here.
    if strong_stop_pay and route == "DO NOT PAY":
        result["coverage_recovery_safety"] = {
            "action": "allow_explicit_stop_pay_dnp_precedence",
            "blockers": [],
            "explicit_stop_pay": True,
        }
        return result

    # Current-document stop-pay language is a final safety boundary. A learned
    # payable workflow may never override it. We fail closed rather than changing
    # the destination when a conflicting automatic payable route survives below.
    if _explicit_stop_pay(document) and route != "DO NOT PAY":
        return _force_review(
            result,
            contract=contract,
            blocker=(
                "explicit current-document stop-pay instruction conflicts with the automatic "
                f"payable route {route}"
            ),
            action="force_review_explicit_stop_pay_route_conflict",
            evidence={
                "proposed_route": route,
                "authority_guard_action": guard_action,
                "explicit_stop_pay": True,
            },
        )

    # Stable vendor semantic consensus is useful for normal AP invoices but is
    # not sufficient automatic authority for operational/non-AP documents. In
    # those documents a referenced vendor can be extracted even when the actual
    # Accounting workflow belongs to a warehouse or handling process.
    if guard_action == "override_stable_vendor_semantic_consensus" and document_type != "ap_invoice":
        return _force_review(
            result,
            contract=contract,
            blocker=(
                "stable-vendor semantic consensus cannot grant automatic authority for "
                f"non-AP operational document type {document_type or 'unknown'}"
            ),
            action="force_review_stable_vendor_override_non_ap_document",
            evidence={
                "document_type": document_type,
                "authority_guard_action": guard_action,
            },
        )

    recovery = result.get("coverage_recovery") or {}
    recovery_action = str(recovery.get("action") or "")

    if recovery_action == "promote_extended_exact_reference_consensus":
        exact = recovery.get("exact_reference_consensus") or {}
        return _force_review(
            result,
            contract=contract,
            blocker=(
                "ordinary numeric exact-reference recovery is not sufficient automatic "
                "routing authority after measured held-out stale/incidental-reference failures"
            ),
            action="force_review_extended_numeric_reference_recovery",
            evidence={"exact_reference_consensus": exact},
        )

    if recovery_action == "promote_semantic_child_accounting_consensus":
        semantic = recovery.get("semantic_child_consensus") or {}
        return _force_review(
            result,
            contract=contract,
            blocker=(
                "semantic-child recovery requires an additional independent current-document "
                "or authoritative context discriminator before automatic routing"
            ),
            action="force_review_semantic_child_recovery_insufficient_authority",
            evidence={"semantic_child_consensus": semantic},
        )

    if route == "DO NOT PAY" and _is_credit_memo(document) and not _explicit_stop_pay(document):
        credit_routes = _same_vendor_credit_workflow_routes(document, support)
        if credit_routes:
            return _force_review(
                result,
                contract=contract,
                blocker=(
                    "generic credit memo cannot inherit automatic DO NOT PAY authority when "
                    "same-vendor Accounting history contains Vendor Credit Memo workflows"
                ),
                action="force_review_generic_credit_memo_dnp_conflict",
                evidence={
                    "same_vendor_credit_workflow_routes": credit_routes,
                    "explicit_stop_pay": False,
                },
            )

    result["coverage_recovery_safety"] = {"action": "allow_existing_decision", "blockers": []}
    return result


# Final drop-in name used by the held-out evaluator.
decide_ap_route_with_authority_guard = decide_ap_route_with_recovery_safety
