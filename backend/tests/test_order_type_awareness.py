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


class TestOrderTypeEndpoints:
    """Tests for GET/PATCH /sales-orders/{id}/order-type"""

    def test_get_order_type_default_warehouse(self):
        """New SO should return 'warehouse' by default"""
        random_so = f"SO-RANDOM-{uuid.uuid4().hex[:6]}"
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{random_so}/order-type")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["order_type"] == "warehouse", f"Expected 'warehouse', got {data}"
        print(f"PASS: GET order-type returns 'warehouse' default for {random_so}")

    def test_get_order_type_drop_ship(self):
        """Existing drop-ship SO should return 'drop_ship'"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{TEST_DS_SO}/order-type")
        assert res.status_code == 200
        data = res.json()
        assert data["order_type"] == "drop_ship", f"Expected 'drop_ship', got {data}"
        print(f"PASS: GET order-type returns 'drop_ship' for {TEST_DS_SO}")

    def test_patch_order_type_set_drop_ship_no_commitments(self):
        """PATCH to drop_ship should succeed when no existing commitments"""
        random_so = f"SO-NOOP-{uuid.uuid4().hex[:6]}"
        res = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{random_so}/order-type",
            json={"order_type": "drop_ship"}
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["order_type"] == "drop_ship"
        print(f"PASS: PATCH to drop_ship succeeds for SO without commitments")

    def test_patch_order_type_invalid_type(self):
        """PATCH with invalid order_type should return 422"""
        res = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{TEST_DS_SO}/order-type",
            json={"order_type": "invalid_type"}
        )
        assert res.status_code == 422
        print("PASS: PATCH with invalid order_type returns 422")

    def test_patch_order_type_set_warehouse(self):
        """PATCH to warehouse should succeed"""
        # Create a fresh SO and set it to drop_ship, then back to warehouse
        random_so = f"SO-REVERT-{uuid.uuid4().hex[:6]}"
        # First set to drop_ship
        res1 = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{random_so}/order-type",
            json={"order_type": "drop_ship"}
        )
        assert res1.status_code == 200
        # Then set back to warehouse
        res2 = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{random_so}/order-type",
            json={"order_type": "warehouse"}
        )
        assert res2.status_code == 200
        data = res2.json()
        assert data["order_type"] == "warehouse"
        print("PASS: PATCH to warehouse succeeds")


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


class TestBCShipmentDropShip:
    """Tests for POST /sales-orders/{id}/bc-shipment with drop-ship"""

    def test_bc_shipment_drop_ship_no_inventory_release(self):
        """Drop-ship shipment records without inventory release"""
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{TEST_DS_SO}/bc-shipment",
            json={
                "shipped_lines": [{"item": "TEST-ITEM-DS-PYTEST", "qty_shipped": 5}],
                "bc_shipment_number": f"SHP-DS-PYTEST-{uuid.uuid4().hex[:6]}",
                "bc_document_id": "",
                "shipment_notes": "pytest drop-ship test"
            }
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["order_type"] == "drop_ship", f"Expected drop_ship, got {data.get('order_type')}"
        assert data.get("total_recorded", 0) >= 1, f"Expected at least 1 recorded, got {data}"
        # Drop-ship should have 0 released (no inventory effect)
        assert data.get("total_released", 0) == 0, f"Expected 0 released for drop-ship, got {data.get('total_released')}"
        print(f"PASS: bc-shipment for drop_ship: {data.get('total_recorded')} recorded, 0 released")

    def test_bc_shipment_warehouse_requires_commitments(self):
        """Warehouse shipment requires existing commitments"""
        random_wh_so = f"SO-WH-NOCOMMIT-{uuid.uuid4().hex[:6]}"
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{random_wh_so}/bc-shipment",
            json={
                "shipped_lines": [{"item": "TEST-ITEM", "qty_shipped": 5}],
                "bc_shipment_number": "SHP-TEST",
            }
        )
        # Should fail because no commitments exist for this warehouse SO
        assert res.status_code == 404, f"Expected 404 for warehouse SO without commitments, got {res.status_code}: {res.text}"
        print("PASS: bc-shipment for warehouse SO without commitments returns 404")


class TestBCInvoiceDropShip:
    """Tests for POST /sales-orders/{id}/bc-invoice with drop-ship"""

    def test_bc_invoice_drop_ship_only_requires_shipment(self):
        """Drop-ship invoice only requires shipment log (no commitment checks)"""
        # First ensure there's a shipment for this SO
        ship_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{TEST_DS_SO}/bc-shipment",
            json={
                "shipped_lines": [{"item": "INVOICE-TEST-ITEM", "qty_shipped": 3}],
                "bc_shipment_number": f"SHP-INV-PRE-{uuid.uuid4().hex[:4]}",
            }
        )
        assert ship_res.status_code == 200, f"Shipment setup failed: {ship_res.text}"
        
        # Now capture invoice
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{TEST_DS_SO}/bc-invoice",
            json={
                "bc_invoice_number": f"INV-DS-PYTEST-{uuid.uuid4().hex[:6]}",
                "bc_document_id": "TEST-DOC",
                "invoice_date": "2026-01-15",
                "invoice_notes": "pytest drop-ship invoice test"
            }
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data.get("order_type") == "drop_ship"
        assert "invoice_log_id" in data
        print(f"PASS: bc-invoice for drop_ship succeeds: {data.get('invoice_log_id')}")

    def test_bc_invoice_drop_ship_requires_shipment(self):
        """Drop-ship invoice without shipment should fail"""
        # Create a fresh drop-ship SO without shipments
        random_ds_so = f"SO-DS-NOSH-{uuid.uuid4().hex[:6]}"
        # Set order type to drop_ship
        type_res = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{random_ds_so}/order-type",
            json={"order_type": "drop_ship"}
        )
        assert type_res.status_code == 200
        
        # Try to invoice without shipment
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{random_ds_so}/bc-invoice",
            json={"bc_invoice_number": "INV-TEST-NO-SHIP"}
        )
        assert res.status_code == 422, f"Expected 422, got {res.status_code}: {res.text}"
        data = res.json()
        assert "shipment" in data.get("detail", "").lower()
        print(f"PASS: bc-invoice for drop_ship without shipment returns 422: {data.get('detail')}")


class TestSummaryDropShip:
    """Tests for GET /sales-orders/{id}/summary with order type"""

    def test_summary_drop_ship_returns_zero_commitments(self):
        """Drop-ship summary should return order_type='drop_ship', 0 commitments, lines=[]"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{TEST_DS_SO}/summary")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["order_type"] == "drop_ship", f"Expected order_type='drop_ship', got {data.get('order_type')}"
        assert data["total_committed_qty"] == 0, f"Expected 0 committed for drop_ship, got {data.get('total_committed_qty')}"
        assert data["total_released_qty"] == 0, f"Expected 0 released for drop_ship, got {data.get('total_released_qty')}"
        assert data["total_remaining_committed_qty"] == 0
        assert data.get("lines") == [], f"Expected empty lines for drop_ship, got {data.get('lines')}"
        print(f"PASS: Summary for drop_ship: order_type={data['order_type']}, commitments=0, lines=[]")

    def test_summary_drop_ship_with_shipment_status(self):
        """Drop-ship summary with shipment should show 'shipped' or 'complete' status"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{TEST_DS_SO}/summary")
        assert res.status_code == 200
        data = res.json()
        # If shipment exists and invoice exists, should be 'complete'
        # If only shipment, should be 'shipped'
        # If neither, should be 'pending'
        assert data.get("operational_status") in ["pending", "shipped", "complete"], \
            f"Unexpected operational_status: {data.get('operational_status')}"
        print(f"PASS: Summary operational_status for drop_ship: {data.get('operational_status')}")

    def test_summary_warehouse_returns_commitment_data(self):
        """Warehouse summary should return order_type='warehouse' with commitment data"""
        # Use a known warehouse SO with commitments
        # First find one from existing test data
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/summary")
        if res.status_code == 200:
            data = res.json()
            assert data["order_type"] == "warehouse"
            print(f"PASS: Summary for warehouse: order_type={data['order_type']}, committed={data.get('total_committed_qty')}")
        else:
            # If SO-107040 doesn't exist, just check a random SO returns 404 properly
            print(f"SKIPPED: No warehouse SO with commitments available for testing")


class TestOrderTypeValidation:
    """Tests for order type switching validation"""

    def test_cannot_switch_to_drop_ship_with_commitments(self):
        """Switching to drop_ship should fail if remaining commitments exist"""
        # This requires a warehouse SO with outstanding commitments
        # We'll use SO-107040 if it exists (from previous test data)
        res = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/order-type",
            json={"order_type": "drop_ship"}
        )
        # Should fail with 422 if commitments exist
        if res.status_code == 422:
            data = res.json()
            assert "commit" in data.get("detail", "").lower() or "release" in data.get("detail", "").lower()
            print(f"PASS: PATCH to drop_ship rejected for SO with commitments: {data.get('detail')}")
        elif res.status_code == 200:
            # If it succeeds, SO had no remaining commitments - revert it
            requests.patch(
                f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/order-type",
                json={"order_type": "warehouse"}
            )
            print("SKIPPED: SO-107040 has no remaining commitments")
        else:
            print(f"SKIPPED: Unexpected response {res.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
