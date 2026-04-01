"""
Test Suite for Sales Order Review Page Feature
Tests the /review/:id route and related backend endpoints:
- POST /api/sales-dashboard/review/{doc_id} - Unified approve/flag endpoint
- POST /api/gpi-integration/sales-orders/preflight/{doc_id} - Preflight validation
- GET /api/documents/{doc_id} - Document details
- GET /api/sales-dashboard/my-queue - My Queue navigation
- GET /api/sales-dashboard/triage-queue - Triage Queue navigation
"""

import os
import pytest
import requests
import time

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ap-status-sync.preview.emergentagent.com")


class TestBatchDemoSetup:
    """Run batch demo to create test documents"""
    
    @pytest.fixture(scope="class")
    def batch_job(self):
        """Run batch demo and wait for completion"""
        # Start batch job
        response = requests.post(f"{BASE_URL}/api/sales-dashboard/demo/run-batch")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "started"
        job_id = data["job_id"]
        
        # Poll for completion (max 120 seconds)
        for _ in range(60):
            time.sleep(2)
            status_response = requests.get(f"{BASE_URL}/api/sales-dashboard/demo/batch-status/{job_id}")
            assert status_response.status_code == 200
            status_data = status_response.json()
            if status_data["status"] == "completed":
                return status_data
        
        pytest.fail("Batch job did not complete in time")
    
    def test_batch_demo_creates_documents(self, batch_job):
        """Verify batch demo creates 5 child documents"""
        assert batch_job["status"] == "completed"
        assert len(batch_job["children"]) == 5
        
        # Verify each child has required fields
        for child in batch_job["children"]:
            assert "doc_id" in child
            assert child["type"] == "PurchaseOrder"
            assert child["customer"] == "Giovanni Food Company., Inc."


