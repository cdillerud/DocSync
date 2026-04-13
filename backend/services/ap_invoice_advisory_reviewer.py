"""
GPI Document Hub — AP Invoice Vendor Advisory Reviewer

Reuses the generic advisory framework pattern from Sales Order
with AP-vendor-specific prompts, profile schema, and field semantics.

ADVISORY ONLY: Never changes posting decisions or routing.
"""

import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.llm_router import get_provider
from services.providers.base_provider import LLMProviderError

logger = logging.getLogger(__name__)


@dataclass
class APAdvisoryResult:
    readiness_status: str      # ready | needs_review | suspicious | incomplete
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
    vendor_profile_id: Optional[str]
    profile_state: str = "unknown"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def classify_vendor_profile_state(profile: Optional[Dict]) -> str:
    if not profile:
        return "none"
    analyzed = profile.get("bc_invoice_count", profile.get("invoices_analyzed", 0))
    conf = profile.get("posting_confidence", profile.get("template_confidence", "low"))
    if conf == "high" and analyzed >= 20:
        return "strong"
    if conf == "medium" or analyzed >= 5:
        return "medium"
    if analyzed >= 1:
        return "weak"
    return "none"


async def review_ap_invoice_readiness(
    extracted_invoice: Dict[str, Any],
    vendor_profile: Optional[Dict[str, Any]],
    validation_results: Optional[Dict[str, Any]] = None,
    document_context: Optional[Dict[str, Any]] = None,
) -> APAdvisoryResult:
    """Evaluate an AP invoice against the vendor's posting profile."""
    retry_count = 0
    profile_state = classify_vendor_profile_state(vendor_profile)
    vendor_id = vendor_profile.get("vendor_no") if vendor_profile else None

    try:
        provider = get_provider("classification")
    except LLMProviderError as e:
        return _error_result(str(e), vendor_id, profile_state)

    model_used = type(provider).__name__
    system_prompt = _build_system_prompt(profile_state)
    user_prompt = _build_user_prompt(extracted_invoice, vendor_profile, validation_results, document_context, profile_state)

    raw = ""
    t0 = time.monotonic()
    for attempt in range(3):
        retry_count = attempt
        try:
            session_id = f"ap_advisory_{(document_context or {}).get('doc_id', 'x')[:16]}"
            raw = await provider.complete(
                system_prompt=system_prompt, user_prompt=user_prompt,
                session_id=session_id, expect_json=True,
            )
            break
        except LLMProviderError as e:
            if attempt < 2:
                continue
            return _error_result(str(e), vendor_id, profile_state,
                                 model_used=model_used, latency_ms=round((time.monotonic() - t0) * 1000))

    latency_ms = round((time.monotonic() - t0) * 1000)

    try:
        data = _parse_json(raw)
        schema_valid = "readiness_status" in data and "confidence" in data

        result = APAdvisoryResult(
            readiness_status=data.get("readiness_status", "needs_review"),
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
            summary=data.get("summary", ""),
            blocking_issues=data.get("blocking_issues", []),
            warnings=data.get("warnings", []),
            unusual_patterns=data.get("unusual_patterns", []),
            profile_matches=data.get("profile_matches", []),
            recommended_next_step=data.get("recommended_next_step", ""),
            model_used=model_used, latency_ms=latency_ms,
            schema_valid=schema_valid, retry_count=retry_count,
            vendor_profile_id=vendor_id, profile_state=profile_state,
        )

        logger.info(
            "[AP-Advisory] status=%s conf=%.2f model=%s latency=%dms profile=%s vendor=%s",
            result.readiness_status, result.confidence, model_used,
            latency_ms, profile_state, vendor_id or "none",
        )
        return result

    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("[AP-Advisory] Parse failed: %s — raw: %s", e, raw[:200])
        return _error_result("Failed to parse model response", vendor_id, profile_state,
                             model_used=model_used, latency_ms=latency_ms)


# =============================================================================
# Prompts
# =============================================================================

