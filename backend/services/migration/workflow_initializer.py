"""
GPI Document Hub - Workflow Initializer for Migration

This module determines the initial workflow state for migrated documents
based on their legacy status flags and document type.

The goal is to place migrated documents in sensible final states so they
don't appear in active work queues unless appropriate.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from ..workflow_engine import (
    WorkflowStatus, WorkflowEvent, DocType, WorkflowEngine, WorkflowHistoryEntry
)
from .sources import LegacyDocumentMetadata

logger = logging.getLogger(__name__)


@dataclass
class WorkflowInitializationResult:
    """Result of workflow initialization for a migrated document."""
    workflow_status: str
    workflow_history: List[Dict[str, Any]]
    reason: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_status": self.workflow_status,
            "workflow_history": self.workflow_history,
            "reason": self.reason
        }


class WorkflowInitializer:
    """
    Determines the initial workflow state for migrated documents.
    
    This class maps legacy status flags to appropriate GPI Hub workflow states,
    ensuring migrated documents appear in sensible states based on their
    processing history in the source system.
    """
    
    @classmethod
    def initialize(
        cls,
        doc_type: str,
        metadata: LegacyDocumentMetadata,
        migration_timestamp: Optional[str] = None
    ) -> WorkflowInitializationResult:
        """
        Determine the initial workflow state for a migrated document.
        
        Args:
            doc_type: The classified document type
            metadata: Legacy document metadata with status flags
            migration_timestamp: Optional timestamp for the migration (defaults to now)
            
        Returns:
            WorkflowInitializationResult with status, history, and reason
        """
        if migration_timestamp is None:
            migration_timestamp = datetime.now(timezone.utc).isoformat()
        
        # Dispatch to type-specific handler
        handler = cls._get_handler(doc_type)
        status, reason = handler(metadata)
        
        # Build workflow history entry
        history_entry = {
            "timestamp": migration_timestamp,
            "user": "migration_job",
            "from_status": None,
            "to_status": status,
            "reason": f"Imported from {metadata.legacy_system}: {reason}",
            "metadata": {
                "legacy_id": metadata.legacy_id,
                "legacy_system": metadata.legacy_system,
            }
        }
        
        return WorkflowInitializationResult(
            workflow_status=status,
            workflow_history=[history_entry],
            reason=reason
        )
    
    @classmethod
    def _get_handler(cls, doc_type: str):
        """Get the appropriate handler for the document type."""
        handlers = {
            DocType.AP_INVOICE.value: cls._initialize_ap_invoice,
            DocType.SALES_INVOICE.value: cls._initialize_sales_invoice,
            DocType.PURCHASE_ORDER.value: cls._initialize_purchase_order,
            DocType.SALES_CREDIT_MEMO.value: cls._initialize_credit_memo,
            DocType.PURCHASE_CREDIT_MEMO.value: cls._initialize_credit_memo,
            DocType.STATEMENT.value: cls._initialize_statement,
            DocType.REMINDER.value: cls._initialize_reminder,
            DocType.FINANCE_CHARGE_MEMO.value: cls._initialize_finance_charge_memo,
            DocType.QUALITY_DOC.value: cls._initialize_quality_doc,
            DocType.OTHER.value: cls._initialize_other,
        }
        return handlers.get(doc_type, cls._initialize_default)
    
    @classmethod
    def _initialize_ap_invoice(
        cls, 
        metadata: LegacyDocumentMetadata
    ) -> tuple[str, str]:
        """
        Initialize workflow for AP Invoice.
        
        State priority:
        1. exported - if posted/paid/exported
        2. approved - if approved but not yet exported
        3. ready_for_approval - if approved in legacy but we want review
        4. extracted - otherwise (requires processing)
        """
        if metadata.is_exported or (metadata.is_posted and metadata.is_paid):
            return (
                WorkflowStatus.EXPORTED.value,
                "Legacy status: exported/posted+paid"
            )
        
        if metadata.is_posted:
            return (
                WorkflowStatus.APPROVED.value,
                "Legacy status: posted (awaiting payment)"
            )
        
        if metadata.is_approved:
            return (
                WorkflowStatus.APPROVED.value,
                "Legacy status: approved"
            )
        
        if metadata.is_canceled or metadata.is_voided:
            return (
                WorkflowStatus.REJECTED.value,
                "Legacy status: canceled/voided"
            )
        
        # Default: needs processing
        return (
            WorkflowStatus.EXTRACTED.value,
            "Legacy status: pending processing"
        )
    
    @classmethod
    def _initialize_sales_invoice(
        cls,
        metadata: LegacyDocumentMetadata
    ) -> tuple[str, str]:
        """
        Initialize workflow for Sales Invoice.
        
        State priority:
        1. exported - if posted/invoiced/exported
        2. approved - if approved
        3. extracted - otherwise
        """
        if metadata.is_exported or metadata.is_posted:
            return (
                WorkflowStatus.EXPORTED.value,
                "Legacy status: posted/exported"
            )
        
        if metadata.is_approved:
            return (
                WorkflowStatus.APPROVED.value,
                "Legacy status: approved"
            )
        
        if metadata.is_canceled or metadata.is_voided:
            return (
                WorkflowStatus.REJECTED.value,
                "Legacy status: canceled/voided"
            )
        
        return (
            WorkflowStatus.EXTRACTED.value,
            "Legacy status: pending processing"
        )
    
    @classmethod
    def _initialize_purchase_order(
        cls,
        metadata: LegacyDocumentMetadata
    ) -> tuple[str, str]:
        """
        Initialize workflow for Purchase Order.
        
        State priority:
        1. exported - if closed (fully processed)
        2. approved - if approved but not closed
        3. validation_pending - if open and awaiting validation
        4. extracted - otherwise
        """
        if metadata.is_closed:
            return (
                WorkflowStatus.EXPORTED.value,
                "Legacy status: closed (fully processed)"
            )
        
        if metadata.is_approved or metadata.is_posted:
            return (
                WorkflowStatus.APPROVED.value,
                "Legacy status: approved/posted"
            )
        
        if metadata.is_canceled or metadata.is_voided:
            return (
                WorkflowStatus.REJECTED.value,
                "Legacy status: canceled/voided"
            )
        
        # Open PO that may need validation
        if metadata.vendor_no or metadata.po_number:
            return (
                WorkflowStatus.VALIDATION_PENDING.value,
                "Legacy status: open, awaiting validation"
            )
        
        return (
            WorkflowStatus.EXTRACTED.value,
            "Legacy status: pending processing"
        )
    
    @classmethod
    def _initialize_credit_memo(
        cls,
        metadata: LegacyDocumentMetadata
    ) -> tuple[str, str]:
        """
        Initialize workflow for Sales/Purchase Credit Memo.
        
        State priority:
        1. exported - if posted/exported
        2. approved - if approved
        3. linked_to_invoice - if we have invoice reference
        4. extracted - otherwise
        """
        if metadata.is_exported or metadata.is_posted:
            return (
                WorkflowStatus.EXPORTED.value,
                "Legacy status: posted/exported"
            )
        
        if metadata.is_approved:
            return (
                WorkflowStatus.APPROVED.value,
                "Legacy status: approved"
            )
        
        if metadata.is_canceled or metadata.is_voided:
            return (
                WorkflowStatus.REJECTED.value,
                "Legacy status: canceled/voided"
            )
        
        # If we have invoice reference, consider it linked
        if metadata.invoice_number or metadata.legacy_bc_doc_no:
            return (
                WorkflowStatus.LINKED_TO_INVOICE.value,
                "Legacy status: linked to original invoice"
            )
        
        return (
            WorkflowStatus.EXTRACTED.value,
            "Legacy status: pending processing"
        )
    
    @classmethod
    def _initialize_statement(
        cls,
        metadata: LegacyDocumentMetadata
    ) -> tuple[str, str]:
        """
        Initialize workflow for Statement.
        
        Statements are typically high-volume, low-friction documents.
        Most historical statements should be archived.
        
        State priority:
        1. archived - if reviewed/closed/exported
        2. reviewed - if reviewed but not archived
        3. ready_for_review - otherwise
        """
        if metadata.is_closed or metadata.is_exported:
            return (
                WorkflowStatus.ARCHIVED.value,
                "Legacy status: archived"
            )
        
        if metadata.is_reviewed:
            return (
                WorkflowStatus.REVIEWED.value,
                "Legacy status: reviewed"
            )
        
        return (
            WorkflowStatus.READY_FOR_REVIEW.value,
            "Legacy status: pending review"
        )
    
    @classmethod
    def _initialize_reminder(
        cls,
        metadata: LegacyDocumentMetadata
    ) -> tuple[str, str]:
        """
        Initialize workflow for Reminder.
        
        Similar to Statement - simple review workflow.
        """
        if metadata.is_exported or metadata.is_closed:
            return (
                WorkflowStatus.EXPORTED.value,
                "Legacy status: exported/closed"
            )
        
        if metadata.is_reviewed:
            return (
                WorkflowStatus.REVIEWED.value,
                "Legacy status: reviewed"
            )
        
        return (
            WorkflowStatus.READY_FOR_REVIEW.value,
            "Legacy status: pending review"
        )
    
    @classmethod
    def _initialize_finance_charge_memo(
        cls,
        metadata: LegacyDocumentMetadata
    ) -> tuple[str, str]:
        """
        Initialize workflow for Finance Charge Memo.
        
        Similar to Reminder - simple review workflow.
        """
        if metadata.is_exported or metadata.is_posted:
            return (
                WorkflowStatus.EXPORTED.value,
                "Legacy status: exported/posted"
            )
        
        if metadata.is_reviewed:
            return (
                WorkflowStatus.REVIEWED.value,
                "Legacy status: reviewed"
            )
        
        return (
            WorkflowStatus.READY_FOR_REVIEW.value,
            "Legacy status: pending review"
        )
    
    @classmethod
    def _initialize_quality_doc(
        cls,
        metadata: LegacyDocumentMetadata
    ) -> tuple[str, str]:
        """
        Initialize workflow for Quality Doc.
        
        State priority:
        1. exported - if fully processed and closed
        2. reviewed - if review completed
        3. tagged - if has quality tags
        4. ready_for_review - otherwise
        """
        if metadata.is_closed and metadata.is_reviewed:
            return (
                WorkflowStatus.EXPORTED.value,
                "Legacy status: closed and reviewed"
            )
        
        if metadata.is_reviewed:
            return (
                WorkflowStatus.REVIEWED.value,
                "Legacy status: review completed"
            )
        
        if metadata.quality_tags:
            return (
                WorkflowStatus.TAGGED.value,
                f"Legacy status: tagged ({', '.join(metadata.quality_tags)})"
            )
        
        return (
            WorkflowStatus.READY_FOR_REVIEW.value,
            "Legacy status: pending review"
        )
    
    @classmethod
    def _initialize_other(
        cls,
        metadata: LegacyDocumentMetadata
    ) -> tuple[str, str]:
        """
        Initialize workflow for OTHER (unclassified) documents.
        
        These go through triage workflow.
        
        State priority:
        1. exported - if fully processed
        2. triage_completed - if reviewed/closed
        3. triage_pending - otherwise
        """
        if metadata.is_exported:
            return (
                WorkflowStatus.EXPORTED.value,
                "Legacy status: exported"
            )
        
        if metadata.is_reviewed or metadata.is_closed or metadata.is_approved:
            return (
                WorkflowStatus.TRIAGE_COMPLETED.value,
                "Legacy status: triaged/reviewed"
            )
        
        return (
            WorkflowStatus.TRIAGE_PENDING.value,
            "Legacy status: pending triage"
        )
    
    @classmethod
    def _initialize_default(
        cls,
        metadata: LegacyDocumentMetadata
    ) -> tuple[str, str]:
        """
        Default initialization for unknown document types.
        
        Falls back to the OTHER workflow.
        """
        return cls._initialize_other(metadata)
    
    @classmethod
    def get_supported_doc_types(cls) -> List[str]:
        """Return list of doc types with specialized initialization logic."""
        return [
            DocType.AP_INVOICE.value,
            DocType.SALES_INVOICE.value,
            DocType.PURCHASE_ORDER.value,
            DocType.SALES_CREDIT_MEMO.value,
            DocType.PURCHASE_CREDIT_MEMO.value,
            DocType.STATEMENT.value,
            DocType.REMINDER.value,
            DocType.FINANCE_CHARGE_MEMO.value,
            DocType.QUALITY_DOC.value,
            DocType.OTHER.value,
        ]
