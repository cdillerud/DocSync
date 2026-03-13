"""
Test: Incoming Supply Status Transitions (Iteration 58)

Tests for the POST /api/incoming-supply/{supply_id}/status endpoint that transitions
incoming supply records through their lifecycle: planned→ordered→received (or cancelled).

Features tested:
- planned→ordered transition (no receipt movement created)
- ordered→received transition (receipt movement created, on_hand increases)
- planned→cancelled transition
- ordered→cancelled transition
- Invalid backward transition ordered→planned returns 422
- Invalid transition cancelled→ordered returns 422
- Duplicate receipt returns 409 (trying to receive already-received supply)
- Non-existent supply ID returns 422
- derive_balances: 'ordered' status counts as incoming
- derive_balances: 'received' status NOT counted as incoming (shows as on_hand via receipt)
- derive_balances: 'cancelled' status NOT counted as incoming
- Full lifecycle test: create→seed→commit→shortage supply→ordered→received→verify on_hand

Regression tests:
- POST /api/incoming-supply/from-shortage still works
- POST /api/inventory-ledger/release still works
- GET /api/inventory-ledger/customers still lists workspaces
"""

import pytest
import requests
import os
import uuid
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestStatusTransitions:
    """Tests for POST /api/incoming-supply/{supply_id}/status endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create a test workspace and seed data for each test"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.test_id = str(uuid.uuid4())[:8]
        self.workspace_id = None
        self.so_reference = f"TEST_SO_TRANS_{self.test_id}"
        self.item_code = f"TEST_TRANS_ITEM_{self.test_id}"
        
        # Create test workspace
        ws_res = self.session.post(f"{BASE_URL}/api/inventory-ledger/customers", json={
            "name": f"Test Transition WS {self.test_id}",
            "code": f"TRANS{self.test_id}",
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
                "item_description": f"Test transition item {item}",
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
            "item_description": f"Test transition item {item}",
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

    def create_shortage_supply(self, qty_needed: float, qty_available: float, item: str = None, so_ref: str = None):
        """Helper: create shortage supply via API"""
        item = item or self.item_code
        so_ref = so_ref or self.so_reference
        
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": so_ref,
            "lines": [{
                "item": item,
                "qty_needed": qty_needed,
                "qty_available": qty_available
            }]
        })
        assert res.status_code == 200, f"Create shortage supply failed: {res.text}"
        data = res.json()
        assert data["created"] == 1, f"Expected 1 created, got {data}"
        return data["supply_ids"][0]

    def get_supply(self, supply_id: str):
        """Helper: get supply record from incoming list"""
        res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/incoming")
        assert res.status_code == 200
        incoming = res.json()
        return next((s for s in incoming if s["id"] == supply_id), None)

    def get_balances(self, item: str = None):
        """Helper: get balances for workspace"""
        item = item or self.item_code
        res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/balances", params={
            "item": item
        })
        assert res.status_code == 200, f"Get balances failed: {res.text}"
        return res.json()["balances"]

    # =========================================================================
    # Test: planned→ordered transition (no receipt movement)
    # =========================================================================
    
    def test_planned_to_ordered_transition(self):
        """Transition from planned to ordered creates no receipt movement"""
        # Seed 100, commit 500 → shortage = 400
        self.seed_and_commit(on_hand=100, commit_qty=500)
        supply_id = self.create_shortage_supply(qty_needed=500, qty_available=100)
        
        # Verify initial status is 'planned'
        supply = self.get_supply(supply_id)
        assert supply["status"] == "planned"
        
        # Get balances before transition
        balances_before = self.get_balances()
        on_hand_before = balances_before[0]["on_hand"]
        
        # Transition to ordered
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={
            "status": "ordered"
        })
        assert res.status_code == 200, f"Transition failed: {res.text}"
        data = res.json()
        
        # Verify response
        assert data["supply"]["status"] == "ordered"
        assert data["receipt_movement_id"] is None, "No receipt movement should be created for ordered"
        
        # Verify on_hand unchanged (no receipt movement)
        balances_after = self.get_balances()
        assert balances_after[0]["on_hand"] == on_hand_before
        
        print(f"SUCCESS: planned→ordered transition works - no receipt movement created")

    # =========================================================================
    # Test: ordered→received transition (receipt movement created)
    # =========================================================================
    
    def test_ordered_to_received_transition(self):
        """Transition from ordered to received creates receipt movement"""
        # Seed 100, commit 500 → shortage = 400
        self.seed_and_commit(on_hand=100, commit_qty=500)
        supply_id = self.create_shortage_supply(qty_needed=500, qty_available=100)
        
        # Transition to ordered first
        self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={"status": "ordered"})
        
        # Get balances before receive
        balances_before = self.get_balances()
        on_hand_before = balances_before[0]["on_hand"]
        incoming_before = balances_before[0]["incoming"]
        
        # Transition to received
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={
            "status": "received"
        })
        assert res.status_code == 200, f"Transition failed: {res.text}"
        data = res.json()
        
        # Verify response
        assert data["supply"]["status"] == "received"
        assert data["receipt_movement_id"] is not None, "Receipt movement should be created"
        
        # Verify on_hand increased by incoming_qty (400)
        balances_after = self.get_balances()
        expected_on_hand = on_hand_before + 400  # 100 + 400 = 500
        assert balances_after[0]["on_hand"] == expected_on_hand, f"Expected on_hand={expected_on_hand}, got {balances_after[0]['on_hand']}"
        
        # Verify incoming is now 0 (supply no longer in incoming filter)
        assert balances_after[0]["incoming"] == 0, f"Expected incoming=0, got {balances_after[0]['incoming']}"
        
        print(f"SUCCESS: ordered→received transition works - on_hand increased from {on_hand_before} to {expected_on_hand}")

    # =========================================================================
    # Test: planned→cancelled transition
    # =========================================================================
    
    def test_planned_to_cancelled_transition(self):
        """Transition from planned to cancelled is allowed"""
        self.seed_and_commit(on_hand=100, commit_qty=500)
        supply_id = self.create_shortage_supply(qty_needed=500, qty_available=100)
        
        # Verify initial status is 'planned'
        supply = self.get_supply(supply_id)
        assert supply["status"] == "planned"
        
        # Transition to cancelled
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={
            "status": "cancelled"
        })
        assert res.status_code == 200, f"Transition failed: {res.text}"
        data = res.json()
        
        # Verify status changed
        assert data["supply"]["status"] == "cancelled"
        assert data["receipt_movement_id"] is None, "No receipt for cancellation"
        
        # Verify supply no longer counts in incoming
        balances = self.get_balances()
        assert balances[0]["incoming"] == 0, "Cancelled supply should not count as incoming"
        
        print(f"SUCCESS: planned→cancelled transition works")

    # =========================================================================
    # Test: ordered→cancelled transition
    # =========================================================================
    
    def test_ordered_to_cancelled_transition(self):
        """Transition from ordered to cancelled is allowed"""
        self.seed_and_commit(on_hand=100, commit_qty=500)
        supply_id = self.create_shortage_supply(qty_needed=500, qty_available=100)
        
        # First transition to ordered
        self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={"status": "ordered"})
        
        # Verify incoming count before cancel
        balances_before = self.get_balances()
        assert balances_before[0]["incoming"] == 400, "ordered status should count as incoming"
        
        # Transition to cancelled
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={
            "status": "cancelled"
        })
        assert res.status_code == 200, f"Transition failed: {res.text}"
        data = res.json()
        
        # Verify status changed
        assert data["supply"]["status"] == "cancelled"
        
        # Verify incoming is now 0
        balances_after = self.get_balances()
        assert balances_after[0]["incoming"] == 0, "Cancelled supply should not count as incoming"
        
        print(f"SUCCESS: ordered→cancelled transition works - incoming zeroed")

    # =========================================================================
    # Test: Invalid backward transition ordered→planned returns 422
    # =========================================================================
    
    def test_invalid_backward_transition_422(self):
        """Backward transition ordered→planned returns HTTP 422"""
        self.seed_and_commit(on_hand=100, commit_qty=500)
        supply_id = self.create_shortage_supply(qty_needed=500, qty_available=100)
        
        # First transition to ordered
        self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={"status": "ordered"})
        
        # Try backward transition to planned
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={
            "status": "planned"
        })
        assert res.status_code == 422, f"Expected 422, got {res.status_code}: {res.text}"
        assert "invalid transition" in res.text.lower() or "allowed" in res.text.lower()
        
        print(f"SUCCESS: Invalid backward transition returns 422")

    # =========================================================================
    # Test: Invalid transition cancelled→ordered returns 422
    # =========================================================================
    
    def test_invalid_transition_from_cancelled_422(self):
        """Transition from cancelled to any state returns HTTP 422"""
        self.seed_and_commit(on_hand=100, commit_qty=500)
        supply_id = self.create_shortage_supply(qty_needed=500, qty_available=100)
        
        # Transition to cancelled
        self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={"status": "cancelled"})
        
        # Try to transition from cancelled to ordered
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={
            "status": "ordered"
        })
        assert res.status_code == 422, f"Expected 422, got {res.status_code}: {res.text}"
        assert "invalid transition" in res.text.lower() or "terminal" in res.text.lower() or "none" in res.text.lower()
        
        print(f"SUCCESS: Invalid transition from cancelled returns 422")

    # =========================================================================
    # Test: Duplicate receipt returns 409
    # =========================================================================
    
    def test_duplicate_receipt_409(self):
        """Trying to receive an already-received supply returns HTTP 409"""
        self.seed_and_commit(on_hand=100, commit_qty=500)
        supply_id = self.create_shortage_supply(qty_needed=500, qty_available=100)
        
        # Transition: planned → ordered → received
        self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={"status": "ordered"})
        res1 = self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={"status": "received"})
        assert res1.status_code == 200
        
        # Try to receive again
        res2 = self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={
            "status": "received"
        })
        assert res2.status_code == 409, f"Expected 409, got {res2.status_code}: {res2.text}"
        assert "already received" in res2.text.lower() or "duplicate" in res2.text.lower()
        
        print(f"SUCCESS: Duplicate receipt returns 409")

    # =========================================================================
    # Test: Non-existent supply ID returns 422
    # =========================================================================
    
    def test_nonexistent_supply_422(self):
        """Transition on non-existent supply ID returns HTTP 422"""
        fake_supply_id = f"fake-{self.test_id}-supply"
        
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/{fake_supply_id}/status", json={
            "status": "ordered"
        })
        assert res.status_code == 422, f"Expected 422, got {res.status_code}: {res.text}"
        assert "not found" in res.text.lower()
        
        print(f"SUCCESS: Non-existent supply returns 422")


class TestDeriveBalancesWithStatuses:
    """Tests for derive_balances with different supply statuses"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.test_id = str(uuid.uuid4())[:8]
        self.workspace_id = None
        self.so_reference = f"TEST_SO_BAL_{self.test_id}"
        self.item_code = f"TEST_BAL_ITEM_{self.test_id}"
        
        ws_res = self.session.post(f"{BASE_URL}/api/inventory-ledger/customers", json={
            "name": f"Test Balance WS {self.test_id}",
            "code": f"BAL{self.test_id}",
            "negative_balance_policy": "warn_only"
        })
        assert ws_res.status_code == 200
        self.workspace_id = ws_res.json()["id"]
        
        yield
        
        if self.workspace_id:
            self.session.put(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}", json={"active": False})

    def seed_and_commit(self, on_hand: float, commit_qty: float):
        self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/seed", json={
            "rows": [{
                "item": self.item_code, "warehouse": "MAIN", "ownership_type": "customer_owned",
                "quantity": on_hand, "unit_of_measure": "units"
            }]
        })
        self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/movements", json={
            "item": self.item_code, "warehouse": "MAIN", "ownership_type": "customer_owned",
            "movement_type": "order_commitment", "quantity_delta": -commit_qty,
            "reference_type": "sales_order", "reference_id": self.so_reference
        })

    def create_shortage_supply(self, qty_needed: float, qty_available: float):
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": self.so_reference,
            "lines": [{"item": self.item_code, "qty_needed": qty_needed, "qty_available": qty_available}]
        })
        assert res.status_code == 200
        return res.json()["supply_ids"][0]

    def get_balances(self):
        res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/balances",
                               params={"item": self.item_code})
        return res.json()["balances"]

    # =========================================================================
    # Test: 'ordered' status counts as incoming
    # =========================================================================
    
    def test_ordered_counts_as_incoming(self):
        """'ordered' status should count as incoming in derive_balances"""
        # Seed 100, commit 500 → shortage = 400
        self.seed_and_commit(on_hand=100, commit_qty=500)
        supply_id = self.create_shortage_supply(qty_needed=500, qty_available=100)
        
        # Transition to ordered
        self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={"status": "ordered"})
        
        # Check balances - incoming should be 400
        balances = self.get_balances()
        assert balances[0]["incoming"] == 400, f"Expected incoming=400, got {balances[0]['incoming']}"
        
        # available = on_hand + incoming - committed = 100 + 400 - 500 = 0
        assert balances[0]["available"] == 0, f"Expected available=0, got {balances[0]['available']}"
        
        print(f"SUCCESS: 'ordered' status counts as incoming (400)")

    # =========================================================================
    # Test: 'received' status NOT counted as incoming
    # =========================================================================
    
    def test_received_not_counted_as_incoming(self):
        """'received' status should NOT count as incoming (shows as on_hand via receipt)"""
        # Seed 100, commit 500 → shortage = 400
        self.seed_and_commit(on_hand=100, commit_qty=500)
        supply_id = self.create_shortage_supply(qty_needed=500, qty_available=100)
        
        # Transition to ordered, then received
        self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={"status": "ordered"})
        self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={"status": "received"})
        
        # Check balances
        balances = self.get_balances()
        assert balances[0]["incoming"] == 0, f"Expected incoming=0 (received supply dropped), got {balances[0]['incoming']}"
        assert balances[0]["on_hand"] == 500, f"Expected on_hand=500 (100+400 receipt), got {balances[0]['on_hand']}"
        
        # available = 500 + 0 - 500 = 0
        assert balances[0]["available"] == 0, f"Expected available=0, got {balances[0]['available']}"
        
        print(f"SUCCESS: 'received' status not counted as incoming, shows as on_hand")

    # =========================================================================
    # Test: 'cancelled' status NOT counted as incoming
    # =========================================================================
    
    def test_cancelled_not_counted_as_incoming(self):
        """'cancelled' status should NOT count as incoming"""
        # Seed 100, commit 500 → shortage = 400
        self.seed_and_commit(on_hand=100, commit_qty=500)
        supply_id = self.create_shortage_supply(qty_needed=500, qty_available=100)
        
        # Verify planned counts as incoming first
        balances_planned = self.get_balances()
        assert balances_planned[0]["incoming"] == 400
        
        # Transition to cancelled
        self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={"status": "cancelled"})
        
        # Check balances - incoming should be 0
        balances = self.get_balances()
        assert balances[0]["incoming"] == 0, f"Expected incoming=0 (cancelled supply dropped), got {balances[0]['incoming']}"
        assert balances[0]["on_hand"] == 100, f"on_hand should remain 100"
        
        # available = 100 + 0 - 500 = -400
        assert balances[0]["available"] == -400, f"Expected available=-400, got {balances[0]['available']}"
        
        print(f"SUCCESS: 'cancelled' status not counted as incoming")


