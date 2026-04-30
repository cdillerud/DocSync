"""
GPI Document Hub — Inside Sales Pilot Refactor Backend Tests
============================================================

Tests for the unified validation service facade, policies registry,
BC prod validation endpoints, and related enhancements.

Test Coverage:
1. POST /api/inside-sales-pilot/validate/{doc_id} - BC prod validation
2. GET /api/inside-sales-pilot/diagnose-order-match - diagnostic endpoint with new summary schema
3. POST /api/inside-sales-pilot/validate-all - batch validation
4. POST /api/readiness/evaluate/{doc_id} - readiness evaluation via unified facade
5. GET /api/inside-sales-pilot/status - pilot status smoke test
6. Unified validation service facade imports
7. Policies registry (4 policies: archive, warehouse, ap_invoice, sales_order)
8. Low-volume vendor gate (introspection)
9. BOL/Tracking field extraction (introspection)
10. Order Match fuzzy tier
"""

import pytest
import requests
import os
import sys

# Add backend to path for direct imports
sys.path.insert(0, '/app/backend')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://contract-intel-9.preview.emergentagent.com').rstrip('/')


class TestUnifiedValidationServiceFacade:
    """Test that unified_validation_service facade imports work correctly."""
    
    def test_facade_imports_work(self):
        """Verify all facade exports can be imported without error."""
        try:
            from services.unified_validation_service import (
                validate_document,
                run_bc_prod_validation,
                run_readiness,
                run_pilot_readiness,
                POLICY_STAGES,
            )
            assert callable(validate_document), "validate_document should be callable"
            assert callable(run_bc_prod_validation), "run_bc_prod_validation should be callable"
            assert callable(run_readiness), "run_readiness should be callable"
            assert callable(run_pilot_readiness), "run_pilot_readiness should be callable"
            assert isinstance(POLICY_STAGES, dict), "POLICY_STAGES should be a dict"
            print("PASS: All unified_validation_service facade imports work")
        except ImportError as e:
            pytest.fail(f"Failed to import from unified_validation_service: {e}")
    
    def test_policy_stages_structure(self):
        """Verify POLICY_STAGES has expected structure."""
        from services.unified_validation_service import POLICY_STAGES
        
        # Check expected policy hints exist
        expected_hints = ["pilot_sales", "sales_order", "ap_invoice", "purchase_order", "warehouse", "generic"]
        for hint in expected_hints:
            assert hint in POLICY_STAGES, f"POLICY_STAGES should contain '{hint}'"
            assert isinstance(POLICY_STAGES[hint], list), f"POLICY_STAGES['{hint}'] should be a list"
        
        # Check pilot_sales has bc_prod and pilot_readiness stages
        assert "bc_prod" in POLICY_STAGES["pilot_sales"], "pilot_sales should include bc_prod stage"
        assert "pilot_readiness" in POLICY_STAGES["pilot_sales"], "pilot_sales should include pilot_readiness stage"
        
        print(f"PASS: POLICY_STAGES has correct structure with {len(POLICY_STAGES)} policy hints")


