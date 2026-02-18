"""
Phase 5: ELT ROI Dashboard - Backend API Tests
Tests for ROI Summary tab data endpoints
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestSettingsStatusAPI:
    """Tests for /api/settings/status endpoint - features section"""
    
    def test_settings_status_returns_features_section(self):
        """Verify settings status includes features section with create_draft_header"""
        response = requests.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200
        
        data = response.json()
        assert "features" in data, "Settings status should include features section"
        assert "create_draft_header" in data["features"], "Features should include create_draft_header"
        
        draft_feature = data["features"]["create_draft_header"]
        assert "enabled" in draft_feature, "create_draft_header should have enabled flag"
        assert "description" in draft_feature, "create_draft_header should have description"
        assert "safety_thresholds" in draft_feature, "create_draft_header should have safety_thresholds"
        
    def test_settings_status_safety_thresholds(self):
        """Verify safety thresholds are present and correct"""
        response = requests.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200
        
        data = response.json()
        thresholds = data["features"]["create_draft_header"]["safety_thresholds"]
        
        assert "eligible_match_methods" in thresholds
        assert "min_match_score_for_draft" in thresholds
        assert "min_confidence_for_draft" in thresholds
        assert thresholds["min_match_score_for_draft"] >= 0.92
        assert thresholds["min_confidence_for_draft"] >= 0.92


class TestAutomationMetricsAPI:
    """Tests for /api/metrics/automation endpoint - draft metrics"""
    
    def test_automation_metrics_returns_draft_fields(self):
        """Verify automation metrics include draft-related fields"""
        response = requests.get(f"{BASE_URL}/api/metrics/automation?days=30")
        assert response.status_code == 200
        
        data = response.json()
        
        # Core metrics
        assert "total_documents" in data
        assert "automation_rate" in data
        assert "review_rate" in data
        
        # Draft metrics (Phase 4/5)
        assert "draft_created_count" in data, "Should include draft_created_count"
        assert "draft_creation_rate" in data, "Should include draft_creation_rate"
        assert "draft_feature_enabled" in data, "Should include draft_feature_enabled"
        assert "header_only_flag" in data, "Should include header_only_flag"
        
    def test_automation_metrics_status_distribution(self):
        """Verify status distribution is present"""
        response = requests.get(f"{BASE_URL}/api/metrics/automation?days=30")
        assert response.status_code == 200
        
        data = response.json()
        assert "status_distribution" in data
        assert "counts" in data["status_distribution"]
        assert "percentages" in data["status_distribution"]
        
    def test_automation_metrics_alias_fields(self):
        """Verify alias-related fields for ROI Summary"""
        response = requests.get(f"{BASE_URL}/api/metrics/automation?days=30")
        assert response.status_code == 200
        
        data = response.json()
        assert "alias_auto_linked" in data
        assert "alias_exception_rate" in data
        assert "duplicate_prevented" in data


class TestVendorMetricsAPI:
    """Tests for /api/metrics/vendors endpoint - Vendor Friction Matrix"""
    
    def test_vendor_metrics_returns_vendors_list(self):
        """Verify vendor metrics returns vendors array"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendors?days=30")
        assert response.status_code == 200
        
        data = response.json()
        assert "vendors" in data
        assert isinstance(data["vendors"], list)
        
    def test_vendor_metrics_vendor_fields(self):
        """Verify each vendor has required fields for Vendor Friction Matrix"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendors?days=30")
        assert response.status_code == 200
        
        data = response.json()
        if data["vendors"]:
            vendor = data["vendors"][0]
            # Required fields for Vendor Friction Matrix table
            assert "vendor" in vendor, "Should have vendor name"
            assert "total_documents" in vendor, "Should have total_documents"
            assert "auto_rate" in vendor, "Should have auto_rate (Automation %)"
            assert "friction_index" in vendor, "Should have friction_index (Exception %)"
            assert "avg_confidence" in vendor, "Should have avg_confidence (Avg Score)"
            assert "has_alias" in vendor, "Should have has_alias flag"
            assert "alias_matches" in vendor, "Should have alias_matches (Alias Usage)"


class TestAliasImpactAPI:
    """Tests for /api/metrics/alias-impact endpoint - Alias Impact section"""
    
    def test_alias_impact_returns_required_fields(self):
        """Verify alias impact returns fields for ROI Summary"""
        response = requests.get(f"{BASE_URL}/api/metrics/alias-impact")
        assert response.status_code == 200
        
        data = response.json()
        
        # Required fields for Alias Impact section
        assert "total_aliases" in data, "Should have total_aliases (Vendors w/ Alias)"
        assert "alias_contribution" in data, "Should have alias_contribution (Automation From Alias %)"
        assert "total_alias_usage" in data, "Should have total_alias_usage"
        
    def test_alias_impact_match_method_distribution(self):
        """Verify match method distribution is present"""
        response = requests.get(f"{BASE_URL}/api/metrics/alias-impact")
        assert response.status_code == 200
        
        data = response.json()
        assert "match_method_distribution" in data
        assert "match_method_percentages" in data


class TestDailyMetricsAPI:
    """Tests for /api/metrics/daily endpoint - Trend chart data"""
    
    def test_daily_metrics_returns_data(self):
        """Verify daily metrics returns data for trend chart"""
        response = requests.get(f"{BASE_URL}/api/metrics/daily?days=14")
        assert response.status_code == 200
        
        data = response.json()
        assert "daily_metrics" in data
        assert isinstance(data["daily_metrics"], list)
        
    def test_daily_metrics_has_chart_fields(self):
        """Verify daily metrics has fields needed for trend chart"""
        response = requests.get(f"{BASE_URL}/api/metrics/daily?days=14")
        assert response.status_code == 200
        
        data = response.json()
        if data["daily_metrics"]:
            day = data["daily_metrics"][0]
            assert "date" in day, "Should have date field"
            # Chart shows auto_linked and needs_review
            assert "auto_linked" in day or "total" in day, "Should have auto_linked or total"


class TestResolutionTimeAPI:
    """Tests for /api/metrics/resolution-time endpoint - Processing Time"""
    
    def test_resolution_time_returns_median(self):
        """Verify resolution time returns median_minutes for Executive Summary"""
        response = requests.get(f"{BASE_URL}/api/metrics/resolution-time?days=30")
        assert response.status_code == 200
        
        data = response.json()
        assert "median_minutes" in data, "Should have median_minutes for Processing Time"


class TestDraftFeatureToggleAPI:
    """Tests for draft feature toggle endpoints"""
    
    def test_get_draft_feature_status(self):
        """Verify GET draft feature status endpoint"""
        response = requests.get(f"{BASE_URL}/api/settings/features/create-draft-header")
        assert response.status_code == 200
        
        data = response.json()
        assert "feature" in data
        assert data["feature"] == "create_draft_header"
        assert "enabled" in data
        assert "safety_thresholds" in data
        
    def test_toggle_draft_feature(self):
        """Verify POST draft feature toggle endpoint"""
        # Get current state
        get_response = requests.get(f"{BASE_URL}/api/settings/features/create-draft-header")
        current_state = get_response.json()["enabled"]
        
        # Toggle to opposite state
        toggle_response = requests.post(
            f"{BASE_URL}/api/settings/features/create-draft-header",
            json={"enabled": not current_state}
        )
        assert toggle_response.status_code == 200
        
        data = toggle_response.json()
        assert "previous_value" in data
        assert "current_value" in data
        assert data["previous_value"] == current_state
        assert data["current_value"] == (not current_state)
        
        # Restore original state
        requests.post(
            f"{BASE_URL}/api/settings/features/create-draft-header",
            json={"enabled": current_state}
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
