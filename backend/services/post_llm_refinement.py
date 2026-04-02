"""
GPI Document Hub — Post-LLM Refinement Service

Runs AFTER the LLM classification + extraction to fix systematic issues:
1. Vendor Name Normalization — maps LLM vendor_raw to canonical BC vendor name
2. Doc Type Refinement — uses vendor profile to correct common type confusion
3. PO Number Validation — checks PO format against vendor history patterns
4. Confidence Calibration — adjusts confidence based on extraction quality signals

This is the "clean up after the LLM" layer that uses the knowledge base
we've already built (aliases, profiles, corrections) to polish results.
"""

import logging
import re
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("post_llm_refinement")


# =========================================================================
# 1. VENDOR NAME NORMALIZATION
# =========================================================================

async def normalize_vendor_name(
    db, vendor_raw: str, vendor_no: str = ""
) -> Tuple[str, str, str]:
    """Resolve LLM vendor_raw to canonical BC vendor name.

    Returns: (canonical_name, vendor_no, method)
    """
    if not vendor_raw:
        return "", vendor_no, ""

    normalized = vendor_raw.strip()
    search_key = normalized.lower().replace(",", "").replace(".", "").replace("  ", " ").strip()

    # Step 1: Exact alias match
    alias = await db.vendor_aliases.find_one(
        {"normalized_alias": search_key},
        {"_id": 0, "canonical_name": 1, "vendor_no": 1, "canonical_vendor_id": 1}
    )
    if alias:
        canon = alias.get("canonical_name", "")
        vno = alias.get("vendor_no") or alias.get("canonical_vendor_id") or vendor_no
        if canon:
            logger.info("[VendorNorm] '%s' -> '%s' (%s) via exact alias", vendor_raw, canon, vno)
            return canon, vno, "alias_exact"

    # Step 2: Fuzzy alias match (starts-with on normalized)
    alias = await db.vendor_aliases.find_one(
        {"normalized_alias": {"$regex": f"^{re.escape(search_key[:20])}"}},
        {"_id": 0, "canonical_name": 1, "vendor_no": 1, "canonical_vendor_id": 1}
    )
    if alias:
        canon = alias.get("canonical_name", "")
        vno = alias.get("vendor_no") or alias.get("canonical_vendor_id") or vendor_no
        if canon:
            logger.info("[VendorNorm] '%s' -> '%s' (%s) via prefix alias", vendor_raw, canon, vno)
            return canon, vno, "alias_prefix"

    # Step 3: Profile name match
    profile = await db.vendor_invoice_profiles.find_one(
        {"vendor_name": {"$regex": f"^{re.escape(vendor_raw)}$", "$options": "i"}},
        {"_id": 0, "vendor_name": 1, "vendor_no": 1}
    )
    if profile:
        canon = profile.get("vendor_name", vendor_raw)
        vno = profile.get("vendor_no") or vendor_no
        logger.info("[VendorNorm] '%s' -> '%s' (%s) via profile", vendor_raw, canon, vno)
        return canon, vno, "profile_match"

    # No match — return original
    return vendor_raw, vendor_no, ""


# =========================================================================
# 2. DOC TYPE REFINEMENT
# =========================================================================

# Common confusions and their resolution rules
TYPE_REFINEMENT_RULES = {
    # If vendor sends 80%+ AP invoices, and LLM says Freight/Shipping → keep as-is
    # But if LLM says Unknown → reclassify to AP_Invoice
    "Unknown_Document": {
        "if_vendor_mostly": "posted_purchase_invoice",
        "threshold": 0.7,
        "reclassify_to": "AP_Invoice",
        "confidence_boost": 0.1,
    },
    "Unknown": {
        "if_vendor_mostly": "posted_purchase_invoice",
        "threshold": 0.7,
        "reclassify_to": "AP_Invoice",
        "confidence_boost": 0.1,
    },
    # Shipping_Document vs Warehouse_Receipt:
    # If the vendor is a warehouse operator, prefer Warehouse_Receipt
    # If the vendor is a carrier/logistics, prefer Shipping_Document
}