class TestPoliciesRegistry:
    """Test the policies registry module."""
    
    def test_list_policies_returns_4_policies(self):
        """Verify list_policies returns 4 registered policies."""
        from policies import list_policies
        
        policies = list_policies()
        assert isinstance(policies, list), "list_policies should return a list"
        assert len(policies) == 4, f"Expected 4 policies, got {len(policies)}"
        
        policy_names = [p["name"] for p in policies]
        expected_names = ["archive", "warehouse", "ap_invoice", "sales_order"]
        for name in expected_names:
            assert name in policy_names, f"Policy '{name}' should be registered"
        
        print(f"PASS: list_policies returns 4 policies: {policy_names}")
    
    def test_get_policy_sales_order(self):
        """Verify get_policy('sales_order') returns the sales_order policy."""
        from policies import get_policy
        
        policy = get_policy("sales_order")
        assert policy is not None, "get_policy('sales_order') should return a policy"
        assert policy.policy_name == "sales_order", f"Expected sales_order policy, got {policy.policy_name}"
        print("PASS: get_policy('sales_order') returns correct policy")
    
    def test_get_policy_invoice_returns_ap_invoice(self):
        """Verify get_policy('invoice') returns the ap_invoice policy."""
        from policies import get_policy
        
        policy = get_policy("invoice")
        assert policy is not None, "get_policy('invoice') should return a policy"
        assert policy.policy_name == "ap_invoice", f"Expected ap_invoice policy, got {policy.policy_name}"
        print("PASS: get_policy('invoice') returns ap_invoice policy")
    
    def test_get_policy_bol_returns_warehouse(self):
        """Verify get_policy('bol') returns the warehouse policy."""
        from policies import get_policy
        
        policy = get_policy("bol")
        assert policy is not None, "get_policy('bol') should return a policy"
        assert policy.policy_name == "warehouse", f"Expected warehouse policy, got {policy.policy_name}"
        print("PASS: get_policy('bol') returns warehouse policy")
    
    def test_get_policy_garbage_returns_archive_fallback(self):
        """Verify get_policy('garbage') falls back to archive policy."""
        from policies import get_policy
        
        policy = get_policy("garbage")
        assert policy is not None, "get_policy('garbage') should return a fallback policy"
        # Should fall back to archive (the default fallback)
        assert policy.policy_name == "archive", f"Expected archive fallback, got {policy.policy_name}"
        print("PASS: get_policy('garbage') falls back to archive policy")


