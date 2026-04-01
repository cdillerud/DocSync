"""
GPI Document Hub — Document Boundary Detection Service

Analyzes multi-page PDFs to detect where one logical document ends
and another begins.  Uses lightweight text heuristics (no LLM calls)
to find boundaries, then groups contiguous pages into logical documents.

Signals used for boundary detection:
  - Vendor name changes between pages
  - Invoice / PO / BOL number changes
  - Date changes
  - Page header patterns (letterhead, "INVOICE", "BILL OF LADING")
  - Blank or near-blank pages (separator sheets)

Result: a list of page groups, each representing one logical document.
"""

import io
import re
import logging
from typing import List, Dict, Any, Optional
from collections import defaultdict

from pypdf import PdfReader

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# PAGE TEXT EXTRACTION
# ═══════════════════════════════════════════════════════════════

def extract_page_texts(file_content: bytes) -> List[Dict[str, Any]]:
    """Extract text from each page of a PDF.
    
    Returns list of {page_num, text, char_count, line_count}.
    """
    reader = PdfReader(io.BytesIO(file_content))
    pages = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append({
            "page_num": i + 1,
            "text": text,
            "char_count": len(text),
            "line_count": text.count("\n") + 1 if text else 0,
        })
    return pages


# ═══════════════════════════════════════════════════════════════
# PAGE FINGERPRINTING
# ═══════════════════════════════════════════════════════════════

# Patterns that indicate a new document is starting
_DOCUMENT_START_PATTERNS = [
    re.compile(r"\b(INVOICE|CREDIT\s+MEMO|DEBIT\s+NOTE)\s*(#|NO|NUMBER|NUM)?[\s.:]*\w", re.IGNORECASE),
    re.compile(r"\b(BILL\s+OF\s+LADING|BOL|B/L)\s*(#|NO|NUMBER)?[\s.:]*\w", re.IGNORECASE),
    re.compile(r"\b(PURCHASE\s+ORDER|P\.?O\.?)\s*(#|NO|NUMBER)?[\s.:]*\d", re.IGNORECASE),
    re.compile(r"\b(PACKING\s+(SLIP|LIST))\b", re.IGNORECASE),
    re.compile(r"\b(REMITTANCE\s+ADVICE)\b", re.IGNORECASE),
    re.compile(r"\b(STATEMENT\s+OF\s+ACCOUNT)\b", re.IGNORECASE),
    re.compile(r"\b(SHIPPING\s+(NOTICE|DOCUMENT|MANIFEST))\b", re.IGNORECASE),
]

# Extract invoice/PO/BOL numbers
_REF_NUMBER_PATTERNS = [
    ("invoice_no", re.compile(r"(?:INVOICE|INV)[\s#.:]*([A-Z0-9][\w-]{2,20})", re.IGNORECASE)),
    ("po_no", re.compile(r"(?:P\.?\s*O\.?\s*#|PURCHASE\s+ORDER\s*#?)\s*:?\s*([A-Z0-9][\w-]{2,20})", re.IGNORECASE)),
    ("bol_no", re.compile(r"(?:BOL|B/L|BILL\s+OF\s+LADING)[\s#.:]*([A-Z0-9][\w-]{2,20})", re.IGNORECASE)),
]

# Date patterns
_DATE_PATTERN = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*[\s.,]+\d{1,2}[\s.,]+\d{2,4})\b",
    re.IGNORECASE
)

# Common vendor name indicators (top of page)
_VENDOR_HEADER_ZONE_LINES = 8  # Look at first N lines for vendor/company name


