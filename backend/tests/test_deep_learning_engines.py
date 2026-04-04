"""
Test Deep Learning Engines - 5 Advanced Intelligence Layers
Tests: extraction patterns, document similarity, self-correction, vendor maturity, predictive readiness
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestDeepLearningSummary:
    """Test GET /api/posting-patterns/deep-learning/summary - All 5 engine summaries"""
    
    def test_deep_learning_summary_returns_200(self):
        """Summary endpoint returns 200 with all 5 engine sections"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify all 5 engine sections exist
        assert "extraction_patterns" in data, "Missing extraction_patterns section"
        assert "document_similarity" in data, "Missing document_similarity section"
        assert "self_correction" in data, "Missing self_correction section"
        assert "vendor_maturity" in data, "Missing vendor_maturity section"
        assert "predictive_readiness" in data, "Missing predictive_readiness section"
        assert "generated_at" in data, "Missing generated_at timestamp"
        print(f"PASS: Deep learning summary has all 5 engine sections")
        
    def test_extraction_patterns_structure(self):
        """Extraction patterns section has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/summary")
        assert response.status_code == 200
        
        ep = response.json().get("extraction_patterns", {})
        assert "vendors_tracked" in ep, "Missing vendors_tracked"
        assert "top_vendors" in ep, "Missing top_vendors"
        assert isinstance(ep["vendors_tracked"], int), "vendors_tracked should be int"
        print(f"PASS: Extraction patterns - {ep['vendors_tracked']} vendors tracked")
        
    def test_vendor_maturity_structure(self):
        """Vendor maturity section has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/summary")
        assert response.status_code == 200
        
        vm = response.json().get("vendor_maturity", {})
        assert "levels" in vm, "Missing levels"
        assert "top_vendors" in vm, "Missing top_vendors"
        print(f"PASS: Vendor maturity levels: {vm.get('levels', {})}")
        
    def test_predictive_readiness_structure(self):
        """Predictive readiness section has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/summary")
        assert response.status_code == 200
        
        pr = response.json().get("predictive_readiness", {})
        assert "predictions_made" in pr, "Missing predictions_made"
        assert "breakdown" in pr, "Missing breakdown"
        print(f"PASS: Predictive readiness - {pr.get('predictions_made', 0)} predictions made")


class TestExtractionPatterns:
    """Test extraction pattern learning endpoints"""
    
    def test_extraction_patterns_for_known_vendor(self):
        """GET /api/posting-patterns/deep-learning/extraction-patterns/ANCH returns patterns"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/extraction-patterns/ANCH")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "vendor_no" in data, "Missing vendor_no"
        # Either has patterns or message saying no patterns
        if "message" not in data:
            assert "field_presence" in data or "field_reliability" in data, "Missing field data"
            print(f"PASS: ANCH has extraction patterns - {data.get('total_documents', 0)} docs learned")
        else:
            print(f"PASS: ANCH extraction patterns endpoint works - {data.get('message')}")
            
    def test_extraction_patterns_for_unknown_vendor(self):
        """GET /api/posting-patterns/deep-learning/extraction-patterns/UNKNOWN returns graceful message"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/extraction-patterns/UNKNOWN_VENDOR_XYZ")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "vendor_no" in data, "Missing vendor_no"
        assert "message" in data or "field_presence" in data, "Should have message or data"
        print(f"PASS: Unknown vendor returns graceful response")
        
    def test_extraction_hints_for_vendor(self):
        """GET /api/posting-patterns/deep-learning/extraction-hints/ANCH returns hints"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/extraction-hints/ANCH")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Hints may be empty if not enough data
        assert isinstance(data, dict), "Should return dict"
        if data:
            # If hints exist, check structure
            if "expected_fields" in data:
                assert isinstance(data["expected_fields"], list)
            if "reliable_fields" in data:
                assert isinstance(data["reliable_fields"], list)
        print(f"PASS: Extraction hints endpoint works - {len(data)} hint categories")


