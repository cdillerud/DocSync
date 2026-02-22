"""
Tests for AP Invoice Workflow Queue APIs
Tests the workflow queue endpoints: status-counts, vendor-pending, bc-validation-pending, 
bc-validation-failed, data-correction-pending, ready-for-approval
Also tests document intake workflow_status initialization
"""
import pytest
import requests
import os
import uuid
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_USERNAME = "admin"
TEST_PASSWORD = "admin"


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def auth_token(api_client):
    """Get authentication token"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "username": TEST_USERNAME,
        "password": TEST_PASSWORD
    })
    assert response.status_code == 200, f"Auth failed: {response.text}"
    return response.json().get("token")


@pytest.fixture(scope="module")
def authenticated_client(api_client, auth_token):
    """Session with auth header"""
    api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
    return api_client


class TestAuthEndpoint:
    """Test authentication endpoint"""
    
    def test_login_success(self, api_client):
        """Test successful login"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert "user" in data
        assert data["user"]["username"] == TEST_USERNAME
        assert data["user"]["role"] == "administrator"


class TestWorkflowStatusCounts:
    """Test GET /api/workflows/ap_invoice/status-counts"""
    
    def test_status_counts_returns_200(self, authenticated_client):
        """Test status counts endpoint returns 200 with expected structure"""
        response = authenticated_client.get(f"{BASE_URL}/api/workflows/ap_invoice/status-counts")
        assert response.status_code == 200
        data = response.json()
        
        # Check expected fields
        assert "status_counts" in data
        assert "total" in data
        assert "exception_queue_total" in data
        
        # status_counts should be a dict
        assert isinstance(data["status_counts"], dict)
        # total should be a number
        assert isinstance(data["total"], int)
        # exception_queue_total should be a number
        assert isinstance(data["exception_queue_total"], int)
    
    def test_status_counts_matches_total(self, authenticated_client):
        """Test that sum of status counts equals total"""
        response = authenticated_client.get(f"{BASE_URL}/api/workflows/ap_invoice/status-counts")
        assert response.status_code == 200
        data = response.json()
        
        counts_sum = sum(data["status_counts"].values())
        assert counts_sum == data["total"], f"Sum of counts {counts_sum} != total {data['total']}"


class TestVendorPendingQueue:
    """Test GET /api/workflows/ap_invoice/vendor-pending"""
    
    def test_vendor_pending_returns_200(self, authenticated_client):
        """Test vendor pending queue returns 200 with expected structure"""
        response = authenticated_client.get(f"{BASE_URL}/api/workflows/ap_invoice/vendor-pending")
        assert response.status_code == 200
        data = response.json()
        
        assert "documents" in data
        assert "total" in data
        assert "queue" in data
        assert data["queue"] == "vendor_pending"
        assert isinstance(data["documents"], list)
        assert isinstance(data["total"], int)
    
    def test_vendor_pending_with_filters(self, authenticated_client):
        """Test vendor pending queue with filter parameters"""
        response = authenticated_client.get(
            f"{BASE_URL}/api/workflows/ap_invoice/vendor-pending",
            params={"skip": 0, "limit": 10, "min_amount": 0}
        )
        assert response.status_code == 200
        data = response.json()
        assert "documents" in data
        assert len(data["documents"]) <= 10


class TestBcValidationPendingQueue:
    """Test GET /api/workflows/ap_invoice/bc-validation-pending"""
    
    def test_bc_validation_pending_returns_200(self, authenticated_client):
        """Test BC validation pending queue returns 200"""
        response = authenticated_client.get(f"{BASE_URL}/api/workflows/ap_invoice/bc-validation-pending")
        assert response.status_code == 200
        data = response.json()
        
        assert "documents" in data
        assert "total" in data
        assert "queue" in data
        assert data["queue"] == "bc_validation_pending"
    
    def test_bc_validation_pending_with_pagination(self, authenticated_client):
        """Test BC validation pending with pagination"""
        response = authenticated_client.get(
            f"{BASE_URL}/api/workflows/ap_invoice/bc-validation-pending",
            params={"skip": 0, "limit": 25}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["documents"]) <= 25


class TestBcValidationFailedQueue:
    """Test GET /api/workflows/ap_invoice/bc-validation-failed"""
    
    def test_bc_validation_failed_returns_200(self, authenticated_client):
        """Test BC validation failed queue returns 200"""
        response = authenticated_client.get(f"{BASE_URL}/api/workflows/ap_invoice/bc-validation-failed")
        assert response.status_code == 200
        data = response.json()
        
        assert "documents" in data
        assert "total" in data
        assert "queue" in data
        assert data["queue"] == "bc_validation_failed"
    
    def test_bc_validation_failed_with_filters(self, authenticated_client):
        """Test BC validation failed with validation_error filter"""
        response = authenticated_client.get(
            f"{BASE_URL}/api/workflows/ap_invoice/bc-validation-failed",
            params={"validation_error": "test"}
        )
        assert response.status_code == 200


class TestDataCorrectionPendingQueue:
    """Test GET /api/workflows/ap_invoice/data-correction-pending"""
    
    def test_data_correction_pending_returns_200(self, authenticated_client):
        """Test data correction pending queue returns 200"""
        response = authenticated_client.get(f"{BASE_URL}/api/workflows/ap_invoice/data-correction-pending")
        assert response.status_code == 200
        data = response.json()
        
        assert "documents" in data
        assert "total" in data
        assert "queue" in data
        assert data["queue"] == "data_correction_pending"


