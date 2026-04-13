"""
GPI Document Hub — Ship-To Analysis Service

Normalizes and compares ship-to addresses, classifying match type
and severity before the LLM advisory step to reduce false positives.

ANALYSIS ONLY: Never changes routing or posting decisions.
"""

import logging
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Common abbreviations for normalization
ABBREVIATIONS = {
    "street": "st", "st.": "st", "avenue": "ave", "ave.": "ave",
    "boulevard": "blvd", "blvd.": "blvd", "drive": "dr", "dr.": "dr",
    "road": "rd", "rd.": "rd", "lane": "ln", "ln.": "ln",
    "court": "ct", "ct.": "ct", "place": "pl", "pl.": "pl",
    "suite": "ste", "ste.": "ste", "unit": "unit",
    "north": "n", "south": "s", "east": "e", "west": "w",
    "n.": "n", "s.": "s", "e.": "e", "w.": "w",
    "ne": "ne", "nw": "nw", "se": "se", "sw": "sw",
    "inc.": "inc", "inc": "inc", "llc": "llc", "llc.": "llc",
    "corp.": "corp", "corp": "corp", "co.": "co", "co": "co",
    "warehouse": "whse", "whse.": "whse", "distribution": "dist",
    "dist.": "dist", "center": "ctr", "ctr.": "ctr",
}


@dataclass
class ShipToAnalysis:
    raw_input: str
    normalized: str
    match_type: str    # exact | normalized_match | known_alternate | plausible_new | unknown_new
    severity: str      # none | low | medium | high
    context_notes: str
    known_locations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def analyze_ship_to(
    ship_to_raw: Optional[str],
    profile: Optional[Dict[str, Any]],
    profile_state: str,
    other_signals_normal: bool = True,
) -> ShipToAnalysis:
    """
    Compare an order's ship-to against customer profile history.

    Args:
        ship_to_raw: The ship-to from the extracted order
        profile: Customer posting profile (may be None)
        profile_state: none | weak | medium | strong
        other_signals_normal: True if amount/items/PO all look normal
    """
    raw = (ship_to_raw or "").strip()
    normalized = _normalize(raw)

    # Gather known locations from profile
    known_raw = []
    known_norm = []
    if profile:
        typical = profile.get("typical_ship_to") or ""
        if typical:
            known_raw.append(typical)
            known_norm.append(_normalize(typical))
        # Also check alternate_ship_tos if stored
        for alt in profile.get("alternate_ship_tos", []):
            if alt and alt not in known_raw:
                known_raw.append(alt)
                known_norm.append(_normalize(alt))

    # No ship-to provided
    if not normalized:
        return ShipToAnalysis(
            raw_input=raw, normalized="", match_type="unknown_new",
            severity="low", context_notes="No ship-to address provided on order",
            known_locations=known_raw,
        )

    # No profile — can't compare
    if profile_state == "none" or not known_norm:
        return ShipToAnalysis(
            raw_input=raw, normalized=normalized, match_type="plausible_new",
            severity="none",
            context_notes="No historical ship-to data — cannot assess whether this destination is typical",
            known_locations=known_raw,
        )

    # Exact normalized match
    if normalized in known_norm:
        return ShipToAnalysis(
            raw_input=raw, normalized=normalized, match_type="exact",
            severity="none", context_notes="Matches known customer location",
            known_locations=known_raw,
        )

    # Fuzzy match — check if one contains the other or high token overlap
    for i, kn in enumerate(known_norm):
        if _fuzzy_match(normalized, kn):
            return ShipToAnalysis(
                raw_input=raw, normalized=normalized, match_type="normalized_match",
                severity="none",
                context_notes=f"Close match to known location '{known_raw[i]}' (formatting difference)",
                known_locations=known_raw,
            )

    # Check city/state extraction for partial match
    for i, kn in enumerate(known_norm):
        if _shares_city(normalized, kn):
            return ShipToAnalysis(
                raw_input=raw, normalized=normalized, match_type="known_alternate",
                severity="low",
                context_notes=f"Same city/region as known location '{known_raw[i]}' but different specific address",
                known_locations=known_raw,
            )

    # Truly new destination — severity depends on context + profile diversity
    location_diversity = len(known_raw)  # how many distinct locations has this customer used?

    if profile_state == "weak":
        severity = "low"
        notes = "New destination not seen in limited order history — may be normal, limited comparison basis"
    elif profile_state == "medium":
        if other_signals_normal:
            severity = "low"
            notes = "Destination differs from common historical locations — other order signals look normal"
        else:
            severity = "medium"
            notes = "Destination differs from common historical locations and other signals also warrant review"
    else:  # strong
        if location_diversity >= 3 and other_signals_normal:
            # Customer already ships to 3+ locations — adding another is routine
            severity = "low"
            notes = f"New destination for a customer with {location_diversity} known locations — likely a normal expansion"
        elif other_signals_normal:
            severity = "low"
            notes = "New destination — but all other order signals match this customer's established pattern"
        else:
            severity = "medium"
            notes = "New destination combined with other atypical signals — worth verifying"

    return ShipToAnalysis(
        raw_input=raw, normalized=normalized, match_type="unknown_new",
        severity=severity, context_notes=notes,
        known_locations=known_raw,
    )


# =============================================================================
# Normalization helpers
# =============================================================================

def _normalize(text: str) -> str:
    """Normalize a ship-to string for comparison."""
    s = text.lower().strip()
    # Remove extra whitespace
    s = re.sub(r'\s+', ' ', s)
    # Remove common punctuation
    s = s.replace(",", " ").replace(".", " ").replace("#", "").replace("-", " ")
    s = re.sub(r'\s+', ' ', s).strip()
    # Apply abbreviations
    tokens = s.split()
    normalized_tokens = [ABBREVIATIONS.get(t, t) for t in tokens]
    return " ".join(normalized_tokens)


def _fuzzy_match(a: str, b: str) -> bool:
    """Check if two normalized strings are close enough to be the same location."""
    if not a or not b:
        return False
    # One contains the other
    if a in b or b in a:
        return True
    # Token overlap >= 70%
    ta = set(a.split())
    tb = set(b.split())
    if not ta or not tb:
        return False
    overlap = len(ta & tb)
    smaller = min(len(ta), len(tb))
    return (overlap / smaller) >= 0.7 if smaller > 0 else False


def _shares_city(a: str, b: str) -> bool:
    """Check if two addresses share the same city name."""
    # Common US city names that might appear in ship-to
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    # If they share 2+ tokens that aren't common abbreviations
    common_words = {"st", "ave", "blvd", "dr", "rd", "n", "s", "e", "w", "ste", "unit", "inc", "llc"}
    meaningful_overlap = (a_tokens & b_tokens) - common_words
    return len(meaningful_overlap) >= 2
