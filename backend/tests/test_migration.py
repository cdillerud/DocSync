"""
Tests for Legacy Migration Module

Tests the migration job, sources, and workflow initialization.
"""
import pytest
import sys
sys.path.insert(0, '/app/backend')

from services.migration import (
    LegacyDocumentSource, JsonFileSource, InMemorySource,
    MigrationJob, MigrationResult, WorkflowInitializer
)
from services.migration.sources import LegacyDocumentMetadata, LegacyDocument
from services.migration.job import MigrationMode, MigrationStats
from services.workflow_engine import WorkflowStatus, DocType


class TestLegacyDocumentMetadata:
    """Tests for LegacyDocumentMetadata."""
    
    def test_to_dict_minimal(self):
        """Test minimal metadata conversion."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001"
        )
        d = metadata.to_dict()
        assert d["legacy_system"] == "SQUARE9"
        assert d["legacy_id"] == "S9-001"
        assert "vendor_name" not in d  # Optional fields not included
    
    def test_to_dict_with_business_fields(self):
        """Test metadata with business fields."""
        metadata = LegacyDocumentMetadata(
            legacy_system="ZETADOCS",
            legacy_id="ZD-001",
            legacy_zetadocs_set_code="ZD00015",
            vendor_name="Acme Corp",
            invoice_number="INV-001",
            amount=1500.00,
            is_posted=True,
            is_paid=True
        )
        d = metadata.to_dict()
        assert d["legacy_zetadocs_set_code"] == "ZD00015"
        assert d["vendor_name"] == "Acme Corp"
        assert d["amount"] == 1500.00
        assert d["is_posted"] == True
        assert d["is_paid"] == True
    
    def test_to_dict_excludes_false_flags(self):
        """Test that False flags are not included."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001",
            is_paid=False,
            is_exported=False
        )
        d = metadata.to_dict()
        assert "is_paid" not in d
        assert "is_exported" not in d


class TestInMemorySource:
    """Tests for InMemorySource."""
    
    def test_add_and_iterate(self):
        """Test adding documents and iterating."""
        source = InMemorySource("test")
        
        doc1 = LegacyDocument(
            metadata=LegacyDocumentMetadata("SQUARE9", "S9-001"),
            binary_reference="/path/to/file1.pdf"
        )
        doc2 = LegacyDocument(
            metadata=LegacyDocumentMetadata("ZETADOCS", "ZD-001"),
            binary_reference="/path/to/file2.pdf"
        )
        
        source.add_document(doc1)
        source.add_document(doc2)
        
        docs = list(source.iter_documents())
        assert len(docs) == 2
    
    def test_source_filter(self):
        """Test filtering by source system."""
        source = InMemorySource("test")
        
        source.add_documents([
            LegacyDocument(
                metadata=LegacyDocumentMetadata("SQUARE9", "S9-001")
            ),
            LegacyDocument(
                metadata=LegacyDocumentMetadata("ZETADOCS", "ZD-001")
            ),
            LegacyDocument(
                metadata=LegacyDocumentMetadata("SQUARE9", "S9-002")
            ),
        ])
        
        square9_docs = list(source.iter_documents(source_filter="SQUARE9"))
        assert len(square9_docs) == 2
        
        zetadocs_docs = list(source.iter_documents(source_filter="ZETADOCS"))
        assert len(zetadocs_docs) == 1
    
    def test_limit(self):
        """Test document limit."""
        source = InMemorySource("test")
        
        for i in range(10):
            source.add_document(
                LegacyDocument(
                    metadata=LegacyDocumentMetadata("SQUARE9", f"S9-{i:03d}")
                )
            )
        
        docs = list(source.iter_documents(limit=3))
        assert len(docs) == 3
    
    def test_get_document_count(self):
        """Test document counting."""
        source = InMemorySource("test")
        
        for i in range(5):
            source.add_document(
                LegacyDocument(
                    metadata=LegacyDocumentMetadata("SQUARE9", f"S9-{i:03d}")
                )
            )
        
        assert source.get_document_count() == 5


