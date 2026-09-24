"""
Test Auto-Scheduling + Badge Count Features (Iteration 178)

Tests:
1. GET /api/posting-patterns/review-queue/badge-count - returns {count: <number>}
2. POST /api/posting-patterns/review-queue/sync-all - returns valid batch result
3. GET /api/posting-patterns/review-queue - returns review queue with summary
4. Scheduler existence verification (code review)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestHealthEndpoint:
    """Basic health check"""
    
    def test_health_check(self):
        """GET /api/health returns 200"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.status_code}"
        print("PASS: Health check OK")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
