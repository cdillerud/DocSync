"""
Unit tests for the Multi-Type Workflow Engine.
Tests the state machine logic for all document types in services/workflow_engine.py
"""
import pytest
from datetime import datetime, timezone
import sys
sys.path.insert(0, '/app/backend')

from services.workflow_engine import (
    WorkflowEngine,
    WorkflowStatus,
    WorkflowEvent,
    WorkflowHistoryEntry,
    DocType,
    SourceSystem,
    CaptureChannel,
    DocumentClassifier,
    WORKFLOW_DEFINITIONS
)


class TestDocTypes:
    """Test document type definitions."""
    
    def test_all_doc_types_defined(self):
        """Verify all expected document types exist."""
        expected = [
            'AP_INVOICE', 'SALES_INVOICE', 'PURCHASE_ORDER',
            'SALES_CREDIT_MEMO', 'PURCHASE_CREDIT_MEMO',
            'STATEMENT', 'REMINDER', 'FINANCE_CHARGE_MEMO',
            'QUALITY_DOC', 'OTHER'
        ]
        actual = [d.value for d in DocType]
        for doc_type in expected:
            assert doc_type in actual, f"Missing doc_type: {doc_type}"
    
    def test_all_doc_types_have_workflows(self):
        """Verify each doc_type has a workflow definition."""
        for doc_type in DocType:
            assert doc_type.value in WORKFLOW_DEFINITIONS, f"No workflow for {doc_type.value}"


class TestDocumentClassifier:
    """Test document classification helpers."""
    
    def test_classify_from_zetadocs_set(self):
        """Test Zetadocs set code classification."""
        doc_type, channel = DocumentClassifier.classify_from_zetadocs_set("ZD00015")
        assert doc_type == DocType.AP_INVOICE
        
        doc_type, channel = DocumentClassifier.classify_from_zetadocs_set("ZD00007")
        assert doc_type == DocType.SALES_INVOICE
        
        doc_type, channel = DocumentClassifier.classify_from_zetadocs_set("ZD00002")
        assert doc_type == DocType.PURCHASE_ORDER
    
    def test_classify_from_square9_workflow(self):
        """Test Square9 workflow name classification."""
        assert DocumentClassifier.classify_from_square9_workflow("AP_Invoice") == DocType.AP_INVOICE
        assert DocumentClassifier.classify_from_square9_workflow("Sales Invoice") == DocType.SALES_INVOICE
        assert DocumentClassifier.classify_from_square9_workflow("Unknown") == DocType.OTHER
    
    def test_classify_from_mailbox_category(self):
        """Test mailbox category classification."""
        assert DocumentClassifier.classify_from_mailbox_category("AP") == DocType.AP_INVOICE
        assert DocumentClassifier.classify_from_mailbox_category("Sales") == DocType.SALES_INVOICE
        assert DocumentClassifier.classify_from_mailbox_category("Unknown") == DocType.OTHER
    
    def test_classify_from_ai_result(self):
        """Test AI classification result mapping."""
        assert DocumentClassifier.classify_from_ai_result("AP_Invoice") == DocType.AP_INVOICE
        assert DocumentClassifier.classify_from_ai_result("Sales_Invoice") == DocType.SALES_INVOICE
        assert DocumentClassifier.classify_from_ai_result("Statement") == DocType.STATEMENT
        assert DocumentClassifier.classify_from_ai_result("Unknown") == DocType.OTHER
    
    def test_determine_source_system(self):
        """Test source system determination."""
        assert DocumentClassifier.determine_source_system(has_zetadocs_set=True) == SourceSystem.ZETADOCS
        assert DocumentClassifier.determine_source_system(has_square9_workflow=True) == SourceSystem.SQUARE9
        assert DocumentClassifier.determine_source_system(is_migration=True) == SourceSystem.MIGRATION
        assert DocumentClassifier.determine_source_system() == SourceSystem.GPI_HUB_NATIVE
    
    def test_determine_capture_channel(self):
        """Test capture channel determination."""
        assert DocumentClassifier.determine_capture_channel("email_inbox") == CaptureChannel.EMAIL
        assert DocumentClassifier.determine_capture_channel("manual_upload") == CaptureChannel.UPLOAD
        assert DocumentClassifier.determine_capture_channel("api_call") == CaptureChannel.API
        assert DocumentClassifier.determine_capture_channel("unknown_source") == CaptureChannel.UNKNOWN


