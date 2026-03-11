"""
GPI Document Hub — Fuzzy Reference Matching Module

Provides advanced comparison logic for reference numbers that handles
real-world document artifacts: OCR errors, truncation, padding,
vendor-specific formatting, partial matches.

All functions are pure (no I/O), making them fast and testable.
"""

import re
from typing import Dict, Tuple, Optional

# =============================================================================
# OCR ERROR MAP — common character substitutions in scanned documents
# =============================================================================

OCR_CHAR_MAP = {
    "1": "I",
    "I": "1",
    "0": "O",
    "O": "0",
    "8": "B",
    "B": "8",
    "5": "S",
    "S": "5",
    "2": "Z",
    "Z": "2",
    "6": "G",
    "G": "6",
}


def _numeric_core(ref: str) -> str:
    """Extract the numeric core of a reference: strip alpha, leading/trailing zeros."""
    digits = re.sub(r"[^0-9]", "", ref)
    return digits.lstrip("0") or "0"


def _apply_ocr_normalization(ref: str) -> str:
    """Replace common OCR-error characters with their numeric equivalents."""
    out = []
    for ch in ref.upper():
        if ch in OCR_CHAR_MAP and not ch.isdigit():
            out.append(OCR_CHAR_MAP[ch])
        else:
            out.append(ch)
    return "".join(out)


# =============================================================================
# LEVENSHTEIN DISTANCE (pure Python, capped for performance)
# =============================================================================

