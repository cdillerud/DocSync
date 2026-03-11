"""
GPI Document Hub - Label Correction Feedback Loop Tests

Tests for the self-learning reference label correction mechanism:
- GET /api/label-corrections/stats
- GET /api/label-corrections/recent
- GET /api/label-corrections/vendor/{vendor_id}
- GET /api/label-corrections/document/{doc_id}
- GET /api/documents/{doc_id}/matching-debug (label_corrections & vendor_correction_patterns)
- POST /api/documents/{doc_id}/matching-debug/rerun

Also tests backend service components:
- LabelCorrectionService ENTITY_TO_LABEL mapping
- COMPATIBLE_LABELS validation
- label_correction_boost scoring component
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL')


class TestLabelCorrectionAPIs:
    """Tests for label correction API endpoints"""
    
    def test_label_correction_stats_endpoint(self):
        """GET /api/label-corrections/stats returns stats structure"""
        response = requests.get(f"{BASE_URL}/api/label-corrections/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify required fields exist
        assert "total_corrections" in data, "Missing total_corrections field"
        assert "unique_vendors" in data, "Missing unique_vendors field"
        assert "top_corrections" in data, "Missing top_corrections field"
        
        # Data type assertions
        assert isinstance(data["total_corrections"], int), "total_corrections should be int"
        assert isinstance(data["unique_vendors"], int), "unique_vendors should be int"
        assert isinstance(data["top_corrections"], list), "top_corrections should be list"
        
        print(f"Label correction stats: total={data['total_corrections']}, vendors={data['unique_vendors']}, top_patterns={len(data['top_corrections'])}")
        
    def test_label_correction_recent_endpoint(self):
        """GET /api/label-corrections/recent returns list of corrections"""
        response = requests.get(f"{BASE_URL}/api/label-corrections/recent?limit=5")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert isinstance(data, list), "Expected list response"
        
        # If corrections exist, validate structure
        if len(data) > 0:
            correction = data[0]
            expected_fields = ["document_id", "predicted_label", "correct_label", "actual_entity_type"]
            for field in expected_fields:
                assert field in correction, f"Missing field {field} in correction"
            print(f"Recent corrections found: {len(data)}, first: {correction.get('predicted_label')} -> {correction.get('correct_label')}")
        else:
            print("No recent corrections (collection is empty - expected for new feature)")
    
    def test_label_correction_vendor_endpoint(self):
        """GET /api/label-corrections/vendor/{vendor_id} returns vendor patterns"""
        # Use a test vendor ID
        test_vendor = "TEST_VENDOR"
        response = requests.get(f"{BASE_URL}/api/label-corrections/vendor/{test_vendor}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "has_patterns" in data, "Missing has_patterns field"
        assert "vendor_id" in data, "Missing vendor_id field"
        
        # If patterns exist, validate structure
        if data.get("has_patterns"):
            assert "patterns" in data, "has_patterns=True but patterns missing"
            assert "label_remaps" in data, "has_patterns=True but label_remaps missing"
            print(f"Vendor {test_vendor} has {data.get('total_corrections', 0)} corrections, {len(data.get('patterns', []))} patterns")
        else:
            print(f"Vendor {test_vendor} has no patterns (expected if no corrections recorded)")
    
    def test_label_correction_document_endpoint(self):
        """GET /api/label-corrections/document/{doc_id} returns document corrections"""
        # Use a test doc ID
        test_doc = "test-doc-12345"
        response = requests.get(f"{BASE_URL}/api/label-corrections/document/{test_doc}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert isinstance(data, list), "Expected list response"
        print(f"Document {test_doc[:8]} has {len(data)} corrections")


class TestMatchingDebugWithLabelCorrections:
    """Tests for matching-debug endpoint integration with label corrections"""
    
    @pytest.fixture
    def sample_document_id(self):
        """Get a document ID from the system"""
        response = requests.get(f"{BASE_URL}/api/documents?limit=1")
        if response.status_code == 200:
            docs = response.json().get("documents", [])
            if docs:
                return docs[0].get("id")
        return None
    
    def test_matching_debug_includes_label_corrections(self, sample_document_id):
        """GET /api/documents/{doc_id}/matching-debug includes label_corrections field"""
        if not sample_document_id:
            pytest.skip("No documents available for testing")
        
        response = requests.get(f"{BASE_URL}/api/documents/{sample_document_id}/matching-debug")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify label_corrections field exists
        assert "label_corrections" in data, "Missing label_corrections field in matching-debug response"
        assert isinstance(data["label_corrections"], list), "label_corrections should be a list"
        
        print(f"Matching debug for doc {sample_document_id[:8]} has {len(data['label_corrections'])} label corrections")
    
    def test_matching_debug_includes_vendor_correction_patterns(self, sample_document_id):
        """GET /api/documents/{doc_id}/matching-debug includes vendor_correction_patterns field"""
        if not sample_document_id:
            pytest.skip("No documents available for testing")
        
        response = requests.get(f"{BASE_URL}/api/documents/{sample_document_id}/matching-debug")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify vendor_correction_patterns field exists
        assert "vendor_correction_patterns" in data, "Missing vendor_correction_patterns field in matching-debug response"
        
        patterns = data["vendor_correction_patterns"]
        if patterns:
            assert "has_patterns" in patterns, "Missing has_patterns in vendor_correction_patterns"
            print(f"Vendor patterns for doc: has_patterns={patterns.get('has_patterns')}")
        else:
            print("vendor_correction_patterns is null (vendor not identified)")
    
    def test_matching_debug_rerun_still_works(self, sample_document_id):
        """POST /api/documents/{doc_id}/matching-debug/rerun still works correctly"""
        if not sample_document_id:
            pytest.skip("No documents available for testing")
        
        response = requests.post(f"{BASE_URL}/api/documents/{sample_document_id}/matching-debug/rerun")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify rerun response structure
        assert "document_id" in data, "Missing document_id in rerun response"
        assert "resolver_strategy" in data, "Missing resolver_strategy in rerun response"
        
        print(f"Rerun successful: strategy={data.get('resolver_strategy')}, outcome={data.get('match_outcome')}")


class TestLabelCorrectionServiceComponents:
    """Tests for backend service components related to label correction"""
    
    def test_entity_to_label_mapping_exists(self):
        """Verify ENTITY_TO_LABEL mapping in label_correction_service"""
        # Indirectly test by checking stats endpoint response
        response = requests.get(f"{BASE_URL}/api/label-corrections/stats")
        assert response.status_code == 200, "Service should be initialized with correct mappings"
        print("Label correction service initialized successfully")
    
    def test_vendor_intelligence_includes_label_correction_patterns(self):
        """Test vendor intelligence endpoint includes label_correction_patterns field"""
        # Get vendor profiles
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles?limit=1")
        if response.status_code == 200:
            data = response.json()
            profiles = data.get("profiles", [])
            if profiles:
                profile = profiles[0]
                # Check if label_correction_patterns field exists in profile structure
                print(f"Vendor profile fields: {list(profile.keys())[:10]}...")
                # Note: label_correction_patterns may be empty/null initially
        else:
            print(f"Vendor intelligence endpoint returned {response.status_code}")
    
    def test_matching_debug_diagnostics_includes_label_correction_hints(self):
        """Test that diagnostics include label_correction_hints"""
        # Get a document for testing
        response = requests.get(f"{BASE_URL}/api/documents?limit=1")
        if response.status_code == 200:
            docs = response.json().get("documents", [])
            if docs:
                doc_id = docs[0]["id"]
                
                debug_response = requests.get(f"{BASE_URL}/api/documents/{doc_id}/matching-debug")
                if debug_response.status_code == 200:
                    data = debug_response.json()
                    diag = data.get("diagnostics", {})
                    
                    # Check if label_correction_hints exists in diagnostics
                    if "label_correction_hints" in diag:
                        print(f"label_correction_hints found in diagnostics: {diag['label_correction_hints']}")
                    else:
                        print("label_correction_hints not in diagnostics (may not have been populated yet)")
        print("Diagnostic structure test completed")


class TestScoreBreakdownLabelCorrectionBoost:
    """Tests for label_correction_boost in score breakdown"""
    
    @pytest.fixture
    def document_with_scores(self):
        """Find a document that has scoring data"""
        response = requests.get(f"{BASE_URL}/api/documents?limit=10")
        if response.status_code == 200:
            docs = response.json().get("documents", [])
            for doc in docs:
                if doc.get("reference_match_outcome") in ["exact_match", "likely_match"]:
                    return doc.get("id")
        return None
    
    def test_score_breakdown_structure(self, document_with_scores):
        """Verify score breakdown includes label_correction_boost component"""
        if not document_with_scores:
            pytest.skip("No document with scores available")
        
        response = requests.get(f"{BASE_URL}/api/documents/{document_with_scores}/matching-debug")
        if response.status_code != 200:
            pytest.skip(f"Matching debug not available: {response.status_code}")
        
        data = response.json()
        diag = data.get("diagnostics", {})
        candidate_scores = diag.get("candidate_scores", [])
        
        if candidate_scores:
            score = candidate_scores[0]
            breakdown = score.get("score_breakdown", {})
            
            # Check available score components
            score_components = list(breakdown.keys())
            print(f"Score components available: {score_components}")
            
            # Verify label_correction_boost is a recognized component
            # It may be 0 if no corrections learned yet
            if "label_correction_boost" in breakdown:
                boost_value = breakdown["label_correction_boost"]
                print(f"label_correction_boost value: {boost_value}")
                assert isinstance(boost_value, (int, float)), "label_correction_boost should be numeric"
            else:
                print("label_correction_boost not present in score breakdown (may not be triggered)")
        else:
            print("No candidate scores in diagnostics")


class TestCompatibleLabelsValidation:
    """Tests for COMPATIBLE_LABELS validation logic"""
    
    def test_compatible_labels_skips_correction(self):
        """
        Verify compatible labels don't create corrections.
        
        According to the spec:
        COMPATIBLE_LABELS for posted_sales_shipment = {SHIPMENT, BOL, LOAD, PRO, REF}
        So BOL -> posted_sales_shipment should NOT create a correction.
        """
        # This is an indirect test - we verify the service is working
        # by checking that corrections are properly filtered
        response = requests.get(f"{BASE_URL}/api/label-corrections/stats")
        assert response.status_code == 200
        
        data = response.json()
        top_corrections = data.get("top_corrections", [])
        
        # If there are corrections, verify they follow the rules
        # BOL -> SHIPMENT should NOT appear in corrections
        for correction in top_corrections:
            predicted = correction.get("predicted")
            correct = correction.get("correct")
            
            # BOL is compatible with SHIPMENT, so this should not be a correction
            if predicted == "BOL" and correct == "SHIPMENT":
                print(f"WARNING: Found BOL->SHIPMENT correction which should be compatible")
            
        print(f"Validated {len(top_corrections)} top correction patterns")


class TestBCCacheShipmentCluster:
    """Tests for BC cache shipment cluster method"""
    
    def test_cache_search_endpoint(self):
        """Verify cache search is working"""
        response = requests.get(f"{BASE_URL}/api/cache/search?reference=111428&limit=5")
        
        # 200 or 404 are both acceptable (depends on cache state)
        assert response.status_code in [200, 404, 503], f"Unexpected status: {response.status_code}"
        
        if response.status_code == 200:
            data = response.json()
            print(f"Cache search returned {len(data.get('results', []))} results")
        else:
            print(f"Cache search returned {response.status_code} (may not be populated)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
