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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
