"""
Test Salesperson Dashboard API Endpoints
Tests the new Rep Performance Dashboard feature with 3 endpoints:
- GET /api/salesperson-dashboard/overview
- GET /api/salesperson-dashboard/trend
- GET /api/salesperson-dashboard/detail/{code}
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestSalespersonDashboardOverview:
    """Tests for /api/salesperson-dashboard/overview endpoint"""

    def test_overview_default_days(self):
        """Test overview endpoint with default days parameter"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/overview")
        assert response.status_code == 200
        
        data = response.json()
        # Verify response structure
        assert "totals" in data
        assert "salespersons" in data
        assert "unassigned" in data or data.get("unassigned") is None
        
        # Verify totals structure
        totals = data["totals"]
        assert "total_documents" in totals
        assert "total_auto_created" in totals
        assert "total_auto_attempted" in totals
        assert "total_pending_review" in totals
        assert "active_reps" in totals
        assert "days" in totals
        assert "overall_success_rate" in totals
        
        # Verify salespersons is a list
        assert isinstance(data["salespersons"], list)

    def test_overview_with_90_days(self):
        """Test overview endpoint with 90 days parameter"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/overview?days=90")
        assert response.status_code == 200
        
        data = response.json()
        assert data["totals"]["days"] == 90
        
        # Verify totals have correct types
        totals = data["totals"]
        assert isinstance(totals["total_documents"], int)
        assert isinstance(totals["total_auto_created"], int)
        assert isinstance(totals["active_reps"], int)
        assert isinstance(totals["overall_success_rate"], (int, float))

    def test_overview_with_7_days(self):
        """Test overview endpoint with 7 days parameter"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/overview?days=7")
        assert response.status_code == 200
        
        data = response.json()
        assert data["totals"]["days"] == 7

    def test_overview_with_365_days(self):
        """Test overview endpoint with 365 days parameter"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/overview?days=365")
        assert response.status_code == 200
        
        data = response.json()
        assert data["totals"]["days"] == 365

    def test_overview_unassigned_structure(self):
        """Test that unassigned bucket has correct structure when present"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/overview?days=90")
        assert response.status_code == 200
        
        data = response.json()
        unassigned = data.get("unassigned")
        
        if unassigned is not None:
            # Verify unassigned structure
            assert "code" in unassigned
            assert unassigned["code"] == "UNASSIGNED"
            assert "name" in unassigned
            assert "total_documents" in unassigned
            assert "auto_created" in unassigned
            assert "unique_customers" in unassigned
            assert "top_customers" in unassigned
            assert isinstance(unassigned["top_customers"], list)


class TestSalespersonDashboardTrend:
    """Tests for /api/salesperson-dashboard/trend endpoint"""

    def test_trend_default_params(self):
        """Test trend endpoint with default parameters"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/trend")
        assert response.status_code == 200
        
        data = response.json()
        assert "interval" in data
        assert "days" in data
        assert "data" in data
        assert isinstance(data["data"], list)

    def test_trend_with_week_interval(self):
        """Test trend endpoint with week interval"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/trend?days=90&interval=week")
        assert response.status_code == 200
        
        data = response.json()
        assert data["interval"] == "week"
        assert data["days"] == 90
        
        # Verify data point structure if data exists
        if len(data["data"]) > 0:
            point = data["data"][0]
            assert "period" in point
            assert "total" in point
            assert "auto_created" in point
            assert "auto_attempted" in point
            assert "success_rate" in point

    def test_trend_with_day_interval(self):
        """Test trend endpoint with day interval"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/trend?days=30&interval=day")
        assert response.status_code == 200
        
        data = response.json()
        assert data["interval"] == "day"

    def test_trend_with_month_interval(self):
        """Test trend endpoint with month interval"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/trend?days=180&interval=month")
        assert response.status_code == 200
        
        data = response.json()
        assert data["interval"] == "month"


class TestSalespersonDashboardDetail:
    """Tests for /api/salesperson-dashboard/detail/{code} endpoint"""

    def test_detail_nonexistent_code(self):
        """Test detail endpoint with non-existent salesperson code"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/detail/TEST_CODE?days=90")
        assert response.status_code == 200
        
        data = response.json()
        # Verify response structure
        assert "salesperson" in data
        assert "total_customers" in data
        assert "customer_breakdown" in data
        assert "recent_documents" in data
        assert "days" in data
        
        # Verify salesperson structure
        sp = data["salesperson"]
        assert "code" in sp
        assert sp["code"] == "TEST_CODE"
        assert "name" in sp
        assert "email" in sp

    def test_detail_with_different_days(self):
        """Test detail endpoint with different days parameter"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/detail/NONEXISTENT?days=30")
        assert response.status_code == 200
        
        data = response.json()
        assert data["days"] == 30

    def test_detail_customer_breakdown_structure(self):
        """Test that customer breakdown has correct structure"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/detail/TEST?days=90")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data["customer_breakdown"], list)
        assert isinstance(data["recent_documents"], list)


class TestSalespersonDashboardValidation:
    """Tests for input validation on salesperson dashboard endpoints"""

    def test_overview_invalid_days_too_low(self):
        """Test overview endpoint rejects days < 1"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/overview?days=0")
        assert response.status_code == 422  # Validation error

    def test_overview_invalid_days_too_high(self):
        """Test overview endpoint rejects days > 365"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/overview?days=500")
        assert response.status_code == 422  # Validation error

    def test_trend_invalid_interval(self):
        """Test trend endpoint rejects invalid interval"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/trend?interval=invalid")
        assert response.status_code == 422  # Validation error

    def test_trend_days_minimum(self):
        """Test trend endpoint enforces minimum days of 7"""
        response = requests.get(f"{BASE_URL}/api/salesperson-dashboard/trend?days=3")
        assert response.status_code == 422  # Validation error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
