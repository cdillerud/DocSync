"""
GPI Document Hub - Square9 Workflow Alignment

This module provides Square9-compatible workflow features:
- Retry counter with configurable max attempts
- Location code validation
- Auto-escalation after max retries
- Workflow stage tracking aligned with Square9 stages
"""

from enum import Enum
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# SQUARE9 WORKFLOW CONFIGURATION
# =============================================================================

class Square9Stage(str, Enum):
    """
    Square9 workflow stages - maps to their visual workflow diagram.
    Used for UI display and tracking.
    """
    # Import stage
    IMPORT = "import"                    # Document received (email/upload)
    
    # Classification stage
    CLASSIFICATION = "classification"    # AI/rule-based classification
    UNCLASSIFIED = "unclassified"       # Classification failed/pending
    
    # Validation stage
    VALIDATION = "validation"            # Field validation in progress
    MISSING_PO = "missing_po"           # PO Number missing
    MISSING_INVOICE = "missing_invoice"  # Invoice Number missing
    MISSING_VENDOR = "missing_vendor"    # Vendor ID missing
    MISSING_LOCATION = "missing_location" # Location Code missing
    MISSING_DATE = "missing_date"        # Document Date missing
    
    # BC Validation stage
    BC_VALIDATION = "bc_validation"      # Validating against BC
    BC_FAILED = "bc_failed"              # BC validation failed
    
    # Processing stage
    VALID = "valid"                      # All validations passed (green checkmark)
    ERROR_RECOVERY = "error_recovery"    # In error recovery flow
    
    # Resolution stage
    READY_FOR_EXPORT = "ready_for_export" # Ready to send to SharePoint/O365
    EXPORTED = "exported"                 # Sent to external system
    DELETED = "deleted"                   # Auto-deleted after max retries
    
    # Manual intervention
    MANUAL_REVIEW = "manual_review"       # Requires human review


# Default configuration - can be overridden per job type
DEFAULT_WORKFLOW_CONFIG = {
    "max_retry_attempts": 4,              # Square9 uses 4
    "auto_delete_on_max_retries": False,  # Safety: don't auto-delete, flag instead
    "auto_escalate_on_max_retries": True, # Escalate to manual review
    "retry_delay_minutes": 5,             # Wait before auto-retry
    "required_fields": {
        "AP_INVOICE": ["vendor", "invoice_number", "amount"],
        "SALES_INVOICE": ["customer", "invoice_number", "amount"],
        "PURCHASE_ORDER": ["vendor", "po_number"],
        "SHIPMENT": ["po_number", "location_code"],
        "RECEIPT": ["po_number", "location_code"],
    },
    "location_codes": {
        "valid_codes": ["SC", "MSC", "WH1", "WH2", "MAIN"],
        "default_code": "MAIN",
        "shipped_from_fallback": "ShippedFrom",
    }
}


# =============================================================================
# RETRY COUNTER LOGIC
# =============================================================================

