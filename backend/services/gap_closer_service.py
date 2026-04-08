"""
Gap Closer Service — Closes the 4 validation gaps using learned intelligence.

GAP 1: Confidence Miscalibration — Route 85-95% band to review (50% accuracy)
GAP 2: PO Validation (226 failures) — Fuzzy PO + vendor-specific patterns
GAP 3: Customer Match (88 failures) — Historical customer lookup from vendor data
GAP 4: Sales Order Match (62 failures) — Cross-reference via document flow
"""

import logging
import re
from typing import Dict, Any, List, Optional

logger = logging.getLogger("gap_closer")


# =============================================================================
# GAP 1: Confidence Band Awareness
# =============================================================================

async def get_confidence_band_accuracy(db, confidence: float, doc: dict = None) -> Dict:
    """
    Look up historical accuracy for a confidence band.
    
    If doc is provided, uses effective confidence (adjusted for extraction quality).
    Returns the band's accuracy and whether it should trigger review.
    """
    # Use effective confidence when doc is available
    if doc:
        from services.per_document_learning_service import compute_effective_confidence
        confidence = compute_effective_confidence(doc)

    if confidence < 0.50:
        band = "0_50"
    elif confidence < 0.70:
        band = "50_70"
    elif confidence < 0.85:
        band = "70_85"
    elif confidence < 0.95:
        band = "85_95"
    else:
        band = "95_100"

    cal = await db.confidence_calibration.find_one(
        {"calibration_id": "global"}, {"_id": 0}
    )
    if not cal or not cal.get("bands"):
        return {"band": band, "accuracy": None, "should_review": False, "reason": "no_calibration_data"}

    band_data = cal["bands"].get(band, {})
    total = band_data.get("total", 0)
    correct = band_data.get("correct", 0)

    if total < 10:
        return {"band": band, "accuracy": None, "should_review": False, "reason": "insufficient_samples"}

    accuracy = correct / total

    # If this band's accuracy is below 65%, flag for review
    should_review = accuracy < 0.65
    reason = ""
    if should_review:
        reason = f"Confidence band {band.replace('_', '-')}% has only {accuracy:.0%} historical accuracy ({total} samples)"

    return {
        "band": band,
        "accuracy": round(accuracy, 4),
        "total_samples": total,
        "should_review": should_review,
        "reason": reason,
    }


def apply_confidence_awareness(readiness: Dict, band_check: Dict) -> Dict:
    """
    Modify readiness evaluation based on confidence band accuracy.
    If the band is unreliable, downgrade to needs_review.
    """
    if not band_check.get("should_review"):
        return readiness

    status = readiness.get("status", "")
    action = readiness.get("recommended_action", "")

    # Only downgrade auto-processing decisions
    if status in ("ReadyToLink", "ReadyToAutoDraft") and action in ("auto_link", "auto_draft"):
        readiness["status"] = "NeedsReview"
        readiness["recommended_action"] = "review"
        readiness["warning_reasons"] = readiness.get("warning_reasons", []) + ["confidence_band_unreliable"]
        readiness["explanations"] = readiness.get("explanations", []) + [
            f"INTELLIGENCE: {band_check['reason']}. Routing to human review for safety."
        ]
        logger.info(
            "[GapCloser:ConfBand] Downgraded %s→NeedsReview: %s",
            status, band_check["reason"],
        )

    return readiness


# =============================================================================
# GAP 2: Enhanced PO Matching
# =============================================================================

