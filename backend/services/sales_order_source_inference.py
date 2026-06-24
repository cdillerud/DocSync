"""Infer customer-order references for historical records without OCR extraction."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.sales_order_preflight import build_sales_order_candidate


_CUSTOMER_REFERENCE_PATTERNS = (
    re.compile(
        r"(?:customer\s+(?:purchase\s+order|po)|customer\s+order)"
        r"(?:\s+(?:number|no\.?))?\s*[:#-]?\s*"
        r"([A-Z0-9][A-Z0-9-]{3,24})",
        re.IGNORECASE,
    ),
)

_GENERIC_REFERENCE_PATTERNS = (
    re.compile(
        r"(?:purchase\s+order|p\.?\s*o\.?|po|order)"
        r"(?:\s+(?:number|no\.?))?\s*[:#-]?\s*"
        r"([A-Z0-9][A-Z0-9-]{3,24})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:number|no\.?)\s*[:#-]\s*([A-Z0-9][A-Z0-9-]{3,24})",
        re.IGNORECASE,
    ),
)

_VENDOR_PO_DOCUMENT_TYPES = {
    "PURCHASE_ORDER",
    "PURCHASEORDER",
    "VENDOR_PURCHASE_ORDER",
}

_SPLIT_SUFFIX_PATTERN = re.compile(r"_doc\d+", re.IGNORECASE)
_PAGE_RANGE_PATTERN = re.compile(
    r"\[pages?\s+\d+(?:-\d+)?/\d+\]",
    re.IGNORECASE,
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


def _extract_reference(
    text: Any,
    *,
    allow_generic: bool,
) -> Optional[str]:
    value = str(text or "").strip()
    if not value:
        return None

    patterns = list(_CUSTOMER_REFERENCE_PATTERNS)
    if allow_generic:
        patterns.extend(_GENERIC_REFERENCE_PATTERNS)

    for pattern in patterns:
        match = pattern.search(value)
        if not match:
            continue
        candidate = _clean_reference(match.group(1))
        if _is_plausible_reference(candidate):
            return candidate
    return None


def _normalize_document_type(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def _effective_document_type(document: Dict[str, Any]) -> str:
    classification = document.get("classification") or {}
    for value in (
        document.get("doc_type"),
        document.get("document_type"),
        document.get("suggested_job_type"),
        classification.get("final_type") if isinstance(classification, dict) else None,
        classification.get("suggested_type") if isinstance(classification, dict) else None,
    ):
        normalized = _normalize_document_type(value)
        if normalized:
            return normalized
    return ""


def _document_text(document: Dict[str, Any]) -> str:
    values = [
        document.get("email_subject"),
        document.get("subject"),
        document.get("file_name"),
        document.get("filename"),
        document.get("raw_text"),
        document.get("ocr_text"),
        document.get("extracted_text"),
        document.get("document_text"),
    ]
    return "\n".join(str(value) for value in values if value)


def _has_customer_context(document: Dict[str, Any]) -> bool:
    extracted = document.get("extracted_fields") or {}
    normalized = document.get("normalized_fields") or {}
    resolved = document.get("resolved_customer") or {}
    return any(
        str(value or "").strip()
        for value in (
            document.get("bc_customer_no"),
            document.get("bc_customer_number"),
            document.get("customer_name_extracted"),
            extracted.get("customer_name") if isinstance(extracted, dict) else None,
            extracted.get("customer_number") if isinstance(extracted, dict) else None,
            normalized.get("customer_name") if isinstance(normalized, dict) else None,
            normalized.get("customer_number") if isinstance(normalized, dict) else None,
            resolved.get("customerNumber") if isinstance(resolved, dict) else None,
            resolved.get("number") if isinstance(resolved, dict) else None,
        )
    )


def _line_candidates(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    extracted = document.get("extracted_fields") or {}
    normalized = document.get("normalized_fields") or {}
    validation = document.get("validation_results") or {}
    validation_normalized = (
        validation.get("normalized_fields")
        if isinstance(validation, dict)
        else {}
    ) or {}

    for value in (
        document.get("sales_order_lines"),
        document.get("line_items"),
        normalized.get("line_items") if isinstance(normalized, dict) else None,
        normalized.get("lines") if isinstance(normalized, dict) else None,
        extracted.get("line_items") if isinstance(extracted, dict) else None,
        extracted.get("lines") if isinstance(extracted, dict) else None,
        validation_normalized.get("line_items")
        if isinstance(validation_normalized, dict)
        else None,
    ):
        if isinstance(value, list):
            return [line for line in value if isinstance(line, dict)]
    return []


def _line_fingerprint(line: Dict[str, Any]) -> Tuple[str, str, str, str]:
    description = str(
        line.get("description")
        or line.get("source_description")
        or line.get("sourceDescription")
        or ""
    ).strip().upper()
    quantity = str(line.get("quantity") or line.get("qty") or "").strip()
    unit_price = str(
        line.get("unit_price")
        or line.get("unitPrice")
        or line.get("price")
        or ""
    ).strip()
    item_number = str(
        line.get("item_number")
        or line.get("itemNumber")
        or line.get("customer_item_number")
        or line.get("customerItemNumber")
        or ""
    ).strip().upper()
    return description, quantity, unit_price, item_number


def _recursive_split_evidence(document: Dict[str, Any]) -> Dict[str, Any]:
    source = str(document.get("source") or "").strip().lower()
    file_name = str(
        document.get("file_name")
        or document.get("filename")
        or ""
    )
    subject = str(
        document.get("email_subject")
        or document.get("subject")
        or ""
    )

    split_suffix_count = len(_SPLIT_SUFFIX_PATTERN.findall(Path(file_name).stem))
    page_range_count = len(_PAGE_RANGE_PATTERN.findall(subject))
    lines = _line_candidates(document)
    fingerprints = {_line_fingerprint(line) for line in lines}
    all_lines_identical = len(lines) > 1 and len(fingerprints) == 1

    recursive = source == "auto_split" and (
        split_suffix_count >= 2
        or page_range_count >= 2
        or all_lines_identical
    )

    return {
        "recursive": recursive,
        "split_suffix_count": split_suffix_count,
        "page_range_count": page_range_count,
        "line_count": len(lines),
        "all_lines_identical": all_lines_identical,
    }


def assess_sales_order_source(document: Dict[str, Any]) -> Dict[str, Any]:
    """Identify strong evidence that a record is not valid customer intake."""

    if document.get("sales_order_excluded") is True:
        return {
            "excluded": True,
            "reason_code": "SALES_ORDER_EXCLUDED",
            "reason": str(
                document.get("sales_order_exclusion_reason")
                or "The document is explicitly excluded from sales-order intake."
            ),
        }

    split_evidence = _recursive_split_evidence(document)
    if split_evidence["recursive"]:
        return {
            "excluded": True,
            "reason_code": "RECURSIVE_SPLIT_ARTIFACT",
            "reason": (
                "The document is a recursively generated split artifact and must be "
                "recovered from its original unsplit source before sales-order review. "
                f"Split suffixes: {split_evidence['split_suffix_count']}; "
                f"page markers: {split_evidence['page_range_count']}; "
                f"lines: {split_evidence['line_count']}; "
                f"all lines identical: {split_evidence['all_lines_identical']}."
            ),
        }

    document_type = _effective_document_type(document)
    if document_type in _VENDOR_PO_DOCUMENT_TYPES:
        return {
            "excluded": True,
            "reason_code": "VENDOR_PURCHASE_ORDER_TYPE",
            "reason": (
                "The effective document type is a vendor purchase order, not a "
                "customer sales-order intake document."
            ),
        }

    text = _document_text(document)
    normalized_text = re.sub(r"\s+", " ", text).strip().lower()

    if re.search(
        r"gamer\s+packaging(?:,?\s+inc\.?)?\s+purchase\s+order",
        normalized_text,
    ):
        return {
            "excluded": True,
            "reason_code": "GAMER_VENDOR_PURCHASE_ORDER",
            "reason": (
                "The source identifies a Gamer Packaging purchase order. Gamer-issued "
                "vendor POs must not be treated as customer sales orders."
            ),
        }

    has_vendor_label = bool(re.search(r"(?:^|\n)\s*vendor\s*:", text, re.IGNORECASE))
    has_purchase_order_heading = bool(
        re.search(r"(?:^|\n)\s*purchase\s+order\s*(?:$|\n)", text, re.IGNORECASE)
    )
    has_gamer_identity = "gamer packaging" in normalized_text
    if has_vendor_label and has_purchase_order_heading and has_gamer_identity:
        return {
            "excluded": True,
            "reason_code": "GAMER_VENDOR_PO_DOCUMENT_CONTENT",
            "reason": (
                "The source contains a Gamer Packaging purchase-order heading and an "
                "explicit Vendor field."
            ),
        }

    return {
        "excluded": False,
        "reason_code": None,
        "reason": None,
    }


def infer_sales_order_reference(
    document: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return a copy with a conservatively inferred customer reference."""

    inferred = copy.deepcopy(document)
    assessment = assess_sales_order_source(inferred)
    if assessment["excluded"]:
        return inferred, {
            "inferred": False,
            "reference": None,
            "source": None,
            "confidence": 0.0,
            "excluded_from_sales_order": True,
            "exclusion_reason_code": assessment["reason_code"],
            "exclusion_reason": assessment["reason"],
        }

    candidate = build_sales_order_candidate(inferred)
    existing = candidate.get("externalDocumentNumber")
    if existing:
        return inferred, {
            "inferred": False,
            "reference": str(existing),
            "source": "existing_extraction",
            "confidence": 1.0,
            "excluded_from_sales_order": False,
        }

    allow_generic = _has_customer_context(inferred)
    subject = inferred.get("email_subject") or inferred.get("subject")
    reference = _extract_reference(subject, allow_generic=allow_generic)
    source = "email_subject" if reference else None
    confidence = 0.95 if reference else 0.0

    if not reference:
        file_name = inferred.get("file_name") or inferred.get("filename")
        stem = Path(str(file_name or "")).stem
        reference = _extract_reference(stem, allow_generic=allow_generic)
        source = "file_name" if reference else None
        confidence = 0.90 if reference else 0.0

    if not reference:
        return inferred, {
            "inferred": False,
            "reference": None,
            "source": None,
            "confidence": 0.0,
            "excluded_from_sales_order": False,
            "reason": (
                "No explicit customer-PO reference was found. Generic purchase-order "
                "language is not used without resolved customer context."
            ),
        }

    extracted_fields = dict(inferred.get("extracted_fields") or {})
    normalized_fields = dict(inferred.get("normalized_fields") or {})

    extracted_fields.setdefault("customer_po_no", reference)
    extracted_fields.setdefault("customer_po_number", reference)
    normalized_fields.setdefault("customer_po", reference)

    inferred["extracted_fields"] = extracted_fields
    inferred["normalized_fields"] = normalized_fields
    inferred["customer_po_number"] = reference
    inferred["order_number_extracted"] = reference

    return inferred, {
        "inferred": True,
        "reference": reference,
        "source": source,
        "confidence": confidence,
        "excluded_from_sales_order": False,
    }
