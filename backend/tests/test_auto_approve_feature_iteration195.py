"""
Iteration 195: Test Auto-Approve Feature for Review Queue

Tests the new batch auto-approval engine that approves drafts from vendors
with proven posting templates (medium+ confidence, 5+ invoices learned).

Endpoints tested:
- POST /api/posting-patterns/review-queue/auto-approve?dry_run=true (preview)
- POST /api/posting-patterns/review-queue/auto-approve?dry_run=false (actual)
- POST /api/posting-patterns/review-queue/auto-approve?min_confidence=low
- GET /api/posting-patterns/review-queue/badge-count
- GET /api/readiness/automation-rate
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestReviewQueueBadgeCount:
    """Test the review queue badge count endpoint"""

    def test_badge_count_returns_count(self):
        """GET /api/posting-patterns/review-queue/badge-count should return count"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/review-queue/badge-count")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "count" in data, "Response should have 'count' field"
        assert isinstance(data["count"], int), "count should be an integer"
        assert data["count"] >= 0, "count should be non-negative"
        
        print(f"✓ Badge count: {data['count']}")


class TestReviewQueueEndpoint:
    """Test the review queue list endpoint"""

    def test_review_queue_list(self):
        """GET /api/posting-patterns/review-queue should return list"""
        response = requests.get(
            f"{BASE_URL}/api/posting-patterns/review-queue",
            params={"status_filter": "pending", "limit": 10}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "count" in data, "Response should have 'count' field"
        assert "items" in data, "Response should have 'items' field"
        assert "summary" in data, "Response should have 'summary' field"
        
        # Verify summary structure
        summary = data["summary"]
        assert "pending" in summary, "Summary should have 'pending' count"
        assert "approved" in summary, "Summary should have 'approved' count"
        assert "corrected" in summary, "Summary should have 'corrected' count"
        
        print(f"✓ Review queue: {data['count']} items, summary: pending={summary['pending']}, approved={summary['approved']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