class TestSelfCorrection:
    """Test self-correction audit endpoints"""
    
    def test_run_self_correction_audit(self):
        """POST /api/posting-patterns/deep-learning/self-correction/run runs audit"""
        response = requests.post(
            f"{BASE_URL}/api/posting-patterns/deep-learning/self-correction/run",
            params={"sample_size": 20}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "audited" in data, "Missing audited count"
        assert "drifts" in data, "Missing drifts count"
        assert "drift_rate" in data, "Missing drift_rate"
        assert "message" in data, "Missing message"
        
        print(f"PASS: Self-correction audit - {data['audited']} audited, {data['drifts']} drifts ({data['drift_rate']*100:.1f}%)")
        
    def test_self_correction_history(self):
        """GET /api/posting-patterns/deep-learning/self-correction/history returns audit history"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/self-correction/history")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert isinstance(data, list), "Should return list of audits"
        
        if len(data) > 0:
            audit = data[0]
            assert "audited" in audit or "audit_id" in audit, "Audit should have audited count or audit_id"
            print(f"PASS: Self-correction history - {len(data)} audits found")
        else:
            print(f"PASS: Self-correction history endpoint works - no audits yet")


class TestVendorMaturity:
    """Test vendor maturity scoring endpoints"""
    
    def test_vendor_maturity_for_known_vendor(self):
        """GET /api/posting-patterns/deep-learning/vendor-maturity/ANCH returns maturity score"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/vendor-maturity/ANCH")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "vendor_no" in data, "Missing vendor_no"
        assert "maturity_level" in data, "Missing maturity_level"
        assert "composite_score" in data, "Missing composite_score"
        
        # Validate maturity level is one of expected values
        valid_levels = ["mastered", "proficient", "developing", "learning", "novice", "unknown"]
        assert data["maturity_level"] in valid_levels, f"Invalid maturity level: {data['maturity_level']}"
        
        # Validate composite score is 0-100
        assert 0 <= data["composite_score"] <= 100, f"Score out of range: {data['composite_score']}"
        
        # Check dimensions if present
        if "dimensions" in data and data["dimensions"]:
            expected_dims = ["volume", "accuracy", "consistency", "recency", "field_coverage", "error_rate"]
            for dim in expected_dims:
                if dim in data["dimensions"]:
                    assert "score" in data["dimensions"][dim], f"Missing score in {dim}"
                    
        print(f"PASS: ANCH maturity - {data['maturity_level']} (score: {data['composite_score']})")
        
    def test_vendor_maturity_for_unknown_vendor(self):
        """GET /api/posting-patterns/deep-learning/vendor-maturity/UNKNOWN returns unknown level"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/vendor-maturity/UNKNOWN_VENDOR_XYZ")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "vendor_no" in data, "Missing vendor_no"
        assert "maturity_level" in data, "Missing maturity_level"
        # Unknown vendor should have unknown level or message
        assert data["maturity_level"] == "unknown" or "message" in data
        print(f"PASS: Unknown vendor maturity returns graceful response")
        
    def test_compute_all_vendor_maturity(self):
        """POST /api/posting-patterns/deep-learning/vendor-maturity/compute-all starts computation"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/deep-learning/vendor-maturity/compute-all")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "message" in data, "Missing message"
        assert "async" in data or "computed" in data, "Should indicate async or computed"
        print(f"PASS: Compute all maturity - {data.get('message', 'started')}")


class TestDocumentSimilarity:
    """Test document similarity/fingerprint endpoints"""
    
    def test_deep_learning_summary_has_fingerprints(self):
        """Summary includes document fingerprint count"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/summary")
        assert response.status_code == 200
        
        ds = response.json().get("document_similarity", {})
        assert "fingerprints_stored" in ds, "Missing fingerprints_stored"
        assert isinstance(ds["fingerprints_stored"], int), "fingerprints_stored should be int"
        print(f"PASS: Document similarity - {ds['fingerprints_stored']} fingerprints stored")


class TestHealthAndIntegration:
    """Basic health and integration tests"""
    
    def test_health_endpoint(self):
        """Health endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.status_code}"
        print("PASS: Health endpoint OK")
        
    def test_learning_dashboard_loads(self):
        """Learning dashboard endpoint returns data"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "summary" in data, "Missing summary"
        print(f"PASS: Learning dashboard loads - {data['summary'].get('total_learning_events', 0)} events")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
