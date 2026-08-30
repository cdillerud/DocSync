"""GPI Document Hub — bounded AI AP routing decision service.

The model is allowed to interpret messy vendor/document patterns, but it is not
allowed to invent a SharePoint destination or bypass Business Central evidence.
The safety governor validates every model proposal against a versioned routing
contract and fails closed when evidence is weak or contradictory.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from services.ap_routing_learning_service import (
    normalize_route_path,
    normalize_vendor_name,
    select_few_shot_examples,
)

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
DEFAULT_MODEL = os.environ.get("AP_ROUTING_MODEL", "gemini-2.5-pro")
DEFAULT_AUTO_ROUTE_THRESHOLD = float(os.environ.get("AP_ROUTING_AUTO_THRESHOLD", "0.92"))
DEFAULT_REVIEW_THRESHOLD = float(os.environ.get("AP_ROUTING_REVIEW_THRESHOLD", "0.70"))

DECISION_AUTO_ROUTE = "auto_route"
DECISION_NEEDS_REVIEW = "needs_review"
DECISION_EXCEPTION = "exception"


@dataclass
class RoutePrediction:
    proposed_route: str
    confidence: float
    evidence: List[str]
    reasoning_summary: str
    bc_refs_used: List[str]
    unresolved: List[str]
    matched_example_ids: List[str]
    model: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GovernedRouteDecision:
    decision: str
    route_path: str
    confidence: float
    reason: str
    blockers: List[str]
    warnings: List[str]
    prediction: Dict[str, Any]
    contract_version: str
    auto_route_threshold: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _compact(value: Any, max_len: int = 4000) -> Any:
    if isinstance(value, str):
        return value[:max_len]
    if isinstance(value, list):
        return [_compact(v, max_len=max_len) for v in value[:20]]
    if isinstance(value, dict):
        return {str(k): _compact(v, max_len=max_len) for k, v in list(value.items())[:80]}
    return value


def _document_evidence(document: Dict[str, Any]) -> Dict[str, Any]:
    extracted = document.get("extracted_fields") or document.get("ai_extraction") or {}
    normalized = document.get("normalized_fields") or {}
    return {
        "file_name": document.get("file_name") or document.get("name") or "",
        "document_type": document.get("document_type") or document.get("suggested_job_type") or "",
        "classification_confidence": document.get("confidence") or document.get("classification_confidence"),
        "vendor_name": (
            document.get("vendor_canonical")
            or document.get("vendor_raw")
            or extracted.get("vendor")
            or extracted.get("vendor_name")
            or ""
        ),
        "extracted_fields": _compact(extracted),
        "normalized_fields": _compact(normalized),
        "po_number_extracted": document.get("po_number_extracted"),
        "bol_number_extracted": document.get("bol_number_extracted"),
        "shipment_number": document.get("shipment_number"),
        "freight_direction": document.get("freight_direction"),
        "is_international": document.get("is_international"),
        "raw_text_excerpt": str(document.get("raw_text") or document.get("document_text") or "")[:8000],
        "email_subject": str(document.get("email_subject") or "")[:1000],
    }


def _example_for_prompt(example: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "example_id": example.get("fingerprint") or example.get("document_id") or example.get("source_item_id"),
        "vendor_name": example.get("vendor_name"),
        "document_type": example.get("document_type") or example.get("suggested_job_type"),
        "route_path": normalize_route_path(example.get("route_path")),
        "bc_context": _compact(example.get("bc_context") or {}),
        "key_evidence": _compact(example.get("key_evidence") or example.get("extracted_fields") or {}),
        "file_name": example.get("file_name"),
        "label_source": example.get("label_source"),
        "reviewer_corrected": bool(example.get("reviewer_corrected")),
    }


def _route_contract_prompt(contract: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "version": contract.get("version", "unknown"),
        "base_path": contract.get("base_path", ""),
        "static_routes": contract.get("static_routes", []),
        "dynamic_routes": contract.get("dynamic_routes", []),
        "review_route": contract.get("review_route", "_NeedsReview"),
    }


def build_route_prompt(
    document: Dict[str, Any],
    bc_context: Dict[str, Any],
    examples: List[Dict[str, Any]],
    contract: Dict[str, Any],
) -> str:
    payload = {
        "document": _document_evidence(document),
        "bc_context": _compact(bc_context or {}),
        "similar_labeled_examples": [_example_for_prompt(e) for e in examples],
        "routing_contract": _route_contract_prompt(contract),
    }
    return (
        "You are the GPI Accounts Payable routing intelligence model.\n\n"
        "Goal: reduce manual Accounting sorting while preserving the exact AP Temp Folder workflow.\n"
        "Accounting's labeled examples are supervised routing truth. The same vendor may legitimately route "
        "to different queues based on PO/order context, international status, warehouse/dropship context, "
        "document purpose, and supporting pages. NEVER infer a one-vendor/one-folder rule.\n\n"
        "Important rules:\n"
        "1. Classifying a carrier document as AP_Invoice does NOT determine its route.\n"
        "2. Business Central/order context outranks vendor identity when they conflict.\n"
        "3. You may propose ONLY a route allowed by routing_contract.\n"
        "4. Do not invent folder names.\n"
        "5. If evidence conflicts or the correct route depends on missing BC context, return unresolved items.\n"
        "6. Use the labeled examples as patterns, not as exact string-match rules.\n"
        "7. Output concise evidence that can be audited by an operator.\n\n"
        "Return JSON ONLY with exactly this shape:\n"
        "{\n"
        '  "proposed_route": "Temp-relative path",\n'
        '  "confidence": 0.0,\n'
        '  "evidence": ["fact 1", "fact 2"],\n'
        '  "reasoning_summary": "one short sentence",\n'
        '  "bc_refs_used": ["PO/order/reference"],\n'
        '  "unresolved": ["missing or contradictory fact"],\n'
        '  "matched_example_ids": ["example id"]\n'
        "}\n\n"
        "INPUT:\n" + json.dumps(payload, ensure_ascii=False, default=str)
    )


def _strip_json_fence(text: str) -> str:
    value = str(text or "").strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    body: List[str] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```json") or (stripped == "```" and not inside):
            inside = True
            continue
        if stripped == "```" and inside:
            break
        if inside:
            body.append(line)
    return "\n".join(body).strip()


def parse_route_prediction(raw: Any, model: str = DEFAULT_MODEL) -> RoutePrediction:
    if isinstance(raw, dict):
        data = raw
    else:
        data = json.loads(_strip_json_fence(str(raw)))

    proposed_route = normalize_route_path(data.get("proposed_route"))
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return RoutePrediction(
        proposed_route=proposed_route,
        confidence=confidence,
        evidence=[str(x)[:500] for x in (data.get("evidence") or [])[:12]],
        reasoning_summary=str(data.get("reasoning_summary") or "")[:1000],
        bc_refs_used=[str(x)[:200] for x in (data.get("bc_refs_used") or [])[:12]],
        unresolved=[str(x)[:500] for x in (data.get("unresolved") or [])[:12]],
        matched_example_ids=[str(x)[:200] for x in (data.get("matched_example_ids") or [])[:12]],
        model=model,
    )


async def _default_llm_send(prompt: str, model: str) -> str:
    if not EMERGENT_LLM_KEY:
        raise RuntimeError("EMERGENT_LLM_KEY is not configured")
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"ap-route-{uuid.uuid4()}",
        system_message=(
            "You make bounded Accounts Payable routing predictions from supplied evidence. "
            "Return valid JSON only. Never invent routes outside the supplied contract."
        ),
    ).with_model("gemini", model)
    return await chat.send_message(UserMessage(text=prompt))


def _normalized_static_routes(contract: Dict[str, Any]) -> set[str]:
    return {
        normalize_route_path(route)
        for route in (contract.get("static_routes") or [])
        if normalize_route_path(route)
    }


def _dynamic_route_allowed(route: str, contract: Dict[str, Any], bc_context: Dict[str, Any]) -> bool:
    """Allow dynamic order folders only when BC evidence proves the dynamic leaf."""
    if not route:
        return False
    dynamic_rules = contract.get("dynamic_routes") or []
    verified_refs = {
        str(v).strip().upper()
        for v in (
            bc_context.get("verified_order_numbers")
            or bc_context.get("order_numbers")
            or [
                bc_context.get("po_number"),
                bc_context.get("bc_order_number"),
                bc_context.get("bc_document_no"),
            ]
        )
        if v
    }
    for rule in dynamic_rules:
        prefix = normalize_route_path(rule.get("prefix"))
        if not prefix or not route.startswith(prefix + "/"):
            continue
        leaf = route[len(prefix) + 1 :].strip().upper()
        if not leaf:
            continue
        if rule.get("requires_verified_bc_reference", True) and leaf not in verified_refs:
            continue
        pattern = rule.get("leaf_pattern")
        if pattern and not re.fullmatch(pattern, leaf, flags=re.IGNORECASE):
            continue
        return True
    return False


def route_is_allowed(route: str, contract: Dict[str, Any], bc_context: Optional[Dict[str, Any]] = None) -> bool:
    normalized = normalize_route_path(route)
    if normalized in _normalized_static_routes(contract):
        return True
    return _dynamic_route_allowed(normalized, contract, bc_context or {})


def _route_requires_bc_context(route: str, contract: Dict[str, Any]) -> bool:
    normalized = normalize_route_path(route)
    for prefix in contract.get("bc_context_required_prefixes") or []:
        p = normalize_route_path(prefix)
        if normalized == p or normalized.startswith(p + "/"):
            return True
    return False


def _bc_context_is_resolved(context: Dict[str, Any]) -> bool:
    status = str(context.get("status") or context.get("resolution_status") or "").lower()
    if status in {"resolved", "resolved_shipment", "matched", "verified"}:
        return True
    return bool(
        context.get("bc_record_id")
        or context.get("po_number")
        or context.get("verified_order_numbers")
        or context.get("location_code")
        or context.get("locationCode")
    )


def govern_route_prediction(
    prediction: RoutePrediction,
    *,
    contract: Dict[str, Any],
    bc_context: Optional[Dict[str, Any]] = None,
    vendor_auto_threshold: Optional[float] = None,
) -> GovernedRouteDecision:
    context = bc_context or {}
    threshold = float(vendor_auto_threshold or contract.get("auto_route_threshold") or DEFAULT_AUTO_ROUTE_THRESHOLD)
    review_threshold = float(contract.get("review_threshold") or DEFAULT_REVIEW_THRESHOLD)
    blockers: List[str] = []
    warnings: List[str] = []

    if not prediction.proposed_route:
        blockers.append("model returned no route")
    elif not route_is_allowed(prediction.proposed_route, contract, context):
        blockers.append(f"route is not allowed by contract: {prediction.proposed_route}")

    if prediction.unresolved:
        blockers.append("model reported unresolved evidence: " + "; ".join(prediction.unresolved[:3]))

    if _route_requires_bc_context(prediction.proposed_route, contract) and not _bc_context_is_resolved(context):
        blockers.append("route requires resolved Business Central/order context")

    if prediction.confidence < review_threshold:
        blockers.append(
            f"confidence {prediction.confidence:.1%} below review floor {review_threshold:.1%}"
        )
    elif prediction.confidence < threshold:
        warnings.append(
            f"confidence {prediction.confidence:.1%} below auto-route threshold {threshold:.1%}"
        )

    review_route = normalize_route_path(contract.get("review_route") or "_NeedsReview")
    if blockers or warnings:
        reason_parts = blockers + warnings
        return GovernedRouteDecision(
            decision=DECISION_NEEDS_REVIEW,
            route_path=review_route,
            confidence=prediction.confidence,
            reason="; ".join(reason_parts),
            blockers=blockers,
            warnings=warnings,
            prediction=prediction.to_dict(),
            contract_version=str(contract.get("version") or "unknown"),
            auto_route_threshold=threshold,
        )

    return GovernedRouteDecision(
        decision=DECISION_AUTO_ROUTE,
        route_path=prediction.proposed_route,
        confidence=prediction.confidence,
        reason=prediction.reasoning_summary or "bounded AI route prediction passed safety governor",
        blockers=[],
        warnings=[],
        prediction=prediction.to_dict(),
        contract_version=str(contract.get("version") or "unknown"),
        auto_route_threshold=threshold,
    )


async def decide_ap_route(
    db,
    *,
    document: Dict[str, Any],
    bc_context: Optional[Dict[str, Any]],
    contract: Dict[str, Any],
    examples: Optional[List[Dict[str, Any]]] = None,
    vendor_auto_threshold: Optional[float] = None,
    model: str = DEFAULT_MODEL,
    llm_send: Optional[Callable[[str, str], Awaitable[Any]]] = None,
) -> Dict[str, Any]:
    """Retrieve supervised examples, ask the model, then fail closed through governor."""
    evidence = _document_evidence(document)
    vendor_name = evidence.get("vendor_name") or ""
    document_type = evidence.get("document_type") or ""
    context = bc_context or {}

    if examples is None:
        examples = await select_few_shot_examples(
            db,
            vendor_name=vendor_name,
            document_type=document_type,
            bc_context=context,
            limit=int(contract.get("few_shot_limit") or 8),
        )

    prompt = build_route_prompt(document, context, examples, contract)
    sender = llm_send or _default_llm_send
    try:
        raw = await sender(prompt, model)
        prediction = parse_route_prediction(raw, model=model)
    except Exception as exc:
        logger.exception("AP routing model call failed")
        prediction = RoutePrediction(
            proposed_route="",
            confidence=0.0,
            evidence=[],
            reasoning_summary="routing model failure",
            bc_refs_used=[],
            unresolved=[f"model_error:{type(exc).__name__}"],
            matched_example_ids=[],
            model=model,
        )

    governed = govern_route_prediction(
        prediction,
        contract=contract,
        bc_context=context,
        vendor_auto_threshold=vendor_auto_threshold,
    )
    result = governed.to_dict()
    result["vendor_name"] = vendor_name
    result["normalized_vendor"] = normalize_vendor_name(vendor_name)
    result["few_shot_count"] = len(examples)
    result["few_shot_routes"] = sorted(
        {normalize_route_path(e.get("route_path")) for e in examples if e.get("route_path")}
    )
    return result
