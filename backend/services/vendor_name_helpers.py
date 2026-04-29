"""
GPI Document Hub - Vendor Name Helpers

Authoritative implementations of vendor name normalization and fuzzy matching,
extracted from server.py during the "Shared Helper Extraction" remediation pass.

Pure string-manipulation utilities with no database or service dependencies.
Uses rapidfuzz for high-quality fuzzy matching.
"""

import re
from rapidfuzz import fuzz

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
# Fuzzy matching (rapidfuzz-based)
# ---------------------------------------------------------------------------

def calculate_fuzzy_score(name1: str, name2: str) -> float:
    """
    Calculate fuzzy match score between two strings using rapidfuzz.
    Returns a score between 0.0 and 1.0.

    Uses token_sort_ratio for order-independent matching, combined with
    partial_ratio for substring matching (handles BC vendor codes like
    "TUMALOC - Tumalo Creek").
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

    n1 = normalize_vendor_name(name1_clean)
    n2 = normalize_vendor_name(name2_clean)

    if not n1 or not n2:
        return 0.0

    # rapidfuzz returns 0-100, normalize to 0-1
    token_sort = fuzz.token_sort_ratio(n1, n2) / 100.0
    partial = fuzz.partial_ratio(n1, n2) / 100.0

    # Weighted: token_sort is primary, partial helps with substrings
    score = max(token_sort, partial * 0.9)

    # Also check with original (non-cleaned) names
    n1_orig = normalize_vendor_name(name1)
    n2_orig = normalize_vendor_name(name2)
    if n1_orig and n2_orig:
        orig_score = fuzz.token_sort_ratio(n1_orig, n2_orig) / 100.0
        score = max(score, orig_score)

    return score


# ---------------------------------------------------------------------------
# Vendor-name match heuristic (single source of truth)
#
# Imported by:
#   - services/vendor_matching.py        (live sender-stamp guard)
#   - scripts/tier1_batch_runner.py      (re-export for back-compat)
#   - scripts/vendor_mismatch_sweep.py   (sweep)
#
# Substring-tolerant, fail-open on insufficient signal. See
# memory/SENDER_STAMP_GUARD_IMPLEMENTATION_DECLARATION.md §3.1.
# ---------------------------------------------------------------------------

_VENDOR_STOPWORDS = {
    "llc", "inc", "corp", "corporation", "company", "co", "ltd", "limited",
    "the", "and", "of", "for", "group", "holdings",
}


def _vendor_tokens(s: str) -> set:
    """Normalize a vendor name to a set of meaningful tokens
    (≥4 chars, not stopwords)."""
    s = re.sub(r"[^\w\s]", " ", (s or "").lower())
    return {t for t in s.split() if len(t) >= 4 and t not in _VENDOR_STOPWORDS}


def vendor_match_likely(a: str, b: str) -> bool:
    """Heuristic: do these two strings likely refer to the same vendor?

    Substring-tolerant so BC vendor codes (e.g. TUMALOC) match human names
    (e.g. TUMALO CREEK). Returns True when at least one significant token
    from one side is a substring of any token on the other side. Returns
    True when either side has no meaningful tokens (insufficient signal
    to flag as a mismatch — fail-open).
    """
    if not a or not b:
        return True
    if a.strip().lower() == b.strip().lower():
        return True
    ta = _vendor_tokens(a)
    tb = _vendor_tokens(b)
    if not ta or not tb:
        return True
    for x in ta:
        for y in tb:
            if x in y or y in x:
                return True
    return False