class TestWorkflowInitializerAPInvoice:
    """Tests for AP Invoice workflow initialization."""
    
    def test_posted_and_paid_goes_to_exported(self):
        """Test that posted+paid AP invoices go to exported."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001",
            is_posted=True,
            is_paid=True
        )
        
        result = WorkflowInitializer.initialize(DocType.AP_INVOICE.value, metadata)
        assert result.workflow_status == WorkflowStatus.EXPORTED.value
    
    def test_exported_goes_to_exported(self):
        """Test that exported AP invoices stay exported."""
        metadata = LegacyDocumentMetadata(
            legacy_system="ZETADOCS",
            legacy_id="ZD-001",
            is_exported=True
        )
        
        result = WorkflowInitializer.initialize(DocType.AP_INVOICE.value, metadata)
        assert result.workflow_status == WorkflowStatus.EXPORTED.value
    
    def test_posted_only_goes_to_approved(self):
        """Test that posted (not paid) goes to approved."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001",
            is_posted=True,
            is_paid=False
        )
        
        result = WorkflowInitializer.initialize(DocType.AP_INVOICE.value, metadata)
        assert result.workflow_status == WorkflowStatus.APPROVED.value
    
    def test_approved_goes_to_approved(self):
        """Test approved invoice."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001",
            is_approved=True
        )
        
        result = WorkflowInitializer.initialize(DocType.AP_INVOICE.value, metadata)
        assert result.workflow_status == WorkflowStatus.APPROVED.value
    
    def test_canceled_goes_to_rejected(self):
        """Test canceled invoice."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001",
            is_canceled=True
        )
        
        result = WorkflowInitializer.initialize(DocType.AP_INVOICE.value, metadata)
        assert result.workflow_status == WorkflowStatus.REJECTED.value
    
    def test_pending_goes_to_extracted(self):
        """Test pending invoice goes to extracted."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001"
        )
        
        result = WorkflowInitializer.initialize(DocType.AP_INVOICE.value, metadata)
        assert result.workflow_status == WorkflowStatus.EXTRACTED.value


class TestWorkflowInitializerPurchaseOrder:
    """Tests for Purchase Order workflow initialization."""
    
    def test_closed_goes_to_exported(self):
        """Test closed PO goes to exported."""
        metadata = LegacyDocumentMetadata(
            legacy_system="ZETADOCS",
            legacy_id="ZD-001",
            is_closed=True
        )
        
        result = WorkflowInitializer.initialize(DocType.PURCHASE_ORDER.value, metadata)
        assert result.workflow_status == WorkflowStatus.EXPORTED.value
    
    def test_approved_goes_to_approved(self):
        """Test approved PO."""
        metadata = LegacyDocumentMetadata(
            legacy_system="ZETADOCS",
            legacy_id="ZD-001",
            is_approved=True
        )
        
        result = WorkflowInitializer.initialize(DocType.PURCHASE_ORDER.value, metadata)
        assert result.workflow_status == WorkflowStatus.APPROVED.value
    
    def test_open_with_vendor_goes_to_validation_pending(self):
        """Test open PO with vendor goes to validation_pending."""
        metadata = LegacyDocumentMetadata(
            legacy_system="ZETADOCS",
            legacy_id="ZD-001",
            vendor_no="V10001"
        )
        
        result = WorkflowInitializer.initialize(DocType.PURCHASE_ORDER.value, metadata)
        assert result.workflow_status == WorkflowStatus.VALIDATION_PENDING.value


class TestWorkflowInitializerStatement:
    """Tests for Statement workflow initialization."""
    
    def test_closed_goes_to_archived(self):
        """Test closed statement goes to archived."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001",
            is_closed=True
        )
        
        result = WorkflowInitializer.initialize(DocType.STATEMENT.value, metadata)
        assert result.workflow_status == WorkflowStatus.ARCHIVED.value
    
    def test_reviewed_goes_to_reviewed(self):
        """Test reviewed statement."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001",
            is_reviewed=True
        )
        
        result = WorkflowInitializer.initialize(DocType.STATEMENT.value, metadata)
        assert result.workflow_status == WorkflowStatus.REVIEWED.value
    
    def test_pending_goes_to_ready_for_review(self):
        """Test pending statement."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001"
        )
        
        result = WorkflowInitializer.initialize(DocType.STATEMENT.value, metadata)
        assert result.workflow_status == WorkflowStatus.READY_FOR_REVIEW.value


