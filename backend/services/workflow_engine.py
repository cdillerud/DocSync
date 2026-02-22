"""
GPI Document Hub - Multi-Type Workflow Engine Service

This module implements a deterministic state machine for document workflows across
multiple document types. It replaces Square9 workflows and Zetadocs document storage
with a unified, type-aware workflow approach.

The workflow engine is pure business logic with no direct HTTP or DB calls.
All state transitions are deterministic and can be covered by unit tests.

Document Types Supported:
- AP_INVOICE: Full workflow with vendor matching, BC validation, approvals
- SALES_INVOICE: Standard workflow with extraction and approval
- PURCHASE_ORDER: Standard workflow with extraction and approval
- SALES_CREDIT_MEMO: Standard workflow with extraction and approval
- PURCHASE_CREDIT_MEMO: Standard workflow with extraction and approval
- STATEMENT: Simplified workflow
- REMINDER: Simplified workflow
- FINANCE_CHARGE_MEMO: Simplified workflow
- QUALITY_DOC: Simplified workflow
- OTHER: Basic capture -> classify -> archive workflow
"""

from enum import Enum
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple, Any
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# DOCUMENT TYPE DEFINITIONS
# =============================================================================

class DocType(str, Enum):
    """
    Document type classification for all documents in the system.
    Maps to Square9 workflows and Zetadocs document sets.
    """
    AP_INVOICE = "AP_INVOICE"                     # Vendor invoices we receive (ZD00015)
    SALES_INVOICE = "SALES_INVOICE"               # Invoices we send (ZD00007)
    PURCHASE_ORDER = "PURCHASE_ORDER"             # Purchase orders (ZD00002)
    SALES_CREDIT_MEMO = "SALES_CREDIT_MEMO"       # Credit memos we issue (ZD00009)
    PURCHASE_CREDIT_MEMO = "PURCHASE_CREDIT_MEMO" # Credit memos we receive
    STATEMENT = "STATEMENT"                       # Account statements
    REMINDER = "REMINDER"                         # Payment reminders
    FINANCE_CHARGE_MEMO = "FINANCE_CHARGE_MEMO"   # Finance charge documents
    QUALITY_DOC = "QUALITY_DOC"                   # Quality documentation
    OTHER = "OTHER"                               # Unclassified documents


class SourceSystem(str, Enum):
    """Source system where the document originated."""
    SQUARE9 = "SQUARE9"
    ZETADOCS = "ZETADOCS"
    GPI_HUB_NATIVE = "GPI_HUB_NATIVE"
    MIGRATION = "MIGRATION"
    UNKNOWN = "UNKNOWN"


class CaptureChannel(str, Enum):
    """Channel through which the document was captured."""
    EMAIL = "EMAIL"
    UPLOAD = "UPLOAD"
    API = "API"
    MIGRATION_JOB = "MIGRATION_JOB"
    ORDER_CONFIRMATION = "ORDER_CONFIRMATION"
    # Pilot-specific channels
    SHADOW_PILOT = "SHADOW_PILOT"
    SHADOW_PILOT_EMAIL = "SHADOW_PILOT_EMAIL"
    SHADOW_PILOT_UPLOAD = "SHADOW_PILOT_UPLOAD"
    SHADOW_PILOT_FILE_DROP = "SHADOW_PILOT_FILE_DROP"
    UNKNOWN = "UNKNOWN"


# Zetadocs Document Set to DocType mapping
ZETADOCS_SET_MAPPING = {
    "ZD00007": (DocType.SALES_INVOICE, None),                        # Sales - Invoices
    "ZD00015": (DocType.AP_INVOICE, None),                           # Purchase - Invoices
    "ZD00002": (DocType.PURCHASE_ORDER, None),                       # Purchase - Orders
    "ZD00006": (DocType.SALES_INVOICE, CaptureChannel.ORDER_CONFIRMATION),  # Order Confirmations
    "ZD00009": (DocType.SALES_CREDIT_MEMO, None),                    # Sales - Return Orders
    "ZD00010": (DocType.SALES_INVOICE, None),                        # Sales - Blanket Sales Orders
}

# Square9 Workflow to DocType mapping
SQUARE9_WORKFLOW_MAPPING = {
    "AP_Invoice": DocType.AP_INVOICE,
    "AP Invoice": DocType.AP_INVOICE,
    "Purchase Invoice": DocType.AP_INVOICE,
    "Sales Invoice": DocType.SALES_INVOICE,
    "Sales_Invoice": DocType.SALES_INVOICE,
    "Purchase Order": DocType.PURCHASE_ORDER,
    "PO": DocType.PURCHASE_ORDER,
    "Credit Memo": DocType.SALES_CREDIT_MEMO,
    "Statement": DocType.STATEMENT,
    "Reminder": DocType.REMINDER,
    "Quality": DocType.QUALITY_DOC,
    "Quality_Doc": DocType.QUALITY_DOC,
    "QC": DocType.QUALITY_DOC,
}


# =============================================================================
# WORKFLOW STATUS & EVENTS
# =============================================================================

class WorkflowStatus(str, Enum):
    """
    Workflow status values. Shared across all document types.
    Not all statuses apply to all document types.
    """
    # Initial capture stage (all types)
    CAPTURED = "captured"
    CLASSIFIED = "classified"
    
    # Extraction stage (all types)
    EXTRACTED = "extracted"
    
    # AP Invoice specific exception queues
    VENDOR_PENDING = "vendor_pending"              # Unknown vendor, needs manual resolution
    BC_VALIDATION_PENDING = "bc_validation_pending" # Awaiting BC validation
    BC_VALIDATION_FAILED = "bc_validation_failed"   # BC validation failed, needs override
    
    # PO validation states (PURCHASE_ORDER)
    VALIDATION_PENDING = "validation_pending"       # PO awaiting validation
    VALIDATION_FAILED = "validation_failed"         # PO validation failed
    
    # Credit memo states (SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO)
    LINKED_TO_INVOICE = "linked_to_invoice"         # Credit memo linked to original invoice
    
    # Quality doc states (QUALITY_DOC)
    TAGGED = "tagged"                               # Quality doc tagged/categorized
    REVIEW_IN_PROGRESS = "review_in_progress"       # Quality review in progress
    
    # OTHER doc states (triage)
    TRIAGE_PENDING = "triage_pending"               # Awaiting triage
    TRIAGE_COMPLETED = "triage_completed"           # Triage completed
    
    # General exception queues (all types)
    DATA_CORRECTION_PENDING = "data_correction_pending"  # Extraction incomplete
    REVIEW_PENDING = "review_pending"              # General review queue
    READY_FOR_REVIEW = "ready_for_review"          # Ready for review (STATEMENT, REMINDER, etc.)
    REVIEWED = "reviewed"                          # Document reviewed
    
    # Approval stage (most types)
    READY_FOR_APPROVAL = "ready_for_approval"
    APPROVAL_IN_PROGRESS = "approval_in_progress"
    APPROVED = "approved"
    REJECTED = "rejected"
    
    # Export/Archive stage (all types)
    EXPORTED = "exported"
    ARCHIVED = "archived"
    
    # Error states
    FAILED = "failed"


