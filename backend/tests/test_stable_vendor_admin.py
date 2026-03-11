"""
Test Suite for Stable Vendor Admin Page Feature
Tests all admin page-specific API endpoints:
- GET /api/stable-vendor/vendors - vendor list with filters/sort
- GET /api/stable-vendor/vendors/{vendor_no} - vendor detail
- POST /api/stable-vendor/vendors/{vendor_no}/override - apply override
- POST /api/stable-vendor/vendors/{vendor_no}/clear-override - clear override
- GET /api/stable-vendor/vendors/{vendor_no}/history - override audit trail
- Effective status computation
- Safety: override does NOT bypass hard document safety controls
"""

import pytest
import requests
import os
import time
from urllib.parse import quote

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# ============================================================================
# Vendor List Endpoint Tests
# ============================================================================

class TestVendorListEndpoint:
    """Test GET /api/stable-vendor/vendors endpoint"""
    
    def test_vendor_list_returns_vendors(self):
        """GET /api/stable-vendor/vendors returns vendor list with total count"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "vendors" in data, "Response missing 'vendors' key"
        assert "total" in data, "Response missing 'total' key"
        assert isinstance(data["vendors"], list), "vendors should be a list"
        assert isinstance(data["total"], int), "total should be integer"
        
        # Should have 17 vendors per problem statement
        print(f"PASS: GET /api/stable-vendor/vendors returned {data['total']} vendors")
    
    def test_vendor_list_enriched_fields(self):
        """Vendor list returns enriched fields for each vendor"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors?limit=5")
        
        assert response.status_code == 200
        data = response.json()
        
        if data["vendors"]:
            vendor = data["vendors"][0]
            # Check required enriched fields
            expected_fields = [
                "vendor_name", "effective_status", "system_status",
                "stable_vendor_score", "has_manual_override"
            ]
            for field in expected_fields:
                assert field in vendor, f"Vendor missing field: {field}"
            
            # effective_status should be one of stable, watch, unstable
            assert vendor["effective_status"] in ["stable", "watch", "unstable"], \
                f"Invalid effective_status: {vendor['effective_status']}"
            
            print(f"PASS: Vendor '{vendor.get('vendor_name', 'N/A')[:30]}' has all enriched fields")
        else:
            print("INFO: No vendors to test enriched fields")
    
    def test_vendor_list_search_filter(self):
        """Search by vendor name filters results"""
        # First get a vendor name to search for
        all_vendors = requests.get(f"{BASE_URL}/api/stable-vendor/vendors?limit=100").json()
        
        if all_vendors.get("vendors"):
            # Find a vendor with 'Cargo' in name or use first vendor's partial name
            test_vendor = None
            for v in all_vendors["vendors"]:
                if "Cargo" in (v.get("vendor_name") or ""):
                    test_vendor = v
                    break
            
            if not test_vendor and all_vendors["vendors"]:
                test_vendor = all_vendors["vendors"][0]
                search_term = test_vendor.get("vendor_name", "")[:5]
            else:
                search_term = "Cargo"
            
            # Now search
            response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors?search={search_term}")
            assert response.status_code == 200
            
            data = response.json()
            assert data["total"] <= all_vendors["total"], "Search should filter results"
            
            # All returned vendors should match search
            for v in data["vendors"]:
                name = (v.get("vendor_name") or "").lower()
                no = (v.get("vendor_no") or "").lower()
                assert search_term.lower() in name or search_term.lower() in no, \
                    f"Vendor '{name}' does not match search '{search_term}'"
            
            print(f"PASS: Search '{search_term}' returned {data['total']} matching vendors")
        else:
            pytest.skip("No vendors available to test search")
    
    def test_vendor_list_status_filter_unstable(self):
        """Status filter=unstable filters by effective status"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors?status=unstable")
        
        assert response.status_code == 200
        data = response.json()
        
        # All returned vendors should have unstable effective status
        for v in data["vendors"]:
            assert v["effective_status"] == "unstable", \
                f"Expected unstable, got {v['effective_status']} for {v.get('vendor_name')}"
        
        print(f"PASS: Status filter 'unstable' returned {data['total']} vendors")
    
    def test_vendor_list_status_filter_overridden(self):
        """Status filter=overridden shows only vendors with manual override"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors?status=overridden")
        
        assert response.status_code == 200
        data = response.json()
        
        # All should have manual override
        for v in data["vendors"]:
            assert v.get("has_manual_override") == True, \
                f"Vendor {v.get('vendor_name')} has no override but in overridden filter"
        
        print(f"PASS: Status filter 'overridden' returned {data['total']} vendors with overrides")
    
    def test_vendor_list_sort_by_score(self):
        """Sorting by stable_vendor_score works"""
        # Sort desc
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors?sort_by=stable_vendor_score&sort_dir=-1&limit=10")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["vendors"]) >= 2:
            scores = [v.get("stable_vendor_score", 0) for v in data["vendors"]]
            assert scores == sorted(scores, reverse=True), "Scores should be sorted descending"
            print(f"PASS: Vendors sorted by score DESC: {scores[:5]}")
        else:
            print("INFO: Not enough vendors to test sorting")


