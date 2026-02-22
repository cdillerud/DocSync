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


# ===========================================================
# ASYNC INTEGRATION TESTS FOR MigrationJob.run()
# ===========================================================

class MockAsyncCollection:
    """Mock MongoDB async collection for testing."""
    
    def __init__(self):
        self.documents = []
        self._existing_legacy_ids = set()
    
    def add_existing_legacy_ids(self, ids):
        """Simulate existing migrated documents."""
        self._existing_legacy_ids.update(ids)
    
    def find(self, query, projection=None):
        """Mock find - returns async iterator."""
        return MockAsyncCursor(self._existing_legacy_ids, query)
    
    async def insert_many(self, docs):
        """Mock insert_many."""
        self.documents.extend(docs)
        return MockInsertResult([d.get("id") for d in docs])
    
    def get_inserted_documents(self):
        """Get all inserted documents."""
        return self.documents


class MockInsertResult:
    """Mock insert result."""
    def __init__(self, ids):
        self.inserted_ids = ids


class MockAsyncCursor:
    """Mock async cursor for find()."""
    
    def __init__(self, legacy_ids, query):
        self._legacy_ids = legacy_ids
        self._index = 0
        self._ids_list = list(legacy_ids)
    
    def __aiter__(self):
        return self
    
    async def __anext__(self):
        if self._index >= len(self._ids_list):
            raise StopAsyncIteration
        legacy_id = self._ids_list[self._index]
        self._index += 1
        return {"legacy_id": legacy_id}


@pytest.mark.asyncio
class TestMigrationJobDryRun:
    """Tests for MigrationJob.run() in dry-run mode."""
    
    async def test_dry_run_processes_all_documents(self):
        """Test that dry-run processes all documents without writing."""
        source = InMemorySource("test")
        
        # Add test documents
        for i in range(5):
            source.add_document(
                LegacyDocument(
                    metadata=LegacyDocumentMetadata(
                        legacy_system="SQUARE9",
                        legacy_id=f"S9-{i:03d}",
                        legacy_workflow_name="AP_Invoice",
                        vendor_name=f"Vendor {i}",
                        is_posted=True
                    )
                )
            )
        
        job = MigrationJob(source, db_collection=None)
        result = await job.run(mode=MigrationMode.DRY_RUN)
        
        assert result.mode == "dry_run"
        assert result.stats.total_processed == 5
        assert result.stats.total_success == 5
        assert result.stats.total_errors == 0
        assert len(result.sample_documents) == 5
    
    async def test_dry_run_with_source_filter(self):
        """Test dry-run with source_filter."""
        source = InMemorySource("test")
        
        source.add_documents([
            LegacyDocument(metadata=LegacyDocumentMetadata("SQUARE9", "S9-001")),
            LegacyDocument(metadata=LegacyDocumentMetadata("ZETADOCS", "ZD-001")),
            LegacyDocument(metadata=LegacyDocumentMetadata("SQUARE9", "S9-002")),
        ])
        
        job = MigrationJob(source)
        result = await job.run(
            mode=MigrationMode.DRY_RUN,
            source_filter="SQUARE9"
        )
        
        assert result.stats.total_processed == 2
        assert result.stats.by_source_system.get("SQUARE9", 0) == 2
    
    async def test_dry_run_with_limit(self):
        """Test dry-run with limit."""
        source = InMemorySource("test")
        
        for i in range(10):
            source.add_document(
                LegacyDocument(
                    metadata=LegacyDocumentMetadata("SQUARE9", f"S9-{i:03d}")
                )
            )
        
        job = MigrationJob(source)
        result = await job.run(mode=MigrationMode.DRY_RUN, limit=3)
        
        assert result.stats.total_processed == 3
    
    async def test_dry_run_sample_documents_limited(self):
        """Test that sample_documents is limited to 20."""
        source = InMemorySource("test")
        
        for i in range(30):
            source.add_document(
                LegacyDocument(
                    metadata=LegacyDocumentMetadata("SQUARE9", f"S9-{i:03d}")
                )
            )
        
        job = MigrationJob(source)
        result = await job.run(mode=MigrationMode.DRY_RUN)
        
        assert result.stats.total_processed == 30
        assert len(result.sample_documents) == 20  # Limited to 20
    
    async def test_dry_run_classifies_correctly(self):
        """Test that dry-run classifies documents correctly."""
        source = InMemorySource("test")
        
        source.add_documents([
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-AP-001",
                    legacy_workflow_name="AP_Invoice"
                )
            ),
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="ZETADOCS",
                    legacy_id="ZD-SI-001",
                    legacy_zetadocs_set_code="ZD00007"  # Sales Invoice
                )
            ),
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-PO-001",
                    legacy_workflow_name="Purchase Order"
                )
            ),
        ])
        
        job = MigrationJob(source)
        result = await job.run(mode=MigrationMode.DRY_RUN)
        
        assert result.stats.by_doc_type.get("AP_INVOICE") == 1
        assert result.stats.by_doc_type.get("SALES_INVOICE") == 1
        assert result.stats.by_doc_type.get("PURCHASE_ORDER") == 1


