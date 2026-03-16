"""
API tests for Document Readiness Engine endpoints.

Tests:
  1. GET /api/readiness/metrics - returns analytics
  2. GET /api/readiness/queue - filterable document queue
  3. GET /api/readiness/queue?status=blocked - filter by status
  4. GET /api/readiness/queue?status=needs_review - filter by status
  5. POST /api/readiness/evaluate/{doc_id} - evaluate single doc
  6. POST /api/readiness/batch - batch evaluate
  7. Verify readiness object structure (11 signals, all required fields)
  8. Non-regression checks for existing endpoints
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# --------------------------------
# 1. Metrics Endpoint
# --------------------------------

class TestReadinessMetrics:
    """Tests for GET /api/readiness/metrics"""
    
    def test_metrics_returns_200(self):
        """Metrics endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: GET /api/readiness/metrics returns 200")
    
    def test_metrics_response_structure(self):
        """Metrics response should have required fields"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        data = response.json()
        
        required_fields = [
            "total_documents",
            "by_status",
            "by_action",
            "top_blocking_reasons",
            "top_warning_reasons",
            "top_reviewer_actions",
            "confidence_by_status",
        ]
        
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
            print(f"  - {field}: {type(data[field]).__name__}")
        
        print("PASS: Metrics response has all required fields")
    
    def test_metrics_by_status_structure(self):
        """by_status should have correct status keys"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        data = response.json()
        
        by_status = data.get("by_status", {})
        expected_statuses = ["ready_auto_draft", "ready_auto_link", "needs_review", "blocked", "ambiguous"]
        
        for status in by_status.keys():
            assert status in expected_statuses, f"Unexpected status: {status}"
        
        print(f"PASS: by_status contains valid statuses: {list(by_status.keys())}")
    
    def test_metrics_total_documents(self):
        """total_documents should be numeric"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        data = response.json()
        
        total = data.get("total_documents")
        assert isinstance(total, int), f"total_documents should be int, got {type(total)}"
        assert total >= 0, "total_documents should be non-negative"
        print(f"PASS: total_documents = {total}")


# --------------------------------
# 2. Queue Endpoint
# --------------------------------

class TestReadinessQueue:
    """Tests for GET /api/readiness/queue"""
    
    def test_queue_returns_200(self):
        """Queue endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/readiness/queue")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: GET /api/readiness/queue returns 200")
    
    def test_queue_response_structure(self):
        """Queue response should have total and documents"""
        response = requests.get(f"{BASE_URL}/api/readiness/queue")
        data = response.json()
        
        assert "total" in data, "Missing 'total' field"
        assert "documents" in data, "Missing 'documents' field"
        assert isinstance(data["documents"], list), "documents should be a list"
        
        print(f"PASS: Queue response structure valid (total={data['total']}, docs_count={len(data['documents'])})")
    
    def test_queue_document_has_readiness(self):
        """Documents in queue should have readiness data"""
        response = requests.get(f"{BASE_URL}/api/readiness/queue?limit=5")
        data = response.json()
        
        if len(data["documents"]) > 0:
            doc = data["documents"][0]
            assert "readiness" in doc, "Document should have readiness field"
            
            readiness = doc["readiness"]
            assert "status" in readiness, "readiness should have status"
            assert "confidence" in readiness, "readiness should have confidence"
            assert "signals" in readiness, "readiness should have signals"
            
            print(f"PASS: Document {doc.get('id', 'unknown')[:8]} has readiness data")
        else:
            print("WARN: No documents with readiness data in queue")
    
    def test_queue_filter_by_status_blocked(self):
        """Queue should filter by status=blocked"""
        response = requests.get(f"{BASE_URL}/api/readiness/queue?status=blocked")
        data = response.json()
        
        assert response.status_code == 200
        assert "documents" in data
        
        # All returned docs should be blocked
        for doc in data["documents"]:
            if "readiness" in doc:
                assert doc["readiness"]["status"] == "blocked", f"Doc {doc.get('id')} is not blocked"
        
        print(f"PASS: Filter by status=blocked works (total={data['total']})")
    
    def test_queue_filter_by_status_needs_review(self):
        """Queue should filter by status=needs_review"""
        response = requests.get(f"{BASE_URL}/api/readiness/queue?status=needs_review")
        data = response.json()
        
        assert response.status_code == 200
        assert "documents" in data
        
        # All returned docs should need review
        for doc in data["documents"]:
            if "readiness" in doc:
                assert doc["readiness"]["status"] == "needs_review", f"Doc {doc.get('id')} is not needs_review"
        
        print(f"PASS: Filter by status=needs_review works (total={data['total']})")
    
    def test_queue_filter_by_action(self):
        """Queue should filter by action param"""
        response = requests.get(f"{BASE_URL}/api/readiness/queue?action=hold")
        data = response.json()
        
        assert response.status_code == 200
        
        for doc in data["documents"]:
            if "readiness" in doc:
                assert doc["readiness"]["recommended_action"] == "hold"
        
        print(f"PASS: Filter by action=hold works (total={data['total']})")
    
    def test_queue_pagination(self):
        """Queue should support limit and skip"""
        response = requests.get(f"{BASE_URL}/api/readiness/queue?limit=2&skip=0")
        data = response.json()
        
        assert response.status_code == 200
        assert len(data["documents"]) <= 2, "limit should restrict results"
        
        print(f"PASS: Pagination works (limit=2 returned {len(data['documents'])} docs)")


