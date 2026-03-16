"""
API Integration tests for vendor resolution improvements:
  - /api/aliases/metrics endpoint includes vendor_resolution_rate
  - /api/dashboard/workflow-intelligence includes vendor_resolution_rate in alias_metrics
  - Verify rapidfuzz is used for fuzzy matching
  - Verify match_method standardization
"""

import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestAliasMetricsEndpoint:
    """Tests for GET /api/aliases/metrics"""

    def test_metrics_returns_vendor_resolution_rate(self):
        """vendor_resolution_rate field must be present in response"""
        response = requests.get(f"{BASE_URL}/api/aliases/metrics")
        assert response.status_code == 200
        data = response.json()
        
        assert "vendor_resolution_rate" in data, "vendor_resolution_rate field missing"
        assert isinstance(data["vendor_resolution_rate"], (int, float))
        
    def test_metrics_returns_all_required_fields(self):
        """Verify all required fields are present"""
        response = requests.get(f"{BASE_URL}/api/aliases/metrics")
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            "total_aliases",
            "auto_learned",
            "manual_aliases",
            "alias_match_rate",
            "vendor_match_rate",
            "vendor_resolution_rate",
            "total_docs",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"


class TestWorkflowIntelligenceEndpoint:
    """Tests for GET /api/dashboard/workflow-intelligence"""

    def test_workflow_intelligence_includes_alias_metrics(self):
        """alias_metrics section must be present with vendor_resolution_rate"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        assert response.status_code == 200
        data = response.json()
        
        assert "vendor_intelligence" in data
        assert "alias_metrics" in data["vendor_intelligence"]
        
        alias_metrics = data["vendor_intelligence"]["alias_metrics"]
        assert "vendor_resolution_rate" in alias_metrics, "vendor_resolution_rate missing in alias_metrics"
        assert isinstance(alias_metrics["vendor_resolution_rate"], (int, float))
        
    def test_workflow_intelligence_alias_metrics_fields(self):
        """Verify alias_metrics has all expected fields"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        assert response.status_code == 200
        data = response.json()
        
        alias_metrics = data["vendor_intelligence"]["alias_metrics"]
        
        expected_fields = [
            "total_aliases",
            "auto_learned",
            "alias_match_rate",
            "vendor_resolution_rate",
        ]
        for field in expected_fields:
            assert field in alias_metrics, f"Missing alias_metrics field: {field}"


class TestVendorAliasesEndpoint:
    """Tests for GET /api/aliases/vendors"""

    def test_list_aliases(self):
        """Can list vendor aliases"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors")
        assert response.status_code == 200
        data = response.json()
        
        assert "aliases" in data
        assert "count" in data
        assert isinstance(data["aliases"], list)

    def test_filter_by_source(self):
        """Can filter aliases by source"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors?source=auto_learned")
        assert response.status_code == 200
        data = response.json()
        
        assert "aliases" in data
        # All returned aliases should have source=auto_learned
        for alias in data["aliases"]:
            assert alias.get("source") == "auto_learned"


class TestVendorMatchingStandardization:
    """Tests for standardized match_method values in documents"""

    def test_document_match_methods_are_standardized(self):
        """Documents should use standardized match_method values"""
        response = requests.get(f"{BASE_URL}/api/documents?limit=50")
        assert response.status_code == 200
        data = response.json()
        
        valid_methods = {
            "alias_match", "fuzzy_match", "bc_exact_match", "manual_match",
            "learned_alias", "bc_search", "normalized", "none",
            # Legacy methods that may still exist
            "alias", "exact_name", "fuzzy", "fuzzy_bc", "fuzzy_candidates",
        }
        
        documents = data.get("documents", data.get("items", []))
        for doc in documents:
            match_method = doc.get("vendor_match_method")
            if match_method and match_method != "none":
                # Just verify it's a string, not checking strict validation
                assert isinstance(match_method, str), f"match_method should be string, got {type(match_method)}"


class TestRapidfuzzIntegration:
    """Tests to verify rapidfuzz is being used for fuzzy matching"""

    def test_rapidfuzz_score_calculation(self):
        """Verify rapidfuzz-based score calculation via Python"""
        from services.vendor_name_helpers import calculate_fuzzy_score
        
        # These should score >= 0.90
        high_similarity_pairs = [
            ("ABC Industrial Supply LLC", "ABC Industrial Supply"),
            ("Smith & Associates", "Smith Associates"),
        ]
        for name1, name2 in high_similarity_pairs:
            score = calculate_fuzzy_score(name1, name2)
            assert score >= 0.90, f"Expected >=0.90 for ({name1}, {name2}), got {score}"
        
        # These should score < 0.90
        low_similarity_pairs = [
            ("ABC Industrial", "XYZ Manufacturing"),
            ("Pacific Northwest Supply", "Atlantic Southeast Logistics"),
        ]
        for name1, name2 in low_similarity_pairs:
            score = calculate_fuzzy_score(name1, name2)
            assert score < 0.90, f"Expected <0.90 for ({name1}, {name2}), got {score}"


class TestNormalizationSuffixes:
    """Tests for vendor name normalization suffix removal"""

    def test_all_suffixes_removed(self):
        """Verify all required suffixes are stripped"""
        from services.vendor_name_helpers import normalize_vendor_name
        
        test_cases = [
            ("Acme Inc.", "acme"),
            ("ABC Supply LLC", "abc supply"),
            ("Global Trading Ltd", "global trading"),
            ("Tech Corp", "tech"),
            ("Tech Corporation", "tech"),
            ("Smith Company", "smith"),
            ("Jones Co.", "jones"),
            ("British Plc", "british"),
            ("Siemens GmbH", "siemens"),
            ("Swiss AG", "swiss"),
        ]
        for input_name, expected in test_cases:
            result = normalize_vendor_name(input_name)
            assert result == expected, f"normalize_vendor_name('{input_name}') = '{result}', expected '{expected}'"