@pytest.mark.asyncio
class TestMigrationJobRealRun:
    """Tests for MigrationJob.run() in real mode."""
    
    async def test_real_run_requires_db_collection(self):
        """Test that real mode requires db_collection."""
        source = InMemorySource("test")
        source.add_document(
            LegacyDocument(metadata=LegacyDocumentMetadata("SQUARE9", "S9-001"))
        )
        
        job = MigrationJob(source, db_collection=None)
        
        with pytest.raises(ValueError, match="db_collection is required"):
            await job.run(mode=MigrationMode.REAL)
    
    async def test_real_run_inserts_documents(self):
        """Test that real mode inserts documents to database."""
        source = InMemorySource("test")
        mock_collection = MockAsyncCollection()
        
        source.add_documents([
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-001",
                    legacy_workflow_name="AP_Invoice",
                    vendor_name="Acme Corp",
                    is_exported=True
                )
            ),
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="ZETADOCS",
                    legacy_id="ZD-001",
                    legacy_zetadocs_set_code="ZD00015",
                    vendor_name="Parts Co",
                    is_posted=True
                )
            ),
        ])
        
        job = MigrationJob(source, db_collection=mock_collection, batch_size=10)
        result = await job.run(mode=MigrationMode.REAL)
        
        assert result.mode == "real"
        assert result.stats.total_success == 2
        assert len(mock_collection.get_inserted_documents()) == 2
    
    async def test_real_run_skips_duplicates(self):
        """Test that real mode skips documents with existing legacy_id."""
        source = InMemorySource("test")
        mock_collection = MockAsyncCollection()
        
        # Simulate existing document
        mock_collection.add_existing_legacy_ids({"S9-001"})
        
        source.add_documents([
            LegacyDocument(
                metadata=LegacyDocumentMetadata("SQUARE9", "S9-001")  # Duplicate
            ),
            LegacyDocument(
                metadata=LegacyDocumentMetadata("SQUARE9", "S9-002")  # New
            ),
        ])
        
        job = MigrationJob(source, db_collection=mock_collection)
        result = await job.run(mode=MigrationMode.REAL)
        
        assert result.stats.total_skipped == 1
        assert result.stats.total_success == 1
        assert len(mock_collection.get_inserted_documents()) == 1
    
    async def test_real_run_sets_correct_fields(self):
        """Test that inserted documents have correct fields."""
        source = InMemorySource("test")
        mock_collection = MockAsyncCollection()
        
        source.add_document(
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-AP-001",
                    legacy_workflow_name="AP_Invoice",
                    vendor_name="Test Vendor",
                    vendor_no="V10001",
                    invoice_number="INV-001",
                    amount=1500.00,
                    is_posted=True,
                    is_paid=True
                ),
                binary_reference="/path/to/file.pdf"
            )
        )
        
        job = MigrationJob(source, db_collection=mock_collection)
        await job.run(mode=MigrationMode.REAL)
        
        docs = mock_collection.get_inserted_documents()
        assert len(docs) == 1
        
        doc = docs[0]
        assert doc["doc_type"] == "AP_INVOICE"
        assert doc["source_system"] == "SQUARE9"
        assert doc["capture_channel"] == "MIGRATION_JOB"
        assert doc["legacy_id"] == "S9-AP-001"
        assert doc["legacy_workflow_name"] == "AP_Invoice"
        assert doc["is_migrated"] == True
        assert doc["workflow_status"] == "exported"
        assert doc["vendor_name"] == "Test Vendor"
        assert doc["invoice_number"] == "INV-001"
        assert doc["amount"] == 1500.00
        assert doc["legacy_file_reference"] == "/path/to/file.pdf"
        assert len(doc["workflow_history"]) == 1
    
    async def test_real_run_batches_inserts(self):
        """Test that documents are inserted in batches."""
        source = InMemorySource("test")
        mock_collection = MockAsyncCollection()
        
        # Add 15 documents
        for i in range(15):
            source.add_document(
                LegacyDocument(
                    metadata=LegacyDocumentMetadata("SQUARE9", f"S9-{i:03d}")
                )
            )
        
        # Use batch size of 5
        job = MigrationJob(source, db_collection=mock_collection, batch_size=5)
        result = await job.run(mode=MigrationMode.REAL)
        
        assert result.stats.total_success == 15
        assert len(mock_collection.get_inserted_documents()) == 15


