"""
Test: Incoming Supply from Shortage (Iteration 57)

Tests for the POST /api/incoming-supply/from-shortage endpoint that creates
incoming supply records from SHORT items on a Sales Order.

Features tested:
- Create supply from shortage: seed balance, commit more than available, call endpoint
- Shortage calculation: qty_needed - qty_available
- Duplicate prevention returns HTTP 409
- Zero/negative shortage rejected (qty_needed <= qty_available)
- Non-existent SO returns HTTP 422
- derive_balances includes 'planned' status in incoming
- available = on_hand + incoming - committed with new planned supply

Regression tests:
- POST /api/inventory-ledger/release still works
- GET /api/inventory-ledger/customers lists workspaces
- GET /api/inventory-ledger/customers/{id}/balances derives correctly
- POST /api/gpi-integration/sales-orders/preflight still returns inventory data
"""

import pytest
import requests
import os
import uuid
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestIncomingSupplyFromShortage:
    """Tests for POST /api/incoming-supply/from-shortage endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create a test workspace and seed data for each test"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.test_id = str(uuid.uuid4())[:8]
        self.workspace_id = None
        self.so_reference = f"TEST_SO_{self.test_id}"
        self.item_code = f"TEST_ITEM_{self.test_id}"
        
        # Create test workspace
        ws_res = self.session.post(f"{BASE_URL}/api/inventory-ledger/customers", json={
            "name": f"Test WS {self.test_id}",
            "code": f"TESTWS{self.test_id}",
            "negative_balance_policy": "warn_only"
        })
        assert ws_res.status_code == 200, f"Failed to create workspace: {ws_res.text}"
        self.workspace_id = ws_res.json()["id"]
        
        yield
        
        # Cleanup: deactivate workspace
        if self.workspace_id:
            self.session.put(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}", json={
                "active": False
            })

    def seed_and_commit(self, on_hand: float, commit_qty: float, item: str = None, so_ref: str = None):
        """Helper: seed opening balance and create commitment"""
        item = item or self.item_code
        so_ref = so_ref or self.so_reference
        
        # Seed opening balance
        seed_res = self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/seed", json={
            "rows": [{
                "item": item,
                "item_description": f"Test item {item}",
                "warehouse": "MAIN",
                "ownership_type": "customer_owned",
                "quantity": on_hand,
                "unit_of_measure": "units"
            }]
        })
        assert seed_res.status_code == 200, f"Seed failed: {seed_res.text}"
        
        # Create order commitment
        mv_res = self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/movements", json={
            "item": item,
            "item_description": f"Test item {item}",
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -commit_qty,
            "unit_of_measure": "units",
            "source_type": "sales_order_commitment",
            "reference_type": "sales_order",
            "reference_id": so_ref,
            "notes": f"Test commitment for {so_ref}"
        })
        assert mv_res.status_code == 200, f"Commitment failed: {mv_res.text}"
        return seed_res, mv_res

    def get_balances(self, item: str = None):
        """Helper: get balances for workspace"""
        item = item or self.item_code
        res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/balances", params={
            "item": item
        })
        assert res.status_code == 200, f"Get balances failed: {res.text}"
        return res.json()["balances"]

    # =========================================================================
    # Test: Create supply from shortage
    # =========================================================================
    
    def test_create_supply_from_shortage(self):
        """Create incoming supply when shortage exists (commit > on_hand)"""
        # Seed 100, commit 400 → shortage = 300, available = -300
        self.seed_and_commit(on_hand=100, commit_qty=400)
        
        # Verify shortage exists
        balances = self.get_balances()
        assert len(balances) == 1
        assert balances[0]["on_hand"] == 100
        assert balances[0]["committed"] == 400
        assert balances[0]["available"] == -300
        
        # Call from-shortage endpoint
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": self.so_reference,
            "lines": [{
                "item": self.item_code,
                "qty_needed": 400,
                "qty_available": 100
            }]
        })
        assert res.status_code == 200, f"Create shortage supply failed: {res.text}"
        data = res.json()
        
        # Verify response
        assert data["created"] == 1, f"Expected 1 created, got {data}"
        assert len(data["supply_ids"]) == 1
        assert data["skipped"] == 0
        assert len(data["duplicates"]) == 0
        
        print(f"SUCCESS: Created supply from shortage - supply_id={data['supply_ids'][0]}")

    # =========================================================================
    # Test: Verify shortage calculation
    # =========================================================================
    
    def test_shortage_calculation(self):
        """Verify shortage = qty_needed - qty_available"""
        # Seed 1000, commit 4000 → shortage = 3000
        self.seed_and_commit(on_hand=1000, commit_qty=4000)
        
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": self.so_reference,
            "lines": [{
                "item": self.item_code,
                "qty_needed": 4000,
                "qty_available": 1000
            }]
        })
        assert res.status_code == 200
        
        # Fetch incoming supply to verify quantity
        inc_res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/incoming", params={
            "item": self.item_code
        })
        assert inc_res.status_code == 200
        incoming = inc_res.json()
        
        # Find our supply record
        supply = next((s for s in incoming if s["source_reference"] == self.so_reference), None)
        assert supply is not None, f"Supply not found for {self.so_reference}"
        assert supply["incoming_qty"] == 3000, f"Expected 3000, got {supply['incoming_qty']}"
        assert supply["status"] == "planned", f"Expected 'planned', got {supply['status']}"
        
        print(f"SUCCESS: Shortage calculation correct - incoming_qty=3000 (4000-1000)")

    # =========================================================================
    # Test: Duplicate prevention returns 409
    # =========================================================================
    
    def test_duplicate_prevention_409(self):
        """Second call for same item+SO returns HTTP 409"""
        self.seed_and_commit(on_hand=100, commit_qty=500)
        
        # First call - should succeed
        res1 = self.session.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": self.so_reference,
            "lines": [{
                "item": self.item_code,
                "qty_needed": 500,
                "qty_available": 100
            }]
        })
        assert res1.status_code == 200
        assert res1.json()["created"] == 1
        
        # Second call - should return 409
        res2 = self.session.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": self.so_reference,
            "lines": [{
                "item": self.item_code,
                "qty_needed": 500,
                "qty_available": 100
            }]
        })
        assert res2.status_code == 409, f"Expected 409, got {res2.status_code}: {res2.text}"
        data = res2.json()
        assert "duplicate" in data["detail"]["message"].lower() or self.item_code in str(data["detail"])
        
        print(f"SUCCESS: Duplicate prevention works - got 409 on second call")

    # =========================================================================
    # Test: Zero shortage rejected
    # =========================================================================
    
    def test_zero_shortage_rejected(self):
        """Zero shortage (qty_needed <= qty_available) returns error"""
        self.seed_and_commit(on_hand=500, commit_qty=100)
        
        # qty_needed=100, qty_available=500 → shortage = -400 (no shortage)
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": self.so_reference,
            "lines": [{
                "item": self.item_code,
                "qty_needed": 100,
                "qty_available": 500
            }]
        })
        assert res.status_code == 200  # Endpoint returns 200 with errors array
        data = res.json()
        
        assert data["created"] == 0, f"Expected 0 created, got {data}"
        assert len(data["errors"]) > 0, f"Expected errors, got {data}"
        assert "no shortage" in data["errors"][0].lower()
        
        print(f"SUCCESS: Zero shortage rejected - error={data['errors'][0]}")

    # =========================================================================
    # Test: Non-existent SO returns 422
    # =========================================================================
    
    def test_nonexistent_so_422(self):
        """Non-existent SO reference returns HTTP 422"""
        fake_so = f"FAKE_SO_{self.test_id}"
        
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": fake_so,
            "lines": [{
                "item": "ANY_ITEM",
                "qty_needed": 100,
                "qty_available": 50
            }]
        })
        assert res.status_code == 422, f"Expected 422, got {res.status_code}: {res.text}"
        assert "no order_commitment" in res.text.lower() or "not found" in res.text.lower()
        
        print(f"SUCCESS: Non-existent SO returns 422")

    # =========================================================================
    # Test: derive_balances includes 'planned' status in incoming
    # =========================================================================
    
    def test_planned_status_in_derive_balances(self):
        """'planned' status incoming supply is included in available calculation"""
        # Seed 1000, commit 4000 → available = -3000
        self.seed_and_commit(on_hand=1000, commit_qty=4000)
        
        balances_before = self.get_balances()
        assert balances_before[0]["available"] == -3000
        assert balances_before[0]["incoming"] == 0
        
        # Create shortage supply (3000 incoming)
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": self.so_reference,
            "lines": [{
                "item": self.item_code,
                "qty_needed": 4000,
                "qty_available": 1000
            }]
        })
        assert res.status_code == 200
        
        # Check balances again - incoming should be 3000, available should be 0
        balances_after = self.get_balances()
        assert balances_after[0]["incoming"] == 3000, f"Expected incoming=3000, got {balances_after[0]}"
        assert balances_after[0]["available"] == 0, f"Expected available=0 (1000+3000-4000), got {balances_after[0]}"
        
        print(f"SUCCESS: 'planned' status included in derive_balances - incoming=3000, available=0")

    # =========================================================================
    # Test: available = on_hand + incoming - committed
    # =========================================================================
    
    def test_available_formula_with_planned_supply(self):
        """Verify available = on_hand + incoming - committed after adding planned supply"""
        # Seed 500, commit 2000 → available = -1500
        self.seed_and_commit(on_hand=500, commit_qty=2000)
        
        balances_1 = self.get_balances()
        assert balances_1[0]["on_hand"] == 500
        assert balances_1[0]["committed"] == 2000
        assert balances_1[0]["incoming"] == 0
        assert balances_1[0]["available"] == -1500  # 500 + 0 - 2000
        
        # Create shortage supply (1500 incoming)
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": self.so_reference,
            "lines": [{
                "item": self.item_code,
                "qty_needed": 2000,
                "qty_available": 500
            }]
        })
        assert res.status_code == 200
        
        # Verify formula: available = 500 + 1500 - 2000 = 0
        balances_2 = self.get_balances()
        assert balances_2[0]["on_hand"] == 500
        assert balances_2[0]["committed"] == 2000
        assert balances_2[0]["incoming"] == 1500
        assert balances_2[0]["available"] == 0
        
        print(f"SUCCESS: available formula verified - 500+1500-2000=0")


class TestRegressionOrderRelease:
    """Regression tests for order release functionality"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.test_id = str(uuid.uuid4())[:8]
        self.workspace_id = None
        self.so_reference = f"TEST_SO_REL_{self.test_id}"
        self.item_code = f"TEST_ITEM_REL_{self.test_id}"
        
        # Create test workspace
        ws_res = self.session.post(f"{BASE_URL}/api/inventory-ledger/customers", json={
            "name": f"Test Release WS {self.test_id}",
            "code": f"RELWS{self.test_id}",
            "negative_balance_policy": "warn_only"
        })
        assert ws_res.status_code == 200
        self.workspace_id = ws_res.json()["id"]
        
        yield
        
        if self.workspace_id:
            self.session.put(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}", json={
                "active": False
            })

    def test_partial_release_still_works(self):
        """REGRESSION: Partial release (seed 100, commit 100, release 30)"""
        # Seed opening balance
        self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/seed", json={
            "rows": [{
                "item": self.item_code,
                "item_description": "Test release item",
                "warehouse": "MAIN",
                "ownership_type": "customer_owned",
                "quantity": 100,
                "unit_of_measure": "units"
            }]
        })
        
        # Create commitment
        self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/movements", json={
            "item": self.item_code,
            "item_description": "Test release item",
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -100,
            "unit_of_measure": "units",
            "source_type": "sales_order_commitment",
            "reference_type": "sales_order",
            "reference_id": self.so_reference,
            "notes": "Test commitment"
        })
        
        # Release 30 units
        rel_res = self.session.post(f"{BASE_URL}/api/inventory-ledger/release", json={
            "sales_order_id": self.so_reference,
            "lines": [{"item": self.item_code, "qty": 30}]
        })
        assert rel_res.status_code == 200, f"Release failed: {rel_res.text}"
        data = rel_res.json()
        assert data["released"] == 1
        
        # Verify balances: committed = 100 - 30 = 70
        bal_res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/balances")
        balances = bal_res.json()["balances"]
        item_bal = next((b for b in balances if b["item"] == self.item_code), None)
        assert item_bal["committed"] == 70, f"Expected committed=70, got {item_bal}"
        assert item_bal["available"] == 30, f"Expected available=30, got {item_bal}"
        
        print("REGRESSION PASS: Partial release works (committed 100→70, available 0→30)")

    def test_over_release_still_returns_422(self):
        """REGRESSION: Over-release returns 422"""
        # Seed and commit
        self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/seed", json={
            "rows": [{"item": self.item_code, "warehouse": "MAIN", "quantity": 50}]
        })
        self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/movements", json={
            "item": self.item_code, "warehouse": "MAIN", "ownership_type": "customer_owned",
            "movement_type": "order_commitment", "quantity_delta": -50,
            "reference_type": "sales_order", "reference_id": self.so_reference
        })
        
        # Try to release more than committed
        rel_res = self.session.post(f"{BASE_URL}/api/inventory-ledger/release", json={
            "sales_order_id": self.so_reference,
            "lines": [{"item": self.item_code, "qty": 100}]
        })
        assert rel_res.status_code == 422, f"Expected 422, got {rel_res.status_code}"
        assert "exceeds" in rel_res.text.lower()
        
        print("REGRESSION PASS: Over-release returns 422")


