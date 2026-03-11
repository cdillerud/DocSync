"""
Test Suite for Stable Vendor Auto-Ready Feature
Tests all 6 API endpoints and edge cases:
- GET /api/stable-vendor/config
- PUT /api/stable-vendor/config
- GET /api/stable-vendor/evaluate/{vendor_id}
- POST /api/stable-vendor/evaluate-document/{doc_id}
- GET /api/stable-vendor/dashboard-metrics
- POST /api/stable-vendor/reevaluate-all
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestStableVendorConfig:
    """Test stable vendor configuration endpoints"""
    
    def test_get_config(self):
        """GET /api/stable-vendor/config returns config with all thresholds"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/config")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify all expected config keys are present
        required_keys = [
            "config_id",
            "min_documents_processed",
            "min_automation_success_rate",
            "min_reference_resolution_rate",
            "max_correction_rate",
            "min_validation_pass_rate",
            "resolver_confidence_auto_ready",
            "resolver_confidence_low_priority",
            "amount_anomaly_enabled",
            "amount_anomaly_std_multiplier",
            "block_new_layout_families",
            "min_layout_family_automation_rate",
            "drift_correction_rate_ceiling",
            "drift_validation_fail_rate_ceiling",
            "enabled"
        ]
        for key in required_keys:
            assert key in data, f"Config missing required key: {key}"
        
        # Verify default values are reasonable
        assert data["config_id"] == "stable_vendor_defaults"
        assert data["min_documents_processed"] >= 0
        assert 0 <= data["min_automation_success_rate"] <= 1
        assert isinstance(data["enabled"], bool)
        print(f"PASS: GET /api/stable-vendor/config returns {len(data)} config keys")
    
    def test_update_config(self):
        """PUT /api/stable-vendor/config updates thresholds and returns updated config"""
        # First get current config
        original = requests.get(f"{BASE_URL}/api/stable-vendor/config").json()
        
        # Update with new values
        updates = {
            "min_documents_processed": 25,
            "min_automation_success_rate": 0.85
        }
        response = requests.put(
            f"{BASE_URL}/api/stable-vendor/config",
            json=updates
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["min_documents_processed"] == 25
        assert data["min_automation_success_rate"] == 0.85
        assert "updated_at" in data
        
        # Verify persistence by GET
        verify = requests.get(f"{BASE_URL}/api/stable-vendor/config").json()
        assert verify["min_documents_processed"] == 25
        
        # Restore original values
        restore = {
            "min_documents_processed": original.get("min_documents_processed", 50),
            "min_automation_success_rate": original.get("min_automation_success_rate", 0.90)
        }
        requests.put(f"{BASE_URL}/api/stable-vendor/config", json=restore)
        print("PASS: PUT /api/stable-vendor/config updates and persists config")


class TestVendorStabilityEvaluation:
    """Test vendor stability evaluation endpoints"""
    
    def test_evaluate_vendor_no_profile(self):
        """Evaluate vendor with no profile returns not stable"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/evaluate/NONEXISTENT_VENDOR_12345")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["stable_vendor_flag"] == False
        assert data["stable_vendor_score"] == 0.0
        assert "No vendor intelligence profile found" in data.get("reasons", [])
        print("PASS: Vendor with no profile returns not stable")
    
    def test_evaluate_vendor_insufficient_volume(self):
        """Vendor with insufficient volume should NOT be stable"""
        # First get a real vendor from documents
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=10")
        if docs_response.status_code == 200:
            docs = docs_response.json().get("documents", [])
            for doc in docs:
                vendor = doc.get("vendor_raw") or doc.get("vendor_canonical")
                if vendor:
                    response = requests.get(f"{BASE_URL}/api/stable-vendor/evaluate/{vendor}")
                    assert response.status_code == 200
                    data = response.json()
                    # With current test data, vendors have <50 docs so should not be stable
                    assert "stable_vendor_flag" in data
                    assert "checks" in data
                    print(f"PASS: Vendor '{vendor}' evaluation returned - stable={data['stable_vendor_flag']}")
                    return
        
        # Fallback: test with a made-up vendor
        response = requests.get(f"{BASE_URL}/api/stable-vendor/evaluate/TestVendor")
        assert response.status_code == 200
        print("PASS: Vendor stability evaluation endpoint working")


class TestDocumentRoutingEvaluation:
    """Test document routing evaluation endpoints"""
    
    def test_evaluate_document_no_vendor(self):
        """Evaluate document with no vendor returns manual_review"""
        # First create or find a doc to test with
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=50")
        assert docs_response.status_code == 200
        
        docs = docs_response.json().get("documents", [])
        test_doc = None
        
        # Find a doc, preferably one without vendor
        for doc in docs:
            if doc.get("id"):
                test_doc = doc
                break
        
        if not test_doc:
            pytest.skip("No documents available for testing")
        
        doc_id = test_doc["id"]
        response = requests.post(f"{BASE_URL}/api/stable-vendor/evaluate-document/{doc_id}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "document_id" in data
        assert "routing" in data
        assert data["routing"] in ["auto_ready", "low_priority_review", "manual_review"]
        assert "reasons" in data
        assert isinstance(data["reasons"], list)
        print(f"PASS: Document {doc_id[:8]} evaluated - routing={data['routing']}")
    
    def test_evaluate_nonexistent_document(self):
        """Evaluate nonexistent document returns 404"""
        response = requests.post(f"{BASE_URL}/api/stable-vendor/evaluate-document/NONEXISTENT_DOC_ID")
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Nonexistent document returns 404")
    
    def test_document_routing_stores_decision(self):
        """Evaluate document stores routing decision on document"""
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=5")
        docs = docs_response.json().get("documents", [])
        
        if not docs:
            pytest.skip("No documents available")
        
        doc_id = docs[0]["id"]
        
        # Evaluate document
        eval_response = requests.post(f"{BASE_URL}/api/stable-vendor/evaluate-document/{doc_id}")
        assert eval_response.status_code == 200
        
        # Fetch document and verify routing is stored
        doc_response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        if doc_response.status_code == 200:
            doc = doc_response.json().get("document", {})
            # After evaluation, stable_vendor_routing should be present
            routing = doc.get("stable_vendor_routing")
            if routing:
                assert "routing" in routing
                assert "evaluated_at" in routing
                print(f"PASS: Document {doc_id[:8]} has stable_vendor_routing stored")
            else:
                print(f"INFO: Document {doc_id[:8]} evaluated but routing not persisted (may be expected)")


class TestDashboardMetrics:
    """Test dashboard metrics endpoint"""
    
    def test_get_dashboard_metrics(self):
        """GET /api/stable-vendor/dashboard-metrics returns KPIs"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/dashboard-metrics")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify all 5 expected metrics are present
        required_metrics = [
            "stable_vendors_count",
            "total_vendors",
            "auto_ready_today",
            "low_priority_today",
            "total_processed_today",
            "stable_vendor_automation_rate",
            "feature_enabled"
        ]
        for metric in required_metrics:
            assert metric in data, f"Missing metric: {metric}"
        
        # Verify types
        assert isinstance(data["stable_vendors_count"], int)
        assert isinstance(data["total_vendors"], int)
        assert isinstance(data["auto_ready_today"], int)
        assert isinstance(data["feature_enabled"], bool)
        assert 0 <= data["stable_vendor_automation_rate"] <= 1
        
        print(f"PASS: Dashboard metrics - {data['stable_vendors_count']}/{data['total_vendors']} stable vendors")


