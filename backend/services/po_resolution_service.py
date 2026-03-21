"""
GPI Document Hub - PO Resolution Service (v2 — Hardened)

Resolves Purchase Order numbers extracted from documents against Business Central.
Primary lookup: BC reference cache → live BC API fallback → local staging fallback.

Used by the document pipeline for Shipping_Document, Warehouse_Receipt,
and Freight_Document types to achieve real BC linkage.

Miss taxonomy: every unresolved case stores an explicit miss_reason for debugging.
BC link results are standardized and categorized.
"""

import re
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from deps import get_db

logger = logging.getLogger("po_resolution")

# ─── Constants ─────────────────────────────────────────────────────────────────

PO_REQUIRED_DOC_TYPES = frozenset({
    "Shipping_Document",
    "Warehouse_Receipt",
    "Freight_Document",
})

STATUS_RESOLVED = "resolved"
STATUS_RESOLVED_SHIPMENT = "resolved_shipment"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_NOT_FOUND = "not_found"
STATUS_SKIPPED = "skipped"

# Miss reasons (taxonomy)
MISS_NO_PO_EXTRACTED = "no_po_extracted"
MISS_NORMALIZED_EMPTY = "normalized_po_empty"
MISS_INVALID_FORMAT = "invalid_po_format"
MISS_CACHE_NO_MATCH = "cache_no_match"
MISS_LIVE_BC_NO_MATCH = "live_bc_no_match"
MISS_VENDOR_CONFLICT = "vendor_conflict"
MISS_MULTIPLE_BC = "multiple_bc_matches"
MISS_BC_LOOKUP_ERROR = "bc_lookup_error"
MISS_NO_BC_MATCH = "no_bc_match"

# BC link failure reasons
BC_LINK_RECORD_NOT_FOUND = "bc_record_not_found"
BC_LINK_AUTH_ERROR = "bc_auth_error"
BC_LINK_VALIDATION_ERROR = "bc_validation_error"
BC_LINK_NETWORK_ERROR = "network_error"
BC_LINK_SANDBOX_ONLY = "sandbox_only_path"
BC_LINK_UNKNOWN = "unknown_error"

# Valid BC PO format patterns (from real cache data analysis):
#   pure numeric: 100092, 109023 (5-6 digits)
#   W-prefix: W102008, W117397
#   WA-prefix: WA1848
#   WR-prefix: WR106124
#   PR-prefix: PR10088
#   T-prefix: T1126
#   WTR-prefix: WTR1012
#   Suffix variants: 104718B, 111597_1
_VALID_BC_PO_PATTERN = re.compile(
    r"^(?:"
    r"\d{4,7}"                     # pure numeric 4-7 digits
    r"|[A-Z]{1,3}\d{3,7}[A-Z]?"  # alpha prefix (1-3 letters) + digits + optional alpha suffix
    r"|\d{5,7}[A-Z_]\w{0,3}"     # digits + suffix letter/underscore
    r")$"
)

# Patterns that are clearly NOT POs (shipping references, BOL numbers, etc.)
_NON_PO_PATTERNS = [
    re.compile(r"^SI-", re.IGNORECASE),        # Shipping Invoice refs
    re.compile(r"^SSH-", re.IGNORECASE),       # SSH shipping refs
    re.compile(r"^SSZ-", re.IGNORECASE),       # SSZ shipping refs
    re.compile(r"^SHL", re.IGNORECASE),        # Shipping line refs
    re.compile(r"^YMJA", re.IGNORECASE),       # YMJA container refs
    re.compile(r"^MSKU", re.IGNORECASE),       # Container refs
    re.compile(r"^TCNU", re.IGNORECASE),       # Container refs
    re.compile(r"^TGBU", re.IGNORECASE),       # Container refs
    re.compile(r"^[A-Z]{4}\d{7}$"),            # Container number pattern
    re.compile(r"^\d{2}-\d{2}-\d{2}-\d+$"),   # Date-based refs
    re.compile(r"^INV-", re.IGNORECASE),       # Invoice refs
    re.compile(r"^BOL-", re.IGNORECASE),       # BOL refs
    re.compile(r"^CN\d{6}", re.IGNORECASE),    # CN container/consignment refs
]


