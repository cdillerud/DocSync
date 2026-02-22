"""
GPI Document Hub - Workflow Engine Service

This module implements a deterministic state machine for AP Invoice document workflows.
It replaces Square9 workflows with a more structured, testable approach.

The workflow engine is pure business logic with no direct HTTP or DB calls.
All state transitions are deterministic and can be covered by unit tests.
"""

from enum import Enum
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple, Any
import logging

logger = logging.getLogger(__name__)


class WorkflowStatus(str, Enum):
    """
    Workflow status values for AP_Invoice documents.
    These replace the Square9 workflow stages.
    """
    # Initial capture stage
    CAPTURED = "captured"
    CLASSIFIED = "classified"
    
    # Extraction and validation stage
    EXTRACTED = "extracted"
    
    # Exception queues (manual intervention needed)
    VENDOR_PENDING = "vendor_pending"  # Unknown vendor, needs manual resolution
    BC_VALIDATION_PENDING = "bc_validation_pending"  # Awaiting BC validation
    BC_VALIDATION_FAILED = "bc_validation_failed"  # BC validation failed, needs override
    DATA_CORRECTION_PENDING = "data_correction_pending"  # Extraction incomplete, needs manual fix
    
    # Approval stage
    READY_FOR_APPROVAL = "ready_for_approval"
    APPROVAL_IN_PROGRESS = "approval_in_progress"
    APPROVED = "approved"
    REJECTED = "rejected"
    
    # Export/Archive stage
    EXPORTED = "exported"
    ARCHIVED = "archived"
    
    # Error states
    FAILED = "failed"


class WorkflowEvent(str, Enum):
    """
    Events that trigger workflow state transitions.
    """
    # Capture events
    ON_CAPTURE = "on_capture"
    ON_CLASSIFICATION_SUCCESS = "on_classification_success"
    ON_CLASSIFICATION_FAILED = "on_classification_failed"
    
    # Extraction events
    ON_EXTRACTION_SUCCESS = "on_extraction_success"
    ON_EXTRACTION_LOW_CONFIDENCE = "on_extraction_low_confidence"
    ON_EXTRACTION_FAILED = "on_extraction_failed"
    
    # Vendor matching events
    ON_VENDOR_MATCHED = "on_vendor_matched"
    ON_VENDOR_MISSING = "on_vendor_missing"
    ON_VENDOR_RESOLVED = "on_vendor_resolved"  # Manual resolution
    
    # BC validation events
    ON_BC_VALID = "on_bc_valid"
    ON_BC_INVALID = "on_bc_invalid"
    ON_BC_VALIDATION_OVERRIDE = "on_bc_validation_override"
    
    # Data correction events
    ON_DATA_CORRECTED = "on_data_corrected"
    
    # Approval events
    ON_APPROVAL_STARTED = "on_approval_started"
    ON_APPROVED = "on_approved"
    ON_REJECTED = "on_rejected"
    
    # Export events
    ON_EXPORTED = "on_exported"
    ON_ARCHIVED = "on_archived"
    
    # Error events
    ON_ERROR = "on_error"
    ON_RETRY = "on_retry"


class WorkflowHistoryEntry:
    """
    Represents a single entry in the workflow history.
    """
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