class TestFullLifecycle:
    """Full lifecycle test: create workspace → seed → commit → shortage supply → ordered → received"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.test_id = str(uuid.uuid4())[:8]
        self.workspace_id = None
        yield
        if self.workspace_id:
            self.session.put(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}", json={"active": False})

    def test_full_lifecycle(self):
        """Complete lifecycle: workspace → seed → commit → shortage → ordered → received → verify"""
        so_ref = f"TEST_FULL_SO_{self.test_id}"
        item = f"TEST_FULL_ITEM_{self.test_id}"
        
        # Step 1: Create workspace
        ws_res = self.session.post(f"{BASE_URL}/api/inventory-ledger/customers", json={
            "name": f"Full Lifecycle WS {self.test_id}",
            "code": f"FULL{self.test_id}",
            "negative_balance_policy": "warn_only"
        })
        assert ws_res.status_code == 200
        self.workspace_id = ws_res.json()["id"]
        print(f"Step 1: Created workspace {self.workspace_id}")
        
        # Step 2: Seed opening balance (200 units)
        seed_res = self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/seed", json={
            "rows": [{
                "item": item, "item_description": "Full lifecycle test item",
                "warehouse": "MAIN", "ownership_type": "customer_owned",
                "quantity": 200, "unit_of_measure": "units"
            }]
        })
        assert seed_res.status_code == 200
        print(f"Step 2: Seeded 200 units")
        
        # Step 3: Create order commitment (1000 units → shortage = 800)
        mv_res = self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/movements", json={
            "item": item, "warehouse": "MAIN", "ownership_type": "customer_owned",
            "movement_type": "order_commitment", "quantity_delta": -1000,
            "unit_of_measure": "units", "source_type": "sales_order_commitment",
            "reference_type": "sales_order", "reference_id": so_ref
        })
        assert mv_res.status_code == 200
        print(f"Step 3: Created commitment for 1000 units")
        
        # Step 4: Verify initial balances (on_hand=200, committed=1000, available=-800)
        bal_res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/balances",
                                    params={"item": item})
        balances = bal_res.json()["balances"]
        assert balances[0]["on_hand"] == 200
        assert balances[0]["committed"] == 1000
        assert balances[0]["incoming"] == 0
        assert balances[0]["available"] == -800
        print(f"Step 4: Initial balances correct - on_hand=200, committed=1000, available=-800")
        
        # Step 5: Create shortage supply (800 units)
        supply_res = self.session.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": so_ref,
            "lines": [{"item": item, "qty_needed": 1000, "qty_available": 200}]
        })
        assert supply_res.status_code == 200
        supply_id = supply_res.json()["supply_ids"][0]
        print(f"Step 5: Created shortage supply {supply_id}")
        
        # Step 6: Verify incoming increased (planned counts)
        bal_res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/balances",
                                    params={"item": item})
        balances = bal_res.json()["balances"]
        assert balances[0]["incoming"] == 800
        assert balances[0]["available"] == 0  # 200 + 800 - 1000 = 0
        print(f"Step 6: Incoming supply counted - incoming=800, available=0")
        
        # Step 7: Transition to ordered
        order_res = self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={"status": "ordered"})
        assert order_res.status_code == 200
        assert order_res.json()["receipt_movement_id"] is None
        print(f"Step 7: Transitioned to ordered - no receipt movement")
        
        # Step 8: Verify ordered still counts as incoming
        bal_res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/balances",
                                    params={"item": item})
        balances = bal_res.json()["balances"]
        assert balances[0]["incoming"] == 800
        assert balances[0]["on_hand"] == 200  # unchanged
        print(f"Step 8: Ordered status counts as incoming - incoming=800, on_hand=200")
        
        # Step 9: Transition to received
        recv_res = self.session.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={"status": "received"})
        assert recv_res.status_code == 200
        receipt_id = recv_res.json()["receipt_movement_id"]
        assert receipt_id is not None
        print(f"Step 9: Transitioned to received - receipt movement={receipt_id}")
        
        # Step 10: Verify final balances (on_hand=1000, incoming=0, available=0)
        bal_res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/balances",
                                    params={"item": item})
        balances = bal_res.json()["balances"]
        assert balances[0]["on_hand"] == 1000, f"Expected on_hand=1000 (200+800), got {balances[0]['on_hand']}"
        assert balances[0]["incoming"] == 0, f"Expected incoming=0, got {balances[0]['incoming']}"
        assert balances[0]["committed"] == 1000
        assert balances[0]["available"] == 0  # 1000 + 0 - 1000 = 0
        print(f"Step 10: Final balances correct - on_hand=1000, incoming=0, committed=1000, available=0")
        
        print(f"\nSUCCESS: Full lifecycle test completed!")


class TestRegressionShortageSupply:
    """Regression tests: shortage supply creation still works"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.test_id = str(uuid.uuid4())[:8]
        self.workspace_id = None
        
        ws_res = self.session.post(f"{BASE_URL}/api/inventory-ledger/customers", json={
            "name": f"Regression Shortage WS {self.test_id}",
            "code": f"REGSH{self.test_id}",
            "negative_balance_policy": "warn_only"
        })
        assert ws_res.status_code == 200
        self.workspace_id = ws_res.json()["id"]
        
        yield
        
        if self.workspace_id:
            self.session.put(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}", json={"active": False})

    def test_shortage_creation_still_works(self):
        """REGRESSION: POST /api/incoming-supply/from-shortage still works"""
        so_ref = f"REG_SO_{self.test_id}"
        item = f"REG_ITEM_{self.test_id}"
        
        # Seed and commit
        self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/seed", json={
            "rows": [{"item": item, "warehouse": "MAIN", "quantity": 50}]
        })
        self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/movements", json={
            "item": item, "warehouse": "MAIN", "ownership_type": "customer_owned",
            "movement_type": "order_commitment", "quantity_delta": -200,
            "reference_type": "sales_order", "reference_id": so_ref
        })
        
        # Create shortage supply
        res = self.session.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": so_ref,
            "lines": [{"item": item, "qty_needed": 200, "qty_available": 50}]
        })
        assert res.status_code == 200
        assert res.json()["created"] == 1
        
        print("REGRESSION PASS: Shortage supply creation works")

    def test_shortage_duplicate_409_still_works(self):
        """REGRESSION: Duplicate shortage returns 409"""
        so_ref = f"REG_DUP_SO_{self.test_id}"
        item = f"REG_DUP_ITEM_{self.test_id}"
        
        # Seed and commit
        self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/seed", json={
            "rows": [{"item": item, "warehouse": "MAIN", "quantity": 50}]
        })
        self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/movements", json={
            "item": item, "warehouse": "MAIN", "ownership_type": "customer_owned",
            "movement_type": "order_commitment", "quantity_delta": -200,
            "reference_type": "sales_order", "reference_id": so_ref
        })
        
        # First call
        res1 = self.session.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": so_ref,
            "lines": [{"item": item, "qty_needed": 200, "qty_available": 50}]
        })
        assert res1.status_code == 200
        
        # Second call - should return 409
        res2 = self.session.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": so_ref,
            "lines": [{"item": item, "qty_needed": 200, "qty_available": 50}]
        })
        assert res2.status_code == 409
        
        print("REGRESSION PASS: Duplicate shortage returns 409")


