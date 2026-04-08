"""
Iteration 196: Test Status Sync Fix for Inbox/Readiness Disconnect

Tests the critical fix where readiness.status and document status were disconnected,
causing 515 'Needs Review' docs in inbox even though readiness said many were ready_auto_draft.

Key endpoints tested:
- POST /api/readiness/sync-status (NEW) - Bulk sync readiness to document status
- POST /api/readiness/reevaluate-all - Re-evaluate all documents
- POST /api/posting-patterns/review-queue/auto-approve?dry_run=true - Auto-approve drafts
- GET /api/readiness/automation-rate - Automation rate dashboard
- GET /api/readiness/metrics - Readiness metrics
"""

import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestStatusSyncEndpoint:
    """Test the new POST /api/readiness/sync-status endpoint"""

    def test_sync_status_returns_correct_shape(self):
        """POST /api/readiness/sync-status should return readiness_synced, approved_synced, total_fixed, message"""
        response = requests.post(f"{BASE_URL}/api/readiness/sync-status")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify response shape - all required fields must be present
        assert "readiness_synced" in data, f"Missing 'readiness_synced' in response: {data}"
        assert "approved_synced" in data, f"Missing 'approved_synced' in response: {data}"
        assert "total_fixed" in data, f"Missing 'total_fixed' in response: {data}"
        assert "message" in data, f"Missing 'message' in response: {data}"
        
        # Verify types
        assert isinstance(data["readiness_synced"], int), f"readiness_synced should be int, got {type(data['readiness_synced'])}"
        assert isinstance(data["approved_synced"], int), f"approved_synced should be int, got {type(data['approved_synced'])}"
        assert isinstance(data["total_fixed"], int), f"total_fixed should be int, got {type(data['total_fixed'])}"
        assert isinstance(data["message"], str), f"message should be str, got {type(data['message'])}"
        
        # Verify total_fixed = readiness_synced + approved_synced
        assert data["total_fixed"] == data["readiness_synced"] + data["approved_synced"], \
            f"total_fixed ({data['total_fixed']}) should equal readiness_synced ({data['readiness_synced']}) + approved_synced ({data['approved_synced']})"
        
        print(f"✓ sync-status returned: readiness_synced={data['readiness_synced']}, approved_synced={data['approved_synced']}, total_fixed={data['total_fixed']}")

    def test_sync_status_with_limit_param(self):
        """POST /api/readiness/sync-status accepts limit parameter"""
        response = requests.post(f"{BASE_URL}/api/readiness/sync-status?limit=100")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "readiness_synced" in data
        assert "total_fixed" in data
        print(f"✓ sync-status with limit=100 returned: total_fixed={data['total_fixed']}")


class TestReevaluateAllEndpoint:
    """Test POST /api/readiness/reevaluate-all still works"""

    def test_reevaluate_all_returns_200(self):
        """POST /api/readiness/reevaluate-all should return 200 with expected fields"""
        response = requests.post(f"{BASE_URL}/api/readiness/reevaluate-all?limit=10")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify expected fields
        assert "total_processed" in data, f"Missing 'total_processed' in response: {data}"
        assert "by_status" in data, f"Missing 'by_status' in response: {data}"
        
        print(f"✓ reevaluate-all returned: total_processed={data['total_processed']}, by_status={data.get('by_status', {})}")


class TestAutoApproveEndpoint:
    """Test POST /api/posting-patterns/review-queue/auto-approve still works"""

    def test_auto_approve_dry_run_returns_correct_shape(self):
        """POST /api/posting-patterns/review-queue/auto-approve?dry_run=true should return expected fields"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/review-queue/auto-approve?dry_run=true")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify expected fields
        assert "approved" in data, f"Missing 'approved' in response: {data}"
        assert "skipped" in data, f"Missing 'skipped' in response: {data}"
        assert "message" in data, f"Missing 'message' in response: {data}"
        
        # dry_run should be True in response (if pending drafts exist)
        if data.get("dry_run") is not None:
            assert data["dry_run"] == True, f"dry_run should be True, got {data['dry_run']}"
        
        print(f"✓ auto-approve dry_run returned: approved={data['approved']}, skipped={data['skipped']}, message={data['message']}")

    def test_auto_approve_with_min_confidence_param(self):
        """POST /api/posting-patterns/review-queue/auto-approve accepts min_confidence parameter"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/review-queue/auto-approve?dry_run=true&min_confidence=high")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "approved" in data
        assert "skipped" in data
        print(f"✓ auto-approve with min_confidence=high returned: approved={data['approved']}, skipped={data['skipped']}")


class TestAutomationRateEndpoint:
    """Test GET /api/readiness/automation-rate still works"""

    def test_automation_rate_returns_200(self):
        """GET /api/readiness/automation-rate should return 200 with expected fields"""
        response = requests.get(f"{BASE_URL}/api/readiness/automation-rate")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify expected fields
        assert "automation_rate" in data, f"Missing 'automation_rate' in response: {data}"
        assert "total_documents" in data, f"Missing 'total_documents' in response: {data}"
        
        # Verify types
        assert isinstance(data["automation_rate"], (int, float)), f"automation_rate should be numeric, got {type(data['automation_rate'])}"
        assert isinstance(data["total_documents"], int), f"total_documents should be int, got {type(data['total_documents'])}"
        
        print(f"✓ automation-rate returned: automation_rate={data['automation_rate']}%, total_documents={data['total_documents']}")

    def test_automation_rate_with_days_param(self):
        """GET /api/readiness/automation-rate accepts days parameter"""
        response = requests.get(f"{BASE_URL}/api/readiness/automation-rate?days=7")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "automation_rate" in data
        assert data.get("period_days") == 7, f"Expected period_days=7, got {data.get('period_days')}"
        print(f"✓ automation-rate with days=7 returned: automation_rate={data['automation_rate']}%")


class TestReadinessMetricsEndpoint:
    """Test GET /api/readiness/metrics still works"""

    def test_readiness_metrics_returns_200(self):
        """GET /api/readiness/metrics should return 200 with expected fields"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify expected fields
        assert "total_documents" in data, f"Missing 'total_documents' in response: {data}"
        assert "by_status" in data, f"Missing 'by_status' in response: {data}"
        
        # Verify types
        assert isinstance(data["total_documents"], int), f"total_documents should be int, got {type(data['total_documents'])}"
        assert isinstance(data["by_status"], dict), f"by_status should be dict, got {type(data['by_status'])}"
        
        print(f"✓ readiness/metrics returned: total_documents={data['total_documents']}, by_status={data['by_status']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