# ─── PO Extraction ────────────────────────────────────────────────────────────

_PO_PATTERNS = [
    re.compile(r"Purchase\s+Order\s*[:#]?\s*(\S+)", re.IGNORECASE),
    re.compile(r"P\.?O\.?\s*[:#]?\s*(\S+)", re.IGNORECASE),
    re.compile(r"Customer\s+P\.?O\.?\s*[:#]?\s*(\S+)", re.IGNORECASE),
    re.compile(r"Order\s+(?:No|Number|#)\s*[:#]?\s*(\S+)", re.IGNORECASE),
    re.compile(r"(?:^|\s)(\d{5,7})(?:\s|$)", re.MULTILINE),
]


def extract_po_candidates(
    text: str,
    existing_fields: Dict[str, Any] = None,
    file_name: str = "",
) -> List[Dict[str, Any]]:
    """Extract PO number candidates from raw text, existing extracted fields,
    BOL number, and source filename.
    Returns a list of {value, normalized, source, confidence, valid_format} sorted by confidence desc.
    """
    candidates: List[Dict[str, Any]] = []
    seen_normalized = set()

    def _add(raw_value: str, source: str, confidence: float):
        norm = normalize_po(raw_value)
        if not norm or norm in seen_normalized:
            return
        seen_normalized.add(norm)
        is_valid = is_valid_po_format(norm)
        is_non_po = is_known_non_po(norm)
        # Downgrade confidence for non-PO patterns
        adj_confidence = 0.10 if is_non_po else (confidence if is_valid else confidence * 0.5)
        candidates.append({
            "value": raw_value.strip(),
            "normalized": norm,
            "source": source,
            "confidence": round(adj_confidence, 3),
            "valid_format": is_valid,
            "is_non_po": is_non_po,
        })

    if existing_fields:
        for field_name in ("po_number", "purchase_order_number", "customer_po"):
            val = existing_fields.get(field_name)
            if val and str(val).strip():
                for part in str(val).split(","):
                    part = part.strip()
                    if part:
                        _add(part, f"extracted_field:{field_name}", 0.90)

        order = existing_fields.get("order_number")
        if order and str(order).strip():
            _add(str(order), "extracted_field:order_number", 0.80)

        # BOL number often contains the real PO in shipping docs
        bol = existing_fields.get("bol_number")
        if bol and str(bol).strip():
            _add(str(bol).strip(), "extracted_field:bol_number", 0.75)

        # Description/subject/notes fields often contain PO references
        for desc_field in ("description", "subject", "notes", "remarks", "reference", "memo"):
            desc_val = existing_fields.get(desc_field)
            if desc_val and str(desc_val).strip():
                desc_text = str(desc_val).strip()
                # Run PO regex patterns against the description text
                for pattern in _PO_PATTERNS:
                    for match in pattern.finditer(desc_text[:2000]):
                        raw = match.group(1).strip()
                        if len(raw) >= 3:
                            _add(raw, f"extracted_field:{desc_field}", 0.72)

    # Extract PO-like tokens from file_name
    if file_name:
        _extract_from_filename(file_name, _add)

    if text:
        for pattern in _PO_PATTERNS:
            for match in pattern.finditer(text[:5000]):
                raw = match.group(1).strip()
                if len(raw) >= 3:
                    _add(raw, f"regex:{pattern.pattern[:30]}", 0.70)

    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates


# Regex for PO-like tokens inside filenames
_FILENAME_PO_PATTERNS = [
    # Explicit PO label in filename: PO_107459, PO-107459, PO107459
    re.compile(r"P\.?O\.?[\s_\-]?(\d{4,7}[A-Z]?)", re.IGNORECASE),
    # Alpha-prefix POs: W117397, WA1848, WR106124, PR10088, WTR1005A
    re.compile(r"\b([A-Z]{1,3}\d{4,7}[A-Z]?)\b"),
    # Standalone 5-7 digit numbers (common PO format)
    re.compile(r"(?:^|[_\-\s.])(\d{5,7})(?:[_\-\s.]|$)"),
]


