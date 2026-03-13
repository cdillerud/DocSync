"""
Sales Order Commitment Reconciliation Tests (Iteration 59)

Tests the POST /api/inventory-ledger/reconcile-sales-order endpoint:
- Decrease line qty creates order_release movement
- Increase line qty creates additional order_commitment movement  
- Unchanged qty creates no movement (action=none)
- Multi-line reconciliation (simultaneous increase + decrease)
- Cancel releases all remaining net commitments
- Repeat cancel is idempotent (adjustments=0)
- Negative qty returns HTTP 422
- Non-existent SO returns HTTP 422
- derive_balances committed recalculates correctly after adjustments
- available = on_hand + incoming - committed after edit and cancel

Regression tests for existing endpoints.
"""

import pytest
import requests
import os
import uuid
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestSOReconciliation:
    """Tests for POST /api/inventory-ledger/reconcile-sales-order endpoint."""
    
    @pytest.fixture(autouse=True)
    def setup_test_workspace(self):
        """Create a test workspace with seed data and commitments for each test."""
        self.unique_id = str(uuid.uuid4())[:8]
        self.workspace_name = f"TEST_RECONCILE_{self.unique_id}"
        self.workspace_code = f"TR{self.unique_id[:4].upper()}"
        self.item1 = f"TEST_ITEM_A_{self.unique_id}"
        self.item2 = f"TEST_ITEM_B_{self.unique_id}"
        self.so_ref = f"SO-RECONCILE-{self.unique_id}"
        
        # Create workspace
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/customers", json={
            "name": self.workspace_name,
            "code": self.workspace_code,
            "negative_balance_policy": "warn_only"
        })
        assert resp.status_code == 200, f"Failed to create workspace: {resp.text}"
        self.workspace_id = resp.json()["id"]
        
        # Seed opening balances: 1000 each for item1 and item2
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/seed", json={
            "rows": [
                {"item": self.item1, "item_description": "Test Item A", "warehouse": "MAIN", 
                 "ownership_type": "customer_owned", "quantity": 1000, "unit_of_measure": "EA"},
                {"item": self.item2, "item_description": "Test Item B", "warehouse": "MAIN",
                 "ownership_type": "customer_owned", "quantity": 1000, "unit_of_measure": "EA"}
            ]
        })
        assert resp.status_code == 200, f"Failed to seed balances: {resp.text}"
        
        # Create initial commitments: 100 for item1, 200 for item2
        for item, qty in [(self.item1, 100), (self.item2, 200)]:
            resp = requests.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/movements", json={
                "item": item,
                "item_description": f"Commitment for {item}",
                "warehouse": "MAIN",
                "ownership_type": "customer_owned",
                "movement_type": "order_commitment",
                "quantity_delta": -qty,  # Negative = committed out
                "unit_of_measure": "EA",
                "source_type": "sales_order_commitment",
                "reference_type": "sales_order",
                "reference_id": self.so_ref,
                "notes": f"Initial commitment for test SO"
            })
            assert resp.status_code == 200, f"Failed to create commitment for {item}: {resp.text}"
        
        yield
        
        # Cleanup: deactivate workspace
        requests.put(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}", json={"active": False})
    
    def _get_balances(self, item=None):
        """Helper to get current balances."""
        params = {"item": item} if item else {}
        resp = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/balances", params=params)
        assert resp.status_code == 200
        return resp.json()["balances"]
    
    def test_decrease_qty_creates_release(self):
        """Decreasing line qty should create an order_release movement."""
        # Initial: committed=100 for item1
        balances_before = self._get_balances(self.item1)
        assert len(balances_before) == 1
        assert balances_before[0]["committed"] == 100
        assert balances_before[0]["available"] == 900  # 1000 - 100
        
        # Reconcile: decrease to 70 (release 30)
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json={
            "sales_order_id": self.so_ref,
            "lines": [{"item": self.item1, "qty": 70}],
            "cancelled": False
        })
        assert resp.status_code == 200, f"Reconcile failed: {resp.text}"
        data = resp.json()
        
        assert data["adjustments"] == 1, f"Expected 1 adjustment, got {data['adjustments']}"
        assert len(data["per_line"]) == 1
        line_result = data["per_line"][0]
        assert line_result["item"] == self.item1
        assert line_result["previous_committed"] == 100
        assert line_result["new_qty"] == 70
        assert line_result["delta"] == -30
        assert line_result["action"] == "release"
        
        # Verify balances: committed should now be 70, available should be 930
        balances_after = self._get_balances(self.item1)
        assert balances_after[0]["committed"] == 70, f"Committed should be 70, got {balances_after[0]['committed']}"
        assert balances_after[0]["available"] == 930, f"Available should be 930, got {balances_after[0]['available']}"
        print(f"PASS: Decrease qty creates release - committed went from 100 to {balances_after[0]['committed']}")
    
    def test_increase_qty_creates_commitment(self):
        """Increasing line qty should create an additional order_commitment movement."""
        # Initial: committed=100 for item1
        balances_before = self._get_balances(self.item1)
        assert balances_before[0]["committed"] == 100
        
        # Reconcile: increase to 150 (add 50 commitment)
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json={
            "sales_order_id": self.so_ref,
            "lines": [{"item": self.item1, "qty": 150}],
            "cancelled": False
        })
        assert resp.status_code == 200, f"Reconcile failed: {resp.text}"
        data = resp.json()
        
        assert data["adjustments"] == 1
        line_result = data["per_line"][0]
        assert line_result["action"] == "commit"
        assert line_result["delta"] == 50
        assert line_result["previous_committed"] == 100
        assert line_result["new_qty"] == 150
        
        # Verify balances
        balances_after = self._get_balances(self.item1)
        assert balances_after[0]["committed"] == 150, f"Committed should be 150, got {balances_after[0]['committed']}"
        assert balances_after[0]["available"] == 850  # 1000 - 150
        print(f"PASS: Increase qty creates commitment - committed went from 100 to {balances_after[0]['committed']}")
    
    def test_unchanged_qty_no_movement(self):
        """Unchanged qty should create no movement (action=none)."""
        # Initial: committed=100 for item1
        balances_before = self._get_balances(self.item1)
        
        # Reconcile: same qty (100)
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json={
            "sales_order_id": self.so_ref,
            "lines": [{"item": self.item1, "qty": 100}],
            "cancelled": False
        })
        assert resp.status_code == 200, f"Reconcile failed: {resp.text}"
        data = resp.json()
        
        assert data["adjustments"] == 0, f"Expected 0 adjustments, got {data['adjustments']}"
        line_result = data["per_line"][0]
        assert line_result["action"] == "none"
        assert line_result["delta"] == 0
        
        # Verify balances unchanged
        balances_after = self._get_balances(self.item1)
        assert balances_after[0]["committed"] == balances_before[0]["committed"]
        print(f"PASS: Unchanged qty creates no movement - committed stays at {balances_after[0]['committed']}")
    
    def test_multi_line_reconciliation(self):
        """Multi-line reconciliation with simultaneous increase and decrease."""
        # Initial: item1=100, item2=200
        
        # Reconcile: item1 decrease to 50, item2 increase to 300
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json={
            "sales_order_id": self.so_ref,
            "lines": [
                {"item": self.item1, "qty": 50},   # decrease from 100
                {"item": self.item2, "qty": 300}   # increase from 200
            ],
            "cancelled": False
        })
        assert resp.status_code == 200, f"Reconcile failed: {resp.text}"
        data = resp.json()
        
        assert data["adjustments"] == 2, f"Expected 2 adjustments, got {data['adjustments']}"
        
        # Check per_line results
        results_by_item = {r["item"]: r for r in data["per_line"]}
        
        assert results_by_item[self.item1]["action"] == "release"
        assert results_by_item[self.item1]["delta"] == -50
        
        assert results_by_item[self.item2]["action"] == "commit"
        assert results_by_item[self.item2]["delta"] == 100
        
        # Verify balances
        balances1 = self._get_balances(self.item1)
        balances2 = self._get_balances(self.item2)
        assert balances1[0]["committed"] == 50
        assert balances2[0]["committed"] == 300
        print(f"PASS: Multi-line reconciliation - item1 committed={balances1[0]['committed']}, item2 committed={balances2[0]['committed']}")
    
    def test_cancel_releases_all(self):
        """Cancel should release all remaining net commitments."""
        # Initial: item1=100, item2=200
        
        # Cancel the SO
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json={
            "sales_order_id": self.so_ref,
            "lines": [],  # Not needed for cancel
            "cancelled": True
        })
        assert resp.status_code == 200, f"Cancel failed: {resp.text}"
        data = resp.json()
        
        # Should have 2 adjustments (one release per item)
        assert data["adjustments"] == 2, f"Expected 2 adjustments for cancel, got {data['adjustments']}"
        
        # Check per_line results
        results_by_item = {r["item"]: r for r in data["per_line"]}
        
        assert results_by_item[self.item1]["action"] == "release"
        assert results_by_item[self.item1]["previous_committed"] == 100
        assert results_by_item[self.item1]["new_qty"] == 0
        
        assert results_by_item[self.item2]["action"] == "release"
        assert results_by_item[self.item2]["previous_committed"] == 200
        assert results_by_item[self.item2]["new_qty"] == 0
        
        # Verify balances: committed should be 0
        balances1 = self._get_balances(self.item1)
        balances2 = self._get_balances(self.item2)
        assert balances1[0]["committed"] == 0, f"Item1 committed should be 0, got {balances1[0]['committed']}"
        assert balances2[0]["committed"] == 0, f"Item2 committed should be 0, got {balances2[0]['committed']}"
        assert balances1[0]["available"] == 1000  # All inventory available
        assert balances2[0]["available"] == 1000
        print(f"PASS: Cancel releases all - both items now have committed=0, available=1000")
    
    def test_repeat_cancel_idempotent(self):
        """Repeat cancel should be idempotent (adjustments=0 if already cancelled)."""
        # First cancel
        resp1 = requests.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json={
            "sales_order_id": self.so_ref,
            "cancelled": True
        })
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["adjustments"] == 2  # Initial cancel releases both
        
        # Second cancel (repeat)
        resp2 = requests.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json={
            "sales_order_id": self.so_ref,
            "cancelled": True
        })
        assert resp2.status_code == 200, f"Repeat cancel failed: {resp2.text}"
        data2 = resp2.json()
        
        # Should have 0 adjustments since already cancelled
        assert data2["adjustments"] == 0, f"Expected 0 adjustments on repeat cancel, got {data2['adjustments']}"
        
        # All per_line should have action=none
        for line_result in data2["per_line"]:
            assert line_result["action"] == "none", f"Expected action=none, got {line_result['action']}"
        
        print(f"PASS: Repeat cancel is idempotent - adjustments=0 on second cancel")
    
    def test_negative_qty_returns_422(self):
        """Negative quantity should return HTTP 422."""
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json={
            "sales_order_id": self.so_ref,
            "lines": [{"item": self.item1, "qty": -50}],
            "cancelled": False
        })
        assert resp.status_code == 422, f"Expected 422 for negative qty, got {resp.status_code}: {resp.text}"
        assert "negative" in resp.text.lower() or "Negative" in resp.text
        print(f"PASS: Negative qty returns 422 with message: {resp.json()['detail'][:100]}")
    
    def test_nonexistent_so_returns_422(self):
        """Non-existent SO should return HTTP 422."""
        fake_so = f"FAKE-SO-{uuid.uuid4()}"
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json={
            "sales_order_id": fake_so,
            "lines": [{"item": "ANY_ITEM", "qty": 10}],
            "cancelled": False
        })
        assert resp.status_code == 422, f"Expected 422 for non-existent SO, got {resp.status_code}: {resp.text}"
        assert "no order_commitment" in resp.text.lower() or "No order_commitment" in resp.text
        print(f"PASS: Non-existent SO returns 422 with message: {resp.json()['detail'][:100]}")
    
    def test_balances_after_reconciliation(self):
        """Verify derive_balances committed recalculates correctly after adjustments."""
        # Initial state
        balances_initial = self._get_balances()
        item1_initial = next(b for b in balances_initial if b["item"] == self.item1)
        assert item1_initial["on_hand"] == 1000
        assert item1_initial["committed"] == 100
        assert item1_initial["available"] == 900
        
        # Reconcile: decrease item1 to 25
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json={
            "sales_order_id": self.so_ref,
            "lines": [{"item": self.item1, "qty": 25}],
            "cancelled": False
        })
        assert resp.status_code == 200
        
        # Verify updated balances
        balances_after = self._get_balances(self.item1)
        assert balances_after[0]["on_hand"] == 1000  # unchanged
        assert balances_after[0]["committed"] == 25   # reduced
        assert balances_after[0]["available"] == 975  # increased
        
        print(f"PASS: Balances recalculate correctly - on_hand=1000, committed=25, available=975")
    
    def test_available_formula_after_edit_and_cancel(self):
        """Verify available = on_hand + incoming - committed after edit and cancel."""
        # Create incoming supply for item1
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/incoming", json={
            "item": self.item1,
            "item_description": "Incoming Test",
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "incoming_qty": 500,
            "unit_of_measure": "EA",
            "status": "ordered",  # Will count as incoming
            "source_reference": "PO-TEST-123"
        })
        assert resp.status_code == 200
        
        # Check balance: on_hand=1000, incoming=500, committed=100 -> available=1400
        balances = self._get_balances(self.item1)
        assert balances[0]["on_hand"] == 1000
        assert balances[0]["incoming"] == 500
        assert balances[0]["committed"] == 100
        assert balances[0]["available"] == 1400, f"Expected available=1400, got {balances[0]['available']}"
        
        # Reconcile: increase to 300 (committed becomes 300)
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json={
            "sales_order_id": self.so_ref,
            "lines": [{"item": self.item1, "qty": 300}],
            "cancelled": False
        })
        assert resp.status_code == 200
        
        # Check balance: on_hand=1000, incoming=500, committed=300 -> available=1200
        balances = self._get_balances(self.item1)
        assert balances[0]["committed"] == 300
        assert balances[0]["available"] == 1200, f"Expected available=1200, got {balances[0]['available']}"
        
        # Cancel the SO (committed becomes 0)
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json={
            "sales_order_id": self.so_ref,
            "cancelled": True
        })
        assert resp.status_code == 200
        
        # Check balance: on_hand=1000, incoming=500, committed=0 -> available=1500
        balances = self._get_balances(self.item1)
        assert balances[0]["committed"] == 0
        assert balances[0]["available"] == 1500, f"Expected available=1500, got {balances[0]['available']}"
        
        print(f"PASS: Available formula verified - after cancel: on_hand=1000, incoming=500, committed=0, available=1500")


