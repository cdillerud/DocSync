"""
Test BC Posting Patterns - Tightened Analyzer (Iteration 172)

Tests for:
1. GET /api/posting-patterns/vendor-summary - consistency_score field
2. GET /api/posting-patterns/settings - returns settings
3. PUT /api/posting-patterns/settings - saves settings
4. GET /api/posting-patterns/ready-queue - returns queue
5. GET /api/posting-patterns/learning-proof/NONEXISTENT - NOT LEARNED verdict
6. POST /api/posting-patterns/draft-preview/nonexistent - returns error
7. GET /api/posting-patterns/status - returns profile counts
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestPostingPatternsTightened:
    """Tests for tightened BC Posting Pattern Analyzer"""

    def test_health_check(self):
        """Verify API is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.text}"
        print("PASS: Health check")

    def test_status_returns_profile_counts(self):
        """GET /api/posting-patterns/status returns profile counts"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/status")
        assert response.status_code == 200, f"Status failed: {response.text}"
        data = response.json()
        
        # Verify structure
        assert "total_profiles" in data, "Missing total_profiles"
        assert "confidence_distribution" in data, "Missing confidence_distribution"
        assert "top_vendors" in data, "Missing top_vendors"
        
        # Verify confidence_distribution structure
        conf_dist = data["confidence_distribution"]
        assert "high" in conf_dist, "Missing high in confidence_distribution"
        assert "medium" in conf_dist, "Missing medium in confidence_distribution"
        assert "low" in conf_dist, "Missing low in confidence_distribution"
        
        print(f"PASS: Status returns profile counts - total_profiles={data['total_profiles']}")

    def test_settings_get(self):
        """GET /api/posting-patterns/settings returns settings"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/settings")
        assert response.status_code == 200, f"Settings GET failed: {response.text}"
        data = response.json()
        
        # Verify required fields
        assert "auto_post_enabled" in data, "Missing auto_post_enabled"
        assert "min_confidence" in data, "Missing min_confidence"
        assert "min_invoices_analyzed" in data, "Missing min_invoices_analyzed"
        
        print(f"PASS: Settings GET - auto_post_enabled={data['auto_post_enabled']}, min_confidence={data['min_confidence']}")

    def test_settings_put(self):
        """PUT /api/posting-patterns/settings saves settings"""
        # First get current settings
        get_response = requests.get(f"{BASE_URL}/api/posting-patterns/settings")
        original = get_response.json()
        
        # Update settings
        new_settings = {
            "auto_post_enabled": True,
            "min_confidence": "medium",
            "min_invoices_analyzed": 15
        }
        put_response = requests.put(
            f"{BASE_URL}/api/posting-patterns/settings",
            json=new_settings,
            headers={"Content-Type": "application/json"}
        )
        assert put_response.status_code == 200, f"Settings PUT failed: {put_response.text}"
        put_data = put_response.json()
        
        assert put_data.get("status") == "updated", "Expected status=updated"
        assert put_data.get("min_confidence") == "medium", "min_confidence not updated"
        
        # Verify persistence with GET
        verify_response = requests.get(f"{BASE_URL}/api/posting-patterns/settings")
        verify_data = verify_response.json()
        assert verify_data.get("min_confidence") == "medium", "Settings not persisted"
        
        print("PASS: Settings PUT and persistence verified")

    def test_ready_queue_returns_queue(self):
        """GET /api/posting-patterns/ready-queue returns queue"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/ready-queue")
        assert response.status_code == 200, f"Ready queue failed: {response.text}"
        data = response.json()
        
        # Verify structure
        assert "count" in data, "Missing count"
        assert "documents" in data, "Missing documents"
        assert isinstance(data["documents"], list), "documents should be a list"
        
        print(f"PASS: Ready queue returns {data['count']} documents")

    def test_vendor_summary_has_consistency_score(self):
        """GET /api/posting-patterns/vendor-summary returns vendors with consistency_score"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/vendor-summary?limit=50")
        assert response.status_code == 200, f"Vendor summary failed: {response.text}"
        data = response.json()
        
        # Verify structure
        assert "count" in data, "Missing count"
        assert "vendors" in data, "Missing vendors"
        assert "settings" in data, "Missing settings"
        assert "ready_total" in data, "Missing ready_total"
        
        # If there are vendors, verify consistency_score field exists
        vendors = data.get("vendors", [])
        if vendors:
            first_vendor = vendors[0]
            assert "consistency_score" in first_vendor, "Missing consistency_score in vendor"
            assert "confidence" in first_vendor, "Missing confidence in vendor"
            assert "invoices_analyzed" in first_vendor, "Missing invoices_analyzed in vendor"
            print(f"PASS: Vendor summary has consistency_score - first vendor: {first_vendor.get('vendor_no')} with consistency_score={first_vendor.get('consistency_score')}")
        else:
            # Empty vendors is expected in preview env (no BC data)
            print("PASS: Vendor summary returns empty vendors (expected in preview env)")

    def test_learning_proof_nonexistent_returns_not_learned(self):
        """GET /api/posting-patterns/learning-proof/NONEXISTENT returns NOT LEARNED verdict"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-proof/NONEXISTENT_VENDOR_12345")
        assert response.status_code == 200, f"Learning proof failed: {response.text}"
        data = response.json()
        
        # Verify NOT LEARNED verdict
        assert "verdict" in data, "Missing verdict"
        assert data["verdict"] == "NOT LEARNED", f"Expected 'NOT LEARNED' verdict, got: {data['verdict']}"
        assert "vendor_no" in data, "Missing vendor_no"
        assert data["vendor_no"] == "NONEXISTENT_VENDOR_12345", "vendor_no mismatch"
        
        print("PASS: Learning proof for nonexistent vendor returns NOT LEARNED")

    def test_draft_preview_nonexistent_returns_error(self):
        """POST /api/posting-patterns/draft-preview/nonexistent returns error"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/draft-preview/nonexistent_doc_id_12345")
        assert response.status_code == 200, f"Draft preview failed: {response.text}"
        data = response.json()
        
        # Verify error response
        assert "error" in data, "Missing error field"
        assert "not found" in data["error"].lower() or "document" in data["error"].lower(), f"Unexpected error: {data['error']}"
        
        print("PASS: Draft preview for nonexistent doc returns error")

    def test_analyze_top_status(self):
        """GET /api/posting-patterns/analyze-top/status returns status"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/analyze-top/status")
        assert response.status_code == 200, f"Analyze top status failed: {response.text}"
        data = response.json()
        
        # Verify structure
        assert "running" in data, "Missing running field"
        assert "progress" in data, "Missing progress field"
        
        print(f"PASS: Analyze top status - running={data['running']}, progress={data['progress']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