# State machine transition rules
# Format: {current_status: {event: (next_status, requires_context_check)}}
WORKFLOW_TRANSITIONS: Dict[str, Dict[str, Tuple[str, bool]]] = {
    # From None/initial state
    None: {
        WorkflowEvent.ON_CAPTURE: (WorkflowStatus.CAPTURED, False),
    },
    
    # From CAPTURED
    WorkflowStatus.CAPTURED: {
        WorkflowEvent.ON_CLASSIFICATION_SUCCESS: (WorkflowStatus.CLASSIFIED, False),
        WorkflowEvent.ON_CLASSIFICATION_FAILED: (WorkflowStatus.FAILED, False),
    },
    
    # From CLASSIFIED
    WorkflowStatus.CLASSIFIED: {
        WorkflowEvent.ON_EXTRACTION_SUCCESS: (WorkflowStatus.EXTRACTED, False),
        WorkflowEvent.ON_EXTRACTION_LOW_CONFIDENCE: (WorkflowStatus.DATA_CORRECTION_PENDING, False),
        WorkflowEvent.ON_EXTRACTION_FAILED: (WorkflowStatus.DATA_CORRECTION_PENDING, False),
    },
    
    # From EXTRACTED - branch based on vendor match
    WorkflowStatus.EXTRACTED: {
        WorkflowEvent.ON_VENDOR_MATCHED: (WorkflowStatus.BC_VALIDATION_PENDING, False),
        WorkflowEvent.ON_VENDOR_MISSING: (WorkflowStatus.VENDOR_PENDING, False),
    },
    
    # From VENDOR_PENDING - manual vendor resolution queue
    WorkflowStatus.VENDOR_PENDING: {
        WorkflowEvent.ON_VENDOR_RESOLVED: (WorkflowStatus.BC_VALIDATION_PENDING, False),
        WorkflowEvent.ON_ERROR: (WorkflowStatus.FAILED, False),
    },
    
    # From BC_VALIDATION_PENDING
    WorkflowStatus.BC_VALIDATION_PENDING: {
        WorkflowEvent.ON_BC_VALID: (WorkflowStatus.READY_FOR_APPROVAL, False),
        WorkflowEvent.ON_BC_INVALID: (WorkflowStatus.BC_VALIDATION_FAILED, False),
    },
    
    # From BC_VALIDATION_FAILED - manual override queue
    WorkflowStatus.BC_VALIDATION_FAILED: {
        WorkflowEvent.ON_BC_VALIDATION_OVERRIDE: (WorkflowStatus.READY_FOR_APPROVAL, False),
        WorkflowEvent.ON_DATA_CORRECTED: (WorkflowStatus.BC_VALIDATION_PENDING, False),
        WorkflowEvent.ON_ERROR: (WorkflowStatus.FAILED, False),
    },
    
    # From DATA_CORRECTION_PENDING
    WorkflowStatus.DATA_CORRECTION_PENDING: {
        WorkflowEvent.ON_DATA_CORRECTED: (WorkflowStatus.EXTRACTED, False),
        WorkflowEvent.ON_ERROR: (WorkflowStatus.FAILED, False),
    },
    
    # From READY_FOR_APPROVAL
    WorkflowStatus.READY_FOR_APPROVAL: {
        WorkflowEvent.ON_APPROVAL_STARTED: (WorkflowStatus.APPROVAL_IN_PROGRESS, False),
        WorkflowEvent.ON_APPROVED: (WorkflowStatus.APPROVED, False),  # Auto-approval path
        WorkflowEvent.ON_REJECTED: (WorkflowStatus.REJECTED, False),
    },
    
    # From APPROVAL_IN_PROGRESS
    WorkflowStatus.APPROVAL_IN_PROGRESS: {
        WorkflowEvent.ON_APPROVED: (WorkflowStatus.APPROVED, False),
        WorkflowEvent.ON_REJECTED: (WorkflowStatus.REJECTED, False),
    },
    
    # From APPROVED
    WorkflowStatus.APPROVED: {
        WorkflowEvent.ON_EXPORTED: (WorkflowStatus.EXPORTED, False),
    },
    
    # From EXPORTED
    WorkflowStatus.EXPORTED: {
        WorkflowEvent.ON_ARCHIVED: (WorkflowStatus.ARCHIVED, False),
    },
    
    # From REJECTED - can be retried
    WorkflowStatus.REJECTED: {
        WorkflowEvent.ON_RETRY: (WorkflowStatus.READY_FOR_APPROVAL, False),
    },
    
    # From FAILED - can be retried
    WorkflowStatus.FAILED: {
        WorkflowEvent.ON_RETRY: (WorkflowStatus.CAPTURED, False),
    },
}