@pytest.mark.asyncio
class TestMigrationJobWorkflowStates:
    """Tests for workflow state initialization during migration."""
    
    async def test_ap_invoice_final_states(self):
        """Test AP Invoice final workflow states."""
        source = InMemorySource("test")
        mock_collection = MockAsyncCollection()
        
        source.add_documents([
            # Fully processed -> exported
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-001",
                    legacy_workflow_name="AP_Invoice",
                    is_posted=True,
                    is_paid=True
                )
            ),
            # Approved -> approved
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-002",
                    legacy_workflow_name="AP_Invoice",
                    is_approved=True
                )
            ),
            # Canceled -> rejected
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-003",
                    legacy_workflow_name="AP_Invoice",
                    is_canceled=True
                )
            ),
            # Pending -> extracted
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-004",
                    legacy_workflow_name="AP_Invoice"
                )
            ),
        ])
        
        job = MigrationJob(source, db_collection=mock_collection)
        result = await job.run(mode=MigrationMode.REAL)
        
        docs = mock_collection.get_inserted_documents()
        statuses = {d["legacy_id"]: d["workflow_status"] for d in docs}
        
        assert statuses["S9-001"] == "exported"
        assert statuses["S9-002"] == "approved"
        assert statuses["S9-003"] == "rejected"
        assert statuses["S9-004"] == "extracted"
    
    async def test_statement_final_states(self):
        """Test Statement final workflow states."""
        source = InMemorySource("test")
        mock_collection = MockAsyncCollection()
        
        source.add_documents([
            # Closed -> archived
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-ST-001",
                    legacy_workflow_name="Statement",
                    is_closed=True
                )
            ),
            # Reviewed -> reviewed
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-ST-002",
                    legacy_workflow_name="Statement",
                    is_reviewed=True
                )
            ),
            # Pending -> ready_for_review
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-ST-003",
                    legacy_workflow_name="Statement"
                )
            ),
        ])
        
        job = MigrationJob(source, db_collection=mock_collection)
        await job.run(mode=MigrationMode.REAL)
        
        docs = mock_collection.get_inserted_documents()
        statuses = {d["legacy_id"]: d["workflow_status"] for d in docs}
        
        assert statuses["S9-ST-001"] == "archived"
        assert statuses["S9-ST-002"] == "reviewed"
        assert statuses["S9-ST-003"] == "ready_for_review"
    
    async def test_quality_doc_final_states(self):
        """Test Quality Doc final workflow states."""
        source = InMemorySource("test")
        mock_collection = MockAsyncCollection()
        
        source.add_documents([
            # Closed and reviewed -> exported
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-QC-001",
                    legacy_workflow_name="Quality",
                    is_closed=True,
                    is_reviewed=True
                )
            ),
            # Tagged -> tagged
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-QC-002",
                    legacy_workflow_name="Quality",
                    quality_tags=["inspection", "passed"]
                )
            ),
        ])
        
        job = MigrationJob(source, db_collection=mock_collection)
        await job.run(mode=MigrationMode.REAL)
        
        docs = mock_collection.get_inserted_documents()
        statuses = {d["legacy_id"]: d["workflow_status"] for d in docs}
        
        assert statuses["S9-QC-001"] == "exported"
        assert statuses["S9-QC-002"] == "tagged"