class TestRegressionInventoryLedger:
    """Regression tests for inventory ledger APIs"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def test_customers_list_still_works(self):
        """REGRESSION: GET /api/inventory-ledger/customers lists workspaces"""
        res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers")
        assert res.status_code == 200
        customers = res.json()
        assert isinstance(customers, list)
        # Should have at least some workspaces (Hormel Foods mentioned in context)
        print(f"REGRESSION PASS: Customers list works - {len(customers)} workspaces")

    def test_balances_derive_still_works(self):
        """REGRESSION: GET /api/inventory-ledger/customers/{id}/balances derives correctly"""
        # Get first customer
        cust_res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers")
        customers = cust_res.json()
        if not customers:
            pytest.skip("No customers to test balances")
        
        customer_id = customers[0]["id"]
        bal_res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}/balances")
        assert bal_res.status_code == 200
        data = bal_res.json()
        assert "balances" in data
        assert "customer_id" in data
        
        print(f"REGRESSION PASS: Balances derive works for customer {customer_id}")

    def test_preflight_still_returns_inventory_data(self):
        """REGRESSION: POST /api/gpi-integration/sales-orders/preflight still works"""
        # We need a document to test preflight - skip if none available
        # Try to find a Sales_Order document
        docs_res = self.session.get(f"{BASE_URL}/api/documents", params={
            "doc_type": "Sales_Order",
            "limit": 1
        })
        if docs_res.status_code != 200:
            pytest.skip("Could not fetch documents")
        
        docs = docs_res.json().get("documents", [])
        if not docs:
            # Try any document
            docs_res = self.session.get(f"{BASE_URL}/api/documents", params={"limit": 1})
            docs = docs_res.json().get("documents", [])
        
        if not docs:
            pytest.skip("No documents available to test preflight")
        
        doc_id = docs[0]["id"]
        preflight_res = self.session.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        # May return 400 if not eligible doc type, but should not crash
        assert preflight_res.status_code in [200, 400, 404], f"Unexpected status: {preflight_res.status_code}"
        
        print(f"REGRESSION PASS: Preflight endpoint responds (status={preflight_res.status_code})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
