"""GPI Document Hub — bounded AI AP routing decision service.

The model may interpret messy vendor/document patterns, but it may not invent a
SharePoint destination or bypass Business Central evidence. Every proposal is
validated against a versioned Accounting Temp routing contract and fails closed
when evidence is weak or contradictory.
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


def _contract_review_route(contract: Dict[str, Any]) -> str:
    """Return the Temp-relative review path.

    An empty string is intentional and means the AP Temp root. Do not replace
    it with a fabricated review folder.
    """
    if "review_route" in contract:
        return normalize_route_path(contract.get("review_route"))
    return ""


def _route_contract_prompt(contract: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "version": contract.get("version", "unknown"),
        "base_path": contract.get("base_path", ""),
        "static_routes": contract.get("static_routes", []),
        "dynamic_routes": contract.get("dynamic_routes", []),
        "review_route": _contract_review_route(contract),
    }


def _filename_reference_shape(value: Any) -> str:
    """Return a route-neutral structural signature for supervised matching.

    This never assigns a route. It only lets labeled examples teach whether a
    vendor's filenames tend to begin with a BC/reference token or with a
    vendor/descriptor token.
    """
    name = str(value or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", name).strip()
    if not stem:
        return "empty"
    if stem[0] in "_-":
        return "vendor_or_descriptor_leading"

    first = re.split(r"[_\s]+", stem, maxsplit=1)[0].strip("-")
    if re.fullmatch(r"W[A-Z]{0,2}\d{3,7}[A-Z]?", first, flags=re.IGNORECASE):
        return "w_prefixed_reference"
    if re.fullmatch(r"\d{4,7}[A-Z]?", first, flags=re.IGNORECASE):
        return "numeric_prefixed_reference"
    if re.fullmatch(r"[A-Z]{1,3}\d{3,7}[A-Z]?", first, flags=re.IGNORECASE):
        return "alpha_prefixed_reference"
    return "descriptor_leading"


def _context_value(context: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = context.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _supervised_route_support(
    document: Dict[str, Any],
    bc_context: Dict[str, Any],
    examples: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Summarize discriminating support from same-vendor Accounting labels.

    The summary is route-neutral evidence for the LLM plus a safety signal for
    the governor. It does not itself choose or override a route.
    """
    evidence = _document_evidence(document)
    vendor_key = normalize_vendor_name(evidence.get("vendor_name"))
    document_type = str(evidence.get("document_type") or "").lower()
    current_shape = _filename_reference_shape(evidence.get("file_name"))
    current_po = _context_value(
        bc_context,
        "po_number",
        "bc_document_no",
        "bc_order_number",
    ).upper()
    current_location = _context_value(
        bc_context,
        "location_code",
        "locationCode",
        "bc_location_code",
    ).upper()
    current_ship_to_name = _normalized_text(
        _context_value(bc_context, "ship_to_name", "shipToName")
    )
    current_ship_to_city = _normalized_text(
        _context_value(bc_context, "ship_to_city", "shipToCity")
    )
    current_ship_to_state = _normalized_text(
        _context_value(bc_context, "ship_to_state", "shipToState")
    )

    same_vendor_examples: List[Dict[str, Any]] = []
    if vendor_key:
        for example in examples:
            example_vendor = normalize_vendor_name(
                example.get("vendor_name")
                or example.get("vendor_canonical")
                or ((example.get("extracted_fields") or {}).get("vendor"))
            )
            if example_vendor == vendor_key:
                same_vendor_examples.append(example)

    route_rows: Dict[str, Dict[str, Any]] = {}
    for example in same_vendor_examples:
        route = normalize_route_path(example.get("route_path"))
        if not route:
            continue

        score = float(example.get("label_weight") or 0.0)
        signals: List[str] = []
        example_type = str(
            example.get("document_type") or example.get("suggested_job_type") or ""
        ).lower()
        if document_type and example_type and document_type == example_type:
            score += 1.5
            signals.append("document_type")

        example_shape = _filename_reference_shape(example.get("file_name"))
        if current_shape not in {"empty", "descriptor_leading"} and example_shape == current_shape:
            score += 4.0
            signals.append("filename_reference_shape")

        example_context = example.get("bc_context") or {}
        example_po = _context_value(
            example_context,
            "po_number",
            "bc_document_no",
            "bc_order_number",
        ).upper()
        if current_po and example_po and current_po == example_po:
            score += 6.0
            signals.append("exact_bc_reference")

        example_location = _context_value(
            example_context,
            "location_code",
            "locationCode",
            "bc_location_code",
        ).upper()
        if current_location and example_location and current_location == example_location:
            score += 5.0
            signals.append("location_code")

        example_ship_to_name = _normalized_text(
            _context_value(example_context, "ship_to_name", "shipToName")
        )
        if current_ship_to_name and example_ship_to_name and current_ship_to_name == example_ship_to_name:
            score += 2.0
            signals.append("ship_to_name")

        example_ship_to_city = _normalized_text(
            _context_value(example_context, "ship_to_city", "shipToCity")
        )
        if current_ship_to_city and example_ship_to_city and current_ship_to_city == example_ship_to_city:
            score += 1.0
            signals.append("ship_to_city")

        example_ship_to_state = _normalized_text(
            _context_value(example_context, "ship_to_state", "shipToState")
        )
        if current_ship_to_state and example_ship_to_state and current_ship_to_state == example_ship_to_state:
            score += 0.5
            signals.append("ship_to_state")

        row = route_rows.setdefault(
            route,
            {
                "route_path": route,
                "support_count": 0,
                "best_score": 0.0,
                "filename_shape_matches": 0,
                "exact_bc_reference_matches": 0,
                "location_matches": 0,
                "ship_to_matches": 0,
                "top_example_ids": [],
            },
        )
        row["support_count"] += 1
        row["best_score"] = max(float(row["best_score"]), round(score, 4))
        if "filename_reference_shape" in signals:
            row["filename_shape_matches"] += 1
        if "exact_bc_reference" in signals:
            row["exact_bc_reference_matches"] += 1
        if "location_code" in signals:
            row["location_matches"] += 1
        if any(signal.startswith("ship_to_") for signal in signals):
            row["ship_to_matches"] += 1
        example_id = (
            example.get("fingerprint")
            or example.get("document_id")
            or example.get("source_item_id")
        )
        if example_id and len(row["top_example_ids"]) < 3:
            row["top_example_ids"].append(str(example_id))

    ranked = sorted(
        route_rows.values(),
        key=lambda row: (float(row["best_score"]), int(row["support_count"])),
        reverse=True,
    )
    top = ranked[0] if ranked else None
    second = ranked[1] if len(ranked) > 1 else None
    margin = round(
        float(top["best_score"]) - float(second["best_score"]) if top and second else 0.0,
        4,
    )
    discriminating_matches = 0
    if top:
        discriminating_matches = (
            int(top["filename_shape_matches"])
            + int(top["exact_bc_reference_matches"])
            + int(top["location_matches"])
            + int(top["ship_to_matches"])
        )
    variable_vendor = len(route_rows) > 1
    strong = bool(variable_vendor and top and margin >= 2.0 and discriminating_matches > 0)

    return {
        "vendor_name": evidence.get("vendor_name") or "",
        "normalized_vendor": vendor_key,
        "same_vendor_example_count": len(same_vendor_examples),
        "variable_vendor": variable_vendor,
        "current_filename_reference_shape": current_shape,
        "current_bc_reference": current_po,
        "current_location_code": current_location,
        "top_route": top.get("route_path") if top else "",
        "top_score": top.get("best_score") if top else 0.0,
        "second_route": second.get("route_path") if second else "",
        "second_score": second.get("best_score") if second else 0.0,
        "margin": margin,
        "strong": strong,
        "routes": ranked[:8],
    }


