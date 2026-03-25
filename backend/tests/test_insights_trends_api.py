"""
Test suite for Insights Trends API and related dashboard endpoints.
Tests the new /api/dashboard/insights-trends endpoint and validates
the Insights page data requirements.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestInsightsTrendsAPI:
    """Tests for GET /api/dashboard/insights-trends endpoint"""
    
    def test_insights_trends_returns_200(self):
        """insights-trends endpoint returns 200 OK"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insights-trends")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: insights-trends returns 200")
    
    def test_insights_trends_has_required_fields(self):
        """insights-trends returns daily array, bakeoff_runs, and period_days"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insights-trends?days=30")
        assert response.status_code == 200
        data = response.json()
        
        # Check top-level fields
        assert "daily" in data, "Missing 'daily' field"
        assert "bakeoff_runs" in data, "Missing 'bakeoff_runs' field"
        assert "period_days" in data, "Missing 'period_days' field"
        
        assert isinstance(data["daily"], list), "'daily' should be a list"
        assert isinstance(data["bakeoff_runs"], list), "'bakeoff_runs' should be a list"
        assert isinstance(data["period_days"], int), "'period_days' should be an int"
        print("PASS: insights-trends has all required top-level fields")
    
    def test_insights_trends_daily_entry_fields(self):
        """Each daily entry has correct fields: date, ingested, auto_rate, validation_rate, exception_rate, ai_confidence, vendor_resolve_rate"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insights-trends?days=30")
        assert response.status_code == 200
        data = response.json()
        
        daily = data.get("daily", [])
        if len(daily) > 0:
            entry = daily[0]
            required_fields = ["date", "ingested", "auto_rate", "validation_rate", "exception_rate", "ai_confidence", "vendor_resolve_rate"]
            for field in required_fields:
                assert field in entry, f"Missing field '{field}' in daily entry"
            print(f"PASS: Daily entry has all required fields: {required_fields}")
        else:
            print("SKIP: No daily data to validate fields (empty array)")
    
    def test_insights_trends_daily_values_are_numeric(self):
        """Daily entry numeric fields are valid numbers"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insights-trends?days=30")
        assert response.status_code == 200
        data = response.json()
        
        daily = data.get("daily", [])
        if len(daily) > 0:
            entry = daily[0]
            numeric_fields = ["ingested", "auto_rate", "validation_rate", "exception_rate", "ai_confidence", "vendor_resolve_rate"]
            for field in numeric_fields:
                value = entry.get(field)
                assert isinstance(value, (int, float)), f"Field '{field}' should be numeric, got {type(value)}"
            print("PASS: All numeric fields in daily entry are valid numbers")
        else:
            print("SKIP: No daily data to validate numeric fields")
    
    def test_insights_trends_rates_are_percentages(self):
        """Rate fields are valid percentages (0-100)"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insights-trends?days=30")
        assert response.status_code == 200
        data = response.json()
        
        daily = data.get("daily", [])
        if len(daily) > 0:
            entry = daily[0]
            rate_fields = ["auto_rate", "validation_rate", "exception_rate", "ai_confidence", "vendor_resolve_rate"]
            for field in rate_fields:
                value = entry.get(field, 0)
                assert 0 <= value <= 100, f"Field '{field}' should be 0-100, got {value}"
            print("PASS: All rate fields are valid percentages (0-100)")
        else:
            print("SKIP: No daily data to validate percentages")
    
    def test_insights_trends_period_selector_7d(self):
        """Period selector with days=7 works"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insights-trends?days=7")
        assert response.status_code == 200
        data = response.json()
        assert data["period_days"] == 7, f"Expected period_days=7, got {data['period_days']}"
        print("PASS: Period selector days=7 works")
    
    def test_insights_trends_period_selector_14d(self):
        """Period selector with days=14 works"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insights-trends?days=14")
        assert response.status_code == 200
        data = response.json()
        assert data["period_days"] == 14, f"Expected period_days=14, got {data['period_days']}"
        print("PASS: Period selector days=14 works")
    
    def test_insights_trends_period_selector_30d(self):
        """Period selector with days=30 works"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insights-trends?days=30")
        assert response.status_code == 200
        data = response.json()
        assert data["period_days"] == 30, f"Expected period_days=30, got {data['period_days']}"
        print("PASS: Period selector days=30 works")


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
