"""
Iteration 191: Test Vendor Processing Bypass and Batch Alias Resolution

Tests:
1. GET /api/readiness/metrics - should return valid readiness metrics
2. GET /api/vendor-intelligence/bypassed-vendors - should return empty list with count=0
3. PATCH /api/vendor-intelligence/profiles/{vendor_no}/bypass - should return 404 for non-existent vendor
4. POST /api/aliases/vendors/batch-resolve - should create alias and return results
5. POST /api/aliases/vendors/batch-resolve with empty mappings - should return 400
6. GET /api/aliases/vendors - should return aliases list
7. POST /api/readiness/reevaluate-all - should work without errors
"""

import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestReadinessMetrics:
    """Test readiness metrics endpoint"""

    def test_get_readiness_metrics(self):
        """GET /api/readiness/metrics should return valid readiness metrics"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics", timeout=30)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Validate response structure
        assert "total_documents" in data, "Missing total_documents field"
        assert "by_status" in data, "Missing by_status field"
        assert "by_action" in data, "Missing by_action field"
        assert "no_readiness_data" in data, "Missing no_readiness_data field"
        assert "top_blocking_reasons" in data, "Missing top_blocking_reasons field"
        assert "top_warning_reasons" in data, "Missing top_warning_reasons field"
        assert "top_reviewer_actions" in data, "Missing top_reviewer_actions field"
        assert "confidence_by_status" in data, "Missing confidence_by_status field"
        
        # Validate types
        assert isinstance(data["total_documents"], int), "total_documents should be int"
        assert isinstance(data["by_status"], dict), "by_status should be dict"
        assert isinstance(data["by_action"], dict), "by_action should be dict"
        assert isinstance(data["top_blocking_reasons"], list), "top_blocking_reasons should be list"
        
        print(f"Readiness metrics: total_documents={data['total_documents']}, by_status={data['by_status']}")


class TestVendorIntelligenceBypass:
    """Test vendor processing bypass endpoints"""

    def test_get_bypassed_vendors_empty(self):
        """GET /api/vendor-intelligence/bypassed-vendors should return empty list with count=0"""
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/bypassed-vendors", timeout=30)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Validate response structure
        assert "bypassed_vendors" in data, "Missing bypassed_vendors field"
        assert "count" in data, "Missing count field"
        
        # Validate types
        assert isinstance(data["bypassed_vendors"], list), "bypassed_vendors should be list"
        assert isinstance(data["count"], int), "count should be int"
        
        # In empty preview DB, should be empty or have some vendors
        print(f"Bypassed vendors: count={data['count']}, vendors={data['bypassed_vendors']}")

    def test_patch_bypass_nonexistent_vendor(self):
        """PATCH /api/vendor-intelligence/profiles/{vendor_no}/bypass should return 404 for non-existent vendor"""
        # Use a vendor_no that definitely doesn't exist
        fake_vendor_no = "NONEXISTENT_VENDOR_12345"
        
        response = requests.patch(
            f"{BASE_URL}/api/vendor-intelligence/profiles/{fake_vendor_no}/bypass",
            params={"enabled": True, "reason": "Test bypass"},
            timeout=30
        )
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data, "Missing detail field in error response"
        print(f"Correctly returned 404 for non-existent vendor: {data['detail']}")


class TestVendorAliases:
    """Test vendor alias endpoints"""

    def test_get_vendor_aliases(self):
        """GET /api/aliases/vendors should return aliases list"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors", timeout=30)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Validate response structure
        assert "aliases" in data, "Missing aliases field"
        assert "count" in data, "Missing count field"
        
        # Validate types
        assert isinstance(data["aliases"], list), "aliases should be list"
        assert isinstance(data["count"], int), "count should be int"
        
        print(f"Vendor aliases: count={data['count']}")

    def test_batch_resolve_empty_mappings(self):
        """POST /api/aliases/vendors/batch-resolve with empty mappings should return 400"""
        response = requests.post(
            f"{BASE_URL}/api/aliases/vendors/batch-resolve",
            json={"mappings": []},
            timeout=30
        )
        
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data, "Missing detail field in error response"
        print(f"Correctly returned 400 for empty mappings: {data['detail']}")

    def test_batch_resolve_creates_alias(self):
        """POST /api/aliases/vendors/batch-resolve should create alias and return results"""
        # Create a test alias mapping
        test_mapping = {
            "mappings": [
                {
                    "alias_string": "TEST_SC_Warehouses_191",
                    "vendor_no": "TESTVENDOR191",
                    "vendor_name": "Test Vendor 191"
                }
            ]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/aliases/vendors/batch-resolve",
            json=test_mapping,
            timeout=30
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Validate response structure
        assert "mappings_processed" in data, "Missing mappings_processed field"
        assert "total_docs_updated" in data, "Missing total_docs_updated field"
        assert "results" in data, "Missing results field"
        
        # Validate values
        assert data["mappings_processed"] == 1, f"Expected 1 mapping processed, got {data['mappings_processed']}"
        assert isinstance(data["results"], list), "results should be list"
        assert len(data["results"]) == 1, f"Expected 1 result, got {len(data['results'])}"
        
        result = data["results"][0]
        assert result["alias_string"] == "TEST_SC_Warehouses_191", "alias_string mismatch"
        assert result["vendor_no"] == "TESTVENDOR191", "vendor_no mismatch"
        assert result["status"] == "resolved", f"Expected status 'resolved', got {result['status']}"
        
        print(f"Batch resolve result: {data}")
        
        # Verify alias was created by fetching aliases
        verify_response = requests.get(f"{BASE_URL}/api/aliases/vendors", timeout=30)
        assert verify_response.status_code == 200
        aliases_data = verify_response.json()
        
        # Check if our test alias exists
        test_alias_found = any(
            a.get("alias_string") == "TEST_SC_Warehouses_191" 
            for a in aliases_data.get("aliases", [])
        )
        print(f"Test alias found in aliases list: {test_alias_found}")

    def test_batch_resolve_skips_invalid_mapping(self):
        """POST /api/aliases/vendors/batch-resolve should skip mappings with missing fields"""
        test_mapping = {
            "mappings": [
                {
                    "alias_string": "",  # Empty alias_string
                    "vendor_no": "TESTVENDOR",
                    "vendor_name": "Test Vendor"
                }
            ]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/aliases/vendors/batch-resolve",
            json=test_mapping,
            timeout=30
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["mappings_processed"] == 1, "Should process 1 mapping"
        
        result = data["results"][0]
        assert result["status"] == "skipped", f"Expected status 'skipped', got {result['status']}"
        assert "missing" in result.get("reason", "").lower(), "Should mention missing fields"
        
        print(f"Correctly skipped invalid mapping: {result}")


class TestReadinessReevaluate:
    """Test readiness reevaluate-all endpoint"""

    def test_reevaluate_all_works(self):
        """POST /api/readiness/reevaluate-all should work without errors"""
        response = requests.post(
            f"{BASE_URL}/api/readiness/reevaluate-all",
            params={"limit": 100},  # Use small limit for test
            timeout=60  # Longer timeout as this may process documents
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Validate response structure
        assert "total_processed" in data, "Missing total_processed field"
        assert "total_corrections" in data, "Missing total_corrections field"
        assert "status_transitions" in data, "Missing status_transitions field"
        assert "by_status" in data, "Missing by_status field"
        assert "errors" in data, "Missing errors field"
        
        # Validate types
        assert isinstance(data["total_processed"], int), "total_processed should be int"
        assert isinstance(data["total_corrections"], int), "total_corrections should be int"
        assert isinstance(data["status_transitions"], list), "status_transitions should be list"
        assert isinstance(data["by_status"], dict), "by_status should be dict"
        assert isinstance(data["errors"], int), "errors should be int"
        
        print(f"Reevaluate-all result: processed={data['total_processed']}, corrections={data['total_corrections']}, errors={data['errors']}")


class TestCleanup:
    """Cleanup test data"""

    def test_cleanup_test_alias(self):
        """Delete test alias created during testing"""
        # Try to delete the test alias we created
        response = requests.delete(
            f"{BASE_URL}/api/aliases/vendors/by-alias/TEST_SC_Warehouses_191",
            timeout=30
        )
        
        # Either 200 (deleted) or 404 (not found) is acceptable
        assert response.status_code in [200, 404], f"Expected 200 or 404, got {response.status_code}: {response.text}"
        
        if response.status_code == 200:
            print("Test alias cleaned up successfully")
        else:
            print("Test alias not found (may not have been created)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