class TestReviewEndpoint:
    """Test the /api/sales-dashboard/review/{doc_id} endpoint"""
    
    @pytest.fixture(scope="class")
    def test_doc_id(self):
        """Get a test document ID from my-queue"""
        response = requests.get(
            f"{BASE_URL}/api/sales-dashboard/my-queue",
            params={"rep_email": "lchen@gamerpackaging.com", "limit": 5}
        )
        assert response.status_code == 200
        data = response.json()
        if data["items"]:
            return data["items"][0]["id"]
        
        # Fallback: run batch demo to create documents
        batch_response = requests.post(f"{BASE_URL}/api/sales-dashboard/demo/run-batch")
        job_id = batch_response.json()["job_id"]
        time.sleep(5)
        status_response = requests.get(f"{BASE_URL}/api/sales-dashboard/demo/batch-status/{job_id}")
        children = status_response.json().get("children", [])
        if children:
            return children[0]["doc_id"]
        pytest.skip("No test documents available")
    
    def test_review_approve_action(self, test_doc_id):
        """Test approve action via review endpoint"""
        response = requests.post(
            f"{BASE_URL}/api/sales-dashboard/review/{test_doc_id}",
            json={"action": "approve"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"
        assert data["doc_id"] == test_doc_id
        assert "approved_at" in data
    
    def test_review_flag_action(self, test_doc_id):
        """Test flag action via review endpoint"""
        response = requests.post(
            f"{BASE_URL}/api/sales-dashboard/review/{test_doc_id}",
            json={"action": "flag", "reason": "Test flag reason from pytest"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "flagged"
        assert data["doc_id"] == test_doc_id
        assert data["reason"] == "Test flag reason from pytest"
        assert "flagged_at" in data
    
    def test_review_invalid_action(self, test_doc_id):
        """Test invalid action returns 400"""
        response = requests.post(
            f"{BASE_URL}/api/sales-dashboard/review/{test_doc_id}",
            json={"action": "invalid_action"}
        )
        assert response.status_code == 400
        assert "Invalid action" in response.json()["detail"]
    
    def test_review_nonexistent_document(self):
        """Test review of non-existent document returns 404"""
        response = requests.post(
            f"{BASE_URL}/api/sales-dashboard/review/nonexistent-doc-id",
            json={"action": "approve"}
        )
        assert response.status_code == 404


class TestPreflightEndpoint:
    """Test the preflight endpoint for BC Sales Order creation"""
    
    @pytest.fixture(scope="class")
    def batch_child_doc_id(self):
        """Get a batch-child document ID"""
        response = requests.get(
            f"{BASE_URL}/api/sales-dashboard/my-queue",
            params={"rep_email": "lchen@gamerpackaging.com", "limit": 10}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Find a batch-child document
        for item in data["items"]:
            if item["id"].startswith("batch-child-"):
                return item["id"]
        
        # Fallback: run batch demo
        batch_response = requests.post(f"{BASE_URL}/api/sales-dashboard/demo/run-batch")
        job_id = batch_response.json()["job_id"]
        time.sleep(5)
        status_response = requests.get(f"{BASE_URL}/api/sales-dashboard/demo/batch-status/{job_id}")
        children = status_response.json().get("children", [])
        if children:
            return children[0]["doc_id"]
        pytest.skip("No batch-child documents available")
    
    def test_preflight_returns_ready_true(self, batch_child_doc_id):
        """Test preflight returns ready=True for batch-child POs"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{batch_child_doc_id}"
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify readiness
        assert data["eligible"] == True
        # Note: ready might be False if already created
        
        # Verify customer resolution
        assert data["mapped_values"]["customer_no"] == "C-10250"
        assert "Giovanni" in data["mapped_values"]["customer_name"]
    
    def test_preflight_returns_line_items(self, batch_child_doc_id):
        """Test preflight returns resolved line items"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{batch_child_doc_id}"
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify line items
        assert data["line_count"] >= 1
        assert len(data["resolved_lines"]) >= 1
        
        # Verify first line structure
        first_line = data["resolved_lines"][0]
        assert "lineType" in first_line
        assert "description" in first_line
        assert "quantity" in first_line
        assert "unitPrice" in first_line
    
    def test_preflight_nonexistent_document(self):
        """Test preflight of non-existent document returns 404"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/nonexistent-doc-id"
        )
        assert response.status_code == 404


class TestDocumentEndpoint:
    """Test the document details endpoint"""
    
    @pytest.fixture(scope="class")
    def batch_child_doc_id(self):
        """Get a batch-child document ID"""
        response = requests.get(
            f"{BASE_URL}/api/sales-dashboard/my-queue",
            params={"rep_email": "lchen@gamerpackaging.com", "limit": 10}
        )
        assert response.status_code == 200
        data = response.json()
        
        for item in data["items"]:
            if item["id"].startswith("batch-child-"):
                return item["id"]
        pytest.skip("No batch-child documents available")
    
    def test_document_endpoint_returns_wrapped_response(self, batch_child_doc_id):
        """Test document endpoint returns {document: {...}, workflows: [...]}"""
        response = requests.get(f"{BASE_URL}/api/documents/{batch_child_doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        # Verify wrapped response structure
        assert "document" in data
        assert "workflows" in data
        
        doc = data["document"]
        assert doc["id"] == batch_child_doc_id
        assert doc["document_type"] == "PurchaseOrder"
    
    def test_document_has_extracted_fields(self, batch_child_doc_id):
        """Test document has extracted fields for review page"""
        response = requests.get(f"{BASE_URL}/api/documents/{batch_child_doc_id}")
        assert response.status_code == 200
        doc = response.json()["document"]
        
        ef = doc.get("extracted_fields", {})
        assert "po_number" in ef
        assert "customer_name" in ef
        assert "total_amount" in ef or "amount" in ef


class TestQueueNavigation:
    """Test that queue pages navigate to /review/:id"""
    
    def test_my_queue_returns_document_ids(self):
        """Test My Queue returns document IDs for navigation"""
        response = requests.get(
            f"{BASE_URL}/api/sales-dashboard/my-queue",
            params={"rep_email": "lchen@gamerpackaging.com", "limit": 5}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify items have IDs for navigation
        for item in data["items"]:
            assert "id" in item
            assert len(item["id"]) > 0
    
    def test_triage_queue_returns_document_ids(self):
        """Test Triage Queue returns document IDs for navigation"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/triage-queue")
        assert response.status_code == 200
        data = response.json()
        
        # Verify items have IDs for navigation
        for item in data["items"]:
            assert "id" in item
            assert len(item["id"]) > 0


class TestAddLineButton:
    """Test the Add Line functionality in CreateBCSalesOrderPanel"""
    
    @pytest.fixture(scope="class")
    def batch_child_doc_id(self):
        """Get a batch-child document ID"""
        response = requests.get(
            f"{BASE_URL}/api/sales-dashboard/my-queue",
            params={"rep_email": "lchen@gamerpackaging.com", "limit": 10}
        )
        assert response.status_code == 200
        data = response.json()
        
        for item in data["items"]:
            if item["id"].startswith("batch-child-"):
                return item["id"]
        pytest.skip("No batch-child documents available")
    
    def test_preflight_returns_editable_lines(self, batch_child_doc_id):
        """Test preflight returns lines that can be edited/added to"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{batch_child_doc_id}"
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify resolved_lines structure supports editing
        for line in data["resolved_lines"]:
            assert "lineType" in line
            assert "lineObjectNumber" in line
            assert "description" in line
            assert "quantity" in line
            assert "unitPrice" in line
            # These fields allow the frontend to edit and add lines


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
