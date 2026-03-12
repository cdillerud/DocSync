"""
BC Purchase Invoice from Document API Tests

Tests the Purchase Invoice preflight validation and creation-from-document flow
for AP_Invoice documents. Similar pattern to Sales Order but for vendor/AP Invoice resolution.

Test document IDs:
- AP_Invoice: 80c7ab51-0cdb-48cc-b39c-b5d8a9c27c85 (eligible for PI creation)
- Sales_Order: 44b2e236-c1ab-4e0e-9c23-23f542d68a71 (not eligible for PI creation)
"""

import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test document IDs
AP_INVOICE_DOC_ID = "80c7ab51-0cdb-48cc-b39c-b5d8a9c27c85"  # AP_Invoice - eligible
SALES_ORDER_DOC_ID = "44b2e236-c1ab-4e0e-9c23-23f542d68a71"  # Sales_Order - not eligible
NONEXISTENT_DOC_ID = "nonexistent-doc-id-12345"


@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestPurchaseInvoicePreflightOnAPInvoice:
    """Tests for preflight validation on AP_Invoice documents (eligible type)"""

    def test_preflight_returns_eligible_true(self, api_client):
        """Preflight on AP_Invoice should return eligible=true"""
        response = api_client.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices/preflight/{AP_INVOICE_DOC_ID}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["eligible"] is True

    def test_preflight_returns_ready_true_with_vendor(self, api_client):
        """Preflight on AP_Invoice should return ready=true since vendor is resolved"""
        response = api_client.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices/preflight/{AP_INVOICE_DOC_ID}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True
        assert data["already_created"] is False

    def test_preflight_returns_correct_vendor(self, api_client):
        """Preflight should resolve vendor to CARGOMO"""
        response = api_client.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices/preflight/{AP_INVOICE_DOC_ID}"
        )
        assert response.status_code == 200
        data = response.json()
        mv = data["mapped_values"]
        assert mv["vendor_no"] == "CARGOMO"
        assert "Cargo" in mv["vendor_name"]
        assert mv["vendor_match_method"] == "validation"
        assert mv["vendor_match_confidence"] >= 0.9

    def test_preflight_returns_correct_invoice_no(self, api_client):
        """Preflight should return vendor invoice number 126156299-AR"""
        response = api_client.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices/preflight/{AP_INVOICE_DOC_ID}"
        )
        assert response.status_code == 200
        data = response.json()
        mv = data["mapped_values"]
        assert mv["vendor_invoice_no"] == "126156299-AR"

    def test_preflight_returns_correct_dates(self, api_client):
        """Preflight should return extracted document date and due date"""
        response = api_client.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices/preflight/{AP_INVOICE_DOC_ID}"
        )
        assert response.status_code == 200
        data = response.json()
        mv = data["mapped_values"]
        assert mv["document_date"]  # Should have a date
        assert mv["document_date_source"] == "extracted"
        assert mv["posting_date"]  # Should have posting date
        assert mv["due_date"]  # Should have due date

    def test_preflight_returns_five_line_items(self, api_client):
        """Preflight should return 5 line items"""
        response = api_client.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices/preflight/{AP_INVOICE_DOC_ID}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["line_count"] == 5
        assert len(data["line_items"]) == 5

    def test_preflight_returns_correct_total_amount(self, api_client):
        """Preflight should return total amount of $2785"""
        response = api_client.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices/preflight/{AP_INVOICE_DOC_ID}"
        )
        assert response.status_code == 200
        data = response.json()
        mv = data["mapped_values"]
        assert mv["total_amount"] == 2785.0

    def test_preflight_returns_idempotency_key(self, api_client):
        """Preflight should return a deterministic idempotency key"""
        response = api_client.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices/preflight/{AP_INVOICE_DOC_ID}"
        )
        assert response.status_code == 200
        data = response.json()
        mv = data["mapped_values"]
        assert mv["idempotency_key"].startswith("PI_")
        assert len(mv["idempotency_key"]) > 10


class TestPurchaseInvoicePreflightOnSalesOrder:
    """Tests for preflight validation on Sales_Order documents (not eligible)"""

    def test_preflight_returns_eligible_false(self, api_client):
        """Preflight on Sales_Order should return eligible=false"""
        response = api_client.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices/preflight/{SALES_ORDER_DOC_ID}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["eligible"] is False

    def test_preflight_returns_ready_false(self, api_client):
        """Preflight on Sales_Order should return ready=false"""
        response = api_client.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices/preflight/{SALES_ORDER_DOC_ID}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is False

    def test_preflight_returns_error_for_ineligible_type(self, api_client):
        """Preflight should return error for ineligible document type"""
        response = api_client.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices/preflight/{SALES_ORDER_DOC_ID}"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["errors"]) > 0
        assert "not eligible" in data["errors"][0].lower() or "Sales_Order" in data["errors"][0]


class TestPurchaseInvoicePreflightNotFound:
    """Tests for preflight validation on nonexistent documents"""

    def test_preflight_returns_404_for_nonexistent_doc(self, api_client):
        """Preflight on nonexistent doc should return 404"""
        response = api_client.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices/preflight/{NONEXISTENT_DOC_ID}"
        )
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()


class TestCreatePurchaseInvoiceFromDocument:
    """Tests for Purchase Invoice creation from document"""

    def test_create_from_ap_invoice_returns_502_bc_unreachable(self, api_client):
        """Create from AP_Invoice should return 502 (BC unreachable in preview env)"""
        response = api_client.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices/from-document/{AP_INVOICE_DOC_ID}",
            params={"vendor_no_override": "CARGOMO"}
        )
        # BC is unreachable in preview env, so we expect 502
        assert response.status_code == 502
        data = response.json()
        assert "BC API error" in data["detail"] or "400" in data["detail"]

    def test_create_from_sales_order_returns_422_not_eligible(self, api_client):
        """Create from Sales_Order should return 422 (not eligible)"""
        response = api_client.post(
            f"{BASE_URL}/api/gpi-integration/purchase-invoices/from-document/{SALES_ORDER_DOC_ID}",
            params={"vendor_no_override": "CARGOMO"}
        )
        assert response.status_code == 422
        data = response.json()
        assert "not eligible" in data["detail"].lower()


class TestRegressionEndpoints:
    """Regression tests for existing endpoints"""

    def test_gpi_integration_status(self, api_client):
        """GET /api/gpi-integration/status should still work"""
        response = api_client.get(f"{BASE_URL}/api/gpi-integration/status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True

    def test_health_endpoint(self, api_client):
        """GET /api/health should still work"""
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