def build_route_prompt(
    document: Dict[str, Any],
    bc_context: Dict[str, Any],
    examples: List[Dict[str, Any]],
    contract: Dict[str, Any],
    supervised_support: Optional[Dict[str, Any]] = None,
) -> str:
    support = supervised_support or _supervised_route_support(document, bc_context, examples)
    payload = {
        "document": _document_evidence(document),
        "bc_context": _compact(bc_context or {}),
        "similar_labeled_examples": [_example_for_prompt(e) for e in examples],
        "supervised_route_support": _compact(support),
        "routing_contract": _route_contract_prompt(contract),
    }
    return (
        "You are the GPI Accounts Payable routing intelligence model.\n\n"
        "Goal: reduce manual Accounting sorting while preserving the exact AP Temp Folder workflow.\n"
        "Accounting's labeled examples are supervised routing truth. The same vendor may legitimately route "
        "to different queues based on PO/order context, international status, warehouse/dropship context, "
        "document purpose, supporting pages, and recurring document/reference structure. "
        "NEVER infer a one-vendor/one-folder rule.\n\n"
        "Important semantics:\n"
        "- AP Temp folder names are GPI business-workflow labels, not ordinary-English logistics definitions.\n"
        "- A third-party consignee, carrier vendor, or freight invoice alone does NOT prove a Dropship route.\n"
        "- supervised_route_support is deterministic evidence summarized from SAME-VENDOR Accounting labels. "
        "When strong=true, top_route is the leading learned workflow unless explicit current BC facts directly "
        "contradict its discriminating evidence. If you depart from strong support, list the contradiction in unresolved.\n\n"
        "Rules:\n"
        "1. Classifying a carrier document as AP_Invoice does NOT determine its route.\n"
        "2. Verified Business Central/order facts outrank vendor identity and generic logistics semantics.\n"
        "3. Propose ONLY a route allowed by routing_contract.\n"
        "4. Do not invent folder names.\n"
        "5. If evidence conflicts or the route depends on missing BC context, list it in unresolved.\n"
        "6. Use labeled examples as patterns, not exact string-match rules.\n"
        "7. Treat filename/reference structure as supervised pattern evidence only when the labeled examples support it.\n"
        "8. Output concise auditable evidence.\n\n"
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
    data = raw if isinstance(raw, dict) else json.loads(_strip_json_fence(str(raw)))
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


def _verified_bc_refs(context: Dict[str, Any]) -> set[str]:
    values = context.get("verified_order_numbers") or context.get("order_numbers")
    if not values:
        values = [
            context.get("po_number"),
            context.get("bc_order_number"),
            context.get("bc_document_no"),
        ]
    if not isinstance(values, list):
        values = [values]
    return {str(v).strip().upper() for v in values if v}


def _dynamic_route_allowed(route: str, contract: Dict[str, Any], bc_context: Dict[str, Any]) -> bool:
    if not route:
        return False
    verified_refs = _verified_bc_refs(bc_context)
    for rule in contract.get("dynamic_routes") or []:
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
    supervised_support: Optional[Dict[str, Any]] = None,
) -> GovernedRouteDecision:
    context = bc_context or {}
    support = supervised_support or {}
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

    if support.get("variable_vendor"):
        top_route = normalize_route_path(support.get("top_route"))
        if support.get("strong"):
            if top_route and prediction.proposed_route != top_route:
                blockers.append(
                    "model route conflicts with strong same-vendor Accounting support: "
                    f"predicted {prediction.proposed_route}, supervised {top_route}"
                )
        else:
            blockers.append(
                "variable-vendor route lacks discriminating same-vendor supervised evidence"
            )

    if prediction.confidence < review_threshold:
        blockers.append(
            f"confidence {prediction.confidence:.1%} below review floor {review_threshold:.1%}"
        )
    elif prediction.confidence < threshold:
        warnings.append(
            f"confidence {prediction.confidence:.1%} below auto-route threshold {threshold:.1%}"
        )

    if blockers or warnings:
        return GovernedRouteDecision(
            decision=DECISION_NEEDS_REVIEW,
            route_path=_contract_review_route(contract),
            confidence=prediction.confidence,
            reason="; ".join(blockers + warnings),
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

    supervised_support = _supervised_route_support(document, context, examples)
    prompt = build_route_prompt(
        document,
        context,
        examples,
        contract,
        supervised_support=supervised_support,
    )
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
        supervised_support=supervised_support,
    )
    result = governed.to_dict()
    result["vendor_name"] = vendor_name
    result["normalized_vendor"] = normalize_vendor_name(vendor_name)
    result["few_shot_count"] = len(examples)
    result["few_shot_routes"] = sorted(
        {normalize_route_path(e.get("route_path")) for e in examples if e.get("route_path")}
    )
    result["supervised_route_support"] = supervised_support
    return result
