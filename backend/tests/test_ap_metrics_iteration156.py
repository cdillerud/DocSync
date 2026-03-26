"""
Test AP Metrics and AP Review Endpoints - Iteration 156

Tests:
- GET /api/dashboard/ap-metrics - AP Invoice posting metrics
- POST /api/ap-review/documents/{doc_id}/post-to-bc - Post to BC validation
- POST /api/ap-review/documents/{doc_id}/mark-ready - Mark ready for post
- POST /api/documents/{doc_id}/reprocess-batch - Batch reprocess endpoint
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestAPMetricsEndpoint:
    """Test GET /api/dashboard/ap-metrics endpoint"""
    
    def test_ap_metrics_returns_200(self):
        """AP metrics endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/dashboard/ap-metrics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET /api/dashboard/ap-metrics returns 200")
    
    def test_ap_metrics_response_structure(self):
        """AP metrics should return expected fields"""
        response = requests.get(f"{BASE_URL}/api/dashboard/ap-metrics")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify required fields exist
        required_fields = [
            'total_ap', 'posted_to_bc', 'failed', 'pending_review',
            'validation_rate', 'success_rate', 'error_breakdown'
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Verify data types
        assert isinstance(data['total_ap'], int), "total_ap should be int"
        assert isinstance(data['posted_to_bc'], int), "posted_to_bc should be int"
        assert isinstance(data['failed'], int), "failed should be int"
        assert isinstance(data['pending_review'], int), "pending_review should be int"
        assert isinstance(data['validation_rate'], (int, float)), "validation_rate should be numeric"
        assert isinstance(data['success_rate'], (int, float)), "success_rate should be numeric"
        assert isinstance(data['error_breakdown'], list), "error_breakdown should be list"
        
        print(f"PASS: AP metrics response structure valid - total_ap={data['total_ap']}, posted={data['posted_to_bc']}, failed={data['failed']}")
    
    def test_ap_metrics_returns_zeros_when_no_ap_docs(self):
        """With no AP docs, metrics should return zeros"""
        response = requests.get(f"{BASE_URL}/api/dashboard/ap-metrics")
        assert response.status_code == 200
        
        data = response.json()
        
        # Per context: there are 0 AP docs in the system
        # All values should be 0 or empty
        if data['total_ap'] == 0:
            assert data['posted_to_bc'] == 0, "posted_to_bc should be 0 when no AP docs"
            assert data['failed'] == 0, "failed should be 0 when no AP docs"
            assert data['pending_review'] == 0, "pending_review should be 0 when no AP docs"
            assert data['validation_rate'] == 0, "validation_rate should be 0 when no AP docs"
            assert data['success_rate'] == 0, "success_rate should be 0 when no AP docs"
            print("PASS: AP metrics returns all zeros when no AP docs exist")
        else:
            print(f"INFO: Found {data['total_ap']} AP docs - metrics are non-zero")


class TestAPReviewPostToBCEndpoint:
    """Test POST /api/ap-review/documents/{doc_id}/post-to-bc endpoint"""
    
    def test_post_to_bc_invalid_doc_returns_404(self):
        """Post to BC with invalid doc_id should return 404"""
        response = requests.post(f"{BASE_URL}/api/ap-review/documents/invalid-doc-id-12345/post-to-bc")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert 'detail' in data, "Response should have detail field"
        assert 'not found' in data['detail'].lower(), f"Error should mention 'not found': {data['detail']}"
        print("PASS: POST /api/ap-review/documents/{invalid_id}/post-to-bc returns 404")
    
    def test_post_to_bc_nonexistent_uuid_returns_404(self):
        """Post to BC with non-existent UUID should return 404"""
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        response = requests.post(f"{BASE_URL}/api/ap-review/documents/{fake_uuid}/post-to-bc")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        print("PASS: POST /api/ap-review/documents/{nonexistent_uuid}/post-to-bc returns 404")


class TestAPReviewMarkReadyEndpoint:
    """Test POST /api/ap-review/documents/{doc_id}/mark-ready endpoint"""
    
    def test_mark_ready_invalid_doc_returns_404(self):
        """Mark ready with invalid doc_id should return 404"""
        response = requests.post(f"{BASE_URL}/api/ap-review/documents/invalid-doc-id-12345/mark-ready")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert 'detail' in data, "Response should have detail field"
        assert 'not found' in data['detail'].lower(), f"Error should mention 'not found': {data['detail']}"
        print("PASS: POST /api/ap-review/documents/{invalid_id}/mark-ready returns 404")


class TestBatchReprocessEndpoint:
    """Test POST /api/documents/{doc_id}/reprocess-batch endpoint"""
    
    def test_reprocess_batch_invalid_doc_returns_404(self):
        """Reprocess batch with invalid doc_id should return 404"""
        response = requests.post(f"{BASE_URL}/api/documents/invalid-doc-id-12345/reprocess-batch")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        print("PASS: POST /api/documents/{invalid_id}/reprocess-batch returns 404")


class TestInsightsTrendsEndpoint:
    """Test GET /api/dashboard/insights-trends endpoint"""
    
    def test_insights_trends_returns_200(self):
        """Insights trends endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insights-trends")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET /api/dashboard/insights-trends returns 200")
    
    def test_insights_trends_response_structure(self):
        """Insights trends should return expected fields"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insights-trends?days=30")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify required fields
        assert 'daily' in data, "Response should have 'daily' field"
        assert 'bakeoff_runs' in data, "Response should have 'bakeoff_runs' field"
        assert 'period_days' in data, "Response should have 'period_days' field"
        
        assert isinstance(data['daily'], list), "daily should be a list"
        assert isinstance(data['bakeoff_runs'], list), "bakeoff_runs should be a list"
        assert data['period_days'] == 30, f"period_days should be 30, got {data['period_days']}"
        
        print(f"PASS: Insights trends structure valid - {len(data['daily'])} daily entries, {len(data['bakeoff_runs'])} bakeoff runs")


class TestDashboardStatsEndpoint:
    """Test GET /api/dashboard/stats endpoint"""
    
    def test_dashboard_stats_returns_200(self):
        """Dashboard stats endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET /api/dashboard/stats returns 200")
    
    def test_dashboard_stats_has_demo_mode_field(self):
        """Dashboard stats should include demo_mode field"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200
        
        data = response.json()
        assert 'demo_mode' in data, "Response should have 'demo_mode' field"
        # Per .env, DEMO_MODE=false
        assert data['demo_mode'] == False, f"demo_mode should be False, got {data['demo_mode']}"
        print("PASS: Dashboard stats shows demo_mode=False (BC Sandbox is REAL)")


class TestHealthEndpoint:
    """Test GET /api/health endpoint"""
    
    def test_health_returns_200(self):
        """Health endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET /api/health returns 200")


class TestInboxStatsEndpoint:
    """Test GET /api/dashboard/inbox-stats endpoint"""
    
    def test_inbox_stats_returns_200(self):
        """Inbox stats endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET /api/dashboard/inbox-stats returns 200")
    
    def test_inbox_stats_response_structure(self):
        """Inbox stats should return expected fields"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        assert response.status_code == 200
        
        data = response.json()
        
        required_fields = [
            'ingested_today', 'avg_daily_7d', 'auto_validation_rate',
            'pending_review', 'bounds_alerts', 'avg_ai_confidence', 'total_documents'
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"PASS: Inbox stats structure valid - total_documents={data['total_documents']}, auto_rate={data['auto_validation_rate']}%")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
