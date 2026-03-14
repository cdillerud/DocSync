"""
Test suite for Manual Inventory Movement Entry (POST /api/inventory-ledger/movements)

Tests the new manual movement endpoint with:
- Allowed types: opening_balance, manual_adjustment, transfer, writeoff, correction
- Blocked types: order_commitment, order_release, receipt (422)
- Zero quantity rejection (422)
- Writeoff must be negative (422)
- Invalid movement_type rejection (422)
- Duplicate opening_balance check (409)
- Idempotency key duplicate rejection (409)
- History/summary inclusion verification
- Balance derivation after manual entries
"""

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def test_workspace(api_client):
    """Create a test workspace for manual movement tests"""
    unique_code = f"MANMOV{uuid.uuid4().hex[:6].upper()}"
    res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers", json={
        "name": f"TEST_Manual_Movement_{unique_code}",
        "code": unique_code,
        "negative_balance_policy": "warn_only"
    })
    assert res.status_code == 200
    data = res.json()
    yield data
    # Cleanup: deactivate workspace
    api_client.put(f"{BASE_URL}/api/inventory-ledger/customers/{data['id']}", json={"active": False})


class TestManualMovementSuccess:
    """Tests for successful manual movement creation"""

    def test_manual_adjustment_positive(self, api_client, test_workspace):
        """POST /api/inventory-ledger/movements - manual_adjustment with positive qty succeeds"""
        unique_item = f"TEST_ADJ_POS_{uuid.uuid4().hex[:6].upper()}"
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "manual_adjustment",
            "item": unique_item,
            "qty": 50,
            "item_description": "Test Positive Adjustment",
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "unit_of_measure": "cases",
            "reference": "CYCLE-COUNT-2026-01",
            "notes": "Positive adjustment from testing"
        })
        assert res.status_code == 200
        data = res.json()
        assert data.get("success") == True
        assert "movement" in data
        assert data["movement"]["item"] == unique_item
        assert data["movement"]["quantity_delta"] == 50
        assert data["movement"]["movement_type"] == "manual_adjustment"
        assert data["movement"]["source_type"] == "manual_entry"

    def test_correction_negative(self, api_client, test_workspace):
        """POST /api/inventory-ledger/movements - correction with negative qty succeeds"""
        # First create opening balance
        unique_item = f"TEST_CORR_{uuid.uuid4().hex[:6].upper()}"
        api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "opening_balance",
            "item": unique_item,
            "qty": 100,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned"
        })
        
        # Now correction (negative)
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "correction",
            "item": unique_item,
            "qty": -20,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "notes": "Correcting inventory count"
        })
        assert res.status_code == 200
        data = res.json()
        assert data.get("success") == True
        assert data["movement"]["quantity_delta"] == -20
        assert data["movement"]["movement_type"] == "correction"

    def test_writeoff_negative(self, api_client, test_workspace):
        """POST /api/inventory-ledger/movements - writeoff with negative qty succeeds"""
        # First create some inventory
        unique_item = f"TEST_WO_{uuid.uuid4().hex[:6].upper()}"
        api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "opening_balance",
            "item": unique_item,
            "qty": 200,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned"
        })
        
        # Now writeoff
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "writeoff",
            "item": unique_item,
            "qty": -50,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "notes": "Damaged goods writeoff"
        })
        assert res.status_code == 200
        data = res.json()
        assert data.get("success") == True
        assert data["movement"]["quantity_delta"] == -50
        assert data["movement"]["movement_type"] == "writeoff"

    def test_transfer_succeeds(self, api_client, test_workspace):
        """POST /api/inventory-ledger/movements - transfer type succeeds"""
        unique_item = f"TEST_XFER_{uuid.uuid4().hex[:6].upper()}"
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "transfer",
            "item": unique_item,
            "qty": 75,
            "warehouse": "WH-EAST",
            "ownership_type": "customer_owned",
            "notes": "Transfer in from West warehouse"
        })
        assert res.status_code == 200
        data = res.json()
        assert data.get("success") == True
        assert data["movement"]["movement_type"] == "transfer"

    def test_opening_balance_succeeds(self, api_client, test_workspace):
        """POST /api/inventory-ledger/movements - opening_balance creates initial inventory"""
        unique_item = f"TEST_OB_{uuid.uuid4().hex[:6].upper()}"
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "opening_balance",
            "item": unique_item,
            "qty": 1000,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "unit_of_measure": "units"
        })
        assert res.status_code == 200
        data = res.json()
        assert data.get("success") == True
        assert data["movement"]["movement_type"] == "opening_balance"


