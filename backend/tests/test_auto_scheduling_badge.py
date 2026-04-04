"""
Test Auto-Scheduling + Badge Count Features (Iteration 178)

Tests:
1. GET /api/posting-patterns/review-queue/badge-count - returns {count: <number>}
2. POST /api/posting-patterns/review-queue/sync-all - returns valid batch result
3. GET /api/posting-patterns/review-queue - returns review queue with summary
4. Scheduler existence verification (code review)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestBadgeCountEndpoint:
    """Tests for the badge-count endpoint"""
    
    def test_badge_count_returns_count(self):
        """GET /api/posting-patterns/review-queue/badge-count returns {count: <number>}"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue/badge-count")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "count" in data, f"Response missing 'count' field: {data}"
        assert isinstance(data["count"], int), f"count should be int, got {type(data['count'])}"
        assert data["count"] >= 0, f"count should be >= 0, got {data['count']}"
        print(f"PASS: badge-count returns count={data['count']}")
    
    def test_badge_count_response_structure(self):
        """Badge count response should be minimal {count: N}"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue/badge-count")
        assert response.status_code == 200
        
        data = response.json()
        # Should be a simple response with just count
        assert "count" in data
        print(f"PASS: badge-count response structure valid: {data}")


class TestSyncAllEndpoint:
    """Tests for the sync-all batch endpoint"""
    
    def test_sync_all_returns_valid_structure(self):
        """POST /api/posting-patterns/review-queue/sync-all returns valid batch result"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/review-queue/sync-all")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Required fields in batch result
        required_fields = ["processed", "changes_found", "no_changes", "errors", "details"]
        for field in required_fields:
            assert field in data, f"Response missing '{field}' field: {data}"
        
        # Type checks
        assert isinstance(data["processed"], int), f"processed should be int"
        assert isinstance(data["changes_found"], int), f"changes_found should be int"
        assert isinstance(data["no_changes"], int), f"no_changes should be int"
        assert isinstance(data["errors"], int), f"errors should be int"
        assert isinstance(data["details"], list), f"details should be list"
        
        print(f"PASS: sync-all returns valid structure: processed={data['processed']}, changes={data['changes_found']}")
    
    def test_sync_all_with_limit(self):
        """POST /api/posting-patterns/review-queue/sync-all?limit=10 respects limit"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/review-queue/sync-all?limit=10")
        assert response.status_code == 200
        
        data = response.json()
        assert "processed" in data
        # processed should be <= limit (10)
        assert data["processed"] <= 10, f"processed ({data['processed']}) should be <= limit (10)"
        print(f"PASS: sync-all respects limit parameter")


class TestReviewQueueEndpoint:
    """Tests for the review-queue list endpoint"""
    
    def test_review_queue_returns_summary(self):
        """GET /api/posting-patterns/review-queue returns summary with counts"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "summary" in data, f"Response missing 'summary' field: {data}"
        
        summary = data["summary"]
        required_summary_fields = ["pending", "approved", "corrected", "total"]
        for field in required_summary_fields:
            assert field in summary, f"Summary missing '{field}' field: {summary}"
            assert isinstance(summary[field], int), f"summary.{field} should be int"
        
        print(f"PASS: review-queue summary: pending={summary['pending']}, approved={summary['approved']}, corrected={summary['corrected']}, total={summary['total']}")
    
    def test_review_queue_returns_items(self):
        """GET /api/posting-patterns/review-queue returns items list"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue")
        assert response.status_code == 200
        
        data = response.json()
        assert "items" in data, f"Response missing 'items' field"
        assert "count" in data, f"Response missing 'count' field"
        assert isinstance(data["items"], list), f"items should be list"
        assert isinstance(data["count"], int), f"count should be int"
        
        print(f"PASS: review-queue returns {data['count']} items")


class TestHealthEndpoint:
    """Basic health check"""
    
    def test_health_check(self):
        """GET /api/health returns 200"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.status_code}"
        print("PASS: Health check OK")


class TestLearningDashboard:
    """Tests for learning dashboard (related to auto-draft tracking)"""
    
    def test_learning_dashboard_includes_auto_draft_stats(self):
        """GET /api/posting-patterns/learning-dashboard includes auto-draft stats"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "summary" in data, f"Response missing 'summary' field"
        
        summary = data["summary"]
        # Should include total_auto_drafted count
        assert "total_auto_drafted" in summary, f"Summary missing 'total_auto_drafted': {summary}"
        assert isinstance(summary["total_auto_drafted"], int)
        
        print(f"PASS: learning-dashboard includes total_auto_drafted={summary['total_auto_drafted']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