class TestWorkflowInitializerQualityDoc:
    """Tests for Quality Doc workflow initialization."""
    
    def test_reviewed_and_closed_goes_to_exported(self):
        """Test fully processed quality doc."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001",
            is_reviewed=True,
            is_closed=True
        )
        
        result = WorkflowInitializer.initialize(DocType.QUALITY_DOC.value, metadata)
        assert result.workflow_status == WorkflowStatus.EXPORTED.value
    
    def test_reviewed_goes_to_reviewed(self):
        """Test reviewed quality doc."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001",
            is_reviewed=True
        )
        
        result = WorkflowInitializer.initialize(DocType.QUALITY_DOC.value, metadata)
        assert result.workflow_status == WorkflowStatus.REVIEWED.value
    
    def test_tagged_goes_to_tagged(self):
        """Test tagged quality doc."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001",
            quality_tags=["inspection", "passed"]
        )
        
        result = WorkflowInitializer.initialize(DocType.QUALITY_DOC.value, metadata)
        assert result.workflow_status == WorkflowStatus.TAGGED.value
    
    def test_pending_goes_to_ready_for_review(self):
        """Test pending quality doc."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001"
        )
        
        result = WorkflowInitializer.initialize(DocType.QUALITY_DOC.value, metadata)
        assert result.workflow_status == WorkflowStatus.READY_FOR_REVIEW.value


