"""
Unit tests for the AP Invoice Workflow Engine.
Tests the state machine logic in services/workflow_engine.py
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
    WORKFLOW_TRANSITIONS
)


class TestWorkflowStatus:
    """Test workflow status enum values."""
    
    def test_all_statuses_defined(self):
        """Verify all expected workflow statuses exist."""
        expected = [
            'captured', 'classified', 'extracted',
            'vendor_pending', 'bc_validation_pending', 'bc_validation_failed',
            'data_correction_pending', 'ready_for_approval', 'approval_in_progress',
            'approved', 'rejected', 'exported', 'archived', 'failed'
        ]
        actual = [s.value for s in WorkflowStatus]
        for status in expected:
            assert status in actual, f"Missing status: {status}"


class TestWorkflowTransitions:
    """Test the state machine transition rules."""
    
    def test_captured_to_classified(self):
        """Document can move from captured to classified on classification success."""
        can, next_status, _ = WorkflowEngine.can_transition(
            WorkflowStatus.CAPTURED.value,
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        assert can is True
        assert next_status == WorkflowStatus.CLASSIFIED.value
    
    def test_captured_to_failed(self):
        """Document can move from captured to failed on classification failure."""
        can, next_status, _ = WorkflowEngine.can_transition(
            WorkflowStatus.CAPTURED.value,
            WorkflowEvent.ON_CLASSIFICATION_FAILED.value
        )
        assert can is True
        assert next_status == WorkflowStatus.FAILED.value
    
    def test_classified_to_extracted(self):
        """Document can move from classified to extracted on successful extraction."""
        can, next_status, _ = WorkflowEngine.can_transition(
            WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        assert can is True
        assert next_status == WorkflowStatus.EXTRACTED.value
    
    def test_classified_to_data_correction(self):
        """Document moves to data_correction_pending on low confidence extraction."""
        can, next_status, _ = WorkflowEngine.can_transition(
            WorkflowStatus.CLASSIFIED.value,
            WorkflowEvent.ON_EXTRACTION_LOW_CONFIDENCE.value
        )
        assert can is True
        assert next_status == WorkflowStatus.DATA_CORRECTION_PENDING.value
    
    def test_extracted_to_vendor_pending(self):
        """Document moves to vendor_pending when vendor is missing."""
        can, next_status, _ = WorkflowEngine.can_transition(
            WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_VENDOR_MISSING.value
        )
        assert can is True
        assert next_status == WorkflowStatus.VENDOR_PENDING.value
    
    def test_extracted_to_bc_validation(self):
        """Document moves to bc_validation_pending when vendor is matched."""
        can, next_status, _ = WorkflowEngine.can_transition(
            WorkflowStatus.EXTRACTED.value,
            WorkflowEvent.ON_VENDOR_MATCHED.value
        )
        assert can is True
        assert next_status == WorkflowStatus.BC_VALIDATION_PENDING.value
    
    def test_vendor_pending_to_bc_validation(self):
        """Document moves from vendor_pending to bc_validation when vendor resolved."""
        can, next_status, _ = WorkflowEngine.can_transition(
            WorkflowStatus.VENDOR_PENDING.value,
            WorkflowEvent.ON_VENDOR_RESOLVED.value
        )
        assert can is True
        assert next_status == WorkflowStatus.BC_VALIDATION_PENDING.value
    
    def test_bc_validation_to_ready_for_approval(self):
        """Document moves to ready_for_approval when BC validation passes."""
        can, next_status, _ = WorkflowEngine.can_transition(
            WorkflowStatus.BC_VALIDATION_PENDING.value,
            WorkflowEvent.ON_BC_VALID.value
        )
        assert can is True
        assert next_status == WorkflowStatus.READY_FOR_APPROVAL.value
    
    def test_bc_validation_to_failed(self):
        """Document moves to bc_validation_failed when BC validation fails."""
        can, next_status, _ = WorkflowEngine.can_transition(
            WorkflowStatus.BC_VALIDATION_PENDING.value,
            WorkflowEvent.ON_BC_INVALID.value
        )
        assert can is True
        assert next_status == WorkflowStatus.BC_VALIDATION_FAILED.value
    
    def test_bc_validation_failed_override(self):
        """Document can override BC validation failure."""
        can, next_status, _ = WorkflowEngine.can_transition(
            WorkflowStatus.BC_VALIDATION_FAILED.value,
            WorkflowEvent.ON_BC_VALIDATION_OVERRIDE.value
        )
        assert can is True
        assert next_status == WorkflowStatus.READY_FOR_APPROVAL.value
    
    def test_approval_flow(self):
        """Test the approval workflow path."""
        # Start approval
        can, next_status, _ = WorkflowEngine.can_transition(
            WorkflowStatus.READY_FOR_APPROVAL.value,
            WorkflowEvent.ON_APPROVAL_STARTED.value
        )
        assert can is True
        assert next_status == WorkflowStatus.APPROVAL_IN_PROGRESS.value
        
        # Approve
        can, next_status, _ = WorkflowEngine.can_transition(
            WorkflowStatus.APPROVAL_IN_PROGRESS.value,
            WorkflowEvent.ON_APPROVED.value
        )
        assert can is True
        assert next_status == WorkflowStatus.APPROVED.value
    
    def test_rejection_flow(self):
        """Test rejection from ready_for_approval."""
        can, next_status, _ = WorkflowEngine.can_transition(
            WorkflowStatus.READY_FOR_APPROVAL.value,
            WorkflowEvent.ON_REJECTED.value
        )
        assert can is True
        assert next_status == WorkflowStatus.REJECTED.value
    
    def test_invalid_transition_blocked(self):
        """Invalid transitions should be blocked."""
        # Can't go directly from captured to approved
        can, _, reason = WorkflowEngine.can_transition(
            WorkflowStatus.CAPTURED.value,
            WorkflowEvent.ON_APPROVED.value
        )
        assert can is False
        assert "not valid" in reason.lower()


class TestAdvanceWorkflow:
    """Test the advance_workflow function."""
    
    def test_successful_transition(self):
        """Test a successful workflow transition."""
        doc = {
            "id": "test-123",
            "workflow_status": WorkflowStatus.CAPTURED.value,
            "workflow_history": []
        }
        
        updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value,
            context={"reason": "Test classification"},
            actor="test_user"
        )
        
        assert success is True
        assert updated_doc["workflow_status"] == WorkflowStatus.CLASSIFIED.value
        assert len(updated_doc["workflow_history"]) == 1
        assert history_entry.to_status == WorkflowStatus.CLASSIFIED.value
        assert history_entry.actor == "test_user"
    
    def test_failed_transition(self):
        """Test a blocked workflow transition."""
        doc = {
            "id": "test-123",
            "workflow_status": WorkflowStatus.CAPTURED.value,
            "workflow_history": []
        }
        
        updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_APPROVED.value  # Invalid from CAPTURED
        )
        
        assert success is False
        assert updated_doc["workflow_status"] == WorkflowStatus.CAPTURED.value  # Unchanged
        assert "blocked" in history_entry.reason.lower()
    
    def test_history_accumulates(self):
        """Test that workflow history accumulates correctly."""
        doc = {
            "id": "test-123",
            "workflow_status": WorkflowStatus.CAPTURED.value,
            "workflow_history": []
        }
        
        # Transition 1: Captured -> Classified
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
        )
        
        # Transition 2: Classified -> Extracted
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_EXTRACTION_SUCCESS.value
        )
        
        # Transition 3: Extracted -> BC Validation Pending
        doc, _, _ = WorkflowEngine.advance_workflow(
            doc, WorkflowEvent.ON_VENDOR_MATCHED.value
        )
        
        assert len(doc["workflow_history"]) == 3
        assert doc["workflow_history"][0]["to_status"] == WorkflowStatus.CLASSIFIED.value
        assert doc["workflow_history"][1]["to_status"] == WorkflowStatus.EXTRACTED.value
        assert doc["workflow_history"][2]["to_status"] == WorkflowStatus.BC_VALIDATION_PENDING.value


class TestInitializeWorkflow:
    """Test workflow initialization."""
    
    def test_initialize_new_document(self):
        """Test initializing workflow on a new document."""
        doc = {"id": "new-doc-123"}
        
        WorkflowEngine.initialize_workflow(doc, actor="email_poller")
        
        assert doc["workflow_status"] == WorkflowStatus.CAPTURED.value
        assert len(doc["workflow_history"]) == 1
        assert doc["workflow_history"][0]["actor"] == "email_poller"
        assert doc["workflow_history"][0]["event"] == WorkflowEvent.ON_CAPTURE.value


class TestHelperMethods:
    """Test helper methods."""
    
    def test_get_exception_statuses(self):
        """Test getting exception queue statuses."""
        exceptions = WorkflowEngine.get_exception_statuses()
        assert WorkflowStatus.VENDOR_PENDING.value in exceptions
        assert WorkflowStatus.BC_VALIDATION_PENDING.value in exceptions
        assert WorkflowStatus.BC_VALIDATION_FAILED.value in exceptions
        assert WorkflowStatus.DATA_CORRECTION_PENDING.value in exceptions
    
    def test_get_terminal_statuses(self):
        """Test getting terminal statuses."""
        terminals = WorkflowEngine.get_terminal_statuses()
        assert WorkflowStatus.EXPORTED.value in terminals
        assert WorkflowStatus.ARCHIVED.value in terminals
        assert WorkflowStatus.REJECTED.value in terminals
    
    def test_queue_mapping(self):
        """Test status to queue mapping."""
        assert WorkflowEngine.get_queue_for_status(WorkflowStatus.VENDOR_PENDING.value) == "vendor_pending"
        assert WorkflowEngine.get_queue_for_status(WorkflowStatus.READY_FOR_APPROVAL.value) == "ready_for_approval"
        assert WorkflowEngine.get_queue_for_status(WorkflowStatus.APPROVED.value) is None  # Not a queue status


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
