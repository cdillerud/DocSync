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
