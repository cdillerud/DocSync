"""
GPI Document Hub — Item / UOM Analysis Service

Pre-LLM analysis of order line items and units of measure against
customer posting profile history. Classifies match quality and
severity to reduce false positives in the advisory reviewer.

ANALYSIS ONLY: Never changes routing or posting decisions.
"""

import logging
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# UOM aliases — groups that should be treated as equivalent
UOM_ALIASES = {
    "ea": {"ea", "each", "eac", "pc", "pcs", "piece", "pieces", "unit", "units"},
    "cs": {"cs", "case", "cases", "cse", "ca"},
    "pk": {"pk", "pack", "packs", "pkg", "package", "packages"},
    "bx": {"bx", "box", "boxes"},
    "pl": {"pl", "pallet", "pallets", "plt", "pal"},
    "ct": {"ct", "carton", "cartons", "ctn"},
    "dz": {"dz", "dozen", "doz"},
    "lb": {"lb", "lbs", "pound", "pounds"},
    "kg": {"kg", "kgs", "kilogram", "kilograms"},
    "gal": {"gal", "gallon", "gallons"},
    "ltr": {"ltr", "l", "liter", "liters", "litre", "litres"},
    "ft": {"ft", "feet", "foot"},
    "rl": {"rl", "roll", "rolls"},
    "set": {"set", "sets", "st"},
}

# Build reverse lookup
_UOM_CANONICAL = {}
for canonical, aliases in UOM_ALIASES.items():
    for alias in aliases:
        _UOM_CANONICAL[alias] = canonical


@dataclass
class LineAnalysis:
    line_index: int
    raw_item: str
    normalized_item: str
    raw_uom: str
    normalized_uom: str
    item_match: str       # exact | normalized | known_alternate | new_plausible | unknown
    uom_match: str        # exact | alias_match | known_alternate | unknown
    severity: str         # none | low | medium | high
    context_note: str


@dataclass
class ItemUomAnalysis:
    total_lines: int
    lines_exact: int
    lines_normalized: int
    lines_new_plausible: int
    lines_unknown: int
    unusual_line_count: int
    overall_severity: str   # none | low | medium | high
    context_notes: str
    line_details: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def analyze_items_uom(
    line_items: List[Dict[str, Any]],
    profile: Optional[Dict[str, Any]],
    profile_state: str,
    other_signals_normal: bool = True,
) -> ItemUomAnalysis:
    """
    Compare order line items against customer profile history.
    """
    if not line_items:
        return ItemUomAnalysis(
            total_lines=0, lines_exact=0, lines_normalized=0,
            lines_new_plausible=0, lines_unknown=0, unusual_line_count=0,
            overall_severity="none",
            context_notes="No line items to analyze",
            line_details=[],
        )

    known_items_raw = set(profile.get("common_items", [])) if profile else set()
    known_items_norm = {_normalize_item(i) for i in known_items_raw}
    known_uoms_raw = set(profile.get("common_uoms", [])) if profile else set()
    known_uoms_norm = {_normalize_uom(u) for u in known_uoms_raw}
    known_uoms_canonical = {_UOM_CANONICAL.get(u.lower().strip(), u.lower().strip()) for u in known_uoms_raw}

    details: List[LineAnalysis] = []

    for idx, line in enumerate(line_items[:20]):  # cap at 20 lines
        raw_item = line.get("item_number") or line.get("item") or line.get("description") or ""
        raw_uom = line.get("uom") or line.get("unit_of_measure") or ""
        norm_item = _normalize_item(raw_item)
        norm_uom = _normalize_uom(raw_uom)
        uom_canonical = _UOM_CANONICAL.get(norm_uom, norm_uom)

        # Item match classification
        if norm_item in known_items_norm:
            item_match = "exact"
        elif known_items_norm and _fuzzy_item_match(norm_item, known_items_norm):
            item_match = "normalized"
        elif not known_items_norm:
            item_match = "new_plausible"
        else:
            item_match = "unknown"

        # UOM match classification
        if not raw_uom:
            uom_match = "exact"  # no UOM specified — no mismatch
        elif norm_uom in known_uoms_norm or uom_canonical in known_uoms_canonical:
            uom_match = "exact"
        elif known_uoms_canonical and uom_canonical in _UOM_CANONICAL.values():
            # It's a valid UOM but not one this customer usually uses
            uom_match = "known_alternate"
        elif not known_uoms_norm:
            uom_match = "exact"  # no history — can't compare
        else:
            uom_match = "unknown"

        # Line severity
        severity, note = _classify_line_severity(
            item_match, uom_match, profile_state, other_signals_normal
        )

        details.append(LineAnalysis(
            line_index=idx, raw_item=raw_item, normalized_item=norm_item,
            raw_uom=raw_uom, normalized_uom=norm_uom,
            item_match=item_match, uom_match=uom_match,
            severity=severity, context_note=note,
        ))

    # Aggregate
    lines_exact = sum(1 for d in details if d.item_match in ("exact", "normalized") and d.uom_match == "exact")
    lines_normalized = sum(1 for d in details if d.item_match == "normalized")
    lines_new = sum(1 for d in details if d.item_match == "new_plausible")
    lines_unknown = sum(1 for d in details if d.item_match == "unknown")
    unusual = sum(1 for d in details if d.severity in ("medium", "high"))

    overall = _compute_overall_severity(details, profile_state, other_signals_normal)

    context = _build_context_notes(details, profile_state, known_items_raw, len(line_items))

    return ItemUomAnalysis(
        total_lines=len(details),
        lines_exact=lines_exact,
        lines_normalized=lines_normalized,
        lines_new_plausible=lines_new,
        lines_unknown=lines_unknown,
        unusual_line_count=unusual,
        overall_severity=overall,
        context_notes=context,
        line_details=[asdict(d) for d in details],
    )


