"""
GPI Document Hub - Shadow Pilot Configuration

This module contains all configuration and utilities for the 14-day shadow pilot.
The pilot runs in read-only observation mode, ingesting and classifying documents
without affecting external systems (BC, Square9, Zetadocs).

Feature Flag: PILOT_MODE_ENABLED
- When True: New documents get pilot metadata, export actions are blocked
- When False: Normal operation, no pilot tagging

Pilot Phase: shadow_pilot_v1
- 14-day validation run
- All doc types: AP, AR/Sales, Warehouse (PO, Quality)
"""

import os
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any


# =============================================================================
# FEATURE FLAG
# =============================================================================

# Master switch for pilot mode - can be set via environment variable
PILOT_MODE_ENABLED = os.environ.get("PILOT_MODE_ENABLED", "true").lower() == "true"

# Current pilot phase identifier
CURRENT_PILOT_PHASE = "shadow_pilot_v1"

# Pilot start and end dates (for reference/validation)
PILOT_START_DATE = "2026-02-22"
PILOT_END_DATE = "2026-03-08"  # 14 days


# =============================================================================
# PILOT CONSTANTS
# =============================================================================

class PilotPhase(str, Enum):
    """Pilot phase identifiers for tracking."""
    SHADOW_PILOT_V1 = "shadow_pilot_v1"
    NONE = "none"  # Not a pilot document


class PilotCaptureChannel(str, Enum):
    """Capture channels specific to pilot ingestion."""
    SHADOW_PILOT = "SHADOW_PILOT"
    SHADOW_PILOT_EMAIL = "SHADOW_PILOT_EMAIL"
    SHADOW_PILOT_UPLOAD = "SHADOW_PILOT_UPLOAD"
    SHADOW_PILOT_FILE_DROP = "SHADOW_PILOT_FILE_DROP"


# =============================================================================
# PILOT METADATA UTILITIES
# =============================================================================

def get_pilot_metadata() -> Dict[str, Any]:
    """
    Generate pilot metadata fields for new documents.
    
    Returns:
        dict with pilot_phase and pilot_date if pilot mode is enabled,
        empty dict otherwise.
    """
    if not PILOT_MODE_ENABLED:
        return {}
    
    return {
        "pilot_phase": CURRENT_PILOT_PHASE,
        "pilot_date": datetime.now(timezone.utc).isoformat(),
    }


def is_pilot_document(document: Dict[str, Any]) -> bool:
    """
    Check if a document is part of the pilot.
    
    Args:
        document: Document dict with potential pilot_phase field
        
    Returns:
        True if document has a pilot_phase set
    """
    return document.get("pilot_phase") is not None


def get_pilot_capture_channel(base_channel: str) -> str:
    """
    Convert a base capture channel to its pilot equivalent.
    
    Args:
        base_channel: Original capture channel (EMAIL, UPLOAD, etc.)
        
    Returns:
        Pilot-specific capture channel if pilot mode enabled,
        otherwise returns the original channel
    """
    if not PILOT_MODE_ENABLED:
        return base_channel
    
    channel_mapping = {
        "EMAIL": PilotCaptureChannel.SHADOW_PILOT_EMAIL.value,
        "UPLOAD": PilotCaptureChannel.SHADOW_PILOT_UPLOAD.value,
        "API": PilotCaptureChannel.SHADOW_PILOT.value,
        "FILE_DROP": PilotCaptureChannel.SHADOW_PILOT_FILE_DROP.value,
    }
    
    return channel_mapping.get(base_channel, PilotCaptureChannel.SHADOW_PILOT.value)


# =============================================================================
# PILOT ACTION GUARDS
# =============================================================================

def is_export_blocked(document: Dict[str, Any] = None) -> bool:
    """
    Check if export actions should be blocked.
    
    During pilot mode, all export actions are blocked to prevent
    writes to external systems (BC, Square9, Zetadocs).
    
    Args:
        document: Optional document to check (for future per-doc control)
        
    Returns:
        True if exports should be blocked
    """
    if not PILOT_MODE_ENABLED:
        return False
    
    # During pilot, block all exports
    return True


def is_bc_validation_blocked(document: Dict[str, Any] = None) -> bool:
    """
    Check if BC validation actions should be blocked.
    
    During pilot, we don't make actual BC API calls.
    
    Args:
        document: Optional document to check
        
    Returns:
        True if BC validation should be blocked/simulated
    """
    if not PILOT_MODE_ENABLED:
        return False
    
    return True


