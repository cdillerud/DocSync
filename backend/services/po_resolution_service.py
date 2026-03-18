"""
GPI Document Hub - PO Resolution Service

Resolves Purchase Order numbers extracted from documents against Business Central.
Primary lookup: BC reference cache → live BC API fallback → local staging fallback.

Used by the document pipeline for Shipping_Document, Warehouse_Receipt,
and Freight_Document types to achieve real BC linkage.
"""

import re
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from deps import get_db

logger = logging.getLogger("po_resolution")

# Document types that require PO resolution for BC linkage
PO_REQUIRED_DOC_TYPES = frozenset({
    "Shipping_Document",
    "Warehouse_Receipt",
    "Freight_Document",
})

# Resolution statuses
STATUS_RESOLVED = "resolved"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_NOT_FOUND = "not_found"
STATUS_SKIPPED = "skipped"

# ─── PO Extraction ────────────────────────────────────────────────────────────

# Regex patterns for extracting PO numbers from raw text.
# Order matters — more specific patterns first.
_PO_PATTERNS = [
    # "Purchase Order 107346" / "Purchase Order: 107346"
    re.compile(r"Purchase\s+Order\s*[:#]?\s*(\S+)", re.IGNORECASE),
    # "PO.107459" / "PO #107346" / "PO: 107346" / "P.O. 107346"
    re.compile(r"P\.?O\.?\s*[:#]?\s*(\S+)", re.IGNORECASE),
    # "Customer PO 107346" / "Customer PO: 107346"
    re.compile(r"Customer\s+P\.?O\.?\s*[:#]?\s*(\S+)", re.IGNORECASE),
    # "Order No 107346" / "Order No: 107346" / "Order Number: 107346"
    re.compile(r"Order\s+(?:No|Number|#)\s*[:#]?\s*(\S+)", re.IGNORECASE),
    # Standalone 5-6 digit number on a line that looks like a reference
    re.compile(r"(?:^|\s)(\d{5,7})(?:\s|$)", re.MULTILINE),
]