# =============================================================================
# Normalization
# =============================================================================

def _normalize_item(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r'[\s\-_\.]+', ' ', s).strip()
    s = re.sub(r'\s+', ' ', s)
    return s


def _normalize_uom(text: str) -> str:
    s = text.lower().strip().rstrip(".")
    return s


def _fuzzy_item_match(needle: str, known_set: set) -> bool:
    if not needle:
        return False
    for known in known_set:
        if needle in known or known in needle:
            return True
        # Token overlap
        nt = set(needle.split())
        kt = set(known.split())
        if nt and kt:
            overlap = len(nt & kt) / min(len(nt), len(kt))
            if overlap >= 0.6:
                return True
    return False


# =============================================================================
# Severity classification
# =============================================================================

def _classify_line_severity(
    item_match: str, uom_match: str,
    profile_state: str, other_normal: bool,
) -> tuple:
    # No history — everything is plausible
    if profile_state == "none":
        return "none", "No customer history — cannot assess item/UOM normalcy"

    if item_match in ("exact", "normalized") and uom_match == "exact":
        return "none", "Matches customer history"

    if item_match in ("exact", "normalized") and uom_match == "known_alternate":
        if profile_state == "weak":
            return "none", "Known item, alternate UOM — limited comparison basis"
        return "low", "Known item with non-typical UOM — may be a valid variant"

    if item_match == "new_plausible":
        return "none", "No item history for comparison"

    if item_match == "unknown":
        if profile_state == "weak":
            return "low", "Item not in limited history — may be normal for this customer"
        if profile_state == "medium":
            if other_normal:
                return "low", "Item not in moderate history — rest of order looks normal"
            return "medium", "Item not in moderate history and other signals also warrant review"
        # strong
        if other_normal:
            return "medium", "Item not seen in extensive order history — worth verifying"
        return "high", "Unknown item combined with other anomalies — elevated concern"

    if uom_match == "unknown":
        if profile_state in ("weak", "none"):
            return "none", "UOM cannot be assessed with limited history"
        return "low", "Non-standard UOM for this customer"

    return "none", ""


def _compute_overall_severity(
    details: List[LineAnalysis], profile_state: str, other_normal: bool,
) -> str:
    if not details:
        return "none"
    severities = [d.severity for d in details]
    if "high" in severities:
        return "high"
    medium_count = severities.count("medium")
    if medium_count >= 2:
        return "high"
    if medium_count == 1:
        return "medium"
    if severities.count("low") >= 2 and profile_state == "strong":
        return "medium" if not other_normal else "low"
    if "low" in severities:
        return "low"
    return "none"


def _build_context_notes(
    details: List[LineAnalysis], profile_state: str,
    known_items: set, total_lines: int,
) -> str:
    if profile_state == "none":
        return f"{total_lines} line(s) — no customer history for item/UOM comparison"

    exact = sum(1 for d in details if d.item_match in ("exact", "normalized") and d.uom_match == "exact")
    unknown = sum(1 for d in details if d.item_match == "unknown")

    if unknown == 0:
        return f"All {total_lines} line(s) use known items and expected UOMs"

    if profile_state == "weak":
        return (f"{exact}/{total_lines} lines match limited history, "
                f"{unknown} line(s) not in sparse profile — may be normal")

    return (f"{exact}/{total_lines} lines match customer history, "
            f"{unknown} line(s) with items not previously seen")