class WorkflowEngine:
    """
    State machine for AP Invoice document workflows.
    
    This class is pure business logic with no database or HTTP dependencies.
    It takes a document's current state and an event, and returns the new state.
    """
    
    @staticmethod
    def get_current_status(document: Dict) -> Optional[str]:
        """Get the current workflow status from a document."""
        return document.get("workflow_status")
    
    @staticmethod
    def get_workflow_history(document: Dict) -> List[Dict]:
        """Get the workflow history from a document."""
        return document.get("workflow_history", [])
    
    @staticmethod
    def can_transition(
        current_status: Optional[str],
        event: str
    ) -> Tuple[bool, Optional[str], str]:
        """
        Check if a transition is valid.
        
        Returns:
            (can_transition, next_status, reason)
        """
        # Handle string enum values
        current_key = current_status.value if isinstance(current_status, WorkflowStatus) else current_status
        event_key = event.value if isinstance(event, WorkflowEvent) else event
        
        # Get transitions for current status
        status_transitions = WORKFLOW_TRANSITIONS.get(current_key)
        
        if status_transitions is None:
            return (False, None, f"No transitions defined for status '{current_status}'")
        
        # Check if event is valid for this status
        transition = status_transitions.get(event_key)
        
        if transition is None:
            valid_events = list(status_transitions.keys())
            return (False, None, f"Event '{event}' not valid for status '{current_status}'. Valid events: {valid_events}")
        
        next_status, _ = transition
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
            actor: Who/what triggered this transition (default: "system")
        
        Returns:
            (updated_document, history_entry, success)
        """
        context = context or {}
        current_status = WorkflowEngine.get_current_status(document)
        
        # Check if transition is valid
        can_transition, next_status, reason = WorkflowEngine.can_transition(current_status, event)
        
        if not can_transition:
            logger.warning(
                "Invalid workflow transition: doc=%s, current=%s, event=%s, reason=%s",
                document.get("id"), current_status, event, reason
            )
            # Create a failed history entry
            history_entry = WorkflowHistoryEntry(
                from_status=current_status,
                to_status=current_status,  # No change
                event=event,
                actor=actor,
                reason=f"Transition blocked: {reason}",
                metadata=context.get("metadata", {})
            )
            return (document, history_entry, False)
        
        # Get the next status value
        next_status_value = next_status.value if isinstance(next_status, WorkflowStatus) else next_status
        
        # Create history entry
        history_entry = WorkflowHistoryEntry(
            from_status=current_status,
            to_status=next_status_value,
            event=event,
            actor=actor,
            reason=context.get("reason"),
            metadata=context.get("metadata", {})
        )
        
        # Update document
        document["workflow_status"] = next_status_value
        
        # Initialize or append to workflow history
        if "workflow_history" not in document:
            document["workflow_history"] = []
        document["workflow_history"].append(history_entry.to_dict())
        
        # Update timestamp
        document["workflow_status_updated_utc"] = datetime.now(timezone.utc).isoformat()
        
        logger.info(
            "Workflow transition: doc=%s, %s -> %s (event=%s, actor=%s)",
            document.get("id"), current_status, next_status_value, event, actor
        )
        
        return (document, history_entry, True)
    
    @staticmethod
    def initialize_workflow(document: Dict, actor: str = "system") -> Dict:
        """
        Initialize workflow tracking on a new document.
        Sets initial status to CAPTURED.
        """
        document["workflow_status"] = WorkflowStatus.CAPTURED.value
        document["workflow_history"] = [{
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "from_status": None,
            "to_status": WorkflowStatus.CAPTURED.value,
            "event": WorkflowEvent.ON_CAPTURE.value,
            "actor": actor,
            "reason": "Document captured and workflow initialized",
            "metadata": {}
        }]
        document["workflow_status_updated_utc"] = datetime.now(timezone.utc).isoformat()
        return document
    
    @staticmethod
    def determine_next_event(document: Dict, validation_results: Dict) -> Optional[str]:
        """
        Determine the next workflow event based on document state and validation results.
        
        This is a helper method that examines document fields and returns the
        appropriate event to advance the workflow.
        """
        current_status = WorkflowEngine.get_current_status(document)
        
        if current_status == WorkflowStatus.CAPTURED.value:
            # Check if classification succeeded
            if document.get("document_type") and document.get("ai_confidence", 0) > 0:
                return WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value
            return WorkflowEvent.ON_CLASSIFICATION_FAILED.value
        
        if current_status == WorkflowStatus.CLASSIFIED.value:
            # Check extraction quality
            ai_confidence = document.get("ai_confidence", 0)
            extracted_fields = document.get("extracted_fields", {})
            
            # Check required fields for AP_Invoice
            vendor = extracted_fields.get("vendor")
            invoice_number = extracted_fields.get("invoice_number")
            amount = extracted_fields.get("amount")
            
            if vendor and invoice_number and amount and ai_confidence >= 0.7:
                return WorkflowEvent.ON_EXTRACTION_SUCCESS.value
            elif ai_confidence < 0.5:
                return WorkflowEvent.ON_EXTRACTION_FAILED.value
            else:
                return WorkflowEvent.ON_EXTRACTION_LOW_CONFIDENCE.value
        
        if current_status == WorkflowStatus.EXTRACTED.value:
            # Check vendor match
            vendor_canonical = document.get("vendor_canonical")
            vendor_match_method = document.get("vendor_match_method")
            
            if vendor_canonical and vendor_match_method and vendor_match_method != "none":
                return WorkflowEvent.ON_VENDOR_MATCHED.value
            return WorkflowEvent.ON_VENDOR_MISSING.value
        
        if current_status == WorkflowStatus.BC_VALIDATION_PENDING.value:
            # Check BC validation results
            if validation_results.get("all_passed", False):
                return WorkflowEvent.ON_BC_VALID.value
            return WorkflowEvent.ON_BC_INVALID.value
        
        return None
    
    @staticmethod
    def get_queue_for_status(status: str) -> Optional[str]:
        """
        Map a workflow status to its corresponding queue name.
        Used for routing documents to the appropriate work queue.
        """
        queue_mapping = {
            WorkflowStatus.VENDOR_PENDING.value: "vendor_pending",
            WorkflowStatus.BC_VALIDATION_PENDING.value: "bc_validation_pending",
            WorkflowStatus.BC_VALIDATION_FAILED.value: "bc_validation_failed",
            WorkflowStatus.DATA_CORRECTION_PENDING.value: "data_correction_pending",
            WorkflowStatus.READY_FOR_APPROVAL.value: "ready_for_approval",
            WorkflowStatus.APPROVAL_IN_PROGRESS.value: "approval_in_progress",
        }
        return queue_mapping.get(status)
    
    @staticmethod
    def get_all_statuses() -> List[str]:
        """Get all possible workflow status values."""
        return [s.value for s in WorkflowStatus]
    
    @staticmethod
    def get_exception_statuses() -> List[str]:
        """Get workflow statuses that represent exception/queue states."""
        return [
            WorkflowStatus.VENDOR_PENDING.value,
            WorkflowStatus.BC_VALIDATION_PENDING.value,
            WorkflowStatus.BC_VALIDATION_FAILED.value,
            WorkflowStatus.DATA_CORRECTION_PENDING.value,
        ]
    
    @staticmethod
    def get_terminal_statuses() -> List[str]:
        """Get workflow statuses that represent terminal states."""
        return [
            WorkflowStatus.EXPORTED.value,
            WorkflowStatus.ARCHIVED.value,
            WorkflowStatus.REJECTED.value,
        ]
    
    @staticmethod
    def calculate_time_in_status(document: Dict, status: str) -> Optional[float]:
        """
        Calculate time (in seconds) a document spent in a specific status.
        Returns None if status not found in history.
        """
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