async def find_po_with_intelligence(db, vendor_no: str, po_candidates: List[str],
                                     bc_client=None, token: str = "", api_url_fn=None) -> Dict:
    """
    Enhanced PO matching that uses learned patterns to find the right PO.
    
    Strategies (in order):
    1. Vendor-specific PO format normalization (learned patterns)
    2. Fuzzy/partial PO matching (strip prefixes, try variations)
    3. Historical PO cross-reference (from line item intelligence)
    4. Document flow cross-reference (linked BOL → PO)
    5. Reverse vendor PO lookup — search previously matched POs for this vendor
    6. Substring/contains matching — try partial number matching
    """
    if not po_candidates:
        return {"found": False, "strategy": "none"}

    # Strategy 2: Build expanded PO candidate list with variations
    expanded = []
    seen = set()
    for po in po_candidates:
        po_clean = str(po).strip()
        if not po_clean or po_clean in seen:
            continue
        seen.add(po_clean)
        expanded.append(po_clean)

        # Variation: strip leading zeros
        stripped = po_clean.lstrip("0")
        if stripped and stripped not in seen:
            expanded.append(stripped)
            seen.add(stripped)

        # Variation: strip common prefixes (PO-, PO#, SO-, etc.)
        for prefix in ["PO-", "PO#", "PO ", "SO-", "SO#", "SO ", "P-", "#", "INV-", "INV#", "INV "]:
            if po_clean.upper().startswith(prefix):
                remainder = po_clean[len(prefix):].strip()
                if remainder and remainder not in seen:
                    expanded.append(remainder)
                    seen.add(remainder)

        # Variation: add common prefixes if not present
        if not any(po_clean.upper().startswith(p) for p in ["PO", "SO", "P0"]):
            for prefix in ["PO", "P0"]:
                variant = f"{prefix}{po_clean}"
                if variant not in seen:
                    expanded.append(variant)
                    seen.add(variant)

        # Variation: numeric-only extraction
        numeric = re.sub(r'[^0-9]', '', po_clean)
        if numeric and len(numeric) >= 4 and numeric not in seen:
            expanded.append(numeric)
            seen.add(numeric)

        # Variation: case-insensitive uppercase
        upper = po_clean.upper()
        if upper not in seen:
            expanded.append(upper)
            seen.add(upper)

        # Variation: try dash and no-dash variants
        if "-" in po_clean:
            no_dash = po_clean.replace("-", "")
            if no_dash not in seen:
                expanded.append(no_dash)
                seen.add(no_dash)
        elif len(po_clean) > 4:
            # Try inserting dash at common positions (e.g., PO1234 -> PO-1234)
            for i in [2, 3]:
                dashed = po_clean[:i] + "-" + po_clean[i:]
                if dashed not in seen:
                    expanded.append(dashed)
                    seen.add(dashed)

        # Variation: last N digits (for long PO numbers that may have extra prefixes)
        if len(po_clean) >= 6:
            for suffix_len in [6, 5, 4]:
                suffix = po_clean[-suffix_len:]
                if suffix not in seen and suffix.isdigit():
                    expanded.append(suffix)
                    seen.add(suffix)

    # Strategy 3: Check document flow for related PO numbers
    if vendor_no:
        flow_docs = await db.document_flow_sequences.find(
            {"vendor_no": vendor_no, "doc_type": {"$in": ["Purchase_Order", "PO", "Sales_Order"]}},
            {"_id": 0, "doc_id": 1}
        ).limit(10).to_list(10)

        for fd in flow_docs:
            doc_id = fd.get("doc_id", "")
            if doc_id:
                related = await db.hub_documents.find_one(
                    {"id": doc_id}, {"_id": 0, "extracted_fields.po_number": 1, "extracted_fields.order_number": 1}
                )
                if related:
                    ef = related.get("extracted_fields") or {}
                    for ref_field in ["po_number", "order_number"]:
                        ref_val = ef.get(ref_field, "")
                        if ref_val and str(ref_val).strip() not in seen:
                            expanded.append(str(ref_val).strip())
                            seen.add(str(ref_val).strip())

    # Strategy 5: Reverse vendor PO lookup — find POs from previously matched docs
    if vendor_no:
        try:
            historical_pos = await db.hub_documents.find(
                {
                    "$or": [
                        {"bc_vendor_number": vendor_no},
                        {"vendor_no": vendor_no},
                        {"matched_vendor_no": vendor_no},
                    ],
                    "validation_results.po_match": True,
                    "extracted_fields.po_number": {"$exists": True, "$nin": [None, ""]},
                },
                {"_id": 0, "extracted_fields.po_number": 1}
            ).limit(50).to_list(50)

            known_pos = set()
            for d in historical_pos:
                po_val = (d.get("extracted_fields") or {}).get("po_number", "")
                if po_val:
                    known_pos.add(str(po_val).strip())

            # For each candidate, check if it's a substring of a known PO or vice versa
            for candidate in list(po_candidates):
                c_clean = str(candidate).strip().upper()
                c_numeric = re.sub(r'[^0-9]', '', c_clean)
                for known in known_pos:
                    k_upper = known.upper()
                    k_numeric = re.sub(r'[^0-9]', '', k_upper)
                    # Substring match: candidate is part of known PO or known PO contains candidate
                    if len(c_numeric) >= 4 and (c_numeric in k_numeric or k_numeric in c_numeric):
                        if known not in seen:
                            expanded.append(known)
                            seen.add(known)
                    # Fuzzy: Levenshtein-like — if only 1-2 chars different
                    elif len(c_clean) >= 4 and len(k_upper) >= 4:
                        if _simple_similarity(c_clean, k_upper) >= 0.8:
                            if known not in seen:
                                expanded.append(known)
                                seen.add(known)
        except Exception as e:
            logger.debug("[PO-Intel] Reverse vendor PO lookup failed: %s", e)

    return {
        "original_candidates": po_candidates,
        "expanded_candidates": expanded,
        "expansion_count": len(expanded) - len(po_candidates),
        "vendor_no": vendor_no,
    }


