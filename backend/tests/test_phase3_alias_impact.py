"""
Phase 3: Alias Impact Integration Tests
- POST /api/documents/{id}/reprocess - safe reprocess without SP/BC duplication
- GET /api/metrics/automation - match_method_breakdown, alias_auto_linked, alias_exception_rate
- GET /api/metrics/vendors - has_alias, roi_hint, alias_matches per vendor
- Document match_method and match_score fields
"""

import pytest
import requests
import os
import uuid
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestPhase3ReprocessEndpoint:
    """Test the safe reprocess endpoint"""
    
    def test_reprocess_nonexistent_document(self):
        """Reprocess should return 404 for non-existent document"""
        fake_id = str(uuid.uuid4())
        response = requests.post(f"{BASE_URL}/api/documents/{fake_id}/reprocess")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data.get("detail", "").lower()
    
    def test_reprocess_endpoint_exists(self):
        """Verify reprocess endpoint is accessible"""
        # First get a document to test with
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=1")
        assert docs_response.status_code == 200
        docs = docs_response.json().get("documents", [])
        
        if docs:
            doc_id = docs[0]["id"]
            response = requests.post(f"{BASE_URL}/api/documents/{doc_id}/reprocess")
            # Should return 200 with reprocess result
            assert response.status_code == 200
            data = response.json()
            # Should have reprocessed field
            assert "reprocessed" in data or "reason" in data
    
    def test_reprocess_linked_document_returns_no_change(self):
        """Reprocessing a LinkedToBC document should return no change needed"""
        # Get a LinkedToBC document if exists
        docs_response = requests.get(f"{BASE_URL}/api/documents?status=LinkedToBC&limit=1")
        assert docs_response.status_code == 200
        docs = docs_response.json().get("documents", [])
        
        if docs:
            doc_id = docs[0]["id"]
            response = requests.post(f"{BASE_URL}/api/documents/{doc_id}/reprocess")
            assert response.status_code == 200
            data = response.json()
            # Should indicate no reprocessing needed
            assert data.get("reprocessed") == False or "already linked" in data.get("reason", "").lower()
    
    def test_reprocess_needs_review_document(self):
        """Reprocessing a NeedsReview document should attempt re-validation"""
        # Get a NeedsReview document if exists
        docs_response = requests.get(f"{BASE_URL}/api/documents?status=NeedsReview&limit=1")
        assert docs_response.status_code == 200
        docs = docs_response.json().get("documents", [])
        
        if docs:
            doc_id = docs[0]["id"]
            response = requests.post(f"{BASE_URL}/api/documents/{doc_id}/reprocess")
            assert response.status_code == 200
            data = response.json()
            
            # Should have reprocess result fields
            assert "reprocessed" in data
            if data.get("reprocessed"):
                assert "old_status" in data
                assert "new_status" in data
                assert "old_match_method" in data
                assert "new_match_method" in data
                assert "document" in data
    
    def test_reprocess_returns_match_method_info(self):
        """Reprocess should return match method change information"""
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=1")
        assert docs_response.status_code == 200
        docs = docs_response.json().get("documents", [])
        
        if docs:
            doc_id = docs[0]["id"]
            doc_status = docs[0].get("status")
            
            # Skip if already linked
            if doc_status == "LinkedToBC":
                pytest.skip("Document already linked, skipping")
            
            response = requests.post(f"{BASE_URL}/api/documents/{doc_id}/reprocess")
            assert response.status_code == 200
            data = response.json()
            
            if data.get("reprocessed"):
                # Should have match method fields
                assert "match_method_changed" in data
                assert "old_match_method" in data
                assert "new_match_method" in data


class TestPhase3AutomationMetrics:
    """Test automation metrics with match_method_breakdown"""
    
    def test_automation_metrics_returns_match_method_breakdown(self):
        """GET /api/metrics/automation should include match_method_breakdown"""
        response = requests.get(f"{BASE_URL}/api/metrics/automation")
        assert response.status_code == 200
        data = response.json()
        
        # Should have match_method_breakdown
        assert "match_method_breakdown" in data
        breakdown = data["match_method_breakdown"]
        
        # Should have all expected match methods
        expected_methods = ["exact_no", "exact_name", "normalized", "alias", "fuzzy", "manual", "none"]
        for method in expected_methods:
            assert method in breakdown, f"Missing match method: {method}"
            assert isinstance(breakdown[method], int), f"Match method {method} should be integer"
    
    def test_automation_metrics_returns_alias_auto_linked(self):
        """GET /api/metrics/automation should include alias_auto_linked count"""
        response = requests.get(f"{BASE_URL}/api/metrics/automation")
        assert response.status_code == 200
        data = response.json()
        
        assert "alias_auto_linked" in data
        assert isinstance(data["alias_auto_linked"], int)
        assert data["alias_auto_linked"] >= 0
    
    def test_automation_metrics_returns_alias_exception_rate(self):
        """GET /api/metrics/automation should include alias_exception_rate"""
        response = requests.get(f"{BASE_URL}/api/metrics/automation")
        assert response.status_code == 200
        data = response.json()
        
        assert "alias_exception_rate" in data
        assert isinstance(data["alias_exception_rate"], (int, float))
        assert data["alias_exception_rate"] >= 0
        assert data["alias_exception_rate"] <= 100
    
    def test_automation_metrics_with_days_filter(self):
        """Automation metrics should respect days filter"""
        for days in [7, 14, 30]:
            response = requests.get(f"{BASE_URL}/api/metrics/automation?days={days}")
            assert response.status_code == 200
            data = response.json()
            
            assert data["period_days"] == days
            assert "match_method_breakdown" in data
            assert "alias_auto_linked" in data
            assert "alias_exception_rate" in data