class WorkflowEvent(str, Enum):
    """Events that trigger workflow state transitions."""
    # Capture events
    ON_CAPTURE = "on_capture"
    ON_CLASSIFICATION_SUCCESS = "on_classification_success"
    ON_CLASSIFICATION_FAILED = "on_classification_failed"
    
    # Extraction events
    ON_EXTRACTION_SUCCESS = "on_extraction_success"
    ON_EXTRACTION_LOW_CONFIDENCE = "on_extraction_low_confidence"
    ON_EXTRACTION_FAILED = "on_extraction_failed"
    
    # Vendor matching events (AP Invoice specific)
    ON_VENDOR_MATCHED = "on_vendor_matched"
    ON_VENDOR_MISSING = "on_vendor_missing"
    ON_VENDOR_RESOLVED = "on_vendor_resolved"
    
    # BC validation events (AP Invoice specific)
    ON_BC_VALID = "on_bc_valid"
    ON_BC_INVALID = "on_bc_invalid"
    ON_BC_VALIDATION_OVERRIDE = "on_bc_validation_override"
    
    # BC Sandbox lookup events (observation mode)
    ON_BC_LOOKUP_SUCCESS = "on_bc_lookup_success"
    ON_BC_LOOKUP_FAILED = "on_bc_lookup_failed"
    ON_BC_LOOKUP_NOT_FOUND = "on_bc_lookup_not_found"
    ON_BC_VENDOR_VALIDATED = "on_bc_vendor_validated"
    ON_BC_CUSTOMER_VALIDATED = "on_bc_customer_validated"
    ON_BC_PO_VALIDATED = "on_bc_po_validated"
    ON_BC_INVOICE_VALIDATED = "on_bc_invoice_validated"
    
    # PO validation events (PURCHASE_ORDER)
    ON_PO_VALIDATION_STARTED = "on_po_validation_started"
    ON_PO_VALID = "on_po_valid"
    ON_PO_INVALID = "on_po_invalid"
    
    # Credit memo events (SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO)
    ON_CREDIT_LINKED_TO_INVOICE = "on_credit_linked_to_invoice"
    
    # Quality doc events (QUALITY_DOC)
    ON_QUALITY_TAGGED = "on_quality_tagged"
    ON_REVIEW_STARTED = "on_review_started"
    
    # Triage events (OTHER)
    ON_TRIAGE_NEEDED = "on_triage_needed"
    ON_TRIAGE_COMPLETED = "on_triage_completed"
    
    # Review events (STATEMENT, REMINDER, FINANCE_CHARGE_MEMO, QUALITY_DOC)
    ON_MARK_READY_FOR_REVIEW = "on_mark_ready_for_review"
    ON_REVIEWED = "on_reviewed"
    
    # Data/Review events
    ON_DATA_CORRECTED = "on_data_corrected"
    ON_REVIEW_COMPLETE = "on_review_complete"
    
    # Approval events
    ON_MARK_READY_FOR_APPROVAL = "on_mark_ready_for_approval"
    ON_APPROVAL_STARTED = "on_approval_started"
    ON_APPROVED = "on_approved"
    ON_REJECTED = "on_rejected"
    
    # Export events
    ON_EXPORTED = "on_exported"
    ON_ARCHIVED = "on_archived"
    
    # Simulation events (Phase 2 Shadow Pilot)
    ON_EXPORT_SIMULATED = "on_export_simulated"
    ON_BC_CREATE_INVOICE_SIMULATED = "on_bc_create_invoice_simulated"
    ON_BC_ATTACHMENT_SIMULATED = "on_bc_attachment_simulated"
    ON_BC_LINKAGE_SIMULATED = "on_bc_linkage_simulated"
    ON_SIMULATION_SUCCESS = "on_simulation_success"
    ON_SIMULATION_WOULD_FAIL = "on_simulation_would_fail"
    
    # Error events
    ON_ERROR = "on_error"
    ON_RETRY = "on_retry"


# =============================================================================
# WORKFLOW DEFINITIONS BY DOCUMENT TYPE
# =============================================================================

# Format: {current_status: {event: next_status}}
# Each document type has its own transition map