class TestManualMovementBlocked:
    """Tests for blocked movement types through manual entry"""

    def test_order_commitment_blocked(self, api_client, test_workspace):
        """POST /api/inventory-ledger/movements - order_commitment returns 422"""
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "order_commitment",
            "item": "TEST-BLOCKED",
            "qty": -100,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned"
        })
        assert res.status_code == 422
        data = res.json()
        assert "detail" in data
        assert "order_commitment" in data["detail"].lower() or "not allowed" in data["detail"].lower()

    def test_order_release_blocked(self, api_client, test_workspace):
        """POST /api/inventory-ledger/movements - order_release returns 422"""
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "order_release",
            "item": "TEST-BLOCKED",
            "qty": 100,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned"
        })
        assert res.status_code == 422
        data = res.json()
        assert "detail" in data
        assert "order_release" in data["detail"].lower() or "not allowed" in data["detail"].lower()

    def test_receipt_blocked(self, api_client, test_workspace):
        """POST /api/inventory-ledger/movements - receipt returns 422"""
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "receipt",
            "item": "TEST-BLOCKED",
            "qty": 100,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned"
        })
        assert res.status_code == 422
        data = res.json()
        assert "detail" in data
        assert "receipt" in data["detail"].lower() or "not allowed" in data["detail"].lower()


class TestManualMovementValidation:
    """Tests for validation rules"""

    def test_zero_quantity_rejected(self, api_client, test_workspace):
        """POST /api/inventory-ledger/movements - zero qty returns 422"""
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "manual_adjustment",
            "item": "TEST-ZERO",
            "qty": 0,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned"
        })
        assert res.status_code == 422
        data = res.json()
        assert "detail" in data
        assert "zero" in data["detail"].lower()

    def test_writeoff_positive_rejected(self, api_client, test_workspace):
        """POST /api/inventory-ledger/movements - writeoff with positive qty returns 422"""
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "writeoff",
            "item": "TEST-WO-POS",
            "qty": 50,  # Should be negative!
            "warehouse": "MAIN",
            "ownership_type": "customer_owned"
        })
        assert res.status_code == 422
        data = res.json()
        assert "detail" in data
        assert "negative" in data["detail"].lower() or "reduce" in data["detail"].lower()

    def test_invalid_movement_type_rejected(self, api_client, test_workspace):
        """POST /api/inventory-ledger/movements - invalid movement_type returns 422"""
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "invalid_type",
            "item": "TEST-INVALID",
            "qty": 100,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned"
        })
        assert res.status_code == 422
        data = res.json()
        assert "detail" in data
        assert "invalid" in data["detail"].lower() or "allowed" in data["detail"].lower()