class TestRegressionRelease:
    """Regression tests: order release still works"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.test_id = str(uuid.uuid4())[:8]
        self.workspace_id = None
        
        ws_res = self.session.post(f"{BASE_URL}/api/inventory-ledger/customers", json={
            "name": f"Regression Release WS {self.test_id}",
            "code": f"REGREL{self.test_id}",
            "negative_balance_policy": "warn_only"
        })
        assert ws_res.status_code == 200
        self.workspace_id = ws_res.json()["id"]
        
        yield
        
        if self.workspace_id:
            self.session.put(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}", json={"active": False})

    def test_release_partial_still_works(self):
        """REGRESSION: Partial release works"""
        so_ref = f"REG_REL_SO_{self.test_id}"
        item = f"REG_REL_ITEM_{self.test_id}"
        
        # Seed and commit
        self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/seed", json={
            "rows": [{"item": item, "warehouse": "MAIN", "quantity": 100}]
        })
        self.session.post(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/movements", json={
            "item": item, "warehouse": "MAIN", "ownership_type": "customer_owned",
            "movement_type": "order_commitment", "quantity_delta": -100,
            "reference_type": "sales_order", "reference_id": so_ref
        })
        
        # Release 30 units
        rel_res = self.session.post(f"{BASE_URL}/api/inventory-ledger/release", json={
            "sales_order_id": so_ref,
            "lines": [{"item": item, "qty": 30}]
        })
        assert rel_res.status_code == 200
        assert rel_res.json()["released"] == 1
        
        # Verify committed dropped
        bal_res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers/{self.workspace_id}/balances")
        balances = bal_res.json()["balances"]
        item_bal = next((b for b in balances if b["item"] == item), None)
        assert item_bal["committed"] == 70
        
        print("REGRESSION PASS: Partial release works (100→70)")


class TestRegressionCustomers:
    """Regression tests: customer list and balances still work"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def test_customers_list(self):
        """REGRESSION: GET /api/inventory-ledger/customers lists workspaces"""
        res = self.session.get(f"{BASE_URL}/api/inventory-ledger/customers")
        assert res.status_code == 200
        customers = res.json()
        assert isinstance(customers, list)
        print(f"REGRESSION PASS: Customers list works - {len(customers)} workspaces")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