def is_external_write_blocked(document: Dict[str, Any] = None) -> bool:
    """
    Check if any external system writes should be blocked.
    
    This is the master guard for all external integrations during pilot.
    
    Args:
        document: Optional document to check
        
    Returns:
        True if external writes should be blocked
    """
    if not PILOT_MODE_ENABLED:
        return False
    
    return True


# =============================================================================
# PILOT WORKFLOW HISTORY HELPERS
# =============================================================================

def create_pilot_workflow_entry(
    action: str,
    from_status: str,
    to_status: str,
    user: str = "pilot_system",
    reason: str = None,
    blocked_action: str = None
) -> Dict[str, Any]:
    """
    Create a workflow history entry with pilot annotations.
    
    Args:
        action: The workflow action performed
        from_status: Previous status
        to_status: New status
        user: Actor performing the action
        reason: Optional reason/comment
        blocked_action: If an external action was blocked, describe it
        
    Returns:
        Workflow history entry dict
    """
    entry = {
        "action": action,
        "from_status": from_status,
        "to_status": to_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user": user,
    }
    
    if reason:
        entry["reason"] = reason
    
    if PILOT_MODE_ENABLED:
        entry["pilot_mode"] = True
        if blocked_action:
            entry["blocked_external_action"] = blocked_action
            entry["pilot_note"] = f"External action '{blocked_action}' blocked during pilot"
    
    return entry


# =============================================================================
# PILOT METRICS THRESHOLDS
# =============================================================================

# Time thresholds for "stuck" document detection (in hours)
STUCK_THRESHOLDS = {
    "vendor_pending": 24,
    "bc_validation_pending": 24,
    "extracted": 24,  # For SALES_INVOICE
    "validation_pending": 24,  # For PURCHASE_ORDER
    "ready_for_review": 48,  # For QUALITY_DOC
    "default": 48,
}


def get_stuck_threshold_hours(status: str) -> int:
    """
    Get the threshold in hours for considering a document "stuck" in a status.
    
    Args:
        status: Workflow status
        
    Returns:
        Hours threshold
    """
    return STUCK_THRESHOLDS.get(status, STUCK_THRESHOLDS["default"])


# =============================================================================
# PILOT LOGGING
# =============================================================================

def create_pilot_log_entry(
    document_id: str,
    event_type: str,
    classification_method: str = None,
    doc_type: str = None,
    workflow_status: str = None,
    ai_classification: Dict[str, Any] = None,
    time_to_status_ms: int = None,
    additional_data: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Create a structured pilot log entry for audit purposes.
    
    Args:
        document_id: The document's ID
        event_type: Type of event (ingestion, classification, routing, etc.)
        classification_method: How the doc was classified (deterministic, ai, etc.)
        doc_type: Assigned document type
        workflow_status: Current/assigned workflow status
        ai_classification: AI classification details if applicable
        time_to_status_ms: Time taken to reach this status in milliseconds
        additional_data: Any other relevant data
        
    Returns:
        Structured log entry dict
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pilot_phase": CURRENT_PILOT_PHASE,
        "document_id": document_id,
        "event_type": event_type,
    }
    
    if classification_method:
        entry["classification_method"] = classification_method
    
    if doc_type:
        entry["doc_type"] = doc_type
    
    if workflow_status:
        entry["workflow_status"] = workflow_status
    
    if ai_classification:
        entry["ai_classification"] = ai_classification
    
    if time_to_status_ms is not None:
        entry["time_to_status_initialization_ms"] = time_to_status_ms
    
    if additional_data:
        entry.update(additional_data)
    
    return entry


# =============================================================================
# PILOT STATUS HELPER
# =============================================================================

def get_pilot_status() -> Dict[str, Any]:
    """
    Get current pilot status and configuration.
    
    Returns:
        Dict with pilot mode status and configuration
    """
    return {
        "pilot_mode_enabled": PILOT_MODE_ENABLED,
        "current_phase": CURRENT_PILOT_PHASE,
        "pilot_start_date": PILOT_START_DATE,
        "pilot_end_date": PILOT_END_DATE,
        "exports_blocked": is_export_blocked(),
        "bc_validation_blocked": is_bc_validation_blocked(),
        "external_writes_blocked": is_external_write_blocked(),
    }
