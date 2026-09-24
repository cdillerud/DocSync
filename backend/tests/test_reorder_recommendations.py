"""
Test suite for GET /api/inventory-ledger/reorder-recommendations endpoint.
Tests reorder recommendation generation based on derived balances.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Hormel Foods workspace (has SHORT items for testing)
HORMEL_CUSTOMER_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"
# Healthy Corp workspace (all healthy inventory)
HEALTHY_CUSTOMER_ID = "0be8d686-c173-4f8e-afb6-32a0676cd68d"


class TestRegressionEndpoints:
    """Regression tests for existing inventory ledger endpoints"""


    def test_reconcile_sales_order_still_works(self):
        """REGRESSION: POST /api/inventory-ledger/reconcile-sales-order responds correctly"""
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order",
            json={
                "sales_order_id": "SO-TEST-NONEXISTENT",
                "lines": [],
                "cancelled": False
            }
        )
        # Returns 422 when no existing order_commitment found (expected validation behavior)
        assert response.status_code == 422, f"Expected 422 for non-existent SO, got {response.status_code}: {response.text}"
        assert "No order_commitment found" in response.text
        print("✓ REGRESSION: Reconcile sales order endpoint responds correctly (422 for no commitments)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
