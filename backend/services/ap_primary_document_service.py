"""Primary document classification wrapper for AP intake.

Uses the existing Gemini classifier for rich extraction, but restores the clear
PDF invoice/credit guards with the installed `pypdf` dependency. Page 1 remains
classification authority; supporting pages are handled separately.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from services.document_intel_helpers import (
    _BOL_FILENAME_PATTERNS,
    _CREDIT_MEMO_PATTERNS,
    _INVOICE_TEXT_PATTERNS,
    _PL_FILENAME_PATTERNS,
    classify_document_with_ai,
)


def _first_page_text(file_path: str, max_chars: int = 5000) -> str:
    if Path(file_path).suffix.lower() != ".pdf":
        return ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        if not reader.pages:
            return ""
        return (reader.pages[0].extract_text() or "")[:max_chars]
    except Exception:
        return ""


def _pypdf_primary_guard(file_path: str, file_name: str) -> Dict[str, Any] | None:
    text = _first_page_text(file_path)
    if not text:
        return None

    credit_matches = _CREDIT_MEMO_PATTERNS.findall(text)
    if credit_matches:
        fields: Dict[str, Any] = {"credit_memo_detected_by": "pypdf_text_pattern"}
        number = re.search(
            r"(?:credit\s+)?(?:invoice|memo)\s*#?\s*[:\s]*([A-Z0-9-]{2,24})",
            text,
            re.I,
        )
        amount = re.search(
            r"(?:credit\s+memo\s+total|total|amount)[:\s]*-?\$?([\d,]+\.?\d*)",
            text,
            re.I,
        )
        if number:
            fields["credit_memo_number"] = number.group(1).strip()
        if amount:
            fields["amount"] = amount.group(1).strip()
        return {
            "suggested_job_type": "Credit_Memo",
            "confidence": 0.94,
            "model": "pypdf-credit-memo-guard",
            "extracted_fields": fields,
            "guard_indicator_count": len(credit_matches),
        }

    invoice_matches = _INVOICE_TEXT_PATTERNS.findall(text)
    filename = str(file_name or "").lower()
    if len(invoice_matches) >= 2:
        # Explicit filenames saying packing list/BOL remain document-purpose evidence.
        if _PL_FILENAME_PATTERNS.search(filename) or _BOL_FILENAME_PATTERNS.search(filename):
            return None
        fields = {"ap_invoice_detected_by": "pypdf_text_pattern"}
        number = re.search(r"invoice\s*#?\s*[:\s]*([A-Z0-9-]{2,24})", text, re.I)
        amount = re.search(
            r"(?:balance\s+due|amount\s+due|total)[:\s]*\$?([\d,]+\.?\d*)",
            text,
            re.I,
        )
        if number:
            fields["invoice_number"] = number.group(1).strip()
        if amount:
            fields["amount"] = amount.group(1).strip()
        return {
            "suggested_job_type": "AP_Invoice",
            "confidence": 0.92,
            "model": "pypdf-ap-invoice-guard",
            "extracted_fields": fields,
            "guard_indicator_count": len(invoice_matches),
        }
    return None


def _merge_fields(base: Dict[str, Any], guard: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base or {})
    for key, value in (guard or {}).items():
        if value not in (None, "", [], {}):
            merged.setdefault(key, value)
    return merged


async def classify_primary_document(file_path: str, file_name: str) -> Dict[str, Any]:
    """Classify page-1 document purpose with deterministic guard + Gemini richness."""
    guard = _pypdf_primary_guard(file_path, file_name)
    ai = await classify_document_with_ai(file_path, file_name)
    result = dict(ai or {})

    if not guard:
        result["primary_classification_guard"] = None
        return result

    ai_type = result.get("suggested_job_type") or result.get("document_type") or ""
    guard_type = guard["suggested_job_type"]
    result["classification_before_primary_guard"] = ai_type
    result["primary_classification_guard"] = guard
    result["extracted_fields"] = _merge_fields(
        result.get("extracted_fields") or {}, guard.get("extracted_fields") or {}
    )

    # Credit memo and clear payable-invoice semantics are dangerous enough to
    # be deterministic guards. This prevents carrier identity from changing an
    # invoice into Freight_Document while retaining Gemini's extracted fields.
    result["suggested_job_type"] = guard_type
    result["document_type"] = guard_type
    result["confidence"] = max(float(result.get("confidence") or 0.0), float(guard["confidence"]))
    result["classification_guard_applied"] = ai_type != guard_type
    result["classification_guard_reason"] = guard.get("model")
    return result
