"""
Auto-Clear Service - Automatically clears high-confidence documents from the queue.

Aligns with Square9 and Zetadocs workflows:
- Documents meeting confidence threshold + validation = auto-cleared
- Auto-cleared docs are archived and removed from active queue
- Configurable thresholds per document type
- Full audit trail maintained
"""

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from enum import Enum

from services.automation_helpers import utcnow

logger = logging.getLogger(__name__)


class AutoClearDecision(Enum):
    """Possible outcomes of auto-clear evaluation."""
    CLEARED = "cleared"              # Document auto-cleared successfully
    NEEDS_REVIEW = "needs_review"    # Below threshold, needs manual review
    VALIDATION_FAILED = "validation_failed"  # Validation issues, can't auto-clear
    MISSING_DATA = "missing_data"    # Missing required extractions
    DUPLICATE = "duplicate"          # Duplicate detected, needs review
    EXCEPTION = "exception"          # Exception occurred, needs manual handling


# =============================================================================
# AUTO-CLEAR CONFIGURATION (Square9/Zetadocs aligned)
# =============================================================================

AUTO_CLEAR_CONFIG = {
    # Global settings
    "enabled": True,
    "default_confidence_threshold": 0.90,  # 90% default
    "require_sharepoint_upload": True,
    "require_bc_validation": True,
    
    # Per-document-type thresholds and rules
    "thresholds": {
        "AP_Invoice": {
            "confidence_threshold": 0.90,
            "require_vendor_match": True,
            "require_no_duplicate": True,
            "require_bc_draft_ready": True,  # Must be ready for BC posting
            "auto_post_if_cleared": True,    # Auto-post to BC when cleared
        },
        "Freight_Document": {
            "confidence_threshold": 0.70,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "require_minimum_extraction": True,
            "require_order_reference": False,
            "auto_post_if_cleared": False,   # Just archive
        },
        "Shipping_Document": {
            "confidence_threshold": 0.70,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "require_minimum_extraction": True,  # Must extract at least vendor OR order ref
            "auto_post_if_cleared": False,   # Just archive
        },
        "Warehouse_Document": {
            "confidence_threshold": 0.70,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "require_minimum_extraction": True,
            "auto_post_if_cleared": False,
        },
        "Quality_Doc": {
            "confidence_threshold": 0.0,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "auto_post_if_cleared": False,
        },
        "QUALITY_DOC": {
            "confidence_threshold": 0.0,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "auto_post_if_cleared": False,
        },
        "Statement": {
            "confidence_threshold": 0.0,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "auto_post_if_cleared": False,
        },
        "STATEMENT": {
            "confidence_threshold": 0.0,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "auto_post_if_cleared": False,
        },
        "Remittance": {
            "confidence_threshold": 0.0,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "auto_post_if_cleared": False,
        },
        "REMITTANCE": {
            "confidence_threshold": 0.0,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "auto_post_if_cleared": False,
        },
        "Order_Confirmation": {
            "confidence_threshold": 0.0,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "auto_post_if_cleared": False,
        },
        "BOL": {
            "confidence_threshold": 0.0,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "auto_post_if_cleared": False,
        },
        "Packing_List": {
            "confidence_threshold": 0.0,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "auto_post_if_cleared": False,
        },
        "Unknown_Document": {
            "confidence_threshold": 0.0,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "auto_post_if_cleared": False,
        },
        "Other": {
            "confidence_threshold": 0.0,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "auto_post_if_cleared": False,
        },
        "Unknown_Sales": {
            "confidence_threshold": 0.0,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "auto_post_if_cleared": False,
        },
        "Unknown": {
            "confidence_threshold": 0.0,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "auto_post_if_cleared": False,
        },
        "Sales_Order": {
            "confidence_threshold": 0.90,
            "require_customer_match": True,
            "require_no_duplicate": True,
            "auto_create_if_cleared": True,  # Auto-create SO in BC
        },
        "Credit_Memo": {
            "confidence_threshold": 0.95,  # Higher threshold for credits
            "require_vendor_match": True,
            "require_no_duplicate": True,
            "auto_post_if_cleared": False,  # Credits need review
        },
        # Default for unknown types - archive-only, relaxed
        "DEFAULT": {
            "confidence_threshold": 0.0,
            "require_vendor_match": False,
            "require_no_duplicate": False,
            "auto_post_if_cleared": False,
        }
    },
    
    # Square9 stage mapping for cleared documents
    "cleared_stage": "EXPORTED",
    "cleared_status": "Completed",
}


