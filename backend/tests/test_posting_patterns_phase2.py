"""
Test Posting Patterns Phase 2 API Endpoints
- Settings CRUD
- Ready Queue
- Vendor Summary
- Draft Preview/Create
- Analysis Status
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestPostingPatternsPhase2Settings:
    """Auto-Post Settings CRUD tests"""
    
    def test_get_settings_returns_defaults(self):
        """GET /api/posting-patterns/settings returns default settings structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/settings")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify required fields exist
        assert "auto_post_enabled" in data, "Missing auto_post_enabled field"
        assert "min_confidence" in data, "Missing min_confidence field"
        assert "min_invoices_analyzed" in data, "Missing min_invoices_analyzed field"
        assert isinstance(data["auto_post_enabled"], bool), "auto_post_enabled should be boolean"
        assert data["min_confidence"] in ["high", "medium", "low"], f"Invalid min_confidence: {data['min_confidence']}"
        print(f"PASS: GET /api/posting-patterns/settings - auto_post_enabled={data['auto_post_enabled']}, min_confidence={data['min_confidence']}")
    
    def test_put_settings_updates_and_returns(self):
        """PUT /api/posting-patterns/settings saves and returns updated settings"""
        # First get current settings
        get_response = requests.get(f"{BASE_URL}/api/posting-patterns/settings")
        assert get_response.status_code == 200
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
        assert put_response.status_code == 200, f"Expected 200, got {put_response.status_code}: {put_response.text}"
        
        data = put_response.json()
        assert data.get("status") == "updated", f"Expected status='updated', got {data.get('status')}"
        assert data.get("auto_post_enabled") == True, "auto_post_enabled not updated"
        assert data.get("min_confidence") == "medium", "min_confidence not updated"
        assert data.get("min_invoices_analyzed") == 15, "min_invoices_analyzed not updated"
        
        # Verify persistence with GET
        verify_response = requests.get(f"{BASE_URL}/api/posting-patterns/settings")
        verify_data = verify_response.json()
        assert verify_data.get("auto_post_enabled") == True, "Settings not persisted"
        assert verify_data.get("min_confidence") == "medium", "min_confidence not persisted"
        print("PASS: PUT /api/posting-patterns/settings - settings updated and persisted")


class TestPostingPatternsPhase2ReadyQueue:
    """Ready Queue endpoint tests"""
    
    def test_get_ready_queue_returns_structure(self):
        """GET /api/posting-patterns/ready-queue returns queue with count"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/ready-queue")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "count" in data, "Missing count field"
        assert "documents" in data, "Missing documents field"
        assert isinstance(data["count"], int), "count should be integer"
        assert isinstance(data["documents"], list), "documents should be list"
        print(f"PASS: GET /api/posting-patterns/ready-queue - count={data['count']}, documents={len(data['documents'])}")
    
    def test_get_ready_queue_with_filters(self):
        """GET /api/posting-patterns/ready-queue supports vendor and confidence filters"""
        # Test with confidence filter
        response = requests.get(f"{BASE_URL}/api/posting-patterns/ready-queue?confidence=high")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "count" in data
        assert "documents" in data
        print(f"PASS: GET /api/posting-patterns/ready-queue with confidence filter - count={data['count']}")


class TestPostingPatternsPhase2VendorSummary:
    """Vendor Summary endpoint tests"""
    
    def test_get_vendor_summary_returns_structure(self):
        """GET /api/posting-patterns/vendor-summary returns vendor list with required fields"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/vendor-summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "count" in data, "Missing count field"
        assert "vendors" in data, "Missing vendors field"
        assert "settings" in data, "Missing settings field"
        assert "ready_total" in data, "Missing ready_total field"
        
        assert isinstance(data["count"], int), "count should be integer"
        assert isinstance(data["vendors"], list), "vendors should be list"
        assert isinstance(data["ready_total"], int), "ready_total should be integer"
        
        # Verify settings structure
        settings = data["settings"]
        assert "auto_post_enabled" in settings, "Missing auto_post_enabled in settings"
        assert "min_confidence" in settings, "Missing min_confidence in settings"
        
        # If vendors exist, verify structure
        if data["vendors"]:
            vendor = data["vendors"][0]
            required_fields = ["vendor_no", "confidence", "ready_docs", "auto_post_eligible"]
            for field in required_fields:
                assert field in vendor, f"Missing {field} in vendor object"
        
        print(f"PASS: GET /api/posting-patterns/vendor-summary - count={data['count']}, ready_total={data['ready_total']}")


class TestPostingPatternsPhase2Status:
    """Status and Analysis endpoints tests"""
    
    def test_get_status_returns_structure(self):
        """GET /api/posting-patterns/status returns posting pattern analysis status"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "total_profiles" in data, "Missing total_profiles field"
        assert "confidence_distribution" in data, "Missing confidence_distribution field"
        assert "top_vendors" in data, "Missing top_vendors field"
        
        # Verify confidence distribution structure
        conf_dist = data["confidence_distribution"]
        assert "high" in conf_dist, "Missing high in confidence_distribution"
        assert "medium" in conf_dist, "Missing medium in confidence_distribution"
        assert "low" in conf_dist, "Missing low in confidence_distribution"
        
        print(f"PASS: GET /api/posting-patterns/status - total_profiles={data['total_profiles']}, distribution={conf_dist}")
    
    def test_get_analyze_top_status(self):
        """GET /api/posting-patterns/analyze-top/status returns background analysis status"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/analyze-top/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "running" in data, "Missing running field"
        assert "progress" in data, "Missing progress field"
        assert isinstance(data["running"], bool), "running should be boolean"
        print(f"PASS: GET /api/posting-patterns/analyze-top/status - running={data['running']}, progress={data['progress']}")


class TestPostingPatternsPhase2DraftPreviewCreate:
    """Draft Preview and Create endpoint tests"""
    
    def test_draft_preview_nonexistent_doc(self):
        """POST /api/posting-patterns/draft-preview/nonexistent returns error for missing doc"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/draft-preview/nonexistent-doc-id-12345")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "error" in data, "Expected error field for nonexistent document"
        assert "not found" in data["error"].lower() or "document" in data["error"].lower(), f"Unexpected error message: {data['error']}"
        print(f"PASS: POST /api/posting-patterns/draft-preview/nonexistent - error={data['error']}")
    
    def test_create_draft_nonexistent_doc(self):
        """POST /api/posting-patterns/create-draft/nonexistent returns error for missing doc"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/create-draft/nonexistent-doc-id-12345")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "error" in data or data.get("success") == False, "Expected error or success=False for nonexistent document"
        print(f"PASS: POST /api/posting-patterns/create-draft/nonexistent - response={data}")


class TestPostingPatternsPhase2HealthCheck:
    """Basic health check to ensure API is running"""
    
    def test_health_endpoint(self):
        """GET /api/health returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: GET /api/health - API is healthy")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