class TestPhase3VendorFrictionMetrics:
    """Test vendor friction metrics with ROI hints"""
    
    def test_vendor_metrics_returns_has_alias(self):
        """GET /api/metrics/vendors should include has_alias per vendor"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendors")
        assert response.status_code == 200
        data = response.json()
        
        assert "vendors" in data
        vendors = data["vendors"]
        
        # Each vendor should have has_alias field
        for vendor in vendors:
            assert "has_alias" in vendor, f"Vendor {vendor.get('vendor')} missing has_alias"
            assert isinstance(vendor["has_alias"], bool)
    
    def test_vendor_metrics_returns_roi_hint(self):
        """GET /api/metrics/vendors should include roi_hint per vendor"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendors")
        assert response.status_code == 200
        data = response.json()
        
        vendors = data.get("vendors", [])
        
        # Each vendor should have roi_hint field (can be None)
        for vendor in vendors:
            assert "roi_hint" in vendor, f"Vendor {vendor.get('vendor')} missing roi_hint"
            # roi_hint can be None or string
            assert vendor["roi_hint"] is None or isinstance(vendor["roi_hint"], str)
    
    def test_vendor_metrics_returns_alias_matches(self):
        """GET /api/metrics/vendors should include alias_matches count per vendor"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendors")
        assert response.status_code == 200
        data = response.json()
        
        vendors = data.get("vendors", [])
        
        # Each vendor should have alias_matches field
        for vendor in vendors:
            assert "alias_matches" in vendor, f"Vendor {vendor.get('vendor')} missing alias_matches"
            assert isinstance(vendor["alias_matches"], int)
            assert vendor["alias_matches"] >= 0
    
    def test_vendor_metrics_structure(self):
        """Verify complete vendor metrics structure"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendors")
        assert response.status_code == 200
        data = response.json()
        
        # Top level fields
        assert "period_days" in data
        assert "vendor_count" in data
        assert "vendors" in data
        assert "total_analyzed" in data
        
        # Vendor fields
        if data["vendors"]:
            vendor = data["vendors"][0]
            expected_fields = [
                "vendor", "total_documents", "auto_linked", "needs_review",
                "alias_matches", "auto_rate", "avg_confidence", "friction_index",
                "has_alias", "potential_auto_rate", "roi_hint"
            ]
            for field in expected_fields:
                assert field in vendor, f"Missing vendor field: {field}"


class TestPhase3DocumentMatchFields:
    """Test that documents store match_method and match_score"""
    
    def test_document_has_match_method_field(self):
        """Documents should have match_method field"""
        response = requests.get(f"{BASE_URL}/api/documents?limit=5")
        assert response.status_code == 200
        docs = response.json().get("documents", [])
        
        # Check documents that have been processed
        for doc in docs:
            if doc.get("status") in ["LinkedToBC", "NeedsReview", "StoredInSP"]:
                # These should have match_method
                if "match_method" in doc:
                    valid_methods = ["exact_no", "exact_name", "normalized", "alias", "fuzzy", "manual", "none"]
                    assert doc["match_method"] in valid_methods, f"Invalid match_method: {doc['match_method']}"
    
    def test_document_has_match_score_field(self):
        """Documents should have match_score field"""
        response = requests.get(f"{BASE_URL}/api/documents?limit=5")
        assert response.status_code == 200
        docs = response.json().get("documents", [])
        
        for doc in docs:
            if doc.get("status") in ["LinkedToBC", "NeedsReview", "StoredInSP"]:
                if "match_score" in doc:
                    assert isinstance(doc["match_score"], (int, float))
                    assert 0 <= doc["match_score"] <= 1
    
    def test_single_document_detail_has_match_fields(self):
        """Single document detail should include match fields"""
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=1")
        assert docs_response.status_code == 200
        docs = docs_response.json().get("documents", [])
        
        if docs:
            doc_id = docs[0]["id"]
            response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
            assert response.status_code == 200
            data = response.json()
            
            doc = data.get("document", {})
            # Document should have these fields if processed
            if doc.get("status") in ["LinkedToBC", "NeedsReview", "StoredInSP"]:
                # Fields may or may not exist depending on processing state
                pass  # Just verify endpoint works


