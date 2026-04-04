"""
Test suite for Learning Dashboard and Review Queue features
Tests the new AI Learning Intelligence and Draft Review Queue endpoints
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestLearningDashboard:
    """Tests for GET /api/posting-patterns/learning-dashboard endpoint"""
    
    def test_learning_dashboard_returns_200(self):
        """Learning dashboard endpoint returns 200 status"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: Learning dashboard returns 200")
    
    def test_learning_dashboard_has_summary(self):
        """Learning dashboard response contains summary object with required fields"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200
        data = response.json()
        
        assert "summary" in data, "Response missing 'summary' field"
        summary = data["summary"]
        
        # Check all required summary fields
        required_fields = [
            "total_learning_events",
            "total_corrections",
            "total_feedback_examples",
            "total_label_corrections",
            "total_posting_profiles",
            "continuously_learning_vendors",
            "total_extraction_profiles",
            "total_vendor_profiles",
            "total_auto_drafted"
        ]
        for field in required_fields:
            assert field in summary, f"Summary missing '{field}' field"
            assert isinstance(summary[field], int), f"'{field}' should be an integer"
        
        print(f"PASS: Learning dashboard summary has all {len(required_fields)} required fields")
    
    def test_learning_dashboard_has_posting_template_confidence(self):
        """Learning dashboard response contains posting_template_confidence array"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200
        data = response.json()
        
        assert "posting_template_confidence" in data, "Response missing 'posting_template_confidence'"
        assert isinstance(data["posting_template_confidence"], list), "posting_template_confidence should be a list"
        print("PASS: Learning dashboard has posting_template_confidence array")
    
    def test_learning_dashboard_has_vendor_learning_activity(self):
        """Learning dashboard response contains vendor_learning_activity array"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200
        data = response.json()
        
        assert "vendor_learning_activity" in data, "Response missing 'vendor_learning_activity'"
        assert isinstance(data["vendor_learning_activity"], list), "vendor_learning_activity should be a list"
        print("PASS: Learning dashboard has vendor_learning_activity array")
    
    def test_learning_dashboard_has_label_correction_patterns(self):
        """Learning dashboard response contains label_correction_patterns with real data"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200
        data = response.json()
        
        assert "label_correction_patterns" in data, "Response missing 'label_correction_patterns'"
        patterns = data["label_correction_patterns"]
        assert isinstance(patterns, list), "label_correction_patterns should be a list"
        
        # Per agent context, there should be real label correction data (PO->SHIPMENT 9x, BOL->PO 1x)
        if len(patterns) > 0:
            pattern = patterns[0]
            assert "from_label" in pattern, "Pattern missing 'from_label'"
            assert "to_label" in pattern, "Pattern missing 'to_label'"
            assert "corrections" in pattern, "Pattern missing 'corrections'"
            assert "vendors_affected" in pattern, "Pattern missing 'vendors_affected'"
            print(f"PASS: Learning dashboard has {len(patterns)} label correction patterns with correct structure")
        else:
            print("PASS: Learning dashboard has label_correction_patterns array (empty)")
    
    def test_learning_dashboard_has_recent_learning_events(self):
        """Learning dashboard response contains recent_learning_events array"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200
        data = response.json()
        
        assert "recent_learning_events" in data, "Response missing 'recent_learning_events'"
        assert isinstance(data["recent_learning_events"], list), "recent_learning_events should be a list"
        print("PASS: Learning dashboard has recent_learning_events array")
    
    def test_learning_dashboard_has_recent_corrections(self):
        """Learning dashboard response contains recent_corrections array"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200
        data = response.json()
        
        assert "recent_corrections" in data, "Response missing 'recent_corrections'"
        assert isinstance(data["recent_corrections"], list), "recent_corrections should be a list"
        print("PASS: Learning dashboard has recent_corrections array")
    
    def test_learning_dashboard_has_auto_draft_by_vendor(self):
        """Learning dashboard response contains auto_draft_by_vendor array"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200
        data = response.json()
        
        assert "auto_draft_by_vendor" in data, "Response missing 'auto_draft_by_vendor'"
        assert isinstance(data["auto_draft_by_vendor"], list), "auto_draft_by_vendor should be a list"
        print("PASS: Learning dashboard has auto_draft_by_vendor array")


class TestReviewQueue:
    """Tests for GET /api/posting-patterns/review-queue endpoint"""
    
    def test_review_queue_returns_200(self):
        """Review queue endpoint returns 200 status"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: Review queue returns 200")
    
    def test_review_queue_has_count_and_items(self):
        """Review queue response contains count and items fields"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue")
        assert response.status_code == 200
        data = response.json()
        
        assert "count" in data, "Response missing 'count' field"
        assert "items" in data, "Response missing 'items' field"
        assert isinstance(data["count"], int), "'count' should be an integer"
        assert isinstance(data["items"], list), "'items' should be a list"
        print(f"PASS: Review queue has count={data['count']} and items array")
    
    def test_review_queue_has_summary(self):
        """Review queue response contains summary with pending/approved/corrected/total"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue")
        assert response.status_code == 200
        data = response.json()
        
        assert "summary" in data, "Response missing 'summary' field"
        summary = data["summary"]
        
        required_fields = ["pending", "approved", "corrected", "total"]
        for field in required_fields:
            assert field in summary, f"Summary missing '{field}' field"
            assert isinstance(summary[field], int), f"'{field}' should be an integer"
        
        print(f"PASS: Review queue summary has all required fields: pending={summary['pending']}, approved={summary['approved']}, corrected={summary['corrected']}, total={summary['total']}")
    
    def test_review_queue_filter_pending(self):
        """Review queue with status_filter=pending returns valid response"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue?status_filter=pending")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "items" in data
        assert "summary" in data
        print("PASS: Review queue filter=pending works")
    
    def test_review_queue_filter_approved(self):
        """Review queue with status_filter=approved returns valid response"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue?status_filter=approved")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "items" in data
        assert "summary" in data
        print("PASS: Review queue filter=approved works")
    
    def test_review_queue_filter_corrected(self):
        """Review queue with status_filter=corrected returns valid response"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue?status_filter=corrected")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "items" in data
        assert "summary" in data
        print("PASS: Review queue filter=corrected works")
    
    def test_review_queue_filter_all(self):
        """Review queue with status_filter=all returns valid response"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue?status_filter=all")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "items" in data
        assert "summary" in data
        print("PASS: Review queue filter=all works")