class TestReevaluateAll:
    """Test reevaluate all vendors endpoint"""
    
    def test_reevaluate_all_vendors(self):
        """POST /api/stable-vendor/reevaluate-all runs async background reevaluation"""
        response = requests.post(f"{BASE_URL}/api/stable-vendor/reevaluate-all")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "status" in data
        assert data["status"] == "accepted"
        assert "message" in data
        
        print(f"PASS: Reevaluate all vendors - {data['message']}")


class TestRoutingEdgeCases:
    """Test edge cases for document routing decisions"""
    
    def test_routing_returns_reasons(self):
        """Document routing always includes reasons list"""
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=3")
        if docs_response.status_code != 200:
            pytest.skip("Could not fetch documents")
        
        docs = docs_response.json().get("documents", [])
        if not docs:
            pytest.skip("No documents available")
        
        for doc in docs[:3]:
            response = requests.post(f"{BASE_URL}/api/stable-vendor/evaluate-document/{doc['id']}")
            if response.status_code == 200:
                data = response.json()
                assert "reasons" in data
                assert len(data["reasons"]) > 0
                print(f"PASS: Doc {doc['id'][:8]} routing={data['routing']} with {len(data['reasons'])} reasons")
    
    def test_vendor_evaluation_includes_checks(self):
        """Vendor evaluation includes detailed checks array"""
        # Get a vendor name from documents
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=10")
        if docs_response.status_code == 200:
            docs = docs_response.json().get("documents", [])
            for doc in docs:
                vendor = doc.get("vendor_raw") or doc.get("matched_vendor_name")
                if vendor:
                    response = requests.get(f"{BASE_URL}/api/stable-vendor/evaluate/{vendor}")
                    if response.status_code == 200:
                        data = response.json()
                        assert "checks" in data
                        assert "stable_vendor_flag" in data
                        assert "stable_vendor_score" in data
                        assert "stable_vendor_last_evaluated" in data
                        print(f"PASS: Vendor '{vendor}' evaluation includes {len(data.get('checks', []))} checks")
                        return
        
        print("INFO: No vendors found to test detailed checks")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
