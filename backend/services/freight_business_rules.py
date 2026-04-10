"""
GPI Document Hub - Freight Business Rules (Controller-Defined)

Source: Meghan Czajkowski (Controller), Gamer Packaging Inc.
Date documented: March 2026

These rules codify the controller's freight processing workflow for automated
classification, validation, and routing of freight invoices through the system.
"""

import re
import logging
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)

# =============================================================================
# ORDER NUMBER PATTERNS
# =============================================================================
# "If it begins with a W or WR it's an inbound to the warehouse.
#  If it's our normal six digit number, ex Order 111279, then it would be a
#  warehouse outbound or a drop ship PO/SO."

ORDER_PATTERN_WAREHOUSE_INBOUND = re.compile(r"^W[R]?\d+", re.IGNORECASE)
ORDER_PATTERN_STANDARD = re.compile(r"^\d{5,6}$")


def classify_order_number(order_ref: str) -> Dict[str, Any]:
    """Classify an order by its number pattern."""
    order_ref = (order_ref or "").strip()
    if not order_ref:
        return {"type": "unknown", "reason": "no_order_ref"}

    if ORDER_PATTERN_WAREHOUSE_INBOUND.match(order_ref):
        return {
            "type": "warehouse_inbound",
            "direction": "inbound",
            "reason": f"Order '{order_ref}' starts with W/WR — warehouse inbound PO",
            "confidence": 0.95,
        }

    if ORDER_PATTERN_STANDARD.match(order_ref):
        return {
            "type": "outbound_or_dropship",
            "direction": "outbound",
            "reason": f"Order '{order_ref}' is standard 6-digit — outbound or drop ship",
            "confidence": 0.85,
        }

    # Container number or other international reference
    if re.match(r"^[A-Z]{4}\d{7}$", order_ref, re.IGNORECASE):
        return {
            "type": "container",
            "direction": "inbound",
            "reason": f"Order '{order_ref}' looks like a container number — likely international",
            "confidence": 0.70,
        }

    return {"type": "unknown", "direction": None, "reason": f"Unrecognized order format: '{order_ref}'", "confidence": 0.3}


# =============================================================================
# LOCATION CODE RULES
# =============================================================================
# Location code 00 = Drop Ship (DS box checked on lines)
# Location code 001 = Rerouted warehouse order to drop ship (SO ref in PO notes)
# Any other location code = Warehouse order (freight applied to item cost)

LOCATION_DROP_SHIP = "00"
LOCATION_REROUTED = "001"


def classify_location_code(location_code: str) -> Dict[str, Any]:
    """Classify order type by BC location code."""
    loc = (location_code or "").strip()
    if not loc:
        return {"type": "unknown", "reason": "no_location_code"}

    if loc == LOCATION_DROP_SHIP:
        return {
            "type": "drop_ship",
            "direction": "outbound",
            "freight_treatment": "outbound_expense",
            "reason": "Location 00 = drop ship order",
            "confidence": 0.95,
        }

    if loc == LOCATION_REROUTED:
        return {
            "type": "rerouted_dropship",
            "direction": "outbound",
            "freight_treatment": "outbound_expense",
            "reason": "Location 001 = rerouted warehouse→drop ship (SO ref in PO notes)",
            "confidence": 0.85,
        }

    return {
        "type": "warehouse",
        "direction": "inbound",
        "freight_treatment": "charge_item_to_inventory",
        "reason": f"Location '{loc}' = warehouse order — freight applied to item cost via Charge Item",
        "confidence": 0.90,
    }


# =============================================================================
# SHIPMENT METHOD CODES
# =============================================================================
# PPDADD = freight on separate line with cost AND sell price
# PPD = freight cost built into item sell price, FREIGHT line with cost only
# Delivered = vendor-arranged, no freight line, no freight bill expected

SHIPMENT_METHODS = {
    "PPDADD": {
        "description": "Freight on separate line with cost and sell price",
        "has_freight_line": True,
        "freight_has_sell_price": True,
        "expects_freight_invoice": True,
    },
    "PPD": {
        "description": "Freight cost in item sell price, FREIGHT line with cost only",
        "has_freight_line": True,
        "freight_has_sell_price": False,
        "expects_freight_invoice": True,
    },
    "DELIVERED": {
        "description": "Vendor-arranged freight, no freight line expected",
        "has_freight_line": False,
        "freight_has_sell_price": False,
        "expects_freight_invoice": False,
    },
}


