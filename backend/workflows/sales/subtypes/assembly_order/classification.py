"""
GPI Hub — Assembly Order classifier (Lane C Step 4b)

Pure, rule-based classifier mirroring the PH pattern. Orthogonal to the
DS/WH classifier in services/document_intel_helpers.py — a document
can be WH *and* Assembly, or neither.

UNWIRED: nothing in production calls this function in the current PR.
Exercised only by its own pytest.

Drop-ship keywords / location codes are redeclared locally here rather
than cross-imported from the PH package. This keeps both archetype
packages fully self-contained (no sibling-package coupling) per the
package-isolation discipline established in Step 4a.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Tuple

# Threshold at which the doc is declared Assembly. Tuned so that any
# single explicit positive signal (order_type, BOM field) crosses it.
ASSEMBLY_CONFIDENCE_THRESHOLD: float = 0.5

# Strict BOM-completeness mode flag — reserved for future tightening.
# When False (default), the bom_completeness gate warns; when True, it
# would block. Not consumed this pass; shipped as a constant hook.
ASSEMBLY_BOM_COMPLETENESS_STRICT: bool = False

# Known Assembly customers — INTENTIONALLY EMPTY per the user sign-off
# rule from Step 4a (no hardcoded customer-specific knowledge). Hook
# preserved for later expansion.
KNOWN_ASSEMBLY_CUSTOMERS: Tuple[str, ...] = ()

# Signal weights.
_W_ORDER_TYPE_ASSEMBLY: float = 0.7
_W_ORDER_TYPE_KIT: float = 0.7
_W_ORDER_TYPE_WORK_ORDER: float = 0.6
_W_BOM_FIELD_PRESENT: float = 0.6
_W_ASSEMBLY_KEYWORD: float = 0.5
_W_KIT_KEYWORD: float = 0.4
_W_KNOWN_CUSTOMER: float = 0.4
_W_DROP_SHIP_KEYWORD: float = -0.8
_W_DROP_SHIP_LOCATION: float = -0.7

# Textual markers (lowercase).
_ASSEMBLY_KEYWORDS: Tuple[str, ...] = (
    "assembly order", "assemble and ship", "bill of materials",
    "work order",
)
_KIT_KEYWORDS: Tuple[str, ...] = (
    "kit order", "kitting", "kit assembly", "pre-kitted",
)

# Locally redeclared drop-ship markers (matches PH's set; intentional
# duplication over cross-package imports — see module docstring).
_DROP_SHIP_KEYWORDS: Tuple[str, ...] = (
    "drop ship", "dropship", "drop-ship", "direct ship", "ship direct",
)
_DROP_SHIP_LOCATION_CODES: Tuple[str, ...] = ("00", "001")

# BOM field names recognized on the extracted doc.
_BOM_FIELDS: Tuple[str, ...] = (
    "bom", "components", "kit_items", "bill_of_materials", "assembly_components",
)

_ORDER_TYPE_ALIASES = {
    "assembly": _W_ORDER_TYPE_ASSEMBLY,
    "kit":      _W_ORDER_TYPE_KIT,
    "work_order": _W_ORDER_TYPE_WORK_ORDER,
    "work order": _W_ORDER_TYPE_WORK_ORDER,
}


@dataclass(frozen=True)
class AssemblyClassification:
    is_assembly_order: bool
    confidence: float
    signals: Tuple[str, ...]
    reasons: Tuple[str, ...]


_EMPTY = AssemblyClassification(
    is_assembly_order=False,
    confidence=0.0,
    signals=(),
    reasons=("no signals found",),
)


def _collect_text(doc: Mapping[str, Any], ef: Mapping[str, Any]) -> str:
    parts = [
        doc.get("raw_text") or "",
        doc.get("ocr_text") or "",
        ef.get("description") or "",
        ef.get("notes") or "",
        ef.get("special_instructions") or "",
        ef.get("remarks") or "",
    ]
    return " ".join(str(p) for p in parts).lower()


def _extract_customer_no(doc: Mapping[str, Any], ef: Mapping[str, Any]) -> str:
    for key in ("customer_no", "customer_number", "bill_to_customer_no"):
        v = ef.get(key) or doc.get(key)
        if v:
            return str(v).strip().upper()
    return ""


def _has_bom_with_entries(ef: Mapping[str, Any], doc: Mapping[str, Any]) -> bool:
    for key in _BOM_FIELDS:
        val = ef.get(key) or doc.get(key)
        if isinstance(val, (list, tuple)) and len(val) > 0:
            return True
    return False


def classify_assembly_order(
    doc: Mapping[str, Any], extracted_fields: Mapping[str, Any],
) -> AssemblyClassification:
    """Classify a sales document. Pure; no I/O; no DB; no mutation.

    Returns the ``_EMPTY`` sentinel when nothing triggers; otherwise
    returns an ``AssemblyClassification`` whose ``is_assembly_order``
    reflects ``confidence >= ASSEMBLY_CONFIDENCE_THRESHOLD``.
    """
    doc = doc or {}
    ef = extracted_fields or {}

    signals: list[str] = []
    reasons: list[str] = []
    score = 0.0

    text = _collect_text(doc, ef)

    # ── Positive signals ────────────────────────────────────────────────
    order_type = (ef.get("order_type") or doc.get("order_type") or "").strip().lower()
    if order_type in _ORDER_TYPE_ALIASES:
        weight = _ORDER_TYPE_ALIASES[order_type]
        score += weight
        signals.append("order_type_assembly")
        reasons.append(f"order_type field == '{order_type}'")

    if _has_bom_with_entries(ef, doc):
        score += _W_BOM_FIELD_PRESENT
        signals.append("bom_field_present")
        reasons.append("BOM / components / kit_items field has entries")

    matched_assembly = next((kw for kw in _ASSEMBLY_KEYWORDS if kw in text), None)
    if matched_assembly:
        score += _W_ASSEMBLY_KEYWORD
        signals.append("assembly_keyword")
        reasons.append(f"assembly keyword in text: '{matched_assembly}'")

    matched_kit = next((kw for kw in _KIT_KEYWORDS if kw in text), None)
    if matched_kit:
        score += _W_KIT_KEYWORD
        signals.append("kit_keyword")
        reasons.append(f"kit keyword in text: '{matched_kit}'")

    customer_no = _extract_customer_no(doc, ef)
    if customer_no and any(customer_no == c.upper() for c in KNOWN_ASSEMBLY_CUSTOMERS):
        score += _W_KNOWN_CUSTOMER
        signals.append("known_assembly_customer")
        reasons.append(
            f"customer {customer_no} is on the KNOWN_ASSEMBLY_CUSTOMERS seed"
        )

    # ── Negative signals ────────────────────────────────────────────────
    matched_ds = next((kw for kw in _DROP_SHIP_KEYWORDS if kw in text), None)
    if matched_ds:
        score += _W_DROP_SHIP_KEYWORD
        signals.append("drop_ship_keyword")
        reasons.append(f"drop-ship keyword in text: '{matched_ds}'")

    loc = (ef.get("ship_to_location_code") or ef.get("location_code") or "").strip()
    if loc and loc in _DROP_SHIP_LOCATION_CODES:
        score += _W_DROP_SHIP_LOCATION
        signals.append("drop_ship_location")
        reasons.append(f"location_code '{loc}' is a drop-ship code")

    if not signals:
        return _EMPTY

    confidence = max(0.0, min(1.0, score))
    return AssemblyClassification(
        is_assembly_order=confidence >= ASSEMBLY_CONFIDENCE_THRESHOLD,
        confidence=confidence,
        signals=tuple(signals),
        reasons=tuple(reasons),
    )


__all__ = [
    "AssemblyClassification",
    "ASSEMBLY_CONFIDENCE_THRESHOLD",
    "ASSEMBLY_BOM_COMPLETENESS_STRICT",
    "KNOWN_ASSEMBLY_CUSTOMERS",
    "classify_assembly_order",
]