def initialize_retry_state(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize Square9-style retry state for a document.
    Called when document is first captured.
    
    Returns dict to merge into document.
    """
    return {
        "retry_count": 0,
        "max_retries": DEFAULT_WORKFLOW_CONFIG["max_retry_attempts"],
        "retry_history": [],
        "auto_escalated": False,
        "square9_stage": Square9Stage.IMPORT.value,
    }


def increment_retry(
    doc: Dict[str, Any], 
    reason: str,
    stage: str = None
) -> Tuple[Dict[str, Any], bool, str]:
    """
    Increment retry counter and determine next action.
    
    Args:
        doc: Document dict
        reason: Why retry is needed
        stage: Current Square9 stage
        
    Returns:
        Tuple of (update_dict, should_escalate, action_message)
    """
    current_count = doc.get("retry_count", 0)
    max_retries = doc.get("max_retries", DEFAULT_WORKFLOW_CONFIG["max_retry_attempts"])
    
    new_count = current_count + 1
    now = datetime.now(timezone.utc).isoformat()
    
    retry_entry = {
        "attempt": new_count,
        "timestamp": now,
        "reason": reason,
        "stage": stage or doc.get("square9_stage", "unknown"),
    }
    
    retry_history = doc.get("retry_history", [])
    retry_history.append(retry_entry)
    
    update = {
        "retry_count": new_count,
        "retry_history": retry_history,
        "last_retry_utc": now,
        "last_retry_reason": reason,
    }
    
    # Check if we've hit max retries
    if new_count >= max_retries:
        if DEFAULT_WORKFLOW_CONFIG["auto_delete_on_max_retries"]:
            update["square9_stage"] = Square9Stage.DELETED.value
            update["workflow_status"] = "deleted"
            return update, True, f"Max retries ({max_retries}) reached - marked for deletion"
        elif DEFAULT_WORKFLOW_CONFIG["auto_escalate_on_max_retries"]:
            update["square9_stage"] = Square9Stage.MANUAL_REVIEW.value
            update["auto_escalated"] = True
            update["escalation_reason"] = f"Max retries ({max_retries}) reached"
            return update, True, f"Max retries ({max_retries}) reached - escalated to manual review"
    
    update["square9_stage"] = Square9Stage.ERROR_RECOVERY.value
    return update, False, f"Retry {new_count}/{max_retries} - {reason}"


def reset_retry_counter(doc: Dict[str, Any], reason: str = "Manual reset") -> Dict[str, Any]:
    """
    Reset retry counter (e.g., after successful processing or manual intervention).
    
    Returns dict to merge into document.
    """
    return {
        "retry_count": 0,
        "last_retry_reset_utc": datetime.now(timezone.utc).isoformat(),
        "last_retry_reset_reason": reason,
        "auto_escalated": False,
    }


# =============================================================================
# LOCATION CODE VALIDATION (Square9 Feature)
# =============================================================================

def validate_location_code(
    location_code: Optional[str],
    doc_type: str
) -> Tuple[bool, str, Optional[str]]:
    """
    Validate location code against configured valid codes.
    Square9 checks for SC, MSC, etc.
    
    Args:
        location_code: The extracted location code
        doc_type: Document type (SHIPMENT, RECEIPT, etc.)
        
    Returns:
        Tuple of (is_valid, message, resolved_code)
    """
    config = DEFAULT_WORKFLOW_CONFIG["location_codes"]
    valid_codes = config["valid_codes"]
    
    if not location_code or location_code.strip() == "":
        # Square9: "Set Location to 'ShippedFrom'" when empty
        return False, "Location code is empty", config["shipped_from_fallback"]
    
    normalized = location_code.strip().upper()
    
    if normalized in [c.upper() for c in valid_codes]:
        return True, f"Valid location code: {normalized}", normalized
    
    # Check for partial matches
    for valid in valid_codes:
        if normalized.startswith(valid.upper()) or valid.upper().startswith(normalized):
            return True, f"Location code matched: {normalized} -> {valid}", valid
    
    return False, f"Invalid location code: {location_code}", config["default_code"]


# =============================================================================
# SQUARE9 STAGE TRANSITIONS
# =============================================================================

def determine_square9_stage(doc: Dict[str, Any]) -> str:
    """
    Determine the current Square9 stage based on document state.
    Used for UI display and workflow tracking.
    
    Args:
        doc: Document dict
        
    Returns:
        Square9Stage value
    """
    workflow_status = doc.get("workflow_status", "captured")
    validation_results = doc.get("validation_results", {})
    
    # Check for escalation first
    if doc.get("auto_escalated"):
        return Square9Stage.MANUAL_REVIEW.value
    
    # Map workflow status to Square9 stage
    status_mapping = {
        "captured": Square9Stage.IMPORT.value,
        "classified": Square9Stage.CLASSIFICATION.value,
        "extracted": Square9Stage.VALIDATION.value,
        "vendor_pending": Square9Stage.MISSING_VENDOR.value,
        "bc_validation_pending": Square9Stage.BC_VALIDATION.value,
        "bc_validation_failed": Square9Stage.BC_FAILED.value,
        "data_correction_pending": Square9Stage.ERROR_RECOVERY.value,
        "ready_for_approval": Square9Stage.VALID.value,
        "approved": Square9Stage.READY_FOR_EXPORT.value,
        "exported": Square9Stage.EXPORTED.value,
        "archived": Square9Stage.EXPORTED.value,
        "failed": Square9Stage.ERROR_RECOVERY.value,
    }
    
    stage = status_mapping.get(workflow_status, Square9Stage.IMPORT.value)
    
    # Check for specific missing field conditions
    if workflow_status == "data_correction_pending":
        checks = validation_results.get("checks", [])
        for check in checks:
            if not check.get("passed", True):
                check_name = check.get("check_name", "")
                if "po" in check_name.lower():
                    return Square9Stage.MISSING_PO.value
                elif "invoice" in check_name.lower():
                    return Square9Stage.MISSING_INVOICE.value
                elif "vendor" in check_name.lower():
                    return Square9Stage.MISSING_VENDOR.value
                elif "location" in check_name.lower():
                    return Square9Stage.MISSING_LOCATION.value
                elif "date" in check_name.lower():
                    return Square9Stage.MISSING_DATE.value
    
    return stage


def get_square9_stage_info(stage: str) -> Dict[str, Any]:
    """
    Get display info for a Square9 stage.
    
    Args:
        stage: Square9Stage value
        
    Returns:
        Dict with label, color, icon, description
    """
    stage_info = {
        Square9Stage.IMPORT.value: {
            "label": "Import",
            "color": "blue",
            "icon": "inbox",
            "description": "Document received and queued for processing",
        },
        Square9Stage.CLASSIFICATION.value: {
            "label": "Classification",
            "color": "purple",
            "icon": "tag",
            "description": "Document type being identified",
        },
        Square9Stage.UNCLASSIFIED.value: {
            "label": "Unclassified",
            "color": "amber",
            "icon": "help-circle",
            "description": "Unable to determine document type",
        },
        Square9Stage.VALIDATION.value: {
            "label": "Validation",
            "color": "blue",
            "icon": "check-square",
            "description": "Validating extracted fields",
        },
        Square9Stage.MISSING_PO.value: {
            "label": "Missing PO",
            "color": "amber",
            "icon": "alert-triangle",
            "description": "PO Number is missing or invalid",
        },
        Square9Stage.MISSING_INVOICE.value: {
            "label": "Missing Invoice #",
            "color": "amber",
            "icon": "alert-triangle",
            "description": "Invoice Number is missing or invalid",
        },
        Square9Stage.MISSING_VENDOR.value: {
            "label": "Missing Vendor",
            "color": "amber",
            "icon": "alert-triangle",
            "description": "Vendor ID is missing or unmatched",
        },
        Square9Stage.MISSING_LOCATION.value: {
            "label": "Missing Location",
            "color": "amber",
            "icon": "alert-triangle",
            "description": "Location Code is missing or invalid",
        },
        Square9Stage.MISSING_DATE.value: {
            "label": "Missing Date",
            "color": "amber",
            "icon": "alert-triangle",
            "description": "Document Date is missing or invalid",
        },
        Square9Stage.BC_VALIDATION.value: {
            "label": "BC Validation",
            "color": "blue",
            "icon": "database",
            "description": "Validating against Business Central",
        },
        Square9Stage.BC_FAILED.value: {
            "label": "BC Failed",
            "color": "red",
            "icon": "x-circle",
            "description": "Business Central validation failed",
        },
        Square9Stage.VALID.value: {
            "label": "Valid",
            "color": "green",
            "icon": "check-circle",
            "description": "All validations passed",
        },
        Square9Stage.ERROR_RECOVERY.value: {
            "label": "Error Recovery",
            "color": "amber",
            "icon": "refresh-cw",
            "description": "Processing error, awaiting retry",
        },
        Square9Stage.READY_FOR_EXPORT.value: {
            "label": "Ready for Export",
            "color": "green",
            "icon": "upload-cloud",
            "description": "Ready to send to SharePoint/BC",
        },
        Square9Stage.EXPORTED.value: {
            "label": "Exported",
            "color": "green",
            "icon": "check",
            "description": "Sent to external system",
        },
        Square9Stage.DELETED.value: {
            "label": "Deleted",
            "color": "gray",
            "icon": "trash-2",
            "description": "Removed after max retries",
        },
        Square9Stage.MANUAL_REVIEW.value: {
            "label": "Manual Review",
            "color": "red",
            "icon": "eye",
            "description": "Requires human intervention",
        },
    }
    
    return stage_info.get(stage, {
        "label": stage.replace("_", " ").title(),
        "color": "gray",
        "icon": "circle",
        "description": "Unknown stage",
    })


# =============================================================================
# FIELD VALIDATION (Square9 Style)
# =============================================================================

def validate_required_fields(
    doc: Dict[str, Any],
    doc_type: str
) -> Tuple[bool, List[Dict[str, Any]], str]:
    """
    Validate required fields based on document type.
    Returns Square9-style validation results.
    
    Args:
        doc: Document dict
        doc_type: Document type
        
    Returns:
        Tuple of (all_valid, check_results, square9_stage)
    """
    required = DEFAULT_WORKFLOW_CONFIG["required_fields"].get(doc_type, [])
    checks = []
    all_valid = True
    stage = Square9Stage.VALID.value
    
    # Field extraction mapping
    field_map = {
        "vendor": ["vendor_raw", "vendor_canonical", "vendor_no"],
        "customer": ["customer_raw", "customer_canonical", "customer_no"],
        "invoice_number": ["invoice_number_raw", "invoice_number_clean"],
        "amount": ["amount_raw", "amount_float"],
        "po_number": ["po_number_raw", "po_number_clean"],
        "location_code": ["location_code", "location"],
        "document_date": ["document_date_raw", "document_date_iso"],
    }
    
    stage_map = {
        "vendor": Square9Stage.MISSING_VENDOR.value,
        "customer": Square9Stage.MISSING_VENDOR.value,
        "invoice_number": Square9Stage.MISSING_INVOICE.value,
        "amount": Square9Stage.MISSING_INVOICE.value,
        "po_number": Square9Stage.MISSING_PO.value,
        "location_code": Square9Stage.MISSING_LOCATION.value,
        "document_date": Square9Stage.MISSING_DATE.value,
    }
    
    for field in required:
        possible_keys = field_map.get(field, [field])
        found = False
        value = None
        
        for key in possible_keys:
            val = doc.get(key)
            if val is not None and str(val).strip() != "":
                found = True
                value = val
                break
        
        check = {
            "field": field,
            "passed": found,
            "value": value,
            "required": True,
        }
        
        if not found:
            check["error"] = f"{field.replace('_', ' ').title()} is empty"
            all_valid = False
            # Set stage to first missing field (Square9 behavior)
            if stage == Square9Stage.VALID.value:
                stage = stage_map.get(field, Square9Stage.ERROR_RECOVERY.value)
        
        checks.append(check)
    
    return all_valid, checks, stage


# =============================================================================
# WORKFLOW DECISION HELPERS
# =============================================================================

def should_retry(doc: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Determine if document should be retried.
    
    Returns:
        Tuple of (should_retry, reason)
    """
    retry_count = doc.get("retry_count", 0)
    max_retries = doc.get("max_retries", DEFAULT_WORKFLOW_CONFIG["max_retry_attempts"])
    
    if doc.get("auto_escalated"):
        return False, "Already escalated to manual review"
    
    if retry_count >= max_retries:
        return False, f"Max retries ({max_retries}) reached"
    
    # Check if in a retryable state
    retryable_stages = [
        Square9Stage.ERROR_RECOVERY.value,
        Square9Stage.UNCLASSIFIED.value,
        Square9Stage.MISSING_PO.value,
        Square9Stage.MISSING_INVOICE.value,
        Square9Stage.MISSING_VENDOR.value,
        Square9Stage.MISSING_LOCATION.value,
        Square9Stage.MISSING_DATE.value,
        Square9Stage.BC_FAILED.value,
    ]
    
    current_stage = doc.get("square9_stage", "")
    if current_stage in retryable_stages:
        return True, f"In retryable stage: {current_stage}"
    
    return False, f"Stage {current_stage} is not retryable"


def get_workflow_summary(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get a summary of document's workflow state for UI display.
    
    Args:
        doc: Document dict
        
    Returns:
        Summary dict with stage, retries, status info
    """
    stage = determine_square9_stage(doc)
    stage_info = get_square9_stage_info(stage)
    retry_count = doc.get("retry_count", 0)
    max_retries = doc.get("max_retries", DEFAULT_WORKFLOW_CONFIG["max_retry_attempts"])
    
    can_retry, retry_reason = should_retry(doc)
    
    return {
        "square9_stage": stage,
        "stage_info": stage_info,
        "retry_count": retry_count,
        "max_retries": max_retries,
        "retries_remaining": max(0, max_retries - retry_count),
        "can_retry": can_retry,
        "retry_reason": retry_reason,
        "auto_escalated": doc.get("auto_escalated", False),
        "escalation_reason": doc.get("escalation_reason"),
        "workflow_status": doc.get("workflow_status", "unknown"),
    }