# ============================================================================
# Vendor Detail Endpoint Tests
# ============================================================================

class TestVendorDetailEndpoint:
    """Test GET /api/stable-vendor/vendors/{vendor_no} endpoint"""
    
    def _get_test_vendor(self):
        """Get a vendor to test with"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors?limit=1")
        if response.status_code == 200:
            vendors = response.json().get("vendors", [])
            if vendors:
                return vendors[0]
        return None
    
    def test_vendor_detail_returns_full_data(self):
        """Vendor detail returns all required sections"""
        vendor = self._get_test_vendor()
        if not vendor:
            pytest.skip("No vendors available")
        
        vendor_id = vendor.get("vendor_no") or vendor.get("vendor_name")
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Check all required sections per problem statement
        assert "stability_checks" in data, "Missing stability_checks"
        assert "stability_reasons" in data, "Missing stability_reasons"
        assert "routing_impact" in data, "Missing routing_impact"
        assert "quality_signals" in data, "Missing quality_signals"
        assert "override_history" in data, "Missing override_history"
        
        # Check computed fields
        assert "effective_status" in data, "Missing effective_status"
        assert "system_status" in data, "Missing system_status"
        
        print(f"PASS: Vendor detail for '{vendor_id[:30]}' has all required sections")
    
    def test_vendor_detail_stability_checks_structure(self):
        """Stability checks have proper structure"""
        vendor = self._get_test_vendor()
        if not vendor:
            pytest.skip("No vendors available")
        
        vendor_id = vendor.get("vendor_no") or vendor.get("vendor_name")
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}")
        
        assert response.status_code == 200
        data = response.json()
        
        checks = data.get("stability_checks", [])
        if checks:
            for check in checks:
                assert "check" in check, "Check missing 'check' field"
                assert "passed" in check, "Check missing 'passed' field"
                assert "value" in check, "Check missing 'value' field"
                assert isinstance(check["passed"], bool), "'passed' should be boolean"
            
            print(f"PASS: {len(checks)} stability checks have proper structure")
        else:
            print("INFO: No stability checks (vendor may have no profile)")
    
    def test_vendor_detail_routing_impact_structure(self):
        """Routing impact has proper structure"""
        vendor = self._get_test_vendor()
        if not vendor:
            pytest.skip("No vendors available")
        
        vendor_id = vendor.get("vendor_no") or vendor.get("vendor_name")
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}")
        
        assert response.status_code == 200
        data = response.json()
        
        ri = data.get("routing_impact", {})
        assert "auto_ready_eligible" in ri, "Missing auto_ready_eligible"
        assert "low_priority_eligible" in ri, "Missing low_priority_eligible"
        assert "blocked_by" in ri, "Missing blocked_by"
        
        assert isinstance(ri["auto_ready_eligible"], bool)
        assert isinstance(ri["low_priority_eligible"], bool)
        assert isinstance(ri["blocked_by"], list)
        
        print(f"PASS: Routing impact - auto_ready={ri['auto_ready_eligible']}, blocked_by={len(ri['blocked_by'])} items")
    
    def test_vendor_detail_404_not_found(self):
        """Non-existent vendor returns 404"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors/NONEXISTENT_VENDOR_XYZ123")
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Non-existent vendor returns 404")


# ============================================================================
# Override Action Tests
# ============================================================================

