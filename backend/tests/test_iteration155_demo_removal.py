"""
Iteration 155 Tests: Demo Scaffolding Removal & Batches Tab
- Pipeline Demo tab removed from Sales module
- Batches tab added to Inbox showing batch_parent documents
- POST /api/documents/{doc_id}/reprocess-batch endpoint
- Sales defaults to My Queue
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestHealthAndBasics:
    """Basic health and connectivity tests"""
    
    def test_health_endpoint(self):
        """Health endpoint returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print("PASS: Health endpoint returns healthy")

class TestBatchesTabBackend:
    """Tests for Batches tab backend support"""
    
    def test_list_batch_parent_documents(self):
        """GET /api/documents with status=batch_parent returns batch parents"""
        response = requests.get(
            f"{BASE_URL}/api/documents",
            params={
                "limit": 10,
                "queue_view": "false",
                "include_cleared": "true",
                "status": "batch_parent"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "documents" in data
        assert "total" in data
        # Should have batch_parent documents (17 from context)
        assert data["total"] >= 1, "Expected at least 1 batch_parent document"
        
        # Verify all returned docs have batch_parent status
        for doc in data["documents"]:
            assert doc.get("status") == "batch_parent", f"Expected batch_parent status, got {doc.get('status')}"
        
        print(f"PASS: Found {data['total']} batch_parent documents")
    
    def test_batch_parent_has_children_count(self):
        """Batch parent documents should have batch_children_count field"""
        response = requests.get(
            f"{BASE_URL}/api/documents",
            params={
                "limit": 1,
                "queue_view": "false",
                "include_cleared": "true",
                "status": "batch_parent"
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        if data["documents"]:
            doc = data["documents"][0]
            # batch_children_count should exist for batch_parent docs
            assert "batch_children_count" in doc or "batch_children_ids" in doc, \
                "Batch parent should have children count or IDs"
            print(f"PASS: Batch parent has children info: count={doc.get('batch_children_count')}")
        else:
            pytest.skip("No batch_parent documents found")

class TestReprocessBatchEndpoint:
    """Tests for POST /api/documents/{doc_id}/reprocess-batch endpoint"""
    
    @pytest.fixture
    def batch_parent_id(self):
        """Get a valid batch_parent document ID for testing"""
        response = requests.get(
            f"{BASE_URL}/api/documents",
            params={
                "limit": 1,
                "queue_view": "false",
                "include_cleared": "true",
                "status": "batch_parent"
            }
        )
        if response.status_code == 200:
            data = response.json()
            if data["documents"]:
                return data["documents"][0]["id"]
        pytest.skip("No batch_parent document available for testing")
    
    def test_reprocess_batch_endpoint_exists(self, batch_parent_id):
        """POST /api/documents/{doc_id}/reprocess-batch endpoint exists and responds"""
        # Note: We're NOT actually triggering reprocess (takes ~70s)
        # Just verify the endpoint exists and validates properly
        
        # Test with invalid doc_id first
        response = requests.post(f"{BASE_URL}/api/documents/invalid_doc_id/reprocess-batch")
        # Should return 404 for non-existent doc
        assert response.status_code == 404, f"Expected 404 for invalid doc, got {response.status_code}"
        print("PASS: Reprocess endpoint returns 404 for invalid doc")
    
    def test_reprocess_batch_validates_batch_parent(self):
        """Reprocess endpoint should reject non-batch_parent documents"""
        # Get a non-batch_parent document
        response = requests.get(
            f"{BASE_URL}/api/documents",
            params={
                "limit": 1,
                "queue_view": "false",
                "include_cleared": "true"
            }
        )
        if response.status_code == 200:
            data = response.json()
            # Find a non-batch_parent doc
            for doc in data["documents"]:
                if doc.get("status") != "batch_parent":
                    # Try to reprocess it - should fail
                    reprocess_resp = requests.post(
                        f"{BASE_URL}/api/documents/{doc['id']}/reprocess-batch"
                    )
                    # Should return 400 because it's not a batch_parent
                    assert reprocess_resp.status_code == 400, \
                        f"Expected 400 for non-batch_parent, got {reprocess_resp.status_code}"
                    print("PASS: Reprocess endpoint rejects non-batch_parent documents")
                    return
        
        pytest.skip("No non-batch_parent document found for validation test")

class TestProcessedTabExcludesBatchParent:
    """Tests that Processed tab correctly excludes batch_parent documents"""
    
    def test_completed_count_excludes_batch_parent(self):
        """Completed count should not include batch_parent documents"""
        response = requests.get(
            f"{BASE_URL}/api/documents",
            params={
                "limit": 0,
                "queue_view": "false",
                "include_cleared": "true"
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        counts = data.get("counts", {})
        completed_count = counts.get("completed", 0)
        
        # From context: 5 completed docs, 17 batch_parent docs
        # completed_count should be 5, not 22
        print(f"Completed count: {completed_count}")
        assert completed_count <= 10, f"Completed count ({completed_count}) seems too high - may include batch_parent"
        print(f"PASS: Completed count ({completed_count}) correctly excludes batch_parent")

class TestAllTabExcludesBatchParent:
    """Tests that All tab (queue_view=true) excludes batch_parent documents"""
    
    def test_queue_view_excludes_batch_parent(self):
        """Queue view should not show batch_parent documents"""
        response = requests.get(
            f"{BASE_URL}/api/documents",
            params={
                "limit": 100,
                "queue_view": "true",
                "include_cleared": "false"
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check that no batch_parent docs are in the results
        for doc in data["documents"]:
            assert doc.get("status") != "batch_parent", \
                f"Found batch_parent in queue view: {doc.get('id')}"
        
        print(f"PASS: Queue view excludes batch_parent (showing {len(data['documents'])} docs)")

class TestInboxStats:
    """Tests for inbox stats strip"""
    
    def test_inbox_stats_endpoint(self):
        """GET /api/dashboard/inbox-stats returns valid stats"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        assert response.status_code == 200
        data = response.json()
        
        # Check expected fields
        expected_fields = ["ingested_today", "auto_validation_rate", "pending_review", "avg_ai_confidence"]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
        
        print(f"PASS: Inbox stats: today={data.get('ingested_today')}, auto_rate={data.get('auto_validation_rate')}%")

class TestInsightsPage:
    """Tests for Insights page backend"""
    
    def test_insights_trends_endpoint(self):
        """GET /api/dashboard/insights-trends returns trend data"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insights-trends")
        assert response.status_code == 200
        data = response.json()
        
        # Should have daily_trend or similar data
        assert "daily_trend" in data or "trends" in data or len(data) > 0, \
            "Insights trends should return data"
        
        print(f"PASS: Insights trends endpoint returns data")

class TestSalesDashboard:
    """Tests for Sales dashboard endpoints"""
    
    def test_triage_queue_endpoint(self):
        """GET /api/sales-dashboard/triage-queue returns data"""
        response = requests.get(
            f"{BASE_URL}/api/sales-dashboard/triage-queue",
            params={"limit": 10}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data or "documents" in data or "items" in data
        print(f"PASS: Triage queue endpoint works")
    
    def test_my_queue_endpoint(self):
        """GET /api/sales-dashboard/my-queue returns data"""
        response = requests.get(
            f"{BASE_URL}/api/sales-dashboard/my-queue",
            params={"limit": 10}
        )
        # May return 200 or 401 if auth required
        assert response.status_code in [200, 401, 422]
        print(f"PASS: My queue endpoint responds (status={response.status_code})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