# Vendor keywords that indicate warehouse operations
WAREHOUSE_KEYWORDS = {"warehouse", "whse", "storage", "distribution", "fulfillment", "3pl"}
CARRIER_KEYWORDS = {"freight", "carrier", "trucking", "logistics", "transport", "shipping"}


async def refine_doc_type(
    db, doc_type: str, confidence: float,
    vendor_raw: str, vendor_no: str,
    extracted_fields: Dict[str, Any]
) -> Tuple[str, float, str]:
    """Refine document type using vendor profile intelligence.

    Returns: (refined_doc_type, refined_confidence, reasoning)
    """
    reasoning_parts = []

    # Rule 1: Unknown → AP_Invoice if vendor sends mostly AP invoices
    if doc_type in ("Unknown_Document", "Unknown", "Unknown_Sales"):
        if vendor_no:
            profile = await db.vendor_invoice_profiles.find_one(
                {"vendor_no": vendor_no}, {"_id": 0}
            )
            if profile:
                stats = profile.get("amount_stats", {})
                invoice_count = stats.get("count", 0)
                if invoice_count > 5:
                    # This vendor has significant AP invoice history
                    # Check if extracted fields look like an invoice
                    has_amount = bool(extracted_fields.get("total_amount") or extracted_fields.get("amount"))
                    has_invoice = bool(extracted_fields.get("invoice_number"))

                    if has_amount or has_invoice:
                        reasoning_parts.append(
                            f"Vendor {vendor_no} has {invoice_count} BC invoices; "
                            f"document has {'amount' if has_amount else 'invoice#'}; "
                            f"reclassified Unknown -> AP_Invoice"
                        )
                        return "AP_Invoice", min(confidence + 0.15, 0.95), "; ".join(reasoning_parts)

    # Rule 2: Shipping_Document vs Warehouse_Receipt disambiguation
    if doc_type in ("Shipping_Document", "Warehouse_Receipt", "Freight_Document"):
        vendor_lower = (vendor_raw or "").lower()

        # Check if vendor name contains warehouse or carrier keywords
        is_warehouse_vendor = any(kw in vendor_lower for kw in WAREHOUSE_KEYWORDS)
        is_carrier_vendor = any(kw in vendor_lower for kw in CARRIER_KEYWORDS)

        # Also check document content signals
        text_signals = _check_doc_content_signals(extracted_fields)

        if doc_type == "Shipping_Document" and is_warehouse_vendor and text_signals.get("has_receipt_signals"):
            reasoning_parts.append(
                f"Vendor '{vendor_raw}' is a warehouse operator + receipt signals detected; "
                f"refined Shipping_Document -> Warehouse_Receipt"
            )
            return "Warehouse_Receipt", confidence, "; ".join(reasoning_parts)

        if doc_type == "Warehouse_Receipt" and is_carrier_vendor and text_signals.get("has_shipping_signals"):
            reasoning_parts.append(
                f"Vendor '{vendor_raw}' is a carrier + shipping signals detected; "
                f"refined Warehouse_Receipt -> Shipping_Document"
            )
            return "Shipping_Document", confidence, "; ".join(reasoning_parts)

        if doc_type == "Freight_Document":
            # Freight_Document is often misclassified — check if it's really a BOL/Shipping
            if text_signals.get("has_bol_signals"):
                reasoning_parts.append("Freight_Document with BOL signals -> Shipping_Document")
                return "Shipping_Document", confidence, "; ".join(reasoning_parts)

    # Rule 3: Check historical corrections for this vendor + doc type combo
    if vendor_no:
        correction = await db.classification_corrections.find_one(
            {
                "original_type": doc_type,
                "vendor_no": vendor_no,
            },
            {"_id": 0},
            sort=[("created_at", -1)]
        )
        if correction and correction.get("corrected_type"):
            corrected = correction["corrected_type"]
            reasoning_parts.append(
                f"Historical correction: {doc_type} -> {corrected} for vendor {vendor_no}"
            )
            return corrected, max(confidence, 0.85), "; ".join(reasoning_parts)

    # No refinement needed
    return doc_type, confidence, ""