class TestRegressionEndpoints:
    """Regression tests for existing endpoints."""
    
    @pytest.fixture(autouse=True)
    def setup_test_workspace(self):
        """Create a test workspace for regression tests."""
        self.unique_id = str(uuid.uuid4())[:8]
        self.workspace_name = f"TEST_REGRESSION_{self.unique_id}"
        self.workspace_code = f"RG{self.unique_id[:4].upper()}"
        self.item = f"TEST_ITEM_{self.unique_id}"
        self.so_ref = f"SO-REG-{self.unique_id}"
        
        # Create workspace
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/customers", json={
            "name": self.workspace_name,
            "code": self.workspace_code,
            "negative_balance_policy": "warn_only"
        })
        assert resp.status_code == 200
        self.workspace_id = resp.json()["id"]
        
        # Seed balance
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/seed", json={
            "rows": [{"item": self.item, "quantity": 500, "warehouse": "MAIN", "ownership_type": "customer_owned"}]
        })
        assert resp.status_code == 200
        
        # Create commitment
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/movements", json={
            "item": self.item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -100,
            "reference_type": "sales_order",
            "reference_id": self.so_ref
        })
        assert resp.status_code == 200
        
        yield
        
        requests.put(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}", json={"active": False})
    
    def test_release_endpoint_still_works(self):
        """REGRESSION: POST /api/inventory-ledger/release still works."""
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/release", json={
            "sales_order_id": self.so_ref,
            "lines": [{"item": self.item, "qty": 30}]
        })
        assert resp.status_code == 200, f"Release failed: {resp.text}"
        data = resp.json()
        assert data["released"] == 1
        print(f"PASS: Release endpoint still works - released 30 units")
    
    def test_incoming_supply_from_shortage_still_works(self):
        """REGRESSION: POST /api/incoming-supply/from-shortage still works."""
        resp = requests.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": self.so_ref,
            "lines": [{"item": self.item, "qty_needed": 200, "qty_available": 50}]
        })
        assert resp.status_code == 200, f"From-shortage failed: {resp.text}"
        data = resp.json()
        assert data["created"] == 1
        print(f"PASS: Incoming supply from shortage still works - created {data['created']} record")
    
    def test_incoming_supply_status_transitions_still_work(self):
        """REGRESSION: POST /api/incoming-supply/{id}/status transitions still work."""
        # First create an incoming supply
        resp = requests.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/incoming", json={
            "item": self.item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "incoming_qty": 100,
            "status": "planned"
        })
        assert resp.status_code == 200
        supply_id = resp.json()["id"]
        
        # Transition planned -> ordered
        resp = requests.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={"status": "ordered"})
        assert resp.status_code == 200, f"Transition failed: {resp.text}"
        assert resp.json()["supply"]["status"] == "ordered"
        print(f"PASS: Status transition planned->ordered works")
    
    def test_customers_list_still_works(self):
        """REGRESSION: GET /api/inventory-ledger/customers still lists workspaces."""
        resp = requests.get(f"{BASE_URL}/api/inventory-ledger/customers")
        assert resp.status_code == 200, f"List customers failed: {resp.text}"
        customers = resp.json()
        assert isinstance(customers, list)
        assert len(customers) > 0
        print(f"PASS: Customers list still works - found {len(customers)} workspaces")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
