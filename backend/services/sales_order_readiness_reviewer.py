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

    # --- Obtain LLM provider ---
    try:
        provider = get_provider("classification")
    except LLMProviderError as e:
        return _error_result(str(e), reviewed_at, profile_id, profile_version)

    model_used = type(provider).__name__

    # --- Build prompts ---
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(extracted_order, customer_profile, validation_results, document_context)

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

def _build_system_prompt() -> str:
    return (
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
        "- 'suspicious' = significant deviations from history (unusual items, amounts, ship-to)\n"
        "- 'incomplete' = missing critical fields (customer, items, amounts)\n"
        "- Always explain your reasoning in summary\n"
        "- If no customer profile exists, note this as a warning (new customer)\n"
        "Do not include any text outside the JSON object."
    )


def _build_user_prompt(
    extracted_order: Dict[str, Any],
    customer_profile: Optional[Dict[str, Any]],
    validation_results: Optional[Dict[str, Any]],
    document_context: Optional[Dict[str, Any]],
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
        parts.append("\n=== CUSTOMER POSTING PROFILE ===")
        parts.append(f"customer_no: {customer_profile.get('customer_no')}")
        parts.append(f"customer_name: {customer_profile.get('customer_name')}")
        parts.append(f"invoices_analyzed: {customer_profile.get('invoices_analyzed')}")
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
    else:
        parts.append("\n=== CUSTOMER POSTING PROFILE ===")
        parts.append("No historical profile available (new or unknown customer)")

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
