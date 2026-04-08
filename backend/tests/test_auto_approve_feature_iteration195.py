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

class TestAutoApproveFeature:
    """Test the new auto-approve batch approval feature"""

    def test_auto_approve_preview_dry_run_true(self):
        """POST /api/posting-patterns/review-queue/auto-approve?dry_run=true should return valid preview"""
        response = requests.post(
            f"{BASE_URL}/api/posting-patterns/review-queue/auto-approve",
            params={"dry_run": True, "min_confidence": "medium", "min_vendor_invoices": 5}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify response structure - core fields always present
        assert "approved" in data, "Response should have 'approved' field"
        assert "skipped" in data, "Response should have 'skipped' field"
        assert "message" in data, "Response should have 'message' field"
        
        # Verify approved/skipped are integers
        assert isinstance(data["approved"], int), "approved should be an integer"
        assert isinstance(data["skipped"], int), "skipped should be an integer"
        
        # When there are pending drafts, additional fields are present
        # When no pending drafts, response is simpler: {"approved": 0, "skipped": 0, "message": "No pending drafts found"}
        if "No pending drafts" not in data.get("message", ""):
            # Full response with dry_run, skip_reasons, top_approved_vendors
            assert "dry_run" in data, "Response should have 'dry_run' field when drafts exist"
            assert data["dry_run"] == True, "dry_run should be True"
            assert "skip_reasons" in data, "Response should have 'skip_reasons' field"
            assert "top_approved_vendors" in data, "Response should have 'top_approved_vendors' field"
        
        print(f"✓ Auto-approve preview (dry_run=true): approved={data['approved']}, skipped={data['skipped']}")
        print(f"  Message: {data['message']}")

    def test_auto_approve_actual_run_dry_run_false(self):
        """POST /api/posting-patterns/review-queue/auto-approve?dry_run=false should work (empty DB returns 0 approved)"""
        response = requests.post(
            f"{BASE_URL}/api/posting-patterns/review-queue/auto-approve",
            params={"dry_run": False, "min_confidence": "medium", "min_vendor_invoices": 5}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify response structure - core fields always present
        assert "approved" in data, "Response should have 'approved' field"
        assert "skipped" in data, "Response should have 'skipped' field"
        
        # In empty/preview DB, approved should be 0 or some number
        assert isinstance(data["approved"], int), "approved should be an integer"
        
        # When there are pending drafts, dry_run field is present
        if "No pending drafts" not in data.get("message", ""):
            assert "dry_run" in data, "Response should have 'dry_run' field when drafts exist"
            assert data["dry_run"] == False, "dry_run should be False"
        
        print(f"✓ Auto-approve actual run (dry_run=false): approved={data['approved']}, skipped={data['skipped']}")

    def test_auto_approve_with_min_confidence_low(self):
        """POST /api/posting-patterns/review-queue/auto-approve with min_confidence=low should work"""
        response = requests.post(
            f"{BASE_URL}/api/posting-patterns/review-queue/auto-approve",
            params={"dry_run": True, "min_confidence": "low", "min_vendor_invoices": 5}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "approved" in data
        assert "skipped" in data
        # dry_run only present when there are pending drafts
        if "No pending drafts" not in data.get("message", ""):
            assert data["dry_run"] == True
        
        print(f"✓ Auto-approve with min_confidence=low: approved={data['approved']}, skipped={data['skipped']}")

    def test_auto_approve_with_min_confidence_high(self):
        """POST /api/posting-patterns/review-queue/auto-approve with min_confidence=high should work"""
        response = requests.post(
            f"{BASE_URL}/api/posting-patterns/review-queue/auto-approve",
            params={"dry_run": True, "min_confidence": "high", "min_vendor_invoices": 5}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "approved" in data
        assert "skipped" in data
        
        print(f"✓ Auto-approve with min_confidence=high: approved={data['approved']}, skipped={data['skipped']}")

    def test_auto_approve_with_custom_min_vendor_invoices(self):
        """POST /api/posting-patterns/review-queue/auto-approve with custom min_vendor_invoices"""
        response = requests.post(
            f"{BASE_URL}/api/posting-patterns/review-queue/auto-approve",
            params={"dry_run": True, "min_confidence": "medium", "min_vendor_invoices": 10}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "approved" in data
        assert "skipped" in data
        
        print(f"✓ Auto-approve with min_vendor_invoices=10: approved={data['approved']}, skipped={data['skipped']}")


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


class TestReadinessAutomationRate:
    """Test that existing readiness automation-rate endpoint still works"""

    def test_automation_rate_still_works(self):
        """GET /api/readiness/automation-rate should still work"""
        response = requests.get(f"{BASE_URL}/api/readiness/automation-rate")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify response has expected fields
        assert "automation_rate" in data or "rate" in data or "total" in data, \
            f"Response should have automation rate info: {data}"
        
        print(f"✓ Automation rate endpoint works: {data}")


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


class TestLearningDashboard:
    """Test the learning dashboard endpoint"""

    def test_learning_dashboard(self):
        """GET /api/posting-patterns/learning-dashboard should work"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "summary" in data, "Response should have 'summary' field"
        
        summary = data["summary"]
        assert "total_learning_events" in summary
        assert "total_corrections" in summary
        assert "total_auto_drafted" in summary
        
        print(f"✓ Learning dashboard: {summary['total_learning_events']} learning events, {summary['total_auto_drafted']} auto-drafted")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
