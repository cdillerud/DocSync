"""
BC Sales Order from Document Feature Tests

Tests for the Create BC Sales Order action endpoints:
- POST /api/gpi-integration/sales-orders/preflight/{doc_id} - Preflight validation
- POST /api/gpi-integration/sales-orders/from-document/{doc_id} - Create sales order

Test Documents:
- Sales_Order: 44b2e236-c1ab-4e0e-9c23-23f542d68a71 (eligible)
- AP_Invoice: 80c7ab51-0cdb-48cc-b39c-b5d8a9c27c85 (not eligible)

Expected behavior:
- Preflight returns mapped values, warnings, eligibility for any doc
- from-document returns 502 when BC is unreachable (expected in preview env)
- from-document returns 422 for missing customer or ineligible doc type
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test document IDs
SALES_ORDER_DOC_ID = "44b2e236-c1ab-4e0e-9c23-23f542d68a71"
AP_INVOICE_DOC_ID = "80c7ab51-0cdb-48cc-b39c-b5d8a9c27c85"
NONEXISTENT_DOC_ID = "nonexistent-doc-id-12345"


class TestPreflightForEligibleDoc:
    """Tests for preflight endpoint with eligible Sales_Order document"""
    
    def test_preflight_returns_200_for_eligible_doc(self):
        """Preflight should return 200 for existing document"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{SALES_ORDER_DOC_ID}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"Preflight for Sales_Order doc returned 200")
    
    def test_preflight_returns_eligible_true_for_sales_order(self):
        """Preflight should return eligible=true for Sales_Order doc"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{SALES_ORDER_DOC_ID}")
        data = response.json()
        
        assert data["eligible"] is True, f"Expected eligible=True, got {data.get('eligible')}"
        print(f"Sales_Order doc is eligible for BC Sales Order creation")
    
    def test_preflight_returns_mapped_values(self):
        """Preflight should return mapped_values with extracted fields"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{SALES_ORDER_DOC_ID}")
        data = response.json()
        
        assert "mapped_values" in data
        mv = data["mapped_values"]
        
        # Should have key fields
        assert "customer_no" in mv
        assert "customer_name" in mv
        assert "external_doc_no" in mv
        assert "order_date" in mv
        assert "idempotency_key" in mv
        assert "bc_company" in mv
        assert "bc_environment" in mv
        
        print(f"Mapped values: customer_name={mv.get('customer_name')}, external_doc_no={mv.get('external_doc_no')}, order_date={mv.get('order_date')}")
    
    def test_preflight_returns_line_items(self):
        """Preflight should return line items from document"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{SALES_ORDER_DOC_ID}")
        data = response.json()
        
        assert "line_items" in data
        assert "line_count" in data
        assert data["line_count"] >= 0
        
        # Verify line item structure
        if data["line_items"]:
            li = data["line_items"][0]
            assert "description" in li
            assert "quantity" in li
            assert "unit_price" in li
            assert "total" in li
        
        print(f"Line items count: {data['line_count']}")
    
    def test_preflight_returns_warnings_for_missing_customer(self):
        """Preflight should return warnings when customer not mapped"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{SALES_ORDER_DOC_ID}")
        data = response.json()
        
        # The test doc has no customer_no, should show warning
        if not data["mapped_values"].get("customer_no"):
            assert "missing_fields" in data
            assert "customer_no" in data.get("missing_fields", [])
            assert len(data.get("warnings", [])) > 0
            print(f"Warnings for missing customer: {data.get('warnings')}")
        else:
            print("Customer mapped - no warnings expected")


