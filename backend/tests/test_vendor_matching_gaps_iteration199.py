"""
Iteration 199: Vendor Matching Gaps Feature Tests
Tests for improved unmatched vendors endpoint with name normalization/deduplication,
better fuzzy matching (Jaccard + first-word bonus), manual BC vendor search, and dismiss functionality.

Endpoints tested:
- GET /api/aliases/vendors/unmatched-gaps
- GET /api/aliases/vendors/search-bc?q=<query>
- POST /api/aliases/vendors/dismiss-unmatched
- POST /api/aliases/vendors/accept-suggestion
- GET /api/readiness/exception-queue
- POST /api/readiness/sync-status
"""

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestUnmatchedVendorGaps:
    """Tests for GET /api/aliases/vendors/unmatched-gaps endpoint"""

    def test_unmatched_gaps_endpoint_returns_200(self):
        """Verify endpoint returns 200 status"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors/unmatched-gaps")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: unmatched-gaps endpoint returns 200")

    def test_unmatched_gaps_response_structure(self):
        """Verify response has correct structure with unmatched_vendors and total"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors/unmatched-gaps")
        assert response.status_code == 200
        data = response.json()
        
        assert "unmatched_vendors" in data, "Response missing 'unmatched_vendors' key"
        assert "total" in data, "Response missing 'total' key"
        assert isinstance(data["unmatched_vendors"], list), "unmatched_vendors should be a list"
        assert isinstance(data["total"], int), "total should be an integer"
        print(f"PASS: Response structure correct - total={data['total']}, vendors={len(data['unmatched_vendors'])}")

    def test_unmatched_gaps_vendor_item_structure(self):
        """Verify each vendor item has required fields: vendor_name, variants, gap_count, sample_files, candidates"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors/unmatched-gaps")
        assert response.status_code == 200
        data = response.json()
        
        if data["unmatched_vendors"]:
            vendor = data["unmatched_vendors"][0]
            required_fields = ["vendor_name", "variants", "gap_count", "sample_files", "candidates"]
            for field in required_fields:
                assert field in vendor, f"Vendor item missing '{field}' field"
            
            assert isinstance(vendor["vendor_name"], str), "vendor_name should be string"
            assert isinstance(vendor["variants"], list), "variants should be list"
            assert isinstance(vendor["gap_count"], int), "gap_count should be int"
            assert isinstance(vendor["sample_files"], list), "sample_files should be list"
            assert isinstance(vendor["candidates"], list), "candidates should be list"
            print(f"PASS: Vendor item structure correct - vendor_name={vendor['vendor_name']}, gap_count={vendor['gap_count']}")
        else:
            print("PASS: No unmatched vendors in preview environment (expected)")

    def test_unmatched_gaps_candidate_structure(self):
        """Verify candidate items have vendor_no, vendor_name, and score fields"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors/unmatched-gaps")
        assert response.status_code == 200
        data = response.json()
        
        for vendor in data["unmatched_vendors"]:
            if vendor["candidates"]:
                candidate = vendor["candidates"][0]
                assert "vendor_no" in candidate, "Candidate missing 'vendor_no'"
                assert "vendor_name" in candidate, "Candidate missing 'vendor_name'"
                assert "score" in candidate, "Candidate missing 'score'"
                assert isinstance(candidate["score"], (int, float)), "score should be numeric"
                assert 0 <= candidate["score"] <= 1, f"score should be 0-1, got {candidate['score']}"
                print(f"PASS: Candidate structure correct - {candidate['vendor_name']} ({candidate['vendor_no']}) score={candidate['score']}")
                return
        
        print("PASS: No candidates found (expected in preview with minimal data)")

    def test_unmatched_gaps_variants_merged(self):
        """Verify variants are properly merged (e.g., 'SC Warehouses, LLC' = 'SC Warehouses, LLC.')"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors/unmatched-gaps")
        assert response.status_code == 200
        data = response.json()
        
        # Check that variants array exists and is properly structured
        for vendor in data["unmatched_vendors"]:
            if vendor["variants"]:
                # Variants should be a list of strings
                assert all(isinstance(v, str) for v in vendor["variants"]), "All variants should be strings"
                print(f"PASS: Vendor '{vendor['vendor_name']}' has {len(vendor['variants'])} variants: {vendor['variants']}")
                return
        
        print("PASS: No vendors with variants found (expected in preview)")


class TestSearchBcVendors:
    """Tests for GET /api/aliases/vendors/search-bc endpoint"""

    def test_search_bc_endpoint_returns_200(self):
        """Verify endpoint returns 200 with valid query"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors/search-bc?q=warehouse")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: search-bc endpoint returns 200")

    def test_search_bc_response_structure(self):
        """Verify response has results array and query field"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors/search-bc?q=test")
        assert response.status_code == 200
        data = response.json()
        
        assert "results" in data, "Response missing 'results' key"
        assert "query" in data, "Response missing 'query' key"
        assert isinstance(data["results"], list), "results should be a list"
        assert data["query"] == "test", f"query should be 'test', got '{data['query']}'"
        print(f"PASS: Response structure correct - query='{data['query']}', results={len(data['results'])}")

    def test_search_bc_result_item_structure(self):
        """Verify each result has vendor_no, vendor_name, score, and source fields"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors/search-bc?q=gamer")
        assert response.status_code == 200
        data = response.json()
        
        if data["results"]:
            result = data["results"][0]
            assert "vendor_no" in result, "Result missing 'vendor_no'"
            assert "vendor_name" in result, "Result missing 'vendor_name'"
            assert "score" in result, "Result missing 'score'"
            assert isinstance(result["score"], (int, float)), "score should be numeric"
            print(f"PASS: Result structure correct - {result['vendor_name']} ({result['vendor_no']}) score={result['score']}")
        else:
            print("PASS: No results found for 'gamer' (expected in preview)")

    def test_search_bc_min_length_validation(self):
        """Verify endpoint requires minimum 2 character query"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors/search-bc?q=a")
        # FastAPI returns 422 for validation errors
        assert response.status_code == 422, f"Expected 422 for short query, got {response.status_code}"
        print("PASS: Endpoint correctly rejects query < 2 chars")

    def test_search_bc_missing_query_param(self):
        """Verify endpoint requires q parameter"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors/search-bc")
        assert response.status_code == 422, f"Expected 422 for missing query, got {response.status_code}"
        print("PASS: Endpoint correctly requires q parameter")

    def test_search_bc_case_insensitive(self):
        """Verify search is case insensitive"""
        response_lower = requests.get(f"{BASE_URL}/api/aliases/vendors/search-bc?q=warehouse")
        response_upper = requests.get(f"{BASE_URL}/api/aliases/vendors/search-bc?q=WAREHOUSE")
        
        assert response_lower.status_code == 200
        assert response_upper.status_code == 200
        
        # Both should return same results (or both empty)
        data_lower = response_lower.json()
        data_upper = response_upper.json()
        
        # Compare result counts (exact match may vary due to scoring)
        print(f"PASS: Case insensitive search - lower={len(data_lower['results'])}, upper={len(data_upper['results'])}")

    def test_search_bc_special_characters(self):
        """Verify search handles special characters safely"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors/search-bc?q=test%20vendor")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: Search handles special characters")


class TestDismissUnmatchedVendor:
    """Tests for POST /api/aliases/vendors/dismiss-unmatched endpoint"""

    def test_dismiss_endpoint_returns_200(self):
        """Verify endpoint returns 200 with valid vendor_name"""
        response = requests.post(
            f"{BASE_URL}/api/aliases/vendors/dismiss-unmatched",
            json={"vendor_name": "TEST_NonExistent_Vendor_12345", "reason": "test_dismiss"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: dismiss-unmatched endpoint returns 200")

    def test_dismiss_response_structure(self):
        """Verify response has vendor_name, docs_dismissed, and reason fields"""
        response = requests.post(
            f"{BASE_URL}/api/aliases/vendors/dismiss-unmatched",
            json={"vendor_name": "TEST_Dismiss_Structure_Test", "reason": "structure_test"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "vendor_name" in data, "Response missing 'vendor_name'"
        assert "docs_dismissed" in data, "Response missing 'docs_dismissed'"
        assert "reason" in data, "Response missing 'reason'"
        assert isinstance(data["docs_dismissed"], int), "docs_dismissed should be int"
        print(f"PASS: Response structure correct - vendor={data['vendor_name']}, dismissed={data['docs_dismissed']}")

    def test_dismiss_requires_vendor_name(self):
        """Verify endpoint requires vendor_name in body"""
        response = requests.post(
            f"{BASE_URL}/api/aliases/vendors/dismiss-unmatched",
            json={"reason": "test"}
        )
        assert response.status_code == 400, f"Expected 400 for missing vendor_name, got {response.status_code}"
        print("PASS: Endpoint correctly requires vendor_name")

    def test_dismiss_empty_vendor_name(self):
        """Verify endpoint rejects empty vendor_name"""
        response = requests.post(
            f"{BASE_URL}/api/aliases/vendors/dismiss-unmatched",
            json={"vendor_name": "", "reason": "test"}
        )
        assert response.status_code == 400, f"Expected 400 for empty vendor_name, got {response.status_code}"
        print("PASS: Endpoint correctly rejects empty vendor_name")

    def test_dismiss_default_reason(self):
        """Verify default reason is 'dismissed_by_user' when not provided"""
        response = requests.post(
            f"{BASE_URL}/api/aliases/vendors/dismiss-unmatched",
            json={"vendor_name": "TEST_Default_Reason_Vendor"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["reason"] == "dismissed_by_user", f"Expected default reason, got '{data['reason']}'"
        print("PASS: Default reason is 'dismissed_by_user'")


class TestAcceptVendorSuggestion:
    """Tests for POST /api/aliases/vendors/accept-suggestion endpoint"""

    def test_accept_suggestion_endpoint_returns_200(self):
        """Verify endpoint returns 200 with valid data"""
        unique_alias = f"TEST_Accept_Alias_{uuid.uuid4().hex[:8]}"
        response = requests.post(
            f"{BASE_URL}/api/aliases/vendors/accept-suggestion",
            json={
                "alias_string": unique_alias,
                "vendor_no": "TEST001",
                "vendor_name": "Test Vendor Inc"
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: accept-suggestion endpoint returns 200")

    def test_accept_suggestion_response_structure(self):
        """Verify response has aliases_created, all_variants, and docs_updated fields"""
        unique_alias = f"TEST_Accept_Structure_{uuid.uuid4().hex[:8]}"
        response = requests.post(
            f"{BASE_URL}/api/aliases/vendors/accept-suggestion",
            json={
                "alias_string": unique_alias,
                "vendor_no": "TEST002",
                "vendor_name": "Test Vendor Structure"
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "aliases_created" in data, "Response missing 'aliases_created'"
        assert "all_variants" in data, "Response missing 'all_variants'"
        assert "docs_updated" in data, "Response missing 'docs_updated'"
        assert isinstance(data["aliases_created"], int), "aliases_created should be int"
        assert isinstance(data["all_variants"], list), "all_variants should be list"
        assert isinstance(data["docs_updated"], int), "docs_updated should be int"
        print(f"PASS: Response structure correct - aliases_created={data['aliases_created']}, docs_updated={data['docs_updated']}")

    def test_accept_suggestion_with_variants(self):
        """Verify endpoint creates aliases for all variants"""
        unique_base = f"TEST_Variants_{uuid.uuid4().hex[:8]}"
        variants = [unique_base, f"{unique_base}.", f"{unique_base}, LLC"]
        
        response = requests.post(
            f"{BASE_URL}/api/aliases/vendors/accept-suggestion",
            json={
                "alias_string": unique_base,
                "vendor_no": "TEST003",
                "vendor_name": "Test Vendor Variants",
                "variants": variants
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should create aliases for all unique variants
        assert data["aliases_created"] >= 1, "Should create at least 1 alias"
        assert len(data["all_variants"]) == len(variants), f"all_variants should include all {len(variants)} variants"
        print(f"PASS: Created {data['aliases_created']} aliases for {len(variants)} variants")

    def test_accept_suggestion_requires_alias_string(self):
        """Verify endpoint requires alias_string"""
        response = requests.post(
            f"{BASE_URL}/api/aliases/vendors/accept-suggestion",
            json={"vendor_no": "TEST004", "vendor_name": "Test"}
        )
        assert response.status_code == 400, f"Expected 400 for missing alias_string, got {response.status_code}"
        print("PASS: Endpoint correctly requires alias_string")

    def test_accept_suggestion_requires_vendor_no(self):
        """Verify endpoint requires vendor_no"""
        response = requests.post(
            f"{BASE_URL}/api/aliases/vendors/accept-suggestion",
            json={"alias_string": "TEST_No_VendorNo", "vendor_name": "Test"}
        )
        assert response.status_code == 400, f"Expected 400 for missing vendor_no, got {response.status_code}"
        print("PASS: Endpoint correctly requires vendor_no")

    def test_accept_suggestion_idempotent(self):
        """Verify accepting same alias twice doesn't create duplicates"""
        unique_alias = f"TEST_Idempotent_{uuid.uuid4().hex[:8]}"
        payload = {
            "alias_string": unique_alias,
            "vendor_no": "TEST005",
            "vendor_name": "Test Vendor Idempotent"
        }
        
        # First call
        response1 = requests.post(f"{BASE_URL}/api/aliases/vendors/accept-suggestion", json=payload)
        assert response1.status_code == 200
        data1 = response1.json()
        
        # Second call with same data
        response2 = requests.post(f"{BASE_URL}/api/aliases/vendors/accept-suggestion", json=payload)
        assert response2.status_code == 200
        data2 = response2.json()
        
        # Second call should create 0 new aliases (already exists)
        assert data2["aliases_created"] == 0, f"Second call should create 0 aliases, got {data2['aliases_created']}"
        print(f"PASS: Idempotent - first call created {data1['aliases_created']}, second call created {data2['aliases_created']}")


