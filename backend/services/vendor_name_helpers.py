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
            # "TUMALOC - Tumalo Creek" is code - name; "Ardagh - ST" is name -
            # plant code, and "ST" alone matched inside "Stephen Conroy".
            if len(parts) == 2 and len(parts[0]) <= 10 and len(parts[1].strip()) >= 4:
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
    # A short name only matches as a whole word ("XPO" in "XPO Logistics"):
    # as a substring "ct" (CT Corporation) is inside "products" and "st"
    # (Ardagh - ST) inside "Stephen Conroy" (97 documents mis-resolved).
    short, long_ = sorted((n1, n2), key=len)
    if len(short) < 5:
        partial = 1.0 if re.search(r"(?<![a-z0-9])" + re.escape(short) + r"(?![a-z0-9])", long_) else 0.0
    else:
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

# ---------------------------------------------------------------------------
# Strict vendor identity agreement
# ---------------------------------------------------------------------------

_VENDOR_IDENTITY_GENERIC_TOKENS = {
    "packaging",
    "solution",
    "solutions",
    "service",
    "services",
    "logistics",
    "transport",
    "transportation",
    "warehouse",
    "manufacturing",
    "manufacturer",
    "industry",
    "industries",
    "product",
    "products",
    "supply",
    "supplies",
    "distribution",
    "distributor",
    "distributors",
    "global",
    "international",
    "group",
    "holdings",
}


def _vendor_identity_anchor_tokens(value: str) -> set:
    """Return brand-like tokens, excluding generic business descriptors."""
    normalized = normalize_vendor_name(value)
    return {
        token
        for token in normalized.split()
        if token and token not in _VENDOR_IDENTITY_GENERIC_TOKENS
    }


def vendor_identity_agrees(a: str, b: str) -> bool:
    """Safely decide whether two non-empty names identify the same vendor.

    This is intentionally stricter than vendor_match_likely. Generic shared
    words such as "packaging", "solutions", and "logistics" are not enough
    to allow sender-, alias-, or history-derived evidence to replace the
    vendor name extracted directly from a document.
    """
    if not a or not b:
        return True

    normalized_a = normalize_vendor_name(a)
    normalized_b = normalize_vendor_name(b)

    if not normalized_a or not normalized_b:
        return True
    if normalized_a == normalized_b:
        return True

    anchors_a = _vendor_identity_anchor_tokens(a)
    anchors_b = _vendor_identity_anchor_tokens(b)
    score = calculate_fuzzy_score(a, b)

    if anchors_a and anchors_b:
        # Substring agreement only for tokens of 4+ characters: short anchors
        # ("st" from "Ardagh - ST", "ct" from "CT Corporation") sat inside
        # unrelated names ("Bluecrest Storage", "Select ...", "Pactiv") and
        # made those vendors attractors for learned aliases.
        code_a = " " not in normalized_a.strip()
        code_b = " " not in normalized_b.strip()

        def _initials(anchors):
            return "".join(t[0] for t in sorted(anchors, key=lambda t: normalized_a.find(t) if t in normalized_a else normalized_b.find(t))) if len(anchors) >= 2 else ""

        def _tokens_agree(left, right):
            if left == right:
                return True
            short, long_ = sorted((left, right), key=len)
            if len(short) >= 4 and short in long_:
                return True
            # A BC vendor code ("H3PLAST", "XPOLOGI", "VNGRAPH") starts with
            # the brand; only for one-word code names, not "Ardagh - ST".
            long_is_code = (long_ == left and code_a) or (long_ == right and code_b)
            return len(short) >= 2 and long_is_code and long_.startswith(short)

        initials_a, initials_b = _initials(anchors_a), _initials(anchors_b)
        anchor_agreement = any(
            _tokens_agree(left, right)
            for left in anchors_a
            for right in anchors_b
        ) or bool(initials_b and initials_b in anchors_a) or bool(initials_a and initials_a in anchors_b)
        return anchor_agreement and score >= 0.55

    # With no distinctive brand tokens, require near-identical full names.
    return score >= 0.92