def _extract_from_filename(file_name: str, add_fn) -> None:
    """Parse PO candidates from a document filename."""
    # Strip file extension
    base = re.sub(r"\.[a-zA-Z]{2,5}$", "", file_name)
    if not base:
        return

    # Try structured patterns first
    for pattern in _FILENAME_PO_PATTERNS:
        for match in pattern.finditer(base):
            raw = match.group(1).strip()
            if len(raw) >= 4:
                add_fn(raw, f"filename:{pattern.pattern[:30]}", 0.65)

    # Fallback: split on common delimiters and test each token
    tokens = re.split(r"[_\-\s.]+", base)
    for token in tokens:
        token = token.strip()
        if len(token) < 4 or len(token) > 10:
            continue
        norm = normalize_po(token)
        if norm and is_valid_po_format(norm) and not is_known_non_po(norm):
            add_fn(token, "filename:token_split", 0.60)


def normalize_po(raw: str) -> str:
    """Normalize a PO value for matching against BC cache.
    - Strip whitespace, remove label noise (PO, P.O., Purchase Order, #)
    - Uppercase, preserve hyphens and alphanumeric chars
    - If purely numeric, strip leading zeros but keep at least 1 digit
    """
    if not raw:
        return ""
    s = str(raw).strip()
    s = re.sub(r"^(?:Purchase\s*Order|P\.?O\.?)\s*[:#]?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^#\s*", "", s)
    s = s.strip()
    s = re.sub(r"[^\w\-.]", "", s)
    s = s.upper()
    if s.isdigit():
        s = s.lstrip("0") or "0"
    return s


def is_valid_po_format(normalized: str) -> bool:
    """Check if a normalized value matches known BC PO formats."""
    if not normalized:
        return False
    return bool(_VALID_BC_PO_PATTERN.match(normalized))


def is_known_non_po(normalized: str) -> bool:
    """Check if a normalized value is a known non-PO reference (shipping ref, container, etc.)."""
    if not normalized:
        return True
    for pattern in _NON_PO_PATTERNS:
        if pattern.match(normalized):
            return True
    return False


def requires_po_resolution(doc_type: str) -> bool:
    """Check if a document type requires PO resolution."""
    return doc_type in PO_REQUIRED_DOC_TYPES


# ─── Convenience: resolve from a full document dict ───────────────────────────

async def resolve_po_from_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    """High-level wrapper: extract PO candidates from a document dict and resolve.

    Merges doc-level metadata (email_subject, email_body) into extracted_fields
    so that `extract_po_candidates` can search subject/description text.
    Callers that already have pre-built candidates should use `resolve_po` directly.
    """
    extracted = dict(doc.get("extracted_fields") or {})

    # Merge top-level doc fields into extracted so regex scans them
    if doc.get("email_subject") and "subject" not in extracted:
        extracted["subject"] = doc["email_subject"]
    if doc.get("email_body") and "description" not in extracted:
        extracted["description"] = doc["email_body"]
    if doc.get("notes") and "notes" not in extracted:
        extracted["notes"] = doc["notes"]

    raw_text = doc.get("raw_text") or ""
    file_name = doc.get("file_name") or ""

    candidates = extract_po_candidates(raw_text, extracted, file_name=file_name)

    # Merge any candidates already persisted on the document
    existing_candidates = doc.get("po_candidates") or []
    if existing_candidates:
        seen = {c["normalized"] for c in candidates}
        for ec in existing_candidates:
            if isinstance(ec, dict) and ec.get("normalized") and ec["normalized"] not in seen:
                candidates.append(ec)
                seen.add(ec["normalized"])

    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
    doc_id = doc.get("id") or ""
    vendor_name = extracted.get("vendor") or extracted.get("shipper") or extracted.get("carrier") or ""
    vendor_no = extracted.get("vendor_no") or ""

    return await resolve_po(
        po_candidates=candidates,
        vendor_name=vendor_name,
        vendor_no=vendor_no,
        doc_type=doc_type,
        document_id=doc_id,
        source_filename=file_name,
    )


