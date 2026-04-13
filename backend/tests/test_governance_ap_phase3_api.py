"""
Integration tests for Governance Dashboard and AP Advisory Phase 3 APIs
Tests:
- GET /api/governance/dashboard - Unified governance dashboard
- POST /api/ap-advisory/suggestions/{id}/approve|reject|apply - Suggestion workflow
- GET /api/ap-advisory/learning-impact-review - Impact review
- GET /api/ap-advisory/learning-impact-review/details - Impact details
- GET /api/ap-advisory/profile-drift - Profile drift summary
- GET /api/ap-advisory/profile-drift/{vendor_no} - Vendor drift detail
- GET /api/ap-advisory/profile-change-history/{vendor_no} - Change history
- GET /api/ap-advisory/vendor-hotspots - Vendor hotspots
- GET /api/ap-advisory/vendor-hotspots/{vendor_no} - Vendor hotspot detail
"""

import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for protected endpoints"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "username": "admin",
        "password": "admin"
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip("Authentication failed - skipping authenticated tests")

@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session

@pytest.fixture
def authenticated_client(api_client, auth_token):
    """Session with auth header"""
    api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
    return api_client


# =============================================================================
# Governance Dashboard Tests
# =============================================================================

class TestGovernanceDashboard:
    """Tests for GET /api/governance/dashboard"""
    
    def test_governance_dashboard_returns_200(self, api_client):
        """Governance dashboard should return 200 without auth"""
        response = api_client.get(f"{BASE_URL}/api/governance/dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET /api/governance/dashboard returns 200")
    
    def test_governance_dashboard_has_sales_orders(self, api_client):
        """Dashboard should have sales_orders section"""
        response = api_client.get(f"{BASE_URL}/api/governance/dashboard")
        data = response.json()
        assert "sales_orders" in data, "Missing sales_orders section"
        so = data["sales_orders"]
        assert "suggestions" in so, "Missing suggestions in sales_orders"
        assert "feedback" in so, "Missing feedback in sales_orders"
        assert "drift_30d" in so, "Missing drift_30d in sales_orders"
        assert "hotspots" in so, "Missing hotspots in sales_orders"
        print("PASS: Dashboard has sales_orders with suggestions, feedback, drift_30d, hotspots")
    
    def test_governance_dashboard_has_ap_invoices(self, api_client):
        """Dashboard should have ap_invoices section"""
        response = api_client.get(f"{BASE_URL}/api/governance/dashboard")
        data = response.json()
        assert "ap_invoices" in data, "Missing ap_invoices section"
        ap = data["ap_invoices"]
        assert "suggestions" in ap, "Missing suggestions in ap_invoices"
        assert "feedback" in ap, "Missing feedback in ap_invoices"
        assert "drift_30d" in ap, "Missing drift_30d in ap_invoices"
        assert "hotspots" in ap, "Missing hotspots in ap_invoices"
        print("PASS: Dashboard has ap_invoices with suggestions, feedback, drift_30d, hotspots")
    
    def test_governance_dashboard_has_system_health(self, api_client):
        """Dashboard should have system_health with 7 key metrics"""
        response = api_client.get(f"{BASE_URL}/api/governance/dashboard")
        data = response.json()
        assert "system_health" in data, "Missing system_health section"
        sys = data["system_health"]
        required_fields = [
            "total_documents", "pending_review", "completed", 
            "posted_to_bc_7d", "ready_to_post", "vendor_profiles", "automation_rate"
        ]
        for field in required_fields:
            assert field in sys, f"Missing {field} in system_health"
        print(f"PASS: system_health has all 7 required fields: {required_fields}")
    
    def test_governance_dashboard_has_combined_drift(self, api_client):
        """Dashboard should have combined_drift section"""
        response = api_client.get(f"{BASE_URL}/api/governance/dashboard")
        data = response.json()
        assert "combined_drift" in data, "Missing combined_drift section"
        cd = data["combined_drift"]
        assert "low" in cd, "Missing low in combined_drift"
        assert "medium" in cd, "Missing medium in combined_drift"
        assert "high" in cd, "Missing high in combined_drift"
        print("PASS: Dashboard has combined_drift with low, medium, high")


# =============================================================================
# AP Advisory Suggestion Workflow Tests (Require Auth)
# =============================================================================

