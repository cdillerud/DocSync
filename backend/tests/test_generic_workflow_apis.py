"""
Test Multi-Document Type Workflow APIs
Tests the generic workflow endpoints for multi-doc_type support:
- GET /api/workflows/generic/queue?doc_type=AP_INVOICE
- GET /api/workflows/generic/status-counts-by-type
- GET /api/workflows/generic/metrics-by-type
- GET /api/workflows/ap_invoice/status-counts
- POST /api/documents/intake (doc_type, source_system, capture_channel)
"""

import pytest
import requests
import os
import io
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Module: Authentication & Setup
class TestAuthSetup:
    """Test basic authentication works"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token for tests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json().get("token")
    
    def test_login_success(self):
        """Verify login works with admin/admin"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["username"] == "admin"


# Module: Generic Queue API Tests
class TestGenericQueueAPI:
    """Test GET /api/workflows/generic/queue endpoint"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token for authenticated requests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        if response.status_code == 200:
            return response.json().get("token")
        pytest.skip("Authentication failed")
    
    def test_generic_queue_ap_invoice(self, auth_token):
        """Test queue API returns documents filtered by doc_type=AP_INVOICE"""
        response = requests.get(
            f"{BASE_URL}/api/workflows/generic/queue",
            params={"doc_type": "AP_INVOICE"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "documents" in data, "Response missing 'documents' field"
        assert "total" in data, "Response missing 'total' field"
        assert "doc_type" in data, "Response missing 'doc_type' field"
        assert data["doc_type"] == "AP_INVOICE", f"Expected doc_type='AP_INVOICE', got '{data.get('doc_type')}'"
        
        # Verify all returned documents are AP_INVOICE type
        for doc in data["documents"]:
            assert doc.get("doc_type") == "AP_INVOICE", f"Document {doc.get('id')} has wrong doc_type: {doc.get('doc_type')}"
    
    def test_generic_queue_sales_invoice(self, auth_token):
        """Test queue API returns documents filtered by doc_type=SALES_INVOICE"""
        response = requests.get(
            f"{BASE_URL}/api/workflows/generic/queue",
            params={"doc_type": "SALES_INVOICE"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "documents" in data
        assert data["doc_type"] == "SALES_INVOICE"
        
        # Verify all returned documents are SALES_INVOICE type
        for doc in data["documents"]:
            assert doc.get("doc_type") == "SALES_INVOICE"
    
    def test_generic_queue_purchase_order(self, auth_token):
        """Test queue API returns documents filtered by doc_type=PURCHASE_ORDER"""
        response = requests.get(
            f"{BASE_URL}/api/workflows/generic/queue",
            params={"doc_type": "PURCHASE_ORDER"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "documents" in data
        assert data["doc_type"] == "PURCHASE_ORDER"
    
    def test_generic_queue_with_status_filter(self, auth_token):
        """Test queue API with both doc_type and status filters"""
        response = requests.get(
            f"{BASE_URL}/api/workflows/generic/queue",
            params={"doc_type": "AP_INVOICE", "status": "captured"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "documents" in data
        assert data["doc_type"] == "AP_INVOICE"
        assert data["status"] == "captured"
        
        # Verify returned documents have correct status
        for doc in data["documents"]:
            assert doc.get("workflow_status") == "captured"
    
    def test_generic_queue_requires_doc_type(self, auth_token):
        """Test that doc_type is required parameter"""
        response = requests.get(
            f"{BASE_URL}/api/workflows/generic/queue",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        # Should fail with 422 Unprocessable Entity since doc_type is required
        assert response.status_code == 422, f"Expected 422 for missing doc_type, got {response.status_code}"


# Module: Status Counts by Type API Tests  
class TestStatusCountsByTypeAPI:
    """Test GET /api/workflows/generic/status-counts-by-type endpoint"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        if response.status_code == 200:
            return response.json().get("token")
        pytest.skip("Authentication failed")
    
    def test_status_counts_by_type_returns_structure(self, auth_token):
        """Test status-counts-by-type returns correct structure"""
        response = requests.get(
            f"{BASE_URL}/api/workflows/generic/status-counts-by-type",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "documents_by_type_and_status" in data, "Missing documents_by_type_and_status"
        assert "supported_doc_types" in data, "Missing supported_doc_types"
        assert "supported_statuses" in data, "Missing supported_statuses"
        
        # Verify supported_doc_types includes expected values
        doc_types = data["supported_doc_types"]
        assert "AP_INVOICE" in doc_types
        assert "SALES_INVOICE" in doc_types
        assert "PURCHASE_ORDER" in doc_types
        assert "OTHER" in doc_types
        
        # Verify we have 10 doc types as specified
        assert len(doc_types) == 10, f"Expected 10 doc types, got {len(doc_types)}"
    
    def test_status_counts_structure_per_type(self, auth_token):
        """Test each doc_type has correct status count structure"""
        response = requests.get(
            f"{BASE_URL}/api/workflows/generic/status-counts-by-type",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        doc_counts = data.get("documents_by_type_and_status", {})
        
        # Each doc_type entry should have 'statuses' dict and 'total' count
        for doc_type, type_data in doc_counts.items():
            assert "statuses" in type_data, f"Missing statuses for {doc_type}"
            assert "total" in type_data, f"Missing total for {doc_type}"
            assert isinstance(type_data["statuses"], dict)
            assert isinstance(type_data["total"], int)


# Module: Metrics by Type API Tests
class TestMetricsByTypeAPI:
    """Test GET /api/workflows/generic/metrics-by-type endpoint"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        if response.status_code == 200:
            return response.json().get("token")
        pytest.skip("Authentication failed")
    
    def test_metrics_by_type_returns_structure(self, auth_token):
        """Test metrics-by-type returns correct structure"""
        response = requests.get(
            f"{BASE_URL}/api/workflows/generic/metrics-by-type",
            params={"days": 30},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "metrics_by_type" in data, "Missing metrics_by_type field"
        assert "days" in data, "Missing days field"
        assert data["days"] == 30
    
    def test_metrics_by_type_with_doc_type_filter(self, auth_token):
        """Test metrics-by-type with specific doc_type filter"""
        response = requests.get(
            f"{BASE_URL}/api/workflows/generic/metrics-by-type",
            params={"days": 30, "doc_type": "AP_INVOICE"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "metrics_by_type" in data
        
        # When filtered by doc_type, should only have that type
        metrics = data.get("metrics_by_type", {})
        if metrics:  # Only check if there are results
            for doc_type in metrics.keys():
                assert doc_type == "AP_INVOICE", f"Expected only AP_INVOICE, got {doc_type}"


# Module: AP Invoice Status Counts API Tests
class TestAPInvoiceStatusCounts:
    """Test GET /api/workflows/ap_invoice/status-counts endpoint"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        if response.status_code == 200:
            return response.json().get("token")
        pytest.skip("Authentication failed")
    
    def test_ap_invoice_status_counts(self, auth_token):
        """Test AP Invoice specific status counts"""
        response = requests.get(
            f"{BASE_URL}/api/workflows/ap_invoice/status-counts",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "status_counts" in data, "Missing status_counts"
        assert "total" in data, "Missing total"


# Module: Document Intake API Tests
class TestDocumentIntakeAPI:
    """Test POST /api/documents/intake sets doc_type, source_system, capture_channel"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        if response.status_code == 200:
            return response.json().get("token")
        pytest.skip("Authentication failed")
    
    @pytest.fixture
    def cleanup_doc_ids(self):
        """Track created documents for cleanup"""
        doc_ids = []
        yield doc_ids
        
        # Cleanup after test
        for doc_id in doc_ids:
            try:
                response = requests.post(f"{BASE_URL}/api/auth/login", json={
                    "username": "admin", "password": "admin"
                })
                token = response.json().get("token")
                requests.delete(
                    f"{BASE_URL}/api/documents/{doc_id}",
                    headers={"Authorization": f"Bearer {token}"}
                )
            except Exception:
                pass
    
    def test_intake_sets_classification_fields(self, auth_token, cleanup_doc_ids):
        """Test that document intake sets doc_type, source_system, capture_channel"""
        # Create a test PDF-like file
        test_content = b"%PDF-1.4 Test invoice content for testing"
        files = {"file": ("TEST_invoice.pdf", io.BytesIO(test_content), "application/pdf")}
        data = {
            "source": "email",
            "sender": "test@example.com",
            "subject": "Test Invoice"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data,
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200, f"Intake failed: {response.text}"
        
        result = response.json()
        doc = result.get("document", {})
        doc_id = doc.get("id")
        
        if doc_id:
            cleanup_doc_ids.append(doc_id)
        
        # Verify classification fields are set
        assert "doc_type" in doc, "Missing doc_type field"
        assert "source_system" in doc, "Missing source_system field"
        assert "capture_channel" in doc, "Missing capture_channel field"
        
        # Verify source_system is GPI_HUB_NATIVE for native uploads
        assert doc["source_system"] == "GPI_HUB_NATIVE", f"Expected GPI_HUB_NATIVE, got {doc['source_system']}"
        
        # Verify capture_channel reflects the source (email)
        assert doc["capture_channel"] == "EMAIL", f"Expected EMAIL, got {doc['capture_channel']}"
        
        # Verify workflow_status is captured
        assert doc.get("workflow_status") == "captured", f"Expected workflow_status=captured, got {doc.get('workflow_status')}"
    
    def test_intake_workflow_history_created(self, auth_token, cleanup_doc_ids):
        """Test that document intake creates workflow history"""
        test_content = b"%PDF-1.4 Test content"
        files = {"file": ("TEST_workflow_history.pdf", io.BytesIO(test_content), "application/pdf")}
        data = {"source": "upload"}
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data,
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        result = response.json()
        doc = result.get("document", {})
        doc_id = doc.get("id")
        
        if doc_id:
            cleanup_doc_ids.append(doc_id)
        
        # Verify workflow_history exists and has at least one entry
        assert "workflow_history" in doc, "Missing workflow_history"
        assert len(doc["workflow_history"]) >= 1, "workflow_history is empty"
        
        # Verify first history entry is capture event
        first_entry = doc["workflow_history"][0]
        assert first_entry.get("event") == "on_capture", f"Expected on_capture event, got {first_entry.get('event')}"
        assert first_entry.get("to_status") == "captured"


# Module: Non-AP Document Workflow Tests
class TestNonAPDocumentWorkflow:
    """Test that non-AP documents skip vendor/BC validation steps"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        if response.status_code == 200:
            return response.json().get("token")
        pytest.skip("Authentication failed")
    
    def test_sales_invoice_in_queue(self, auth_token):
        """Test SALES_INVOICE documents appear in generic queue"""
        response = requests.get(
            f"{BASE_URL}/api/workflows/generic/queue",
            params={"doc_type": "SALES_INVOICE"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        # Verify structure is correct
        assert "documents" in data
        assert data["doc_type"] == "SALES_INVOICE"
        
        # Documents should NOT have AP-specific statuses
        for doc in data["documents"]:
            status = doc.get("workflow_status", "")
            assert status not in ["vendor_pending", "bc_validation_pending", "bc_validation_failed"], \
                f"SALES_INVOICE should not have AP-specific status: {status}"


# Module: Supported Doc Types Test
class TestSupportedDocTypes:
    """Test all 10 document types are supported"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin", "password": "admin"
        })
        if response.status_code == 200:
            return response.json().get("token")
        pytest.skip("Authentication failed")
    
    def test_all_doc_types_supported(self, auth_token):
        """Verify all 10 doc types are in supported_doc_types"""
        response = requests.get(
            f"{BASE_URL}/api/workflows/generic/status-counts-by-type",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        supported = data.get("supported_doc_types", [])
        
        expected_types = [
            "AP_INVOICE", "SALES_INVOICE", "PURCHASE_ORDER",
            "SALES_CREDIT_MEMO", "PURCHASE_CREDIT_MEMO",
            "STATEMENT", "REMINDER", "FINANCE_CHARGE_MEMO",
            "QUALITY_DOC", "OTHER"
        ]
        
        for doc_type in expected_types:
            assert doc_type in supported, f"Missing doc_type: {doc_type}"
    
    def test_generic_queue_accepts_all_types(self, auth_token):
        """Test generic queue endpoint accepts all supported doc_types"""
        doc_types = [
            "AP_INVOICE", "SALES_INVOICE", "PURCHASE_ORDER",
            "SALES_CREDIT_MEMO", "PURCHASE_CREDIT_MEMO", 
            "STATEMENT", "REMINDER", "FINANCE_CHARGE_MEMO",
            "QUALITY_DOC", "OTHER"
        ]
        
        for doc_type in doc_types:
            response = requests.get(
                f"{BASE_URL}/api/workflows/generic/queue",
                params={"doc_type": doc_type},
                headers={"Authorization": f"Bearer {auth_token}"}
            )
            assert response.status_code == 200, f"Failed for doc_type={doc_type}: {response.text}"
            
            data = response.json()
            assert data.get("doc_type") == doc_type


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