def get_shipment_method_rules(method_code: str) -> Dict[str, Any]:
    """Get freight handling rules for a shipment method code."""
    code = (method_code or "").strip().upper()
    return SHIPMENT_METHODS.get(code, {
        "description": f"Unknown shipment method: {code}",
        "has_freight_line": None,
        "freight_has_sell_price": None,
        "expects_freight_invoice": None,
    })


# =============================================================================
# FREIGHT ITEM CODES
# =============================================================================
# Outbound: FREIGHT, DETENTION (must match codes on SO)
# Inbound: Charge Item codes (allocated to item cost)
# International: CUSTOMS, TARIFF, FREIGHT, DRAYAGE
# Warehouse inbound: WHSEFRT (sell price, no cost — cost via charge items)

OUTBOUND_FREIGHT_CODES = {"FREIGHT", "DETENTION"}
INTERNATIONAL_FREIGHT_CODES = {"CUSTOMS", "TARIFF", "FREIGHT", "DRAYAGE"}
WAREHOUSE_FREIGHT_CODES = {"WHSEFRT"}
ALL_FREIGHT_CODES = OUTBOUND_FREIGHT_CODES | INTERNATIONAL_FREIGHT_CODES | WAREHOUSE_FREIGHT_CODES


def validate_freight_item_codes(
    pi_item_codes: List[str],
    so_item_codes: List[str],
    order_type: str,
) -> Dict[str, Any]:
    """Validate that PI item codes match expected codes for the order type."""
    pi_set = {c.upper() for c in pi_item_codes if c}
    so_set = {c.upper() for c in so_item_codes if c}

    issues = []
    if order_type in ("outbound_or_dropship", "drop_ship"):
        # PI codes should match SO freight lines
        pi_freight = pi_set & ALL_FREIGHT_CODES
        so_freight = so_set & ALL_FREIGHT_CODES
        if pi_freight and so_freight and pi_freight != so_freight:
            issues.append(f"PI freight codes {pi_freight} don't match SO codes {so_freight}")
        if pi_freight - ALL_FREIGHT_CODES:
            issues.append(f"Unrecognized freight codes on PI: {pi_freight - ALL_FREIGHT_CODES}")
    elif order_type == "warehouse_inbound":
        # Should use charge item codes
        if pi_set & OUTBOUND_FREIGHT_CODES:
            issues.append("Inbound order using outbound freight codes — should use Charge Items")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "pi_freight_codes": list(pi_set & ALL_FREIGHT_CODES),
        "so_freight_codes": list(so_set & ALL_FREIGHT_CODES),
    }


# =============================================================================
# INTERNATIONAL SHIPMENT DETECTION
# =============================================================================
# "CARGOMO and USCUSTO would for sure always be associated with international"
# Check vendor + location code to determine treatment

ALWAYS_INTERNATIONAL_VENDORS = {"CARGOMO", "USCUSTO"}


def detect_international(vendor_no: str, vendor_name: str = "") -> Dict[str, Any]:
    """Detect if a vendor is associated with international shipments."""
    v = (vendor_no or "").upper().strip()
    vn = (vendor_name or "").upper()
    if v in ALWAYS_INTERNATIONAL_VENDORS or any(iv in vn for iv in ALWAYS_INTERNATIONAL_VENDORS):
        return {
            "is_international": True,
            "confidence": 0.95,
            "reason": f"Vendor {v} is always associated with international shipments",
        }
    return {"is_international": False, "confidence": 0.0, "reason": "Not a known international vendor"}


# =============================================================================
# FREIGHT VENDOR DETECTION
# =============================================================================
# Vendor posting group LOGIS-WH = freight carrier (also includes warehouses)

FREIGHT_VENDOR_POSTING_GROUP = "LOGIS-WH"


def is_freight_vendor_by_posting_group(posting_group: str) -> bool:
    """Check if vendor belongs to the freight/logistics posting group."""
    return (posting_group or "").strip().upper() == FREIGHT_VENDOR_POSTING_GROUP


# =============================================================================
# REVIEW THRESHOLDS
# =============================================================================
# "$100 more/less → freight issues spreadsheet for Logistics"

FREIGHT_VARIANCE_THRESHOLD = 100.0  # dollars


