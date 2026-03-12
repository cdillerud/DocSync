"""
GPI Integration Router Tests

Tests for the GPI Hub Integration BC extension API endpoints.
These endpoints provide integration with Business Central custom APIs.

Since the BC sandbox credentials in this environment are not valid,
endpoints that require BC connectivity will return 502 errors (expected).
The tests validate:
  - /status endpoint works without BC connectivity
  - Error handling for unreachable BC APIs
  - Request validation (422 for missing required fields)
  - Proper HTTP status codes
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestGPIIntegrationStatus:
    """Tests for /api/gpi-integration/status endpoint - works without BC credentials"""
    
    def test_status_endpoint_returns_200(self):
        """GET /status should return 200 with configuration info"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/status")
        assert response.status_code == 200
        
        data = response.json()
        assert "configured" in data
        assert "environment" in data
        assert "source_system" in data
        assert data["source_system"] == "GPI_HUB"
        assert "api_group" in data
        assert data["api_group"] == "gpi/integration/v1.0"
        print(f"Status endpoint returned: {data}")
    
    def test_status_shows_tenant_id_masked(self):
        """Status should mask tenant_id for security"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/status")
        data = response.json()
        
        # tenant_id should be masked (ends with ...)
        tenant_id = data.get("tenant_id", "")
        if tenant_id:
            assert "..." in tenant_id, "Tenant ID should be masked"


class TestGPIIntegrationCompanies:
    """Tests for /api/gpi-integration/companies endpoint"""
    
    def test_companies_endpoint_returns_502_when_bc_unreachable(self):
        """GET /companies should return 502 when BC API is unreachable"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/companies")
        
        # In this test environment, BC credentials are invalid
        # So we expect 502 (BC API error)
        assert response.status_code == 502
        
        data = response.json()
        assert "detail" in data
        assert "BC API error" in data["detail"]
        print(f"Companies endpoint returned expected 502: {data['detail'][:100]}")


class TestGPIIntegrationSalesOrders:
    """Tests for /api/gpi-integration/sales-orders endpoint"""
    
    def test_sales_orders_missing_customer_no_returns_422(self):
        """POST /sales-orders without customer_no should return 422"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders",
            json={}
        )
        assert response.status_code == 422
        
        data = response.json()
        assert "detail" in data
        # Verify the error mentions customer_no is required
        error_detail = str(data["detail"])
        assert "customer_no" in error_detail or "Field required" in error_detail
        print(f"Validation error for missing customer_no: {data}")
    
    def test_sales_orders_valid_body_returns_502_when_bc_unreachable(self):
        """POST /sales-orders with valid body returns 502 when BC unreachable"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders",
            json={
                "customer_no": "C001",
                "external_doc_no": "PO-12345",
                "order_date": "2026-01-15",
                "source_doc_id": "doc-123",
                "idempotency_key": "test-key-001",
                "transaction_id": "txn-001"
            }
        )
        
        # Should return 502 because BC API is unreachable
        assert response.status_code == 502
        data = response.json()
        assert "detail" in data
        print(f"Sales order creation returned expected 502: {data['detail'][:100]}")


class TestGPIIntegrationPurchaseInvoices:
    """Tests for /api/gpi-integration/purchase-invoices endpoint"""
    
    def test_purchase_invoices_missing_vendor_no_returns_422(self):
        """POST /purchase-invoices without vendor_no should return 422"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices",
            json={}
        )
        assert response.status_code == 422
        
        data = response.json()
        assert "detail" in data
        error_detail = str(data["detail"])
        assert "vendor_no" in error_detail or "Field required" in error_detail
        print(f"Validation error for missing vendor_no: {data}")
    
    def test_purchase_invoices_valid_body_returns_502_when_bc_unreachable(self):
        """POST /purchase-invoices with valid body returns 502 when BC unreachable"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices",
            json={
                "vendor_no": "V001",
                "vendor_invoice_no": "INV-2026-001",
                "document_date": "2026-01-15",
                "posting_date": "2026-01-15",
                "source_doc_id": "doc-456",
                "idempotency_key": "test-key-002",
                "transaction_id": "txn-002"
            }
        )
        
        assert response.status_code == 502
        data = response.json()
        assert "detail" in data
        print(f"Purchase invoice creation returned expected 502: {data['detail'][:100]}")


class TestGPIIntegrationCustomers:
    """Tests for /api/gpi-integration/customers endpoint"""
    
    def test_customers_missing_name_returns_422(self):
        """POST /customers without name should return 422"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/customers",
            json={}
        )
        assert response.status_code == 422
        
        data = response.json()
        assert "detail" in data
        error_detail = str(data["detail"])
        assert "name" in error_detail or "Field required" in error_detail
        print(f"Validation error for missing name: {data}")
    
    def test_customers_valid_body_returns_502_when_bc_unreachable(self):
        """POST /customers with valid body returns 502 when BC unreachable"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/customers",
            json={
                "name": "Test Customer Inc.",
                "address": "123 Main St",
                "city": "Chicago",
                "state_code": "IL",
                "postal_code": "60601",
                "country_code": "US",
                "source_doc_id": "doc-789",
                "idempotency_key": "test-key-003"
            }
        )
        
        assert response.status_code == 502
        data = response.json()
        assert "detail" in data
        print(f"Customer creation returned expected 502: {data['detail'][:100]}")


class TestGPIIntegrationVendors:
    """Tests for /api/gpi-integration/vendors endpoint"""
    
    def test_vendors_missing_name_returns_422(self):
        """POST /vendors without name should return 422"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/vendors",
            json={}
        )
        assert response.status_code == 422
        
        data = response.json()
        assert "detail" in data
        error_detail = str(data["detail"])
        assert "name" in error_detail or "Field required" in error_detail
        print(f"Validation error for missing name: {data}")
    
    def test_vendors_valid_body_returns_502_when_bc_unreachable(self):
        """POST /vendors with valid body returns 502 when BC unreachable"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/vendors",
            json={
                "name": "Test Vendor LLC",
                "address": "456 Oak Ave",
                "city": "New York",
                "state_code": "NY",
                "postal_code": "10001",
                "country_code": "US",
                "source_doc_id": "doc-012",
                "idempotency_key": "test-key-004"
            }
        )
        
        assert response.status_code == 502
        data = response.json()
        assert "detail" in data
        print(f"Vendor creation returned expected 502: {data['detail'][:100]}")


class TestGPIIntegrationLogs:
    """Tests for /api/gpi-integration/logs endpoint"""
    
    def test_logs_returns_502_when_bc_unreachable(self):
        """GET /logs returns 502 when BC API is unreachable"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/logs")
        
        assert response.status_code == 502
        data = response.json()
        assert "detail" in data
        assert "BC API error" in data["detail"]
        print(f"Logs endpoint returned expected 502: {data['detail'][:100]}")
    
    def test_logs_accepts_query_parameters(self):
        """GET /logs accepts filter query parameters"""
        response = requests.get(
            f"{BASE_URL}/api/gpi-integration/logs",
            params={
                "record_type": "SalesOrder",
                "status": "Completed",
                "top": 10
            }
        )
        
        # Should still return 502 because BC is unreachable
        # but the query params should be accepted (no 400/422)
        assert response.status_code == 502
        print("Logs endpoint accepted query parameters without validation error")


class TestHealthEndpointRegression:
    """Regression test - ensure /api/health still works"""
    
    def test_health_endpoint_returns_healthy(self):
        """GET /api/health should return healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        assert "service" in data
        print(f"Health endpoint OK: {data}")