def levenshtein_distance(s1: str, s2: str, max_dist: int = 5) -> int:
    """
    Compute Levenshtein distance between two strings.
    Returns early if distance exceeds max_dist (returns max_dist + 1).
    """
    len1, len2 = len(s1), len(s2)
    if abs(len1 - len2) > max_dist:
        return max_dist + 1

    if len1 > len2:
        s1, s2 = s2, s1
        len1, len2 = len2, len1

    prev_row = list(range(len1 + 1))
    for j in range(1, len2 + 1):
        curr_row = [j] + [0] * len1
        for i in range(1, len1 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            curr_row[i] = min(
                curr_row[i - 1] + 1,
                prev_row[i] + 1,
                prev_row[i - 1] + cost,
            )
        prev_row = curr_row
        if min(prev_row) > max_dist:
            return max_dist + 1
    return prev_row[len1]


def string_similarity(s1: str, s2: str) -> float:
    """Normalized string similarity: 1.0 = identical, 0.0 = completely different."""
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0
    max_len = max(len(s1), len(s2))
    dist = levenshtein_distance(s1, s2, max_dist=max_len)
    return max(0.0, 1.0 - dist / max_len)


# =============================================================================
# FUZZY MATCH SCORING
# =============================================================================

def compute_fuzzy_match(
    extracted_ref: str,
    candidate_ref: str,
) -> Dict[str, float]:
    """
    Compare two reference strings using multiple fuzzy strategies.

    Returns a breakdown dict with individual signal scores and a combined
    `fuzzy_score` (0.0–1.0).

    Signals:
        exact_normalized   – numeric cores match exactly
        partial_overlap    – one is a suffix/prefix of the other
        levenshtein_sim    – overall string similarity
        ocr_corrected      – match after OCR error correction
        numeric_core_match – digits-only comparison
    """
    if not extracted_ref or not candidate_ref:
        return {"fuzzy_score": 0.0}

    ext = extracted_ref.upper().strip()
    cand = candidate_ref.upper().strip()

    breakdown: Dict[str, float] = {}

    # 1. Exact normalized match (case-insensitive, stripped)
    if ext == cand:
        return {
            "fuzzy_score": 1.0,
            "exact_normalized": 1.0,
        }

    # 2. Numeric core comparison (ignore leading zeros, padding)
    ext_core = _numeric_core(ext)
    cand_core = _numeric_core(cand)

    # Only compare numeric cores if both strings actually contain digits
    ext_has_digits = bool(re.search(r"\d", ext))
    cand_has_digits = bool(re.search(r"\d", cand))

    if ext_has_digits and cand_has_digits and ext_core == cand_core and ext_core != "0":
        breakdown["numeric_core_match"] = 0.90
    elif ext_has_digits and cand_has_digits and ext_core and cand_core:
        # Partial numeric overlap: one is suffix/prefix of the other
        if ext_core.endswith(cand_core) or cand_core.endswith(ext_core):
            overlap_len = min(len(ext_core), len(cand_core))
            max_len = max(len(ext_core), len(cand_core))
            breakdown["partial_overlap"] = round(0.70 * (overlap_len / max_len), 4)
        elif ext_core.startswith(cand_core) or cand_core.startswith(ext_core):
            overlap_len = min(len(ext_core), len(cand_core))
            max_len = max(len(ext_core), len(cand_core))
            breakdown["partial_overlap"] = round(0.60 * (overlap_len / max_len), 4)

    # 3. OCR error correction
    ext_ocr = _apply_ocr_normalization(ext)
    cand_ocr = _apply_ocr_normalization(cand)
    if ext_ocr != ext or cand_ocr != cand:
        ocr_ext_core = _numeric_core(ext_ocr)
        ocr_cand_core = _numeric_core(cand_ocr)
        if ocr_ext_core == ocr_cand_core and ocr_ext_core != "0":
            breakdown["ocr_corrected"] = 0.80
        elif ext_ocr == cand_ocr:
            breakdown["ocr_corrected"] = 0.85

    # 4. Levenshtein similarity on the original strings
    sim = string_similarity(ext, cand)
    if sim >= 0.70:
        breakdown["levenshtein_sim"] = round(sim * 0.75, 4)

    # 5. Levenshtein on numeric cores
    if ext_has_digits and cand_has_digits and ext_core and cand_core and "numeric_core_match" not in breakdown:
        core_sim = string_similarity(ext_core, cand_core)
        if core_sim >= 0.75:
            breakdown["numeric_core_sim"] = round(core_sim * 0.65, 4)

    # Combined score: take the best individual signal
    if breakdown:
        best = max(breakdown.values())
        breakdown["fuzzy_score"] = round(min(best, 1.0), 4)
    else:
        breakdown["fuzzy_score"] = 0.0

    return breakdown


# =============================================================================
# CONTEXTUAL SIMILARITY
# =============================================================================

def compute_contextual_similarity(
    doc: Dict,
    bc_record: Dict,
) -> Tuple[float, Dict[str, float], str]:
    """
    Compute contextual similarity between a document and a BC record.

    Uses non-reference signals: vendor, customer, date proximity, amount.

    Returns: (score, breakdown, reasoning)
    """
    breakdown: Dict[str, float] = {}
    reasons = []

    # --- Vendor / Customer alignment ---
    doc_vendor = (
        doc.get("vendor_raw") or doc.get("matched_vendor_name") or ""
    ).lower().replace(" ", "")
    doc_customer = (doc.get("customer_name") or "").lower().replace(" ", "")

    bc_vendor = (
        bc_record.get("vendorName") or bc_record.get("vendor_name") or ""
    ).lower().replace(" ", "")
    bc_customer = (
        bc_record.get("customerName") or bc_record.get("customer_name") or ""
    ).lower().replace(" ", "")

    if doc_vendor and bc_vendor:
        if doc_vendor in bc_vendor or bc_vendor in doc_vendor:
            breakdown["ctx_vendor_match"] = 0.30
            reasons.append("Vendor name match")
    if doc_vendor and bc_customer:
        if doc_vendor in bc_customer or bc_customer in doc_vendor:
            breakdown["ctx_customer_match"] = 0.20
            reasons.append("Customer alignment")
    if doc_customer and bc_customer:
        if doc_customer in bc_customer or bc_customer in doc_customer:
            breakdown.setdefault("ctx_customer_match", 0)
            breakdown["ctx_customer_match"] = max(breakdown["ctx_customer_match"], 0.25)
            reasons.append("Customer name match")

    # --- Date proximity ---
    doc_date_str = (
        doc.get("invoice_date") or doc.get("document_date") or doc.get("received_at")
    )
    bc_date_str = (
        bc_record.get("postingDate") or bc_record.get("orderDate")
        or bc_record.get("documentDate") or bc_record.get("posting_date")
    )
    if doc_date_str and bc_date_str:
        try:
            from datetime import datetime as dt
            doc_date = dt.fromisoformat(str(doc_date_str).replace("Z", "+00:00").split("T")[0])
            bc_date = dt.fromisoformat(str(bc_date_str).replace("Z", "+00:00").split("T")[0])
            days = abs((doc_date - bc_date).days)
            if days <= 3:
                breakdown["ctx_date_proximity"] = 0.25
                reasons.append(f"Date: {days}d apart (strong)")
            elif days <= 7:
                breakdown["ctx_date_proximity"] = 0.20
                reasons.append(f"Date: {days}d apart")
            elif days <= 14:
                breakdown["ctx_date_proximity"] = 0.10
                reasons.append(f"Date: {days}d apart (moderate)")
            elif days <= 30:
                breakdown["ctx_date_proximity"] = 0.05
                reasons.append(f"Date: {days}d apart (weak)")
        except (ValueError, TypeError):
            pass

    # --- Amount proximity ---
    doc_amount = _parse_amount(doc.get("total_amount") or doc.get("invoice_amount"))
    bc_amount = _parse_amount(
        bc_record.get("totalAmountIncludingTax")
        or bc_record.get("totalAmount")
        or bc_record.get("amount")
    )
    if doc_amount and bc_amount and doc_amount > 0 and bc_amount > 0:
        ratio = min(doc_amount, bc_amount) / max(doc_amount, bc_amount)
        if ratio >= 0.95:
            breakdown["ctx_amount_match"] = 0.20
            reasons.append(f"Amount match: {ratio:.0%}")
        elif ratio >= 0.85:
            breakdown["ctx_amount_match"] = 0.10
            reasons.append(f"Amount close: {ratio:.0%}")

    score = min(sum(breakdown.values()), 0.50)  # cap contextual at 0.50
    breakdown["contextual_score"] = round(score, 4)
    reasoning = "; ".join(reasons) if reasons else "No contextual signals"

    return score, breakdown, reasoning


def _parse_amount(val) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = re.sub(r"[^\d.]", "", str(val))
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None
