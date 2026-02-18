"""
Test suite for Audit Dashboard (Proof Engine) and Vendor Alias Engine
Tests automation metrics, vendor friction, alias management, resolution time, and daily trends
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestAutomationMetrics:
    """Tests for GET /api/metrics/automation endpoint"""
    
    def test_automation_metrics_default(self):
        """Test automation metrics with default 30 days"""
        response = requests.get(f"{BASE_URL}/api/metrics/automation")
        assert response.status_code == 200
        
        data = response.json()
        # Verify required fields
        assert "period_days" in data
        assert data["period_days"] == 30
        assert "total_documents" in data
        assert "status_distribution" in data
        assert "counts" in data["status_distribution"]
        assert "percentages" in data["status_distribution"]
        
        # Verify status counts structure
        counts = data["status_distribution"]["counts"]
        for status in ["Received", "StoredInSP", "Classified", "NeedsReview", "LinkedToBC", "Exception"]:
            assert status in counts
            assert isinstance(counts[status], int)
        
        # Verify confidence distribution
        assert "confidence_distribution" in data
        conf_dist = data["confidence_distribution"]
        assert "0.90-1.00" in conf_dist
        assert "0.80-0.90" in conf_dist
        assert "0.70-0.80" in conf_dist
        assert "below_0.70" in conf_dist
        
        # Verify calculated rates
        assert "automation_rate" in data
        assert "review_rate" in data
        assert "average_confidence" in data
        assert "duplicate_prevented" in data
        
    def test_automation_metrics_custom_days(self):
        """Test automation metrics with custom day range"""
        response = requests.get(f"{BASE_URL}/api/metrics/automation?days=7")
        assert response.status_code == 200
        
        data = response.json()
        assert data["period_days"] == 7
        
    def test_automation_metrics_job_type_filter(self):
        """Test automation metrics filtered by job type"""
        response = requests.get(f"{BASE_URL}/api/metrics/automation?job_type=AP_Invoice")
        assert response.status_code == 200
        
        data = response.json()
        assert "total_documents" in data


class TestVendorFrictionMetrics:
    """Tests for GET /api/metrics/vendors endpoint"""
    
    def test_vendor_friction_default(self):
        """Test vendor friction index with default 30 days"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendors")
        assert response.status_code == 200
        
        data = response.json()
        assert "period_days" in data
        assert data["period_days"] == 30
        assert "vendor_count" in data
        assert "vendors" in data
        assert "total_analyzed" in data
        assert isinstance(data["vendors"], list)
        
    def test_vendor_friction_structure(self):
        """Test vendor friction data structure"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendors?days=30")
        assert response.status_code == 200
        
        data = response.json()
        if data["vendors"]:
            vendor = data["vendors"][0]
            assert "vendor" in vendor
            assert "total_documents" in vendor
            assert "auto_linked" in vendor
            assert "needs_review" in vendor
            assert "auto_rate" in vendor
            assert "avg_confidence" in vendor
            assert "friction_index" in vendor


class TestAliasImpactMetrics:
    """Tests for GET /api/metrics/alias-impact endpoint"""
    
    def test_alias_impact_metrics(self):
        """Test alias impact metrics"""
        response = requests.get(f"{BASE_URL}/api/metrics/alias-impact")
        assert response.status_code == 200
        
        data = response.json()
        assert "total_aliases" in data
        assert "total_alias_usage" in data
        assert "top_aliases" in data
        assert "match_method_distribution" in data
        assert "match_method_percentages" in data
        assert "alias_contribution" in data
        
        # Verify match method distribution structure
        match_methods = data["match_method_distribution"]
        for method in ["exact_no", "exact_name", "normalized", "alias", "fuzzy", "no_match"]:
            assert method in match_methods


class TestResolutionTimeMetrics:
    """Tests for GET /api/metrics/resolution-time endpoint"""
    
    def test_resolution_time_default(self):
        """Test resolution time metrics with default 30 days"""
        response = requests.get(f"{BASE_URL}/api/metrics/resolution-time")
        assert response.status_code == 200
        
        data = response.json()
        assert "period_days" in data
        assert data["period_days"] == 30
        assert "total_resolved" in data
        assert "median_minutes" in data
        assert "p95_minutes" in data
        assert "avg_minutes" in data
        assert "by_job_type" in data
        
    def test_resolution_time_custom_days(self):
        """Test resolution time with custom day range"""
        response = requests.get(f"{BASE_URL}/api/metrics/resolution-time?days=7")
        assert response.status_code == 200
        
        data = response.json()
        assert data["period_days"] == 7


class TestDailyMetrics:
    """Tests for GET /api/metrics/daily endpoint"""
    
    def test_daily_metrics_default(self):
        """Test daily metrics with default 14 days"""
        response = requests.get(f"{BASE_URL}/api/metrics/daily")
        assert response.status_code == 200
        
        data = response.json()
        assert "daily_metrics" in data
        assert isinstance(data["daily_metrics"], list)
        assert len(data["daily_metrics"]) == 14
        
    def test_daily_metrics_structure(self):
        """Test daily metrics data structure"""
        response = requests.get(f"{BASE_URL}/api/metrics/daily?days=7")
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["daily_metrics"]) == 7
        
        if data["daily_metrics"]:
            day = data["daily_metrics"][0]
            assert "date" in day
            assert "total" in day
            assert "auto_linked" in day
            assert "needs_review" in day
            assert "auto_rate" in day


class TestVendorAliasEngine:
    """Tests for Vendor Alias CRUD operations"""
    
    @pytest.fixture
    def test_alias_data(self):
        """Generate unique test alias data"""
        unique_id = str(uuid.uuid4())[:8]
        return {
            "alias_string": f"TEST_Vendor_{unique_id}",
            "vendor_no": f"V{unique_id}",
            "vendor_name": f"Test Vendor Name {unique_id}",
            "notes": "Test alias for automated testing"
        }
    
    def test_list_aliases_empty(self):
        """Test listing aliases when empty"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors")
        assert response.status_code == 200
        
        data = response.json()
        assert "aliases" in data
        assert "count" in data
        assert isinstance(data["aliases"], list)
        
    def test_create_alias(self, test_alias_data):
        """Test creating a new vendor alias"""
        response = requests.post(
            f"{BASE_URL}/api/aliases/vendors",
            json=test_alias_data
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "alias_id" in data
        assert "message" in data
        assert data["message"] == "Alias created successfully"
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/aliases/vendors/{data['alias_id']}")
        
    def test_create_and_verify_alias(self, test_alias_data):
        """Test creating alias and verifying it's persisted"""
        # Create
        create_response = requests.post(
            f"{BASE_URL}/api/aliases/vendors",
            json=test_alias_data
        )
        assert create_response.status_code == 200
        alias_id = create_response.json()["alias_id"]
        
        # Verify via list
        list_response = requests.get(f"{BASE_URL}/api/aliases/vendors")
        assert list_response.status_code == 200
        
        aliases = list_response.json()["aliases"]
        found = next((a for a in aliases if a["alias_id"] == alias_id), None)
        assert found is not None
        assert found["alias_string"] == test_alias_data["alias_string"]
        assert found["vendor_no"] == test_alias_data["vendor_no"]
        assert found["vendor_name"] == test_alias_data["vendor_name"]
        assert "normalized_alias" in found
        assert "usage_count" in found
        assert found["usage_count"] == 0
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/aliases/vendors/{alias_id}")
        
    def test_create_duplicate_alias_fails(self, test_alias_data):
        """Test that creating duplicate alias returns error"""
        # Create first alias
        create_response = requests.post(
            f"{BASE_URL}/api/aliases/vendors",
            json=test_alias_data
        )
        assert create_response.status_code == 200
        alias_id = create_response.json()["alias_id"]
        
        # Try to create duplicate
        duplicate_response = requests.post(
            f"{BASE_URL}/api/aliases/vendors",
            json=test_alias_data
        )
        assert duplicate_response.status_code == 400
        assert "already exists" in duplicate_response.json().get("detail", "")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/aliases/vendors/{alias_id}")
        
    def test_delete_alias(self, test_alias_data):
        """Test deleting a vendor alias"""
        # Create
        create_response = requests.post(
            f"{BASE_URL}/api/aliases/vendors",
            json=test_alias_data
        )
        alias_id = create_response.json()["alias_id"]
        
        # Delete
        delete_response = requests.delete(f"{BASE_URL}/api/aliases/vendors/{alias_id}")
        assert delete_response.status_code == 200
        assert delete_response.json()["message"] == "Alias deleted"
        
        # Verify deleted
        list_response = requests.get(f"{BASE_URL}/api/aliases/vendors")
        aliases = list_response.json()["aliases"]
        found = next((a for a in aliases if a["alias_id"] == alias_id), None)
        assert found is None
        
    def test_delete_nonexistent_alias(self):
        """Test deleting non-existent alias returns 404"""
        response = requests.delete(f"{BASE_URL}/api/aliases/vendors/nonexistent-id")
        assert response.status_code == 404
        
    def test_suggest_alias_new(self):
        """Test alias suggestion for new vendor"""
        response = requests.get(
            f"{BASE_URL}/api/aliases/vendors/suggest",
            params={
                "vendor_name": "NewTestVendor",
                "resolved_vendor_no": "V999",
                "resolved_vendor_name": "New Test Vendor Inc"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["suggest_alias"] == True
        assert "suggested_alias" in data
        assert data["suggested_alias"]["alias_string"] == "NewTestVendor"
        assert data["suggested_alias"]["vendor_no"] == "V999"
        assert data["suggested_alias"]["vendor_name"] == "New Test Vendor Inc"
        assert "message" in data
        
    def test_suggest_alias_existing(self, test_alias_data):
        """Test alias suggestion when alias already exists"""
        # Create alias first
        create_response = requests.post(
            f"{BASE_URL}/api/aliases/vendors",
            json=test_alias_data
        )
        alias_id = create_response.json()["alias_id"]
        
        # Try to suggest same alias
        suggest_response = requests.get(
            f"{BASE_URL}/api/aliases/vendors/suggest",
            params={
                "vendor_name": test_alias_data["alias_string"],
                "resolved_vendor_no": "V999",
                "resolved_vendor_name": "Some Vendor"
            }
        )
        assert suggest_response.status_code == 200
        
        data = suggest_response.json()
        assert data["suggest_alias"] == False
        assert data["reason"] == "Alias already exists"
        assert "existing_alias" in data
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/aliases/vendors/{alias_id}")


class TestAuthentication:
    """Test authentication for audit dashboard"""
    
    def test_login_success(self):
        """Test successful login"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": "admin", "password": "admin"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "token" in data
        assert "user" in data
        assert data["user"]["username"] == "admin"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
