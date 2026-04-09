"""
Iteration 201: Test inbox-metrics endpoint
Tests the new GET /api/dashboard/inbox-metrics endpoint that returns detailed breakdown
of documents currently IN the inbox (non-terminal, non-cleared).

Metrics include:
- By Status (workflow_status counts)
- By Document Type
- By Age/Staleness (lt_1h, 1h_24h, 24h_3d, gt_3d)
- By Vendor (top 10)
- By Blocker Reason (no_vendor, no_po, low_confidence, duplicate_flag, no_extraction, validation_failed)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestInboxMetricsEndpoint:
    """Tests for GET /api/dashboard/inbox-metrics"""

    def test_inbox_metrics_returns_200(self):
        """GET /api/dashboard/inbox-metrics returns 200"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-metrics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET /api/dashboard/inbox-metrics returns 200")

    def test_inbox_metrics_has_total_inbox(self):
        """Response contains total_inbox field"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-metrics")
        data = response.json()
        assert "total_inbox" in data, f"Missing 'total_inbox' in response: {data.keys()}"
        assert isinstance(data["total_inbox"], int), f"total_inbox should be int, got {type(data['total_inbox'])}"
        print(f"PASS: total_inbox = {data['total_inbox']}")

    def test_inbox_metrics_has_by_status(self):
        """Response contains by_status object"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-metrics")
        data = response.json()
        assert "by_status" in data, f"Missing 'by_status' in response: {data.keys()}"
        assert isinstance(data["by_status"], dict), f"by_status should be dict, got {type(data['by_status'])}"
        print(f"PASS: by_status = {data['by_status']}")

    def test_inbox_metrics_has_by_type(self):
        """Response contains by_type object"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-metrics")
        data = response.json()
        assert "by_type" in data, f"Missing 'by_type' in response: {data.keys()}"
        assert isinstance(data["by_type"], dict), f"by_type should be dict, got {type(data['by_type'])}"
        print(f"PASS: by_type = {data['by_type']}")

    def test_inbox_metrics_has_by_age(self):
        """Response contains by_age object with correct keys"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-metrics")
        data = response.json()
        assert "by_age" in data, f"Missing 'by_age' in response: {data.keys()}"
        assert isinstance(data["by_age"], dict), f"by_age should be dict, got {type(data['by_age'])}"
        
        # Check required age bucket keys
        required_keys = ["lt_1h", "1h_24h", "24h_3d", "gt_3d"]
        for key in required_keys:
            assert key in data["by_age"], f"Missing '{key}' in by_age: {data['by_age'].keys()}"
            assert isinstance(data["by_age"][key], int), f"by_age[{key}] should be int, got {type(data['by_age'][key])}"
        print(f"PASS: by_age = {data['by_age']}")

    def test_inbox_metrics_has_by_vendor(self):
        """Response contains by_vendor array"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-metrics")
        data = response.json()
        assert "by_vendor" in data, f"Missing 'by_vendor' in response: {data.keys()}"
        assert isinstance(data["by_vendor"], list), f"by_vendor should be list, got {type(data['by_vendor'])}"
        
        # If there are vendors, check structure
        if len(data["by_vendor"]) > 0:
            vendor_entry = data["by_vendor"][0]
            assert "vendor" in vendor_entry, f"Missing 'vendor' in vendor entry: {vendor_entry}"
            assert "count" in vendor_entry, f"Missing 'count' in vendor entry: {vendor_entry}"
        print(f"PASS: by_vendor has {len(data['by_vendor'])} entries")

    def test_inbox_metrics_has_by_blocker(self):
        """Response contains by_blocker object with correct keys"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-metrics")
        data = response.json()
        assert "by_blocker" in data, f"Missing 'by_blocker' in response: {data.keys()}"
        assert isinstance(data["by_blocker"], dict), f"by_blocker should be dict, got {type(data['by_blocker'])}"
        
        # Check required blocker keys
        required_keys = ["no_vendor", "no_po", "low_confidence", "duplicate_flag", "no_extraction", "validation_failed"]
        for key in required_keys:
            assert key in data["by_blocker"], f"Missing '{key}' in by_blocker: {data['by_blocker'].keys()}"
            assert isinstance(data["by_blocker"][key], int), f"by_blocker[{key}] should be int, got {type(data['by_blocker'][key])}"
        print(f"PASS: by_blocker = {data['by_blocker']}")

    def test_inbox_metrics_complete_response_structure(self):
        """Verify complete response structure with all 5 metric categories"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-metrics")
        data = response.json()
        
        # All required top-level keys
        required_keys = ["total_inbox", "by_status", "by_type", "by_age", "by_vendor", "by_blocker"]
        for key in required_keys:
            assert key in data, f"Missing required key '{key}' in response"
        
        print(f"PASS: Complete response structure verified with all 5 metric categories")
        print(f"  - total_inbox: {data['total_inbox']}")
        print(f"  - by_status: {len(data['by_status'])} statuses")
        print(f"  - by_type: {len(data['by_type'])} types")
        print(f"  - by_age: {data['by_age']}")
        print(f"  - by_vendor: {len(data['by_vendor'])} vendors")
        print(f"  - by_blocker: {data['by_blocker']}")


class TestInboxStatsRegression:
    """Regression tests for GET /api/dashboard/inbox-stats (existing endpoint)"""

    def test_inbox_stats_returns_200(self):
        """GET /api/dashboard/inbox-stats still returns 200"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET /api/dashboard/inbox-stats returns 200")

    def test_inbox_stats_has_required_fields(self):
        """inbox-stats response has required fields"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        data = response.json()
        
        required_fields = [
            "ingested_today", "avg_daily_7d", "auto_validation_rate",
            "pending_review", "bounds_alerts", "avg_ai_confidence", "total_documents"
        ]
        for field in required_fields:
            assert field in data, f"Missing '{field}' in inbox-stats response"
        
        print(f"PASS: inbox-stats has all required fields")
        print(f"  - ingested_today: {data['ingested_today']}")
        print(f"  - auto_validation_rate: {data['auto_validation_rate']}%")
        print(f"  - pending_review: {data['pending_review']}")


class TestDashboardStatsRegression:
    """Regression tests for GET /api/dashboard/stats"""

    def test_dashboard_stats_returns_200(self):
        """GET /api/dashboard/stats still returns 200"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET /api/dashboard/stats returns 200")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