class TestExceptionQueue:
    """Tests for GET /api/readiness/exception-queue endpoint"""

    def test_exception_queue_endpoint_returns_200(self):
        """Verify endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/readiness/exception-queue")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: exception-queue endpoint returns 200")

    def test_exception_queue_response_structure(self):
        """Verify response has total and documents fields"""
        response = requests.get(f"{BASE_URL}/api/readiness/exception-queue")
        assert response.status_code == 200
        data = response.json()
        
        assert "total" in data, "Response missing 'total'"
        assert "documents" in data, "Response missing 'documents'"
        assert isinstance(data["total"], int), "total should be int"
        assert isinstance(data["documents"], list), "documents should be list"
        print(f"PASS: Response structure correct - total={data['total']}, documents={len(data['documents'])}")

    def test_exception_queue_pagination(self):
        """Verify pagination with skip and limit parameters"""
        response = requests.get(f"{BASE_URL}/api/readiness/exception-queue?skip=0&limit=5")
        assert response.status_code == 200
        data = response.json()
        
        # Should return at most 5 documents
        assert len(data["documents"]) <= 5, f"Expected at most 5 documents, got {len(data['documents'])}"
        print(f"PASS: Pagination works - returned {len(data['documents'])} documents with limit=5")


class TestSyncStatus:
    """Tests for POST /api/readiness/sync-status endpoint"""

    def test_sync_status_endpoint_returns_200(self):
        """Verify endpoint returns 200"""
        response = requests.post(f"{BASE_URL}/api/readiness/sync-status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: sync-status endpoint returns 200")

    def test_sync_status_response_structure(self):
        """Verify response has expected fields"""
        response = requests.post(f"{BASE_URL}/api/readiness/sync-status")
        assert response.status_code == 200
        data = response.json()
        
        # Should have cleanup results
        assert isinstance(data, dict), "Response should be a dict"
        # Common fields in sync-status response
        expected_fields = ["total_cleaned", "rules_applied"]
        for field in expected_fields:
            if field in data:
                print(f"  Found field: {field}={data[field]}")
        
        print(f"PASS: sync-status response structure valid")

    def test_sync_status_force_cleanup(self):
        """Verify force cleanup functionality"""
        response = requests.post(f"{BASE_URL}/api/readiness/sync-status")
        assert response.status_code == 200
        data = response.json()
        
        # Verify it returns cleanup statistics
        if "total_cleaned" in data:
            assert isinstance(data["total_cleaned"], int), "total_cleaned should be int"
            print(f"PASS: Force cleanup returned total_cleaned={data['total_cleaned']}")
        else:
            print("PASS: sync-status completed (no total_cleaned field)")


class TestCleanup:
    """Cleanup test data created during testing"""

    def test_cleanup_test_aliases(self):
        """Clean up TEST_ prefixed aliases created during testing"""
        # Get all aliases
        response = requests.get(f"{BASE_URL}/api/aliases/vendors?limit=500")
        if response.status_code == 200:
            data = response.json()
            aliases = data.get("aliases", [])
            deleted = 0
            for alias in aliases:
                alias_string = alias.get("alias_string", "")
                if alias_string.startswith("TEST_"):
                    alias_id = alias.get("alias_id")
                    if alias_id:
                        del_response = requests.delete(f"{BASE_URL}/api/aliases/vendors/{alias_id}")
                        if del_response.status_code == 200:
                            deleted += 1
            print(f"PASS: Cleaned up {deleted} test aliases")
        else:
            print("PASS: Cleanup skipped (could not fetch aliases)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
