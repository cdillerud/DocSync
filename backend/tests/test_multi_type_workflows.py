"""
Tests for Multi-Document Type Workflow Engine

Tests for all document type workflows:
- SALES_INVOICE
- PURCHASE_ORDER
- SALES_CREDIT_MEMO
- PURCHASE_CREDIT_MEMO
- STATEMENT
- REMINDER
- FINANCE_CHARGE_MEMO
- QUALITY_DOC
- OTHER
"""
import pytest
import sys
sys.path.insert(0, '/app/backend')

from services.workflow_engine import (
    WorkflowEngine, WorkflowStatus, WorkflowEvent, DocType,
    WORKFLOW_DEFINITIONS
)


class TestSalesInvoiceWorkflowFull:
    """Full workflow tests for SALES_INVOICE."""
    
    def test_happy_path_with_approval(self):
        """Test complete happy path: capture -> classify -> extract -> approval -> export."""
        doc = {
            "id": "test-sales-invoice-001",
            "doc_type": DocType.SALES_INVOICE.value
        }
        
        # Initialize
        doc = WorkflowEngine.initialize_workflow(doc)
        assert doc["workflow_status"] == WorkflowStatus.CAPTURED.value
        
        # Classification
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.CLASSIFIED.value
        
        # Extraction
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.EXTRACTED.value
        
        # Mark ready for approval
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_MARK_READY_FOR_APPROVAL.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.READY_FOR_APPROVAL.value
        
        # Start approval
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_APPROVAL_STARTED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.APPROVAL_IN_PROGRESS.value
        
        # Approve
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_APPROVED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.APPROVED.value
        
        # Export
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_EXPORTED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.EXPORTED.value
    
    def test_direct_approval_path(self):
        """Test direct approval from extracted state."""
        doc = {
            "id": "test-sales-direct",
            "doc_type": DocType.SALES_INVOICE.value,
            "workflow_status": WorkflowStatus.EXTRACTED.value
        }
        
        # Direct approval (skip ready_for_approval)
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_APPROVED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.APPROVED.value


class TestPurchaseOrderWorkflowFull:
    """Full workflow tests for PURCHASE_ORDER."""
    
    def test_happy_path_with_validation(self):
        """Test complete path with PO validation."""
        doc = {
            "id": "test-po-001",
            "doc_type": DocType.PURCHASE_ORDER.value
        }
        
        # Initialize
        doc = WorkflowEngine.initialize_workflow(doc)
        
        # Classification
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        assert success
        
        # Extraction
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.EXTRACTED.value
        
        # Start PO validation
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_PO_VALIDATION_STARTED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.VALIDATION_PENDING.value
        
        # PO valid
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_PO_VALID.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.READY_FOR_APPROVAL.value
        
        # Approve
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_APPROVED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.APPROVED.value
    
    def test_validation_failed_path(self):
        """Test path when PO validation fails."""
        doc = {
            "id": "test-po-fail",
            "doc_type": DocType.PURCHASE_ORDER.value,
            "workflow_status": WorkflowStatus.VALIDATION_PENDING.value
        }
        
        # PO invalid
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_PO_INVALID.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.VALIDATION_FAILED.value
        
        # Override and mark ready for approval
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_MARK_READY_FOR_APPROVAL.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.READY_FOR_APPROVAL.value


class TestSalesCreditMemoWorkflowFull:
    """Full workflow tests for SALES_CREDIT_MEMO."""
    
    def test_happy_path_with_invoice_linkage(self):
        """Test path with credit memo linked to invoice."""
        doc = {
            "id": "test-scm-001",
            "doc_type": DocType.SALES_CREDIT_MEMO.value
        }
        
        # Initialize
        doc = WorkflowEngine.initialize_workflow(doc)
        
        # Classification
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        assert success
        
        # Extraction
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.EXTRACTED.value
        
        # Link to invoice
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_CREDIT_LINKED_TO_INVOICE.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.LINKED_TO_INVOICE.value
        
        # Mark ready for approval
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_MARK_READY_FOR_APPROVAL.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.READY_FOR_APPROVAL.value
        
        # Approve
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_APPROVED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.APPROVED.value


class TestPurchaseCreditMemoWorkflowFull:
    """Full workflow tests for PURCHASE_CREDIT_MEMO."""
    
    def test_happy_path(self):
        """Test standard path for purchase credit memo."""
        doc = {
            "id": "test-pcm-001",
            "doc_type": DocType.PURCHASE_CREDIT_MEMO.value
        }
        
        doc = WorkflowEngine.initialize_workflow(doc)
        
        # Classification -> Extraction
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        assert doc["workflow_status"] == WorkflowStatus.EXTRACTED.value
        
        # Link to invoice
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_CREDIT_LINKED_TO_INVOICE.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.LINKED_TO_INVOICE.value