def _build_system_prompt(profile_state: str) -> str:
    base = (
        "You are an AP invoice readiness reviewer for a document processing hub. "
        "Given an invoice's extracted data and the vendor's historical posting profile, "
        "evaluate whether the invoice looks ready for posting, needs review, "
        "appears suspicious, or is incomplete.\n\n"
        "Respond ONLY with a JSON object:\n"
        "{\n"
        '  "readiness_status": "ready | needs_review | suspicious | incomplete",\n'
        '  "confidence": 0.0 to 1.0,\n'
        '  "summary": "1-2 sentence assessment",\n'
        '  "blocking_issues": ["hard blockers"],\n'
        '  "warnings": ["soft warnings"],\n'
        '  "unusual_patterns": ["deviations from vendor history"],\n'
        '  "profile_matches": ["fields matching history"],\n'
        '  "recommended_next_step": "single recommendation"\n'
        "}\n\n"
        "Rules:\n"
        "- 'ready' = all fields present, matches vendor history\n"
        "- 'needs_review' = mostly OK but has warnings\n"
        "- 'suspicious' = significant deviations from STRONG known pattern\n"
        "- 'incomplete' = missing critical fields (vendor, amount, invoice number)\n"
    )

    if profile_state == "none":
        base += (
            "\nNO VENDOR PROFILE:\n"
            "- No history. Cannot judge normalcy.\n"
            "- Use 'needs_review' if structurally complete. Keep confidence ≤0.60.\n"
            "- Do NOT flag amounts/items as unusual without a baseline.\n"
        )
    elif profile_state == "weak":
        base += (
            "\nWEAK VENDOR PROFILE (few invoices):\n"
            "- Limited data. Phrase deviations as 'differs from limited sample.'\n"
            "- Keep confidence ≤0.70. Prefer 'needs_review' over 'suspicious.'\n"
        )
    elif profile_state == "strong":
        base += (
            "\nSTRONG VENDOR PROFILE:\n"
            "- Mature vendors evolve: new items, seasonal variation are normal.\n"
            "- Only escalate to 'suspicious' when multiple signals deviate materially.\n"
        )

    base += "Do not include text outside the JSON."
    return base


def _build_user_prompt(
    extracted: Dict, profile: Optional[Dict],
    validation: Optional[Dict], context: Optional[Dict],
    profile_state: str,
) -> str:
    parts = ["=== EXTRACTED INVOICE ==="]
    for k in ("vendor_name", "vendor_number", "invoice_number", "invoice_date",
              "due_date", "total_amount", "currency", "po_number", "line_items"):
        val = extracted.get(k)
        if val is not None:
            if k == "line_items" and isinstance(val, list):
                parts.append(f"line_items ({len(val)} lines):")
                for i, li in enumerate(val[:10]):
                    parts.append(f"  {i+1}. {li.get('item', li.get('description', '?'))} qty={li.get('quantity', '?')} amt={li.get('amount', '?')}")
            else:
                parts.append(f"{k}: {val}")

    if profile and profile_state != "none":
        parts.append(f"\n=== VENDOR PROFILE (state: {profile_state}) ===")
        parts.append(f"vendor_no: {profile.get('vendor_no')}")
        parts.append(f"vendor_name: {profile.get('vendor_name', '')}")
        parts.append(f"bc_invoice_count: {profile.get('bc_invoice_count', 0)}")
        parts.append(f"posting_confidence: {profile.get('posting_confidence', profile.get('template_confidence', 'unknown'))}")

        amt = profile.get("amount_stats") or {}
        if amt:
            parts.append(f"amount_stats: avg={amt.get('mean', '?')}, min={amt.get('min', '?')}, max={amt.get('max', '?')}")

        items = profile.get("default_item_code") or profile.get("common_items")
        if items:
            parts.append(f"common_items: {items}")
        desc_pat = profile.get("description_pattern")
        if desc_pat:
            parts.append(f"description_pattern: {desc_pat}")
    else:
        parts.append("\n=== VENDOR PROFILE (state: none) ===")
        parts.append("No vendor history. Cannot compare against baseline.")

    if validation:
        parts.append("\n=== VALIDATION ===")
        for k in ("vendor_matched", "po_validated", "amount_validated",
                   "duplicate_check", "all_passed"):
            v = validation.get(k)
            if v is not None:
                parts.append(f"{k}: {v}")

    return "\n".join(parts)


def _parse_json(raw: str) -> Dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(line for line in lines if not line.startswith("```")).strip()
    if text.startswith("{"):
        return json.loads(text)
    if "{" in text:
        return json.loads(text[text.find("{"):text.rfind("}") + 1])
    raise ValueError(f"No JSON: {text[:200]}")


def _error_result(error, vendor_id, profile_state, model_used="none", latency_ms=0):
    return APAdvisoryResult(
        readiness_status="needs_review", confidence=0.0, summary="", blocking_issues=[],
        warnings=[], unusual_patterns=[], profile_matches=[], recommended_next_step="",
        model_used=model_used, latency_ms=latency_ms, schema_valid=False, retry_count=0,
        vendor_profile_id=vendor_id, profile_state=profile_state, error=error,
    )