def _check_doc_content_signals(fields: Dict[str, Any]) -> Dict[str, bool]:
    """Check extracted fields for content signals."""
    all_text = " ".join(str(v) for v in fields.values() if isinstance(v, str)).lower()

    return {
        "has_receipt_signals": any(kw in all_text for kw in [
            "receipt", "received", "inbound", "unloading", "receiving"
        ]),
        "has_shipping_signals": any(kw in all_text for kw in [
            "shipped", "outbound", "delivery", "consignee", "tracking"
        ]),
        "has_bol_signals": any(kw in all_text for kw in [
            "bill of lading", "bol", "b/l", "carrier", "freight bill"
        ]),
    }


# =========================================================================
# 3. PO NUMBER VALIDATION
# =========================================================================

async def validate_po_number(
    db, po_number: str, vendor_no: str
) -> Tuple[str, bool, str]:
    """Validate/clean PO number against vendor's historical patterns.

    Returns: (cleaned_po, is_valid, reasoning)
    """
    if not po_number or not vendor_no:
        return po_number or "", bool(po_number), ""

    po_clean = po_number.strip()

    # Get vendor profile for PO patterns
    profile = await db.vendor_invoice_profiles.find_one(
        {"vendor_no": vendor_no}, {"_id": 0, "po_patterns": 1, "po_expected": 1}
    )

    if not profile:
        return po_clean, True, ""

    po_expected = profile.get("po_expected", True)
    patterns = profile.get("po_patterns", {})

    # If vendor doesn't use POs but LLM extracted one, it might be wrong
    if not po_expected and po_clean:
        # Check if what was extracted looks like a PO or something else
        # Common false positives: phone numbers, dates, internal refs
        if _looks_like_false_po(po_clean):
            logger.info("[POValidate] Vendor %s doesn't use POs; '%s' looks like false positive", vendor_no, po_clean)
            return "", False, f"Vendor {vendor_no} doesn't use POs; '{po_clean}' appears to be a false positive"

    # Validate against known patterns
    if patterns.get("has_patterns") and po_clean:
        avg_len = patterns.get("avg_length", 0)

        # Strip common noise prefixes
        for noise in ("PO ", "PO#", "PO:", "P.O.", "PU ", "P0"):
            if po_clean.upper().startswith(noise):
                po_clean = po_clean[len(noise):].strip()
                break

        # Check if length is reasonable (within 2x of average)
        if avg_len > 0 and len(po_clean) > avg_len * 3:
            # Might have multiple POs concatenated — take the first one
            parts = re.split(r'[/,;\s]+', po_clean)
            if len(parts) > 1:
                po_clean = parts[0].strip()
                logger.info("[POValidate] Truncated multi-PO '%s' to '%s'", po_number, po_clean)

    return po_clean, True, ""


def _looks_like_false_po(po: str) -> bool:
    """Check if a 'PO number' is actually something else."""
    po = po.strip()

    # Phone numbers (10+ digits with dashes)
    if re.match(r'^\d{3}[-.]?\d{3}[-.]?\d{4}$', po):
        return True

    # Dates
    if re.match(r'^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$', po):
        return True

    # Very long strings (likely descriptions)
    if len(po) > 50:
        return True

    # Email addresses
    if "@" in po:
        return True

    return False


# =========================================================================
# 4. CONFIDENCE CALIBRATION
# =========================================================================