class TestAPInvoiceWorkflow:
    """Test AP Invoice specific workflow transitions."""
    
    def test_full_happy_path(self):
        """Test complete happy path for AP Invoice."""
        doc = {"id": "ap-test-1", "doc_type": DocType.AP_INVOICE.value, "workflow_history": []}
        
        # captured -> classified
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.AP_INVOICE.value,
            WorkflowStatus.CAPTURED.value,
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        assert can is True
        assert next_status == WorkflowStatus.CLASSIFIED.value
        
        # classified -> extracted
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.AP_INVOICE.value,
            WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        assert can is True
        assert next_status == WorkflowStatus.EXTRACTED.value
        
        # extracted -> bc_validation_pending (vendor matched)
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.AP_INVOICE.value,
            WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_VENDOR_MATCHED.value
        )
        assert can is True
        assert next_status == WorkflowStatus.BC_VALIDATION_PENDING.value
        
        # bc_validation_pending -> ready_for_approval
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.AP_INVOICE.value,
            WorkflowStatus.BC_VALIDATION_PENDING.value,
            WorkflowEvent.ON_BC_VALID.value
        )
        assert can is True
        assert next_status == WorkflowStatus.READY_FOR_APPROVAL.value
        
        # ready_for_approval -> approved
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.AP_INVOICE.value,
            WorkflowStatus.READY_FOR_APPROVAL.value,
            WorkflowEvent.ON_APPROVED.value
        )
        assert can is True
        assert next_status == WorkflowStatus.APPROVED.value
    
    def test_vendor_pending_path(self):
        """Test AP Invoice with unmatched vendor."""
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.AP_INVOICE.value,
            WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_VENDOR_MISSING.value
        )
        assert can is True
        assert next_status == WorkflowStatus.VENDOR_PENDING.value
        
        # Resolve vendor -> bc_validation_pending
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.AP_INVOICE.value,
            WorkflowStatus.VENDOR_PENDING.value,
            WorkflowEvent.ON_VENDOR_RESOLVED.value
        )
        assert can is True
        assert next_status == WorkflowStatus.BC_VALIDATION_PENDING.value
    
    def test_bc_validation_failed_path(self):
        """Test AP Invoice with BC validation failure and override."""
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.AP_INVOICE.value,
            WorkflowStatus.BC_VALIDATION_PENDING.value,
            WorkflowEvent.ON_BC_INVALID.value
        )
        assert can is True
        assert next_status == WorkflowStatus.BC_VALIDATION_FAILED.value
        
        # Override BC validation -> ready_for_approval
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.AP_INVOICE.value,
            WorkflowStatus.BC_VALIDATION_FAILED.value,
            WorkflowEvent.ON_BC_VALIDATION_OVERRIDE.value
        )
        assert can is True
        assert next_status == WorkflowStatus.READY_FOR_APPROVAL.value


class TestSalesInvoiceWorkflow:
    """Test Sales Invoice workflow transitions."""
    
    def test_standard_path(self):
        """Test standard Sales Invoice path (no vendor/BC validation)."""
        # captured -> classified
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.SALES_INVOICE.value,
            WorkflowStatus.CAPTURED.value,
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        assert can is True
        assert next_status == WorkflowStatus.CLASSIFIED.value
        
        # classified -> extracted
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.SALES_INVOICE.value,
            WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        assert can is True
        assert next_status == WorkflowStatus.EXTRACTED.value
        
        # extracted -> ready_for_approval (via review complete)
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.SALES_INVOICE.value,
            WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_REVIEW_COMPLETE.value
        )
        assert can is True
        assert next_status == WorkflowStatus.READY_FOR_APPROVAL.value
    
    def test_no_vendor_pending_for_sales(self):
        """Sales Invoice should NOT have vendor_pending path."""
        can, _, reason = WorkflowEngine.can_transition(
            DocType.SALES_INVOICE.value,
            WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_VENDOR_MISSING.value
        )
        assert can is False


class TestPurchaseOrderWorkflow:
    """Test Purchase Order workflow transitions."""
    
    def test_standard_path(self):
        """Test standard PO path."""
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.PURCHASE_ORDER.value,
            WorkflowStatus.CAPTURED.value,
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        assert can is True
        
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.PURCHASE_ORDER.value,
            WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        assert can is True


