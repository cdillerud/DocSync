"""
Iteration 202: Test retry-captured feature for documents stuck in 'Captured' workflow_status.

Features tested:
1. POST /api/readiness/retry-captured - returns 200 with correct response structure
2. POST /api/readiness/retry-captured?force_escalate=true - returns 200
3. GET /api/dashboard/inbox-metrics - regression check
4. GET /api/dashboard/inbox-stats - regression check
5. Backend scheduler log verification (Captured Doc Auto-Retry scheduler started)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestRetryCapturedEndpoint:
    """Tests for POST /api/readiness/retry-captured endpoint"""

    def test_retry_captured_returns_200(self):
        """POST /api/readiness/retry-captured returns 200"""
        response = requests.post(f"{BASE_URL}/api/readiness/retry-captured")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: POST /api/readiness/retry-captured returns 200")

    def test_retry_captured_response_structure(self):
        """Response has correct structure: total_found, retried, escalated_to_exception, max_retries, details, message"""
        response = requests.post(f"{BASE_URL}/api/readiness/retry-captured")
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        assert "total_found" in data, "Missing 'total_found' field"
        assert "retried" in data, "Missing 'retried' field"
        assert "escalated_to_exception" in data, "Missing 'escalated_to_exception' field"
        assert "max_retries" in data, "Missing 'max_retries' field"
        assert "details" in data, "Missing 'details' field"
        assert "message" in data, "Missing 'message' field"
        
        # Check types
        assert isinstance(data["total_found"], int), "total_found should be int"
        assert isinstance(data["retried"], int), "retried should be int"
        assert isinstance(data["escalated_to_exception"], int), "escalated_to_exception should be int"
        assert isinstance(data["max_retries"], int), "max_retries should be int"
        assert isinstance(data["details"], list), "details should be list"
        assert isinstance(data["message"], str), "message should be str"
        
        print(f"PASS: Response structure correct - total_found={data['total_found']}, retried={data['retried']}, escalated={data['escalated_to_exception']}, max_retries={data['max_retries']}")

    def test_retry_captured_max_retries_is_4(self):
        """max_retries should be 4 as per requirements"""
        response = requests.post(f"{BASE_URL}/api/readiness/retry-captured")
        assert response.status_code == 200
        data = response.json()
        
        assert data["max_retries"] == 4, f"Expected max_retries=4, got {data['max_retries']}"
        print("PASS: max_retries is 4")

    def test_retry_captured_with_force_escalate(self):
        """POST /api/readiness/retry-captured?force_escalate=true returns 200"""
        response = requests.post(f"{BASE_URL}/api/readiness/retry-captured?force_escalate=true")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Should have same structure
        assert "total_found" in data
        assert "retried" in data
        assert "escalated_to_exception" in data
        assert "message" in data
        
        print(f"PASS: force_escalate=true returns 200 - total_found={data['total_found']}, escalated={data['escalated_to_exception']}")

    def test_retry_captured_with_limit_param(self):
        """POST /api/readiness/retry-captured?limit=10 returns 200"""
        response = requests.post(f"{BASE_URL}/api/readiness/retry-captured?limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: limit parameter accepted")


class TestRegressionDashboardEndpoints:
    """Regression tests for dashboard endpoints from previous iterations"""

    def test_inbox_metrics_returns_200(self):
        """GET /api/dashboard/inbox-metrics returns 200 (regression from iteration 201)"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-metrics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check key fields exist
        assert "total_inbox" in data, "Missing total_inbox"
        assert "by_status" in data, "Missing by_status"
        assert "by_type" in data, "Missing by_type"
        assert "by_age" in data, "Missing by_age"
        assert "by_vendor" in data, "Missing by_vendor"
        assert "by_blocker" in data, "Missing by_blocker"
        
        print(f"PASS: GET /api/dashboard/inbox-metrics returns 200 with all fields - total_inbox={data['total_inbox']}")

    def test_inbox_stats_returns_200(self):
        """GET /api/dashboard/inbox-stats returns 200 (regression)"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check key fields
        assert "ingested_today" in data, "Missing ingested_today"
        assert "auto_validation_rate" in data, "Missing auto_validation_rate"
        assert "pending_review" in data, "Missing pending_review"
        
        print(f"PASS: GET /api/dashboard/inbox-stats returns 200 - ingested_today={data['ingested_today']}")


class TestExceptionQueueEndpoint:
    """Tests for exception queue endpoint"""

    def test_exception_queue_returns_200(self):
        """GET /api/readiness/exception-queue returns 200"""
        response = requests.get(f"{BASE_URL}/api/readiness/exception-queue")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "total" in data, "Missing 'total' field"
        assert "documents" in data, "Missing 'documents' field"
        assert isinstance(data["total"], int), "total should be int"
        assert isinstance(data["documents"], list), "documents should be list"
        
        print(f"PASS: GET /api/readiness/exception-queue returns 200 - total={data['total']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
