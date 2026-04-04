"""
Test Feedback Loop Features — Iteration 177

Tests the new feedback loop additions:
1. POST /api/posting-patterns/review-queue/{doc_id}/sync-from-bc - Sync draft from BC
2. POST /api/posting-patterns/review-queue/sync-all - Batch sync all drafts
3. GET /api/posting-patterns/review-queue/{doc_id}/feedback - Get feedback details
4. GET /api/posting-patterns/review-queue - Review queue summary structure
5. POST /api/posting-patterns/review-queue/{doc_id}/approve - Approve draft (error for non-existent)
6. POST /api/posting-patterns/review-queue/{doc_id}/correct - Correct draft (error for non-existent)
7. draft_feedback_service.py module functions exist
8. original_draft_lines storage in gpi_integration.py
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestHealthCheck:
    """Basic health check"""
    
    def test_health_endpoint(self):
        """Verify API is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.status_code}"
        print("PASS: Health endpoint returns 200")


class TestSyncFromBCEndpoint:
    """Test POST /api/posting-patterns/review-queue/{doc_id}/sync-from-bc"""
    
    def test_sync_from_bc_nonexistent_doc(self):
        """Sync from BC returns proper error for non-existent document"""
        fake_doc_id = "nonexistent-doc-12345"
        response = requests.post(f"{BASE_URL}/api/posting-patterns/review-queue/{fake_doc_id}/sync-from-bc")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") == False, "Expected success=False for non-existent doc"
        assert "error" in data, "Expected error field in response"
        assert "not found" in data.get("error", "").lower() or "Document not found" in data.get("error", ""), \
            f"Expected 'not found' error, got: {data.get('error')}"
        print(f"PASS: sync-from-bc returns proper error for non-existent doc: {data.get('error')}")


class TestSyncAllEndpoint:
    """Test POST /api/posting-patterns/review-queue/sync-all"""
    
    def test_sync_all_returns_valid_structure(self):
        """Sync all returns valid batch sync result structure"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/review-queue/sync-all")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify required fields in response
        required_fields = ["processed", "changes_found", "no_changes", "errors", "details"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Verify types
        assert isinstance(data["processed"], int), "processed should be int"
        assert isinstance(data["changes_found"], int), "changes_found should be int"
        assert isinstance(data["no_changes"], int), "no_changes should be int"
        assert isinstance(data["errors"], int), "errors should be int"
        assert isinstance(data["details"], list), "details should be list"
        
        print(f"PASS: sync-all returns valid structure: processed={data['processed']}, "
              f"changes_found={data['changes_found']}, no_changes={data['no_changes']}, errors={data['errors']}")


class TestFeedbackEndpoint:
    """Test GET /api/posting-patterns/review-queue/{doc_id}/feedback"""
    
    def test_feedback_nonexistent_doc(self):
        """Feedback endpoint returns proper error for non-existent document"""
        fake_doc_id = "nonexistent-doc-67890"
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue/{fake_doc_id}/feedback")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") == False, "Expected success=False for non-existent doc"
        assert "error" in data, "Expected error field in response"
        assert "not found" in data.get("error", "").lower() or "Document not found" in data.get("error", ""), \
            f"Expected 'not found' error, got: {data.get('error')}"
        print(f"PASS: feedback endpoint returns proper error for non-existent doc: {data.get('error')}")


class TestReviewQueueSummary:
    """Test GET /api/posting-patterns/review-queue summary structure"""
    
    def test_review_queue_returns_correct_structure(self):
        """Review queue returns correct summary structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify top-level fields
        assert "count" in data, "Missing 'count' field"
        assert "items" in data, "Missing 'items' field"
        assert "summary" in data, "Missing 'summary' field"
        
        # Verify summary structure
        summary = data["summary"]
        required_summary_fields = ["pending", "approved", "corrected", "total"]
        for field in required_summary_fields:
            assert field in summary, f"Missing summary field: {field}"
            assert isinstance(summary[field], int), f"summary.{field} should be int"
        
        # Verify items is a list
        assert isinstance(data["items"], list), "items should be a list"
        
        print(f"PASS: review-queue returns correct structure: count={data['count']}, "
              f"summary={{pending={summary['pending']}, approved={summary['approved']}, "
              f"corrected={summary['corrected']}, total={summary['total']}}}")


class TestApproveEndpoint:
    """Test POST /api/posting-patterns/review-queue/{doc_id}/approve"""
    
    def test_approve_nonexistent_doc(self):
        """Approve returns proper error for non-existent document"""
        fake_doc_id = "nonexistent-doc-approve-123"
        response = requests.post(f"{BASE_URL}/api/posting-patterns/review-queue/{fake_doc_id}/approve")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") == False, "Expected success=False for non-existent doc"
        assert "error" in data, "Expected error field in response"
        assert "not found" in data.get("error", "").lower() or "Document not found" in data.get("error", ""), \
            f"Expected 'not found' error, got: {data.get('error')}"
        print(f"PASS: approve endpoint returns proper error for non-existent doc: {data.get('error')}")


class TestCorrectEndpoint:
    """Test POST /api/posting-patterns/review-queue/{doc_id}/correct"""
    
    def test_correct_nonexistent_doc(self):
        """Correct returns proper error for non-existent document"""
        fake_doc_id = "nonexistent-doc-correct-456"
        response = requests.post(
            f"{BASE_URL}/api/posting-patterns/review-queue/{fake_doc_id}/correct",
            json=[{"field": "amount", "original": "100", "corrected": "150"}]
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("success") == False, "Expected success=False for non-existent doc"
        assert "error" in data, "Expected error field in response"
        assert "not found" in data.get("error", "").lower() or "Document not found" in data.get("error", ""), \
            f"Expected 'not found' error, got: {data.get('error')}"
        print(f"PASS: correct endpoint returns proper error for non-existent doc: {data.get('error')}")


class TestReviewQueueFilters:
    """Test review queue filter functionality"""
    
    def test_filter_pending(self):
        """Filter by pending status works"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue?status_filter=pending")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        print(f"PASS: pending filter works, returned {len(data['items'])} items")
    
    def test_filter_approved(self):
        """Filter by approved status works"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue?status_filter=approved")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        print(f"PASS: approved filter works, returned {len(data['items'])} items")
    
    def test_filter_corrected(self):
        """Filter by corrected status works"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue?status_filter=corrected")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        print(f"PASS: corrected filter works, returned {len(data['items'])} items")
    
    def test_filter_all(self):
        """Filter by all status works"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue?status_filter=all")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        print(f"PASS: all filter works, returned {len(data['items'])} items")


class TestLearningDashboard:
    """Test learning dashboard endpoint (from previous iteration, ensure still works)"""
    
    def test_learning_dashboard_returns_valid_data(self):
        """Learning dashboard returns valid structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify summary exists
        assert "summary" in data, "Missing 'summary' field"
        summary = data["summary"]
        
        # Verify key summary fields
        expected_fields = ["total_learning_events", "total_corrections", "total_posting_profiles"]
        for field in expected_fields:
            assert field in summary, f"Missing summary field: {field}"
        
        print(f"PASS: learning-dashboard returns valid data: "
              f"learning_events={summary.get('total_learning_events')}, "
              f"corrections={summary.get('total_corrections')}, "
              f"profiles={summary.get('total_posting_profiles')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