# ─── PO Resolution ────────────────────────────────────────────────────────────

async def resolve_po(
    po_candidates: List[Dict[str, Any]],
    vendor_name: str = "",
    vendor_no: str = "",
    doc_type: str = "",
    document_id: str = "",
    source_filename: str = "",
) -> Dict[str, Any]:
    """Resolve PO candidates against BC. Returns the canonical po_resolution object.
    Lookup order: BC cache → live BC API → local staging fallback.
    Every miss is explained with a miss_reason.
    """
    db = get_db()
    result = _empty_result(document_id, doc_type)
    result["source_filename"] = source_filename
    result["vendor_name"] = vendor_name
    result["vendor_no"] = vendor_no

    if not po_candidates:
        logger.info("[PO_RESOLUTION] doc=%s No PO candidates to resolve", document_id[:12])
        result["status"] = STATUS_NOT_FOUND
        result["miss_reason"] = MISS_NO_PO_EXTRACTED
        return result

    # Filter to valid-format candidates only for BC lookup; keep all for audit
    valid_candidates = [c for c in po_candidates if c.get("valid_format") and not c.get("is_non_po")]
    result["candidates_raw"] = [c["normalized"] for c in po_candidates]
    result["candidates_valid"] = [c["normalized"] for c in valid_candidates]

    if not valid_candidates:
        logger.info(
            "[PO_RESOLUTION] doc=%s All %d candidates invalid format or non-PO: %s",
            document_id[:12], len(po_candidates), [c["normalized"] for c in po_candidates],
        )
        result["status"] = STATUS_NOT_FOUND
        result["miss_reason"] = MISS_INVALID_FORMAT
        result["candidates_tried"] = [c["normalized"] for c in po_candidates]
        return result

    logger.info(
        "[PO_RESOLUTION] doc=%s Resolving %d valid candidates (of %d total): %s",
        document_id[:12], len(valid_candidates), len(po_candidates),
        [c["normalized"] for c in valid_candidates[:5]],
    )

    all_matches: List[Dict[str, Any]] = []
    lookup_trace: List[Dict[str, Any]] = []  # Audit trail for every lookup

    for candidate in valid_candidates[:10]:
        normalized = candidate["normalized"]
        if not normalized:
            continue

        trace_entry = {"candidate": normalized, "lookups": []}

        # ── Step 1: BC Reference Cache — Purchase Orders (fast, local) ──
        cache_matches = await _search_bc_cache(db, normalized, vendor_no, vendor_name)
        trace_entry["lookups"].append({
            "source": "bc_cache", "query": normalized,
            "hits": len(cache_matches),
            "result": [m.get("bc_document_no") for m in cache_matches][:3],
        })
        for cm in cache_matches:
            cm["po_candidate"] = candidate
            cm["lookup_source"] = "bc_cache"
            all_matches.append(cm)
            logger.info(
                "[PO_RESOLUTION] doc=%s CACHE HIT: candidate=%s -> BC PO %s vendor=%s confidence=%.2f method=%s",
                document_id[:12], normalized, cm["bc_document_no"],
                cm.get("bc_vendor_name", ""), cm["confidence"], cm.get("match_method", ""),
            )

        # ── Step 1.5: BC Cache — Posted Sales Shipments (fallback) ──
        if not cache_matches:
            shipment_matches = await _search_bc_cache_shipments(db, normalized)
            trace_entry["lookups"].append({
                "source": "bc_cache_shipment", "query": normalized,
                "hits": len(shipment_matches),
                "result": [m.get("bc_document_no") for m in shipment_matches][:3],
            })
            for sm in shipment_matches:
                sm["po_candidate"] = candidate
                sm["lookup_source"] = "bc_cache_shipment"
                all_matches.append(sm)
                logger.info(
                    "[PO_RESOLUTION] doc=%s SHIPMENT HIT: candidate=%s -> Shipment %s customer=%s order=%s",
                    document_id[:12], normalized, sm["bc_document_no"],
                    sm.get("bc_customer_name", ""), sm.get("bc_order_number", ""),
                )

        # ── Step 2: Live BC API fallback (if no cache hit) ──
        if not cache_matches:
            bc_matches, bc_error = await _search_bc_api(normalized, document_id)
            trace_entry["lookups"].append({
                "source": "bc_api", "query": normalized,
                "hits": len(bc_matches),
                "error": bc_error,
            })
            for bm in bc_matches:
                bm["po_candidate"] = candidate
                bm["lookup_source"] = "bc_api"
                all_matches.append(bm)
                logger.info(
                    "[PO_RESOLUTION] doc=%s BC API HIT: candidate=%s -> PO %s",
                    document_id[:12], normalized, bm["bc_document_no"],
                )

        # ── Step 3: Local staging fallback ──
        if not cache_matches and not [m for m in all_matches if m.get("po_candidate") == candidate]:
            local_matches = await _search_local_staging(db, normalized)
            trace_entry["lookups"].append({
                "source": "local_staging", "query": normalized,
                "hits": len(local_matches),
            })
            for lm in local_matches:
                lm["po_candidate"] = candidate
                lm["lookup_source"] = "local_staging"
                all_matches.append(lm)
                logger.info(
                    "[PO_RESOLUTION] doc=%s LOCAL HIT: candidate=%s -> %s",
                    document_id[:12], normalized, lm.get("entity_id", ""),
                )

        lookup_trace.append(trace_entry)

    result["lookup_trace"] = lookup_trace

    if not all_matches:
        # Determine specific miss reason
        had_bc_errors = any(
            lu.get("error") for te in lookup_trace for lu in te.get("lookups", [])
            if lu.get("source") == "bc_api"
        )
        if had_bc_errors:
            miss_reason = MISS_BC_LOOKUP_ERROR
        else:
            miss_reason = MISS_NO_BC_MATCH

        po_cache_count = await db.bc_reference_cache.count_documents({"bc_entity_type": "purchase_order"})
        logger.warning(
            "[PO_RESOLUTION] doc=%s NOT FOUND (reason=%s): tried %d valid candidates against BC cache (%d POs), BC API, local staging",
            document_id[:12], miss_reason, len(valid_candidates), po_cache_count,
        )
        result["status"] = STATUS_NOT_FOUND
        result["miss_reason"] = miss_reason
        result["candidates_tried"] = [c["normalized"] for c in valid_candidates[:5]]
        return result

    # Deduplicate and rank
    all_matches.sort(key=lambda m: m["confidence"], reverse=True)
    best = all_matches[0]

    # Check for ambiguity
    distinct_po_nos = {m["bc_document_no"] for m in all_matches if m.get("bc_document_no")}
    if len(distinct_po_nos) > 1 and len(all_matches) > 1:
        distinct_vendors = {m.get("bc_vendor_no") or m.get("bc_vendor_name", "") for m in all_matches if m.get("bc_document_no")}
        distinct_vendors.discard("")
        second = all_matches[1]
        if len(distinct_vendors) > 1 and second["bc_document_no"] != best["bc_document_no"] and second["confidence"] >= 0.70:
            result["status"] = STATUS_AMBIGUOUS
            result["miss_reason"] = MISS_VENDOR_CONFLICT if len(distinct_vendors) > 1 else MISS_MULTIPLE_BC
            result["reason"] = f"multiple_po_matches: {len(distinct_po_nos)} POs from {len(distinct_vendors)} vendors"
            result["matches"] = [_format_match(m) for m in all_matches[:5]]
            result["best_match"] = _format_match(best)
            logger.warning(
                "[PO_RESOLUTION] doc=%s AMBIGUOUS (reason=%s): %d distinct POs from %d vendors",
                document_id[:12], result["miss_reason"], len(distinct_po_nos), len(distinct_vendors),
            )
            return result
        elif len(distinct_vendors) <= 1:
            logger.info(
                "[PO_RESOLUTION] doc=%s Multi-PO shipment: %d POs from same vendor (%s), using first: %s",
                document_id[:12], len(distinct_po_nos),
                best.get("bc_vendor_name", ""), best.get("bc_document_no", ""),
            )

    # Single clear winner
    is_shipment = best.get("bc_entity_type") == "posted_sales_shipment"
    result["status"] = STATUS_RESOLVED_SHIPMENT if is_shipment else STATUS_RESOLVED
    result["po_number"] = best.get("bc_document_no", best.get("entity_id", ""))
    result["bc_record_id"] = best.get("bc_record_id", "")
    result["bc_entity_type"] = best.get("bc_entity_type", "purchase_order")
    result["confidence"] = best["confidence"]
    result["match_method"] = best.get("match_method", "unknown")
    result["lookup_source"] = best.get("lookup_source", "")
    result["bc_vendor_no"] = best.get("bc_vendor_no", "")
    result["bc_vendor_name"] = best.get("bc_vendor_name", "")
    result["bc_customer_no"] = best.get("bc_customer_no", "")
    result["bc_customer_name"] = best.get("bc_customer_name", "")
    result["bc_order_number"] = best.get("bc_order_number", "")
    result["bc_status"] = best.get("bc_status", "")
    result["best_match"] = _format_match(best)
    result["matches"] = [_format_match(m) for m in all_matches[:5]]
    result["miss_reason"] = None

    if is_shipment:
        logger.info(
            "[PO_RESOLUTION] doc=%s RESOLVED (SHIPMENT): Shipment=%s bc_id=%s confidence=%.2f customer=%s order=%s",
            document_id[:12], result["po_number"],
            result["bc_record_id"][:12] if result["bc_record_id"] else "-",
            result["confidence"], result.get("bc_customer_name", ""),
            result.get("bc_order_number", ""),
        )
    else:
        logger.info(
            "[PO_RESOLUTION] doc=%s RESOLVED: PO=%s bc_id=%s confidence=%.2f method=%s source=%s vendor=%s",
            document_id[:12], result["po_number"],
            result["bc_record_id"][:12] if result["bc_record_id"] else "-",
            result["confidence"], result["match_method"], result["lookup_source"],
            result.get("bc_vendor_name", ""),
        )

    return result


