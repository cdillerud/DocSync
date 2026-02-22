"""
GPI Document Hub - Migration Job

This module implements the core migration logic for importing legacy documents
from Square9 and Zetadocs into GPI Hub.

The migration job:
1. Reads documents from a LegacyDocumentSource
2. Classifies each document using the existing classification pipeline
3. Maps legacy fields to the GPI Hub document model
4. Initializes workflow states based on legacy status
5. Optionally writes to the database (or runs in dry-run mode)
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum

from ..workflow_engine import (
    DocType, SourceSystem, CaptureChannel, DocumentClassifier,
    WorkflowStatus, ZETADOCS_SET_MAPPING, SQUARE9_WORKFLOW_MAPPING
)
from .sources import LegacyDocumentSource, LegacyDocument, LegacyDocumentMetadata
from .workflow_initializer import WorkflowInitializer

logger = logging.getLogger(__name__)


class MigrationMode(str, Enum):
    """Migration execution modes."""
    DRY_RUN = "dry_run"     # Validate and report without writing
    REAL = "real"           # Actually write to database


@dataclass
class MigrationStats:
    """Statistics for a migration run."""
    total_processed: int = 0
    total_success: int = 0
    total_skipped: int = 0
    total_errors: int = 0
    
    by_doc_type: Dict[str, int] = field(default_factory=dict)
    by_source_system: Dict[str, int] = field(default_factory=dict)
    by_workflow_status: Dict[str, int] = field(default_factory=dict)
    
    errors: List[Dict[str, Any]] = field(default_factory=list)
    
    def record_success(
        self,
        doc_type: str,
        source_system: str,
        workflow_status: str
    ) -> None:
        """Record a successful migration."""
        self.total_processed += 1
        self.total_success += 1
        
        self.by_doc_type[doc_type] = self.by_doc_type.get(doc_type, 0) + 1
        self.by_source_system[source_system] = self.by_source_system.get(source_system, 0) + 1
        self.by_workflow_status[workflow_status] = self.by_workflow_status.get(workflow_status, 0) + 1
    
    def record_skip(self, reason: str, legacy_id: str) -> None:
        """Record a skipped document."""
        self.total_processed += 1
        self.total_skipped += 1
        logger.info(f"Skipped document {legacy_id}: {reason}")
    
    def record_error(self, error: str, legacy_id: str) -> None:
        """Record a migration error."""
        self.total_processed += 1
        self.total_errors += 1
        self.errors.append({
            "legacy_id": legacy_id,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        logger.error(f"Error migrating {legacy_id}: {error}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_processed": self.total_processed,
            "total_success": self.total_success,
            "total_skipped": self.total_skipped,
            "total_errors": self.total_errors,
            "by_doc_type": self.by_doc_type,
            "by_source_system": self.by_source_system,
            "by_workflow_status": self.by_workflow_status,
            "errors": self.errors[:100],  # Limit errors in output
            "error_count": len(self.errors)
        }


@dataclass
class MigrationResult:
    """Result of a migration job run."""
    mode: str
    source_name: str
    started_at: str
    completed_at: str
    duration_seconds: float
    stats: MigrationStats
    
    # Sample of migrated documents (for dry-run review)
    sample_documents: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "mode": self.mode,
            "source_name": self.source_name,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "stats": self.stats.to_dict(),
            "sample_documents": self.sample_documents[:20],  # Limit sample size
        }


class MigrationJob:
    """
    Core migration job for importing legacy documents into GPI Hub.
    
    The job can run in two modes:
    - DRY_RUN: Validates and transforms documents without writing to the database
    - REAL: Actually writes documents to the database
    
    Usage:
        source = JsonFileSource("/path/to/export.json")
        job = MigrationJob(source)
        result = await job.run(mode=MigrationMode.DRY_RUN)
        
        # Review result, then run for real
        if result.stats.total_errors == 0:
            result = await job.run(mode=MigrationMode.REAL)
    """
    
    def __init__(
        self,
        source: LegacyDocumentSource,
        db_collection=None,
        skip_duplicates: bool = True,
        batch_size: int = 100
    ):
        """
        Initialize the migration job.
        
        Args:
            source: The legacy document source to read from
            db_collection: MongoDB collection for hub_documents (required for REAL mode)
            skip_duplicates: If True, skip documents with matching legacy_id
            batch_size: Number of documents to process in each batch
        """
        self.source = source
        self.db_collection = db_collection
        self.skip_duplicates = skip_duplicates
        self.batch_size = batch_size
        
        self._migration_timestamp = None
    
    async def run(
        self,
        mode: MigrationMode = MigrationMode.DRY_RUN,
        source_filter: Optional[str] = None,
        doc_type_filter: Optional[str] = None,
        limit: Optional[int] = None
    ) -> MigrationResult:
        """
        Execute the migration job.
        
        Args:
            mode: DRY_RUN to validate only, REAL to write to database
            source_filter: Filter by legacy system ("SQUARE9", "ZETADOCS")
            doc_type_filter: Filter by document type
            limit: Maximum number of documents to process
            
        Returns:
            MigrationResult with statistics and sample documents
        """
        started_at = datetime.now(timezone.utc)
        self._migration_timestamp = started_at.isoformat()
        
        stats = MigrationStats()
        sample_documents = []
        
        logger.info(
            f"Starting migration job in {mode.value} mode from {self.source.get_source_name()}"
        )
        
        # Validate REAL mode requirements
        if mode == MigrationMode.REAL and self.db_collection is None:
            raise ValueError("db_collection is required for REAL mode migration")
        
        # Get existing legacy IDs if skip_duplicates is enabled
        existing_ids = set()
        if self.skip_duplicates and mode == MigrationMode.REAL:
            existing_ids = await self._get_existing_legacy_ids()
            logger.info(f"Found {len(existing_ids)} existing migrated documents")
        
        # Process documents
        batch = []
        for legacy_doc in self.source.iter_documents(source_filter, doc_type_filter, limit):
            try:
                # Skip duplicates
                if legacy_doc.metadata.legacy_id in existing_ids:
                    stats.record_skip(
                        "Duplicate legacy_id",
                        legacy_doc.metadata.legacy_id
                    )
                    continue
                
                # Transform to GPI Hub document
                gpi_doc = self._transform_document(legacy_doc)
                
                if gpi_doc is None:
                    stats.record_skip(
                        "Transformation failed",
                        legacy_doc.metadata.legacy_id
                    )
                    continue
                
                # Collect sample for dry-run review
                if len(sample_documents) < 20:
                    sample_documents.append(gpi_doc)
                
                # Record success stats
                stats.record_success(
                    gpi_doc.get("doc_type", "OTHER"),
                    gpi_doc.get("source_system", "UNKNOWN"),
                    gpi_doc.get("workflow_status", "unknown")
                )
                
                # Batch for database insertion
                if mode == MigrationMode.REAL:
                    batch.append(gpi_doc)
                    
                    if len(batch) >= self.batch_size:
                        await self._write_batch(batch)
                        batch = []
            
            except Exception as e:
                stats.record_error(str(e), legacy_doc.metadata.legacy_id)
        
        # Write remaining batch
        if mode == MigrationMode.REAL and batch:
            await self._write_batch(batch)
        
        # Build result
        completed_at = datetime.now(timezone.utc)
        duration = (completed_at - started_at).total_seconds()
        
        result = MigrationResult(
            mode=mode.value,
            source_name=self.source.get_source_name(),
            started_at=started_at.isoformat(),
            completed_at=completed_at.isoformat(),
            duration_seconds=duration,
            stats=stats,
            sample_documents=sample_documents
        )
        
        logger.info(
            f"Migration completed: {stats.total_success} success, "
            f"{stats.total_skipped} skipped, {stats.total_errors} errors "
            f"in {duration:.2f}s"
        )
        
        return result
    
    def _transform_document(self, legacy_doc: LegacyDocument) -> Optional[Dict[str, Any]]:
        """
        Transform a legacy document to GPI Hub document format.
        
        This includes:
        1. Classification (doc_type determination)
        2. Field mapping
        3. Workflow initialization
        """
        metadata = legacy_doc.metadata
        
        # Step 1: Determine doc_type using existing classification logic
        doc_type, capture_channel = self._classify_document(metadata)
        
        # Step 2: Determine source_system
        source_system = self._map_source_system(metadata.legacy_system)
        
        # Step 3: Initialize workflow state
        workflow_result = WorkflowInitializer.initialize(
            doc_type=doc_type,
            metadata=metadata,
            migration_timestamp=self._migration_timestamp
        )
        
        # Step 4: Build the GPI Hub document
        doc_id = str(uuid.uuid4())
        
        gpi_doc = {
            "id": doc_id,
            "doc_type": doc_type,
            "source_system": source_system,
            "capture_channel": capture_channel,
            
            # Legacy identifiers
            "legacy_system": metadata.legacy_system,
            "legacy_id": metadata.legacy_id,
            "legacy_workflow_name": metadata.legacy_workflow_name,
            "legacy_zetadocs_set_code": metadata.legacy_zetadocs_set_code,
            "legacy_bc_doc_no": metadata.legacy_bc_doc_no,
            "legacy_file_reference": legacy_doc.binary_reference,
            
            # Classification tracking
            "classification_method": f"migration:{metadata.legacy_system}",
            
            # Workflow state
            "workflow_status": workflow_result.workflow_status,
            "workflow_history": workflow_result.workflow_history,
            "workflow_status_updated_utc": self._migration_timestamp,
            
            # Timestamps
            "created_utc": self._migration_timestamp,
            "updated_utc": self._migration_timestamp,
            "migrated_utc": self._migration_timestamp,
            
            # Status tracking
            "status": "migrated",
            "is_migrated": True,
        }
        
        # Add business fields based on document type
        self._add_business_fields(gpi_doc, metadata, doc_type)
        
        # Add legacy status snapshot
        gpi_doc["legacy_status"] = {
            "is_paid": metadata.is_paid,
            "is_posted": metadata.is_posted,
            "is_exported": metadata.is_exported,
            "is_approved": metadata.is_approved,
            "is_canceled": metadata.is_canceled,
            "is_voided": metadata.is_voided,
            "is_closed": metadata.is_closed,
            "is_reviewed": metadata.is_reviewed,
        }
        
        return gpi_doc
    
    def _classify_document(
        self,
        metadata: LegacyDocumentMetadata
    ) -> Tuple[str, str]:
        """
        Classify the document using deterministic rules.
        
        Reuses the existing classification logic from workflow_engine.
        """
        doc_type = DocType.OTHER.value
        capture_channel = CaptureChannel.MIGRATION_JOB.value
        
        # Try Zetadocs set code first
        if metadata.legacy_zetadocs_set_code:
            result = ZETADOCS_SET_MAPPING.get(metadata.legacy_zetadocs_set_code)
            if result:
                doc_type_enum, channel_override = result
                doc_type = doc_type_enum.value
                if channel_override:
                    capture_channel = channel_override.value
                return doc_type, capture_channel
        
        # Try Square9 workflow name
        if metadata.legacy_workflow_name:
            doc_type_enum = SQUARE9_WORKFLOW_MAPPING.get(metadata.legacy_workflow_name)
            if doc_type_enum:
                doc_type = doc_type_enum.value
                return doc_type, capture_channel
        
        # Try to infer from available fields
        doc_type = self._infer_doc_type_from_fields(metadata)
        
        return doc_type, capture_channel
    
    def _infer_doc_type_from_fields(self, metadata: LegacyDocumentMetadata) -> str:
        """
        Infer document type from available business fields.
        
        This is a fallback when workflow/set code is not available.
        """
        # Quality doc indicators
        if metadata.quality_tags or metadata.quality_category:
            return DocType.QUALITY_DOC.value
        
        # If we have vendor info and invoice number, likely AP Invoice
        if metadata.vendor_no and metadata.invoice_number:
            return DocType.AP_INVOICE.value
        
        # If we have customer info, likely Sales Invoice
        if metadata.customer_no and metadata.invoice_number:
            return DocType.SALES_INVOICE.value
        
        # If we have PO number without invoice number, likely PO
        if metadata.po_number and not metadata.invoice_number:
            return DocType.PURCHASE_ORDER.value
        
        # Default to OTHER
        return DocType.OTHER.value
    
    def _map_source_system(self, legacy_system: str) -> str:
        """Map legacy system name to SourceSystem enum value."""
        mapping = {
            "SQUARE9": SourceSystem.SQUARE9.value,
            "ZETADOCS": SourceSystem.ZETADOCS.value,
        }
        return mapping.get(legacy_system, SourceSystem.UNKNOWN.value)
    
    def _add_business_fields(
        self,
        gpi_doc: Dict[str, Any],
        metadata: LegacyDocumentMetadata,
        doc_type: str
    ) -> None:
        """
        Add business-specific fields to the GPI Hub document.
        
        Different document types have different relevant fields.
        """
        # Common extracted fields structure
        extracted_fields = {}
        
        # Vendor/Customer fields
        if metadata.vendor_name:
            gpi_doc["vendor_name"] = metadata.vendor_name
            gpi_doc["vendor_raw"] = metadata.vendor_name
            gpi_doc["vendor_normalized"] = metadata.vendor_name.upper().strip()
            extracted_fields["vendor"] = metadata.vendor_name
        
        if metadata.vendor_no:
            gpi_doc["vendor_no"] = metadata.vendor_no
            gpi_doc["vendor_canonical"] = metadata.vendor_no
            extracted_fields["vendor_no"] = metadata.vendor_no
        
        if metadata.customer_name:
            gpi_doc["customer_name"] = metadata.customer_name
            extracted_fields["customer"] = metadata.customer_name
        
        if metadata.customer_no:
            gpi_doc["customer_no"] = metadata.customer_no
            extracted_fields["customer_no"] = metadata.customer_no
        
        # Invoice/Document number
        if metadata.invoice_number:
            gpi_doc["invoice_number"] = metadata.invoice_number
            gpi_doc["invoice_number_raw"] = metadata.invoice_number
            gpi_doc["invoice_number_clean"] = metadata.invoice_number.strip().upper()
            extracted_fields["invoice_number"] = metadata.invoice_number
        
        if metadata.document_number:
            gpi_doc["document_number"] = metadata.document_number
            extracted_fields["document_number"] = metadata.document_number
        
        # PO Number
        if metadata.po_number:
            gpi_doc["po_number"] = metadata.po_number
            gpi_doc["po_number_raw"] = metadata.po_number
            gpi_doc["po_number_clean"] = metadata.po_number.strip().upper()
            extracted_fields["po_number"] = metadata.po_number
        
        # Amount and currency
        if metadata.amount is not None:
            gpi_doc["amount"] = metadata.amount
            gpi_doc["amount_raw"] = str(metadata.amount)
            gpi_doc["amount_float"] = float(metadata.amount)
            extracted_fields["total_amount"] = metadata.amount
        
        if metadata.currency:
            gpi_doc["currency"] = metadata.currency
            extracted_fields["currency"] = metadata.currency
        
        # Dates
        if metadata.invoice_date:
            gpi_doc["invoice_date"] = metadata.invoice_date
            extracted_fields["invoice_date"] = metadata.invoice_date
        
        if metadata.due_date:
            gpi_doc["due_date"] = metadata.due_date
            gpi_doc["due_date_raw"] = metadata.due_date
            gpi_doc["due_date_iso"] = metadata.due_date
            extracted_fields["due_date"] = metadata.due_date
        
        if metadata.posting_date:
            gpi_doc["posting_date"] = metadata.posting_date
        
        # Quality doc specific
        if doc_type == DocType.QUALITY_DOC.value:
            if metadata.quality_tags:
                gpi_doc["quality_tags"] = metadata.quality_tags
            if metadata.quality_category:
                gpi_doc["quality_category"] = metadata.quality_category
        
        # Store original dates
        if metadata.created_date:
            gpi_doc["legacy_created_date"] = metadata.created_date
        
        if metadata.modified_date:
            gpi_doc["legacy_modified_date"] = metadata.modified_date
        
        if metadata.created_by:
            gpi_doc["legacy_created_by"] = metadata.created_by
        
        # Store extracted fields
        if extracted_fields:
            gpi_doc["extracted_fields"] = extracted_fields
        
        # Store any extra fields
        if metadata.extra:
            gpi_doc["legacy_extra"] = metadata.extra
    
    async def _get_existing_legacy_ids(self) -> set:
        """Get set of legacy_ids already in the database."""
        if self.db_collection is None:
            return set()
        
        cursor = self.db_collection.find(
            {"is_migrated": True},
            {"legacy_id": 1, "_id": 0}
        )
        
        ids = set()
        async for doc in cursor:
            if doc.get("legacy_id"):
                ids.add(doc["legacy_id"])
        
        return ids
    
    async def _write_batch(self, batch: List[Dict[str, Any]]) -> None:
        """Write a batch of documents to the database."""
        if not batch or self.db_collection is None:
            return
        
        try:
            result = await self.db_collection.insert_many(batch)
            logger.debug(f"Inserted batch of {len(result.inserted_ids)} documents")
        except Exception as e:
            logger.error(f"Error writing batch: {e}")
            raise


class MigrationJobBuilder:
    """
    Builder pattern for creating migration jobs with various configurations.
    
    Example:
        job = (MigrationJobBuilder()
            .with_json_source("/path/to/export.json")
            .with_db_collection(db.hub_documents)
            .skip_duplicates(True)
            .batch_size(50)
            .build())
    """
    
    def __init__(self):
        self._source = None
        self._db_collection = None
        self._skip_duplicates = True
        self._batch_size = 100
    
    def with_source(self, source: LegacyDocumentSource) -> 'MigrationJobBuilder':
        """Set the document source."""
        self._source = source
        return self
    
    def with_json_source(self, file_path: str) -> 'MigrationJobBuilder':
        """Use a JSON file as the source."""
        from .sources import JsonFileSource
        self._source = JsonFileSource(file_path)
        return self
    
    def with_db_collection(self, collection) -> 'MigrationJobBuilder':
        """Set the database collection."""
        self._db_collection = collection
        return self
    
    def skip_duplicates(self, skip: bool) -> 'MigrationJobBuilder':
        """Configure duplicate handling."""
        self._skip_duplicates = skip
        return self
    
    def batch_size(self, size: int) -> 'MigrationJobBuilder':
        """Set the batch size."""
        self._batch_size = size
        return self
    
    def build(self) -> MigrationJob:
        """Build the migration job."""
        if self._source is None:
            raise ValueError("Source is required")
        
        return MigrationJob(
            source=self._source,
            db_collection=self._db_collection,
            skip_duplicates=self._skip_duplicates,
            batch_size=self._batch_size
        )