def _simple_similarity(a: str, b: str) -> float:
    """Quick character-level similarity (Jaccard on character bigrams)."""
    if not a or not b:
        return 0.0
    bigrams_a = set(a[i:i+2] for i in range(len(a)-1))
    bigrams_b = set(b[i:i+2] for i in range(len(b)-1))
    if not bigrams_a or not bigrams_b:
        return 0.0
    intersection = bigrams_a & bigrams_b
    union = bigrams_a | bigrams_b
    return len(intersection) / len(union)


async def find_customer_from_vendor_history(db, vendor_no: str, doc_type: str) -> Optional[Dict]:
    """
    GAP 3: Look up historical customer associations for a vendor.
    If this vendor's docs always ship to the same customer, suggest it.
    """
    if not vendor_no:
        return None

    # Check document flow for customer associations
    pipeline = [
        {"$match": {
            "$or": [
                {"bc_vendor_number": vendor_no},
                {"vendor_no": vendor_no},
                {"matched_vendor_no": vendor_no},
            ],
            "validation_results.bc_record_info.type": "customer",
        }},
        {"$group": {
            "_id": {
                "customer_name": "$validation_results.bc_record_info.displayName",
                "customer_number": "$validation_results.bc_record_info.number",
            },
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 3},
    ]

    try:
        results = await db.hub_documents.aggregate(pipeline).to_list(3)
    except Exception:
        results = []

    if not results:
        # Try from successful validation checks
        pipeline2 = [
            {"$match": {
                "$or": [
                    {"bc_vendor_number": vendor_no},
                    {"vendor_no": vendor_no},
                    {"matched_vendor_no": vendor_no},
                ],
                "validation_results.checks": {
                    "$elemMatch": {"check_name": "customer_match", "passed": True}
                },
            }},
            {"$project": {"_id": 0, "validation_results.checks": 1}},
            {"$limit": 20},
        ]
        try:
            docs = await db.hub_documents.aggregate(pipeline2).to_list(20)
            customer_counts = {}
            for d in docs:
                for c in (d.get("validation_results", {}).get("checks") or []):
                    if c.get("check_name") == "customer_match" and c.get("passed"):
                        cname = c.get("customer_name", "")
                        cnum = c.get("customer_number", "")
                        if cname:
                            key = f"{cname}|{cnum}"
                            customer_counts[key] = customer_counts.get(key, 0) + 1
            if customer_counts:
                best = max(customer_counts, key=customer_counts.get)
                parts = best.split("|")
                return {
                    "customer_name": parts[0],
                    "customer_number": parts[1] if len(parts) > 1 else "",
                    "association_count": customer_counts[best],
                    "source": "historical_validation",
                }
        except Exception:
            pass

    if results:
        best = results[0]["_id"]
        return {
            "customer_name": best.get("customer_name", ""),
            "customer_number": best.get("customer_number", ""),
            "association_count": results[0]["count"],
            "source": "document_history",
        }

    # Try from matched sales orders in document flow
    flow_pipeline = [
        {"$match": {
            "vendor_no": vendor_no,
            "doc_type": {"$in": ["Shipping_Document", "BOL", "SHIPMENT"]},
        }},
        {"$sort": {"arrived_at": -1}},
        {"$limit": 10},
    ]
    try:
        flows = await db.document_flow_sequences.aggregate(flow_pipeline).to_list(10)
        for f in flows:
            doc_id = f.get("doc_id", "")
            if doc_id:
                doc = await db.hub_documents.find_one(
                    {"id": doc_id}, {"_id": 0, "validation_results": 1}
                )
                if doc:
                    so_match = (doc.get("validation_results") or {}).get("matched_sales_order")
                    if so_match and so_match.get("customer_name"):
                        return {
                            "customer_name": so_match["customer_name"],
                            "customer_number": so_match.get("customer_number", ""),
                            "association_count": 1,
                            "source": "document_flow_sales_order",
                        }
    except Exception:
        pass

    return None


async def find_sales_order_from_flow(db, vendor_no: str, order_reference: str) -> Optional[Dict]:
    """
    GAP 4: Cross-reference document flow to find sales order matches.
    If a BOL from this vendor was previously matched to a sales order,
    and this doc references the same order, use that match.
    """
    if not order_reference:
        return None

    order_str = str(order_reference).strip()

    # Check if any previous document from this vendor matched this order
    query = {
        "$or": [
            {"validation_results.matched_sales_order.number": order_str},
            {"extracted_fields.order_number": order_str},
            {"extracted_fields.bol_number": order_str},
            {"extracted_fields.po_number": order_str},
        ],
    }
    if vendor_no:
        query["$or"] = [
            {"bc_vendor_number": vendor_no},
            {"vendor_no": vendor_no},
            {"matched_vendor_no": vendor_no},
        ]
        # Build the full query differently to combine conditions
        query = {
            "$and": [
                {"$or": [
                    {"bc_vendor_number": vendor_no},
                    {"vendor_no": vendor_no},
                    {"matched_vendor_no": vendor_no},
                ]},
                {"$or": [
                    {"validation_results.matched_sales_order.number": order_str},
                    {"validation_results.matched_sales_order.number": order_str.lstrip("0")},
                ]},
            ]
        }

    try:
        match_doc = await db.hub_documents.find_one(
            query, {"_id": 0, "validation_results.matched_sales_order": 1}
        )
        if match_doc:
            so = (match_doc.get("validation_results") or {}).get("matched_sales_order")
            if so:
                logger.info(
                    "[GapCloser:SOFlow] Found historical SO match: %s → %s",
                    order_str, so.get("customer_name"),
                )
                return {
                    "found": True,
                    "source": "document_flow_history",
                    "number": so.get("number", ""),
                    "customer_name": so.get("customer_name", ""),
                    "customer_number": so.get("customer_number", ""),
                    "order_date": so.get("order_date", ""),
                }
    except Exception as e:
        logger.debug("[GapCloser:SOFlow] Error: %s", e)

    # Try fuzzy order number matching
    variations = [order_str]
    stripped = order_str.lstrip("0")
    if stripped and stripped != order_str:
        variations.append(stripped)
    # Try with common prefixes
    for prefix in ["SO", "S-", "SO-"]:
        if not order_str.upper().startswith(prefix):
            variations.append(f"{prefix}{order_str}")

    for variant in variations[1:]:  # Skip first (already tried)
        try:
            match_doc = await db.hub_documents.find_one(
                {"validation_results.matched_sales_order.number": variant},
                {"_id": 0, "validation_results.matched_sales_order": 1}
            )
            if match_doc:
                so = (match_doc.get("validation_results") or {}).get("matched_sales_order")
                if so:
                    logger.info(
                        "[GapCloser:SOFlow] Found SO via variant '%s': %s",
                        variant, so.get("customer_name"),
                    )
                    return {
                        "found": True,
                        "source": "fuzzy_flow_match",
                        "number": so.get("number", ""),
                        "customer_name": so.get("customer_name", ""),
                        "customer_number": so.get("customer_number", ""),
                        "original_reference": order_str,
                        "matched_variant": variant,
                    }
        except Exception:
            pass

    return None


# =============================================================================
# INTEGRATION: Enhance BC Validation with Intelligence
# =============================================================================

async def enhance_po_candidates(db, vendor_no: str, original_candidates: List[str]) -> List[str]:
    """
    Expand PO candidates using learned intelligence.
    Called before BC PO validation to increase match chances.
    """
    result = await find_po_with_intelligence(db, vendor_no, original_candidates)
    return result.get("expanded_candidates", original_candidates)


async def get_customer_suggestion(db, vendor_no: str, doc_type: str) -> Optional[str]:
    """
    Get a customer name suggestion based on vendor history.
    Returns the most likely customer name or None.
    """
    result = await find_customer_from_vendor_history(db, vendor_no, doc_type)
    if result and result.get("association_count", 0) >= 2:
        return result.get("customer_name")
    return None