# =============================================================================
# AUTO-CLEAR EVALUATION LOGIC
# =============================================================================

def evaluate_auto_clear(
    doc: Dict[str, Any],
    validation_results: Optional[Dict[str, Any]] = None,
    config_override: Optional[Dict[str, Any]] = None
) -> Tuple[AutoClearDecision, str, Dict[str, Any]]:
    """
    Evaluate whether a document should be auto-cleared from the queue.
    
    Args:
        doc: The document dictionary with all extracted fields
        validation_results: BC validation results (if available)
        config_override: Optional config overrides
        
    Returns:
        Tuple of (decision, reason, details)
    """
    config = config_override or AUTO_CLEAR_CONFIG
    
    if not config.get("enabled", True):
        return AutoClearDecision.NEEDS_REVIEW, "Auto-clear disabled", {}
    
    doc_type = doc.get("doc_type") or doc.get("document_type") or doc.get("suggested_job_type") or "DEFAULT"

    # =================================================================
    # HARD GUARDRAIL: Never auto-clear unclassified / junk documents.
    # Protects against split children (`auto_split`) that come back as
    # `Unknown` with 0 confidence and no extracted fields — previously
    # these trivially passed the single confidence check (0.0 ≥ 0.0) and
    # got exported/completed, bypassing human review.
    # =================================================================
    UNKNOWN_TYPES = {
        None, "", "DEFAULT",
        "Unknown", "UNKNOWN", "unknown",
        "Unknown_Document", "UNKNOWN_DOCUMENT",
        "Unknown_Sales", "UNKNOWN_SALES",
        "Other", "OTHER",
    }
    if doc_type in UNKNOWN_TYPES:
        ai_class_early = doc.get("ai_classification") or {}
        conf_early = (
            ai_class_early.get("confidence")
            or doc.get("classification_confidence")
            or doc.get("ai_confidence")
            or doc.get("confidence")
            or 0.0
        )
        try:
            if isinstance(conf_early, str):
                conf_early = float(conf_early.replace("%", "")) / 100 if "%" in conf_early else float(conf_early)
            conf_early = float(conf_early)
        except (TypeError, ValueError):
            conf_early = 0.0

        extracted_early = doc.get("extracted_fields") or {}
        normalized_early = doc.get("normalized_fields") or {}
        meaningful_early = sum(
            1
            for k, v in {**extracted_early, **normalized_early}.items()
            if v and str(v).strip() and not str(k).endswith("_detected_by")
        )

        # Require BOTH reasonable confidence (>=0.70) AND real extracted content
        # before an Unknown/Other doc may proceed through the remaining checks.
        if conf_early < 0.70 or meaningful_early < 2:
            return (
                AutoClearDecision.NEEDS_REVIEW,
                (
                    f"Unclassified document (doc_type={doc_type or 'None'}, "
                    f"confidence={conf_early:.2f}, fields={meaningful_early}) — "
                    "refusing to auto-clear without human review"
                ),
                {
                    "doc_id": doc.get("id"),
                    "doc_type": doc_type,
                    "evaluated_at": utcnow(),
                    "checks": [{
                        "check": "unclassified_guard",
                        "passed": False,
                        "value": {
                            "doc_type": doc_type,
                            "confidence": conf_early,
                            "meaningful_fields": meaningful_early,
                        },
                        "message": "Unknown / low-confidence / no-content docs require manual review",
                    }],
                    "all_checks_passed": False,
                    "unclassified_guard_triggered": True,
                },
            )
    # Case-insensitive config lookup — DB stores 'AP_INVOICE', config keys use 'AP_Invoice'
    type_config = config["thresholds"].get(doc_type)
    if type_config is None:
        doc_type_lower = doc_type.lower()
        for key, val in config["thresholds"].items():
            if key.lower() == doc_type_lower:
                type_config = val
                break
        if type_config is None:
            type_config = config["thresholds"]["DEFAULT"]
    
    details = {
        "doc_id": doc.get("id"),
        "doc_type": doc_type,
        "evaluated_at": utcnow(),
        "checks": [],
        "threshold_config": type_config
    }
    
    # =================================================================
    # CHECK 1: Confidence Threshold
    # =================================================================
    # Prioritize classification confidence over extraction confidence
    ai_class = doc.get("ai_classification") or {}
    confidence = (
        ai_class.get("confidence")
        or doc.get("classification_confidence")
        or doc.get("ai_confidence")
        or doc.get("confidence")
        or 0
    )
    # Handle string percentages like "100%"
    if isinstance(confidence, str):
        confidence = float(confidence.replace("%", "")) / 100 if "%" in confidence else float(confidence)
    confidence = float(confidence)
    # If classification says 100% but field stores extraction confidence, use 100%
    ai_method = ai_class.get("method") or doc.get("classification_method") or ""
    if ai_method and confidence < 0.5:
        # There was a classification — trust that over low extraction score
        # Check if doc was successfully classified (has a doc_type)
        if doc.get("doc_type") or doc.get("document_type"):
            confidence = max(confidence, 0.85)  # Classified docs get at least 85%
    threshold = type_config.get("confidence_threshold", 0.90)
    
    confidence_passed = (confidence or 0) >= threshold
    details["checks"].append({
        "check": "confidence",
        "passed": confidence_passed,
        "value": confidence,
        "threshold": threshold,
        "message": f"Confidence {confidence:.1%} {'≥' if confidence_passed else '<'} {threshold:.1%}"
    })
    
    if not confidence_passed:
        return (
            AutoClearDecision.NEEDS_REVIEW,
            f"Confidence {confidence:.1%} below threshold {threshold:.1%}",
            details
        )
    
    # =================================================================
    # CHECK 2: Vendor/Customer Match (if required)
    # =================================================================
    if type_config.get("require_vendor_match"):
        vendor_matched = bool(
            doc.get("vendor_canonical") or 
            doc.get("vendor_id") or
            (validation_results and validation_results.get("match_method") not in (None, "none"))
        )
        details["checks"].append({
            "check": "vendor_match",
            "passed": vendor_matched,
            "value": doc.get("vendor_canonical"),
            "message": f"Vendor {'matched' if vendor_matched else 'not matched'}: {doc.get('vendor_canonical', 'N/A')}"
        })
        
        if not vendor_matched:
            return (
                AutoClearDecision.VALIDATION_FAILED,
                "Vendor match required but not found",
                details
            )
    
    if type_config.get("require_customer_match"):
        customer_matched = bool(
            doc.get("customer_canonical") or
            doc.get("customer_id") or
            (validation_results and validation_results.get("bc_record_id"))
        )
        details["checks"].append({
            "check": "customer_match",
            "passed": customer_matched,
            "value": doc.get("customer_canonical"),
            "message": f"Customer {'matched' if customer_matched else 'not matched'}"
        })
        
        if not customer_matched:
            return (
                AutoClearDecision.VALIDATION_FAILED,
                "Customer match required but not found",
                details
            )
    
    # =================================================================
    # CHECK 3: Duplicate Check
    # =================================================================
    if type_config.get("require_no_duplicate"):
        # Only use hard duplicate flag (content-hash match), not fuzzy "possible_duplicate"
        # For AP invoices, also check possible_duplicate (fuzzy match)
        is_hard_dup = doc.get("is_duplicate", False)
        is_ap = doc_type in ("AP_Invoice", "AP_INVOICE")
        is_fuzzy_dup = doc.get("possible_duplicate", False) if is_ap else False
        is_dup = is_hard_dup or is_fuzzy_dup
        details["checks"].append({
            "check": "duplicate",
            "passed": not is_dup,
            "value": is_dup,
            "message": "Duplicate detected" if is_dup else "No duplicate found"
        })
        
        if is_dup:
            return (
                AutoClearDecision.DUPLICATE,
                "Duplicate document detected - requires review",
                details
            )
    
    # =================================================================
    # CHECK 4: Minimum Extraction Quality
    # =================================================================
    if type_config.get("require_minimum_extraction"):
        extracted = doc.get("extracted_fields", {})
        normalized = doc.get("normalized_fields", {})
        
        # Exclude metadata fields (e.g., bol_detected_by, packing_list_detected_by)
        # from counting — these are heuristic markers, not real document data
        meaningful_extracted = {
            k: v for k, v in extracted.items()
            if v and str(v).strip() and not k.endswith("_detected_by")
        }
        meaningful_normalized = {
            k: v for k, v in normalized.items()
            if v and str(v).strip()
        }
        
        # Must have at least ONE of: vendor name, order reference, or 3+ REAL fields
        has_vendor = bool(
            meaningful_extracted.get("vendor") or meaningful_normalized.get("vendor")
        )
        has_order = bool(
            meaningful_extracted.get("po_number") or meaningful_normalized.get("po_number") or
            meaningful_extracted.get("bol_number") or meaningful_normalized.get("bol_number") or
            meaningful_extracted.get("order_number") or meaningful_extracted.get("so_number")
        )
        non_empty_fields = len(meaningful_extracted) + len(meaningful_normalized)
        has_enough_fields = non_empty_fields >= 3
        
        extraction_ok = has_vendor or has_order or has_enough_fields
        details["checks"].append({
            "check": "minimum_extraction",
            "passed": extraction_ok,
            "value": {"has_vendor": has_vendor, "has_order": has_order, "field_count": non_empty_fields},
            "message": f"Extraction quality: vendor={has_vendor}, order_ref={has_order}, fields={non_empty_fields}"
        })
        
        if not extraction_ok:
            return (
                AutoClearDecision.MISSING_DATA,
                f"Insufficient data extracted (no vendor, no order ref, only {non_empty_fields} meaningful fields). Needs manual review.",
                details
            )

    # =================================================================
    # CHECK 5: Required Fields (document-type specific)
    # =================================================================
    extracted = doc.get("extracted_fields", {})
    normalized = doc.get("normalized_fields", {})
    
    if type_config.get("require_order_reference"):
        order_ref = (
            doc.get("po_number_extracted") or
            doc.get("bol_number_extracted") or
            normalized.get("po_number") or
            normalized.get("bol_number") or
            extracted.get("po_number") or
            extracted.get("bol_number") or
            extracted.get("order_number")
        )
        details["checks"].append({
            "check": "order_reference",
            "passed": bool(order_ref),
            "value": order_ref,
            "message": f"Order reference: {order_ref or 'MISSING'}"
        })
        
        if not order_ref:
            return (
                AutoClearDecision.MISSING_DATA,
                "Order reference (PO/BOL#) required but missing",
                details
            )
    
    if type_config.get("require_bol_number"):
        bol = (
            doc.get("bol_number_extracted") or
            normalized.get("bol_number") or
            extracted.get("bol_number")
        )
        details["checks"].append({
            "check": "bol_number",
            "passed": bool(bol),
            "value": bol,
            "message": f"BOL#: {bol or 'MISSING'}"
        })
        
        if not bol:
            return (
                AutoClearDecision.MISSING_DATA,
                "BOL number required but missing",
                details
            )
    
    if type_config.get("require_ship_date"):
        ship_date = (
            doc.get("document_date_extracted") or
            normalized.get("ship_date") or
            extracted.get("ship_date") or
            extracted.get("document_date")
        )
        details["checks"].append({
            "check": "ship_date",
            "passed": bool(ship_date),
            "value": ship_date,
            "message": f"Ship date: {ship_date or 'MISSING'}"
        })
        
        if not ship_date:
            return (
                AutoClearDecision.MISSING_DATA,
                "Ship date required but missing (Square9: 'Missing Location')",
                details
            )
    
    # =================================================================
    # CHECK 5a: PO Resolution (shipping/freight/warehouse docs)
    # =================================================================
    from services.po_resolution_service import PO_REQUIRED_DOC_TYPES
    if doc_type in PO_REQUIRED_DOC_TYPES:
        po_res = doc.get("po_resolution") or {}
        po_status = po_res.get("status", "")
        po_resolved_ok = po_status == "resolved"
        details["checks"].append({
            "check": "po_resolution",
            "passed": po_resolved_ok,
            "value": {
                "status": po_status,
                "po_number": po_res.get("po_number"),
                "confidence": po_res.get("confidence"),
                "match_method": po_res.get("match_method"),
            },
            "message": f"PO resolution: {po_status} — {'PO ' + str(po_res.get('po_number', '')) if po_resolved_ok else 'unresolved'}",
        })

        if not po_resolved_ok:
            reason = "po_ambiguous" if po_status == "ambiguous" else "po_not_found"
            return (
                AutoClearDecision.NEEDS_REVIEW,
                f"Shipping doc cannot auto-clear: PO {po_status or 'not resolved'}",
                details,
            )

    # =================================================================
    # CHECK 5a-AP: BC Validation Warnings (AP invoices)
    # PO not found in BC = MUST go to review, never auto-clear
    # =================================================================
    if doc_type in ("AP_Invoice", "AP_INVOICE", "Purchase_Invoice"):
        val_results = doc.get("validation_results") or {}
        val_warnings = val_results.get("warnings") or []
        # Also check for po_not_found in the checks array
        val_checks = val_results.get("checks") or []

        po_found_in_bc = True  # assume ok unless we find evidence otherwise
        blocking_warnings = []

        for w in val_warnings:
            check_name = w.get("check_name", "") if isinstance(w, dict) else str(w)
            if "po_not_found" in check_name or "po_multi_source" in check_name or "po_bc_api_error" in check_name:
                po_found_in_bc = False
                blocking_warnings.append(check_name)

        # Also check if validation explicitly failed PO
        for c in val_checks:
            if isinstance(c, dict) and c.get("check_name") in ("po_validation", "po_match"):
                if not c.get("passed", True):
                    po_found_in_bc = False
                    blocking_warnings.append(c.get("check_name", "po_check"))

        details["checks"].append({
            "check": "ap_po_bc_validation",
            "passed": po_found_in_bc,
            "value": {"warnings": blocking_warnings},
            "message": f"AP PO in BC: {'validated' if po_found_in_bc else 'PO not found in BC — blocking auto-clear'}",
        })

        if not po_found_in_bc:
            return (
                AutoClearDecision.NEEDS_REVIEW,
                f"AP invoice cannot auto-clear: PO not validated in BC ({', '.join(blocking_warnings)})",
                details,
            )

    # =================================================================
    # CHECK 5b: BC Draft Ready (for AP invoices)
    # =================================================================
    if type_config.get("require_bc_draft_ready"):
        draft_ready = doc.get("draft_candidate", False) or doc.get("bc_create_ready", False)
        details["checks"].append({
            "check": "bc_draft_ready",
            "passed": draft_ready,
            "value": draft_ready,
            "message": f"BC draft ready: {draft_ready}"
        })
        
        if not draft_ready:
            return (
                AutoClearDecision.VALIDATION_FAILED,
                "Document not ready for BC draft creation",
                details
            )
    
    # =================================================================
    # CHECK 6: SharePoint Upload (only for AP invoices and types that need BC posting)
    # =================================================================
    requires_sp = type_config.get("auto_post_if_cleared") or type_config.get("auto_create_if_cleared")
    if config.get("require_sharepoint_upload") and requires_sp:
        sp_uploaded = bool(
            doc.get("sharepoint_item_id")
            or doc.get("sharepoint_web_url")
            or doc.get("sharepoint_drive_id")
            or doc.get("sharepoint_share_link_url")
        )
        details["checks"].append({
            "check": "sharepoint_upload",
            "passed": sp_uploaded,
            "value": doc.get("sharepoint_web_url"),
            "message": f"SharePoint: {'uploaded' if sp_uploaded else 'not uploaded'}"
        })
        
        if not sp_uploaded:
            return (
                AutoClearDecision.VALIDATION_FAILED,
                "SharePoint upload required but not completed",
                details
            )
    
    # =================================================================
    # ALL CHECKS PASSED - Document can be auto-cleared
    # =================================================================
    details["all_checks_passed"] = True
    details["auto_post_eligible"] = type_config.get("auto_post_if_cleared", False)
    details["auto_create_eligible"] = type_config.get("auto_create_if_cleared", False)
    
    return (
        AutoClearDecision.CLEARED,
        f"All {len(details['checks'])} checks passed - document auto-cleared",
        details
    )