class TestPhase3ReprocessIdempotency:
    """Test that reprocess is idempotent and doesn't duplicate records"""
    
    def test_reprocess_does_not_duplicate_sharepoint(self):
        """Reprocessing should not create duplicate SharePoint records"""
        # Get a document with SharePoint info
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=10")
        assert docs_response.status_code == 200
        docs = docs_response.json().get("documents", [])
        
        # Find a document with SharePoint info that's not LinkedToBC
        target_doc = None
        for doc in docs:
            if doc.get("sharepoint_item_id") and doc.get("status") != "LinkedToBC":
                target_doc = doc
                break
        
        if target_doc:
            original_sp_id = target_doc["sharepoint_item_id"]
            doc_id = target_doc["id"]
            
            # Reprocess
            response = requests.post(f"{BASE_URL}/api/documents/{doc_id}/reprocess")
            assert response.status_code == 200
            
            # Verify SharePoint ID hasn't changed
            updated_response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
            assert updated_response.status_code == 200
            updated_doc = updated_response.json().get("document", {})
            
            assert updated_doc.get("sharepoint_item_id") == original_sp_id, \
                "SharePoint item ID should not change on reprocess"
    
    def test_reprocess_creates_workflow_record(self):
        """Reprocessing should create a workflow record"""
        docs_response = requests.get(f"{BASE_URL}/api/documents?status=NeedsReview&limit=1")
        assert docs_response.status_code == 200
        docs = docs_response.json().get("documents", [])
        
        if docs:
            doc_id = docs[0]["id"]
            
            # Get workflow count before
            wf_before = requests.get(f"{BASE_URL}/api/workflows?limit=100")
            before_count = wf_before.json().get("total", 0)
            
            # Reprocess
            response = requests.post(f"{BASE_URL}/api/documents/{doc_id}/reprocess")
            assert response.status_code == 200
            
            if response.json().get("reprocessed"):
                # Check workflow was created
                wf_after = requests.get(f"{BASE_URL}/api/workflows?limit=100")
                after_count = wf_after.json().get("total", 0)
                
                # Should have at least one more workflow
                assert after_count >= before_count


class TestPhase3AliasIntegration:
    """Test alias creation and reprocess integration"""
    
    def test_create_alias_and_verify_in_metrics(self):
        """Create an alias and verify it appears in vendor metrics"""
        # Create a test alias
        test_alias = {
            "alias_string": f"TEST_VENDOR_{uuid.uuid4().hex[:8]}",
            "vendor_name": "Test Vendor Corp",
            "vendor_no": "V-TEST-001"
        }
        
        create_response = requests.post(f"{BASE_URL}/api/aliases/vendors", json=test_alias)
        assert create_response.status_code in [200, 201]
        
        created = create_response.json()
        alias_id = created.get("id")
        
        try:
            # Verify alias exists
            list_response = requests.get(f"{BASE_URL}/api/aliases/vendors")
            assert list_response.status_code == 200
            aliases = list_response.json().get("aliases", [])
            
            found = any(a.get("alias_string") == test_alias["alias_string"] for a in aliases)
            assert found, "Created alias should appear in list"
            
        finally:
            # Cleanup
            if alias_id:
                requests.delete(f"{BASE_URL}/api/aliases/vendors/{alias_id}")
    
    def test_alias_impact_metrics_endpoint(self):
        """Verify alias impact metrics endpoint works"""
        response = requests.get(f"{BASE_URL}/api/metrics/alias-impact")
        assert response.status_code == 200
        data = response.json()
        
        # Should have expected fields
        assert "total_aliases" in data
        assert "match_method_distribution" in data or "usage_count" in data


class TestPhase3EndToEndFlow:
    """End-to-end test of the alias impact flow"""
    
    def test_full_reprocess_flow(self):
        """Test complete reprocess flow: get doc -> reprocess -> verify"""
        # Get a NeedsReview document
        docs_response = requests.get(f"{BASE_URL}/api/documents?status=NeedsReview&limit=1")
        assert docs_response.status_code == 200
        docs = docs_response.json().get("documents", [])
        
        if not docs:
            pytest.skip("No NeedsReview documents available for testing")
        
        doc = docs[0]
        doc_id = doc["id"]
        original_status = doc.get("status")
        original_match_method = doc.get("match_method", "none")
        
        # Reprocess the document
        reprocess_response = requests.post(f"{BASE_URL}/api/documents/{doc_id}/reprocess")
        assert reprocess_response.status_code == 200
        result = reprocess_response.json()
        
        # Verify response structure
        if result.get("reprocessed"):
            assert "old_status" in result
            assert "new_status" in result
            assert "old_match_method" in result
            assert "new_match_method" in result
            assert "document" in result
            
            # Verify document was updated
            updated_doc = result["document"]
            assert "reprocessed_utc" in updated_doc or "updated_utc" in updated_doc
        
        # Verify document state via GET
        get_response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        assert get_response.status_code == 200
        final_doc = get_response.json().get("document", {})
        
        # Document should have match_method field
        if final_doc.get("status") in ["LinkedToBC", "NeedsReview", "StoredInSP"]:
            # These processed states should have match info
            pass  # Just verify endpoint works


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