# ─── BC Link Execution ────────────────────────────────────────────────────────

async def attempt_bc_link(document_id: str, po_resolution: Dict[str, Any]) -> Dict[str, Any]:
    """Attempt to link a document to a BC purchase order.
    Returns a standardized BC link result object.
    """
    link_result = {
        "status": "failed",
        "bc_record_type": None,
        "bc_record_id": None,
        "link_method": None,
        "error_code": None,
        "error_message": None,
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "document_id": document_id,
    }

    if po_resolution.get("status") not in (STATUS_RESOLVED, STATUS_RESOLVED_SHIPMENT):
        link_result["error_code"] = BC_LINK_RECORD_NOT_FOUND
        link_result["error_message"] = f"PO not resolved (status={po_resolution.get('status')})"
        logger.warning(
            "[BC_LINK] doc=%s SKIP: PO not resolved (status=%s)",
            document_id[:12], po_resolution.get("status"),
        )
        return link_result

    bc_record_id = po_resolution.get("bc_record_id", "")
    po_number = po_resolution.get("po_number", "")
    lookup_source = po_resolution.get("lookup_source", "")
    bc_entity_type = po_resolution.get("bc_entity_type", "purchase_order")

    # Shipment match — link directly from cache (no live BC verification needed)
    if bc_entity_type == "posted_sales_shipment":
        link_result["status"] = "linked_shipment"
        link_result["bc_record_type"] = "posted_sales_shipment"
        link_result["bc_record_id"] = bc_record_id or po_number
        link_result["link_method"] = f"shipment_cache_match:{po_resolution.get('match_method', 'unknown')}"
        link_result["bc_customer_name"] = po_resolution.get("bc_customer_name", "")
        link_result["bc_order_number"] = po_resolution.get("bc_order_number", "")
        logger.info(
            "[BC_LINK] doc=%s SHIPMENT LINK: Shipment=%s customer=%s order=%s",
            document_id[:12], po_number,
            po_resolution.get("bc_customer_name", ""),
            po_resolution.get("bc_order_number", ""),
        )
        return link_result

    if not bc_record_id:
        # PO resolved via local staging — no real BC record to link to
        if lookup_source == "local_staging":
            link_result["status"] = "linked_local"
            link_result["bc_record_type"] = "local_draft"
            link_result["bc_record_id"] = po_number
            link_result["link_method"] = "local_staging_match"
            logger.info(
                "[BC_LINK] doc=%s LOCAL LINK: PO=%s (local draft, not real BC)",
                document_id[:12], po_number,
            )
            return link_result

        link_result["error_code"] = BC_LINK_RECORD_NOT_FOUND
        link_result["error_message"] = "Resolved PO has no bc_record_id"
        logger.warning("[BC_LINK] doc=%s FAIL: No bc_record_id for PO=%s", document_id[:12], po_number)
        return link_result

    # Real BC record — attempt link
    try:
        from services.business_central_service import get_bc_service
        svc = get_bc_service()

        # Verify the PO still exists in BC
        po = await svc.find_purchase_order_by_number(po_number)
        if not po:
            link_result["error_code"] = BC_LINK_RECORD_NOT_FOUND
            link_result["error_message"] = f"BC PO {po_number} no longer found in live BC"
            logger.warning("[BC_LINK] doc=%s FAIL: BC PO %s not found in live BC", document_id[:12], po_number)
            return link_result

        # Successfully verified — mark as linked
        link_result["status"] = "linked"
        link_result["bc_record_type"] = "purchaseOrder"
        link_result["bc_record_id"] = po.get("id", bc_record_id)
        link_result["link_method"] = f"bc_po_verified:{po_resolution.get('match_method', 'unknown')}"
        logger.info(
            "[BC_LINK] doc=%s SUCCESS: Linked to BC PO %s (bc_id=%s, vendor=%s)",
            document_id[:12], po_number, link_result["bc_record_id"][:20],
            po.get("vendorName", ""),
        )

    except Exception as e:
        err_str = str(e).lower()
        if "token" in err_str or "auth" in err_str or "unauthorized" in err_str:
            link_result["error_code"] = BC_LINK_AUTH_ERROR
        elif "timeout" in err_str or "connect" in err_str:
            link_result["error_code"] = BC_LINK_NETWORK_ERROR
        elif "sandbox" in err_str:
            link_result["error_code"] = BC_LINK_SANDBOX_ONLY
        else:
            link_result["error_code"] = BC_LINK_UNKNOWN
        link_result["error_message"] = str(e)[:200]
        logger.error(
            "[BC_LINK] doc=%s FAIL (%s): PO=%s error=%s",
            document_id[:12], link_result["error_code"], po_number, str(e)[:100],
        )

    return link_result