@pytest.mark.asyncio
class TestMigrationJobClassification:
    """Tests for document classification during migration."""
    
    async def test_zetadocs_set_code_classification(self):
        """Test classification by Zetadocs set code."""
        source = InMemorySource("test")
        mock_collection = MockAsyncCollection()
        
        source.add_documents([
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="ZETADOCS",
                    legacy_id="ZD-001",
                    legacy_zetadocs_set_code="ZD00015"  # AP_INVOICE
                )
            ),
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="ZETADOCS",
                    legacy_id="ZD-002",
                    legacy_zetadocs_set_code="ZD00007"  # SALES_INVOICE
                )
            ),
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="ZETADOCS",
                    legacy_id="ZD-003",
                    legacy_zetadocs_set_code="ZD00002"  # PURCHASE_ORDER
                )
            ),
        ])
        
        job = MigrationJob(source, db_collection=mock_collection)
        result = await job.run(mode=MigrationMode.REAL)
        
        docs = mock_collection.get_inserted_documents()
        types = {d["legacy_id"]: d["doc_type"] for d in docs}
        
        assert types["ZD-001"] == "AP_INVOICE"
        assert types["ZD-002"] == "SALES_INVOICE"
        assert types["ZD-003"] == "PURCHASE_ORDER"
    
    async def test_square9_workflow_classification(self):
        """Test classification by Square9 workflow name."""
        source = InMemorySource("test")
        mock_collection = MockAsyncCollection()
        
        source.add_documents([
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-001",
                    legacy_workflow_name="AP_Invoice"
                )
            ),
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-002",
                    legacy_workflow_name="Sales Invoice"
                )
            ),
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-003",
                    legacy_workflow_name="Quality"
                )
            ),
        ])
        
        job = MigrationJob(source, db_collection=mock_collection)
        await job.run(mode=MigrationMode.REAL)
        
        docs = mock_collection.get_inserted_documents()
        types = {d["legacy_id"]: d["doc_type"] for d in docs}
        
        assert types["S9-001"] == "AP_INVOICE"
        assert types["S9-002"] == "SALES_INVOICE"
        assert types["S9-003"] == "QUALITY_DOC"
    
    async def test_field_inference_classification(self):
        """Test classification by field inference when no workflow/set code."""
        source = InMemorySource("test")
        mock_collection = MockAsyncCollection()
        
        source.add_documents([
            # Vendor + invoice -> AP_INVOICE
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-001",
                    vendor_no="V10001",
                    invoice_number="INV-001"
                )
            ),
            # Customer + invoice -> SALES_INVOICE
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-002",
                    customer_no="C10001",
                    invoice_number="SI-001"
                )
            ),
            # Quality tags -> QUALITY_DOC
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-003",
                    quality_tags=["inspection"]
                )
            ),
            # No hints -> OTHER
            LegacyDocument(
                metadata=LegacyDocumentMetadata(
                    legacy_system="SQUARE9",
                    legacy_id="S9-004"
                )
            ),
        ])
        
        job = MigrationJob(source, db_collection=mock_collection)
        await job.run(mode=MigrationMode.REAL)
        
        docs = mock_collection.get_inserted_documents()
        types = {d["legacy_id"]: d["doc_type"] for d in docs}
        
        assert types["S9-001"] == "AP_INVOICE"
        assert types["S9-002"] == "SALES_INVOICE"
        assert types["S9-003"] == "QUALITY_DOC"
        assert types["S9-004"] == "OTHER"


@pytest.mark.asyncio
class TestMigrationResult:
    """Tests for MigrationResult structure."""
    
    async def test_result_has_correct_structure(self):
        """Test that result has all required fields."""
        source = InMemorySource("test_source")
        source.add_document(
            LegacyDocument(metadata=LegacyDocumentMetadata("SQUARE9", "S9-001"))
        )
        
        job = MigrationJob(source)
        result = await job.run(mode=MigrationMode.DRY_RUN)
        
        result_dict = result.to_dict()
        
        assert "mode" in result_dict
        assert "source_name" in result_dict
        assert "started_at" in result_dict
        assert "completed_at" in result_dict
        assert "duration_seconds" in result_dict
        assert "stats" in result_dict
        assert "sample_documents" in result_dict
    
    async def test_result_stats_structure(self):
        """Test stats have correct structure."""
        source = InMemorySource("test")
        source.add_document(
            LegacyDocument(
                metadata=LegacyDocumentMetadata("SQUARE9", "S9-001", is_exported=True)
            )
        )
        
        job = MigrationJob(source)
        result = await job.run(mode=MigrationMode.DRY_RUN)
        
        stats = result.to_dict()["stats"]
        
        assert "total_processed" in stats
        assert "total_success" in stats
        assert "total_skipped" in stats
        assert "total_errors" in stats
        assert "by_doc_type" in stats
        assert "by_source_system" in stats
        assert "by_workflow_status" in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
