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
    


class TestPostingPatternsPhase2HealthCheck:
    """Basic health check to ensure API is running"""
    
    def test_health_endpoint(self):
        """GET /api/health returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: GET /api/health - API is healthy")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
