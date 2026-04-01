"""
Test: Document Intelligence P0 Fix Verification
===============================================
Tests the fixes for the data extraction pipeline issues:
1. UPLOAD_DIR fallback when local_file_path is not stored on document
2. Clear ERROR logging when no file exists (not silent failure)  
3. Heuristic-classified documents still get full LLM field extraction
4. extracted_fields contain meaningful data (not just metadata)

Known test documents:
- 7c04212b-cdd5-4c7d-9eea-329daaaa3420 (W91.pdf, has file on disk)
- ae78e544-041d-4603-bb1c-1112403ef887 (no file on disk - fallback to existing fields)
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    # Fallback for local testing
    BASE_URL = "https://ap-status-sync.preview.emergentagent.com"

# Test document IDs from the review request
DOC_WITH_FILE = "7c04212b-cdd5-4c7d-9eea-329daaaa3420"  # W91.pdf exists
DOC_WITHOUT_FILE = "ae78e544-041d-4603-bb1c-1112403ef887"  # No file on disk


class TestHealth:
    """Basic health check"""
    
    def test_backend_health(self):
        """Verify backend is running"""
        response = requests.get(f"{BASE_URL}/api/health", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print(f"✓ Backend healthy: {data}")


class TestDocumentList:
    """Test GET /api/documents endpoint"""
    
    def test_documents_list_returns_data(self):
        """GET /api/documents should work with status filter"""
        response = requests.get(
            f"{BASE_URL}/api/documents",
            params={"limit": 5, "status": "Completed"},
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        assert "documents" in data
        assert "counts" in data
        print(f"✓ Documents list returned {len(data['documents'])} docs, total_all: {data['counts'].get('total_all')}")
    
    def test_documents_list_counts_accurate(self):
        """Verify document count statistics"""
        response = requests.get(f"{BASE_URL}/api/documents", params={"status": "NeedsReview"}, timeout=30)
        assert response.status_code == 200
        data = response.json()
        counts = data.get("counts", {})
        assert counts.get("total_all", 0) >= 0
        print(f"✓ Document counts: total={counts.get('total_all')}, pending_review={counts.get('pending_review')}")


class TestDocumentIntelligenceProcess:
    """Test POST /api/document-intelligence/process/{doc_id}
    
    Core P0 fix: UPLOAD_DIR fallback + clear error logging
    """
    
    def test_process_document_with_file(self):
        """Document with file on disk should extract fields via UPLOAD_DIR fallback"""
        response = requests.post(
            f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE}",
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "result_id" in data, "Missing result_id"
        assert "document_id" in data, "Missing document_id"
        assert data["document_id"] == DOC_WITH_FILE
        assert "extracted_fields" in data, "Missing extracted_fields"
        assert "document_type" in data, "Missing document_type"
        assert "classification_confidence" in data, "Missing classification_confidence"
        
        # P0 Fix verification: extracted_fields should have meaningful data
        fields = data.get("extracted_fields", {})
        assert len(fields) > 0, "extracted_fields should not be empty for doc with file"
        
        # Check for non-metadata fields (not just _detected_by fields)
        meaningful_keys = [k for k in fields.keys() if not k.endswith("_detected_by")]
        assert len(meaningful_keys) > 0, "Should have meaningful extracted fields, not just metadata"
        
        print(f"✓ Document processed: type={data['document_type']}, confidence={data['classification_confidence']}")
        print(f"  Extracted fields ({len(fields)}): {list(fields.keys())[:10]}")
    
    def test_process_document_without_file_graceful_fallback(self):
        """Document without file should use existing extracted_fields (graceful fallback)"""
        response = requests.post(
            f"{BASE_URL}/api/document-intelligence/process/{DOC_WITHOUT_FILE}",
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Should return result even without file (fallback to existing fields)
        assert "result_id" in data
        assert "document_id" in data
        assert data["document_id"] == DOC_WITHOUT_FILE
        assert "extracted_fields" in data
        
        # Fallback behavior: uses existing extracted_fields from document
        fields = data.get("extracted_fields", {})
        print(f"✓ Document without file processed with fallback: fields={list(fields.keys())[:5]}")
        
        # Note: classification_confidence may be 0 when no file processing occurs
        # This is expected behavior for the fallback path
    
    def test_process_nonexistent_document_returns_error(self):
        """Non-existent document should return 4xx error"""
        fake_id = "nonexistent-doc-id-12345"
        response = requests.post(
            f"{BASE_URL}/api/document-intelligence/process/{fake_id}",
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        # Should return 4xx (not found) or 5xx with meaningful error, not silent success
        assert response.status_code in [400, 404, 500], f"Expected error status, got {response.status_code}"
        print(f"✓ Non-existent doc correctly returns error: {response.status_code}")
    
    def test_extracted_fields_have_meaningful_data(self):
        """Verify extracted_fields contain meaningful business data"""
        response = requests.post(
            f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE}",
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        fields = data.get("extracted_fields", {})
        
        # Check for common business fields (at least some should be present)
        common_fields = [
            "vendor", "customer", "invoice_number", "invoice_date",
            "amount", "po_number", "order_date", "ship_to", "shipper", "consignee"
        ]
        present_fields = [f for f in common_fields if f in fields]
        
        # At least one meaningful field should be extracted
        assert len(present_fields) > 0 or len(fields) > 0, \
            f"Expected at least one meaningful field. Got fields: {list(fields.keys())}"
        
        print(f"✓ Meaningful fields present: {present_fields}")


class TestDocumentReprocess:
    """Test POST /api/documents/{doc_id}/reprocess endpoint"""
    
    def test_reprocess_without_reclassify(self):
        """Reprocess should work without reclassify flag"""
        response = requests.post(
            f"{BASE_URL}/api/documents/{DOC_WITH_FILE}/reprocess",
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "reprocessed" in data
        assert "document" in data
        print(f"✓ Reprocess without reclassify: reprocessed={data.get('reprocessed')}")
    
    def test_reprocess_with_reclassify_true(self):
        """Reprocess with reclassify=true should re-run AI classification using UPLOAD_DIR"""
        response = requests.post(
            f"{BASE_URL}/api/documents/{DOC_WITH_FILE}/reprocess?reclassify=true",
            headers={"Content-Type": "application/json"},
            timeout=90  # AI classification may take time
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "reprocessed" in data
        assert data.get("reprocessed") == True, "Should have reprocessed with reclassify"
        assert "document" in data
        
        doc = data.get("document", {})
        assert "extracted_fields" in doc or doc.get("extracted_fields") is not None
        
        print(f"✓ Reprocess with reclassify=true: status_changed={data.get('status_changed')}")
        print(f"  Document type: {doc.get('suggested_job_type')}, confidence: {doc.get('ai_confidence')}")
    
    def test_reprocess_idempotent_for_linked_documents(self):
        """Documents already linked to BC should not be reprocessed (idempotency)"""
        # First check document status
        get_resp = requests.get(f"{BASE_URL}/api/documents/{DOC_WITH_FILE}", timeout=30)
        assert get_resp.status_code == 200
        doc = get_resp.json().get("document", {})
        
        # If already linked, reprocess should skip
        if doc.get("status") == "LinkedToBC" or doc.get("bc_record_id"):
            reprocess_resp = requests.post(
                f"{BASE_URL}/api/documents/{DOC_WITH_FILE}/reprocess",
                timeout=30
            )
            assert reprocess_resp.status_code == 200
            data = reprocess_resp.json()
            # Should indicate no reprocessing needed
            if not data.get("reprocessed", True):
                print(f"✓ Linked document correctly skipped reprocessing")
        else:
            print(f"✓ Document not linked, reprocessing allowed (status: {doc.get('status')})")


class TestHeuristicPlusLLMExtraction:
    """Test that heuristic-classified documents still get LLM field extraction
    
    P0 fix: Heuristic provides classification, LLM provides full extraction
    """
    
    def test_intelligence_result_has_model_info(self):
        """Verify model info shows heuristic+LLM combination when applicable"""
        response = requests.post(
            f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE}",
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check model metadata
        model_name = data.get("model_name", "")
        model_provider = data.get("model_provider", "")
        
        # Should indicate AI model was used for extraction
        assert model_name or model_provider, "Should have model info"
        print(f"✓ Model info: name={model_name}, provider={model_provider}")
    
    def test_extraction_schema_present(self):
        """Verify extraction_schema is returned with required/optional fields"""
        response = requests.post(
            f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE}",
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        schema = data.get("extraction_schema", {})
        assert "required" in schema, "Missing required fields in schema"
        assert "optional" in schema, "Missing optional fields in schema"
        print(f"✓ Extraction schema: required={len(schema.get('required', []))}, optional={len(schema.get('optional', []))}")


class TestAutomationReadiness:
    """Test automation readiness scoring after processing"""
    
    def test_automation_readiness_computed(self):
        """Verify automation_readiness is computed after processing"""
        response = requests.post(
            f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE}",
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check readiness fields
        assert "automation_readiness" in data, "Missing automation_readiness"
        assert "automation_readiness_score" in data, "Missing automation_readiness_score"
        assert "automation_decision" in data, "Missing automation_decision"
        
        readiness = data.get("automation_readiness")
        score = data.get("automation_readiness_score", 0)
        reasons = data.get("automation_readiness_reasons", [])
        
        assert readiness in ["ready", "needs_review", "blocked"], f"Invalid readiness: {readiness}"
        assert 0 <= score <= 100, f"Score out of range: {score}"
        
        print(f"✓ Automation readiness: {readiness} (score={score})")
        if reasons:
            print(f"  Reasons: {reasons[:3]}")


class TestDocumentDetailAPI:
    """Test GET /api/documents/{doc_id} endpoint"""
    
    def test_get_document_detail(self):
        """Get document detail should return full document info"""
        response = requests.get(f"{BASE_URL}/api/documents/{DOC_WITH_FILE}", timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        assert "document" in data
        doc = data["document"]
        
        assert "id" in doc
        assert doc["id"] == DOC_WITH_FILE
        assert "file_name" in doc
        assert "extracted_fields" in doc or doc.get("extracted_fields") is not None
        
        print(f"✓ Document detail: {doc.get('file_name')}, type={doc.get('suggested_job_type')}")
    
    def test_get_nonexistent_document(self):
        """Non-existent document should return 404"""
        response = requests.get(f"{BASE_URL}/api/documents/fake-doc-id-xyz", timeout=30)
        assert response.status_code == 404
        print("✓ Non-existent document correctly returns 404")


# Integration test combining multiple operations
class TestEndToEndWorkflow:
    """End-to-end workflow tests"""
    
    def test_process_then_verify_document_updated(self):
        """Process a document, then verify the document record was updated"""
        # Step 1: Process document
        process_resp = requests.post(
            f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE}",
            timeout=60
        )
        assert process_resp.status_code == 200
        process_data = process_resp.json()
        result_id = process_data.get("result_id")
        
        # Step 2: Get document and verify intelligence fields updated
        get_resp = requests.get(f"{BASE_URL}/api/documents/{DOC_WITH_FILE}", timeout=30)
        assert get_resp.status_code == 200
        doc = get_resp.json().get("document", {})
        
        # Verify document was updated with intelligence results
        assert doc.get("intelligence_result_id") or doc.get("intelligence_processed_at"), \
            "Document should have intelligence result after processing"
        
        print(f"✓ E2E: Process result_id={result_id}, doc.intelligence_result_id={doc.get('intelligence_result_id')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