WORKFLOW_DEFINITIONS: Dict[str, Dict[Optional[str], Dict[str, str]]] = {
    # =========================================================================
    # AP_INVOICE: Full workflow with vendor matching and BC validation
    # =========================================================================
    DocType.AP_INVOICE.value: {
        None: {
            WorkflowEvent.ON_CAPTURE.value: WorkflowStatus.CAPTURED.value,
        },
        WorkflowStatus.CAPTURED.value: {
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value: WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_CLASSIFICATION_FAILED.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.CLASSIFIED.value: {
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_EXTRACTION_LOW_CONFIDENCE.value: WorkflowStatus.DATA_CORRECTION_PENDING.value,
            WorkflowEvent.ON_EXTRACTION_FAILED.value: WorkflowStatus.DATA_CORRECTION_PENDING.value,
        },
        WorkflowStatus.EXTRACTED.value: {
            WorkflowEvent.ON_VENDOR_MATCHED.value: WorkflowStatus.BC_VALIDATION_PENDING.value,
            WorkflowEvent.ON_VENDOR_MISSING.value: WorkflowStatus.VENDOR_PENDING.value,
        },
        WorkflowStatus.VENDOR_PENDING.value: {
            WorkflowEvent.ON_VENDOR_RESOLVED.value: WorkflowStatus.BC_VALIDATION_PENDING.value,
            WorkflowEvent.ON_ERROR.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.BC_VALIDATION_PENDING.value: {
            WorkflowEvent.ON_BC_VALID.value: WorkflowStatus.READY_FOR_APPROVAL.value,
            WorkflowEvent.ON_BC_INVALID.value: WorkflowStatus.BC_VALIDATION_FAILED.value,
        },
        WorkflowStatus.BC_VALIDATION_FAILED.value: {
            WorkflowEvent.ON_BC_VALIDATION_OVERRIDE.value: WorkflowStatus.READY_FOR_APPROVAL.value,
            WorkflowEvent.ON_DATA_CORRECTED.value: WorkflowStatus.BC_VALIDATION_PENDING.value,
            WorkflowEvent.ON_ERROR.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.DATA_CORRECTION_PENDING.value: {
            WorkflowEvent.ON_DATA_CORRECTED.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_ERROR.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.READY_FOR_APPROVAL.value: {
            WorkflowEvent.ON_APPROVAL_STARTED.value: WorkflowStatus.APPROVAL_IN_PROGRESS.value,
            WorkflowEvent.ON_APPROVED.value: WorkflowStatus.APPROVED.value,
            WorkflowEvent.ON_REJECTED.value: WorkflowStatus.REJECTED.value,
        },
        WorkflowStatus.APPROVAL_IN_PROGRESS.value: {
            WorkflowEvent.ON_APPROVED.value: WorkflowStatus.APPROVED.value,
            WorkflowEvent.ON_REJECTED.value: WorkflowStatus.REJECTED.value,
        },
        WorkflowStatus.APPROVED.value: {
            WorkflowEvent.ON_EXPORTED.value: WorkflowStatus.EXPORTED.value,
        },
        WorkflowStatus.EXPORTED.value: {
            WorkflowEvent.ON_ARCHIVED.value: WorkflowStatus.ARCHIVED.value,
        },
        WorkflowStatus.REJECTED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.READY_FOR_APPROVAL.value,
        },
        WorkflowStatus.FAILED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.CAPTURED.value,
        },
    },
    
    # =========================================================================
    # SALES_INVOICE: Standard approval workflow
    # States: captured -> classified -> extracted -> ready_for_approval ->
    #         approval_in_progress -> approved -> exported
    # =========================================================================
    DocType.SALES_INVOICE.value: {
        None: {
            WorkflowEvent.ON_CAPTURE.value: WorkflowStatus.CAPTURED.value,
        },
        WorkflowStatus.CAPTURED.value: {
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value: WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_CLASSIFICATION_FAILED.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.CLASSIFIED.value: {
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_EXTRACTION_LOW_CONFIDENCE.value: WorkflowStatus.DATA_CORRECTION_PENDING.value,
            WorkflowEvent.ON_EXTRACTION_FAILED.value: WorkflowStatus.DATA_CORRECTION_PENDING.value,
        },
        WorkflowStatus.EXTRACTED.value: {
            WorkflowEvent.ON_MARK_READY_FOR_APPROVAL.value: WorkflowStatus.READY_FOR_APPROVAL.value,
            # Direct approval path
            WorkflowEvent.ON_APPROVED.value: WorkflowStatus.APPROVED.value,
        },
        WorkflowStatus.DATA_CORRECTION_PENDING.value: {
            WorkflowEvent.ON_DATA_CORRECTED.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_ERROR.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.READY_FOR_APPROVAL.value: {
            WorkflowEvent.ON_APPROVAL_STARTED.value: WorkflowStatus.APPROVAL_IN_PROGRESS.value,
            WorkflowEvent.ON_APPROVED.value: WorkflowStatus.APPROVED.value,
            WorkflowEvent.ON_REJECTED.value: WorkflowStatus.REJECTED.value,
        },
        WorkflowStatus.APPROVAL_IN_PROGRESS.value: {
            WorkflowEvent.ON_APPROVED.value: WorkflowStatus.APPROVED.value,
            WorkflowEvent.ON_REJECTED.value: WorkflowStatus.REJECTED.value,
        },
        WorkflowStatus.APPROVED.value: {
            WorkflowEvent.ON_EXPORTED.value: WorkflowStatus.EXPORTED.value,
        },
        WorkflowStatus.EXPORTED.value: {
            WorkflowEvent.ON_ARCHIVED.value: WorkflowStatus.ARCHIVED.value,
        },
        WorkflowStatus.REJECTED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.READY_FOR_APPROVAL.value,
        },
        WorkflowStatus.FAILED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.CAPTURED.value,
        },
    },
    
    # =========================================================================
    # PURCHASE_ORDER: Workflow with PO validation step
    # States: captured -> classified -> extracted -> validation_pending ->
    #         ready_for_approval -> approval_in_progress -> approved -> exported
    # =========================================================================
    DocType.PURCHASE_ORDER.value: {
        None: {
            WorkflowEvent.ON_CAPTURE.value: WorkflowStatus.CAPTURED.value,
        },
        WorkflowStatus.CAPTURED.value: {
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value: WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_CLASSIFICATION_FAILED.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.CLASSIFIED.value: {
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_EXTRACTION_LOW_CONFIDENCE.value: WorkflowStatus.DATA_CORRECTION_PENDING.value,
            WorkflowEvent.ON_EXTRACTION_FAILED.value: WorkflowStatus.DATA_CORRECTION_PENDING.value,
        },
        WorkflowStatus.EXTRACTED.value: {
            WorkflowEvent.ON_PO_VALIDATION_STARTED.value: WorkflowStatus.VALIDATION_PENDING.value,
            # Direct approval path (skip validation if not needed)
            WorkflowEvent.ON_MARK_READY_FOR_APPROVAL.value: WorkflowStatus.READY_FOR_APPROVAL.value,
        },
        WorkflowStatus.VALIDATION_PENDING.value: {
            WorkflowEvent.ON_PO_VALID.value: WorkflowStatus.READY_FOR_APPROVAL.value,
            WorkflowEvent.ON_PO_INVALID.value: WorkflowStatus.VALIDATION_FAILED.value,
        },
        WorkflowStatus.VALIDATION_FAILED.value: {
            WorkflowEvent.ON_DATA_CORRECTED.value: WorkflowStatus.VALIDATION_PENDING.value,
            WorkflowEvent.ON_MARK_READY_FOR_APPROVAL.value: WorkflowStatus.READY_FOR_APPROVAL.value,  # Override
            WorkflowEvent.ON_ERROR.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.DATA_CORRECTION_PENDING.value: {
            WorkflowEvent.ON_DATA_CORRECTED.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_ERROR.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.READY_FOR_APPROVAL.value: {
            WorkflowEvent.ON_APPROVAL_STARTED.value: WorkflowStatus.APPROVAL_IN_PROGRESS.value,
            WorkflowEvent.ON_APPROVED.value: WorkflowStatus.APPROVED.value,
            WorkflowEvent.ON_REJECTED.value: WorkflowStatus.REJECTED.value,
        },
        WorkflowStatus.APPROVAL_IN_PROGRESS.value: {
            WorkflowEvent.ON_APPROVED.value: WorkflowStatus.APPROVED.value,
            WorkflowEvent.ON_REJECTED.value: WorkflowStatus.REJECTED.value,
        },
        WorkflowStatus.APPROVED.value: {
            WorkflowEvent.ON_EXPORTED.value: WorkflowStatus.EXPORTED.value,
        },
        WorkflowStatus.EXPORTED.value: {
            WorkflowEvent.ON_ARCHIVED.value: WorkflowStatus.ARCHIVED.value,
        },
        WorkflowStatus.REJECTED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.READY_FOR_APPROVAL.value,
        },
        WorkflowStatus.FAILED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.CAPTURED.value,
        },
    },
    
    # =========================================================================
    # SALES_CREDIT_MEMO: Workflow with invoice linkage
    # States: captured -> classified -> extracted -> linked_to_invoice ->
    #         ready_for_approval -> approval_in_progress -> approved -> exported
    # =========================================================================
    DocType.SALES_CREDIT_MEMO.value: {
        None: {
            WorkflowEvent.ON_CAPTURE.value: WorkflowStatus.CAPTURED.value,
        },
        WorkflowStatus.CAPTURED.value: {
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value: WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_CLASSIFICATION_FAILED.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.CLASSIFIED.value: {
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_EXTRACTION_LOW_CONFIDENCE.value: WorkflowStatus.DATA_CORRECTION_PENDING.value,
            WorkflowEvent.ON_EXTRACTION_FAILED.value: WorkflowStatus.DATA_CORRECTION_PENDING.value,
        },
        WorkflowStatus.EXTRACTED.value: {
            WorkflowEvent.ON_CREDIT_LINKED_TO_INVOICE.value: WorkflowStatus.LINKED_TO_INVOICE.value,
            # Direct approval path (skip linkage if not needed)
            WorkflowEvent.ON_MARK_READY_FOR_APPROVAL.value: WorkflowStatus.READY_FOR_APPROVAL.value,
        },
        WorkflowStatus.LINKED_TO_INVOICE.value: {
            WorkflowEvent.ON_MARK_READY_FOR_APPROVAL.value: WorkflowStatus.READY_FOR_APPROVAL.value,
            # Fast-track to approval
            WorkflowEvent.ON_APPROVED.value: WorkflowStatus.APPROVED.value,
        },
        WorkflowStatus.DATA_CORRECTION_PENDING.value: {
            WorkflowEvent.ON_DATA_CORRECTED.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_ERROR.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.READY_FOR_APPROVAL.value: {
            WorkflowEvent.ON_APPROVAL_STARTED.value: WorkflowStatus.APPROVAL_IN_PROGRESS.value,
            WorkflowEvent.ON_APPROVED.value: WorkflowStatus.APPROVED.value,
            WorkflowEvent.ON_REJECTED.value: WorkflowStatus.REJECTED.value,
        },
        WorkflowStatus.APPROVAL_IN_PROGRESS.value: {
            WorkflowEvent.ON_APPROVED.value: WorkflowStatus.APPROVED.value,
            WorkflowEvent.ON_REJECTED.value: WorkflowStatus.REJECTED.value,
        },
        WorkflowStatus.APPROVED.value: {
            WorkflowEvent.ON_EXPORTED.value: WorkflowStatus.EXPORTED.value,
        },
        WorkflowStatus.EXPORTED.value: {
            WorkflowEvent.ON_ARCHIVED.value: WorkflowStatus.ARCHIVED.value,
        },
        WorkflowStatus.REJECTED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.READY_FOR_APPROVAL.value,
        },
        WorkflowStatus.FAILED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.CAPTURED.value,
        },
    },
    
    # =========================================================================
    # PURCHASE_CREDIT_MEMO: Workflow with invoice linkage (same as SALES_CREDIT_MEMO)
    # States: captured -> classified -> extracted -> linked_to_invoice ->
    #         ready_for_approval -> approval_in_progress -> approved -> exported
    # =========================================================================
    DocType.PURCHASE_CREDIT_MEMO.value: {
        None: {
            WorkflowEvent.ON_CAPTURE.value: WorkflowStatus.CAPTURED.value,
        },
        WorkflowStatus.CAPTURED.value: {
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value: WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_CLASSIFICATION_FAILED.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.CLASSIFIED.value: {
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_EXTRACTION_LOW_CONFIDENCE.value: WorkflowStatus.DATA_CORRECTION_PENDING.value,
            WorkflowEvent.ON_EXTRACTION_FAILED.value: WorkflowStatus.DATA_CORRECTION_PENDING.value,
        },
        WorkflowStatus.EXTRACTED.value: {
            WorkflowEvent.ON_CREDIT_LINKED_TO_INVOICE.value: WorkflowStatus.LINKED_TO_INVOICE.value,
            # Direct approval path
            WorkflowEvent.ON_MARK_READY_FOR_APPROVAL.value: WorkflowStatus.READY_FOR_APPROVAL.value,
        },
        WorkflowStatus.LINKED_TO_INVOICE.value: {
            WorkflowEvent.ON_MARK_READY_FOR_APPROVAL.value: WorkflowStatus.READY_FOR_APPROVAL.value,
            WorkflowEvent.ON_APPROVED.value: WorkflowStatus.APPROVED.value,
        },
        WorkflowStatus.DATA_CORRECTION_PENDING.value: {
            WorkflowEvent.ON_DATA_CORRECTED.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_ERROR.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.READY_FOR_APPROVAL.value: {
            WorkflowEvent.ON_APPROVAL_STARTED.value: WorkflowStatus.APPROVAL_IN_PROGRESS.value,
            WorkflowEvent.ON_APPROVED.value: WorkflowStatus.APPROVED.value,
            WorkflowEvent.ON_REJECTED.value: WorkflowStatus.REJECTED.value,
        },
        WorkflowStatus.APPROVAL_IN_PROGRESS.value: {
            WorkflowEvent.ON_APPROVED.value: WorkflowStatus.APPROVED.value,
            WorkflowEvent.ON_REJECTED.value: WorkflowStatus.REJECTED.value,
        },
        WorkflowStatus.APPROVED.value: {
            WorkflowEvent.ON_EXPORTED.value: WorkflowStatus.EXPORTED.value,
        },
        WorkflowStatus.EXPORTED.value: {
            WorkflowEvent.ON_ARCHIVED.value: WorkflowStatus.ARCHIVED.value,
        },
        WorkflowStatus.REJECTED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.READY_FOR_APPROVAL.value,
        },
        WorkflowStatus.FAILED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.CAPTURED.value,
        },
    },
    
    # =========================================================================
    # STATEMENT: High volume, fast path review workflow
    # States: captured -> classified -> extracted -> ready_for_review ->
    #         reviewed -> archived/exported
    # =========================================================================
    DocType.STATEMENT.value: {
        None: {
            WorkflowEvent.ON_CAPTURE.value: WorkflowStatus.CAPTURED.value,
        },
        WorkflowStatus.CAPTURED.value: {
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value: WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_CLASSIFICATION_FAILED.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.CLASSIFIED.value: {
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_EXTRACTION_FAILED.value: WorkflowStatus.READY_FOR_REVIEW.value,
        },
        WorkflowStatus.EXTRACTED.value: {
            WorkflowEvent.ON_MARK_READY_FOR_REVIEW.value: WorkflowStatus.READY_FOR_REVIEW.value,
            # Fast-track to export
            WorkflowEvent.ON_EXPORTED.value: WorkflowStatus.EXPORTED.value,
            WorkflowEvent.ON_ARCHIVED.value: WorkflowStatus.ARCHIVED.value,
        },
        WorkflowStatus.READY_FOR_REVIEW.value: {
            WorkflowEvent.ON_REVIEWED.value: WorkflowStatus.REVIEWED.value,
            WorkflowEvent.ON_ERROR.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.REVIEWED.value: {
            WorkflowEvent.ON_ARCHIVED.value: WorkflowStatus.ARCHIVED.value,
            WorkflowEvent.ON_EXPORTED.value: WorkflowStatus.EXPORTED.value,
        },
        WorkflowStatus.EXPORTED.value: {
            WorkflowEvent.ON_ARCHIVED.value: WorkflowStatus.ARCHIVED.value,
        },
        WorkflowStatus.FAILED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.CAPTURED.value,
        },
    },
    
    # =========================================================================
    # REMINDER: Simple review workflow (shared pattern with FINANCE_CHARGE_MEMO)
    # States: captured -> classified -> extracted -> ready_for_review -> reviewed -> exported
    # =========================================================================
    DocType.REMINDER.value: {
        None: {
            WorkflowEvent.ON_CAPTURE.value: WorkflowStatus.CAPTURED.value,
        },
        WorkflowStatus.CAPTURED.value: {
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value: WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_CLASSIFICATION_FAILED.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.CLASSIFIED.value: {
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_EXTRACTION_FAILED.value: WorkflowStatus.READY_FOR_REVIEW.value,
        },
        WorkflowStatus.EXTRACTED.value: {
            WorkflowEvent.ON_MARK_READY_FOR_REVIEW.value: WorkflowStatus.READY_FOR_REVIEW.value,
            # Fast-track to export
            WorkflowEvent.ON_EXPORTED.value: WorkflowStatus.EXPORTED.value,
        },
        WorkflowStatus.READY_FOR_REVIEW.value: {
            WorkflowEvent.ON_REVIEWED.value: WorkflowStatus.REVIEWED.value,
            WorkflowEvent.ON_ERROR.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.REVIEWED.value: {
            WorkflowEvent.ON_EXPORTED.value: WorkflowStatus.EXPORTED.value,
        },
        WorkflowStatus.EXPORTED.value: {
            WorkflowEvent.ON_ARCHIVED.value: WorkflowStatus.ARCHIVED.value,
        },
        WorkflowStatus.FAILED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.CAPTURED.value,
        },
    },
    
    # =========================================================================
    # FINANCE_CHARGE_MEMO: Simple review workflow (same as REMINDER)
    # States: captured -> classified -> extracted -> ready_for_review -> reviewed -> exported
    # =========================================================================
    DocType.FINANCE_CHARGE_MEMO.value: {
        None: {
            WorkflowEvent.ON_CAPTURE.value: WorkflowStatus.CAPTURED.value,
        },
        WorkflowStatus.CAPTURED.value: {
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value: WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_CLASSIFICATION_FAILED.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.CLASSIFIED.value: {
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_EXTRACTION_FAILED.value: WorkflowStatus.READY_FOR_REVIEW.value,
        },
        WorkflowStatus.EXTRACTED.value: {
            WorkflowEvent.ON_MARK_READY_FOR_REVIEW.value: WorkflowStatus.READY_FOR_REVIEW.value,
            WorkflowEvent.ON_EXPORTED.value: WorkflowStatus.EXPORTED.value,
        },
        WorkflowStatus.READY_FOR_REVIEW.value: {
            WorkflowEvent.ON_REVIEWED.value: WorkflowStatus.REVIEWED.value,
            WorkflowEvent.ON_ERROR.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.REVIEWED.value: {
            WorkflowEvent.ON_EXPORTED.value: WorkflowStatus.EXPORTED.value,
        },
        WorkflowStatus.EXPORTED.value: {
            WorkflowEvent.ON_ARCHIVED.value: WorkflowStatus.ARCHIVED.value,
        },
        WorkflowStatus.FAILED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.CAPTURED.value,
        },
    },
    
    # =========================================================================
    # QUALITY_DOC: Quality review workflow with tagging step
    # States: captured -> classified -> extracted -> tagged -> ready_for_review ->
    #         review_in_progress -> reviewed -> exported
    # =========================================================================
    DocType.QUALITY_DOC.value: {
        None: {
            WorkflowEvent.ON_CAPTURE.value: WorkflowStatus.CAPTURED.value,
        },
        WorkflowStatus.CAPTURED.value: {
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value: WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_CLASSIFICATION_FAILED.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.CLASSIFIED.value: {
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_EXTRACTION_FAILED.value: WorkflowStatus.READY_FOR_REVIEW.value,
        },
        WorkflowStatus.EXTRACTED.value: {
            WorkflowEvent.ON_QUALITY_TAGGED.value: WorkflowStatus.TAGGED.value,
            # Direct review path
            WorkflowEvent.ON_MARK_READY_FOR_REVIEW.value: WorkflowStatus.READY_FOR_REVIEW.value,
        },
        WorkflowStatus.TAGGED.value: {
            WorkflowEvent.ON_MARK_READY_FOR_REVIEW.value: WorkflowStatus.READY_FOR_REVIEW.value,
        },
        WorkflowStatus.READY_FOR_REVIEW.value: {
            WorkflowEvent.ON_REVIEW_STARTED.value: WorkflowStatus.REVIEW_IN_PROGRESS.value,
            WorkflowEvent.ON_REVIEWED.value: WorkflowStatus.REVIEWED.value,
            WorkflowEvent.ON_REJECTED.value: WorkflowStatus.REJECTED.value,
        },
        WorkflowStatus.REVIEW_IN_PROGRESS.value: {
            WorkflowEvent.ON_REVIEWED.value: WorkflowStatus.REVIEWED.value,
            WorkflowEvent.ON_REJECTED.value: WorkflowStatus.REJECTED.value,
        },
        WorkflowStatus.REVIEWED.value: {
            WorkflowEvent.ON_EXPORTED.value: WorkflowStatus.EXPORTED.value,
        },
        WorkflowStatus.EXPORTED.value: {
            WorkflowEvent.ON_ARCHIVED.value: WorkflowStatus.ARCHIVED.value,
        },
        WorkflowStatus.REJECTED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.READY_FOR_REVIEW.value,
        },
        WorkflowStatus.FAILED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.CAPTURED.value,
        },
    },
    
    # =========================================================================
    # OTHER: Triage workflow for unclassified/edge case documents
    # States: captured -> classified -> extracted -> triage_pending ->
    #         triage_completed -> exported
    # =========================================================================
    DocType.OTHER.value: {
        None: {
            WorkflowEvent.ON_CAPTURE.value: WorkflowStatus.CAPTURED.value,
        },
        WorkflowStatus.CAPTURED.value: {
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value: WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_CLASSIFICATION_FAILED.value: WorkflowStatus.TRIAGE_PENDING.value,
        },
        WorkflowStatus.CLASSIFIED.value: {
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value: WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_EXTRACTION_FAILED.value: WorkflowStatus.TRIAGE_PENDING.value,
            WorkflowEvent.ON_TRIAGE_NEEDED.value: WorkflowStatus.TRIAGE_PENDING.value,
        },
        WorkflowStatus.EXTRACTED.value: {
            WorkflowEvent.ON_TRIAGE_NEEDED.value: WorkflowStatus.TRIAGE_PENDING.value,
            WorkflowEvent.ON_TRIAGE_COMPLETED.value: WorkflowStatus.TRIAGE_COMPLETED.value,
            # Direct export for simple OTHER documents
            WorkflowEvent.ON_EXPORTED.value: WorkflowStatus.EXPORTED.value,
        },
        WorkflowStatus.TRIAGE_PENDING.value: {
            WorkflowEvent.ON_TRIAGE_COMPLETED.value: WorkflowStatus.TRIAGE_COMPLETED.value,
            WorkflowEvent.ON_ERROR.value: WorkflowStatus.FAILED.value,
        },
        WorkflowStatus.TRIAGE_COMPLETED.value: {
            WorkflowEvent.ON_EXPORTED.value: WorkflowStatus.EXPORTED.value,
        },
        WorkflowStatus.EXPORTED.value: {
            WorkflowEvent.ON_ARCHIVED.value: WorkflowStatus.ARCHIVED.value,
        },
        WorkflowStatus.FAILED.value: {
            WorkflowEvent.ON_RETRY.value: WorkflowStatus.CAPTURED.value,
        },
    },
}


# =============================================================================
# WORKFLOW HISTORY ENTRY
# =============================================================================

class WorkflowHistoryEntry:
    """Represents a single entry in the workflow history."""
    
    def __init__(
        self,
        from_status: Optional[str],
        to_status: str,
        event: str,
        actor: str = "system",
        reason: Optional[str] = None,
        metadata: Optional[Dict] = None
    ):
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.from_status = from_status
        self.to_status = to_status
        self.event = event
        self.actor = actor
        self.reason = reason
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "event": self.event,
            "actor": self.actor,
            "reason": self.reason,
            "metadata": self.metadata
        }


# =============================================================================
# DOCUMENT CLASSIFICATION HELPER
# =============================================================================

class DocumentClassifier:
    """
    Helper class for classifying documents based on various signals.
    Uses deterministic rules based on metadata, source markers, etc.
    """
    
    @staticmethod
    def classify_from_zetadocs_set(set_code: str) -> Tuple[DocType, Optional[CaptureChannel]]:
        """Classify based on Zetadocs document set code."""
        if set_code in ZETADOCS_SET_MAPPING:
            return ZETADOCS_SET_MAPPING[set_code]
        return (DocType.OTHER, None)
    
    @staticmethod
    def classify_from_square9_workflow(workflow_name: str) -> DocType:
        """Classify based on Square9 workflow name."""
        if workflow_name in SQUARE9_WORKFLOW_MAPPING:
            return SQUARE9_WORKFLOW_MAPPING[workflow_name]
        return DocType.OTHER
    
    @staticmethod
    def classify_from_mailbox_category(category: str) -> DocType:
        """Classify based on mailbox category (AP, Sales, etc.)."""
        category_upper = (category or "").upper()
        if category_upper == "AP":
            return DocType.AP_INVOICE
        elif category_upper == "SALES":
            return DocType.SALES_INVOICE
        elif category_upper == "PURCHASE":
            return DocType.PURCHASE_ORDER
        return DocType.OTHER
    
    @staticmethod
    def classify_from_ai_result(suggested_type: str) -> DocType:
        """Classify based on AI classification result."""
        type_map = {
            "AP_Invoice": DocType.AP_INVOICE,
            "AP Invoice": DocType.AP_INVOICE,
            "Purchase Invoice": DocType.AP_INVOICE,
            "Sales_Invoice": DocType.SALES_INVOICE,
            "Sales Invoice": DocType.SALES_INVOICE,
            "Sales_Order": DocType.SALES_INVOICE,
            "Purchase_Order": DocType.PURCHASE_ORDER,
            "Purchase Order": DocType.PURCHASE_ORDER,
            "Credit_Memo": DocType.SALES_CREDIT_MEMO,
            "Sales_Credit_Memo": DocType.SALES_CREDIT_MEMO,
            "Statement": DocType.STATEMENT,
            "Reminder": DocType.REMINDER,
            "Quality_Issue": DocType.QUALITY_DOC,
        }
        return type_map.get(suggested_type, DocType.OTHER)
    
    @staticmethod
    def determine_source_system(
        has_zetadocs_set: bool = False,
        has_square9_workflow: bool = False,
        is_migration: bool = False
    ) -> SourceSystem:
        """Determine the source system based on metadata."""
        if is_migration:
            return SourceSystem.MIGRATION
        if has_zetadocs_set:
            return SourceSystem.ZETADOCS
        if has_square9_workflow:
            return SourceSystem.SQUARE9
        return SourceSystem.GPI_HUB_NATIVE
    
    @staticmethod
    def determine_capture_channel(source: str) -> CaptureChannel:
        """Determine capture channel from source string."""
        source_lower = (source or "").lower()
        if "email" in source_lower:
            return CaptureChannel.EMAIL
        if "upload" in source_lower:
            return CaptureChannel.UPLOAD
        if "api" in source_lower:
            return CaptureChannel.API
        if "migration" in source_lower:
            return CaptureChannel.MIGRATION_JOB
        return CaptureChannel.UNKNOWN


# =============================================================================
# MAIN WORKFLOW ENGINE
# =============================================================================

class WorkflowEngine:
    """
    Multi-type document workflow state machine.
    
    This class handles workflow transitions for all document types.
    It reads doc_type from the document and chooses the appropriate state machine.
    """
    
    @staticmethod
    def get_doc_type(document: Dict) -> str:
        """Get the document type, defaulting to OTHER if not set."""
        return document.get("doc_type", DocType.OTHER.value)
    
    @staticmethod
    def get_current_status(document: Dict) -> Optional[str]:
        """Get the current workflow status from a document."""
        return document.get("workflow_status")
    
    @staticmethod
    def get_workflow_history(document: Dict) -> List[Dict]:
        """Get the workflow history from a document."""
        return document.get("workflow_history", [])
    
    @staticmethod
    def get_workflow_definition(doc_type: str) -> Dict:
        """Get the workflow definition for a document type."""
        if doc_type in WORKFLOW_DEFINITIONS:
            return WORKFLOW_DEFINITIONS[doc_type]
        # Default to OTHER workflow for unknown types
        return WORKFLOW_DEFINITIONS[DocType.OTHER.value]
    
    @staticmethod
    def can_transition(
        doc_type: str,
        current_status: Optional[str],
        event: str
    ) -> Tuple[bool, Optional[str], str]:
        """
        Check if a transition is valid for the given document type.
        
        Returns:
            (can_transition, next_status, reason)
        """
        workflow_def = WorkflowEngine.get_workflow_definition(doc_type)
        
        # Handle enum values
        current_key = current_status.value if isinstance(current_status, WorkflowStatus) else current_status
        event_key = event.value if isinstance(event, WorkflowEvent) else event
        
        # Get transitions for current status
        status_transitions = workflow_def.get(current_key)
        
        if status_transitions is None:
            return (False, None, f"No transitions defined for status '{current_status}' in {doc_type} workflow")
        
        # Check if event is valid for this status
        next_status = status_transitions.get(event_key)
        
        if next_status is None:
            valid_events = list(status_transitions.keys())
            return (False, None, f"Event '{event}' not valid for status '{current_status}' in {doc_type} workflow. Valid: {valid_events}")
        
        return (True, next_status, "Transition allowed")
    
    @staticmethod
    def advance_workflow(
        document: Dict,
        event: str,
        context: Optional[Dict] = None,
        actor: str = "system"
    ) -> Tuple[Dict, WorkflowHistoryEntry, bool]:
        """
        Advance a document through the workflow based on an event.
        
        Args:
            document: The document dict (will be modified in place)
            event: The workflow event that triggered this transition
            context: Optional context data (user_id, reason, metadata, etc.)
            actor: Who/what triggered this transition
        
        Returns:
            (updated_document, history_entry, success)
        """
        context = context or {}
        doc_type = WorkflowEngine.get_doc_type(document)
        current_status = WorkflowEngine.get_current_status(document)
        
        # Check if transition is valid
        can_transition, next_status, reason = WorkflowEngine.can_transition(
            doc_type, current_status, event
        )
        
        if not can_transition:
            logger.warning(
                "Invalid workflow transition: doc=%s, type=%s, current=%s, event=%s, reason=%s",
                document.get("id"), doc_type, current_status, event, reason
            )
            history_entry = WorkflowHistoryEntry(
                from_status=current_status,
                to_status=current_status,
                event=event,
                actor=actor,
                reason=f"Transition blocked: {reason}",
                metadata=context.get("metadata", {})
            )
            return (document, history_entry, False)
        
        # Create history entry
        history_entry = WorkflowHistoryEntry(
            from_status=current_status,
            to_status=next_status,
            event=event,
            actor=actor,
            reason=context.get("reason"),
            metadata=context.get("metadata", {})
        )
        
        # Update document
        document["workflow_status"] = next_status
        
        # Initialize or append to workflow history
        if "workflow_history" not in document:
            document["workflow_history"] = []
        document["workflow_history"].append(history_entry.to_dict())
        
        # Update timestamp
        document["workflow_status_updated_utc"] = datetime.now(timezone.utc).isoformat()
        
        logger.info(
            "Workflow transition: doc=%s, type=%s, %s -> %s (event=%s, actor=%s)",
            document.get("id"), doc_type, current_status, next_status, event, actor
        )
        
        return (document, history_entry, True)
    
    @staticmethod
    def initialize_workflow(
        document: Dict,
        doc_type: str = None,
        source_system: str = None,
        capture_channel: str = None,
        actor: str = "system"
    ) -> Dict:
        """
        Initialize workflow tracking on a new document.
        Sets classification fields and initial workflow status.
        """
        now = datetime.now(timezone.utc).isoformat()
        
        # Set classification fields
        document["doc_type"] = doc_type or document.get("doc_type", DocType.OTHER.value)
        document["source_system"] = source_system or document.get("source_system", SourceSystem.GPI_HUB_NATIVE.value)
        document["capture_channel"] = capture_channel or document.get("capture_channel", CaptureChannel.UNKNOWN.value)
        
        # Initialize workflow
        document["workflow_status"] = WorkflowStatus.CAPTURED.value
        document["workflow_history"] = [{
            "timestamp": now,
            "from_status": None,
            "to_status": WorkflowStatus.CAPTURED.value,
            "event": WorkflowEvent.ON_CAPTURE.value,
            "actor": actor,
            "reason": f"Document captured: {document['doc_type']}",
            "metadata": {
                "doc_type": document["doc_type"],
                "source_system": document["source_system"],
                "capture_channel": document["capture_channel"]
            }
        }]
        document["workflow_status_updated_utc"] = now
        
        return document
    
    @staticmethod
    def is_ap_specific_status(status: str) -> bool:
        """Check if a status is AP Invoice specific."""
        ap_specific = [
            WorkflowStatus.VENDOR_PENDING.value,
            WorkflowStatus.BC_VALIDATION_PENDING.value,
            WorkflowStatus.BC_VALIDATION_FAILED.value,
        ]
        return status in ap_specific
    
    @staticmethod
    def get_exception_statuses(doc_type: str = None) -> List[str]:
        """Get exception statuses (statuses requiring manual intervention) for a document type."""
        if doc_type == DocType.AP_INVOICE.value:
            return [
                WorkflowStatus.VENDOR_PENDING.value,
                WorkflowStatus.BC_VALIDATION_PENDING.value,
                WorkflowStatus.BC_VALIDATION_FAILED.value,
                WorkflowStatus.DATA_CORRECTION_PENDING.value,
            ]
        elif doc_type == DocType.PURCHASE_ORDER.value:
            return [
                WorkflowStatus.VALIDATION_PENDING.value,
                WorkflowStatus.VALIDATION_FAILED.value,
                WorkflowStatus.DATA_CORRECTION_PENDING.value,
            ]
        elif doc_type in [DocType.SALES_CREDIT_MEMO.value, DocType.PURCHASE_CREDIT_MEMO.value]:
            return [
                WorkflowStatus.DATA_CORRECTION_PENDING.value,
            ]
        elif doc_type == DocType.QUALITY_DOC.value:
            return [
                WorkflowStatus.READY_FOR_REVIEW.value,
                WorkflowStatus.REVIEW_IN_PROGRESS.value,
            ]
        elif doc_type == DocType.OTHER.value:
            return [
                WorkflowStatus.TRIAGE_PENDING.value,
            ]
        elif doc_type in [DocType.STATEMENT.value, DocType.REMINDER.value, DocType.FINANCE_CHARGE_MEMO.value]:
            return [
                WorkflowStatus.READY_FOR_REVIEW.value,
            ]
        return [
            WorkflowStatus.DATA_CORRECTION_PENDING.value,
        ]
    
    @staticmethod
    def get_terminal_statuses() -> List[str]:
        """Get terminal statuses (applies to all types)."""
        return [
            WorkflowStatus.EXPORTED.value,
            WorkflowStatus.ARCHIVED.value,
            WorkflowStatus.REJECTED.value,
            WorkflowStatus.APPROVED.value,  # Approved is also terminal for most types
        ]
    
    @staticmethod
    def get_active_statuses() -> List[str]:
        """Get non-terminal statuses (document still requires processing)."""
        terminal = [
            WorkflowStatus.EXPORTED.value,
            WorkflowStatus.ARCHIVED.value,
            WorkflowStatus.FAILED.value,
        ]
        return [s.value for s in WorkflowStatus if s.value not in terminal]
    
    @staticmethod
    def get_all_statuses() -> List[str]:
        """Get all possible workflow status values."""
        return [s.value for s in WorkflowStatus]
    
    @staticmethod
    def get_all_events() -> List[str]:
        """Get all possible workflow event values."""
        return [e.value for e in WorkflowEvent]
    
    @staticmethod
    def get_all_doc_types() -> List[str]:
        """Get all supported document types."""
        return [d.value for d in DocType]
    
    @staticmethod
    def get_valid_statuses_for_doc_type(doc_type: str) -> List[str]:
        """Get all valid statuses for a specific document type based on its workflow definition."""
        workflow_def = WorkflowEngine.get_workflow_definition(doc_type)
        statuses = set()
        for current_status, transitions in workflow_def.items():
            if current_status is not None:
                statuses.add(current_status)
            for next_status in transitions.values():
                statuses.add(next_status)
        return list(statuses)
    
    @staticmethod
    def get_valid_events_for_status(doc_type: str, status: str) -> List[str]:
        """Get valid events that can be triggered from a specific status for a document type."""
        workflow_def = WorkflowEngine.get_workflow_definition(doc_type)
        status_transitions = workflow_def.get(status, {})
        return list(status_transitions.keys())
    
    @staticmethod
    def get_queue_for_status(status: str, doc_type: str = None) -> Optional[str]:
        """Map a workflow status to its corresponding queue name."""
        queue_mapping = {
            # AP Invoice specific
            WorkflowStatus.VENDOR_PENDING.value: "vendor_pending",
            WorkflowStatus.BC_VALIDATION_PENDING.value: "bc_validation_pending",
            WorkflowStatus.BC_VALIDATION_FAILED.value: "bc_validation_failed",
            # PO specific
            WorkflowStatus.VALIDATION_PENDING.value: "validation_pending",
            WorkflowStatus.VALIDATION_FAILED.value: "validation_failed",
            # Credit memo specific
            WorkflowStatus.LINKED_TO_INVOICE.value: "linked_to_invoice",
            # Quality doc specific
            WorkflowStatus.TAGGED.value: "tagged",
            WorkflowStatus.REVIEW_IN_PROGRESS.value: "review_in_progress",
            # OTHER specific
            WorkflowStatus.TRIAGE_PENDING.value: "triage_pending",
            WorkflowStatus.TRIAGE_COMPLETED.value: "triage_completed",
            # Generic
            WorkflowStatus.DATA_CORRECTION_PENDING.value: "data_correction_pending",
            WorkflowStatus.REVIEW_PENDING.value: "review_pending",
            WorkflowStatus.READY_FOR_REVIEW.value: "ready_for_review",
            WorkflowStatus.REVIEWED.value: "reviewed",
            WorkflowStatus.READY_FOR_APPROVAL.value: "ready_for_approval",
            WorkflowStatus.APPROVAL_IN_PROGRESS.value: "approval_in_progress",
        }
        return queue_mapping.get(status)
    
    @staticmethod
    def calculate_time_in_status(document: Dict, status: str) -> Optional[float]:
        """Calculate time (seconds) a document spent in a specific status."""
        history = document.get("workflow_history", [])
        
        enter_time = None
        exit_time = None
        
        for entry in history:
            if entry.get("to_status") == status:
                enter_time = entry.get("timestamp")
            if entry.get("from_status") == status:
                exit_time = entry.get("timestamp")
        
        if enter_time:
            exit_dt = datetime.fromisoformat(exit_time) if exit_time else datetime.now(timezone.utc)
            enter_dt = datetime.fromisoformat(enter_time)
            return (exit_dt - enter_dt).total_seconds()
        
        return None


# =============================================================================
# BC VALIDATION WORKFLOW HELPERS
# =============================================================================

class BCValidationHistoryEntry:
    """
    Creates workflow history entries specifically for BC validation events.
    Used during observation mode to track BC lookup results without affecting workflow state.
    """
    
    @staticmethod
    def create_bc_lookup_entry(
        event: str,
        lookup_type: str,
        lookup_key: str,
        bc_result: Dict,
        actor: str = "bc_sandbox_service",
        observation_only: bool = True
    ) -> Dict:
        """
        Create a workflow history entry for a BC lookup.
        
        Args:
            event: The WorkflowEvent value (e.g., ON_BC_LOOKUP_SUCCESS)
            lookup_type: Type of lookup (vendor, customer, po, invoice)
            lookup_key: The key used for lookup (vendor_number, etc.)
            bc_result: The BCLookupResult.to_dict() data
            actor: Who/what performed the lookup
            observation_only: Whether this is observation mode (no workflow changes)
            
        Returns:
            Workflow history entry dict
        """
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "actor": actor,
            "bc_validation": {
                "lookup_type": lookup_type,
                "lookup_key": lookup_key,
                "status": bc_result.get("status"),
                "timing_ms": bc_result.get("timing_ms"),
                "endpoint": bc_result.get("endpoint"),
                "response_size": bc_result.get("response_size"),
                "found": bc_result.get("status") in ["success", "demo_mode"] and bool(bc_result.get("data")),
                "error": bc_result.get("error"),
            },
            "observation_only": observation_only,
            "metadata": {
                "bc_data_summary": _summarize_bc_data(bc_result.get("data", {}), lookup_type)
            }
        }
    
    @staticmethod
    def create_bc_validation_entry(
        validation_type: str,
        validation_result: Dict,
        actor: str = "bc_sandbox_service"
    ) -> Dict:
        """
        Create a workflow history entry for a full BC validation.
        
        Args:
            validation_type: Type of validation (ap_invoice, sales_invoice, purchase_order)
            validation_result: The full validation result dict
            actor: Who/what performed the validation
            
        Returns:
            Workflow history entry dict
        """
        checks_passed = sum(1 for c in validation_result.get("checks", []) if c.get("passed"))
        checks_total = len(validation_result.get("checks", []))
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": WorkflowEvent.ON_BC_LOOKUP_SUCCESS.value if validation_result.get("overall_valid") else WorkflowEvent.ON_BC_LOOKUP_FAILED.value,
            "actor": actor,
            "bc_validation": {
                "validation_type": validation_type,
                "overall_valid": validation_result.get("overall_valid"),
                "checks_passed": checks_passed,
                "checks_total": checks_total,
                "total_timing_ms": validation_result.get("total_timing_ms"),
                "warnings": validation_result.get("warnings", []),
                "errors": validation_result.get("errors", []),
            },
            "observation_only": validation_result.get("observation_only", True),
            "pilot_mode": validation_result.get("pilot_mode", True),
            "metadata": {
                "checks": [
                    {
                        "name": c.get("check_name"),
                        "passed": c.get("passed"),
                        "timing_ms": c.get("bc_lookup", {}).get("timing_ms")
                    }
                    for c in validation_result.get("checks", [])
                ]
            }
        }


def _summarize_bc_data(data: Dict, lookup_type: str) -> Dict:
    """Summarize BC data for workflow history (exclude sensitive/large fields)."""
    if not data:
        return {}
    
    summary = {}
    
    if lookup_type == "vendor":
        summary = {
            "number": data.get("number"),
            "displayName": data.get("displayName"),
            "balance": data.get("balance")
        }
    elif lookup_type == "customer":
        summary = {
            "number": data.get("number"),
            "displayName": data.get("displayName"),
            "balance": data.get("balance")
        }
    elif lookup_type == "purchase_order":
        summary = {
            "number": data.get("number"),
            "vendorNumber": data.get("vendorNumber"),
            "status": data.get("status"),
            "totalAmount": data.get("totalAmount")
        }
    elif lookup_type == "purchase_invoice":
        summary = {
            "number": data.get("number"),
            "vendorNumber": data.get("vendorNumber"),
            "vendorInvoiceNumber": data.get("vendorInvoiceNumber"),
            "status": data.get("status"),
            "totalAmountIncludingTax": data.get("totalAmountIncludingTax")
        }
    elif lookup_type == "sales_invoice":
        summary = {
            "number": data.get("number"),
            "customerNumber": data.get("customerNumber"),
            "status": data.get("status"),
            "totalAmountIncludingTax": data.get("totalAmountIncludingTax")
        }
    
    return summary


# =============================================================================
# BACKWARD COMPATIBILITY
# =============================================================================

# Keep old WORKFLOW_TRANSITIONS for backward compatibility (maps to AP_INVOICE)
WORKFLOW_TRANSITIONS = WORKFLOW_DEFINITIONS[DocType.AP_INVOICE.value]
