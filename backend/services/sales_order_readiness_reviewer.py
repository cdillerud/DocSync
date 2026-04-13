"""
GPI Document Hub — Sales Order Readiness Reviewer

LLM-assisted advisory layer that evaluates whether an extracted sales order
looks normal, suspicious, incomplete, or ready for posting/review — using
the customer's historical posting profile as context.

ADVISORY ONLY: Never changes posting decisions. Results are stored on the
document as `so_readiness_review` for human reviewers and audit trail.
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.llm_router import get_provider
from services.providers.base_provider import LLMProviderError

logger = logging.getLogger(__name__)

# Response schema the LLM must return
RESPONSE_SCHEMA = {
    "readiness_status": "ready | needs_review | suspicious | incomplete",
    "confidence": 0.0,
    "summary": "1-2 sentence plain English assessment",
    "blocking_issues": ["list of hard blockers preventing posting"],
    "warnings": ["list of soft warnings that merit human attention"],
    "unusual_patterns": ["list of deviations from customer history"],
    "profile_matches": ["list of fields that match historical pattern"],
    "recommended_next_step": "single actionable recommendation",
}


@dataclass
class ReadinessReviewResult:
    readiness_status: str  # ready | needs_review | suspicious | incomplete
    confidence: float
    summary: str
    blocking_issues: List[str]
    warnings: List[str]
    unusual_patterns: List[str]
    profile_matches: List[str]
    recommended_next_step: str
    model_used: str
    latency_ms: int
    schema_valid: bool
    retry_count: int
    customer_profile_id: Optional[str]
    customer_profile_version: Optional[str]
    reviewed_at: str
    profile_state: str = "unknown"  # none | weak | medium | strong
    ship_to_analysis: Optional[Dict[str, Any]] = None
    item_uom_analysis: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


async def review_sales_order_readiness(
    extracted_order: Dict[str, Any],
    customer_profile: Optional[Dict[str, Any]],
    validation_results: Optional[Dict[str, Any]] = None,
    document_context: Optional[Dict[str, Any]] = None,
) -> ReadinessReviewResult:
    """
    Evaluate a sales order against the customer's historical posting profile.

    Args:
        extracted_order: Extracted SO data (customer, items, amounts, PO, etc.)
        customer_profile: From customer_posting_profiles collection (may be None)
        validation_results: Existing deterministic validation results
        document_context: Additional context (doc_id, file_name, doc_type)

    Returns:
        ReadinessReviewResult — advisory only, never modifies the document.
    """
    reviewed_at = datetime.now(timezone.utc).isoformat()
    retry_count = 0

    profile_id = customer_profile.get("customer_no") if customer_profile else None
    profile_version = customer_profile.get("last_analyzed") if customer_profile else None
    profile_state = _classify_profile_state(customer_profile)

    # --- Ship-to pre-analysis ---
    from services.ship_to_analysis_service import analyze_ship_to
    ship_to_raw = extracted_order.get("ship_to_name") or ""
    ship_to_result = analyze_ship_to(
        ship_to_raw, customer_profile, profile_state,
        other_signals_normal=True,  # refined below after amount check
    )
    # Refine: check if amount/items also look off
    if customer_profile and customer_profile.get("status") == "analyzed":
        total = float(extracted_order.get("total_amount") or 0)
        amt_range = customer_profile.get("amount_range", {})
        amt_ok = (amt_range.get("min", 0) <= total <= amt_range.get("max", float("inf"))) if total > 0 else True
        items = [li.get("item_number") or li.get("description", "") for li in (extracted_order.get("line_items") or [])]
        known_items = set(customer_profile.get("common_items", []))
        items_ok = not items or any(i in known_items for i in items)
        if not amt_ok or not items_ok:
            ship_to_result = analyze_ship_to(ship_to_raw, customer_profile, profile_state, other_signals_normal=False)

    doc_id = (document_context or {}).get("doc_id", "unknown")
    logger.info(
        "[SO-Readiness] ship_to: doc=%s profile=%s raw='%s' norm='%s' match=%s severity=%s",
        doc_id[:8], profile_state, ship_to_raw[:40], ship_to_result.normalized[:40],
        ship_to_result.match_type, ship_to_result.severity,
    )

    # --- Item/UOM pre-analysis ---
    from services.item_uom_analysis_service import analyze_items_uom
    line_items = extracted_order.get("line_items") or []
    # Determine if amount is within range for context
    amt_normal = True
    if customer_profile and customer_profile.get("amount_range"):
        total = float(extracted_order.get("total_amount") or 0)
        ar = customer_profile["amount_range"]
        if total > 0:
            amt_normal = ar.get("min", 0) <= total <= ar.get("max", float("inf"))

    item_uom_result = analyze_items_uom(
        line_items, customer_profile, profile_state,
        other_signals_normal=amt_normal and ship_to_result.severity in ("none", "low"),
    )
    logger.info(
        "[SO-Readiness] items: doc=%s profile=%s lines=%d exact=%d unknown=%d severity=%s",
        doc_id[:8], profile_state, item_uom_result.total_lines,
        item_uom_result.lines_exact, item_uom_result.lines_unknown,
        item_uom_result.overall_severity,
    )

    # --- Obtain LLM provider ---
    try:
        provider = get_provider("classification")
    except LLMProviderError as e:
        return _error_result(str(e), reviewed_at, profile_id, profile_version)

    model_used = type(provider).__name__

    # --- Build prompts ---
    system_prompt = _build_system_prompt(profile_state)
    user_prompt = _build_user_prompt(extracted_order, customer_profile, validation_results, document_context, profile_state, ship_to_result, item_uom_result)

    # --- Call LLM with retry ---
    raw = ""
    t0 = time.monotonic()
    max_retries = 2

    for attempt in range(max_retries + 1):
        retry_count = attempt
        try:
            session_id = f"so_readiness_{document_context.get('doc_id', 'unknown')[:20]}" if document_context else "so_readiness"
            raw = await provider.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                session_id=session_id,
                expect_json=True,
            )
            break
        except LLMProviderError as e:
            if attempt < max_retries:
                logger.warning("[SO-Readiness] Retry %d for LLM call: %s", attempt + 1, e)
                continue
            latency_ms = round((time.monotonic() - t0) * 1000)
            return _error_result(
                str(e), reviewed_at, profile_id, profile_version,
                model_used=model_used, latency_ms=latency_ms, retry_count=retry_count,
            )

    latency_ms = round((time.monotonic() - t0) * 1000)

    # --- Parse response ---
    try:
        data = _parse_json_response(raw)
        schema_valid = _validate_schema(data)

        result = ReadinessReviewResult(
            readiness_status=data.get("readiness_status", "needs_review"),
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
            summary=data.get("summary", ""),
            blocking_issues=data.get("blocking_issues", []),
            warnings=data.get("warnings", []),
            unusual_patterns=data.get("unusual_patterns", []),
            profile_matches=data.get("profile_matches", []),
            recommended_next_step=data.get("recommended_next_step", ""),
            model_used=model_used,
            latency_ms=latency_ms,
            schema_valid=schema_valid,
            retry_count=retry_count,
            customer_profile_id=profile_id,
            customer_profile_version=profile_version,
            reviewed_at=reviewed_at,
            profile_state=profile_state,
            ship_to_analysis=ship_to_result.to_dict(),
            item_uom_analysis=item_uom_result.to_dict(),
        )

        logger.info(
            "[SO-Readiness] status=%s confidence=%.2f model=%s latency=%dms schema_valid=%s retries=%d customer=%s",
            result.readiness_status, result.confidence, model_used,
            latency_ms, schema_valid, retry_count, profile_id or "no_profile",
        )
        return result

    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("[SO-Readiness] Failed to parse response: %s — raw: %s", e, raw[:300])
        return ReadinessReviewResult(
            readiness_status="needs_review",
            confidence=0.0,
            summary="",
            blocking_issues=[],
            warnings=[],
            unusual_patterns=[],
            profile_matches=[],
            recommended_next_step="",
            model_used=model_used,
            latency_ms=latency_ms,
            schema_valid=False,
            retry_count=retry_count,
            customer_profile_id=profile_id,
            customer_profile_version=profile_version,
            reviewed_at=reviewed_at,
            error="Failed to parse model response",
        )


# =============================================================================
# Prompt construction
# =============================================================================

def _build_system_prompt(profile_state: str) -> str:
    base = (
        "You are a sales order readiness reviewer for a document processing hub. "
        "Given a sales order's extracted data and the customer's historical posting profile, "
        "evaluate whether the order looks ready for posting, needs human review, "
        "appears suspicious, or is incomplete.\n\n"
        "Respond ONLY with a JSON object matching this exact schema:\n"
        "{\n"
        '  "readiness_status": "ready | needs_review | suspicious | incomplete",\n'
        '  "confidence": 0.0 to 1.0,\n'
        '  "summary": "1-2 sentence plain English assessment",\n'
        '  "blocking_issues": ["hard blockers preventing posting"],\n'
        '  "warnings": ["soft warnings for human attention"],\n'
        '  "unusual_patterns": ["deviations from customer history"],\n'
        '  "profile_matches": ["fields consistent with history"],\n'
        '  "recommended_next_step": "single actionable recommendation"\n'
        "}\n\n"
        "Rules:\n"
        "- 'ready' = all fields present, matches customer history, no red flags\n"
        "- 'needs_review' = mostly OK but has warnings or minor gaps\n"
        "- 'suspicious' = significant deviations from a STRONG known pattern\n"
        "- 'incomplete' = missing critical fields (customer, items, amounts)\n"
        "- Always explain your reasoning in summary\n"
    )

    if profile_state == "none":
        base += (
            "\nIMPORTANT — NO CUSTOMER PROFILE EXISTS:\n"
            "- There is no historical data for this customer. You CANNOT determine what is 'normal' for them.\n"
            "- Do NOT mark items, amounts, ship-to, or UOM as 'unusual' — you have no baseline to compare against.\n"
            "- Treat this as a 'limited comparison basis' situation, not an anomaly.\n"
            "- Use 'needs_review' if the order data looks structurally complete but you have no history.\n"
            "- Only use 'suspicious' if the extracted data itself is internally inconsistent (e.g., zero amounts, contradictory fields).\n"
            "- Keep confidence below 0.60 — you are working without historical context.\n"
            "- In warnings, state 'No customer history available — manual verification recommended' rather than listing speculative anomalies.\n"
        )
    elif profile_state == "weak":
        base += (
            "\nIMPORTANT — WEAK CUSTOMER PROFILE (few historical orders):\n"
            "- The profile has very limited data. Patterns may not be statistically reliable.\n"
            "- Phrase deviations as 'differs from limited sample' rather than 'unusual' or 'anomalous.'\n"
            "- Do NOT treat deviations from a small sample as strong evidence of risk.\n"
            "- Keep confidence below 0.70 — the comparison basis is thin.\n"
            "- Prefer 'needs_review' over 'suspicious' unless the order has actual blocking issues.\n"
        )
    elif profile_state == "medium":
        base += (
            "\nCUSTOMER PROFILE: MODERATE HISTORY.\n"
            "- The profile has a reasonable number of orders. Patterns are indicative but not definitive.\n"
            "- Flag deviations as 'worth verifying' rather than 'anomalous.'\n"
        )
    # strong: no special instruction — default behavior is appropriate

    base += "Do not include any text outside the JSON object."
    return base


def _build_user_prompt(
    extracted_order: Dict[str, Any],
    customer_profile: Optional[Dict[str, Any]],
    validation_results: Optional[Dict[str, Any]],
    document_context: Optional[Dict[str, Any]],
    profile_state: str = "unknown",
    ship_to_analysis=None,
    item_uom_analysis=None,
) -> str:
    parts = []

    # Extracted order data
    parts.append("=== EXTRACTED SALES ORDER ===")
    for key in ("customer_name", "customer_number", "order_number", "po_number",
                "order_date", "requested_delivery_date", "ship_to_name",
                "total_amount", "currency", "line_items"):
        val = extracted_order.get(key)
        if val is not None:
            if key == "line_items" and isinstance(val, list):
                parts.append(f"line_items ({len(val)} lines):")
                for i, li in enumerate(val[:10]):
                    item = li.get("item_number") or li.get("description") or "?"
                    qty = li.get("quantity", "?")
                    uom = li.get("uom") or li.get("unit_of_measure", "?")
                    amt = li.get("unit_price") or li.get("amount", "?")
                    parts.append(f"  {i+1}. {item} qty={qty} uom={uom} price={amt}")
            else:
                parts.append(f"{key}: {val}")

    # Customer profile
    if customer_profile and customer_profile.get("status") == "analyzed":
        analyzed = customer_profile.get("invoices_analyzed", 0)
        parts.append(f"\n=== CUSTOMER POSTING PROFILE (state: {profile_state}, {analyzed} orders analyzed) ===")
        parts.append(f"customer_no: {customer_profile.get('customer_no')}")
        parts.append(f"customer_name: {customer_profile.get('customer_name')}")
        parts.append(f"invoices_analyzed: {analyzed}")
        parts.append(f"template_confidence: {customer_profile.get('template_confidence')}")
        parts.append(f"common_items: {customer_profile.get('common_items', [])}")
        parts.append(f"common_uoms: {customer_profile.get('common_uoms', [])}")
        parts.append(f"po_number_pattern: {customer_profile.get('po_number_pattern')}")
        parts.append(f"typical_order_value: ${customer_profile.get('typical_order_value', 0):.2f}")
        amt_range = customer_profile.get("amount_range", {})
        parts.append(f"amount_range: ${amt_range.get('min', 0):.2f} — ${amt_range.get('max', 0):.2f}")
        parts.append(f"typical_ship_to: {customer_profile.get('typical_ship_to')}")
        parts.append(f"typical_line_count: {customer_profile.get('typical_line_count')}")
        parts.append(f"days_to_ship_p50: {customer_profile.get('days_to_ship_p50')}")
        if profile_state == "weak":
            parts.append("NOTE: This profile is based on very few orders — treat patterns as tentative, not definitive.")
    else:
        parts.append("\n=== CUSTOMER POSTING PROFILE (state: none) ===")
        parts.append("No historical profile available. This is a new or unknown customer.")
        parts.append("You have no basis to judge what is 'normal' for this customer.")

    # Existing validation
    if validation_results:
        parts.append("\n=== EXISTING VALIDATION ===")
        for key in ("customer_matched", "po_validated", "amount_validated",
                     "duplicate_check", "overall_status"):
            val = validation_results.get(key)
            if val is not None:
                parts.append(f"{key}: {val}")
        checks = validation_results.get("checks", [])
        for c in checks[:5]:
            parts.append(f"  check: {c.get('check_name')} = {'PASS' if c.get('passed') else 'FAIL'}")

    # Ship-to pre-analysis
    if ship_to_analysis:
        parts.append("\n=== SHIP-TO ANALYSIS (pre-computed) ===")
        parts.append(f"match_type: {ship_to_analysis.match_type}")
        parts.append(f"severity: {ship_to_analysis.severity}")
        parts.append(f"context: {ship_to_analysis.context_notes}")
        if ship_to_analysis.match_type in ("exact", "normalized_match"):
            parts.append("INSTRUCTION: The ship-to matches a known customer location. Do NOT flag it as unusual.")
        elif ship_to_analysis.match_type == "known_alternate":
            parts.append("INSTRUCTION: The ship-to is in the same area as known locations. Mention it only as a minor note, not as an anomaly.")
        elif ship_to_analysis.severity == "none":
            parts.append("INSTRUCTION: Ship-to cannot be compared (no history). Do NOT treat it as unusual.")

    # Item/UOM pre-analysis
    if item_uom_analysis:
        parts.append("\n=== ITEM/UOM ANALYSIS (pre-computed) ===")
        parts.append(f"overall_severity: {item_uom_analysis.overall_severity}")
        parts.append(f"context: {item_uom_analysis.context_notes}")
        parts.append(f"lines: {item_uom_analysis.total_lines} total, {item_uom_analysis.lines_exact} exact match, {item_uom_analysis.lines_unknown} unknown")
        if item_uom_analysis.overall_severity == "none":
            parts.append("INSTRUCTION: Item/UOM analysis shows no concerns. Do NOT flag items or UOMs as unusual.")
        elif item_uom_analysis.overall_severity == "low":
            parts.append("INSTRUCTION: Minor item/UOM variations detected. Mention as a note, not as a significant anomaly.")
        # Let medium/high speak for themselves

    return "\n".join(parts)


# =============================================================================
# Parsing & validation
# =============================================================================

def _parse_json_response(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        body = [line for idx, line in enumerate(lines) if not lines[idx].startswith("```")]
        text = "\n".join(body).strip()
    if text.startswith("{"):
        return json.loads(text)
    if "{" in text:
        return json.loads(text[text.find("{"):text.rfind("}") + 1])
    raise ValueError(f"No JSON found in response: {text[:200]}")


def _validate_schema(data: Dict[str, Any]) -> bool:
    required = {"readiness_status", "confidence", "summary", "recommended_next_step"}
    if not required.issubset(data.keys()):
        return False
    if data["readiness_status"] not in ("ready", "needs_review", "suspicious", "incomplete"):
        return False
    try:
        float(data["confidence"])
    except (ValueError, TypeError):
        return False
    return True


def _classify_profile_state(profile: Optional[Dict[str, Any]]) -> str:
    """Classify customer profile into none/weak/medium/strong."""
    if not profile or profile.get("status") != "analyzed":
        return "none"
    analyzed = profile.get("invoices_analyzed", 0)
    conf = profile.get("template_confidence", "low")
    if conf == "high" and analyzed >= 20:
        return "strong"
    if conf == "medium" or analyzed >= 5:
        return "medium"
    return "weak"


def _error_result(
    error: str, reviewed_at: str,
    profile_id: Optional[str], profile_version: Optional[str],
    model_used: str = "none", latency_ms: int = 0, retry_count: int = 0,
) -> ReadinessReviewResult:
    return ReadinessReviewResult(
        readiness_status="needs_review",
        confidence=0.0,
        summary="",
        blocking_issues=[],
        warnings=[],
        unusual_patterns=[],
        profile_matches=[],
        recommended_next_step="",
        model_used=model_used,
        latency_ms=latency_ms,
        schema_valid=False,
        retry_count=retry_count,
        customer_profile_id=profile_id,
        customer_profile_version=profile_version,
        reviewed_at=reviewed_at,
        error=error,
    )