def check_freight_variance(
    invoice_amount: float, reference_amount: float
) -> Dict[str, Any]:
    """Check if freight invoice amount varies from reference by more than threshold."""
    if reference_amount is None or reference_amount == 0:
        return {"needs_review": False, "variance": 0, "reason": "No reference amount to compare"}

    variance = abs(invoice_amount - reference_amount)
    if variance > FREIGHT_VARIANCE_THRESHOLD:
        return {
            "needs_review": True,
            "variance": round(variance, 2),
            "reason": f"Freight variance ${variance:.2f} exceeds ${FREIGHT_VARIANCE_THRESHOLD} threshold "
                      f"(invoice=${invoice_amount:.2f}, reference=${reference_amount:.2f})",
            "severity": "high" if variance > FREIGHT_VARIANCE_THRESHOLD * 3 else "medium",
        }
    return {
        "needs_review": False,
        "variance": round(variance, 2),
        "reason": f"Variance ${variance:.2f} within threshold",
    }


# =============================================================================
# DUPLICATE DETECTION (ENHANCED)
# =============================================================================
# "Vendor + Invoice Number + Order Number"
# "LTL carriers (XPO and R&L) sometimes send different invoice numbers for same shipment"

LTL_CARRIERS_HIGH_DUP_RISK = {"XPO", "XPOLOGI", "R&L", "R+L", "RLCARR", "RL CARRIERS"}


def get_duplicate_check_fields(vendor_no: str) -> Dict[str, Any]:
    """Get the appropriate duplicate check strategy for a vendor."""
    v = (vendor_no or "").upper().strip()
    is_ltl_risk = any(ltl in v for ltl in LTL_CARRIERS_HIGH_DUP_RISK)
    return {
        "primary_key": ["vendor_no", "invoice_number", "order_reference"],
        "requires_order_ref": True,
        "ltl_high_risk": is_ltl_risk,
        "ltl_note": "LTL carriers may send different invoice numbers for same shipment — also check by vendor + order + amount" if is_ltl_risk else None,
    }


# =============================================================================
# MULTI-ORDER INVOICE DETECTION
# =============================================================================
# "Multiple SO's listed on freight bill — verify costs total"
# "International invoices could have multiple orders — costs on all orders reviewed"

def detect_multi_order_invoice(
    extracted_refs: List[str],
) -> Dict[str, Any]:
    """Detect if an invoice references multiple orders."""
    unique_orders = set()
    for ref in (extracted_refs or []):
        ref = ref.strip()
        if ORDER_PATTERN_STANDARD.match(ref) or ORDER_PATTERN_WAREHOUSE_INBOUND.match(ref):
            unique_orders.add(ref)

    if len(unique_orders) > 1:
        return {
            "is_multi_order": True,
            "order_count": len(unique_orders),
            "orders": sorted(unique_orders),
            "needs_review": True,
            "reason": f"Invoice references {len(unique_orders)} orders: {', '.join(sorted(unique_orders))} — verify costs total correctly",
        }
    return {"is_multi_order": False, "order_count": len(unique_orders), "orders": sorted(unique_orders), "needs_review": False}


# =============================================================================
# INVOICE NAMING CONVENTION PARSER
# =============================================================================
# Convention: "OrderNumber_Vendor_InvoiceDate_InvoiceNumber"

INVOICE_NAME_PATTERN = re.compile(
    r"^(?P<order>\w+)_(?P<vendor>[^_]+)_(?P<date>\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})_(?P<invoice>.+?)(?:\.\w+)?$"
)


def parse_invoice_filename(filename: str) -> Dict[str, Any]:
    """Parse invoice filename using Gamer naming convention."""
    fn = (filename or "").strip()
    match = INVOICE_NAME_PATTERN.match(fn)
    if match:
        return {
            "parsed": True,
            "order_number": match.group("order"),
            "vendor_code": match.group("vendor"),
            "invoice_date": match.group("date"),
            "invoice_number": match.group("invoice"),
        }
    return {"parsed": False, "reason": f"Filename '{fn}' doesn't match convention OrderNumber_Vendor_Date_InvoiceNumber"}


# =============================================================================
# MASTER CLASSIFICATION FUNCTION
# =============================================================================

