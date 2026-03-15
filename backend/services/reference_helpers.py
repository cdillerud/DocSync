"""
GPI Document Hub - Reference Intelligence Shared Helpers

Canonical normalization, fuzzy matching, and freight detection utilities
used across the reference intelligence domain.

Consumers:
  - entity_resolution_service  (normalize_text, fuzzy_ratio)
  - reference_intelligence_service  (normalize_reference, is_freight_carrier)
  - unified_vendor_matcher  (normalize_company_name, fuzzy_ratio, is_freight_carrier)
  - bc_reference_resolver / bc_reference_cache_service (normalize_reference)
"""

import re
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# 1. Text normalization  (generic string → matching-safe form)
# ---------------------------------------------------------------------------

def normalize_text(value: str) -> str:
    """Normalize a string for matching: lowercase, strip, collapse whitespace,
    remove punctuation.

    Used by: entity_resolution_service (customer/vendor/PO/invoice matching).
    """
    if not value:
        return ""
    s = str(value).lower().strip()
    s = re.sub(r'[^\w\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# ---------------------------------------------------------------------------
# 2. Reference number normalization  (document/PO/BOL numbers → BC lookup key)
# ---------------------------------------------------------------------------

_REFERENCE_PREFIXES = [
    (r'^BOL[\s\-#:\.]*', 'strip_bol_prefix'),
    (r'^B/L[\s\-#:\.]*', 'strip_bl_prefix'),
    (r'^P\.?O\.?[\s\-#:\.]*', 'strip_po_prefix'),
    (r'^REF[\s\-#:\.]*', 'strip_ref_prefix'),
    (r'^ORDER[\s\-#:\.]*', 'strip_order_prefix'),
    (r'^SO[\s\-#:\.]*', 'strip_so_prefix'),
    (r'^SHIP[\s\-#:\.]*', 'strip_ship_prefix'),
    (r'^LOAD[\s\-#:\.]*', 'strip_load_prefix'),
    (r'^PRO[\s\-#:\.]*', 'strip_pro_prefix'),
    (r'^INV[\s\-#:\.]*', 'strip_inv_prefix'),
    (r'^PU[\s\-#:\.]*', 'strip_pu_prefix'),
    (r'^#', 'strip_hash_prefix'),
]


def normalize_reference(raw_value: str, *, return_trace: bool = False):
    """Normalize a reference number for BC lookup.

    Steps: uppercase → strip known prefixes → strip punctuation → strip leading zeros.

    If *return_trace* is True, returns ``(normalized, trace_steps[])``.

    Used by: reference_intelligence_service, bc_reference_cache_service.
    """
    if not raw_value:
        return ("", []) if return_trace else ""

    trace: List[dict] = []
    normalized = raw_value.strip()
    trace.append({"step": "input", "value": normalized})

    upper = normalized.upper()
    if upper != normalized:
        trace.append({"step": "uppercase", "value": upper})
    normalized = upper

    for prefix_re, step_name in _REFERENCE_PREFIXES:
        before = normalized
        normalized = re.sub(prefix_re, '', normalized, flags=re.IGNORECASE)
        if normalized != before:
            trace.append({"step": step_name, "value": normalized})

    clean = re.sub(r'[\s\-\.\#\:\,]+', '', normalized)
    if clean != normalized:
        trace.append({"step": "strip_punctuation", "value": clean})
    normalized = clean

    stripped = normalized.lstrip('0') or '0'
    if stripped != normalized:
        trace.append({"step": "strip_leading_zeros", "value": stripped})
    normalized = stripped

    return (normalized, trace) if return_trace else normalized


# ---------------------------------------------------------------------------
# 3. Company name normalization  (vendor/customer name → matching key)
# ---------------------------------------------------------------------------

_COMPANY_SUFFIXES = [
    " inc", " inc.", " llc", " corp", " corp.", " corporation",
    " co", " co.", " company", " ltd", " ltd.", " lp", " lp.",
]


def normalize_company_name(name: str) -> str:
    """Normalize a company/vendor name for matching.

    Steps: lowercase → strip common legal suffixes → remove special chars →
    collapse whitespace.

    Used by: unified_vendor_matcher.
    """
    if not name:
        return ""
    normalized = name.lower().strip()
    for suffix in _COMPANY_SUFFIXES:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
    normalized = re.sub(r'[^\w\s]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized


# ---------------------------------------------------------------------------
# 4. Fuzzy matching
# ---------------------------------------------------------------------------

def fuzzy_ratio(a: str, b: str, normalizer=None) -> float:
    """SequenceMatcher ratio between two strings.

    If *normalizer* is provided it is applied to both strings before comparison.
    """
    if not a or not b:
        return 0.0
    if normalizer:
        a = normalizer(a)
        b = normalizer(b)
    return SequenceMatcher(None, a, b).ratio()


def fuzzy_vendor_match(a: str, b: str) -> bool:
    """Quick vendor-name similarity check (prefix + token overlap).

    Returns True when the two names are "close enough" without computing a
    full SequenceMatcher ratio — useful for counterparty alignment checks
    where speed matters more than precision.

    Used by: reference_intelligence_service (counterparty scoring).
    """
    if not a or not b:
        return False
    # Prefix match (handles abbreviations)
    min_len = min(len(a), len(b))
    if min_len >= 6 and a[:6] == b[:6]:
        return True
    # Token overlap
    tokens_a = set(a.replace(",", " ").split())
    tokens_b = set(b.replace(",", " ").split())
    if tokens_a and tokens_b:
        overlap = len(tokens_a & tokens_b)
        if overlap >= 2 or (overlap >= 1 and min(len(tokens_a), len(tokens_b)) <= 2):
            return True
    return False


# ---------------------------------------------------------------------------
# 5. Freight carrier detection
# ---------------------------------------------------------------------------

FREIGHT_KEYWORDS = frozenset([
    "freight", "transport", "trucking", "logistics", "carrier",
    "shipping", "express", "delivery", "ltl", "truckload",
    "moving", "hauling", "drayage",
])


def is_freight_carrier(name: str) -> bool:
    """Return True if *name* contains a freight-related keyword."""
    if not name:
        return False
    name_lower = name.lower()
    return any(kw in name_lower for kw in FREIGHT_KEYWORDS)