class TestStatementWorkflow:
    """Test Statement (simplified) workflow."""
    
    def test_simplified_path(self):
        """Statement should have simplified workflow."""
        # captured -> classified
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.STATEMENT.value,
            WorkflowStatus.CAPTURED.value,
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        assert can is True
        
        # classified -> extracted
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.STATEMENT.value,
            WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        assert can is True
        
        # extracted -> exported (direct)
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.STATEMENT.value,
            WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_EXPORTED.value
        )
        assert can is True


class TestOtherWorkflow:
    """Test OTHER (fallback) workflow."""
    
    def test_minimal_path(self):
        """OTHER should have minimal workflow."""
        can, next_status, _ = WorkflowEngine.can_transition(
            DocType.OTHER.value,
            WorkflowStatus.CAPTURED.value,
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        assert can is True


class TestAdvanceWorkflowWithDocType:
    """Test advance_workflow respects doc_type."""
    
    def test_advance_uses_doc_type(self):
        """advance_workflow should use doc_type to select state machine."""
        doc = {
            "id": "test-123",
            "doc_type": DocType.SALES_INVOICE.value,
            "workflow_status": WorkflowStatus.CAPTURED.value,
            "workflow_history": []
        }
        
        updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value,
            actor="test"
        )
        
        assert success is True
        assert updated_doc["workflow_status"] == WorkflowStatus.CLASSIFIED.value
    
    def test_advance_blocks_invalid_transition_for_type(self):
        """advance_workflow should block invalid transitions for doc_type."""
        doc = {
            "id": "test-456",
            "doc_type": DocType.SALES_INVOICE.value,
            "workflow_status": WorkflowStatus.EXTRACTED.value,
            "workflow_history": []
        }
        
        # Sales Invoice shouldn't have vendor_missing transition
        _, _, success = WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_VENDOR_MISSING.value,
            actor="test"
        )
        
        assert success is False
        assert doc["workflow_status"] == WorkflowStatus.EXTRACTED.value  # Unchanged


class TestInitializeWorkflow:
    """Test workflow initialization."""
    
    def test_initialize_with_doc_type(self):
        """Initialize workflow should set all classification fields."""
        doc = {"id": "new-doc-123"}
        
        WorkflowEngine.initialize_workflow(
            doc,
            doc_type=DocType.AP_INVOICE.value,
            source_system=SourceSystem.GPI_HUB_NATIVE.value,
            capture_channel=CaptureChannel.EMAIL.value,
            actor="email_poller"
        )
        
        assert doc["doc_type"] == DocType.AP_INVOICE.value
        assert doc["source_system"] == SourceSystem.GPI_HUB_NATIVE.value
        assert doc["capture_channel"] == CaptureChannel.EMAIL.value
        assert doc["workflow_status"] == WorkflowStatus.CAPTURED.value
        assert len(doc["workflow_history"]) == 1


class TestHelperMethods:
    """Test helper methods."""
    
    def test_get_all_doc_types(self):
        """Test getting all supported document types."""
        types = WorkflowEngine.get_all_doc_types()
        assert len(types) == 10
        assert DocType.AP_INVOICE.value in types
        assert DocType.SALES_INVOICE.value in types
    
    def test_get_exception_statuses_by_type(self):
        """Test exception statuses are correct per type."""
        ap_exceptions = WorkflowEngine.get_exception_statuses(DocType.AP_INVOICE.value)
        assert WorkflowStatus.VENDOR_PENDING.value in ap_exceptions
        assert WorkflowStatus.BC_VALIDATION_PENDING.value in ap_exceptions
        
        # Non-AP types have simpler exceptions
        other_exceptions = WorkflowEngine.get_exception_statuses(DocType.SALES_INVOICE.value)
        assert WorkflowStatus.VENDOR_PENDING.value not in other_exceptions
    
    def test_is_ap_specific_status(self):
        """Test AP-specific status detection."""
        assert WorkflowEngine.is_ap_specific_status(WorkflowStatus.VENDOR_PENDING.value) is True
        assert WorkflowEngine.is_ap_specific_status(WorkflowStatus.BC_VALIDATION_PENDING.value) is True
        assert WorkflowEngine.is_ap_specific_status(WorkflowStatus.READY_FOR_APPROVAL.value) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