# --------------------------------
# 3. Evaluate Single Document
# --------------------------------

class TestReadinessEvaluate:
    """Tests for POST /api/readiness/evaluate/{doc_id}"""
    
    def test_evaluate_nonexistent_returns_404(self):
        """Evaluating nonexistent doc should return 404"""
        response = requests.post(f"{BASE_URL}/api/readiness/evaluate/NONEXISTENT-DOC-ID-123")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: POST /api/readiness/evaluate/NONEXISTENT returns 404")
    
    def test_evaluate_existing_document(self):
        """Evaluating existing doc should return readiness"""
        # First get a document ID from queue
        queue_resp = requests.get(f"{BASE_URL}/api/readiness/queue?limit=1")
        queue_data = queue_resp.json()
        
        if len(queue_data.get("documents", [])) == 0:
            pytest.skip("No documents available to test evaluate")
        
        doc_id = queue_data["documents"][0]["id"]
        
        response = requests.post(f"{BASE_URL}/api/readiness/evaluate/{doc_id}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "success" in data
        assert data["success"] is True
        assert "readiness" in data
        
        readiness = data["readiness"]
        assert "status" in readiness
        assert "confidence" in readiness
        assert "signals" in readiness
        
        print(f"PASS: Evaluated doc {doc_id[:8]} -> status={readiness['status']}, confidence={readiness['confidence']}")


# --------------------------------
# 4. Batch Evaluate
# --------------------------------

class TestReadinessBatch:
    """Tests for POST /api/readiness/batch"""
    
    def test_batch_evaluate_returns_200(self):
        """Batch evaluate should return 200"""
        response = requests.post(f"{BASE_URL}/api/readiness/batch?limit=5")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "total" in data
        print(f"PASS: Batch evaluate returned (total={data.get('total', 0)})")


# --------------------------------
# 5. Readiness Object Structure
# --------------------------------

class TestReadinessObjectStructure:
    """Tests for readiness object completeness"""
    
    def test_signals_has_11_fields(self):
        """Signals should have exactly 11 boolean fields"""
        response = requests.get(f"{BASE_URL}/api/readiness/queue?limit=1")
        data = response.json()
        
        if len(data.get("documents", [])) == 0:
            pytest.skip("No documents to check signals")
        
        doc = data["documents"][0]
        signals = doc.get("readiness", {}).get("signals", {})
        
        expected_signals = [
            "vendor_resolved",
            "customer_resolved",
            "po_resolved",
            "duplicate_risk",
            "graph_linked",
            "line_items_present",
            "line_items_confident",
            "required_fields_complete",
            "policy_blocked",
            "policy_held",
            "manually_overridden",
        ]
        
        for sig in expected_signals:
            assert sig in signals, f"Missing signal: {sig}"
            assert isinstance(signals[sig], bool), f"Signal {sig} should be bool"
        
        assert len(signals) == 11, f"Expected 11 signals, got {len(signals)}"
        print(f"PASS: Readiness signals has all 11 fields: {list(signals.keys())}")
    
    def test_readiness_required_fields(self):
        """Readiness object should have all required fields"""
        response = requests.get(f"{BASE_URL}/api/readiness/queue?limit=1")
        data = response.json()
        
        if len(data.get("documents", [])) == 0:
            pytest.skip("No documents to check readiness fields")
        
        readiness = data["documents"][0].get("readiness", {})
        
        required_fields = [
            "status",
            "confidence",
            "recommended_action",
            "blocking_reasons",
            "warning_reasons",
            "required_reviewer_actions",
            "explanations",
            "signals",
            "last_evaluated_at",
            "reviewed_override",
        ]
        
        for field in required_fields:
            assert field in readiness, f"Missing readiness field: {field}"
        
        print("PASS: Readiness object has all required fields")
    
    def test_status_values(self):
        """Status should be one of valid values"""
        response = requests.get(f"{BASE_URL}/api/readiness/queue?limit=50")
        data = response.json()
        
        valid_statuses = ["ready_auto_draft", "ready_auto_link", "needs_review", "blocked", "ambiguous"]
        
        for doc in data.get("documents", []):
            status = doc.get("readiness", {}).get("status")
            if status:
                assert status in valid_statuses, f"Invalid status: {status}"
        
        print("PASS: All documents have valid status values")


# --------------------------------
# 6. Non-Regression: Existing Endpoints
# --------------------------------

class TestNonRegression:
    """Verify existing APIs still work"""
    
    def test_dashboard_stats(self):
        """Dashboard stats should still work"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200
        print("PASS: /api/dashboard/stats still works")
    
    def test_aliases_metrics(self):
        """Aliases metrics should still work"""
        response = requests.get(f"{BASE_URL}/api/aliases/metrics")
        assert response.status_code == 200
        print("PASS: /api/aliases/metrics still works")
    
    def test_vendor_resolution_metrics(self):
        """Vendor resolution metrics should still work"""
        response = requests.get(f"{BASE_URL}/api/vendor-resolution/metrics")
        assert response.status_code == 200
        print("PASS: /api/vendor-resolution/metrics still works")
    
    def test_health(self):
        """Health endpoint should still work"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print("PASS: /api/health still works")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