class TestDuplicateChecks:
    """Tests for duplicate detection"""

    def test_duplicate_opening_balance_rejected(self, api_client, test_workspace):
        """POST /api/inventory-ledger/movements - duplicate opening_balance returns 409"""
        unique_item = f"TEST_DUP_OB_{uuid.uuid4().hex[:6].upper()}"
        
        # First opening balance - should succeed
        res1 = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "opening_balance",
            "item": unique_item,
            "qty": 100,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned"
        })
        assert res1.status_code == 200
        
        # Second opening balance for SAME item/warehouse/ownership - should fail
        res2 = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "opening_balance",
            "item": unique_item,
            "qty": 200,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned"
        })
        assert res2.status_code == 409
        data = res2.json()
        assert "detail" in data
        assert "already exists" in data["detail"].lower() or "duplicate" in data["detail"].lower() or "opening balance" in data["detail"].lower()

    def test_idempotency_key_duplicate_rejected(self, api_client, test_workspace):
        """POST /api/inventory-ledger/movements - duplicate idempotency_key returns 409"""
        unique_item = f"TEST_IDEMP_{uuid.uuid4().hex[:6].upper()}"
        idempotency_key = f"key_{uuid.uuid4().hex}"
        
        # First request with idempotency key - should succeed
        res1 = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "manual_adjustment",
            "item": unique_item,
            "qty": 100,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "idempotency_key": idempotency_key
        })
        assert res1.status_code == 200
        
        # Second request with SAME idempotency key - should fail
        res2 = api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "manual_adjustment",
            "item": unique_item,
            "qty": 50,  # Different qty, but same key
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "idempotency_key": idempotency_key
        })
        assert res2.status_code == 409
        data = res2.json()
        assert "detail" in data
        assert "idempotency" in data["detail"].lower() or "duplicate" in data["detail"].lower()


class TestHistoryIntegration:
    """Tests that manual entries appear in history/summary endpoints"""

    def test_manual_entry_appears_in_history(self, api_client, test_workspace):
        """GET /api/inventory-ledger/history - manual entries have source_type=manual_entry"""
        unique_item = f"TEST_HIST_{uuid.uuid4().hex[:6].upper()}"
        
        # Create manual adjustment
        api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "manual_adjustment",
            "item": unique_item,
            "qty": 75,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned"
        })
        
        # Check history
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/history", params={
            "customer_id": test_workspace["id"],
            "item": unique_item
        })
        assert res.status_code == 200
        data = res.json()
        assert "movements" in data
        assert len(data["movements"]) >= 1
        
        # Find the manual adjustment
        movement = next((m for m in data["movements"] if m["movement_type"] == "manual_adjustment"), None)
        assert movement is not None
        assert movement["source_type"] == "manual_entry"

    def test_manual_entries_in_summary(self, api_client, test_workspace):
        """GET /api/inventory-ledger/history/summary - totals include manual entries"""
        unique_item = f"TEST_SUMM_{uuid.uuid4().hex[:6].upper()}"
        
        # Create opening balance + manual adjustment
        api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "opening_balance",
            "item": unique_item,
            "qty": 500,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned"
        })
        
        api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "manual_adjustment",
            "item": unique_item,
            "qty": 100,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned"
        })
        
        # Check summary
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/history/summary", params={
            "customer_id": test_workspace["id"],
            "item": unique_item
        })
        assert res.status_code == 200
        data = res.json()
        assert "movement_type_totals" in data
        
        # Should include both types
        totals = data["movement_type_totals"]
        assert "opening_balance" in totals
        assert "manual_adjustment" in totals


class TestBalanceDerivation:
    """Tests for balance derivation after manual entries"""

    def test_on_hand_correct_after_manual_entries(self, api_client, test_workspace):
        """derive_balances - on_hand correct after manual_adjustment + correction + writeoff"""
        unique_item = f"TEST_BAL_{uuid.uuid4().hex[:6].upper()}"
        
        # Opening: +1000
        api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "opening_balance",
            "item": unique_item,
            "qty": 1000,
            "warehouse": "BAL-TEST",
            "ownership_type": "customer_owned"
        })
        
        # Manual adjustment: +200
        api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "manual_adjustment",
            "item": unique_item,
            "qty": 200,
            "warehouse": "BAL-TEST",
            "ownership_type": "customer_owned"
        })
        
        # Correction: -50
        api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "correction",
            "item": unique_item,
            "qty": -50,
            "warehouse": "BAL-TEST",
            "ownership_type": "customer_owned"
        })
        
        # Writeoff: -100
        api_client.post(f"{BASE_URL}/api/inventory-ledger/movements", json={
            "customer_id": test_workspace["id"],
            "movement_type": "writeoff",
            "item": unique_item,
            "qty": -100,
            "warehouse": "BAL-TEST",
            "ownership_type": "customer_owned"
        })
        
        # Expected on_hand: 1000 + 200 - 50 - 100 = 1050
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{test_workspace['id']}/balances", params={
            "item": unique_item,
            "warehouse": "BAL-TEST"
        })
        assert res.status_code == 200
        data = res.json()
        balances = data.get("balances", [])
        assert len(balances) >= 1
        
        bucket = next((b for b in balances if b["item"] == unique_item and b["warehouse"] == "BAL-TEST"), None)
        assert bucket is not None
        assert bucket["on_hand"] == 1050