def calibrate_confidence(
    confidence: float,
    doc_type: str,
    extracted_fields: Dict[str, Any],
    vendor_resolved: bool,
    refinement_applied: bool,
) -> float:
    """Calibrate confidence based on extraction quality signals.

    Boosts confidence when multiple strong signals align.
    Reduces when signals conflict or are weak.
    """
    base = confidence

    # Boost: vendor was resolved via alias/profile
    if vendor_resolved:
        base = min(base + 0.02, 1.0)

    # Boost: key fields extracted for this doc type
    if doc_type in ("AP_Invoice", "Credit_Memo"):
        has_vendor = bool(extracted_fields.get("vendor"))
        has_amount = bool(extracted_fields.get("total_amount") or extracted_fields.get("amount"))
        has_invoice = bool(extracted_fields.get("invoice_number"))
        has_line_items = bool(extracted_fields.get("line_items"))

        signal_count = sum([has_vendor, has_amount, has_invoice, has_line_items])
        if signal_count >= 3:
            base = min(base + 0.03, 1.0)
        elif signal_count <= 1:
            base = max(base - 0.05, 0.3)

    elif doc_type in ("Shipping_Document", "Warehouse_Receipt"):
        has_po = bool(extracted_fields.get("po_number"))
        has_vendor = bool(extracted_fields.get("vendor"))
        if has_po and has_vendor:
            base = min(base + 0.02, 1.0)

    # Reduce: refinement was applied (type was changed)
    if refinement_applied and base > 0.95:
        base = 0.95  # Cap at 0.95 when we had to correct the type

    return round(base, 3)


# =========================================================================
# MAIN ENTRY POINT — Called from classification pipeline
# =========================================================================

async def refine_classification(
    db,
    doc_type: str,
    confidence: float,
    extracted_fields: Dict[str, Any],
    vendor_raw: str = "",
    vendor_no: str = "",
) -> Dict[str, Any]:
    """Run all post-LLM refinement steps.

    Returns dict with refined values and reasoning.
    """
    result = {
        "original_doc_type": doc_type,
        "original_confidence": confidence,
        "refinements_applied": [],
    }

    # 1. Vendor normalization
    canonical_vendor, resolved_no, norm_method = await normalize_vendor_name(
        db, vendor_raw, vendor_no
    )
    if norm_method:
        result["refinements_applied"].append(f"vendor_norm:{norm_method}")
        extracted_fields["vendor"] = canonical_vendor
        result["vendor_canonical"] = canonical_vendor
        result["vendor_no"] = resolved_no
    else:
        result["vendor_canonical"] = vendor_raw
        result["vendor_no"] = vendor_no

    final_vendor_no = resolved_no or vendor_no

    # 2. Doc type refinement
    refined_type, refined_conf, type_reasoning = await refine_doc_type(
        db, doc_type, confidence, canonical_vendor or vendor_raw, final_vendor_no, extracted_fields
    )
    type_changed = refined_type != doc_type
    if type_changed:
        result["refinements_applied"].append(f"type_refine:{doc_type}->{refined_type}")
        logger.info("[Refine] Doc type: %s -> %s (%s)", doc_type, refined_type, type_reasoning)

    # 3. PO validation
    po_raw = extracted_fields.get("po_number", "")
    if po_raw:
        po_clean, po_valid, po_reasoning = await validate_po_number(db, po_raw, final_vendor_no)
        if po_clean != po_raw:
            result["refinements_applied"].append(f"po_clean:{po_raw}->{po_clean}")
            extracted_fields["po_number"] = po_clean
        if not po_valid:
            result["refinements_applied"].append(f"po_rejected:{po_raw}")
            extracted_fields.pop("po_number", None)

    # 4. Confidence calibration
    calibrated_conf = calibrate_confidence(
        refined_conf, refined_type, extracted_fields,
        vendor_resolved=bool(norm_method),
        refinement_applied=type_changed,
    )

    result["doc_type"] = refined_type
    result["confidence"] = calibrated_conf
    result["extracted_fields"] = extracted_fields
    result["type_reasoning"] = type_reasoning

    if result["refinements_applied"]:
        logger.info(
            "[Refine] Applied %d refinements: %s | type=%s conf=%.3f",
            len(result["refinements_applied"]),
            ", ".join(result["refinements_applied"]),
            refined_type, calibrated_conf,
        )

    return result