def extract_po_candidates(text: str, existing_fields: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """Extract PO number candidates from raw text and existing extracted fields.

    Returns a list of {value, normalized, source, confidence} sorted by confidence desc.
    """
    candidates: List[Dict[str, Any]] = []
    seen_normalized = set()

    def _add(raw_value: str, source: str, confidence: float):
        norm = normalize_po(raw_value)
        if not norm or norm in seen_normalized:
            return
        seen_normalized.add(norm)
        candidates.append({
            "value": raw_value.strip(),
            "normalized": norm,
            "source": source,
            "confidence": round(confidence, 3),
        })

    # From existing extracted fields (highest confidence — LLM or heuristic output)
    if existing_fields:
        for field_name in ("po_number", "purchase_order_number", "customer_po"):
            val = existing_fields.get(field_name)
            if val and str(val).strip():
                # Handle comma-separated POs (e.g., "PO.107459,107460")
                for part in str(val).split(","):
                    part = part.strip()
                    if part:
                        _add(part, f"extracted_field:{field_name}", 0.90)

        # order_number can also be a PO for shipping docs
        order = existing_fields.get("order_number")
        if order and str(order).strip():
            _add(str(order), "extracted_field:order_number", 0.80)

    # From raw text via regex
    if text:
        for pattern in _PO_PATTERNS:
            for match in pattern.finditer(text[:5000]):
                raw = match.group(1).strip()
                if len(raw) >= 3:  # Skip very short matches
                    _add(raw, f"regex:{pattern.pattern[:30]}", 0.70)

    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates


def normalize_po(raw: str) -> str:
    """Normalize a PO value for matching against BC cache.

    Strategy:
    - Strip whitespace
    - Remove label noise: PO, P.O., Purchase Order, #
    - Uppercase
    - Preserve hyphens and alphanumeric chars (BC may use alphanumeric POs)
    - If result is purely numeric, strip leading zeros
    """
    if not raw:
        return ""
    s = str(raw).strip()

    # Remove common label prefixes
    s = re.sub(r"^(?:Purchase\s*Order|P\.?O\.?)\s*[:#]?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^#\s*", "", s)

    # Strip surrounding whitespace
    s = s.strip()

    # Remove characters that are never part of a PO number
    # Keep: alphanumeric, hyphens, dots (some PO formats use them)
    s = re.sub(r"[^\w\-.]", "", s)

    # Uppercase
    s = s.upper()

    # If purely numeric, strip leading zeros but keep at least 1 digit
    if s.isdigit():
        s = s.lstrip("0") or "0"

    return s


# ─── PO Resolution ────────────────────────────────────────────────────────────

async def resolve_po(
    po_candidates: List[Dict[str, Any]],
    vendor_name: str = "",
    vendor_no: str = "",
    doc_type: str = "",
    document_id: str = "",
) -> Dict[str, Any]:
    """Resolve PO candidates against BC.

    Lookup order:
    1. BC reference cache (exact + normalized)
    2. Live BC API fallback
    3. Local staging collections (po_drafts) as final fallback

    Returns the canonical po_resolution object.
    """
    db = get_db()
    result = _empty_result(document_id, doc_type)

    if not po_candidates:
        logger.info("[PO_RESOLUTION] doc=%s No PO candidates to resolve", document_id[:12])
        result["status"] = STATUS_NOT_FOUND
        result["reason"] = "no_po_candidates"
        return result

    logger.info(
        "[PO_RESOLUTION] doc=%s Resolving %d candidates: %s",
        document_id[:12],
        len(po_candidates),
        [c["normalized"] for c in po_candidates[:5]],
    )

    all_matches: List[Dict[str, Any]] = []

    for candidate in po_candidates[:10]:  # Cap at 10 candidates
        normalized = candidate["normalized"]
        if not normalized:
            continue

        # ── Step 1: BC Reference Cache (fast, local) ──
        cache_matches = await _search_bc_cache(db, normalized, vendor_no, vendor_name)
        for cm in cache_matches:
            cm["po_candidate"] = candidate
            cm["lookup_source"] = "bc_cache"
            all_matches.append(cm)
            logger.info(
                "[PO_RESOLUTION] doc=%s CACHE HIT: candidate=%s → BC PO %s vendor=%s confidence=%.2f",
                document_id[:12], normalized, cm["bc_document_no"], cm.get("bc_vendor_name", ""), cm["confidence"],
            )

        # ── Step 2: Live BC API fallback (if no cache hit) ──
        if not cache_matches:
            bc_matches = await _search_bc_api(normalized, document_id)
            for bm in bc_matches:
                bm["po_candidate"] = candidate
                bm["lookup_source"] = "bc_api"
                all_matches.append(bm)
                logger.info(
                    "[PO_RESOLUTION] doc=%s BC API HIT: candidate=%s → PO %s",
                    document_id[:12], normalized, bm["bc_document_no"],
                )

        # ── Step 3: Local staging fallback ──
        if not cache_matches and not [m for m in all_matches if m.get("po_candidate") == candidate]:
            local_matches = await _search_local_staging(db, normalized)
            for lm in local_matches:
                lm["po_candidate"] = candidate
                lm["lookup_source"] = "local_staging"
                all_matches.append(lm)
                logger.info(
                    "[PO_RESOLUTION] doc=%s LOCAL HIT: candidate=%s → %s",
                    document_id[:12], normalized, lm.get("entity_id", ""),
                )

    if not all_matches:
        logger.warning(
            "[PO_RESOLUTION] doc=%s NOT FOUND: tried %d candidates against BC cache (%d POs), BC API, local staging",
            document_id[:12], len(po_candidates),
            await db.bc_reference_cache.count_documents({"bc_entity_type": "purchase_order"}),
        )
        result["status"] = STATUS_NOT_FOUND
        result["reason"] = "no_bc_match"
        result["candidates_tried"] = [c["normalized"] for c in po_candidates[:5]]
        return result

    # Deduplicate and rank
    all_matches.sort(key=lambda m: m["confidence"], reverse=True)
    best = all_matches[0]

    # Check for ambiguity: multiple distinct BC records with similar confidence
    distinct_po_nos = {m["bc_document_no"] for m in all_matches if m.get("bc_document_no")}
    if len(distinct_po_nos) > 1 and len(all_matches) > 1:
        # Multiple POs from SAME vendor is normal (multi-PO shipment) — not ambiguous
        distinct_vendors = {m.get("bc_vendor_no") or m.get("bc_vendor_name", "") for m in all_matches if m.get("bc_document_no")}
        distinct_vendors.discard("")
        second = all_matches[1]
        if len(distinct_vendors) > 1 and second["bc_document_no"] != best["bc_document_no"] and second["confidence"] >= 0.70:
            result["status"] = STATUS_AMBIGUOUS
            result["reason"] = f"multiple_po_matches: {len(distinct_po_nos)} distinct POs from {len(distinct_vendors)} vendors"
            result["matches"] = all_matches[:5]
            result["best_match"] = _format_match(best)
            logger.warning(
                "[PO_RESOLUTION] doc=%s AMBIGUOUS: %d distinct POs from %d vendors",
                document_id[:12], len(distinct_po_nos), len(distinct_vendors),
            )
            return result
        elif len(distinct_vendors) <= 1:
            # Same vendor, multiple POs — resolve to the first (highest confidence)
            logger.info(
                "[PO_RESOLUTION] doc=%s Multi-PO shipment: %d POs from same vendor (%s), using first: %s",
                document_id[:12], len(distinct_po_nos),
                best.get("bc_vendor_name", ""), best.get("bc_document_no", ""),
            )

    # Single clear winner
    result["status"] = STATUS_RESOLVED
    result["po_number"] = best.get("bc_document_no", best.get("entity_id", ""))
    result["bc_record_id"] = best.get("bc_record_id", "")
    result["confidence"] = best["confidence"]
    result["match_method"] = best.get("match_method", "unknown")
    result["lookup_source"] = best.get("lookup_source", "")
    result["bc_vendor_no"] = best.get("bc_vendor_no", "")
    result["bc_vendor_name"] = best.get("bc_vendor_name", "")
    result["bc_status"] = best.get("bc_status", "")
    result["best_match"] = _format_match(best)
    result["matches"] = all_matches[:5]

    logger.info(
        "[PO_RESOLUTION] doc=%s RESOLVED: PO=%s bc_id=%s confidence=%.2f method=%s source=%s",
        document_id[:12], result["po_number"], result["bc_record_id"][:12] if result["bc_record_id"] else "-",
        result["confidence"], result["match_method"], result["lookup_source"],
    )

    return result


# ─── BC Cache Search ──────────────────────────────────────────────────────────

async def _search_bc_cache(
    db, normalized_po: str, vendor_no: str = "", vendor_name: str = ""
) -> List[Dict[str, Any]]:
    """Search the BC reference cache for a PO number.
    Returns scored matches.
    """
    matches = []

    # Exact match on document number
    query = {
        "bc_entity_type": "purchase_order",
        "$or": [
            {"normalized_document_no": normalized_po},
            {"bc_document_no": normalized_po},
        ],
    }
    cache_hits = await db.bc_reference_cache.find(query, {"_id": 0}).to_list(10)

    for hit in cache_hits:
        confidence = 0.95  # Exact cache match
        method = "bc_cache_exact"

        # Boost confidence if vendor also matches
        if vendor_no and hit.get("bc_vendor_no") == vendor_no:
            confidence = min(1.0, confidence + 0.05)
            method = "bc_cache_exact+vendor_no"
        elif vendor_name and hit.get("bc_vendor_name"):
            from services.reference_helpers import fuzzy_ratio, normalize_text
            v_score = fuzzy_ratio(vendor_name, hit["bc_vendor_name"], normalizer=normalize_text)
            if v_score >= 0.80:
                confidence = min(1.0, confidence + 0.03)
                method = f"bc_cache_exact+vendor_fuzzy({v_score:.0%})"

        matches.append({
            **hit,
            "confidence": confidence,
            "match_method": method,
        })

    # If no exact match, try partial/suffix match (last N digits)
    if not matches and len(normalized_po) >= 4:
        suffix = normalized_po[-5:] if len(normalized_po) >= 5 else normalized_po
        fuzzy_query = {
            "bc_entity_type": "purchase_order",
            "normalized_document_no": {"$regex": f"{re.escape(suffix)}$"},
        }
        fuzzy_hits = await db.bc_reference_cache.find(fuzzy_query, {"_id": 0}).limit(5).to_list(5)
        for hit in fuzzy_hits:
            matches.append({
                **hit,
                "confidence": 0.65,
                "match_method": f"bc_cache_suffix({suffix})",
            })

    return matches


# ─── Live BC API Search ───────────────────────────────────────────────────────

async def _search_bc_api(normalized_po: str, document_id: str) -> List[Dict[str, Any]]:
    """Fallback: search live BC API for a purchase order by number."""
    try:
        from services.business_central_service import get_bc_service
        svc = get_bc_service()
        po = await svc.find_purchase_order_by_number(normalized_po)
        if po:
            logger.info(
                "[PO_RESOLUTION] doc=%s BC API found PO: %s (vendor=%s)",
                document_id[:12], po.get("number", ""), po.get("vendorName", ""),
            )
            return [{
                "bc_record_id": po.get("id", ""),
                "bc_document_no": po.get("number", ""),
                "bc_vendor_no": po.get("vendorNumber", ""),
                "bc_vendor_name": po.get("vendorName", ""),
                "bc_status": po.get("status", ""),
                "bc_posting_date": po.get("orderDate", ""),
                "confidence": 0.90,
                "match_method": "bc_api_exact",
            }]
    except Exception as e:
        logger.warning(
            "[PO_RESOLUTION] doc=%s BC API search failed for PO=%s: %s",
            document_id[:12], normalized_po, str(e),
        )
    return []


# ─── Local Staging Fallback ───────────────────────────────────────────────────

async def _search_local_staging(db, normalized_po: str) -> List[Dict[str, Any]]:
    """Final fallback: search local po_drafts and so_drafts."""
    matches = []

    # PO drafts
    po = await db.po_drafts.find_one(
        {"$or": [
            {"po_draft_id": {"$regex": f"^{re.escape(normalized_po)}$", "$options": "i"}},
            {"source_reference": {"$regex": f"^{re.escape(normalized_po)}$", "$options": "i"}},
        ]},
        {"_id": 0},
    )
    if po:
        matches.append({
            "entity_id": po.get("po_draft_id", ""),
            "bc_document_no": po.get("po_draft_id", ""),
            "bc_vendor_name": po.get("vendor_name", ""),
            "confidence": 0.60,
            "match_method": "local_po_draft",
        })

    # SO drafts (customer PO)
    so = await db.so_drafts.find_one(
        {"customer_po_number": {"$regex": f"^{re.escape(normalized_po)}$", "$options": "i"}},
        {"_id": 0},
    )
    if so:
        matches.append({
            "entity_id": so.get("so_draft_id", ""),
            "bc_document_no": so.get("so_draft_id", ""),
            "bc_vendor_name": so.get("customer_name", ""),
            "confidence": 0.55,
            "match_method": "local_so_draft",
        })

    return matches


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _empty_result(document_id: str, doc_type: str) -> Dict[str, Any]:
    return {
        "document_id": document_id,
        "doc_type": doc_type,
        "status": STATUS_SKIPPED,
        "po_number": None,
        "bc_record_id": None,
        "confidence": 0.0,
        "match_method": None,
        "lookup_source": None,
        "bc_vendor_no": None,
        "bc_vendor_name": None,
        "bc_status": None,
        "reason": None,
        "best_match": None,
        "matches": [],
        "candidates_tried": [],
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }


def _format_match(match: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "bc_document_no": match.get("bc_document_no", ""),
        "bc_record_id": match.get("bc_record_id", ""),
        "bc_vendor_no": match.get("bc_vendor_no", ""),
        "bc_vendor_name": match.get("bc_vendor_name", ""),
        "bc_status": match.get("bc_status", ""),
        "confidence": match.get("confidence", 0),
        "match_method": match.get("match_method", ""),
        "lookup_source": match.get("lookup_source", ""),
    }


def requires_po_resolution(doc_type: str) -> bool:
    """Check if a document type requires PO resolution."""
    return doc_type in PO_REQUIRED_DOC_TYPES