class TestReadyForApprovalQueue:
    """Test GET /api/workflows/ap_invoice/ready-for-approval"""
    
    def test_ready_for_approval_returns_200(self, authenticated_client):
        """Test ready for approval queue returns 200"""
        response = authenticated_client.get(f"{BASE_URL}/api/workflows/ap_invoice/ready-for-approval")
        assert response.status_code == 200
        data = response.json()
        
        assert "documents" in data
        assert "total" in data
        assert "queue" in data
        assert data["queue"] == "ready_for_approval"
    
    def test_ready_for_approval_with_amount_filters(self, authenticated_client):
        """Test ready for approval with amount filters"""
        response = authenticated_client.get(
            f"{BASE_URL}/api/workflows/ap_invoice/ready-for-approval",
            params={"min_amount": 100, "max_amount": 10000}
        )
        assert response.status_code == 200
        data = response.json()
        assert "documents" in data


class TestDocumentIntake:
    """Test POST /api/documents/intake creates document with workflow_status=captured"""
    
    def test_intake_creates_document_with_captured_status(self, authenticated_client):
        """Test that document intake sets workflow_status to 'captured'"""
        # Create a test file
        test_content = f"Test invoice content {uuid.uuid4()}"
        test_filename = f"TEST_workflow_invoice_{uuid.uuid4().hex[:8]}.txt"
        
        # Remove Content-Type header for multipart form data
        headers = dict(authenticated_client.headers)
        if "Content-Type" in headers:
            del headers["Content-Type"]
        
        files = {
            'file': (test_filename, test_content.encode(), 'text/plain')
        }
        form_data = {
            'source': 'test_workflow',
            'sender': 'test@example.com',
            'subject': 'Test Workflow Invoice'
        }
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=form_data,
            headers={"Authorization": headers.get("Authorization", "")}
        )
        
        assert response.status_code == 200, f"Intake failed: {response.text}"
        data = response.json()
        
        # Check document created with workflow_status = captured
        assert "document" in data
        doc = data["document"]
        assert doc["workflow_status"] == "captured", f"Expected 'captured', got '{doc['workflow_status']}'"
        
        # Check workflow_history was initialized
        assert "workflow_history" in doc
        assert len(doc["workflow_history"]) >= 1
        
        # First history entry should be ON_CAPTURE event
        first_history = doc["workflow_history"][0]
        assert first_history["to_status"] == "captured"
        assert first_history["event"] == "on_capture"
        
        # Cleanup - delete the test document
        doc_id = doc["id"]
        cleanup_response = authenticated_client.delete(f"{BASE_URL}/api/documents/{doc_id}")
        print(f"Cleanup: Deleted test document {doc_id}")
    
    def test_intake_workflow_history_has_timestamp(self, authenticated_client):
        """Test that workflow history entries have timestamps"""
        test_content = f"Test invoice {uuid.uuid4()}"
        test_filename = f"TEST_timestamp_test_{uuid.uuid4().hex[:8]}.txt"
        
        headers = dict(authenticated_client.headers)
        if "Content-Type" in headers:
            del headers["Content-Type"]
        
        files = {
            'file': (test_filename, test_content.encode(), 'text/plain')
        }
        form_data = {
            'source': 'test_workflow'
        }
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=form_data,
            headers={"Authorization": headers.get("Authorization", "")}
        )
        
        assert response.status_code == 200
        data = response.json()
        doc = data["document"]
        
        # Check timestamp exists
        assert "workflow_status_updated_utc" in doc
        first_history = doc["workflow_history"][0]
        assert "timestamp" in first_history
        
        # Cleanup
        doc_id = doc["id"]
        authenticated_client.delete(f"{BASE_URL}/api/documents/{doc_id}")


class TestWorkflowMetrics:
    """Test GET /api/workflows/ap_invoice/metrics"""
    
    def test_metrics_returns_200(self, authenticated_client):
        """Test workflow metrics endpoint returns 200"""
        response = authenticated_client.get(f"{BASE_URL}/api/workflows/ap_invoice/metrics")
        assert response.status_code == 200
        data = response.json()
        
        # Should have metrics structure
        assert isinstance(data, dict)
    
    def test_metrics_with_days_param(self, authenticated_client):
        """Test workflow metrics with days parameter"""
        response = authenticated_client.get(
            f"{BASE_URL}/api/workflows/ap_invoice/metrics",
            params={"days": 7}
        )
        assert response.status_code == 200


class TestDashboardIntegration:
    """Test dashboard stats include proper data"""
    
    def test_dashboard_stats_returns_200(self, authenticated_client):
        """Test dashboard stats endpoint"""
        response = authenticated_client.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200
        data = response.json()
        
        assert "total_documents" in data
        assert "by_status" in data
        assert "demo_mode" in data


class TestAllQueueEndpointsConsistency:
    """Test all queue endpoints return consistent structure"""
    
    QUEUE_ENDPOINTS = [
        ("vendor-pending", "vendor_pending"),
        ("bc-validation-pending", "bc_validation_pending"),
        ("bc-validation-failed", "bc_validation_failed"),
        ("data-correction-pending", "data_correction_pending"),
        ("ready-for-approval", "ready_for_approval"),
    ]
    
    @pytest.mark.parametrize("endpoint,expected_queue", QUEUE_ENDPOINTS)
    def test_queue_endpoint_structure(self, authenticated_client, endpoint, expected_queue):
        """Test each queue endpoint has consistent structure"""
        response = authenticated_client.get(
            f"{BASE_URL}/api/workflows/ap_invoice/{endpoint}"
        )
        assert response.status_code == 200, f"Endpoint {endpoint} failed: {response.text}"
        
        data = response.json()
        assert "documents" in data, f"Endpoint {endpoint} missing 'documents'"
        assert "total" in data, f"Endpoint {endpoint} missing 'total'"
        assert "queue" in data, f"Endpoint {endpoint} missing 'queue'"
        assert data["queue"] == expected_queue, f"Endpoint {endpoint} queue mismatch: expected {expected_queue}, got {data['queue']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