class TestPreflightForIneligibleDoc:
    """Tests for preflight endpoint with ineligible AP_Invoice document"""
    
    def test_preflight_returns_200_for_ineligible_doc(self):
        """Preflight should return 200 even for ineligible doc (shows status)"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{AP_INVOICE_DOC_ID}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("Preflight for AP_Invoice doc returned 200")
    
    def test_preflight_returns_eligible_false_for_ap_invoice(self):
        """Preflight should return eligible=false for AP_Invoice doc"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{AP_INVOICE_DOC_ID}")
        data = response.json()
        
        assert data["eligible"] is False, f"Expected eligible=False for AP_Invoice, got {data.get('eligible')}"
        print("AP_Invoice doc is NOT eligible for BC Sales Order creation")
    
    def test_preflight_returns_error_for_ineligible_type(self):
        """Preflight should include error message for ineligible doc type"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{AP_INVOICE_DOC_ID}")
        data = response.json()
        
        assert "errors" in data
        assert len(data["errors"]) > 0
        
        # Error should mention the doc type is not eligible
        error_text = " ".join(data["errors"])
        assert "AP_Invoice" in error_text or "not eligible" in error_text
        print(f"Error for ineligible type: {data['errors']}")


class TestPreflightForNonexistentDoc:
    """Tests for preflight endpoint with nonexistent document"""
    
    def test_preflight_returns_404_for_nonexistent_doc(self):
        """Preflight should return 404 for nonexistent document"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{NONEXISTENT_DOC_ID}")
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()
        print("Preflight returns 404 for nonexistent doc")


class TestFromDocumentMissingCustomer:
    """Tests for from-document endpoint without customer"""
    
    def test_from_document_returns_422_without_customer(self):
        """From-document without customer should return 422"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{SALES_ORDER_DOC_ID}")
        
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print("From-document without customer returns 422")
    
    def test_from_document_returns_missing_customer_error(self):
        """From-document should return missing_customer error type"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{SALES_ORDER_DOC_ID}")
        data = response.json()
        
        assert "detail" in data
        detail = data["detail"]
        
        # Should be structured error
        if isinstance(detail, dict):
            assert detail.get("error") == "missing_customer"
            assert "message" in detail
            print(f"Missing customer error: {detail['message']}")
        else:
            # Or string containing missing customer info
            assert "customer" in detail.lower()
            print(f"Missing customer error: {detail}")


class TestFromDocumentWithCustomerOverride:
    """Tests for from-document endpoint with customer override"""
    
    def test_from_document_with_customer_returns_502(self):
        """From-document with customer should attempt BC creation and return 502"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{SALES_ORDER_DOC_ID}",
            params={"customer_no_override": "C00100"}
        )
        
        # Expected: 502 because BC is unreachable in preview env
        assert response.status_code == 502, f"Expected 502 (BC unreachable), got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data
        assert "BC API error" in data["detail"]
        print("From-document with customer returns 502 (BC unreachable - expected)")


class TestFromDocumentIneligibleType:
    """Tests for from-document endpoint with ineligible document type"""
    
    def test_from_document_ineligible_returns_422(self):
        """From-document for AP_Invoice should return 422"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{AP_INVOICE_DOC_ID}",
            params={"customer_no_override": "C00100"}
        )
        
        assert response.status_code == 422, f"Expected 422 for ineligible type, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data
        assert "not eligible" in data["detail"].lower() or "AP_Invoice" in data["detail"]
        print("From-document for AP_Invoice returns 422 (not eligible)")


class TestFromDocumentNonexistent:
    """Tests for from-document endpoint with nonexistent document"""
    
    def test_from_document_returns_404_for_nonexistent(self):
        """From-document for nonexistent doc should return 404"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{NONEXISTENT_DOC_ID}",
            params={"customer_no_override": "C00100"}
        )
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()
        print("From-document for nonexistent doc returns 404")


class TestRegressionEndpoints:
    """Regression tests for existing endpoints"""
    
    def test_health_endpoint_still_works(self):
        """GET /api/health should return healthy"""
        response = requests.get(f"{BASE_URL}/api/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print("Health endpoint OK")
    
    def test_gpi_integration_status_still_works(self):
        """GET /api/gpi-integration/status should return config"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/status")
        
        assert response.status_code == 200
        data = response.json()
        assert "configured" in data
        assert "source_system" in data
        assert data["source_system"] == "GPI_HUB"
        print("GPI Integration status endpoint OK")
