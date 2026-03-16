"""
API integration tests for Autonomous Document Routing (Auto-Clear Gate).

Tests cover:
  - GET /api/dashboard/routing-summary
  - GET /api/dashboard/stats (routing_summary field)
  - GET /api/dashboard/workflow-intelligence (routing_summary field)
  - POST /api/auto-clear/route/{doc_id}
  - POST /api/auto-clear/route-batch?limit=N
  - Routing score thresholds verification
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestRoutingSummaryEndpoint:
    """Tests for GET /api/dashboard/routing-summary"""

    def test_routing_summary_returns_200(self):
        response = requests.get(f"{BASE_URL}/api/dashboard/routing-summary")
        assert response.status_code == 200
        data = response.json()
        
        # Validate response structure
        assert "total" in data
        assert "counts" in data
        assert isinstance(data["total"], int)
        assert isinstance(data["counts"], dict)

    def test_routing_summary_has_status_counts(self):
        response = requests.get(f"{BASE_URL}/api/dashboard/routing-summary")
        assert response.status_code == 200
        data = response.json()
        
        # Check for expected status keys
        counts = data.get("counts", {})
        # At least one status should exist if documents are routed
        if data["total"] > 0:
            assert len(counts) > 0
            
        # Each status count should have count and avg_score
        for status, info in counts.items():
            if status != "unrouted":
                assert "count" in info
                assert "avg_score" in info
                assert isinstance(info["count"], int)
                assert isinstance(info["avg_score"], (int, float))


class TestDashboardStatsRoutingSummary:
    """Tests for routing_summary in GET /api/dashboard/stats"""

    def test_stats_includes_routing_summary(self):
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200
        data = response.json()
        
        # routing_summary should be present
        assert "routing_summary" in data
        routing = data["routing_summary"]
        assert isinstance(routing, dict)
        
    def test_stats_routing_summary_structure(self):
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200
        routing = response.json().get("routing_summary", {})
        
        # Each entry should have count and avg_score
        for status, info in routing.items():
            assert "count" in info
            assert "avg_score" in info


class TestWorkflowIntelligenceRoutingSummary:
    """Tests for routing_summary in GET /api/dashboard/workflow-intelligence"""

    def test_workflow_intelligence_includes_routing_summary(self):
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        assert response.status_code == 200
        data = response.json()
        
        # routing_summary should be present
        assert "routing_summary" in data
        routing = data["routing_summary"]
        assert isinstance(routing, dict)
        
    def test_workflow_intelligence_routing_structure(self):
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        assert response.status_code == 200
        routing = response.json().get("routing_summary", {})
        
        # Should have total_routed and counts
        assert "total_routed" in routing
        assert "counts" in routing
        assert isinstance(routing["total_routed"], int)
        assert isinstance(routing["counts"], dict)


class TestRouteSingleDocument:
    """Tests for POST /api/auto-clear/route/{doc_id}"""

    def test_route_nonexistent_document_returns_404(self):
        response = requests.post(f"{BASE_URL}/api/auto-clear/route/NONEXISTENT-DOC-ID")
        assert response.status_code == 404

    def test_route_existing_document_returns_routing_result(self):
        # First get a document ID
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=1")
        if docs_response.status_code != 200:
            pytest.skip("Could not fetch documents")
            
        docs = docs_response.json()
        if not docs.get("documents"):
            pytest.skip("No documents available")
            
        doc_id = docs["documents"][0]["id"]
        
        # Route the document
        response = requests.post(f"{BASE_URL}/api/auto-clear/route/{doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        # Validate response structure
        assert "success" in data
        assert data["success"] == True
        assert "doc_id" in data
        assert "routing_status" in data
        assert "routing_score" in data
        assert "routing_reasons" in data
        assert "routing_timestamp" in data
        
        # Validate routing_status is one of the expected values
        assert data["routing_status"] in ["auto_process", "review", "blocked"]
        
        # Validate score is in range
        assert 0 <= data["routing_score"] <= 100
        
        # Validate reasons is a list
        assert isinstance(data["routing_reasons"], list)


class TestRouteBatch:
    """Tests for POST /api/auto-clear/route-batch"""

    def test_route_batch_returns_counts(self):
        response = requests.post(f"{BASE_URL}/api/auto-clear/route-batch?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        # Validate response structure
        assert "total" in data
        assert "auto_process" in data
        assert "review" in data
        assert "blocked" in data
        assert "errors" in data
        
        # All should be integers
        assert isinstance(data["total"], int)
        assert isinstance(data["auto_process"], int)
        assert isinstance(data["review"], int)
        assert isinstance(data["blocked"], int)
        assert isinstance(data["errors"], int)
        
        # Sum of statuses + errors should equal total
        assert data["auto_process"] + data["review"] + data["blocked"] + data["errors"] == data["total"]


class TestRoutingScoreThresholds:
    """Tests to verify routing score thresholds match specification"""

    def test_auto_process_threshold_is_75(self):
        # Route a document and verify threshold
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=10")
        if docs_response.status_code != 200:
            pytest.skip("Could not fetch documents")
            
        docs = docs_response.json().get("documents", [])
        
        auto_process_found = False
        review_found = False
        blocked_found = False
        
        for doc in docs:
            score = doc.get("routing_score")
            status = doc.get("routing_status")
            
            if score is None or status is None:
                continue
                
            # Verify thresholds: auto_process >= 75, review 40-74, blocked < 40
            if status == "auto_process":
                auto_process_found = True
                assert score >= 75, f"auto_process doc has score {score} < 75"
            elif status == "review":
                review_found = True
                assert 40 <= score < 75, f"review doc has score {score} not in [40, 75)"
            elif status == "blocked":
                blocked_found = True
                assert score < 40, f"blocked doc has score {score} >= 40"
        
        # At least verify we found some routed documents
        if not (auto_process_found or review_found or blocked_found):
            # Check routing summary to confirm documents exist
            summary = requests.get(f"{BASE_URL}/api/dashboard/routing-summary").json()
            if summary.get("total", 0) > 0:
                print(f"Routing summary shows {summary['total']} docs but couldn't verify individual thresholds")