class TestOverrideActions:
    """Test override apply/clear endpoints"""
    
    def _get_test_vendor(self):
        """Get a vendor to test with"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors?limit=1")
        if response.status_code == 200:
            vendors = response.json().get("vendors", [])
            if vendors:
                return vendors[0]
        return None
    
    def test_apply_force_watch_override(self):
        """POST /api/stable-vendor/vendors/{vendor_no}/override applies override"""
        vendor = self._get_test_vendor()
        if not vendor:
            pytest.skip("No vendors available")
        
        vendor_id = vendor.get("vendor_no") or vendor.get("vendor_name")
        
        # Apply force_watch override
        payload = {
            "status": "force_watch",
            "reason": "Testing override via pytest",
            "note": "Automated test - will be cleared",
            "actor": "pytest_admin"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/override",
            json=payload
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "new_status" in data, "Response missing new_status"
        assert data["new_status"] == "watch", f"Expected watch, got {data['new_status']}"
        assert "old_status" in data, "Response missing old_status"
        
        print(f"PASS: Override applied - {data['old_status']} -> {data['new_status']}")
        
        # Verify via GET
        detail = requests.get(f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}").json()
        assert detail["effective_status"] == "watch", "Effective status not updated"
        assert detail.get("has_manual_override") == True, "Override not flagged"
        
        print("PASS: Override verified in vendor detail")
    
    def test_clear_override(self):
        """POST /api/stable-vendor/vendors/{vendor_no}/clear-override clears override"""
        vendor = self._get_test_vendor()
        if not vendor:
            pytest.skip("No vendors available")
        
        vendor_id = vendor.get("vendor_no") or vendor.get("vendor_name")
        
        # First apply an override
        requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/override",
            json={"status": "force_unstable", "reason": "Test before clear", "actor": "pytest"}
        )
        
        # Now clear it
        response = requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/clear-override",
            json={"reason": "Clearing test override", "actor": "pytest_admin"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "new_status" in data, "Response missing new_status"
        # After clearing, should revert to system status (unstable since vendors don't meet thresholds)
        assert data["new_status"] in ["stable", "unstable"], f"Unexpected status: {data['new_status']}"
        
        print(f"PASS: Override cleared - reverted to system status: {data['new_status']}")
        
        # Verify via GET
        detail = requests.get(f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}").json()
        assert detail.get("has_manual_override") != True or detail.get("manual_override_status") == "none"
        
        print("PASS: Clear override verified")
    
    def test_override_creates_history(self):
        """Override actions create history entries"""
        vendor = self._get_test_vendor()
        if not vendor:
            pytest.skip("No vendors available")
        
        vendor_id = vendor.get("vendor_no") or vendor.get("vendor_name")
        
        # Apply override
        requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/override",
            json={"status": "force_stable", "reason": "Test history", "actor": "pytest_history_test"}
        )
        
        # Get history
        response = requests.get(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/history"
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        history = response.json()
        assert isinstance(history, list), "History should be a list"
        
        if history:
            latest = history[0]
            assert "action" in latest, "History entry missing action"
            assert "timestamp" in latest, "History entry missing timestamp"
            assert "actor" in latest, "History entry missing actor"
            assert "vendor_no" in latest, "History entry missing vendor_no"
            
            print(f"PASS: History has {len(history)} entries, latest: {latest['action']} by {latest['actor']}")
        else:
            print("INFO: No history entries (may be first test)")
        
        # Clean up - clear override
        requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/clear-override",
            json={"reason": "Cleanup", "actor": "pytest"}
        )
    
    def test_override_invalid_status_rejected(self):
        """Invalid override status returns 400"""
        vendor = self._get_test_vendor()
        if not vendor:
            pytest.skip("No vendors available")
        
        vendor_id = vendor.get("vendor_no") or vendor.get("vendor_name")
        
        response = requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/override",
            json={"status": "invalid_status", "reason": "test", "actor": "pytest"}
        )
        
        assert response.status_code == 400, f"Expected 400 for invalid status, got {response.status_code}"
        print("PASS: Invalid override status rejected with 400")


# ============================================================================
# Override History Endpoint Tests
# ============================================================================

class TestOverrideHistory:
    """Test GET /api/stable-vendor/vendors/{vendor_no}/history endpoint"""
    
    def test_history_endpoint_returns_list(self):
        """History endpoint returns list of entries"""
        # Get a vendor
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors?limit=1")
        if response.status_code != 200 or not response.json().get("vendors"):
            pytest.skip("No vendors available")
        
        vendor = response.json()["vendors"][0]
        vendor_id = vendor.get("vendor_no") or vendor.get("vendor_name")
        
        response = requests.get(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/history"
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        history = response.json()
        assert isinstance(history, list), "History should be a list"
        
        print(f"PASS: History endpoint returned {len(history)} entries")


# ============================================================================
# Effective Status Computation Tests
# ============================================================================

class TestEffectiveStatusComputation:
    """Test that effective status is computed correctly"""
    
    def test_force_stable_gives_stable_status(self):
        """force_stable override results in effective status = stable"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors?limit=1")
        if response.status_code != 200 or not response.json().get("vendors"):
            pytest.skip("No vendors available")
        
        vendor = response.json()["vendors"][0]
        vendor_id = vendor.get("vendor_no") or vendor.get("vendor_name")
        
        # Apply force_stable
        requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/override",
            json={"status": "force_stable", "reason": "Test effective status", "actor": "pytest"}
        )
        
        # Check effective status
        detail = requests.get(f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}").json()
        assert detail["effective_status"] == "stable", \
            f"Expected stable, got {detail['effective_status']}"
        
        print("PASS: force_stable override results in effective_status=stable")
        
        # Cleanup
        requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/clear-override",
            json={"reason": "Cleanup", "actor": "pytest"}
        )
    
    def test_force_watch_gives_watch_status(self):
        """force_watch override results in effective status = watch"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors?limit=1")
        if response.status_code != 200 or not response.json().get("vendors"):
            pytest.skip("No vendors available")
        
        vendor = response.json()["vendors"][0]
        vendor_id = vendor.get("vendor_no") or vendor.get("vendor_name")
        
        # Apply force_watch
        requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/override",
            json={"status": "force_watch", "reason": "Test effective status", "actor": "pytest"}
        )
        
        # Check effective status
        detail = requests.get(f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}").json()
        assert detail["effective_status"] == "watch", \
            f"Expected watch, got {detail['effective_status']}"
        
        print("PASS: force_watch override results in effective_status=watch")
        
        # Cleanup
        requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/clear-override",
            json={"reason": "Cleanup", "actor": "pytest"}
        )
    
    def test_force_unstable_gives_unstable_status(self):
        """force_unstable override results in effective status = unstable"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors?limit=1")
        if response.status_code != 200 or not response.json().get("vendors"):
            pytest.skip("No vendors available")
        
        vendor = response.json()["vendors"][0]
        vendor_id = vendor.get("vendor_no") or vendor.get("vendor_name")
        
        # Apply force_unstable
        requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/override",
            json={"status": "force_unstable", "reason": "Test effective status", "actor": "pytest"}
        )
        
        # Check effective status
        detail = requests.get(f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}").json()
        assert detail["effective_status"] == "unstable", \
            f"Expected unstable, got {detail['effective_status']}"
        
        print("PASS: force_unstable override results in effective_status=unstable")
        
        # Cleanup
        requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/clear-override",
            json={"reason": "Cleanup", "actor": "pytest"}
        )
    
    def test_no_override_uses_system_status(self):
        """With no override, effective status equals system-derived status"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors?limit=1")
        if response.status_code != 200 or not response.json().get("vendors"):
            pytest.skip("No vendors available")
        
        vendor = response.json()["vendors"][0]
        vendor_id = vendor.get("vendor_no") or vendor.get("vendor_name")
        
        # Clear any existing override
        requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/clear-override",
            json={"reason": "Ensure no override", "actor": "pytest"}
        )
        
        # Check that effective = system
        detail = requests.get(f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}").json()
        assert detail["effective_status"] == detail["system_status"], \
            f"Expected effective={detail['system_status']}, got {detail['effective_status']}"
        
        print(f"PASS: No override - effective_status equals system_status={detail['system_status']}")


# ============================================================================
# Safety Tests - Override Does NOT Bypass Hard Document Safety Controls
# ============================================================================

class TestSafetyConstraints:
    """Test that overrides don't bypass hard document safety controls"""
    
    def test_document_with_validation_failure_still_manual_review(self):
        """
        Even with force_stable vendor, a document with validation failure
        should still route to manual_review (override affects vendor trust, not doc safety)
        """
        # Get a vendor
        vendors_response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors?limit=1")
        if vendors_response.status_code != 200 or not vendors_response.json().get("vendors"):
            pytest.skip("No vendors available")
        
        vendor = vendors_response.json()["vendors"][0]
        vendor_id = vendor.get("vendor_no") or vendor.get("vendor_name")
        
        # Apply force_stable to vendor
        requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/override",
            json={"status": "force_stable", "reason": "Test safety bypass", "actor": "pytest"}
        )
        
        # Get a document from this vendor that has validation issues
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=50")
        if docs_response.status_code != 200:
            print("INFO: Could not fetch documents to test safety")
            return
        
        docs = docs_response.json().get("documents", [])
        test_doc = None
        
        for doc in docs:
            doc_vendor = doc.get("vendor_raw") or doc.get("matched_vendor_name") or doc.get("vendor_canonical")
            if doc_vendor and vendor_id.lower() in doc_vendor.lower():
                val_state = doc.get("validation_state", "unknown")
                if val_state in ["fail", "failed", "error"]:
                    test_doc = doc
                    break
        
        if test_doc:
            # Evaluate this document
            doc_id = test_doc["id"]
            eval_response = requests.post(f"{BASE_URL}/api/stable-vendor/evaluate-document/{doc_id}")
            
            if eval_response.status_code == 200:
                result = eval_response.json()
                # Safety: validation failure should NOT be bypassed
                if "Validation failed" in str(result.get("reasons", [])):
                    assert result["routing"] == "manual_review", \
                        f"Document with validation failure should route to manual_review, got {result['routing']}"
                    print("PASS: Document with validation failure still routes to manual_review despite force_stable vendor")
                else:
                    print(f"INFO: Document {doc_id} routing={result['routing']} (validation state may have changed)")
        else:
            print("INFO: No document with validation failure found to test safety bypass")
        
        # Cleanup
        requests.post(
            f"{BASE_URL}/api/stable-vendor/vendors/{quote(vendor_id, safe='')}/clear-override",
            json={"reason": "Cleanup", "actor": "pytest"}
        )


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
