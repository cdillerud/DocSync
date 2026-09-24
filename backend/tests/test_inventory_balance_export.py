"""
Tests for GET /api/inventory-ledger/export endpoint (CSV export feature).
Tests CSV format, headers, status values, filtering, and regression checks.
"""
import pytest
import requests
import os
import uuid
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test customer workspace - Hormel Foods has data
TEST_CUSTOMER_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"


class TestExportRegression:
    """Regression tests for related endpoints"""
    
    
    
    def test_reconcile_sales_order_endpoint_exists(self):
        """POST /api/inventory-ledger/reconcile-sales-order endpoint available"""
        # Test with empty/cancelled order - just verify endpoint responds
        payload = {
            "sales_order_id": f"TEST-SO-{uuid.uuid4().hex[:8]}",
            "lines": [],
            "cancelled": True
        }
        response = requests.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json=payload)
        # Expect 200 (no-op for empty cancelled) or 422 (validation)
        assert response.status_code in [200, 422], f"Unexpected status: {response.status_code}"
        print(f"✓ reconcile-sales-order endpoint responds: {response.status_code}")
    
    def test_incoming_from_shortage_endpoint_exists(self):
        """POST /api/incoming-supply/from-shortage endpoint available"""
        payload = {
            "sales_order_id": f"TEST-SO-{uuid.uuid4().hex[:8]}",
            "lines": []
        }
        response = requests.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json=payload)
        # Expect 200 (empty lines = no-op) or 422 (validation)
        assert response.status_code in [200, 422], f"Unexpected status: {response.status_code}"
        print(f"✓ incoming-supply/from-shortage endpoint responds: {response.status_code}")
    


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