class TestWorkflowInitializerOther:
    """Tests for OTHER document workflow initialization."""
    
    def test_exported_goes_to_exported(self):
        """Test exported OTHER doc."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001",
            is_exported=True
        )
        
        result = WorkflowInitializer.initialize(DocType.OTHER.value, metadata)
        assert result.workflow_status == WorkflowStatus.EXPORTED.value
    
    def test_reviewed_goes_to_triage_completed(self):
        """Test reviewed OTHER doc."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001",
            is_reviewed=True
        )
        
        result = WorkflowInitializer.initialize(DocType.OTHER.value, metadata)
        assert result.workflow_status == WorkflowStatus.TRIAGE_COMPLETED.value
    
    def test_pending_goes_to_triage_pending(self):
        """Test pending OTHER doc."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001"
        )
        
        result = WorkflowInitializer.initialize(DocType.OTHER.value, metadata)
        assert result.workflow_status == WorkflowStatus.TRIAGE_PENDING.value


class TestWorkflowInitializerHistory:
    """Tests for workflow history initialization."""
    
    def test_history_entry_created(self):
        """Test that history entry is created."""
        metadata = LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-001",
            is_posted=True
        )
        
        result = WorkflowInitializer.initialize(DocType.AP_INVOICE.value, metadata)
        
        assert len(result.workflow_history) == 1
        entry = result.workflow_history[0]
        assert entry["user"] == "migration_job"
        assert entry["from_status"] is None
        assert entry["to_status"] == result.workflow_status
        assert "SQUARE9" in entry["reason"]
    
    def test_history_includes_legacy_id(self):
        """Test that history includes legacy_id."""
        metadata = LegacyDocumentMetadata(
            legacy_system="ZETADOCS",
            legacy_id="ZD-123"
        )
        
        result = WorkflowInitializer.initialize(DocType.AP_INVOICE.value, metadata)
        entry = result.workflow_history[0]
        
        assert entry["metadata"]["legacy_id"] == "ZD-123"


class TestMigrationStats:
    """Tests for MigrationStats."""
    
    def test_record_success(self):
        """Test recording successful migration."""
        stats = MigrationStats()
        
        stats.record_success(
            doc_type="AP_INVOICE",
            source_system="SQUARE9",
            workflow_status="exported"
        )
        
        assert stats.total_processed == 1
        assert stats.total_success == 1
        assert stats.by_doc_type["AP_INVOICE"] == 1
        assert stats.by_source_system["SQUARE9"] == 1
        assert stats.by_workflow_status["exported"] == 1
    
    def test_record_skip(self):
        """Test recording skipped document."""
        stats = MigrationStats()
        
        stats.record_skip("Duplicate", "S9-001")
        
        assert stats.total_processed == 1
        assert stats.total_skipped == 1
    
    def test_record_error(self):
        """Test recording migration error."""
        stats = MigrationStats()
        
        stats.record_error("Invalid data", "S9-001")
        
        assert stats.total_processed == 1
        assert stats.total_errors == 1
        assert len(stats.errors) == 1


class TestMigrationJobTransform:
    """Tests for MigrationJob document transformation."""
    
    def test_transform_ap_invoice(self):
        """Test transforming AP Invoice."""
        source = InMemorySource("test")
        job = MigrationJob(source)
        job._migration_timestamp = "2026-02-22T12:00:00Z"
        
        legacy_doc = LegacyDocument(
            metadata=LegacyDocumentMetadata(
                legacy_system="SQUARE9",
                legacy_id="S9-AP-001",
                legacy_workflow_name="AP_Invoice",
                vendor_name="Acme Corp",
                vendor_no="V10001",
                invoice_number="INV-001",
                amount=1500.00,
                is_posted=True,
                is_paid=True
            ),
            binary_reference="/path/to/inv.pdf"
        )
        
        gpi_doc = job._transform_document(legacy_doc)
        
        assert gpi_doc["doc_type"] == "AP_INVOICE"
        assert gpi_doc["source_system"] == "SQUARE9"
        assert gpi_doc["capture_channel"] == "MIGRATION_JOB"
        assert gpi_doc["legacy_id"] == "S9-AP-001"
        assert gpi_doc["workflow_status"] == "exported"
        assert gpi_doc["vendor_name"] == "Acme Corp"
        assert gpi_doc["invoice_number"] == "INV-001"
        assert gpi_doc["amount"] == 1500.00
        assert gpi_doc["is_migrated"] == True
    
    def test_transform_zetadocs_invoice(self):
        """Test transforming Zetadocs invoice using set code."""
        source = InMemorySource("test")
        job = MigrationJob(source)
        job._migration_timestamp = "2026-02-22T12:00:00Z"
        
        legacy_doc = LegacyDocument(
            metadata=LegacyDocumentMetadata(
                legacy_system="ZETADOCS",
                legacy_id="ZD-15-001",
                legacy_zetadocs_set_code="ZD00015",
                vendor_name="Parts Co",
                invoice_number="GP-001"
            )
        )
        
        gpi_doc = job._transform_document(legacy_doc)
        
        assert gpi_doc["doc_type"] == "AP_INVOICE"
        assert gpi_doc["source_system"] == "ZETADOCS"
        assert gpi_doc["legacy_zetadocs_set_code"] == "ZD00015"
    
    def test_transform_quality_doc(self):
        """Test transforming Quality Doc."""
        source = InMemorySource("test")
        job = MigrationJob(source)
        job._migration_timestamp = "2026-02-22T12:00:00Z"
        
        legacy_doc = LegacyDocument(
            metadata=LegacyDocumentMetadata(
                legacy_system="SQUARE9",
                legacy_id="S9-QC-001",
                legacy_workflow_name="Quality",
                quality_tags=["inspection", "passed"],
                quality_category="Final QC",
                is_reviewed=True
            )
        )
        
        gpi_doc = job._transform_document(legacy_doc)
        
        assert gpi_doc["doc_type"] == "QUALITY_DOC"
        assert gpi_doc["workflow_status"] == "reviewed"
        assert gpi_doc["quality_tags"] == ["inspection", "passed"]
        assert gpi_doc["quality_category"] == "Final QC"


class TestSupportedDocTypes:
    """Test supported document types."""
    
    def test_all_required_types_supported(self):
        """Verify all required types have initialization logic."""
        supported = WorkflowInitializer.get_supported_doc_types()
        
        required = [
            "AP_INVOICE",
            "SALES_INVOICE",
            "PURCHASE_ORDER",
            "STATEMENT",
            "QUALITY_DOC",
        ]
        
        for doc_type in required:
            assert doc_type in supported, f"Missing support for {doc_type}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