# ─── BC Cache Search ──────────────────────────────────────────────────────────

async def _search_bc_cache(
    db, normalized_po: str, vendor_no: str = "", vendor_name: str = ""
) -> List[Dict[str, Any]]:
    """Search the BC reference cache for a PO number. Returns scored matches."""
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
        confidence = 0.95
        method = "bc_cache_exact"

        if vendor_no and hit.get("bc_vendor_no") == vendor_no:
            confidence = min(1.0, confidence + 0.05)
            method = "bc_cache_exact+vendor_no"
        elif vendor_name and hit.get("bc_vendor_name"):
            try:
                from services.reference_helpers import fuzzy_ratio, normalize_text
                v_score = fuzzy_ratio(vendor_name, hit["bc_vendor_name"], normalizer=normalize_text)
                if v_score >= 0.80:
                    confidence = min(1.0, confidence + 0.03)
                    method = f"bc_cache_exact+vendor_fuzzy({v_score:.0%})"
            except Exception:
                pass

        matches.append({**hit, "confidence": confidence, "match_method": method})

    # Suffix match (last 5 digits) — only when no exact hit
    if not matches and len(normalized_po) >= 5 and normalized_po.isdigit():
        suffix = normalized_po[-5:]
        fuzzy_query = {
            "bc_entity_type": "purchase_order",
            "normalized_document_no": {"$regex": f"{re.escape(suffix)}$"},
        }
        fuzzy_hits = await db.bc_reference_cache.find(fuzzy_query, {"_id": 0}).limit(5).to_list(5)
        for hit in fuzzy_hits:
            matches.append({
                **hit, "confidence": 0.55, "match_method": f"bc_cache_suffix({suffix})",
            })

    return matches