def get_auto_clear_update(
    decision: AutoClearDecision,
    details: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Get the database update fields for an auto-clear decision.
    
    Returns the $set dictionary to apply to the document.
    """
    now = utcnow()
    
    if decision == AutoClearDecision.CLEARED:
        return {
            "status": AUTO_CLEAR_CONFIG["cleared_status"],
            "square9_stage": AUTO_CLEAR_CONFIG["cleared_stage"],
            "workflow_status": "exported",
            "auto_cleared": True,
            "auto_cleared_at": now,
            "auto_clear_details": details,
            "archived": True,
            "archived_utc": now,
            "queue_visible": False,  # Hide from default queue
            "updated_utc": now
        }
    else:
        # Not cleared - just record the evaluation
        return {
            "auto_cleared": False,
            "auto_clear_attempted_at": now,
            "auto_clear_decision": decision.value,
            "auto_clear_details": details,
            "queue_visible": True,
            "updated_utc": now
        }


def get_auto_clear_summary(details: Dict[str, Any]) -> str:
    """Get a human-readable summary of the auto-clear evaluation."""
    checks = details.get("checks", [])
    passed = sum(1 for c in checks if c.get("passed"))
    total = len(checks)
    
    summary_lines = [f"Auto-Clear Evaluation: {passed}/{total} checks passed"]
    
    for check in checks:
        status = "✓" if check.get("passed") else "✗"
        summary_lines.append(f"  {status} {check.get('check')}: {check.get('message')}")
    
    return "\n".join(summary_lines)


# =============================================================================
# CONFIGURATION HELPERS
# =============================================================================

def get_threshold_for_type(doc_type: str) -> float:
    """Get the confidence threshold for a document type (case-insensitive)."""
    type_config = AUTO_CLEAR_CONFIG["thresholds"].get(doc_type)
    if type_config is None:
        doc_type_lower = doc_type.lower()
        for key, val in AUTO_CLEAR_CONFIG["thresholds"].items():
            if key.lower() == doc_type_lower:
                type_config = val
                break
    if type_config is None:
        type_config = AUTO_CLEAR_CONFIG["thresholds"]["DEFAULT"]
    return type_config.get("confidence_threshold", 0.90)


def update_threshold(doc_type: str, new_threshold: float) -> bool:
    """Update the confidence threshold for a document type."""
    if doc_type not in AUTO_CLEAR_CONFIG["thresholds"]:
        AUTO_CLEAR_CONFIG["thresholds"][doc_type] = dict(
            AUTO_CLEAR_CONFIG["thresholds"]["DEFAULT"]
        )
    
    AUTO_CLEAR_CONFIG["thresholds"][doc_type]["confidence_threshold"] = new_threshold
    return True


def get_auto_clear_config() -> Dict[str, Any]:
    """Get the current auto-clear configuration."""
    return AUTO_CLEAR_CONFIG
