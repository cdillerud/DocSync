"""
GPI Document Hub - Event Service

This module implements the core event infrastructure for the event-driven workflow platform.
Events are the source of truth for workflow history. The document stores current derived state.

Event Naming Convention:
- Use dot-separated names: category.action
- Examples: document.received, classification.completed, vendor.match.completed, bc.validation.failed

Phase 3 Compatibility:
- Designed so subscribers/rules can plug in later without rework
- Events include correlation_id for tracing related events
- Payload structure is consistent and extensible
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Literal
from enum import Enum

# Phase 3 Step 4d.5: required import for the migrated `emit_intake_events`
# orchestrator (moved verbatim from server._emit_intake_events).
from services.derived_state_service import get_derived_state_service

logger = logging.getLogger(__name__)


# =============================================================================
# EVENT TYPE DEFINITIONS
# =============================================================================

class EventCategory(str, Enum):
    """High-level event categories."""
    DOCUMENT = "document"
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    VENDOR = "vendor"
    PO = "po"
    BC = "bc"
    SHAREPOINT = "sharepoint"
    AUTOMATION = "automation"
    REVIEW = "review"
    SYSTEM = "system"


class EventStatus(str, Enum):
    """Event outcome status."""
    COMPLETED = "completed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"
    PENDING = "pending"


# Standard event types with their expected payload structures
EVENT_TYPES = {
    # Document lifecycle events
    "document.received": {
        "description": "Document captured into the system",
        "category": EventCategory.DOCUMENT,
        "payload_keys": ["source", "file_name", "content_type", "file_size"]
    },
    "document.duplicate_detected": {
        "description": "Duplicate document detected",
        "category": EventCategory.DOCUMENT,
        "payload_keys": ["existing_doc_id", "match_type", "sha256_match"]
    },
    "document.marked_ready": {
        "description": "Document marked ready for processing",
        "category": EventCategory.DOCUMENT,
        "payload_keys": ["ready_for", "reason"]
    },
    "document.archived": {
        "description": "Document archived to SharePoint",
        "category": EventCategory.DOCUMENT,
        "payload_keys": ["folder_path", "sharepoint_item_id"]
    },
    "document.deleted": {
        "description": "Document deleted from system",
        "category": EventCategory.DOCUMENT,
        "payload_keys": ["reason", "deleted_by"]
    },
    
    # Classification events
    "classification.started": {
        "description": "AI classification started",
        "category": EventCategory.CLASSIFICATION,
        "payload_keys": ["method"]
    },
    "classification.completed": {
        "description": "Document classification completed",
        "category": EventCategory.CLASSIFICATION,
        "payload_keys": ["doc_type", "confidence", "method", "model"]
    },
    "classification.failed": {
        "description": "Document classification failed",
        "category": EventCategory.CLASSIFICATION,
        "payload_keys": ["error", "fallback_type"]
    },
    "classification.overridden": {
        "description": "Classification manually overridden by user",
        "category": EventCategory.CLASSIFICATION,
        "payload_keys": ["old_type", "new_type", "reason", "actor"]
    },
    
    # Extraction events
    "extraction.started": {
        "description": "Data extraction started",
        "category": EventCategory.EXTRACTION,
        "payload_keys": ["method"]
    },
    "extraction.completed": {
        "description": "Data extraction completed",
        "category": EventCategory.EXTRACTION,
        "payload_keys": ["fields_extracted", "completeness_score"]
    },
    "extraction.failed": {
        "description": "Data extraction failed",
        "category": EventCategory.EXTRACTION,
        "payload_keys": ["error", "partial_fields"]
    },
    
    # Vendor matching events
    "vendor.match.started": {
        "description": "Vendor matching started",
        "category": EventCategory.VENDOR,
        "payload_keys": ["vendor_raw"]
    },
    "vendor.match.completed": {
        "description": "Vendor successfully matched",
        "category": EventCategory.VENDOR,
        "payload_keys": ["vendor_name", "vendor_no", "match_method", "match_score", "source"]
    },
    "vendor.match.failed": {
        "description": "No vendor match found",
        "category": EventCategory.VENDOR,
        "payload_keys": ["vendor_raw", "candidates", "reason"]
    },
    "vendor.resolved": {
        "description": "Vendor manually resolved by user",
        "category": EventCategory.VENDOR,
        "payload_keys": ["vendor_no", "vendor_name", "actor", "resolution_method"]
    },
    
    # PO validation events
    "po.validation.started": {
        "description": "PO validation started",
        "category": EventCategory.PO,
        "payload_keys": ["po_number"]
    },
    "po.validation.completed": {
        "description": "PO validation succeeded",
        "category": EventCategory.PO,
        "payload_keys": ["po_number", "bc_po_id", "status"]
    },
    "po.validation.failed": {
        "description": "PO validation failed",
        "category": EventCategory.PO,
        "payload_keys": ["po_number", "error", "reason"]
    },
    "po.validation.skipped": {
        "description": "PO validation skipped",
        "category": EventCategory.PO,
        "payload_keys": ["reason"]
    },
    
    # Business Central events
    "bc.validation.started": {
        "description": "BC validation started",
        "category": EventCategory.BC,
        "payload_keys": ["validation_type", "checks"]
    },
    "bc.validation.completed": {
        "description": "BC validation completed successfully",
        "category": EventCategory.BC,
        "payload_keys": ["all_passed", "checks_passed", "checks_total", "warnings"]
    },
    "bc.validation.failed": {
        "description": "BC validation failed",
        "category": EventCategory.BC,
        "payload_keys": ["failed_checks", "errors"]
    },
    "bc.validation.overridden": {
        "description": "BC validation manually overridden",
        "category": EventCategory.BC,
        "payload_keys": ["reason", "actor", "failed_checks_overridden"]
    },
    "bc.draft.created": {
        "description": "BC draft document created",
        "category": EventCategory.BC,
        "payload_keys": ["bc_type", "bc_id", "bc_number"]
    },
    "bc.draft.creation_failed": {
        "description": "BC draft creation failed",
        "category": EventCategory.BC,
        "payload_keys": ["bc_type", "error"]
    },
    "bc.posted": {
        "description": "Document posted to BC",
        "category": EventCategory.BC,
        "payload_keys": ["bc_type", "bc_id", "bc_number", "posted_by"]
    },
    "bc.attachment.uploaded": {
        "description": "Document attached to BC record",
        "category": EventCategory.BC,
        "payload_keys": ["bc_record_id", "attachment_id"]
    },
    
    # SharePoint events
    "sharepoint.upload.started": {
        "description": "SharePoint upload started",
        "category": EventCategory.SHAREPOINT,
        "payload_keys": ["folder_path"]
    },
    "sharepoint.upload.succeeded": {
        "description": "Document uploaded to SharePoint",
        "category": EventCategory.SHAREPOINT,
        "payload_keys": ["drive_id", "item_id", "folder_path", "share_link"]
    },
    "sharepoint.upload.failed": {
        "description": "SharePoint upload failed",
        "category": EventCategory.SHAREPOINT,
        "payload_keys": ["error", "http_status", "folder_path"]
    },
    "sharepoint.upload.conflict": {
        "description": "SharePoint upload conflict (file exists)",
        "category": EventCategory.SHAREPOINT,
        "payload_keys": ["existing_item_id", "resolution"]
    },
    
    # Automation decision events
    "automation.decision.completed": {
        "description": "Automation decision made",
        "category": EventCategory.AUTOMATION,
        "payload_keys": ["decision", "reason", "auto_clear", "auto_post"]
    },
    "automation.auto_clear.applied": {
        "description": "Auto-clear decision applied",
        "category": EventCategory.AUTOMATION,
        "payload_keys": ["confidence_threshold", "match_method_eligible", "reason"]
    },
    "automation.auto_post.applied": {
        "description": "Auto-post decision applied",
        "category": EventCategory.AUTOMATION,
        "payload_keys": ["bc_number", "vendor_no", "amount"]
    },
    "automation.auto_post.blocked": {
        "description": "Auto-post blocked",
        "category": EventCategory.AUTOMATION,
        "payload_keys": ["reason", "blocking_checks"]
    },
    
    # Review events
    "review.assigned": {
        "description": "Document assigned for review",
        "category": EventCategory.REVIEW,
        "payload_keys": ["queue", "reason", "assigned_to"]
    },
    
    # AP Validation lifecycle events
    "validation.started": {
        "description": "AP validation started",
        "category": EventCategory.DOCUMENT,
        "payload_keys": ["document_type", "validation_version"]
    },
    "validation.completed": {
        "description": "AP validation completed",
        "category": EventCategory.DOCUMENT,
        "payload_keys": [
            "document_type", "validation_state", "all_passed",
            "blocking_issues_count", "warnings_count",
            "vendor_resolved", "invoice_number_present",
            "invoice_date_present", "total_amount_present", "is_duplicate"
        ]
    },
    "validation.failed": {
        "description": "AP validation error",
        "category": EventCategory.DOCUMENT,
        "payload_keys": ["document_type", "error"]
    },
    "validation.warning_detected": {
        "description": "AP validation passed with warnings",
        "category": EventCategory.DOCUMENT,
        "payload_keys": ["document_type", "warnings"]
    },
    "review.started": {
        "description": "Review started",
        "category": EventCategory.REVIEW,
        "payload_keys": ["reviewer", "queue"]
    },
    "review.completed": {
        "description": "Review completed",
        "category": EventCategory.REVIEW,
        "payload_keys": ["reviewer", "action", "changes"]
    },
    "review.approved": {
        "description": "Document approved",
        "category": EventCategory.REVIEW,
        "payload_keys": ["approver", "comment"]
    },
    "review.rejected": {
        "description": "Document rejected",
        "category": EventCategory.REVIEW,
        "payload_keys": ["rejector", "reason"]
    },
    
    # System events
    "system.reprocessed": {
        "description": "Document reprocessed",
        "category": EventCategory.SYSTEM,
        "payload_keys": ["trigger", "actor", "reclassify"]
    },
    "system.error": {
        "description": "System error occurred",
        "category": EventCategory.SYSTEM,
        "payload_keys": ["error", "component", "recoverable"]
    },
    
    # Reference Resolution events (NEW)
    "reference.resolve.started": {
        "description": "Reference resolution started",
        "category": EventCategory.PO,
        "payload_keys": ["reference_number", "tables_to_check"]
    },
    "reference.resolve.completed": {
        "description": "Reference resolution completed",
        "category": EventCategory.PO,
        "payload_keys": ["reference_number", "reference_type", "bc_record_id", "status", "tables_checked"]
    },
    
    # BOL Extraction events (NEW)
    "bol.extracted": {
        "description": "BOL number extracted from document",
        "category": EventCategory.EXTRACTION,
        "payload_keys": ["bol_number", "source_field"]
    },
    
    # BC Write events (NEW)
    "bc.write_blocked": {
        "description": "BC write operation blocked by safety guard",
        "category": EventCategory.BC,
        "payload_keys": ["reason", "document_id", "attempted_action", "bc_environment"]
    },
}


# =============================================================================
# EVENT MODEL
# =============================================================================

class WorkflowEvent:
    """
    Represents a single workflow event.
    
    This is the atomic unit of workflow history. Events are immutable once created.
    """
    
    def __init__(
        self,
        event_type: str,
        document_id: str,
        status: str = EventStatus.COMPLETED.value,
        source_service: str = "system",
        correlation_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        actor: Optional[str] = None,
        timestamp: Optional[str] = None,
        event_id: Optional[str] = None
    ):
        self.event_id = event_id or str(uuid.uuid4())
        self.document_id = document_id
        self.event_type = event_type
        self.status = status
        self.source_service = source_service
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.payload = payload or {}
        self.actor = actor
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for storage."""
        return {
            "event_id": self.event_id,
            "document_id": self.document_id,
            "event_type": self.event_type,
            "status": self.status,
            "source_service": self.source_service,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "payload": self.payload
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowEvent":
        """Create event from dictionary."""
        return cls(
            event_id=data.get("event_id"),
            document_id=data.get("document_id"),
            event_type=data.get("event_type"),
            status=data.get("status", EventStatus.COMPLETED.value),
            source_service=data.get("source_service", "system"),
            correlation_id=data.get("correlation_id"),
            payload=data.get("payload", {}),
            actor=data.get("actor"),
            timestamp=data.get("timestamp")
        )
    
    def get_payload_summary(self, max_length: int = 100) -> str:
        """Get a short summary of the payload for UI display."""
        if not self.payload:
            return ""
        
        # Pick the most relevant fields to summarize
        summary_parts = []
        priority_keys = ["doc_type", "vendor_name", "match_method", "bc_number", 
                        "decision", "error", "reason", "confidence"]
        
        for key in priority_keys:
            if key in self.payload:
                val = self.payload[key]
                if isinstance(val, float):
                    val = f"{val:.2f}"
                elif isinstance(val, bool):
                    val = "Yes" if val else "No"
                elif isinstance(val, (list, dict)):
                    continue  # Skip complex types in summary
                summary_parts.append(f"{key}: {val}")
        
        summary = ", ".join(summary_parts)
        if len(summary) > max_length:
            summary = summary[:max_length - 3] + "..."
        return summary


# =============================================================================
# EVENT SERVICE
# =============================================================================

class EventService:
    """
    Central service for emitting and querying workflow events.
    
    This service is the primary interface for:
    - Emitting new events
    - Querying event history for a document
    - Converting legacy audit trail data to events
    - Supporting backwards compatibility fallback
    
    Phase 3 Design Notes:
    - Subscribers can be added by calling register_subscriber()
    - Rules engine will query events and emit new events based on patterns
    """
    
    def __init__(self, db):
        self.db = db
        self._subscribers = []  # For Phase 3: list of (event_pattern, callback) tuples
    
    async def emit(
        self,
        event_type: str,
        document_id: str,
        status: str = EventStatus.COMPLETED.value,
        source_service: str = "system",
        correlation_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        actor: Optional[str] = None
    ) -> WorkflowEvent:
        """
        Emit a new workflow event.
        
        This is the primary method for recording workflow history.
        Events are stored in the workflow_events collection.
        
        Args:
            event_type: Event type (e.g., "classification.completed")
            document_id: Document ID this event relates to
            status: Event outcome (completed, failed, warning, skipped)
            source_service: Service that emitted this event
            correlation_id: ID for tracing related events
            payload: Event-specific data
            actor: User or service that triggered this event
        
        Returns:
            The created WorkflowEvent
        """
        event = WorkflowEvent(
            event_type=event_type,
            document_id=document_id,
            status=status,
            source_service=source_service,
            correlation_id=correlation_id,
            payload=payload or {},
            actor=actor
        )
        
        # Store event
        await self.db.workflow_events.insert_one(event.to_dict())
        
        logger.info(
            "[Event] %s | doc=%s | status=%s | source=%s",
            event_type, document_id[:8], status, source_service
        )
        
        # Phase 3: Notify subscribers (placeholder)
        # await self._notify_subscribers(event)
        
        return event
    
    async def get_events(
        self,
        document_id: str,
        event_types: Optional[List[str]] = None,
        limit: int = 100,
        skip: int = 0
    ) -> List[WorkflowEvent]:
        """
        Get events for a document.
        
        Args:
            document_id: Document ID
            event_types: Optional filter for specific event types
            limit: Max events to return
            skip: Number of events to skip (for pagination)
        
        Returns:
            List of WorkflowEvent objects, newest first
        """
        query = {"document_id": document_id}
        if event_types:
            query["event_type"] = {"$in": event_types}
        
        cursor = self.db.workflow_events.find(
            query, {"_id": 0}
        ).sort("timestamp", -1).skip(skip).limit(limit)
        
        events = []
        async for doc in cursor:
            events.append(WorkflowEvent.from_dict(doc))
        
        return events
    
    async def get_events_by_correlation(
        self,
        correlation_id: str,
        limit: int = 100
    ) -> List[WorkflowEvent]:
        """Get all events with the same correlation ID."""
        cursor = self.db.workflow_events.find(
            {"correlation_id": correlation_id}, {"_id": 0}
        ).sort("timestamp", 1).limit(limit)
        
        events = []
        async for doc in cursor:
            events.append(WorkflowEvent.from_dict(doc))
        
        return events
    
    async def get_latest_event(
        self,
        document_id: str,
        event_type: Optional[str] = None
    ) -> Optional[WorkflowEvent]:
        """Get the most recent event for a document."""
        query = {"document_id": document_id}
        if event_type:
            query["event_type"] = event_type
        
        doc = await self.db.workflow_events.find_one(
            query, {"_id": 0},
            sort=[("timestamp", -1)]
        )
        
        return WorkflowEvent.from_dict(doc) if doc else None
    
    async def get_event_timeline(
        self,
        document_id: str,
        include_legacy: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get a unified timeline of events for UI display.
        
        This method provides backwards compatibility by:
        1. First fetching events from workflow_events collection
        2. If include_legacy=True and no events found, falling back to
           workflow_history on the document record
        
        Returns:
            List of event dictionaries formatted for UI timeline
        """
        # Get events from new system
        events = await self.get_events(document_id, limit=200)
        
        timeline = []
        
        if events:
            # Format new events for timeline
            for event in events:
                timeline.append({
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "status": event.status,
                    "timestamp": event.timestamp,
                    "source_service": event.source_service,
                    "actor": event.actor,
                    "correlation_id": event.correlation_id,
                    "payload_summary": event.get_payload_summary(),
                    "payload": event.payload,
                    "source": "event_system"
                })
        
        if include_legacy and not events:
            # Fall back to legacy workflow_history on document
            timeline = await self._get_legacy_timeline(document_id)
        
        # Sort by timestamp, newest first
        timeline.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        return timeline
    
    async def _get_legacy_timeline(self, document_id: str) -> List[Dict[str, Any]]:
        """
        Convert legacy workflow_history to timeline format.
        
        This provides backwards compatibility for documents processed before
        the event system was implemented.
        """
        doc = await self.db.hub_documents.find_one(
            {"id": document_id},
            {"workflow_history": 1, "_id": 0}
        )
        
        if not doc or not doc.get("workflow_history"):
            return []
        
        timeline = []
        for entry in doc.get("workflow_history", []):
            # Convert legacy history entry to event-like format
            event_type = self._map_legacy_event(entry)
            
            timeline.append({
                "event_id": entry.get("event_id", str(uuid.uuid4())),
                "event_type": event_type,
                "status": self._map_legacy_status(entry),
                "timestamp": entry.get("timestamp"),
                "source_service": entry.get("actor", "system"),
                "actor": entry.get("actor"),
                "correlation_id": entry.get("correlation_id"),
                "payload_summary": entry.get("reason", ""),
                "payload": entry.get("metadata", {}),
                "source": "legacy_history",
                # Include legacy fields for compatibility
                "legacy_from_status": entry.get("from_status"),
                "legacy_to_status": entry.get("to_status"),
                "legacy_event": entry.get("event")
            })
        
        return timeline
    
    def _map_legacy_event(self, entry: Dict) -> str:
        """Map legacy workflow_history event to new event type."""
        legacy_event = entry.get("event", "")
        to_status = entry.get("to_status", "")
        
        # Map common legacy events
        mapping = {
            "on_capture": "document.received",
            "on_classification_success": "classification.completed",
            "on_classification_failed": "classification.failed",
            "on_extraction_success": "extraction.completed",
            "on_extraction_failed": "extraction.failed",
            "on_extraction_low_confidence": "extraction.completed",
            "on_vendor_matched": "vendor.match.completed",
            "on_vendor_missing": "vendor.match.failed",
            "on_vendor_resolved": "vendor.resolved",
            "on_bc_valid": "bc.validation.completed",
            "on_bc_invalid": "bc.validation.failed",
            "on_bc_validation_override": "bc.validation.overridden",
            "on_approved": "review.approved",
            "on_rejected": "review.rejected",
            "on_exported": "sharepoint.upload.succeeded",
            "on_archived": "document.archived",
            "on_error": "system.error",
        }
        
        return mapping.get(legacy_event, f"legacy.{legacy_event or to_status}")
    
    def _map_legacy_status(self, entry: Dict) -> str:
        """Map legacy entry to event status."""
        to_status = entry.get("to_status", "")
        event = entry.get("event", "")
        
        if "failed" in event.lower() or "failed" in to_status.lower():
            return EventStatus.FAILED.value
        elif "warning" in str(entry.get("metadata", {})).lower():
            return EventStatus.WARNING.value
        
        return EventStatus.COMPLETED.value
    
    async def count_events(
        self,
        document_id: Optional[str] = None,
        event_type: Optional[str] = None,
        status: Optional[str] = None,
        since: Optional[str] = None
    ) -> int:
        """Count events matching criteria."""
        query = {}
        if document_id:
            query["document_id"] = document_id
        if event_type:
            query["event_type"] = event_type
        if status:
            query["status"] = status
        if since:
            query["timestamp"] = {"$gte": since}
        
        return await self.db.workflow_events.count_documents(query)
    
    # =========================================================================
    # Phase 3 Placeholder: Subscriber Registration
    # =========================================================================
    
    def register_subscriber(self, event_pattern: str, callback):
        """
        Register a subscriber for events matching a pattern.
        
        Phase 3 feature - placeholder for now.
        
        Args:
            event_pattern: Glob pattern for event types (e.g., "vendor.*")
            callback: Async function to call when matching event occurs
        """
        self._subscribers.append((event_pattern, callback))
        logger.info("Registered event subscriber for pattern: %s", event_pattern)
    
    async def _notify_subscribers(self, event: WorkflowEvent):
        """
        Notify all matching subscribers of an event.
        
        Phase 3 feature - placeholder implementation.
        """
        import fnmatch
        for pattern, callback in self._subscribers:
            if fnmatch.fnmatch(event.event_type, pattern):
                try:
                    await callback(event)
                except Exception as e:
                    logger.error(
                        "Subscriber error for %s on event %s: %s",
                        pattern, event.event_type, str(e)
                    )


# =============================================================================
# HELPER FUNCTIONS FOR EMITTING STANDARD EVENTS
# =============================================================================

async def emit_document_received(
    event_service: EventService,
    document_id: str,
    source: str,
    file_name: str,
    content_type: str,
    file_size: int,
    correlation_id: Optional[str] = None
) -> WorkflowEvent:
    """Helper to emit document.received event."""
    return await event_service.emit(
        event_type="document.received",
        document_id=document_id,
        source_service=source,
        correlation_id=correlation_id,
        payload={
            "source": source,
            "file_name": file_name,
            "content_type": content_type,
            "file_size": file_size
        }
    )


async def emit_classification_completed(
    event_service: EventService,
    document_id: str,
    doc_type: str,
    confidence: float,
    method: str,
    model: Optional[str] = None,
    correlation_id: Optional[str] = None
) -> WorkflowEvent:
    """Helper to emit classification.completed event."""
    return await event_service.emit(
        event_type="classification.completed",
        document_id=document_id,
        source_service="ai_classifier",
        correlation_id=correlation_id,
        payload={
            "doc_type": doc_type,
            "confidence": confidence,
            "method": method,
            "model": model
        }
    )


async def emit_vendor_match(
    event_service: EventService,
    document_id: str,
    matched: bool,
    vendor_name: Optional[str] = None,
    vendor_no: Optional[str] = None,
    match_method: Optional[str] = None,
    match_score: Optional[float] = None,
    source: str = "unified_vendor_matcher",
    correlation_id: Optional[str] = None,
    **extra_payload
) -> WorkflowEvent:
    """Helper to emit vendor.match.completed or vendor.match.failed event."""
    if matched:
        return await event_service.emit(
            event_type="vendor.match.completed",
            document_id=document_id,
            source_service=source,
            correlation_id=correlation_id,
            payload={
                "vendor_name": vendor_name,
                "vendor_no": vendor_no,
                "match_method": match_method,
                "match_score": match_score,
                "source": source,
                **extra_payload
            }
        )
    else:
        return await event_service.emit(
            event_type="vendor.match.failed",
            document_id=document_id,
            status=EventStatus.WARNING.value,
            source_service=source,
            correlation_id=correlation_id,
            payload={
                "vendor_raw": vendor_name,
                "reason": extra_payload.get("reason", "No match found"),
                **extra_payload
            }
        )


async def emit_bc_validation(
    event_service: EventService,
    document_id: str,
    passed: bool,
    checks: List[Dict],
    warnings: Optional[List] = None,
    correlation_id: Optional[str] = None
) -> WorkflowEvent:
    """Helper to emit bc.validation.completed or bc.validation.failed event."""
    checks_passed = sum(1 for c in checks if c.get("passed"))
    failed_checks_list = [c for c in checks if not c.get("passed")]
    required_failures = [c for c in failed_checks_list if c.get("required", False)]
    
    # Compute validation_status for derived state
    if required_failures:
        v_status = "fail"
    elif failed_checks_list:
        v_status = "warn"
    else:
        v_status = "pass"
    
    if passed:
        return await event_service.emit(
            event_type="bc.validation.completed",
            document_id=document_id,
            source_service="bc_sandbox_service",
            correlation_id=correlation_id,
            payload={
                "all_passed": True,
                "validation_status": v_status,
                "checks_passed": checks_passed,
                "checks_total": len(checks),
                "warnings": warnings or []
            }
        )
    else:
        failed_checks = [c.get("check_name") for c in checks if not c.get("passed")]
        return await event_service.emit(
            event_type="bc.validation.failed",
            document_id=document_id,
            status=EventStatus.FAILED.value,
            source_service="bc_sandbox_service",
            correlation_id=correlation_id,
            payload={
                "failed_checks": failed_checks,
                "checks_passed": checks_passed,
                "checks_total": len(checks),
                "errors": [c.get("details") for c in checks if not c.get("passed")]
            }
        )


async def emit_sharepoint_upload(
    event_service: EventService,
    document_id: str,
    success: bool,
    folder_path: str,
    drive_id: Optional[str] = None,
    item_id: Optional[str] = None,
    share_link: Optional[str] = None,
    error: Optional[str] = None,
    correlation_id: Optional[str] = None
) -> WorkflowEvent:
    """Helper to emit sharepoint.upload.succeeded or sharepoint.upload.failed event."""
    if success:
        return await event_service.emit(
            event_type="sharepoint.upload.succeeded",
            document_id=document_id,
            source_service="sharepoint_service",
            correlation_id=correlation_id,
            payload={
                "drive_id": drive_id,
                "item_id": item_id,
                "folder_path": folder_path,
                "share_link": share_link
            }
        )
    else:
        return await event_service.emit(
            event_type="sharepoint.upload.failed",
            document_id=document_id,
            status=EventStatus.FAILED.value,
            source_service="sharepoint_service",
            correlation_id=correlation_id,
            payload={
                "error": error,
                "folder_path": folder_path
            }
        )


async def emit_automation_decision(
    event_service: EventService,
    document_id: str,
    decision: str,
    reason: str,
    auto_clear: bool = False,
    auto_post: bool = False,
    correlation_id: Optional[str] = None,
    **extra_payload
) -> WorkflowEvent:
    """Helper to emit automation.decision.completed event."""
    return await event_service.emit(
        event_type="automation.decision.completed",
        document_id=document_id,
        source_service="auto_clear_service",
        correlation_id=correlation_id,
        payload={
            "decision": decision,
            "reason": reason,
            "auto_clear": auto_clear,
            "auto_post": auto_post,
            **extra_payload
        }
    )


# =============================================================================
# GLOBAL EVENT SERVICE INSTANCE
# =============================================================================

_event_service: Optional[EventService] = None


def get_event_service() -> Optional[EventService]:
    """Get the global event service instance."""
    return _event_service


def set_event_service(db) -> EventService:
    """Initialize and set the global event service instance."""
    global _event_service
    _event_service = EventService(db)
    return _event_service


async def initialize_event_indexes(db):
    """Create indexes for the workflow_events collection."""
    # Index for querying events by document
    await db.workflow_events.create_index(
        [("document_id", 1), ("timestamp", -1)],
        name="document_events_idx"
    )
    
    # Index for querying events by type
    await db.workflow_events.create_index(
        [("event_type", 1), ("timestamp", -1)],
        name="event_type_idx"
    )
    
    # Index for correlation ID lookups
    await db.workflow_events.create_index(
        "correlation_id",
        name="correlation_idx"
    )
    
    # Index for time-based queries
    await db.workflow_events.create_index(
        [("timestamp", -1)],
        name="timestamp_idx"
    )
    
    # Compound index for status queries
    await db.workflow_events.create_index(
        [("document_id", 1), ("status", 1)],
        name="document_status_idx"
    )
    
    logger.info("Created indexes for workflow_events collection")

async def emit_intake_events(
    doc_id: str, 
    correlation_id: str,
    classification: dict,
    validation_results: dict,
    sp_result: dict,
    decision: str,
    auto_clear_result: dict
):
    """
    Emit events for the intake pipeline.
    This is called after the main intake processing to record events.
    """
    event_service = get_event_service()
    if not event_service:
        return
    
    # Classification event
    await emit_classification_completed(
        event_service, doc_id,
        classification.get("suggested_job_type", "Unknown"),
        classification.get("confidence", 0.0),
        classification.get("classification_method", "ai"),
        classification.get("model"),
        correlation_id
    )
    
    # Vendor match event
    matched_vendor = validation_results.get("matched_vendor_no")
    await emit_vendor_match(
        event_service, doc_id,
        matched=bool(matched_vendor),
        vendor_name=validation_results.get("matched_vendor_name"),
        vendor_no=matched_vendor,
        match_method=validation_results.get("match_method", "none"),
        match_score=validation_results.get("match_score", 0.0),
        correlation_id=correlation_id
    )
    
    # BC validation event
    await emit_bc_validation(
        event_service, doc_id,
        passed=validation_results.get("all_passed", False),
        checks=validation_results.get("checks", []),
        warnings=validation_results.get("warnings"),
        correlation_id=correlation_id
    )
    
    # SharePoint upload event
    if sp_result:
        await emit_sharepoint_upload(
            event_service, doc_id,
            success=True,
            folder_path=sp_result.get("folder_path", ""),
            drive_id=sp_result.get("drive_id"),
            item_id=sp_result.get("item_id"),
            share_link=sp_result.get("share_link"),
            correlation_id=correlation_id
        )
    
    # Automation decision event
    auto_cleared = auto_clear_result and auto_clear_result.get("cleared", False)
    await emit_automation_decision(
        event_service, doc_id,
        decision=decision,
        reason=auto_clear_result.get("reason") if auto_clear_result else "",
        auto_clear=auto_cleared,
        auto_post=False,
        correlation_id=correlation_id
    )
    
    # Update derived state
    derived_state_service = get_derived_state_service()
    if derived_state_service:
        await derived_state_service.update_document_derived_state(doc_id)