async def _search_bc_cache_shipments(
    db, normalized_ref: str
) -> List[Dict[str, Any]]:
    """Search BC cache for posted_sales_shipment matches. Returns scored matches.
    Used as fallback when no purchase_order match is found.
    """
    matches = []

    query = {
        "bc_entity_type": "posted_sales_shipment",
        "$or": [
            {"normalized_document_no": normalized_ref},
            {"bc_document_no": normalized_ref},
        ],
    }
    cache_hits = await db.bc_reference_cache.find(query, {"_id": 0}).to_list(5)

    for hit in cache_hits:
        matches.append({
            **hit,
            "confidence": 0.85,
            "match_method": "bc_cache_shipment_exact",
            "bc_customer_no": hit.get("bc_customer_no", ""),
            "bc_customer_name": hit.get("bc_customer_name", ""),
            "bc_order_number": hit.get("bc_order_number", ""),
        })

    return matches


# ─── Live BC API Search ───────────────────────────────────────────────────────

async def _search_bc_api(normalized_po: str, document_id: str) -> tuple:
    """Fallback: search live BC API. Returns (matches_list, error_string_or_None)."""
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
            }], None
        return [], None
    except Exception as e:
        logger.warning(
            "[PO_RESOLUTION] doc=%s BC API search failed for PO=%s: %s",
            document_id[:12], normalized_po, str(e)[:100],
        )
        return [], str(e)[:200]


