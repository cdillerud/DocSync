"""
Test Suite for Sales Order Type Awareness (Warehouse vs Drop-Ship)

Tests the order_type field (warehouse|drop_ship), endpoint to edit order type,
warehouse inventory logic, and drop-ship order flow without inventory movements.
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test SO IDs for isolation
TEST_DS_SO = "SO-TEST-DROP-001"  # Pre-existing drop-ship SO per main agent context
TEST_WH_SO = f"SO-WH-TEST-{uuid.uuid4().hex[:6].upper()}"


class TestReconcileSalesOrderDropShip:
    """Tests for POST /reconcile-sales-order rejection for drop-ship"""

    def test_reconcile_rejects_drop_ship(self):
        """Reconcile should return 422 for drop-ship orders"""
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order",
            json={"sales_order_id": TEST_DS_SO, "lines": [], "cancelled": False}
        )
        assert res.status_code == 422, f"Expected 422, got {res.status_code}: {res.text}"
        data = res.json()
        assert "drop" in data.get("detail", "").lower() or "no inventory" in data.get("detail", "").lower()
        print(f"PASS: POST /reconcile-sales-order for drop_ship returns 422: {data.get('detail')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