class TestInsideSalesPilotEndpoints:
    """Test Inside Sales Pilot API endpoints."""
    
    def test_pilot_status_endpoint(self):
        """GET /api/inside-sales-pilot/status returns pilot config + summary."""
        response = requests.get(f"{BASE_URL}/api/inside-sales-pilot/status", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        
        data = response.json()
        # Check expected fields
        assert "enabled" in data, "Response should contain 'enabled'"
        assert "mailboxes" in data, "Response should contain 'mailboxes'"
        assert "total_documents" in data, "Response should contain 'total_documents'"
        
        print(f"PASS: /api/inside-sales-pilot/status returns valid response (enabled={data.get('enabled')}, docs={data.get('total_documents')})")
    
    def test_validate_single_document_nonexistent(self):
        """POST /api/inside-sales-pilot/validate/{doc_id} for non-existent doc returns error dict."""
        fake_doc_id = "NONEXISTENT-DOC-12345"
        response = requests.post(f"{BASE_URL}/api/inside-sales-pilot/validate/{fake_doc_id}", timeout=30)
        
        # Should return 200 with error in body (not 404)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        
        data = response.json()
        assert "error" in data, "Response should contain 'error' for non-existent doc"
        assert fake_doc_id in data["error"], f"Error should mention doc_id: {data['error']}"
        
        print(f"PASS: /api/inside-sales-pilot/validate/{{doc_id}} returns error dict for non-existent doc")
    
    def test_validate_single_document_structure(self):
        """POST /api/inside-sales-pilot/validate/{doc_id} returns expected structure."""
        # Use a fake doc_id - should return error but with proper structure
        fake_doc_id = "TEST-VALIDATION-STRUCTURE"
        response = requests.post(f"{BASE_URL}/api/inside-sales-pilot/validate/{fake_doc_id}", timeout=30)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # For non-existent doc, should have error
        # For existing doc, should have customer_match, order_lookup, item_validation, amount_check
        if "error" not in data:
            expected_keys = ["customer_match", "order_lookup", "item_validation", "amount_check"]
            for key in expected_keys:
                assert key in data, f"Response should contain '{key}'"
        
        print("PASS: /api/inside-sales-pilot/validate endpoint returns expected structure")
    
    def test_diagnose_order_match_endpoint(self):
        """GET /api/inside-sales-pilot/diagnose-order-match returns new summary schema."""
        response = requests.get(
            f"{BASE_URL}/api/inside-sales-pilot/diagnose-order-match",
            params={"sample_size": 5},
            timeout=60
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        
        data = response.json()
        
        # Check expected top-level keys
        expected_keys = ["cache_health", "extraction_health", "sample_matches", "raw_cache_samples", "summary"]
        for key in expected_keys:
            assert key in data, f"Response should contain '{key}'"
        
        # Check summary has the new hit_via_fuzzy_normalized bucket
        summary = data.get("summary", {})
        assert "hit_via_fuzzy_normalized" in summary, "Summary should contain 'hit_via_fuzzy_normalized' bucket"
        
        # Check other expected summary fields
        summary_fields = ["sample_size", "no_ref_extracted", "hit_via_cache_multi", "hit_via_direct_cache", 
                         "hit_via_customer_scoped", "hit_via_live_bc_api", "misses", "hit_rate_pct"]
        for field in summary_fields:
            assert field in summary, f"Summary should contain '{field}'"
        
        print(f"PASS: /api/inside-sales-pilot/diagnose-order-match returns correct schema with fuzzy_normalized bucket")
        print(f"  - cache_health: {data.get('cache_health', {}).get('total_sales_order_records', 0)} sales_order records")
        print(f"  - summary: {summary}")
    
    def test_validate_all_endpoint(self):
        """POST /api/inside-sales-pilot/validate-all returns scores array + avg_score."""
        response = requests.post(
            f"{BASE_URL}/api/inside-sales-pilot/validate-all",
            params={"force": "true"},
            timeout=120
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        
        data = response.json()
        
        # Check expected fields
        assert "total" in data, "Response should contain 'total'"
        assert "validated" in data, "Response should contain 'validated'"
        assert "scores" in data, "Response should contain 'scores'"
        assert isinstance(data["scores"], list), "'scores' should be a list"
        
        # avg_score may not be present if no docs were validated
        if data.get("scores"):
            assert "avg_score" in data, "Response should contain 'avg_score' when scores exist"
        
        print(f"PASS: /api/inside-sales-pilot/validate-all returns expected structure (total={data.get('total')}, validated={data.get('validated')})")


class TestReadinessEndpoints:
    """Test readiness evaluation endpoints."""
    
    def test_evaluate_nonexistent_doc_returns_404(self):
        """POST /api/readiness/evaluate/{doc_id} for non-existent doc returns HTTP 404."""
        fake_doc_id = "NONEXISTENT-READINESS-DOC"
        response = requests.post(f"{BASE_URL}/api/readiness/evaluate/{fake_doc_id}", timeout=30)
        
        assert response.status_code == 404, f"Expected 404 for non-existent doc, got {response.status_code}: {response.text[:200]}"
        print("PASS: /api/readiness/evaluate/{doc_id} returns 404 for non-existent doc")
    
    def test_readiness_metrics_endpoint(self):
        """GET /api/readiness/metrics returns readiness analytics."""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        
        data = response.json()
        expected_keys = ["total_documents", "by_status", "by_action"]
        for key in expected_keys:
            assert key in data, f"Response should contain '{key}'"
        
        print(f"PASS: /api/readiness/metrics returns valid response (total_documents={data.get('total_documents')})")


class TestLowVolumeVendorGate:
    """Test low-volume vendor gate logic via introspection."""
    
    def test_low_volume_vendor_gate_code_exists(self):
        """Verify LOW-VOLUME VENDOR GATE code exists in document_readiness_service."""
        import inspect
        from services.document_readiness_service import evaluate_and_persist
        
        source = inspect.getsource(evaluate_and_persist)
        
        # Check for low-volume vendor gate markers
        assert "LOW-VOLUME VENDOR GATE" in source or "LOW_VOLUME_THRESHOLD" in source, \
            "evaluate_and_persist should contain LOW-VOLUME VENDOR GATE logic"
        assert "low_volume_vendor" in source, \
            "evaluate_and_persist should add 'low_volume_vendor' warning"
        
        print("PASS: Low-volume vendor gate code exists in evaluate_and_persist")
    
    def test_low_volume_threshold_value(self):
        """Verify LOW_VOLUME_THRESHOLD is set to 5."""
        import inspect
        from services.document_readiness_service import evaluate_and_persist
        
        source = inspect.getsource(evaluate_and_persist)
        
        # Check threshold value
        assert "LOW_VOLUME_THRESHOLD = 5" in source, \
            "LOW_VOLUME_THRESHOLD should be set to 5"
        
        print("PASS: LOW_VOLUME_THRESHOLD is correctly set to 5")


class TestBOLTrackingFieldExtraction:
    """Test BOL/Tracking field extraction via introspection."""
    
    def test_bol_tracking_fields_in_extraction(self):
        """Verify _extract_sales_fields adds bol_number, tracking_number, carrier."""
        import inspect
        from services.inside_sales_pilot_service import _extract_sales_fields
        
        source = inspect.getsource(_extract_sales_fields)
        
        # Check for BOL/tracking field extraction
        assert "bol_number" in source, "_extract_sales_fields should extract bol_number"
        assert "tracking_number" in source, "_extract_sales_fields should extract tracking_number"
        assert "carrier" in source, "_extract_sales_fields should extract carrier"
        
        print("PASS: _extract_sales_fields extracts bol_number, tracking_number, carrier")


class TestOrderMatchFuzzyTier:
    """Test order match fuzzy tier via introspection."""
    
    def test_fuzzy_normalized_search_tier_exists(self):
        """Verify fuzzy_normalized_search tier exists in _check_order."""
        import inspect
        from services.bc_prod_validator import _check_order
        
        source = inspect.getsource(_check_order)
        
        # Check for fuzzy normalized search tier
        assert "fuzzy_normalized" in source, "_check_order should have fuzzy_normalized search tier"
        assert "normalized_document_no" in source or "normalized_external_ref" in source, \
            "_check_order should search normalized fields"
        
        print("PASS: fuzzy_normalized_search tier exists in _check_order")
    
    def test_fuzzy_tier_minimum_length_check(self):
        """Verify fuzzy tier has minimum length check (6+ chars)."""
        import inspect
        from services.bc_prod_validator import _check_order
        
        source = inspect.getsource(_check_order)
        
        # Check for length validation
        assert "len(ref) < 6" in source or "len(normalized_ref) < 6" in source, \
            "_check_order fuzzy tier should have 6-char minimum length check"
        
        print("PASS: fuzzy tier has minimum length check")


class TestBCReferenceCacheHealth:
    """Test BC reference cache health via diagnose endpoint."""
    
    def test_cache_has_sales_order_records(self):
        """Verify bc_reference_cache has sales_order records."""
        response = requests.get(
            f"{BASE_URL}/api/inside-sales-pilot/diagnose-order-match",
            params={"sample_size": 1},
            timeout=30
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        cache_health = data.get("cache_health", {})
        total_so = cache_health.get("total_sales_order_records", 0)
        
        # Preview env should have sales_order records in cache
        assert total_so > 0, f"Expected sales_order records in cache, got {total_so}"
        
        print(f"PASS: bc_reference_cache has {total_so} sales_order records")


class TestUnifiedFacadeIntegration:
    """Test that endpoints use the unified validation service facade."""
    
    def test_validate_endpoint_uses_unified_facade(self):
        """Verify /api/inside-sales-pilot/validate/{doc_id} uses unified facade."""
        import inspect
        from routers.inside_sales_pilot import validate_single_document
        
        source = inspect.getsource(validate_single_document)
        
        # Should import from unified_validation_service
        assert "unified_validation_service" in source or "run_bc_prod_validation" in source, \
            "validate_single_document should use unified_validation_service"
        
        print("PASS: validate endpoint uses unified validation service facade")
    
    def test_readiness_evaluate_uses_unified_facade(self):
        """Verify /api/readiness/evaluate/{doc_id} uses unified facade."""
        import inspect
        from routers.readiness import evaluate_document_readiness
        
        source = inspect.getsource(evaluate_document_readiness)
        
        # Should import from unified_validation_service
        assert "unified_validation_service" in source or "run_readiness" in source, \
            "evaluate_document_readiness should use unified_validation_service"
        
        print("PASS: readiness evaluate endpoint uses unified validation service facade")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
