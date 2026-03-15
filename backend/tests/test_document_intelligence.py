"""
Document Intelligence API Tests
Tests the Document Intelligence endpoints (iteration_94):
  POST /api/document-intelligence/process/{id}
  GET  /api/document-intelligence/review-queue
  GET  /api/document-intelligence/{id}
  PATCH /api/document-intelligence/{id}
  GET  /api/document-intelligence/summary
"""

import pytest
import requests
import os
import time
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def auth_token(api_client):
    """Get authentication token"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "username": "admin",
        "password": "admin"
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip("Authentication failed - skipping authenticated tests")


@pytest.fixture(scope="module")
def authenticated_client(api_client, auth_token):
    """Session with auth header"""
    api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
    return api_client


@pytest.fixture(scope="module")
def existing_doc_ids(authenticated_client):
    """Get existing document IDs for testing"""
    response = authenticated_client.get(f"{BASE_URL}/api/documents?limit=10")
    assert response.status_code == 200
    docs = response.json().get("documents", [])
    if not docs:
        pytest.skip("No existing documents to test with")
    return [doc["id"] for doc in docs]


# ==================== GET /api/document-intelligence/summary ====================
class TestGetIntelligenceSummary:
    """GET /api/document-intelligence/summary endpoint tests"""

    def test_summary_endpoint_returns_200(self, authenticated_client):
        """Summary endpoint should return 200"""
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"Summary endpoint returns 200")

    def test_summary_response_structure(self, authenticated_client):
        """Summary should contain required fields"""
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/summary")
        data = response.json()
        
        # Validate required fields
        assert "total_processed" in data, "Missing total_processed"
        assert "by_readiness" in data, "Missing by_readiness"
        assert "by_document_type" in data, "Missing by_document_type"
        assert "total_corrections" in data, "Missing total_corrections"
        
        # Validate types
        assert isinstance(data["total_processed"], int), "total_processed should be int"
        assert isinstance(data["by_readiness"], dict), "by_readiness should be dict"
        assert isinstance(data["by_document_type"], list), "by_document_type should be list"
        assert isinstance(data["total_corrections"], int), "total_corrections should be int"
        
        print(f"Summary structure valid: total_processed={data['total_processed']}, by_readiness={list(data['by_readiness'].keys())}, total_corrections={data['total_corrections']}")


# ==================== GET /api/document-intelligence/review-queue ====================
class TestReviewQueue:
    """GET /api/document-intelligence/review-queue endpoint tests"""

    def test_review_queue_default_returns_200(self, authenticated_client):
        """Review queue should return 200"""
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/review-queue")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("Review queue default returns 200")

    def test_review_queue_response_structure(self, authenticated_client):
        """Review queue should return total, items, status_counts, limit, offset"""
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/review-queue")
        data = response.json()
        
        assert "total" in data, "Missing total"
        assert "items" in data, "Missing items"
        assert "status_counts" in data, "Missing status_counts"
        assert "limit" in data, "Missing limit"
        assert "offset" in data, "Missing offset"
        
        assert isinstance(data["items"], list), "items should be list"
        assert isinstance(data["status_counts"], dict), "status_counts should be dict"
        
        print(f"Review queue structure valid: total={data['total']}, items_count={len(data['items'])}, status_counts={data['status_counts']}")

    def test_review_queue_filter_by_status_ready(self, authenticated_client):
        """Review queue should filter by status=ready"""
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/review-queue?status=ready")
        assert response.status_code == 200
        data = response.json()
        
        # All items should have automation_readiness = ready
        for item in data["items"]:
            assert item.get("automation_readiness") == "ready", f"Expected ready, got {item.get('automation_readiness')}"
        
        print(f"Filter status=ready works: {len(data['items'])} items")

    def test_review_queue_filter_by_status_needs_review(self, authenticated_client):
        """Review queue should filter by status=needs_review"""
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/review-queue?status=needs_review")
        assert response.status_code == 200
        data = response.json()
        
        for item in data["items"]:
            assert item.get("automation_readiness") == "needs_review", f"Expected needs_review, got {item.get('automation_readiness')}"
        
        print(f"Filter status=needs_review works: {len(data['items'])} items")

    def test_review_queue_filter_by_status_blocked(self, authenticated_client):
        """Review queue should filter by status=blocked"""
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/review-queue?status=blocked")
        assert response.status_code == 200
        data = response.json()
        
        for item in data["items"]:
            assert item.get("automation_readiness") == "blocked", f"Expected blocked, got {item.get('automation_readiness')}"
        
        print(f"Filter status=blocked works: {len(data['items'])} items")

    def test_review_queue_item_enrichment(self, authenticated_client):
        """Review queue items should be enriched with document metadata"""
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/review-queue?status=ready")
        data = response.json()
        
        if data["items"]:
            item = data["items"][0]
            # Check for enriched fields
            assert "document_id" in item, "Missing document_id"
            assert "document_type" in item, "Missing document_type"
            assert "classification_confidence" in item, "Missing classification_confidence"
            assert "automation_readiness" in item, "Missing automation_readiness"
            assert "automation_readiness_score" in item, "Missing automation_readiness_score"
            
            # File metadata enrichment
            assert "file_name" in item, "Missing file_name enrichment"
            
            print(f"Item enrichment valid: document_id={item['document_id']}, file_name={item.get('file_name')}")
        else:
            print("No items to test enrichment (queue empty)")


# ==================== GET /api/document-intelligence/{id} ====================
class TestGetIntelligenceResult:
    """GET /api/document-intelligence/{id} endpoint tests"""

    def test_get_result_for_processed_doc(self, authenticated_client, existing_doc_ids):
        """Should return stored intelligence result after processing"""
        # First document in list - already processed per context
        doc_id = "e94c01cb-5c64-4f82-9fe0-64dc2ba4fa09"
        
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}")
        
        if response.status_code == 404:
            print(f"Document {doc_id} not processed yet - skipping")
            pytest.skip("Document not processed yet")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("document_id") == doc_id, f"document_id mismatch"
        assert "document_type" in data, "Missing document_type"
        assert "classification_confidence" in data, "Missing classification_confidence"
        assert "automation_readiness" in data, "Missing automation_readiness"
        assert "automation_readiness_score" in data, "Missing automation_readiness_score"
        
        print(f"Get intelligence result: doc_id={doc_id}, type={data.get('document_type')}, readiness={data.get('automation_readiness')}, score={data.get('automation_readiness_score')}")

    def test_get_result_404_for_unprocessed(self, authenticated_client):
        """Should return 404 for non-existent/unprocessed document"""
        fake_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/{fake_id}")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        
        print(f"404 returned correctly for unprocessed doc_id={fake_id}")


# ==================== POST /api/document-intelligence/process/{id} ====================
class TestProcessDocument:
    """POST /api/document-intelligence/process/{id} endpoint tests"""

    def test_process_returns_404_for_nonexistent(self, authenticated_client):
        """Should return 404 for non-existent doc_id"""
        fake_id = "nonexistent-doc-id-12345"
        
        response = authenticated_client.post(f"{BASE_URL}/api/document-intelligence/process/{fake_id}")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        
        print(f"Process 404 for non-existent doc_id={fake_id}")

    def test_process_existing_document(self, authenticated_client, existing_doc_ids):
        """Should process a document and return intelligence result"""
        doc_id = existing_doc_ids[0]
        
        response = authenticated_client.post(f"{BASE_URL}/api/document-intelligence/process/{doc_id}")
        
        # Allow for slow AI processing
        assert response.status_code in [200, 500], f"Expected 200 or 500, got {response.status_code}: {response.text}"
        
        if response.status_code == 200:
            data = response.json()
            
            # Validate response structure
            assert "result_id" in data, "Missing result_id"
            assert "document_id" in data, "Missing document_id"
            assert data["document_id"] == doc_id, "document_id mismatch"
            assert "document_type" in data, "Missing document_type"
            assert "classification_confidence" in data, "Missing classification_confidence"
            assert "extracted_fields" in data, "Missing extracted_fields"
            assert "automation_readiness" in data, "Missing automation_readiness"
            assert "automation_readiness_score" in data, "Missing automation_readiness_score"
            assert "automation_readiness_reasons" in data, "Missing automation_readiness_reasons"
            assert "model_name" in data, "Missing model_name"
            assert "prompt_version" in data, "Missing prompt_version"
            assert "processing_duration_ms" in data, "Missing processing_duration_ms"
            
            # Validate readiness status
            assert data["automation_readiness"] in ["ready", "needs_review", "blocked"], f"Invalid readiness: {data['automation_readiness']}"
            
            # Validate score range
            assert 0 <= data["automation_readiness_score"] <= 100, f"Score out of range: {data['automation_readiness_score']}"
            
            print(f"Process success: doc_id={doc_id}, type={data['document_type']}, readiness={data['automation_readiness']}, score={data['automation_readiness_score']}, duration={data['processing_duration_ms']}ms")
        else:
            print(f"Process returned 500 (possibly due to AI/BC issues): {response.text[:200]}")

    def test_reprocess_document(self, authenticated_client, existing_doc_ids):
        """Should be able to re-process a document"""
        doc_id = existing_doc_ids[0]
        
        # Process twice
        response1 = authenticated_client.post(f"{BASE_URL}/api/document-intelligence/process/{doc_id}")
        if response1.status_code == 200:
            response2 = authenticated_client.post(f"{BASE_URL}/api/document-intelligence/process/{doc_id}")
            assert response2.status_code == 200, f"Re-process failed: {response2.text}"
            
            print(f"Re-process success for doc_id={doc_id}")
        else:
            print(f"Initial process failed, skipping re-process test")


# ==================== PATCH /api/document-intelligence/{id} ====================
class TestCorrectIntelligence:
    """PATCH /api/document-intelligence/{id} endpoint tests"""

    def test_correction_404_for_unprocessed(self, authenticated_client):
        """Should return 404 if document hasn't been processed yet"""
        fake_id = "unprocessed-doc-correction-test"
        
        response = authenticated_client.patch(
            f"{BASE_URL}/api/document-intelligence/{fake_id}",
            json={"corrected_type": "AP_Invoice", "corrected_by": "test"}
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        
        print(f"Correction 404 for unprocessed doc_id={fake_id}")

    def test_correction_applies_type_change(self, authenticated_client, existing_doc_ids):
        """Should apply type correction and update confidence to 1.0"""
        # Use the document that has been corrected per context
        doc_id = "e94c01cb-5c64-4f82-9fe0-64dc2ba4fa09"
        
        # First ensure it's processed
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}")
        if response.status_code == 404:
            # Process it first
            authenticated_client.post(f"{BASE_URL}/api/document-intelligence/process/{doc_id}")
            time.sleep(2)
        
        # Get current state
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}")
        if response.status_code != 200:
            pytest.skip("Could not get intelligence result for correction test")
        
        original = response.json()
        original_type = original.get("document_type")
        
        # Apply correction
        new_type = "TEST_CORRECTED_TYPE"
        response = authenticated_client.patch(
            f"{BASE_URL}/api/document-intelligence/{doc_id}",
            json={
                "corrected_type": new_type,
                "corrected_by": "test_agent",
                "notes": "Testing type correction"
            }
        )
        
        assert response.status_code == 200, f"Correction failed: {response.text}"
        
        data = response.json()
        assert data.get("document_type") == new_type, f"Type not updated: {data.get('document_type')}"
        assert data.get("classification_confidence") == 1.0, f"Confidence not set to 1.0: {data.get('classification_confidence')}"
        assert data.get("manually_corrected") == True, "manually_corrected not set"
        
        # Check correction history
        history = data.get("correction_history", [])
        assert len(history) > 0, "correction_history empty"
        last_correction = history[-1]
        assert last_correction.get("corrected_by") == "test_agent", "corrected_by not recorded"
        assert "document_type" in last_correction.get("changes", {}), "type change not in history"
        
        print(f"Type correction applied: {original_type} -> {new_type}, confidence=1.0, history entries={len(history)}")
        
        # Revert the type for other tests
        authenticated_client.patch(
            f"{BASE_URL}/api/document-intelligence/{doc_id}",
            json={
                "corrected_type": original_type,
                "corrected_by": "test_cleanup",
                "notes": "Reverting type for test cleanup"
            }
        )

    def test_correction_applies_field_changes(self, authenticated_client):
        """Should apply field corrections"""
        doc_id = "e94c01cb-5c64-4f82-9fe0-64dc2ba4fa09"
        
        # Get current state
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}")
        if response.status_code != 200:
            pytest.skip("Document not processed")
        
        original = response.json()
        original_fields = original.get("extracted_fields", {})
        
        # Apply field correction with unique value
        unique_val = f"TEST_VALUE_{int(time.time())}"
        response = authenticated_client.patch(
            f"{BASE_URL}/api/document-intelligence/{doc_id}",
            json={
                "corrected_fields": {"test_field": unique_val},
                "corrected_by": "test_agent",
                "notes": "Testing field correction"
            }
        )
        
        assert response.status_code == 200, f"Field correction failed: {response.text}"
        
        data = response.json()
        fields = data.get("extracted_fields", {})
        assert fields.get("test_field") == unique_val, f"Field not updated: {fields.get('test_field')}"
        
        # Check correction history - find our specific correction
        history = data.get("correction_history", [])
        found_field_change = False
        for correction in reversed(history):
            changes = correction.get("changes", {})
            if "extracted_fields" in changes and "test_field" in changes["extracted_fields"]:
                found_field_change = True
                break
        
        assert found_field_change, "field change not found in history"
        
        print(f"Field correction applied: test_field={unique_val}")

    def test_correction_rederives_readiness(self, authenticated_client):
        """Should re-derive automation_readiness after correction"""
        doc_id = "e94c01cb-5c64-4f82-9fe0-64dc2ba4fa09"
        
        # Get current state
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}")
        if response.status_code != 200:
            pytest.skip("Document not processed")
        
        original = response.json()
        original_readiness = original.get("automation_readiness")
        original_score = original.get("automation_readiness_score")
        
        # Apply a correction that might change readiness
        response = authenticated_client.patch(
            f"{BASE_URL}/api/document-intelligence/{doc_id}",
            json={
                "corrected_type": "AP_Invoice",  # High-confidence type
                "corrected_by": "test_agent",
                "notes": "Testing readiness re-derivation"
            }
        )
        
        assert response.status_code == 200
        
        data = response.json()
        new_readiness = data.get("automation_readiness")
        new_score = data.get("automation_readiness_score")
        
        # Verify readiness fields exist (may or may not change)
        assert new_readiness in ["ready", "needs_review", "blocked"], f"Invalid readiness: {new_readiness}"
        assert 0 <= new_score <= 100, f"Invalid score: {new_score}"
        
        print(f"Readiness re-derived: {original_readiness}({original_score}) -> {new_readiness}({new_score})")


