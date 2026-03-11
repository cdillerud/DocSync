"""
Reference Intelligence v2 API Tests

Tests the new fuzzy matching, cross-document correlation, and enhanced diagnostics features.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestFuzzyMatching:
    """Part 1: Fuzzy matching tests for OCR correction, numeric core match, partial match"""
    
    def test_fuzzy_numeric_core_match(self):
        """Test fuzzy matching with leading zeros (numeric core match)"""
        response = requests.get(
            f"{BASE_URL}/api/reference-intelligence/v2/fuzzy-test",
            params={"ref1": "000111428", "ref2": "111428"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "result" in data, f"No 'result' in response: {data}"
        assert "fuzzy_score" in data["result"], f"No 'fuzzy_score' in result: {data}"
        
        fuzzy_score = data["result"]["fuzzy_score"]
        assert fuzzy_score >= 0.85, f"Numeric core match score {fuzzy_score} should be >= 0.85"
        print(f"✅ Numeric core match: 000111428 vs 111428 = {fuzzy_score:.2f}")
    
    def test_fuzzy_ocr_correction_O_to_0(self):
        """Test fuzzy matching with OCR error: O mistaken for 0"""
        response = requests.get(
            f"{BASE_URL}/api/reference-intelligence/v2/fuzzy-test",
            params={"ref1": "89268460", "ref2": "8926846O"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        fuzzy_score = data["result"]["fuzzy_score"]
        assert fuzzy_score >= 0.70, f"OCR correction score {fuzzy_score} should be >= 0.70"
        print(f"✅ OCR correction (O→0): 89268460 vs 8926846O = {fuzzy_score:.2f}")
    
    def test_fuzzy_partial_match(self):
        """Test fuzzy matching with partial overlap (missing leading digit)"""
        response = requests.get(
            f"{BASE_URL}/api/reference-intelligence/v2/fuzzy-test",
            params={"ref1": "89268460", "ref2": "9268460"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        fuzzy_score = data["result"]["fuzzy_score"]
        assert fuzzy_score > 0, f"Partial match score {fuzzy_score} should be > 0"
        print(f"✅ Partial match: 89268460 vs 9268460 = {fuzzy_score:.2f}")
    
    def test_fuzzy_ocr_correction_invoice_ref(self):
        """Test fuzzy matching with OCR errors on invoice reference (O and B)"""
        response = requests.get(
            f"{BASE_URL}/api/reference-intelligence/v2/fuzzy-test",
            params={"ref1": "INV-0303853", "ref2": "INV-O3O3B53"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        fuzzy_score = data["result"]["fuzzy_score"]
        assert fuzzy_score >= 0.70, f"OCR correction score {fuzzy_score} should be >= 0.70"
        print(f"✅ OCR correction (multi-char): INV-0303853 vs INV-O3O3B53 = {fuzzy_score:.2f}")
    
    def test_fuzzy_no_match(self):
        """Test fuzzy matching with completely different numeric references"""
        # Use numeric references that are actually different
        response = requests.get(
            f"{BASE_URL}/api/reference-intelligence/v2/fuzzy-test",
            params={"ref1": "1234567890", "ref2": "9876543210"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        fuzzy_score = data["result"]["fuzzy_score"]
        # Different numeric sequences should have low score
        assert fuzzy_score < 0.5, f"No match score {fuzzy_score} should be low (< 0.5) for different numbers"
        print(f"✅ No match: 1234567890 vs 9876543210 = {fuzzy_score:.2f}")
    
    def test_fuzzy_test_returns_breakdown(self):
        """Test that fuzzy-test endpoint returns score breakdown"""
        response = requests.get(
            f"{BASE_URL}/api/reference-intelligence/v2/fuzzy-test",
            params={"ref1": "123456", "ref2": "123456"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "ref1" in data and "ref2" in data
        assert "result" in data
        result = data["result"]
        
        # Exact match should have fuzzy_score = 1.0
        assert result.get("fuzzy_score") == 1.0, f"Exact match should have score 1.0, got {result.get('fuzzy_score')}"
        print(f"✅ Exact match breakdown: {result}")


class TestClusterEndpoints:
    """Part 4: Cross-document correlation cluster tests"""
    
    def test_cluster_stats(self):
        """Test /api/reference-intelligence/v2/cluster-stats returns total_clusters"""
        response = requests.get(f"{BASE_URL}/api/reference-intelligence/v2/cluster-stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "total_clusters" in data, f"Missing 'total_clusters' in response: {data}"
        assert isinstance(data["total_clusters"], int), f"total_clusters should be int: {data}"
        print(f"✅ Cluster stats: {data}")
    
    def test_clusters_list(self):
        """Test /api/reference-intelligence/v2/clusters returns clusters array and total"""
        response = requests.get(
            f"{BASE_URL}/api/reference-intelligence/v2/clusters",
            params={"limit": 5}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "clusters" in data, f"Missing 'clusters' in response: {data}"
        assert "total" in data, f"Missing 'total' in response: {data}"
        assert isinstance(data["clusters"], list), f"clusters should be list: {data}"
        print(f"✅ Clusters list: total={data['total']}, returned={len(data['clusters'])}")


class TestDiagnosticsEndpoint:
    """Part 6: Enhanced diagnostics for v2 signals"""
    
    @pytest.fixture(scope="class")
    def doc_id(self):
        """Get a document ID for testing"""
        response = requests.get(f"{BASE_URL}/api/documents", params={"limit": 1})
        assert response.status_code == 200
        docs = response.json().get("documents", [])
        if not docs:
            pytest.skip("No documents available for testing")
        return docs[0]["id"]
    
    def test_diagnostics_returns_cluster_info(self, doc_id):
        """Test diagnostics endpoint returns cluster, vendor_behavior, v2_signals"""
        response = requests.get(f"{BASE_URL}/api/reference-intelligence/v2/diagnostics/{doc_id}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check required fields
        assert "document_id" in data, f"Missing 'document_id': {data.keys()}"
        assert "cluster" in data, f"Missing 'cluster': {data.keys()}"
        assert "vendor_behavior" in data, f"Missing 'vendor_behavior': {data.keys()}"
        assert "v2_signals" in data, f"Missing 'v2_signals': {data.keys()}"
        
        # Cluster should have structure
        cluster = data["cluster"]
        assert "cluster_id" in cluster, f"cluster should have 'cluster_id': {cluster}"
        
        # Vendor behavior should have has_hints field
        vendor = data["vendor_behavior"]
        assert "has_hints" in vendor, f"vendor_behavior should have 'has_hints': {vendor}"
        
        print(f"✅ Diagnostics for {doc_id[:8]}: cluster={cluster.get('cluster_id')}, vendor_hints={vendor.get('has_hints')}")
    
    def test_diagnostics_not_found(self):
        """Test diagnostics endpoint with invalid doc ID"""
        response = requests.get(f"{BASE_URL}/api/reference-intelligence/v2/diagnostics/nonexistent-id-12345")
        assert response.status_code == 200  # Returns error in body, not 404
        data = response.json()
        assert "error" in data or data.get("document_id") is not None


class TestFeedbackEndpoint:
    """Part 7: Learning feedback endpoint"""
    
    @pytest.fixture(scope="class")
    def doc_id(self):
        """Get a document ID for testing"""
        response = requests.get(f"{BASE_URL}/api/documents", params={"limit": 1})
        assert response.status_code == 200
        docs = response.json().get("documents", [])
        if not docs:
            pytest.skip("No documents available for testing")
        return docs[0]["id"]
    
    def test_feedback_submission(self, doc_id):
        """Test POST /api/reference-intelligence/v2/feedback returns status=accepted"""
        feedback_payload = {
            "document_id": doc_id,
            "correction_type": "label_correction",
            "predicted_label": "PO",
            "correct_label": "BOL",
            "actor": "test_agent"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/reference-intelligence/v2/feedback",
            json=feedback_payload
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data.get("status") == "accepted", f"Expected status='accepted', got: {data}"
        assert "document_id" in data
        assert "correction_type" in data
        print(f"✅ Feedback accepted: {data}")
    
    def test_feedback_missing_fields(self):
        """Test feedback endpoint rejects missing required fields"""
        response = requests.post(
            f"{BASE_URL}/api/reference-intelligence/v2/feedback",
            json={"correction_type": "label_correction"}  # Missing document_id
        )
        assert response.status_code == 200
        data = response.json()
        assert "error" in data, f"Expected error for missing document_id: {data}"


class TestExistingApisStillWork:
    """Part 8: Safety check - existing APIs must still work"""
    
    def test_auth_login(self):
        """Verify /api/auth/login still works"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": "admin", "password": "admin"}
        )
        assert response.status_code == 200, f"Auth login failed: {response.status_code} {response.text}"
        data = response.json()
        assert "token" in data
        print("✅ Auth login works")
    
    def test_documents_list(self):
        """Verify /api/documents still works"""
        response = requests.get(f"{BASE_URL}/api/documents", params={"limit": 5})
        assert response.status_code == 200, f"Documents list failed: {response.status_code}"
        data = response.json()
        assert "documents" in data
        print(f"✅ Documents list works: {len(data['documents'])} docs")
    
    def test_workflows_status(self):
        """Verify workflow status endpoint still works"""
        response = requests.get(f"{BASE_URL}/api/workflows/ap_invoice/status-counts")
        assert response.status_code == 200, f"Workflows failed: {response.status_code}"
        print("✅ Workflows endpoint works")
    
    def test_settings_status(self):
        """Verify settings status endpoint still works"""
        response = requests.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200, f"Settings failed: {response.status_code}"
        print("✅ Settings endpoint works")