class TestStatementWorkflowFull:
    """Full workflow tests for STATEMENT (high volume, fast path)."""
    
    def test_review_path(self):
        """Test statement review path."""
        doc = {
            "id": "test-statement-001",
            "doc_type": DocType.STATEMENT.value
        }
        
        doc = WorkflowEngine.initialize_workflow(doc)
        
        # Classification
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        
        # Extraction
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        assert doc["workflow_status"] == WorkflowStatus.EXTRACTED.value
        
        # Mark ready for review
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_MARK_READY_FOR_REVIEW.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.READY_FOR_REVIEW.value
        
        # Reviewed
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_REVIEWED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.REVIEWED.value
        
        # Archive
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_ARCHIVED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.ARCHIVED.value
    
    def test_fast_export_path(self):
        """Test fast track directly to export."""
        doc = {
            "id": "test-statement-fast",
            "doc_type": DocType.STATEMENT.value,
            "workflow_status": WorkflowStatus.EXTRACTED.value
        }
        
        # Direct export from extracted
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_EXPORTED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.EXPORTED.value


class TestReminderWorkflowFull:
    """Full workflow tests for REMINDER."""
    
    def test_review_path(self):
        """Test reminder review path."""
        doc = {
            "id": "test-reminder-001",
            "doc_type": DocType.REMINDER.value
        }
        
        doc = WorkflowEngine.initialize_workflow(doc)
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        
        # Mark ready for review
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_MARK_READY_FOR_REVIEW.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.READY_FOR_REVIEW.value
        
        # Reviewed
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_REVIEWED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.REVIEWED.value


class TestFinanceChargeMemoWorkflowFull:
    """Full workflow tests for FINANCE_CHARGE_MEMO."""
    
    def test_review_path(self):
        """Test finance charge memo review path."""
        doc = {
            "id": "test-fcm-001",
            "doc_type": DocType.FINANCE_CHARGE_MEMO.value
        }
        
        doc = WorkflowEngine.initialize_workflow(doc)
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        
        # Mark ready for review
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_MARK_READY_FOR_REVIEW.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.READY_FOR_REVIEW.value


class TestQualityDocWorkflowFull:
    """Full workflow tests for QUALITY_DOC."""
    
    def test_tagged_review_path(self):
        """Test quality doc with tagging and review."""
        doc = {
            "id": "test-quality-001",
            "doc_type": DocType.QUALITY_DOC.value
        }
        
        doc = WorkflowEngine.initialize_workflow(doc)
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        
        # Tag
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_QUALITY_TAGGED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.TAGGED.value
        
        # Mark ready for review
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_MARK_READY_FOR_REVIEW.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.READY_FOR_REVIEW.value
        
        # Start review
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_REVIEW_STARTED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.REVIEW_IN_PROGRESS.value
        
        # Complete review
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_REVIEWED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.REVIEWED.value
    
    def test_rejection_path(self):
        """Test quality doc rejection."""
        doc = {
            "id": "test-quality-reject",
            "doc_type": DocType.QUALITY_DOC.value,
            "workflow_status": WorkflowStatus.READY_FOR_REVIEW.value
        }
        
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_REJECTED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.REJECTED.value


class TestOtherWorkflowFull:
    """Full workflow tests for OTHER (triage workflow)."""
    
    def test_triage_path(self):
        """Test OTHER document triage path."""
        doc = {
            "id": "test-other-001",
            "doc_type": DocType.OTHER.value
        }
        
        doc = WorkflowEngine.initialize_workflow(doc)
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        
        # Triage needed
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_TRIAGE_NEEDED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.TRIAGE_PENDING.value
        
        # Triage completed
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_TRIAGE_COMPLETED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.TRIAGE_COMPLETED.value
        
        # Export
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_EXPORTED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.EXPORTED.value
    
    def test_classification_failed_to_triage(self):
        """Test that classification failure goes to triage."""
        doc = {
            "id": "test-other-classify-fail",
            "doc_type": DocType.OTHER.value,
            "workflow_status": WorkflowStatus.CAPTURED.value
        }
        
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_CLASSIFICATION_FAILED.value
        )
        assert success
        assert doc["workflow_status"] == WorkflowStatus.TRIAGE_PENDING.value