# ─── Local Staging Fallback ───────────────────────────────────────────────────

async def _search_local_staging(db, normalized_po: str) -> List[Dict[str, Any]]:
    """Final fallback: search local po_drafts and so_drafts."""
    matches = []
    try:
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
    except Exception:
        pass

    try:
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
    except Exception:
        pass

    return matches


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _empty_result(document_id: str, doc_type: str) -> Dict[str, Any]:
    return {
        "document_id": document_id,
        "doc_type": doc_type,
        "status": STATUS_SKIPPED,
        "po_number": None,
        "bc_record_id": None,
        "bc_entity_type": None,
        "confidence": 0.0,
        "match_method": None,
        "lookup_source": None,
        "bc_vendor_no": None,
        "bc_vendor_name": None,
        "bc_customer_no": None,
        "bc_customer_name": None,
        "bc_order_number": None,
        "bc_status": None,
        "miss_reason": None,
        "reason": None,
        "best_match": None,
        "matches": [],
        "candidates_raw": [],
        "candidates_valid": [],
        "candidates_tried": [],
        "lookup_trace": [],
        "source_filename": None,
        "vendor_name": None,
        "vendor_no": None,
        "bc_link": None,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }


def _format_match(match: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "bc_document_no": match.get("bc_document_no", ""),
        "bc_record_id": match.get("bc_record_id", ""),
        "bc_entity_type": match.get("bc_entity_type", ""),
        "bc_vendor_no": match.get("bc_vendor_no", ""),
        "bc_vendor_name": match.get("bc_vendor_name", ""),
        "bc_customer_no": match.get("bc_customer_no", ""),
        "bc_customer_name": match.get("bc_customer_name", ""),
        "bc_order_number": match.get("bc_order_number", ""),
        "bc_status": match.get("bc_status", ""),
        "confidence": match.get("confidence", 0),
        "match_method": match.get("match_method", ""),
        "lookup_source": match.get("lookup_source", ""),
    }