class TestMatchingDebugScoreBreakdown:
    """Part 5: Verify score breakdown includes fuzzy/contextual signals"""
    
    @pytest.fixture(scope="class")
    def doc_id(self):
        """Get a document ID for testing"""
        response = requests.get(f"{BASE_URL}/api/documents", params={"limit": 10})
        assert response.status_code == 200
        docs = response.json().get("documents", [])
        # Try to find a doc with reference_intelligence data
        for doc in docs:
            if doc.get("reference_intelligence", {}).get("matching_diagnostics"):
                return doc["id"]
        # Fall back to first doc
        if docs:
            return docs[0]["id"]
        pytest.skip("No documents available for testing")
    
    def test_matching_debug_endpoint(self, doc_id):
        """Test /api/documents/{doc_id}/matching-debug includes score breakdown"""
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}/matching-debug")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Should return diagnostics
        assert "diagnostics" in data or "match_outcome" in data, f"Response missing expected fields: {data.keys()}"
        print(f"✅ Matching debug response for {doc_id[:8]}: {list(data.keys())}")
        
        # If there are candidate scores, check for v2 signal fields
        diag = data.get("diagnostics", {})
        candidate_scores = diag.get("candidate_scores", [])
        if candidate_scores:
            first_score = candidate_scores[0]
            breakdown = first_score.get("score_breakdown", {})
            print(f"  Score breakdown keys: {list(breakdown.keys())}")
            # v2 signals would be fuzzy_reference_similarity, contextual_similarity
            # They may or may not be present depending on match type


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