class TestInvalidTransitions:
    """Test that invalid transitions are properly blocked."""
    
    def test_invalid_event_for_status(self):
        """Test that invalid events are blocked."""
        doc = {
            "id": "test-invalid",
            "doc_type": DocType.SALES_INVOICE.value,
            "workflow_status": WorkflowStatus.CAPTURED.value
        }
        
        # Cannot approve from captured
        doc, _, success = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_APPROVED.value
        )
        assert not success
        assert doc["workflow_status"] == WorkflowStatus.CAPTURED.value
    
    def test_ap_specific_event_on_non_ap(self):
        """Test that AP-specific events don't work on non-AP types."""
        doc = {
            "id": "test-ap-specific",
            "doc_type": DocType.SALES_INVOICE.value,
            "workflow_status": WorkflowStatus.EXTRACTED.value
        }
        
        # Vendor missing is AP-specific
        can, _, _ = WorkflowEngine.can_transition(
            doc["doc_type"],
            doc["workflow_status"],
            WorkflowEvent.ON_VENDOR_MISSING.value
        )
        assert not can


class TestHelperMethodsExtended:
    """Test extended helper methods."""
    
    def test_get_valid_statuses_for_doc_type(self):
        """Test getting valid statuses for each doc type."""
        ap_statuses = WorkflowEngine.get_valid_statuses_for_doc_type(DocType.AP_INVOICE.value)
        assert WorkflowStatus.VENDOR_PENDING.value in ap_statuses
        assert WorkflowStatus.BC_VALIDATION_PENDING.value in ap_statuses
        
        sales_statuses = WorkflowEngine.get_valid_statuses_for_doc_type(DocType.SALES_INVOICE.value)
        assert WorkflowStatus.VENDOR_PENDING.value not in sales_statuses
        assert WorkflowStatus.READY_FOR_APPROVAL.value in sales_statuses
        
        other_statuses = WorkflowEngine.get_valid_statuses_for_doc_type(DocType.OTHER.value)
        assert WorkflowStatus.TRIAGE_PENDING.value in other_statuses
        assert WorkflowStatus.TRIAGE_COMPLETED.value in other_statuses
    
    def test_get_valid_events_for_status(self):
        """Test getting valid events for a specific status."""
        events = WorkflowEngine.get_valid_events_for_status(
            DocType.STATEMENT.value,
            WorkflowStatus.READY_FOR_REVIEW.value
        )
        assert WorkflowEvent.ON_REVIEWED.value in events
    
    def test_get_exception_statuses_by_type(self):
        """Test exception statuses vary by type."""
        ap_exceptions = WorkflowEngine.get_exception_statuses(DocType.AP_INVOICE.value)
        assert WorkflowStatus.VENDOR_PENDING.value in ap_exceptions
        
        po_exceptions = WorkflowEngine.get_exception_statuses(DocType.PURCHASE_ORDER.value)
        assert WorkflowStatus.VALIDATION_PENDING.value in po_exceptions
        
        other_exceptions = WorkflowEngine.get_exception_statuses(DocType.OTHER.value)
        assert WorkflowStatus.TRIAGE_PENDING.value in other_exceptions
    
    def test_get_active_statuses(self):
        """Test getting active (non-terminal) statuses."""
        active = WorkflowEngine.get_active_statuses()
        assert WorkflowStatus.CAPTURED.value in active
        assert WorkflowStatus.EXTRACTED.value in active
        assert WorkflowStatus.EXPORTED.value not in active
        assert WorkflowStatus.ARCHIVED.value not in active
    
    def test_get_queue_for_status(self):
        """Test queue mapping for new statuses."""
        assert WorkflowEngine.get_queue_for_status(WorkflowStatus.TRIAGE_PENDING.value) == "triage_pending"
        assert WorkflowEngine.get_queue_for_status(WorkflowStatus.READY_FOR_REVIEW.value) == "ready_for_review"
        assert WorkflowEngine.get_queue_for_status(WorkflowStatus.VALIDATION_PENDING.value) == "validation_pending"
        assert WorkflowEngine.get_queue_for_status(WorkflowStatus.LINKED_TO_INVOICE.value) == "linked_to_invoice"
        assert WorkflowEngine.get_queue_for_status(WorkflowStatus.TAGGED.value) == "tagged"


class TestAllDocTypesHaveDefinitions:
    """Verify all doc types have workflow definitions."""
    
    def test_all_doc_types_defined(self):
        """All doc types should have workflow definitions."""
        for doc_type in DocType:
            assert doc_type.value in WORKFLOW_DEFINITIONS, f"Missing workflow for {doc_type.value}"
    
    def test_all_doc_types_have_capture_event(self):
        """All doc types should support the capture event."""
        for doc_type in DocType:
            workflow = WORKFLOW_DEFINITIONS[doc_type.value]
            assert None in workflow, f"No initial state for {doc_type.value}"
            assert WorkflowEvent.ON_CAPTURE.value in workflow[None], \
                f"No ON_CAPTURE transition for {doc_type.value}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
