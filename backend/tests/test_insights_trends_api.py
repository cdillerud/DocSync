"""
Regression tests for dashboard/auth/documents endpoints.

2026-09-24: dropped TestInsightsTrendsAPI (insights-trends endpoint
removed, was Insights-page-only). The remaining classes here
(TestInboxStatsAPI, TestAuthAPI, TestDocumentsAPI) are unrelated
regression coverage that happened to share this file and are kept.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestInboxStatsAPI:
    """Tests for GET /api/dashboard/inbox-stats endpoint (regression)"""
    
    def test_inbox_stats_returns_200(self):
        """inbox-stats endpoint returns 200 OK"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: inbox-stats returns 200")
    
    def test_inbox_stats_has_required_fields(self):
        """inbox-stats returns all 7 required fields"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        assert response.status_code == 200
        data = response.json()
        
        required_fields = ["ingested_today", "avg_daily_7d", "auto_validation_rate", 
                          "pending_review", "bounds_alerts", "avg_ai_confidence", "total_documents"]
        for field in required_fields:
            assert field in data, f"Missing field '{field}'"
        print(f"PASS: inbox-stats has all required fields: {required_fields}")


class TestAuthAPI:
    """Tests for authentication endpoints"""
    
    def test_login_with_valid_credentials(self):
        """Login with admin/admin returns 200"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "token" in data or "access_token" in data, "Missing token in response"
        print("PASS: Login with admin/admin returns 200 with token")
    
    def test_login_with_invalid_credentials(self):
        """Login with invalid credentials returns 401/403"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "invalid",
            "password": "wrong"
        })
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: Login with invalid credentials returns 401/403")


class TestDocumentsAPI:
    """Tests for documents endpoint"""
    
    def test_documents_returns_200(self):
        """GET /api/documents returns 200"""
        response = requests.get(f"{BASE_URL}/api/documents?limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "documents" in data, "Missing 'documents' field"
        print("PASS: GET /api/documents returns 200 with documents list")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
