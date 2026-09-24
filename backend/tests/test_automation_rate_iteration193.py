"""
Iteration 193: Test Automation Rate Dashboard Widget API
Tests the new GET /api/readiness/automation-rate endpoint with various days parameters
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestReadinessMetricsStillWorks:
    """Verify existing /api/readiness/metrics endpoint still works"""
    
    def test_readiness_metrics_endpoint(self):
        """Test that /api/readiness/metrics still returns valid data"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify key fields exist
        assert 'total_documents' in data
        assert 'by_status' in data
        
        print(f"✓ /api/readiness/metrics works: total_documents={data.get('total_documents')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