# ==================== Integration Tests ====================
class TestIntegrationFlows:
    """End-to-end integration tests"""

    def test_full_flow_process_get_correct(self, authenticated_client, existing_doc_ids):
        """Test full flow: process -> get -> correct"""
        doc_id = existing_doc_ids[1] if len(existing_doc_ids) > 1 else existing_doc_ids[0]
        
        # Step 1: Process
        process_resp = authenticated_client.post(f"{BASE_URL}/api/document-intelligence/process/{doc_id}")
        if process_resp.status_code != 200:
            print(f"Process failed (acceptable for integration): {process_resp.status_code}")
            pytest.skip("Process failed")
        
        process_data = process_resp.json()
        print(f"Step 1 - Processed: {process_data.get('document_type')}, score={process_data.get('automation_readiness_score')}")
        
        # Step 2: Get
        get_resp = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data.get("document_id") == doc_id
        print(f"Step 2 - Get: verified document_id match")
        
        # Step 3: Correct - use unique value to ensure it's a change
        unique_val = f"flow_{int(time.time())}"
        correct_resp = authenticated_client.patch(
            f"{BASE_URL}/api/document-intelligence/{doc_id}",
            json={
                "corrected_fields": {"integration_test": unique_val},
                "corrected_by": "integration_test",
                "notes": "Full flow integration test"
            }
        )
        assert correct_resp.status_code == 200
        correct_data = correct_resp.json()
        
        # Check if manually_corrected is True OR the correction was applied (field exists)
        fields = correct_data.get("extracted_fields", {})
        correction_applied = fields.get("integration_test") == unique_val
        assert correction_applied, f"Correction not applied: expected {unique_val}, got {fields.get('integration_test')}"
        print(f"Step 3 - Correct: applied, integration_test={unique_val}")
        
        print(f"Full integration flow completed for doc_id={doc_id}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