def classify_freight_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply all controller-defined business rules to classify a freight document.
    Returns a comprehensive classification with direction, type, review flags.
    """
    result = {
        "rules_applied": [],
        "direction": None,
        "order_type": None,
        "is_international": False,
        "is_drop_ship": False,
        "freight_treatment": None,
        "review_flags": [],
        "confidence": 0.0,
    }

    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""
    vendor_name = doc.get("vendor_canonical") or doc.get("vendor_raw") or ""

    # 1. Parse filename for order/vendor hints
    filename = doc.get("file_name") or ""
    fn_parsed = parse_invoice_filename(filename)
    if fn_parsed.get("parsed"):
        result["filename_parsed"] = fn_parsed
        result["rules_applied"].append("filename_convention")

    # 2. Classify by order number — check all possible order reference fields
    order_ref = ""
    for field_name in [
        "po_number", "order_number", "so_number",
        "_po_resolution_number",  # Resolved PO from BC matching
    ]:
        val = ef.get(field_name) or nf.get(field_name)
        if val:
            if isinstance(val, list):
                order_ref = str(val[0]) if val else ""
            else:
                order_ref = str(val)
            break
    if not order_ref:
        order_ref = doc.get("external_document_no") or ""
    if not order_ref and fn_parsed.get("parsed"):
        order_ref = fn_parsed.get("order_number") or ""
    # Also try _po_all_candidates for W/WR patterns
    if not order_ref or classify_order_number(order_ref).get("type") == "unknown":
        all_candidates = ef.get("_po_all_candidates") or []
        for cand in all_candidates:
            cand_class = classify_order_number(str(cand))
            if cand_class.get("direction"):
                order_ref = str(cand)
                break
    order_ref = str(order_ref).strip()
    order_class = classify_order_number(order_ref)
    if order_class.get("direction"):
        result["direction"] = order_class["direction"]
        result["order_type"] = order_class["type"]
        result["confidence"] = max(result["confidence"], order_class.get("confidence", 0))
        result["rules_applied"].append("order_number_pattern")

    # 2b. Also check if extraction already detected freight direction
    existing_direction = ef.get("freight_direction") or ""
    if existing_direction in ("inbound", "outbound") and not result["direction"]:
        result["direction"] = existing_direction
        result["rules_applied"].append("extracted_freight_direction")

    # 3. Check location code (from BC reference data if available)
    location_code = doc.get("bc_location_code") or ef.get("location_code") or ""
    if location_code:
        loc_class = classify_location_code(location_code)
        if loc_class.get("type") != "unknown":
            result["order_type"] = loc_class["type"]
            result["direction"] = loc_class["direction"]
            result["freight_treatment"] = loc_class.get("freight_treatment")
            result["is_drop_ship"] = loc_class["type"] in ("drop_ship", "rerouted_dropship")
            result["confidence"] = max(result["confidence"], loc_class.get("confidence", 0))
            result["rules_applied"].append("location_code")

    # 4. Check international vendor
    intl = detect_international(vendor_no, vendor_name)
    if intl["is_international"]:
        result["is_international"] = True
        result["rules_applied"].append("international_vendor")

    # 5. Check for multi-order invoice
    all_refs = []
    for field in ["po_number", "order_number", "so_number", "reference_numbers", "_po_all_candidates"]:
        val = ef.get(field) or nf.get(field)
        if isinstance(val, list):
            all_refs.extend(str(v) for v in val)
        elif val:
            all_refs.append(str(val))
    multi = detect_multi_order_invoice(all_refs)
    if multi["is_multi_order"]:
        result["review_flags"].append({
            "type": "multi_order_invoice",
            "severity": "high",
            "reason": multi["reason"],
        })
        result["rules_applied"].append("multi_order_detection")

    # 6. Check freight variance (if we have both invoice amount and reference amount)
    invoice_amount = None
    for f in ["amount", "invoice_amount", "total_amount"]:
        val = ef.get(f) or nf.get(f)
        if val:
            try:
                invoice_amount = float(str(val).replace(",", "").replace("$", ""))
                break
            except (ValueError, TypeError):
                pass
    ref_amount = doc.get("bc_reference_freight_amount")
    if invoice_amount is not None and ref_amount is not None:
        variance = check_freight_variance(invoice_amount, ref_amount)
        if variance["needs_review"]:
            result["review_flags"].append({
                "type": "freight_variance",
                "severity": variance["severity"],
                "reason": variance["reason"],
                "variance": variance["variance"],
            })
            result["rules_applied"].append("freight_variance_check")

    # 7. Determine freight treatment if not already set
    if not result["freight_treatment"]:
        if result["direction"] == "inbound" and not result["is_drop_ship"]:
            result["freight_treatment"] = "charge_item_to_inventory"
        elif result["direction"] == "outbound" or result["is_drop_ship"]:
            result["freight_treatment"] = "outbound_expense"
        elif result["is_international"]:
            result["freight_treatment"] = "international_multi_code"

    # 8. Check duplicate risk for LTL carriers
    dup_strategy = get_duplicate_check_fields(vendor_no)
    if dup_strategy["ltl_high_risk"]:
        result["review_flags"].append({
            "type": "ltl_duplicate_risk",
            "severity": "medium",
            "reason": dup_strategy["ltl_note"],
        })
        result["rules_applied"].append("ltl_duplicate_risk")

    return result