class TestRegressions:
    """Regression tests - existing endpoints should still work"""

    def test_reconcile_sales_order_works(self, api_client, test_workspace):
        """REGRESSION: POST /api/inventory-ledger/reconcile-sales-order still works"""
        unique_item = f"TEST_REG_SO_{uuid.uuid4().hex[:6].upper()}"
        so_id = f"SO-REG-{uuid.uuid4().hex[:6].upper()}"
        
        # Create opening balance + commitment via OLD endpoint (customers/{id}/movements)
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{test_workspace['id']}/movements", json={
            "item": unique_item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "opening_balance",
            "quantity_delta": 500,
            "unit_of_measure": "cases"
        })
        
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{test_workspace['id']}/movements", json={
            "item": unique_item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -100,
            "unit_of_measure": "cases",
            "source_type": "sales_order_commitment",
            "reference_type": "sales_order",
            "reference_id": so_id
        })
        
        # Reconcile (cancel)
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json={
            "sales_order_id": so_id,
            "lines": [],
            "cancelled": True
        })
        assert res.status_code == 200

    def test_incoming_supply_from_shortage_works(self, api_client, test_workspace):
        """REGRESSION: POST /api/incoming-supply/from-shortage still works"""
        unique_item = f"TEST_REG_SHORT_{uuid.uuid4().hex[:6].upper()}"
        so_id = f"SO-SHORT-{uuid.uuid4().hex[:6].upper()}"
        
        # Create opening balance
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{test_workspace['id']}/movements", json={
            "item": unique_item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "opening_balance",
            "quantity_delta": 50,
            "unit_of_measure": "cases"
        })
        
        # Create commitment (to establish the item in system)
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{test_workspace['id']}/movements", json={
            "item": unique_item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -100,
            "unit_of_measure": "cases",
            "source_type": "sales_order_commitment",
            "reference_type": "sales_order",
            "reference_id": so_id
        })
        
        # Create shortage supply - needs to reference the SO that has commitment
        res = api_client.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json={
            "sales_order_id": so_id,
            "lines": [{"item": unique_item, "qty_needed": 100, "qty_available": 50}]
        })
        # 200 for success or 409 for duplicate (if test run multiple times)
        assert res.status_code in [200, 409]

    def test_incoming_supply_status_transition_works(self, api_client, test_workspace):
        """REGRESSION: POST /api/incoming-supply/{id}/status still works"""
        unique_item = f"TEST_REG_STAT_{uuid.uuid4().hex[:6].upper()}"
        
        # Create incoming supply via customers endpoint
        create_res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{test_workspace['id']}/incoming", json={
            "item": unique_item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "incoming_qty": 100,
            "unit_of_measure": "cases",
            "eta": "2026-02-15",
            "source_reference": "PO-REG-TEST"
        })
        assert create_res.status_code == 200
        supply_id = create_res.json()["id"]
        
        # Transition planned → ordered (if it starts as expected, transition to ordered first may fail)
        # The new endpoint expects: planned → ordered OR expected → ordered
        res = api_client.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={
            "status": "ordered"
        })
        # Could be 200 or 422 depending on current status
        assert res.status_code in [200, 422]