class TestAPSuggestionWorkflow:
    """Tests for suggestion approve/reject/apply endpoints"""
    
    def test_approve_nonexistent_suggestion_returns_422(self, authenticated_client):
        """Approving nonexistent suggestion should return 422"""
        response = authenticated_client.post(f"{BASE_URL}/api/ap-advisory/suggestions/FAKE_SUGG_001/approve")
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print("PASS: POST /api/ap-advisory/suggestions/FAKE_SUGG_001/approve returns 422")
    
    def test_reject_nonexistent_suggestion_returns_422(self, authenticated_client):
        """Rejecting nonexistent suggestion should return 422"""
        response = authenticated_client.post(f"{BASE_URL}/api/ap-advisory/suggestions/FAKE_SUGG_002/reject")
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print("PASS: POST /api/ap-advisory/suggestions/FAKE_SUGG_002/reject returns 422")
    
    def test_apply_nonexistent_suggestion_returns_422(self, authenticated_client):
        """Applying nonexistent suggestion should return 422"""
        response = authenticated_client.post(f"{BASE_URL}/api/ap-advisory/suggestions/FAKE_SUGG_003/apply")
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print("PASS: POST /api/ap-advisory/suggestions/FAKE_SUGG_003/apply returns 422")
    
    def test_approve_requires_auth(self, api_client):
        """Approve endpoint should require authentication"""
        response = api_client.post(f"{BASE_URL}/api/ap-advisory/suggestions/test/approve")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Approve endpoint requires authentication (401 without token)")
    
    def test_reject_requires_auth(self, api_client):
        """Reject endpoint should require authentication"""
        response = api_client.post(f"{BASE_URL}/api/ap-advisory/suggestions/test/reject")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Reject endpoint requires authentication (401 without token)")
    
    def test_apply_requires_auth(self, api_client):
        """Apply endpoint should require authentication"""
        response = api_client.post(f"{BASE_URL}/api/ap-advisory/suggestions/test/apply")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Apply endpoint requires authentication (401 without token)")


# =============================================================================
# AP Learning Impact Review Tests
# =============================================================================

class TestAPLearningImpactReview:
    """Tests for learning impact review endpoints"""
    
    def test_learning_impact_review_returns_200(self, api_client):
        """Learning impact review should return 200"""
        response = api_client.get(f"{BASE_URL}/api/ap-advisory/learning-impact-review")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        # Verify structure - total_applied is always present
        assert "total_applied" in data, "Missing total_applied"
        # vendors_affected may be missing if no data (returns message instead)
        if data.get("total_applied", 0) > 0:
            assert "vendors_affected" in data, "Missing vendors_affected when total_applied > 0"
        print(f"PASS: GET /api/ap-advisory/learning-impact-review returns 200 (total_applied={data.get('total_applied', 0)})")
    
    def test_learning_impact_review_details_returns_200(self, api_client):
        """Learning impact review details should return 200"""
        response = api_client.get(f"{BASE_URL}/api/ap-advisory/learning-impact-review/details")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        # Verify structure
        assert "total" in data, "Missing total"
        assert "showing" in data, "Missing showing"
        assert "records" in data, "Missing records"
        print("PASS: GET /api/ap-advisory/learning-impact-review/details returns 200 with total, showing, records")


# =============================================================================
# AP Profile Drift Tests
# =============================================================================

class TestAPProfileDrift:
    """Tests for profile drift endpoints"""
    
    def test_profile_drift_returns_200(self, api_client):
        """Profile drift summary should return 200"""
        response = api_client.get(f"{BASE_URL}/api/ap-advisory/profile-drift")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "total_vendors" in data, "Missing total_vendors"
        print("PASS: GET /api/ap-advisory/profile-drift returns 200 with valid structure")
    
    def test_profile_drift_fake_vendor_returns_valid_json(self, api_client):
        """Profile drift for nonexistent vendor should return valid JSON (empty or error)"""
        response = api_client.get(f"{BASE_URL}/api/ap-advisory/profile-drift/FAKE_V001")
        # Should return 200 with empty/default data or 404
        assert response.status_code in [200, 404], f"Expected 200 or 404, got {response.status_code}: {response.text}"
        print(f"PASS: GET /api/ap-advisory/profile-drift/FAKE_V001 returns {response.status_code}")
    
    def test_profile_change_history_fake_vendor(self, api_client):
        """Change history for nonexistent vendor should return valid JSON with empty changes"""
        response = api_client.get(f"{BASE_URL}/api/ap-advisory/profile-change-history/FAKE_V001")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        # Should have changes array (possibly empty)
        assert "changes" in data or "total" in data, "Missing changes or total in response"
        print("PASS: GET /api/ap-advisory/profile-change-history/FAKE_V001 returns 200 with valid structure")


# =============================================================================
# AP Vendor Hotspots Tests
# =============================================================================

class TestAPVendorHotspots:
    """Tests for vendor hotspots endpoints"""
    
    def test_vendor_hotspots_returns_200(self, api_client):
        """Vendor hotspots should return 200"""
        response = api_client.get(f"{BASE_URL}/api/ap-advisory/vendor-hotspots")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        # Verify structure
        assert "total_vendors_analyzed" in data, "Missing total_vendors_analyzed"
        assert "severity_distribution" in data, "Missing severity_distribution"
        assert "hotspots" in data, "Missing hotspots"
        print("PASS: GET /api/ap-advisory/vendor-hotspots returns 200 with total_vendors_analyzed, severity_distribution, hotspots")
    
    def test_vendor_hotspot_detail_fake_vendor(self, api_client):
        """Vendor hotspot detail for nonexistent vendor should return valid JSON"""
        response = api_client.get(f"{BASE_URL}/api/ap-advisory/vendor-hotspots/FAKE_V001")
        # Should return 200 with empty/default data or 404
        assert response.status_code in [200, 404], f"Expected 200 or 404, got {response.status_code}: {response.text}"
        if response.status_code == 200:
            data = response.json()
            # Should have some structure
            assert isinstance(data, dict), "Response should be a dict"
        print(f"PASS: GET /api/ap-advisory/vendor-hotspots/FAKE_V001 returns {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
