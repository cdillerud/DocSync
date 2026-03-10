"""
GPI Document Hub - Derived State Service

This module implements the derived state model for documents.
Document state is derived from the event history, providing:

1. validation_state: pass | warning | fail
2. workflow_state: received | processing | reviewing | ready | completed
3. automation_state: manual | assisted | autonomous

The derived state model fixes the "contradictory status" problem by
clearly separating these three dimensions of document state.

Backwards Compatibility:
- If no workflow events exist, falls back to existing document fields
- New and old documents both work with this model
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# STATE TAXONOMY
# =============================================================================

class ValidationState(str, Enum):
    """
    Validation state - result of checking document data against BC/rules.
    
    This answers: "Is the data correct and complete?"
    """
    PENDING = "pending"      # Not yet validated
    PASS = "pass"            # All validation checks passed
    WARNING = "warning"      # Passed with warnings (non-blocking issues)
    FAIL = "fail"            # Validation failed (blocking issues)


class WorkflowState(str, Enum):
    """
    Workflow state - where the document is in its lifecycle.
    
    This answers: "What stage is this document at?"
    """
    RECEIVED = "received"        # Just arrived, not processed
    PROCESSING = "processing"    # Being classified/extracted/validated
    REVIEWING = "reviewing"      # In a review queue awaiting human action
    READY = "ready"              # Ready for final action (BC creation, approval)
    COMPLETED = "completed"      # Fully processed and archived
    FAILED = "failed"            # Processing failed, needs intervention


class AutomationState(str, Enum):
    """
    Automation state - level of automation applied.
    
    This answers: "How much human involvement is needed?"
    """
    MANUAL = "manual"            # Requires full human review
    ASSISTED = "assisted"        # AI-assisted but needs human confirmation
    AUTONOMOUS = "autonomous"    # Fully automated, no human needed


# =============================================================================
# STATE DERIVATION LOGIC
# =============================================================================

class DerivedStateService:
    """
    Service for deriving document state from events or legacy fields.
    
    State Derivation Priority:
    1. Events in workflow_events collection (if present)
    2. Fallback to document fields (validation_results, status, auto_cleared, etc.)
    """
    
    def __init__(self, db):
        self.db = db
    
    async def derive_state(
        self,
        document_id: str,
        document: Optional[Dict] = None,
        events: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Derive the complete state model for a document.
        
        Returns:
            {
                "validation_state": "pass" | "warning" | "fail" | "pending",
                "workflow_state": "received" | "processing" | "reviewing" | "ready" | "completed" | "failed",
                "automation_state": "manual" | "assisted" | "autonomous",
                "state_reason": "Brief explanation of why document is in this state",
                "blocking_issues": ["List of blocking issues if any"],
                "warnings": ["List of warnings if any"],
                "needs_review": True/False,
                "review_queue": "vendor_pending" | "po_match" | "approval" | null,
                "derived_from": "events" | "legacy"
            }
        """
        # Fetch document if not provided
        if document is None:
            document = await self.db.hub_documents.find_one(
                {"id": document_id}, {"_id": 0}
            )
            if not document:
                return self._empty_state("Document not found")
        
        # Check if we have events
        if events is None:
            events = await self.db.workflow_events.find(
                {"document_id": document_id}, {"_id": 0}
            ).sort("timestamp", -1).limit(100).to_list(100)
        
        if events and len(events) > 0:
            return self._derive_from_events(document, events)
        else:
            return self._derive_from_legacy(document)
    
    def _derive_from_events(
        self,
        document: Dict,
        events: List[Dict]
    ) -> Dict[str, Any]:
        """Derive state from event history."""
        
        # Build state from events
        validation_state = ValidationState.PENDING.value
        workflow_state = WorkflowState.RECEIVED.value
        automation_state = AutomationState.MANUAL.value
        state_reason = ""
        blocking_issues = []
        warnings = []
        needs_review = False
        review_queue = None
        
        # Track what we've seen
        has_classification = False
        has_extraction = False
        has_vendor_match = False
        has_bc_validation = False
        has_sharepoint_upload = False
        has_automation_decision = False
        
        # Process events from oldest to newest
        for event in reversed(events):
            event_type = event.get("event_type", "")
            status = event.get("status", "")
            payload = event.get("payload", {})
            
            # Document received
            if event_type == "document.received":
                workflow_state = WorkflowState.PROCESSING.value
            
            # Classification events
            elif event_type == "classification.completed":
                has_classification = True
                if status == "failed":
                    workflow_state = WorkflowState.FAILED.value
                    validation_state = ValidationState.FAIL.value
                    blocking_issues.append("Classification failed")
            
            elif event_type == "classification.failed":
                has_classification = True
                workflow_state = WorkflowState.FAILED.value
                validation_state = ValidationState.FAIL.value
                blocking_issues.append(payload.get("error", "Classification failed"))
            
            # Extraction events
            elif event_type == "extraction.completed":
                has_extraction = True
                completeness = payload.get("completeness_score", 0)
                if completeness < 0.5:
                    warnings.append(f"Low extraction completeness: {completeness:.0%}")
            
            elif event_type == "extraction.failed":
                has_extraction = True
                validation_state = ValidationState.WARNING.value
                warnings.append(payload.get("error", "Extraction incomplete"))
            
            # Vendor match events
            elif event_type == "vendor.match.completed":
                has_vendor_match = True
            
            elif event_type == "vendor.match.failed":
                has_vendor_match = True
                validation_state = ValidationState.FAIL.value
                needs_review = True
                review_queue = "vendor_pending"
                blocking_issues.append("Vendor not matched")
            
            elif event_type == "vendor.resolved":
                # Vendor was resolved - clear the blocking issue
                if "Vendor not matched" in blocking_issues:
                    blocking_issues.remove("Vendor not matched")
                needs_review = review_queue == "vendor_pending"
                if review_queue == "vendor_pending":
                    review_queue = None
            
            # BC validation events
            elif event_type == "bc.validation.completed":
                has_bc_validation = True
                if payload.get("all_passed"):
                    if validation_state != ValidationState.FAIL.value:
                        validation_state = ValidationState.PASS.value
                        if payload.get("warnings"):
                            validation_state = ValidationState.WARNING.value
                            warnings.extend(payload.get("warnings", []))
            
            elif event_type == "bc.validation.failed":
                has_bc_validation = True
                validation_state = ValidationState.FAIL.value
                needs_review = True
                review_queue = "bc_validation"
                blocking_issues.extend(payload.get("failed_checks", []))
            
            elif event_type == "bc.validation.overridden":
                # Override clears the blocking issues
                blocking_issues = [i for i in blocking_issues if "BC" not in i]
                if not blocking_issues:
                    validation_state = ValidationState.WARNING.value
                    warnings.append("BC validation overridden")
                needs_review = False
                review_queue = None
            
            # PO validation events
            elif event_type == "po.validation.failed":
                validation_state = ValidationState.FAIL.value
                needs_review = True
                review_queue = "po_match"
                blocking_issues.append(f"PO not found: {payload.get('po_number', 'unknown')}")
            
            elif event_type == "po.validation.completed":
                if "PO not found" in " ".join(blocking_issues):
                    blocking_issues = [i for i in blocking_issues if "PO not found" not in i]
            
            # SharePoint events
            elif event_type == "sharepoint.upload.succeeded":
                has_sharepoint_upload = True
            
            elif event_type == "sharepoint.upload.failed":
                warnings.append(f"SharePoint upload failed: {payload.get('error', 'unknown')}")
            
            # Automation decision events
            elif event_type == "automation.decision.completed":
                decision = payload.get("decision", "")
                
                if payload.get("auto_clear"):
                    automation_state = AutomationState.AUTONOMOUS.value
                    workflow_state = WorkflowState.COMPLETED.value
                    state_reason = "Auto-cleared"
                elif payload.get("auto_post"):
                    automation_state = AutomationState.AUTONOMOUS.value
                    workflow_state = WorkflowState.COMPLETED.value
                    state_reason = "Auto-posted"
                elif decision == "NeedsReview":
                    needs_review = True
                    workflow_state = WorkflowState.REVIEWING.value
                    automation_state = AutomationState.ASSISTED.value
                elif decision == "ReadyForApproval":
                    workflow_state = WorkflowState.READY.value
                    automation_state = AutomationState.ASSISTED.value
            
            # Review events
            elif event_type == "review.assigned":
                needs_review = True
                workflow_state = WorkflowState.REVIEWING.value
                review_queue = payload.get("queue")
            
            elif event_type == "review.approved":
                needs_review = False
                workflow_state = WorkflowState.READY.value
                review_queue = None
            
            elif event_type == "review.rejected":
                validation_state = ValidationState.FAIL.value
                workflow_state = WorkflowState.FAILED.value
                blocking_issues.append(payload.get("reason", "Rejected"))
            
            # BC creation events
            elif event_type == "bc.draft.created":
                workflow_state = WorkflowState.COMPLETED.value
                state_reason = f"BC draft created: {payload.get('bc_number')}"
            
            elif event_type == "bc.posted":
                workflow_state = WorkflowState.COMPLETED.value
                automation_state = AutomationState.AUTONOMOUS.value
                state_reason = f"Posted to BC: {payload.get('bc_number')}"
            
            # Document archived
            elif event_type == "document.archived":
                workflow_state = WorkflowState.COMPLETED.value
            
            # System events
            elif event_type == "system.reprocessed":
                # Reset to processing state
                workflow_state = WorkflowState.PROCESSING.value
                blocking_issues = []
                warnings = []
        
        # Determine final workflow state if still processing
        if workflow_state == WorkflowState.PROCESSING.value:
            if blocking_issues:
                workflow_state = WorkflowState.REVIEWING.value
                needs_review = True
            elif has_bc_validation and validation_state == ValidationState.PASS.value:
                workflow_state = WorkflowState.READY.value
            elif has_classification and has_extraction:
                workflow_state = WorkflowState.REVIEWING.value
        
        # Generate state reason if not set
        if not state_reason:
            if blocking_issues:
                state_reason = f"Blocked: {blocking_issues[0]}"
            elif warnings:
                state_reason = f"Warning: {warnings[0]}"
            elif workflow_state == WorkflowState.READY.value:
                state_reason = "Ready for processing"
            elif workflow_state == WorkflowState.REVIEWING.value:
                state_reason = "Awaiting review"
            elif workflow_state == WorkflowState.COMPLETED.value:
                state_reason = "Processing complete"
            else:
                state_reason = f"In {workflow_state}"
        
        return {
            "validation_state": validation_state,
            "workflow_state": workflow_state,
            "automation_state": automation_state,
            "state_reason": state_reason,
            "blocking_issues": blocking_issues,
            "warnings": warnings,
            "needs_review": needs_review,
            "review_queue": review_queue,
            "derived_from": "events",
            # Processing flags for compatibility
            "has_classification": has_classification,
            "has_extraction": has_extraction,
            "has_vendor_match": has_vendor_match,
            "has_bc_validation": has_bc_validation,
            "has_sharepoint_upload": has_sharepoint_upload,
        }
    
    def _derive_from_legacy(self, document: Dict) -> Dict[str, Any]:
        """
        Derive state from legacy document fields.
        
        This provides backwards compatibility for documents processed
        before the event system was implemented.
        """
        # Derive validation_state from validation_results
        validation_state = ValidationState.PENDING.value
        blocking_issues = []
        warnings = []
        
        validation_results = document.get("validation_results", {})
        if validation_results:
            if validation_results.get("all_passed"):
                validation_state = ValidationState.PASS.value
                warnings = validation_results.get("warnings", [])
                if warnings:
                    validation_state = ValidationState.WARNING.value
            else:
                validation_state = ValidationState.FAIL.value
                # Extract failed checks as blocking issues
                for check in validation_results.get("checks", []):
                    if not check.get("passed"):
                        blocking_issues.append(check.get("check_name", "Unknown check"))
        
        # Derive workflow_state from status field
        status = document.get("status", "Received")
        workflow_status = document.get("workflow_status", "")
        
        workflow_state = WorkflowState.RECEIVED.value
        needs_review = False
        review_queue = None
        
        status_mapping = {
            "Received": WorkflowState.RECEIVED.value,
            "Classified": WorkflowState.PROCESSING.value,
            "Validated": WorkflowState.READY.value,
            "Valid": WorkflowState.READY.value,
            "NeedsReview": WorkflowState.REVIEWING.value,
            "Exception": WorkflowState.REVIEWING.value,
            "LinkedToBC": WorkflowState.COMPLETED.value,
            "Completed": WorkflowState.COMPLETED.value,
            "Posted": WorkflowState.COMPLETED.value,
            "Archived": WorkflowState.COMPLETED.value,
            "Failed": WorkflowState.FAILED.value,
        }
        
        workflow_state = status_mapping.get(status, WorkflowState.PROCESSING.value)
        
        # Check for specific review queues from workflow_status
        if workflow_status == "vendor_pending":
            needs_review = True
            review_queue = "vendor_pending"
            blocking_issues.append("Vendor not matched")
        elif workflow_status == "bc_validation_pending":
            needs_review = True
            review_queue = "bc_validation"
        elif workflow_status == "bc_validation_failed":
            needs_review = True
            review_queue = "bc_validation"
        elif workflow_status == "data_correction_pending":
            needs_review = True
            review_queue = "data_correction"
        elif workflow_status == "ready_for_approval":
            workflow_state = WorkflowState.READY.value
            review_queue = "approval"
        
        if status == "NeedsReview":
            needs_review = True
        
        # Derive automation_state from auto_cleared and other flags
        automation_state = AutomationState.MANUAL.value
        
        if document.get("auto_cleared"):
            automation_state = AutomationState.AUTONOMOUS.value
            workflow_state = WorkflowState.COMPLETED.value
        elif document.get("auto_posted"):
            automation_state = AutomationState.AUTONOMOUS.value
            workflow_state = WorkflowState.COMPLETED.value
        elif document.get("ai_confidence", 0) > 0.9 and validation_state == ValidationState.PASS.value:
            automation_state = AutomationState.ASSISTED.value
        
        # Generate state reason
        state_reason = ""
        if blocking_issues:
            state_reason = f"Blocked: {blocking_issues[0]}"
        elif document.get("auto_cleared"):
            state_reason = document.get("auto_clear_reason", "Auto-cleared")
        elif document.get("status") == "LinkedToBC":
            state_reason = f"Linked to BC: {document.get('bc_document_no', 'unknown')}"
        elif needs_review:
            state_reason = f"In queue: {review_queue or 'review'}"
        else:
            state_reason = f"Status: {status}"
        
        return {
            "validation_state": validation_state,
            "workflow_state": workflow_state,
            "automation_state": automation_state,
            "state_reason": state_reason,
            "blocking_issues": blocking_issues,
            "warnings": warnings if isinstance(warnings, list) else [],
            "needs_review": needs_review,
            "review_queue": review_queue,
            "derived_from": "legacy",
            # Legacy flags
            "has_classification": bool(document.get("document_type")) and document.get("document_type") != "Other",
            "has_extraction": bool(document.get("extracted_fields") or document.get("invoice_number")),
            "has_vendor_match": bool(document.get("matched_vendor_no")),
            "has_bc_validation": bool(validation_results),
            "has_sharepoint_upload": bool(document.get("sharepoint_item_id")),
        }
    
    def _empty_state(self, reason: str = "") -> Dict[str, Any]:
        """Return an empty/default state."""
        return {
            "validation_state": ValidationState.PENDING.value,
            "workflow_state": WorkflowState.RECEIVED.value,
            "automation_state": AutomationState.MANUAL.value,
            "state_reason": reason or "Unknown",
            "blocking_issues": [],
            "warnings": [],
            "needs_review": False,
            "review_queue": None,
            "derived_from": "none",
            "has_classification": False,
            "has_extraction": False,
            "has_vendor_match": False,
            "has_bc_validation": False,
            "has_sharepoint_upload": False,
        }
    
    async def update_document_derived_state(
        self,
        document_id: str,
        document: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Calculate derived state and update the document record.
        
        This should be called after emitting events to keep the document
        record in sync with the latest derived state.
        
        Returns:
            The derived state that was applied
        """
        derived = await self.derive_state(document_id, document)
        
        # Update document with derived state fields
        update_data = {
            "validation_state": derived["validation_state"],
            "workflow_state": derived["workflow_state"],
            "automation_state": derived["automation_state"],
            "state_reason": derived["state_reason"],
            "needs_review": derived["needs_review"],
            "review_queue": derived["review_queue"],
            "derived_state_updated_utc": datetime.now(timezone.utc).isoformat()
        }
        
        await self.db.hub_documents.update_one(
            {"id": document_id},
            {"$set": update_data}
        )
        
        logger.debug(
            "Updated derived state for doc %s: validation=%s, workflow=%s, automation=%s",
            document_id[:8], derived["validation_state"],
            derived["workflow_state"], derived["automation_state"]
        )
        
        return derived


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_state_badge_color(state_type: str, value: str) -> str:
    """Get badge color for state value (for UI)."""
    colors = {
        "validation_state": {
            "pending": "gray",
            "pass": "green",
            "warning": "yellow",
            "fail": "red"
        },
        "workflow_state": {
            "received": "gray",
            "processing": "blue",
            "reviewing": "yellow",
            "ready": "green",
            "completed": "green",
            "failed": "red"
        },
        "automation_state": {
            "manual": "gray",
            "assisted": "blue",
            "autonomous": "purple"
        }
    }
    return colors.get(state_type, {}).get(value, "gray")


def get_state_icon(state_type: str, value: str) -> str:
    """Get icon name for state value (for UI)."""
    icons = {
        "validation_state": {
            "pending": "clock",
            "pass": "check-circle",
            "warning": "alert-triangle",
            "fail": "x-circle"
        },
        "workflow_state": {
            "received": "inbox",
            "processing": "loader",
            "reviewing": "eye",
            "ready": "check",
            "completed": "check-circle",
            "failed": "x-circle"
        },
        "automation_state": {
            "manual": "user",
            "assisted": "cpu",
            "autonomous": "zap"
        }
    }
    return icons.get(state_type, {}).get(value, "circle")


def format_state_for_display(derived_state: Dict) -> Dict[str, Any]:
    """Format derived state for UI display."""
    return {
        "validation": {
            "state": derived_state["validation_state"],
            "color": get_state_badge_color("validation_state", derived_state["validation_state"]),
            "icon": get_state_icon("validation_state", derived_state["validation_state"]),
            "label": derived_state["validation_state"].replace("_", " ").title()
        },
        "workflow": {
            "state": derived_state["workflow_state"],
            "color": get_state_badge_color("workflow_state", derived_state["workflow_state"]),
            "icon": get_state_icon("workflow_state", derived_state["workflow_state"]),
            "label": derived_state["workflow_state"].replace("_", " ").title()
        },
        "automation": {
            "state": derived_state["automation_state"],
            "color": get_state_badge_color("automation_state", derived_state["automation_state"]),
            "icon": get_state_icon("automation_state", derived_state["automation_state"]),
            "label": derived_state["automation_state"].replace("_", " ").title()
        },
        "reason": derived_state["state_reason"],
        "blocking_issues": derived_state["blocking_issues"],
        "warnings": derived_state["warnings"],
        "needs_review": derived_state["needs_review"],
        "review_queue": derived_state["review_queue"]
    }


# =============================================================================
# GLOBAL SERVICE INSTANCE
# =============================================================================

_derived_state_service: Optional[DerivedStateService] = None


def get_derived_state_service() -> Optional[DerivedStateService]:
    """Get the global derived state service instance."""
    return _derived_state_service


def set_derived_state_service(db) -> DerivedStateService:
    """Initialize and set the global derived state service instance."""
    global _derived_state_service
    _derived_state_service = DerivedStateService(db)
    return _derived_state_service