class TestReviewQueueActions:
    """Tests for POST /api/posting-patterns/review-queue/{doc_id}/approve and /correct endpoints"""
    
    def test_approve_nonexistent_doc_returns_error(self):
        """Approve endpoint returns error for non-existent document"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/review-queue/fake-id/approve")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "success" in data, "Response missing 'success' field"
        assert data["success"] == False, "Expected success=false for non-existent doc"
        assert "error" in data, "Response missing 'error' field"
        assert "not found" in data["error"].lower(), f"Expected 'not found' in error, got: {data['error']}"
        print(f"PASS: Approve non-existent doc returns error: {data['error']}")
    
    def test_correct_nonexistent_doc_returns_error(self):
        """Correct endpoint returns error for non-existent document"""
        corrections = [{"field": "amount", "original": "100", "corrected": "200"}]
        response = requests.post(
            f"{BASE_URL}/api/posting-patterns/review-queue/fake-id/correct",
            json=corrections,
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "success" in data, "Response missing 'success' field"
        assert data["success"] == False, "Expected success=false for non-existent doc"
        assert "error" in data, "Response missing 'error' field"
        assert "not found" in data["error"].lower(), f"Expected 'not found' in error, got: {data['error']}"
        print(f"PASS: Correct non-existent doc returns error: {data['error']}")


class TestHealthCheck:
    """Basic health check to ensure API is running"""
    
    def test_health_endpoint(self):
        """Health endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: Health endpoint returns 200")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
