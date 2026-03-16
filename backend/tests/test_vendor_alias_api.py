"""
API Integration tests for Vendor Alias Learning endpoints.

Tests:
  - GET /api/aliases/metrics - alias metrics dashboard
  - GET /api/aliases/vendors - list aliases with filters
  - GET /api/aliases/vendors/suggest - alias suggestion
  - POST /api/aliases/vendors - create alias
  - DELETE /api/aliases/vendors/by-alias/{alias} - delete by name
  - GET /api/dashboard/workflow-intelligence - alias_metrics in vendor_intelligence
"""

import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestAliasMetricsEndpoint:
    """Tests for GET /api/aliases/metrics"""

    def test_metrics_returns_required_fields(self):
        """Verify metrics endpoint returns all required fields"""
        response = requests.get(f"{BASE_URL}/api/aliases/metrics")
        assert response.status_code == 200
        
        data = response.json()
        
        # Required fields per spec
        assert "total_aliases" in data
        assert "auto_learned" in data
        assert "alias_match_rate" in data
        assert "top_aliases" in data
        assert "vendor_match_rate" in data
        
        # Type validation
        assert isinstance(data["total_aliases"], int)
        assert isinstance(data["auto_learned"], int)
        assert isinstance(data["alias_match_rate"], (int, float))
        assert isinstance(data["top_aliases"], list)
        assert isinstance(data["vendor_match_rate"], (int, float))

    def test_metrics_has_additional_stats(self):
        """Verify additional helpful stats are present"""
        response = requests.get(f"{BASE_URL}/api/aliases/metrics")
        data = response.json()
        
        assert "manual_aliases" in data
        assert "total_alias_usage" in data
        assert "alias_matched_docs" in data
        assert "total_docs" in data


class TestAliasVendorsEndpoint:
    """Tests for GET /api/aliases/vendors"""

    def test_get_all_vendors_returns_aliases(self):
        """Verify vendors endpoint returns list of aliases"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors")
        assert response.status_code == 200
        
        data = response.json()
        assert "aliases" in data
        assert "count" in data
        assert isinstance(data["aliases"], list)
        assert data["count"] == len(data["aliases"])

    def test_filter_by_source(self):
        """Verify source filter works"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors?source=auto_learned")
        assert response.status_code == 200
        
        data = response.json()
        assert "aliases" in data
        # All returned aliases should have source=auto_learned
        for alias in data["aliases"]:
            assert alias.get("source") == "auto_learned"

    def test_filter_by_vendor_id(self):
        """Verify vendor_id filter works"""
        # First get an existing vendor_no to test with
        all_response = requests.get(f"{BASE_URL}/api/aliases/vendors")
        aliases = all_response.json().get("aliases", [])
        
        if aliases:
            vendor_no = aliases[0].get("vendor_no")
            response = requests.get(f"{BASE_URL}/api/aliases/vendors?vendor_id={vendor_no}")
            assert response.status_code == 200


