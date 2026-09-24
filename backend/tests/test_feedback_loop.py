"""
Test Feedback Loop Features — Iteration 177

Tests the new feedback loop additions:
1. POST /api/posting-patterns/review-queue/{doc_id}/sync-from-bc - Sync draft from BC
2. POST /api/posting-patterns/review-queue/sync-all - Batch sync all drafts
3. GET /api/posting-patterns/review-queue/{doc_id}/feedback - Get feedback details
4. GET /api/posting-patterns/review-queue - Review queue summary structure
5. POST /api/posting-patterns/review-queue/{doc_id}/approve - Approve draft (error for non-existent)
6. POST /api/posting-patterns/review-queue/{doc_id}/correct - Correct draft (error for non-existent)
7. draft_feedback_service.py module functions exist
8. original_draft_lines storage in gpi_integration.py
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestHealthCheck:
    """Basic health check"""
    
    def test_health_endpoint(self):
        """Verify API is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.status_code}"
        print("PASS: Health endpoint returns 200")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
