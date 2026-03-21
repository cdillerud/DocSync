"""
Bake-Off Feature Tests
Tests for GPI Hub vs Square 9 comparison workspace.
Covers: Run CRUD, Document CRUD, Scoring, Metrics, Export, Auto-populate
"""

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
API = f"{BASE_URL}/api/bakeoff"


class TestBakeOffRuns:
    """Test run management: create, list, get, update, complete, archive, delete"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test data"""
        self.test_run_ids = []
        yield
        # Cleanup: delete test runs
        for run_id in self.test_run_ids:
            try:
                requests.delete(f"{API}/runs/{run_id}")
            except:
                pass
    
    def test_create_run(self):
        """POST /api/bakeoff/runs - Create a new bake-off run"""
        payload = {
            "name": f"TEST_Run_{uuid.uuid4().hex[:8]}",
            "description": "Test run for pytest",
            "test_date": "2026-03-21",
            "source_batch_identifier": "BATCH-001",
            "expected_document_count": 25
        }
        response = requests.post(f"{API}/runs", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "run_id" in data
        assert data["name"] == payload["name"]
        assert data["description"] == payload["description"]
        assert data["test_date"] == payload["test_date"]
        assert data["status"] == "draft"
        assert data["expected_document_count"] == 25
        assert data["actual_document_count"] == 0
        
        self.test_run_ids.append(data["run_id"])
        print(f"✓ Created run: {data['run_id']}")
    
    def test_list_runs(self):
        """GET /api/bakeoff/runs - List all runs"""
        response = requests.get(f"{API}/runs")
        assert response.status_code == 200
        
        data = response.json()
        assert "runs" in data
        assert "total" in data
        assert isinstance(data["runs"], list)
        print(f"✓ Listed {data['total']} runs")
    
    def test_list_runs_by_status(self):
        """GET /api/bakeoff/runs?status=draft - Filter runs by status"""
        response = requests.get(f"{API}/runs", params={"status": "draft"})
        assert response.status_code == 200
        
        data = response.json()
        for run in data["runs"]:
            assert run["status"] == "draft"
        print(f"✓ Filtered runs by status=draft: {len(data['runs'])} found")
    
    def test_get_run(self):
        """GET /api/bakeoff/runs/{run_id} - Get single run"""
        # First create a run
        payload = {"name": f"TEST_GetRun_{uuid.uuid4().hex[:8]}"}
        create_resp = requests.post(f"{API}/runs", json=payload)
        run_id = create_resp.json()["run_id"]
        self.test_run_ids.append(run_id)
        
        # Get the run
        response = requests.get(f"{API}/runs/{run_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["run_id"] == run_id
        assert data["name"] == payload["name"]
        print(f"✓ Got run: {run_id}")
    
    def test_get_run_not_found(self):
        """GET /api/bakeoff/runs/{run_id} - 404 for non-existent run"""
        response = requests.get(f"{API}/runs/nonexistent-id")
        assert response.status_code == 404
        print("✓ 404 for non-existent run")
    
    def test_update_run(self):
        """PUT /api/bakeoff/runs/{run_id} - Update run details"""
        # Create run
        payload = {"name": f"TEST_UpdateRun_{uuid.uuid4().hex[:8]}"}
        create_resp = requests.post(f"{API}/runs", json=payload)
        run_id = create_resp.json()["run_id"]
        self.test_run_ids.append(run_id)
        
        # Update run
        update_payload = {
            "name": "Updated Name",
            "description": "Updated description",
            "expected_document_count": 100
        }
        response = requests.put(f"{API}/runs/{run_id}", json=update_payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["description"] == "Updated description"
        assert data["expected_document_count"] == 100
        print(f"✓ Updated run: {run_id}")
    
    def test_complete_run(self):
        """POST /api/bakeoff/runs/{run_id}/complete - Mark run as complete"""
        # Create run
        payload = {"name": f"TEST_CompleteRun_{uuid.uuid4().hex[:8]}"}
        create_resp = requests.post(f"{API}/runs", json=payload)
        run_id = create_resp.json()["run_id"]
        self.test_run_ids.append(run_id)
        
        # Complete run
        response = requests.post(f"{API}/runs/{run_id}/complete")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "complete"
        
        # Verify via GET
        get_resp = requests.get(f"{API}/runs/{run_id}")
        assert get_resp.json()["status"] == "complete"
        assert get_resp.json()["completed_at"] is not None
        print(f"✓ Completed run: {run_id}")
    
    def test_archive_run(self):
        """POST /api/bakeoff/runs/{run_id}/archive - Archive run"""
        # Create run
        payload = {"name": f"TEST_ArchiveRun_{uuid.uuid4().hex[:8]}"}
        create_resp = requests.post(f"{API}/runs", json=payload)
        run_id = create_resp.json()["run_id"]
        self.test_run_ids.append(run_id)
        
        # Archive run
        response = requests.post(f"{API}/runs/{run_id}/archive")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "archived"
        
        # Verify via GET
        get_resp = requests.get(f"{API}/runs/{run_id}")
        assert get_resp.json()["status"] == "archived"
        assert get_resp.json()["archived_at"] is not None
        print(f"✓ Archived run: {run_id}")
    
    def test_delete_draft_run(self):
        """DELETE /api/bakeoff/runs/{run_id} - Delete draft run"""
        # Create run
        payload = {"name": f"TEST_DeleteRun_{uuid.uuid4().hex[:8]}"}
        create_resp = requests.post(f"{API}/runs", json=payload)
        run_id = create_resp.json()["run_id"]
        
        # Delete run (draft status)
        response = requests.delete(f"{API}/runs/{run_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["deleted"] == True
        
        # Verify deleted
        get_resp = requests.get(f"{API}/runs/{run_id}")
        assert get_resp.status_code == 404
        print(f"✓ Deleted draft run: {run_id}")
    
    def test_delete_non_draft_run_blocked(self):
        """DELETE /api/bakeoff/runs/{run_id} - Cannot delete non-draft run"""
        # Create and complete run
        payload = {"name": f"TEST_DeleteBlockedRun_{uuid.uuid4().hex[:8]}"}
        create_resp = requests.post(f"{API}/runs", json=payload)
        run_id = create_resp.json()["run_id"]
        self.test_run_ids.append(run_id)
        
        requests.post(f"{API}/runs/{run_id}/complete")
        
        # Try to delete (should fail)
        response = requests.delete(f"{API}/runs/{run_id}")
        assert response.status_code == 400
        assert "draft" in response.json().get("detail", "").lower()
        print(f"✓ Delete blocked for non-draft run: {run_id}")


class TestBakeOffDocuments:
    """Test document management: add, list, get, update, delete"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Create a test run for document tests"""
        payload = {"name": f"TEST_DocRun_{uuid.uuid4().hex[:8]}"}
        resp = requests.post(f"{API}/runs", json=payload)
        self.run_id = resp.json()["run_id"]
        self.doc_uids = []
        yield
        # Cleanup
        requests.delete(f"{API}/runs/{self.run_id}")
    
    def test_add_document(self):
        """POST /api/bakeoff/runs/{run_id}/documents - Add document"""
        payload = {
            "document_id": f"DOC-{uuid.uuid4().hex[:8]}",
            "file_name": "invoice_001.pdf",
            "vendor_truth": "Acme Corp",
            "doc_type_truth": "Invoice",
            "amount_truth": 1500.50,
            "po_truth": "PO-12345",
            "folder_truth": "AP/Invoices"
        }
        response = requests.post(f"{API}/runs/{self.run_id}/documents", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert "doc_uid" in data
        assert data["document_id"] == payload["document_id"]
        assert data["file_name"] == payload["file_name"]
        assert data["vendor_truth"] == payload["vendor_truth"]
        assert data["amount_truth"] == payload["amount_truth"]
        assert data["gpi_ingested"] is None
        assert data["s9_ingested"] is None
        
        self.doc_uids.append(data["doc_uid"])
        print(f"✓ Added document: {data['doc_uid']}")
    
    def test_list_documents(self):
        """GET /api/bakeoff/runs/{run_id}/documents - List documents"""
        # Add a document first
        payload = {"document_id": f"DOC-{uuid.uuid4().hex[:8]}", "file_name": "test.pdf"}
        add_resp = requests.post(f"{API}/runs/{self.run_id}/documents", json=payload)
        self.doc_uids.append(add_resp.json()["doc_uid"])
        
        # List documents
        response = requests.get(f"{API}/runs/{self.run_id}/documents")
        assert response.status_code == 200
        
        data = response.json()
        assert "documents" in data
        assert "total" in data
        assert data["total"] >= 1
        print(f"✓ Listed {data['total']} documents")
    
    def test_list_documents_with_search(self):
        """GET /api/bakeoff/runs/{run_id}/documents?search=... - Search documents"""
        # Add document with specific name
        unique_name = f"UNIQUE_{uuid.uuid4().hex[:8]}.pdf"
        payload = {"document_id": "DOC-SEARCH", "file_name": unique_name}
        add_resp = requests.post(f"{API}/runs/{self.run_id}/documents", json=payload)
        self.doc_uids.append(add_resp.json()["doc_uid"])
        
        # Search
        response = requests.get(f"{API}/runs/{self.run_id}/documents", params={"search": unique_name[:10]})
        assert response.status_code == 200
        
        data = response.json()
        assert data["total"] >= 1
        assert any(unique_name in d.get("file_name", "") for d in data["documents"])
        print(f"✓ Search found document with name containing '{unique_name[:10]}'")
    
    def test_get_document(self):
        """GET /api/bakeoff/runs/{run_id}/documents/{doc_uid} - Get single document"""
        # Add document
        payload = {"document_id": f"DOC-{uuid.uuid4().hex[:8]}", "file_name": "get_test.pdf"}
        add_resp = requests.post(f"{API}/runs/{self.run_id}/documents", json=payload)
        doc_uid = add_resp.json()["doc_uid"]
        self.doc_uids.append(doc_uid)
        
        # Get document
        response = requests.get(f"{API}/runs/{self.run_id}/documents/{doc_uid}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["doc_uid"] == doc_uid
        assert data["file_name"] == "get_test.pdf"
        print(f"✓ Got document: {doc_uid}")
    
    def test_update_document_scoring(self):
        """PUT /api/bakeoff/runs/{run_id}/documents/{doc_uid} - Update scoring"""
        # Add document
        payload = {
            "document_id": f"DOC-{uuid.uuid4().hex[:8]}",
            "file_name": "score_test.pdf",
            "vendor_truth": "Test Vendor",
            "doc_type_truth": "Invoice"
        }
        add_resp = requests.post(f"{API}/runs/{self.run_id}/documents", json=payload)
        doc_uid = add_resp.json()["doc_uid"]
        self.doc_uids.append(doc_uid)
        
        # Update GPI scoring
        update_payload = {
            "gpi_ingested": True,
            "gpi_vendor": "Test Vendor",
            "gpi_doc_type": "Invoice",
            "gpi_amount": 1000.00,
            "gpi_needs_review": "None",
            "gpi_final_status": "Usable"
        }
        response = requests.put(f"{API}/runs/{self.run_id}/documents/{doc_uid}", json=update_payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data["gpi_ingested"] == True
        assert data["gpi_vendor"] == "Test Vendor"
        assert data["gpi_final_status"] == "Usable"
        assert data["gpi_manually_edited"] == True  # Should be marked as manually edited
        print(f"✓ Updated document scoring: {doc_uid}")
    
    def test_auto_scoring_correctness(self):
        """PUT /api/bakeoff/runs/{run_id}/documents/{doc_uid} - Auto-scoring calculates correctness"""
        # Add document with truth values
        payload = {
            "document_id": f"DOC-{uuid.uuid4().hex[:8]}",
            "vendor_truth": "Acme Corp",
            "doc_type_truth": "Invoice",
            "amount_truth": 500.00,
            "po_truth": "PO-999"
        }
        add_resp = requests.post(f"{API}/runs/{self.run_id}/documents", json=payload)
        doc_uid = add_resp.json()["doc_uid"]
        self.doc_uids.append(doc_uid)
        
        # Update with matching GPI values
        update_payload = {
            "gpi_vendor": "Acme Corp",  # Matches truth
            "gpi_doc_type": "Invoice",  # Matches truth
            "gpi_amount": 500.00,  # Matches truth
            "gpi_po": "PO-999"  # Matches truth
        }
        response = requests.put(f"{API}/runs/{self.run_id}/documents/{doc_uid}", json=update_payload)
        assert response.status_code == 200
        
        data = response.json()
        # Auto-scoring should mark these as correct
        assert data["gpi_vendor_correct"] == True
        assert data["gpi_doc_type_correct"] == True
        assert data["gpi_amount_correct"] == True
        assert data["gpi_po_correct"] == True
        print(f"✓ Auto-scoring calculated correctness: {doc_uid}")
    
    def test_auto_scoring_po_normalization(self):
        """Auto-scoring normalizes PO numbers (removes prefixes)"""
        # Add document with PO truth
        payload = {
            "document_id": f"DOC-{uuid.uuid4().hex[:8]}",
            "po_truth": "PO-12345"
        }
        add_resp = requests.post(f"{API}/runs/{self.run_id}/documents", json=payload)
        doc_uid = add_resp.json()["doc_uid"]
        self.doc_uids.append(doc_uid)
        
        # Update with PO without prefix (should still match)
        update_payload = {"gpi_po": "12345"}
        response = requests.put(f"{API}/runs/{self.run_id}/documents/{doc_uid}", json=update_payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data["gpi_po_correct"] == True  # Should match after normalization
        print(f"✓ PO normalization working: 'PO-12345' matches '12345'")
    
    def test_update_why_wrong_tags(self):
        """PUT /api/bakeoff/runs/{run_id}/documents/{doc_uid} - Update why wrong tags"""
        # Add document
        payload = {"document_id": f"DOC-{uuid.uuid4().hex[:8]}"}
        add_resp = requests.post(f"{API}/runs/{self.run_id}/documents", json=payload)
        doc_uid = add_resp.json()["doc_uid"]
        self.doc_uids.append(doc_uid)
        
        # Update with why wrong tags
        update_payload = {
            "gpi_why_wrong_tags": ["Vendor alias miss", "OCR issue"],
            "s9_why_wrong_tags": ["Classification error"]
        }
        response = requests.put(f"{API}/runs/{self.run_id}/documents/{doc_uid}", json=update_payload)
        assert response.status_code == 200
        
        data = response.json()
        assert "Vendor alias miss" in data["gpi_why_wrong_tags"]
        assert "OCR issue" in data["gpi_why_wrong_tags"]
        assert "Classification error" in data["s9_why_wrong_tags"]
        print(f"✓ Updated why wrong tags: {doc_uid}")
    
    def test_delete_document(self):
        """DELETE /api/bakeoff/runs/{run_id}/documents/{doc_uid} - Delete document"""
        # Add document
        payload = {"document_id": f"DOC-{uuid.uuid4().hex[:8]}"}
        add_resp = requests.post(f"{API}/runs/{self.run_id}/documents", json=payload)
        doc_uid = add_resp.json()["doc_uid"]
        
        # Delete document
        response = requests.delete(f"{API}/runs/{self.run_id}/documents/{doc_uid}")
        assert response.status_code == 200
        assert response.json()["deleted"] == True
        
        # Verify deleted
        get_resp = requests.get(f"{API}/runs/{self.run_id}/documents/{doc_uid}")
        assert get_resp.status_code == 404
        print(f"✓ Deleted document: {doc_uid}")


class TestBakeOffMetrics:
    """Test metrics and summary endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Create a test run with documents for metrics tests"""
        payload = {"name": f"TEST_MetricsRun_{uuid.uuid4().hex[:8]}"}
        resp = requests.post(f"{API}/runs", json=payload)
        self.run_id = resp.json()["run_id"]
        
        # Add some documents with scoring
        for i in range(3):
            doc_payload = {
                "document_id": f"DOC-METRIC-{i}",
                "vendor_truth": f"Vendor{i}",
                "doc_type_truth": "Invoice"
            }
            add_resp = requests.post(f"{API}/runs/{self.run_id}/documents", json=doc_payload)
            doc_uid = add_resp.json()["doc_uid"]
            
            # Score the document
            score_payload = {
                "gpi_ingested": True,
                "gpi_vendor": f"Vendor{i}",
                "gpi_doc_type": "Invoice",
                "gpi_needs_review": "None",
                "gpi_final_status": "Usable" if i < 2 else "Partial",
                "s9_ingested": True,
                "s9_vendor": f"Vendor{i}" if i == 0 else "Wrong",
                "s9_doc_type": "Invoice",
                "s9_needs_review": "Minor",
                "s9_final_status": "Partial"
            }
            requests.put(f"{API}/runs/{self.run_id}/documents/{doc_uid}", json=score_payload)
        
        yield
        # Cleanup
        requests.delete(f"{API}/runs/{self.run_id}")
    
    def test_get_metrics(self):
        """GET /api/bakeoff/runs/{run_id}/metrics - Get run metrics"""
        response = requests.get(f"{API}/runs/{self.run_id}/metrics")
        assert response.status_code == 200
        
        data = response.json()
        assert "metrics" in data
        assert "breakdowns" in data
        
        metrics = data["metrics"]
        assert metrics["total"] == 3
        assert "gpi" in metrics
        assert "s9" in metrics
        
        gpi = metrics["gpi"]
        assert "ingest_rate" in gpi
        assert "classification_accuracy" in gpi
        assert "vendor_accuracy" in gpi
        assert "no_touch_rate" in gpi
        assert "usable_output_rate" in gpi
        
        print(f"✓ Got metrics: total={metrics['total']}, GPI ingest={gpi['ingest_rate']}%")
    
    def test_get_breakdowns(self):
        """GET /api/bakeoff/runs/{run_id}/metrics - Breakdowns included"""
        response = requests.get(f"{API}/runs/{self.run_id}/metrics")
        assert response.status_code == 200
        
        data = response.json()
        breakdowns = data["breakdowns"]
        
        assert "gpi_why_wrong" in breakdowns
        assert "s9_why_wrong" in breakdowns
        assert "by_doc_type" in breakdowns
        assert "by_vendor" in breakdowns
        assert "insights" in breakdowns
        
        print(f"✓ Got breakdowns: {len(breakdowns['by_doc_type'])} doc types, {len(breakdowns['by_vendor'])} vendors")


class TestBakeOffExport:
    """Test Excel export functionality"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Create a test run for export tests"""
        payload = {"name": f"TEST_ExportRun_{uuid.uuid4().hex[:8]}"}
        resp = requests.post(f"{API}/runs", json=payload)
        self.run_id = resp.json()["run_id"]
        
        # Add a document
        doc_payload = {"document_id": "DOC-EXPORT-1", "file_name": "export_test.pdf"}
        requests.post(f"{API}/runs/{self.run_id}/documents", json=doc_payload)
        
        yield
        # Cleanup
        requests.delete(f"{API}/runs/{self.run_id}")
    
    def test_export_excel(self):
        """GET /api/bakeoff/runs/{run_id}/export - Export as Excel"""
        response = requests.get(f"{API}/runs/{self.run_id}/export")
        assert response.status_code == 200
        
        # Check content type
        content_type = response.headers.get("content-type", "")
        assert "spreadsheet" in content_type or "excel" in content_type.lower() or "octet-stream" in content_type
        
        # Check content disposition
        content_disp = response.headers.get("content-disposition", "")
        assert "attachment" in content_disp
        assert ".xlsx" in content_disp
        
        # Check file size (should have some content)
        assert len(response.content) > 1000  # Excel files are at least a few KB
        
        print(f"✓ Exported Excel: {len(response.content)} bytes")
    
    def test_export_not_found(self):
        """GET /api/bakeoff/runs/{run_id}/export - 404 for non-existent run"""
        response = requests.get(f"{API}/runs/nonexistent-id/export")
        assert response.status_code == 404
        print("✓ 404 for export of non-existent run")


class TestBakeOffAutoPopulate:
    """Test auto-populate GPI functionality"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Create a test run for auto-populate tests"""
        payload = {"name": f"TEST_AutoPopRun_{uuid.uuid4().hex[:8]}"}
        resp = requests.post(f"{API}/runs", json=payload)
        self.run_id = resp.json()["run_id"]
        yield
        # Cleanup
        requests.delete(f"{API}/runs/{self.run_id}")
    
    def test_auto_populate(self):
        """POST /api/bakeoff/runs/{run_id}/auto-populate - Auto-populate GPI data"""
        # Add a document
        doc_payload = {"document_id": "DOC-AUTOPOP-1", "file_name": "autopop_test.pdf"}
        requests.post(f"{API}/runs/{self.run_id}/documents", json=doc_payload)
        
        # Call auto-populate
        response = requests.post(f"{API}/runs/{self.run_id}/auto-populate")
        assert response.status_code == 200
        
        data = response.json()
        assert "linked" in data
        assert "total" in data
        assert data["total"] >= 1
        
        print(f"✓ Auto-populate: linked {data['linked']} of {data['total']} documents")


class TestBakeOffWhyWrongTags:
    """Test why-wrong tags endpoint"""
    
    def test_get_why_wrong_tags(self):
        """GET /api/bakeoff/why-wrong-tags - Get available tags"""
        response = requests.get(f"{API}/why-wrong-tags")
        assert response.status_code == 200
        
        data = response.json()
        assert "tags" in data
        assert isinstance(data["tags"], list)
        assert len(data["tags"]) > 0
        
        # Check expected tags
        expected_tags = ["Vendor alias miss", "OCR issue", "Classification error", "PO mismatch"]
        for tag in expected_tags:
            assert tag in data["tags"], f"Expected tag '{tag}' not found"
        
        print(f"✓ Got {len(data['tags'])} why-wrong tags")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
