"""
Test Batch Re-evaluate All Feature (Iteration 180)

Tests:
1. POST /api/readiness/reevaluate-all?limit=5 - returns valid response structure
2. GET /api/posting-patterns/learning-dashboard - no NoneType round() error
3. POST /api/readiness/evaluate/{doc_id} - returns success for existing documents
4. GET /api/readiness/metrics - returns metrics
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestBatchReevaluateAll:
    """Tests for the new batch re-evaluate all feature"""

    def test_health_check(self):
        """Verify API is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.text}"
        print("PASS: Health check returned 200")

    def test_reevaluate_all_endpoint_returns_valid_structure(self):
        """POST /api/readiness/reevaluate-all?limit=5 returns valid response structure"""
        response = requests.post(f"{BASE_URL}/api/readiness/reevaluate-all?limit=5")
        assert response.status_code == 200, f"reevaluate-all failed: {response.status_code} - {response.text}"
        
        data = response.json()
        
        # Verify required fields exist
        assert "total_processed" in data, "Missing total_processed field"
        assert "total_corrections" in data, "Missing total_corrections field"
        assert "status_transitions" in data, "Missing status_transitions field"
        assert "vendor_corrections" in data, "Missing vendor_corrections field"
        assert "by_status" in data, "Missing by_status field"
        assert "errors" in data, "Missing errors field"
        
        # Verify types
        assert isinstance(data["total_processed"], int), "total_processed should be int"
        assert isinstance(data["total_corrections"], int), "total_corrections should be int"
        assert isinstance(data["status_transitions"], list), "status_transitions should be list"
        assert isinstance(data["vendor_corrections"], list), "vendor_corrections should be list"
        assert isinstance(data["by_status"], dict), "by_status should be dict"
        assert isinstance(data["errors"], int), "errors should be int"
        
        print(f"PASS: reevaluate-all returned valid structure - processed={data['total_processed']}, corrections={data['total_corrections']}")

    def test_learning_dashboard_no_nonetype_error(self):
        """GET /api/posting-patterns/learning-dashboard returns valid JSON (no NoneType round error)"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200, f"learning-dashboard failed: {response.status_code} - {response.text}"
        
        data = response.json()
        
        # Verify summary exists
        assert "summary" in data, "Missing summary field"
        summary = data["summary"]
        
        # Verify key summary fields
        assert "total_learning_events" in summary, "Missing total_learning_events"
        assert "total_corrections" in summary, "Missing total_corrections"
        assert "total_posting_profiles" in summary, "Missing total_posting_profiles"
        
        # Verify posting_template_confidence exists and is a list
        assert "posting_template_confidence" in data, "Missing posting_template_confidence"
        assert isinstance(data["posting_template_confidence"], list), "posting_template_confidence should be list"
        
        # Verify vendor_learning_activity exists and is a list
        assert "vendor_learning_activity" in data, "Missing vendor_learning_activity"
        assert isinstance(data["vendor_learning_activity"], list), "vendor_learning_activity should be list"
        
        # Check that round() didn't fail on None values
        for item in data["posting_template_confidence"]:
            assert "avg_invoices_analyzed" in item, "Missing avg_invoices_analyzed"
            assert isinstance(item["avg_invoices_analyzed"], (int, float)), "avg_invoices_analyzed should be numeric"
        
        for item in data["vendor_learning_activity"]:
            assert "total_amount_learned" in item, "Missing total_amount_learned"
            assert "avg_lines_per_invoice" in item, "Missing avg_lines_per_invoice"
            assert isinstance(item["total_amount_learned"], (int, float)), "total_amount_learned should be numeric"
            assert isinstance(item["avg_lines_per_invoice"], (int, float)), "avg_lines_per_invoice should be numeric"
        
        print(f"PASS: learning-dashboard returned valid JSON - total_learning_events={summary['total_learning_events']}, total_corrections={summary['total_corrections']}")

    def test_readiness_metrics_endpoint(self):
        """GET /api/readiness/metrics returns metrics"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        assert response.status_code == 200, f"readiness/metrics failed: {response.status_code} - {response.text}"
        
        data = response.json()
        
        # Verify required fields
        assert "total_documents" in data, "Missing total_documents"
        assert "by_status" in data, "Missing by_status"
        assert "by_action" in data, "Missing by_action"
        
        assert isinstance(data["total_documents"], int), "total_documents should be int"
        assert isinstance(data["by_status"], dict), "by_status should be dict"
        
        print(f"PASS: readiness/metrics returned valid data - total_documents={data['total_documents']}")

    def test_evaluate_single_document(self):
        """POST /api/readiness/evaluate/{doc_id} returns success for existing documents"""
        # First get a document ID from the queue
        queue_response = requests.get(f"{BASE_URL}/api/readiness/queue?limit=1")
        assert queue_response.status_code == 200, f"readiness/queue failed: {queue_response.status_code}"
        
        queue_data = queue_response.json()
        documents = queue_data.get("documents", [])
        
        if not documents:
            # Try to get any document from hub_documents
            docs_response = requests.get(f"{BASE_URL}/api/documents?limit=1")
            if docs_response.status_code == 200:
                docs_data = docs_response.json()
                documents = docs_data.get("documents", [])
        
        if not documents:
            pytest.skip("No documents available to test evaluate endpoint")
        
        doc_id = documents[0].get("id")
        assert doc_id, "Document has no id field"
        
        # Test evaluate endpoint
        response = requests.post(f"{BASE_URL}/api/readiness/evaluate/{doc_id}")
        assert response.status_code == 200, f"evaluate/{doc_id} failed: {response.status_code} - {response.text}"
        
        data = response.json()
        assert "success" in data, "Missing success field"
        assert data["success"] is True, f"Evaluate returned success=False: {data}"
        assert "readiness" in data, "Missing readiness field"
        
        readiness = data["readiness"]
        assert "status" in readiness, "Missing status in readiness"
        assert "confidence" in readiness, "Missing confidence in readiness"
        assert "signals" in readiness, "Missing signals in readiness"
        
        print(f"PASS: evaluate/{doc_id[:8]} returned success - status={readiness['status']}, confidence={readiness['confidence']}")

    def test_evaluate_nonexistent_document_returns_404(self):
        """POST /api/readiness/evaluate/{doc_id} returns 404 for non-existent doc"""
        response = requests.post(f"{BASE_URL}/api/readiness/evaluate/nonexistent-doc-id-12345")
        assert response.status_code == 404, f"Expected 404 for non-existent doc, got {response.status_code}"
        print("PASS: evaluate/nonexistent-doc returns 404")

    def test_reevaluate_all_status_transitions_structure(self):
        """Verify status_transitions in reevaluate-all response have correct structure"""
        response = requests.post(f"{BASE_URL}/api/readiness/reevaluate-all?limit=3")
        assert response.status_code == 200, f"reevaluate-all failed: {response.status_code}"
        
        data = response.json()
        transitions = data.get("status_transitions", [])
        
        # If there are transitions, verify their structure
        for t in transitions:
            assert "doc_id" in t, "Missing doc_id in transition"
            assert "from" in t, "Missing from in transition"
            assert "to" in t, "Missing to in transition"
            assert "old_confidence" in t, "Missing old_confidence in transition"
            assert "new_confidence" in t, "Missing new_confidence in transition"
        
        print(f"PASS: status_transitions structure valid - {len(transitions)} transitions found")

    def test_reevaluate_all_vendor_corrections_structure(self):
        """Verify vendor_corrections in reevaluate-all response have correct structure"""
        response = requests.post(f"{BASE_URL}/api/readiness/reevaluate-all?limit=3")
        assert response.status_code == 200, f"reevaluate-all failed: {response.status_code}"
        
        data = response.json()
        vendor_corrections = data.get("vendor_corrections", [])
        
        # If there are vendor corrections, verify their structure
        for vc in vendor_corrections:
            assert "vendor_no" in vc, "Missing vendor_no in vendor_corrections"
            assert "correction_count" in vc, "Missing correction_count in vendor_corrections"
            assert "signals" in vc, "Missing signals in vendor_corrections"
            assert isinstance(vc["signals"], list), "signals should be a list"
        
        print(f"PASS: vendor_corrections structure valid - {len(vendor_corrections)} vendors with corrections")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
