"""
GPI Document Hub - Vendor Name Helpers

Authoritative implementations of vendor name normalization and fuzzy matching,
extracted from server.py during the "Shared Helper Extraction" remediation pass.

Pure string-manipulation utilities with no database or service dependencies.
"""

import re

# ---------------------------------------------------------------------------
# In-memory alias map (loaded from DB at startup, mutated by alias CRUD)
# ---------------------------------------------------------------------------

VENDOR_ALIAS_MAP: dict = {
    # "Alias on Invoice": "Vendor Name in BC"
    # Populated at runtime by alias CRUD operations
}


# ---------------------------------------------------------------------------
# Vendor name normalization
# ---------------------------------------------------------------------------

def normalize_vendor_name(name: str) -> str:
    """
    Normalize vendor name for matching.
    Strips common suffixes, punctuation, and converts to lowercase.
    """
    if not name:
        return ""

    name = name.lower()

    suffixes = [
        r'\s*,?\s*(inc\.?|incorporated)$',
        r'\s*,?\s*(llc\.?|l\.l\.c\.?)$',
        r'\s*,?\s*(ltd\.?|limited)$',
        r'\s*,?\s*(corp\.?|corporation)$',
        r'\s*,?\s*(co\.?|company)$',
        r'\s*,?\s*(plc\.?)$',
        r'\s*,?\s*(gmbh)$',
        r'\s*,?\s*(ag)$',
    ]

    for suffix in suffixes:
        name = re.sub(suffix, '', name, flags=re.IGNORECASE)

    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()

    return name


# ---------------------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------------------

def calculate_fuzzy_score(name1: str, name2: str) -> float:
    """
    Calculate fuzzy match score between two strings.
    Uses simple token overlap ratio.
    Also handles BC vendor names that include vendor codes like "TUMALOC - Tumalo Creek"
    """
    if not name1 or not name2:
        return 0.0

    def clean_bc_name(name):
        n = name
        if ' - ' in n:
            parts = n.split(' - ', 1)
            if len(parts) == 2 and len(parts[0]) <= 10:
                n = parts[1]
        return n

    name1_clean = clean_bc_name(name1)
    name2_clean = clean_bc_name(name2)

    tokens1 = set(normalize_vendor_name(name1_clean).split())
    tokens2 = set(normalize_vendor_name(name2_clean).split())

    if not tokens1 or not tokens2:
        return 0.0

    intersection = tokens1 & tokens2
    union = tokens1 | tokens2

    base_score = len(intersection) / len(union)

    orig_tokens1 = set(normalize_vendor_name(name1).split())
    orig_tokens2 = set(normalize_vendor_name(name2).split())
    orig_intersection = orig_tokens1 & orig_tokens2
    orig_union = orig_tokens1 | orig_tokens2
    orig_score = len(orig_intersection) / len(orig_union) if orig_union else 0

    return max(base_score, orig_score)