def fingerprint_page(page: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze a single page's text to extract document identity signals."""
    text = page["text"]
    top_text = "\n".join(text.split("\n")[:_VENDOR_HEADER_ZONE_LINES])

    fp = {
        "page_num": page["page_num"],
        "is_blank": page["char_count"] < 30,
        "is_separator": _is_separator_page(text, page["char_count"]),
        "doc_type_hints": [],
        "ref_numbers": {},
        "dates": [],
        "top_text_hash": hash(top_text.strip().lower()[:200]),
        "has_letterhead": False,
        "vendor_hint": "",
    }

    if fp["is_blank"]:
        return fp

    # Document type hints from header patterns
    for pattern in _DOCUMENT_START_PATTERNS:
        m = pattern.search(text[:500])  # Check first 500 chars
        if m:
            fp["doc_type_hints"].append(m.group(0).strip())

    # Reference numbers
    for ref_type, pattern in _REF_NUMBER_PATTERNS:
        m = pattern.search(text)
        if m:
            fp["ref_numbers"][ref_type] = m.group(1).strip()

    # Dates (first 3 found)
    dates = _DATE_PATTERN.findall(text[:800])
    fp["dates"] = dates[:3]

    # Vendor hint — look for company names in top lines
    fp["vendor_hint"] = _extract_vendor_hint(top_text)

    # Letterhead detection — if top lines have a strong header pattern
    fp["has_letterhead"] = bool(fp["doc_type_hints"]) or _has_letterhead(top_text)

    return fp


def _is_separator_page(text: str, char_count: int) -> bool:
    """Detect separator/blank pages inserted between documents."""
    if char_count < 30:
        return True
    text_lower = text.strip().lower()
    if text_lower in ("", "this page intentionally left blank", "separator"):
        return True
    # Page with only a few short lines (like a fax cover)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) <= 2 and char_count < 100:
        return True
    return False


def _extract_vendor_hint(top_text: str) -> str:
    """Try to extract a company/vendor name from the top of the page.
    
    Heuristic: the first non-blank line that looks like a company name
    (contains Corp, Inc, LLC, Ltd, Co., etc. or is in ALL CAPS).
    """
    company_suffixes = re.compile(
        r"\b(Inc|Corp|LLC|Ltd|Co|Company|Corporation|Incorporated|"
        r"Industries|Manufacturing|Enterprises|Services|Group|International)\b\.?",
        re.IGNORECASE
    )

    for line in top_text.split("\n"):
        line = line.strip()
        if not line or len(line) < 3:
            continue
        # Check for company suffix
        if company_suffixes.search(line):
            return line[:80]
        # Check for ALL CAPS line (common in letterheads)
        if line.isupper() and len(line) > 5 and len(line) < 60 and line.isalpha() is False:
            return line[:80]

    return ""


def _has_letterhead(top_text: str) -> bool:
    """Detect if the top of the page has letterhead characteristics."""
    lines = [l.strip() for l in top_text.split("\n") if l.strip()]
    if not lines:
        return False
    # Letterhead: first line is company name (often caps or contains phone/address)
    first = lines[0]
    if len(first) > 5 and (first.isupper() or re.search(r"\d{3}[-.)]\d{3}", first)):
        return True
    # Check for address pattern in first few lines
    for line in lines[:4]:
        if re.search(r"\b\d{5}(-\d{4})?\b", line):  # ZIP code
            return True
        if re.search(r"\b(phone|tel|fax|email)\b", line, re.IGNORECASE):
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# BOUNDARY DETECTION
# ═══════════════════════════════════════════════════════════════

def detect_boundaries(fingerprints: List[Dict]) -> List[int]:
    """Detect document boundaries from page fingerprints.
    
    Returns a list of page numbers where new documents START (1-indexed).
    Page 1 is always a boundary (start of first document).
    
    Example: [1, 4, 7] means pages 1-3 are doc 1, pages 4-6 are doc 2, pages 7+ are doc 3.
    """
    if len(fingerprints) <= 1:
        return [1]

    boundaries = [1]  # First page always starts a document

    for i in range(1, len(fingerprints)):
        prev = fingerprints[i - 1]
        curr = fingerprints[i]

        # Skip blank/separator pages — they ARE boundaries
        if curr["is_separator"] or curr["is_blank"]:
            continue
        if prev["is_separator"] or prev["is_blank"]:
            # Page after a separator is a new document
            boundaries.append(curr["page_num"])
            continue

        # Score how likely this is a new document (0 = same doc, higher = new doc)
        boundary_score = 0
        reasons = []

        # Signal 1: Vendor name changed
        if prev["vendor_hint"] and curr["vendor_hint"]:
            if _vendor_names_differ(prev["vendor_hint"], curr["vendor_hint"]):
                boundary_score += 3
                reasons.append("vendor_changed")

        # Signal 2: Reference number changed
        for ref_type in ("invoice_no", "po_no", "bol_no"):
            prev_ref = prev["ref_numbers"].get(ref_type, "")
            curr_ref = curr["ref_numbers"].get(ref_type, "")
            if prev_ref and curr_ref and prev_ref != curr_ref:
                boundary_score += 3
                reasons.append(f"{ref_type}_changed")
                break

        # Signal 3: New letterhead / doc type header — but ONLY if vendor or ref also changed
        # (A multi-page invoice will have the same letterhead on every page)
        if curr["has_letterhead"] and curr["doc_type_hints"]:
            vendor_same = (prev["vendor_hint"] and curr["vendor_hint"]
                          and not _vendor_names_differ(prev["vendor_hint"], curr["vendor_hint"]))
            refs_same = _refs_match(prev["ref_numbers"], curr["ref_numbers"])
            if not vendor_same or not refs_same:
                boundary_score += 2
                reasons.append("new_header_different_entity")

        # Signal 4: Top-of-page text is very different AND previous page had no letterhead
        # (transition from non-letterhead page to letterhead page)
        if prev["top_text_hash"] != curr["top_text_hash"]:
            if curr["has_letterhead"] and not prev["has_letterhead"]:
                boundary_score += 2
                reasons.append("letterhead_transition")

        # Signal 5: Document type hints differ
        prev_types = set(h.split()[0].upper() for h in prev.get("doc_type_hints", []))
        curr_types = set(h.split()[0].upper() for h in curr.get("doc_type_hints", []))
        if prev_types and curr_types and prev_types != curr_types:
            boundary_score += 2
            reasons.append("doc_type_changed")

        # Threshold: score >= 2 means this is likely a new document
        if boundary_score >= 2:
            boundaries.append(curr["page_num"])
            logger.debug("[Boundary] Page %d: NEW DOCUMENT (score=%d, reasons=%s)",
                        curr["page_num"], boundary_score, reasons)

    return sorted(set(boundaries))


def _vendor_names_differ(a: str, b: str) -> bool:
    """Compare two vendor name hints, accounting for minor variations."""
    a_norm = re.sub(r"[^a-z0-9]", "", a.lower())
    b_norm = re.sub(r"[^a-z0-9]", "", b.lower())
    if not a_norm or not b_norm:
        return False
    # If one is a substring of the other, they're the same vendor
    if a_norm in b_norm or b_norm in a_norm:
        return False
    # Simple character overlap check
    overlap = len(set(a_norm) & set(b_norm)) / max(len(set(a_norm)), len(set(b_norm)))
    return overlap < 0.7


def _refs_match(refs_a: Dict, refs_b: Dict) -> bool:
    """Check if two pages have matching reference numbers.
    
    Returns True if they share at least one common ref type with the same value,
    or if neither page has any refs (ambiguous → assume same doc).
    """
    if not refs_a and not refs_b:
        return True  # No refs on either page → can't tell, assume same doc
    
    for ref_type in ("invoice_no", "po_no", "bol_no"):
        a_val = refs_a.get(ref_type, "")
        b_val = refs_b.get(ref_type, "")
        if a_val and b_val:
            if a_val == b_val:
                return True  # Same ref → same doc
            else:
                return False  # Different ref → different doc
    
    return True  # No overlapping ref types → ambiguous, assume same


# ═══════════════════════════════════════════════════════════════
# PAGE GROUPING
# ═══════════════════════════════════════════════════════════════

def group_pages(page_texts: List[Dict], boundaries: List[int]) -> List[Dict[str, Any]]:
    """Group pages into logical documents based on detected boundaries.
    
    Returns list of groups:
    [
        {"group_num": 1, "pages": [1, 2, 3], "vendor_hint": "...", "doc_type_hint": "..."},
        {"group_num": 2, "pages": [4], "vendor_hint": "...", "doc_type_hint": "..."},
    ]
    """
    if not boundaries:
        boundaries = [1]

    total_pages = len(page_texts)
    groups = []

    for i, start_page in enumerate(boundaries):
        end_page = boundaries[i + 1] - 1 if i + 1 < len(boundaries) else total_pages
        pages_in_group = list(range(start_page, end_page + 1))

        # Filter out blank/separator pages
        non_blank = [p for p in pages_in_group
                     if page_texts[p - 1]["char_count"] >= 30]

        if not non_blank:
            continue  # Skip groups that are all blank pages

        # Get fingerprint info from the first page of the group
        first_page = page_texts[non_blank[0] - 1]
        fp = fingerprint_page(first_page)

        group = {
            "group_num": len(groups) + 1,
            "pages": non_blank,
            "page_range": f"{non_blank[0]}-{non_blank[-1]}" if len(non_blank) > 1 else str(non_blank[0]),
            "page_count": len(non_blank),
            "vendor_hint": fp.get("vendor_hint", ""),
            "doc_type_hints": fp.get("doc_type_hints", []),
            "ref_numbers": fp.get("ref_numbers", {}),
        }
        groups.append(group)

    return groups


# ═══════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def analyze_document_boundaries(file_content: bytes) -> Dict[str, Any]:
    """Full boundary analysis on a multi-page PDF.
    
    Returns:
    {
        "total_pages": 10,
        "should_split": True,
        "document_count": 3,
        "groups": [...],
        "boundaries": [1, 4, 7],
        "analysis": "10-page PDF contains 3 logical documents"
    }
    """
    try:
        page_texts = extract_page_texts(file_content)
    except Exception as e:
        logger.warning("[Boundary] Failed to read PDF: %s", e)
        return {"total_pages": 0, "should_split": False, "document_count": 0,
                "groups": [], "boundaries": [], "analysis": f"PDF read error: {e}"}

    total_pages = len(page_texts)

    if total_pages <= 1:
        return {
            "total_pages": total_pages,
            "should_split": False,
            "document_count": 1,
            "groups": [{"group_num": 1, "pages": [1], "page_count": 1}] if total_pages == 1 else [],
            "boundaries": [1] if total_pages == 1 else [],
            "analysis": "Single page document",
        }

    # Fingerprint all pages
    fingerprints = [fingerprint_page(p) for p in page_texts]

    # Detect boundaries
    boundaries = detect_boundaries(fingerprints)

    # Group pages
    groups = group_pages(page_texts, boundaries)

    should_split = len(groups) > 1
    analysis = (
        f"{total_pages}-page PDF contains {len(groups)} logical document(s)"
        if should_split else
        f"{total_pages}-page PDF appears to be a single document"
    )

    logger.info("[Boundary] %s — boundaries at pages %s", analysis, boundaries)

    return {
        "total_pages": total_pages,
        "should_split": should_split,
        "document_count": len(groups),
        "groups": groups,
        "boundaries": boundaries,
        "fingerprints": [
            {k: v for k, v in fp.items() if k != "top_text_hash"}
            for fp in fingerprints
        ],
        "analysis": analysis,
    }