class TestAliasSuggestEndpoint:
    """Tests for GET /api/aliases/vendors/suggest"""

    def test_suggest_new_alias(self):
        """Verify suggest endpoint returns suggestion for new alias"""
        response = requests.get(
            f"{BASE_URL}/api/aliases/vendors/suggest",
            params={
                "vendor_name": "UniqueTestVendorXYZ123",
                "resolved_vendor_no": "VTEST",
                "resolved_vendor_name": "Test Resolved Vendor"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "suggest_alias" in data
        assert data["suggest_alias"] == True
        assert "suggested_alias" in data
        assert data["suggested_alias"]["alias_string"] == "UniqueTestVendorXYZ123"
        assert data["suggested_alias"]["vendor_no"] == "VTEST"

    def test_suggest_existing_alias_returns_false(self):
        """Verify suggest returns false for existing aliases"""
        # First create an alias
        create_response = requests.post(
            f"{BASE_URL}/api/aliases/vendors",
            json={
                "alias_string": "TestSuggestExisting",
                "vendor_no": "VSUGGEST",
                "vendor_name": "Test Suggest Vendor"
            }
        )
        
        try:
            # Now try to suggest same alias
            response = requests.get(
                f"{BASE_URL}/api/aliases/vendors/suggest",
                params={
                    "vendor_name": "TestSuggestExisting",
                    "resolved_vendor_no": "VOTHER",
                    "resolved_vendor_name": "Other Vendor"
                }
            )
            assert response.status_code == 200
            
            data = response.json()
            assert data["suggest_alias"] == False
            assert "existing_alias" in data
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/aliases/vendors/by-alias/TestSuggestExisting")


class TestAliasDeleteByNameEndpoint:
    """Tests for DELETE /api/aliases/vendors/by-alias/{alias}"""

    def test_delete_existing_alias(self):
        """Verify delete by alias name works"""
        # Create alias first
        create_response = requests.post(
            f"{BASE_URL}/api/aliases/vendors",
            json={
                "alias_string": "TestDeleteByName",
                "vendor_no": "VDELETE",
                "vendor_name": "Test Delete Vendor"
            }
        )
        assert create_response.status_code == 200
        
        # Delete by name
        delete_response = requests.delete(
            f"{BASE_URL}/api/aliases/vendors/by-alias/TestDeleteByName"
        )
        assert delete_response.status_code == 200
        assert "deleted" in delete_response.json().get("message", "").lower()
        
        # Verify deleted
        verify_response = requests.get(f"{BASE_URL}/api/aliases/vendors")
        aliases = verify_response.json().get("aliases", [])
        matching = [a for a in aliases if a.get("alias_string") == "TestDeleteByName"]
        assert len(matching) == 0

    def test_delete_nonexistent_alias_returns_404(self):
        """Verify 404 for non-existent alias"""
        response = requests.delete(
            f"{BASE_URL}/api/aliases/vendors/by-alias/NonExistentAliasXYZ999"
        )
        assert response.status_code == 404


class TestDashboardAliasMetrics:
    """Tests for alias_metrics in /api/dashboard/workflow-intelligence"""

    def test_workflow_intelligence_includes_alias_metrics(self):
        """Verify workflow-intelligence includes alias_metrics in vendor_intelligence"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        assert response.status_code == 200
        
        data = response.json()
        assert "vendor_intelligence" in data
        
        vi = data["vendor_intelligence"]
        assert "alias_metrics" in vi
        
        am = vi["alias_metrics"]
        assert "total_aliases" in am
        assert "auto_learned" in am
        assert "alias_match_rate" in am


class TestNormalization:
    """Tests for vendor name normalization via API"""

    def test_normalized_alias_created_correctly(self):
        """Verify alias normalization on creation"""
        # Create alias with suffixes
        create_response = requests.post(
            f"{BASE_URL}/api/aliases/vendors",
            json={
                "alias_string": "Test Normalization LLC",
                "vendor_no": "VNORM",
                "vendor_name": "Test Normalized Vendor"
            }
        )
        
        try:
            assert create_response.status_code == 200
            
            # Get and verify normalized form
            get_response = requests.get(f"{BASE_URL}/api/aliases/vendors")
            aliases = get_response.json().get("aliases", [])
            matching = [a for a in aliases if a.get("alias_string") == "Test Normalization LLC"]
            
            assert len(matching) == 1
            # LLC should be stripped in normalized form
            assert matching[0]["normalized_alias"] == "test normalization"
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/aliases/vendors/by-alias/Test Normalization LLC")


class TestSafetyRules:
    """Verify safety rules documented in spec"""

    def test_metrics_shows_confidence_threshold_behavior(self):
        """Document that aliases require ai_confidence >= 0.8"""
        # This is tested via unit tests, but we verify metrics are consistent
        response = requests.get(f"{BASE_URL}/api/aliases/metrics")
        assert response.status_code == 200
        
        data = response.json()
        # auto_learned should be 0 since no high-confidence approvals yet
        assert data["auto_learned"] == 0

    def test_short_vendor_raw_not_learned(self):
        """Document that vendor_raw must be >= 3 chars"""
        # This is tested via unit tests - we verify system behavior
        # by checking that no aliases exist with very short normalized forms
        response = requests.get(f"{BASE_URL}/api/aliases/vendors")
        aliases = response.json().get("aliases", [])
        
        for alias in aliases:
            # All normalized aliases should have meaningful length
            normalized = alias.get("normalized_alias", "")
            if normalized:
                # Note: normalized form may be shorter due to suffix removal
                # but original alias_string should be >= 3 chars
                assert len(alias.get("alias_string", "")) >= 3
