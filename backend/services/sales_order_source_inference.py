"""Infer customer-order references for historical records without OCR extraction."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from services.sales_order_preflight import build_sales_order_candidate


_REFERENCE_PATTERNS = (
    re.compile(
        r"(?:purchase\s+order|customer\s+po|p\.?\s*o\.?|po|order)"
        r"(?:\s+(?:number|no\.?))?\s*[:#-]?\s*"
        r"([A-Z0-9][A-Z0-9-]{3,24})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:number|no\.?)\s*[:#-]\s*([A-Z0-9][A-Z0-9-]{3,24})",
        re.IGNORECASE,
    ),
)


def _clean_reference(value: Any) -> str:
    text = str(value or "").strip().strip("-_:;,.()[]{}")
    return text.upper()


def _is_plausible_reference(value: str) -> bool:
    if not value or len(value) < 4 or len(value) > 25:
        return False
    if not any(character.isdigit() for character in value):
        return False
    normalized = re.sub(r"[^A-Z0-9]", "", value)
    if len(normalized) < 4:
        return False
    return True


def _extract_reference(text: Any) -> Optional[str]:
    value = str(text or "").strip()
    if not value:
        return None

    for pattern in _REFERENCE_PATTERNS:
        match = pattern.search(value)
        if not match:
            continue
        candidate = _clean_reference(match.group(1))
        if _is_plausible_reference(candidate):
            return candidate
    return None


def infer_sales_order_reference(
    document: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return a copy with an inferred external reference when one is absent."""

    inferred = copy.deepcopy(document)
    candidate = build_sales_order_candidate(inferred)
    existing = candidate.get("externalDocumentNumber")
    if existing:
        return inferred, {
            "inferred": False,
            "reference": str(existing),
            "source": "existing_extraction",
            "confidence": 1.0,
        }

    subject = inferred.get("email_subject") or inferred.get("subject")
    reference = _extract_reference(subject)
    source = "email_subject" if reference else None
    confidence = 0.95 if reference else 0.0

    if not reference:
        file_name = inferred.get("file_name") or inferred.get("filename")
        stem = Path(str(file_name or "")).stem
        reference = _extract_reference(stem)
        source = "file_name" if reference else None
        confidence = 0.90 if reference else 0.0

    if not reference:
        return inferred, {
            "inferred": False,
            "reference": None,
            "source": None,
            "confidence": 0.0,
        }

    extracted_fields = dict(inferred.get("extracted_fields") or {})
    normalized_fields = dict(inferred.get("normalized_fields") or {})

    extracted_fields.setdefault("customer_po_no", reference)
    extracted_fields.setdefault("customer_po_number", reference)
    normalized_fields.setdefault("customer_po", reference)
    normalized_fields.setdefault("po_number", reference)

    inferred["extracted_fields"] = extracted_fields
    inferred["normalized_fields"] = normalized_fields
    inferred["customer_po_number"] = reference
    inferred["order_number_extracted"] = reference

    return inferred, {
        "inferred": True,
        "reference": reference,
        "source": source,
        "confidence": confidence,
    }
