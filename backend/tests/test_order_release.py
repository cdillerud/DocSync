"""
Test suite for Order Release Movement Type (Iteration 56)

Tests the order_release movement type for releasing committed inventory when 
a Sales Order line is fulfilled or cancelled.

Endpoint: POST /api/inventory-ledger/release
Request: {sales_order_id, lines: [{item, qty}]}

Key formulas:
- committed = sum(order_commitment) - sum(order_release)
- available = on_hand + incoming - committed
- on_hand excludes BOTH order_commitment AND order_release

Test scenarios:
1. commit→release lifecycle: create workspace, seed balance, commit, partial release, verify balances
2. full release: remaining committed becomes 0, available returns to original
3. over-release rejection: release qty > outstanding committed → HTTP 422
4. non-existent SO → HTTP 422
5. multi-line release: release multiple items in one request
6. REGRESSION: existing ledger functionality unchanged
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
    """Create a test workspace for release tests"""
    unique_code = f"RLST{uuid.uuid4().hex[:4].upper()}"
    res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers", json={
        "name": f"Release Test {unique_code}",
        "code": unique_code,
        "negative_balance_policy": "warn_only"
    })
    assert res.status_code == 200
    workspace = res.json()
    yield workspace
    # Cleanup: deactivate workspace
    api_client.put(f"{BASE_URL}/api/inventory-ledger/customers/{workspace['id']}", json={"active": False})


class TestOrderReleaseLifecycle:
    """Test the commit→release lifecycle"""

    def test_partial_release_lifecycle(self, api_client, test_workspace):
        """Complete lifecycle: seed balance → commit → partial release → verify balances"""
        workspace_id = test_workspace['id']
        unique_item = f"ITEM-{uuid.uuid4().hex[:6].upper()}"
        so_ref = f"SO-PARTIAL-{uuid.uuid4().hex[:6].upper()}"
        
        # Step 1: Seed opening balance of 100 units
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "item_description": "Test Item for Partial Release",
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "opening_balance",
            "quantity_delta": 100,
            "unit_of_measure": "units"
        })
        assert res.status_code == 200
        
        # Verify initial balance: on_hand=100, committed=0, available=100
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/balances?item={unique_item}")
        assert res.status_code == 200
        bal = res.json()['balances'][0]
        assert bal['on_hand'] == 100
        assert bal['committed'] == 0
        assert bal['available'] == 100
        
        # Step 2: Create order_commitment for 50 units
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "item_description": "Test Item for Partial Release",
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -50,
            "unit_of_measure": "units",
            "source_type": "sales_order_commitment",
            "reference_type": "sales_order",
            "reference_id": so_ref
        })
        assert res.status_code == 200
        
        # Verify after commitment: on_hand=100, committed=50, available=50
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/balances?item={unique_item}")
        assert res.status_code == 200
        bal = res.json()['balances'][0]
        assert bal['on_hand'] == 100, f"Expected on_hand=100, got {bal['on_hand']}"
        assert bal['committed'] == 50, f"Expected committed=50, got {bal['committed']}"
        assert bal['available'] == 50, f"Expected available=50, got {bal['available']}"
        
        # Step 3: Partial release of 30 units
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/release", json={
            "sales_order_id": so_ref,
            "lines": [{"item": unique_item, "qty": 30}]
        })
        assert res.status_code == 200
        data = res.json()
        assert data['released'] == 1
        assert len(data['movement_ids']) == 1
        
        # Verify after partial release: on_hand=100, committed=20 (50-30), available=80 (100-20)
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/balances?item={unique_item}")
        assert res.status_code == 200
        bal = res.json()['balances'][0]
        assert bal['on_hand'] == 100, f"Expected on_hand=100, got {bal['on_hand']}"
        assert bal['committed'] == 20, f"Expected committed=20 (50-30), got {bal['committed']}"
        assert bal['available'] == 80, f"Expected available=80 (100-20), got {bal['available']}"

    def test_full_release(self, api_client, test_workspace):
        """Full release: remaining committed becomes 0, available returns to on_hand"""
        workspace_id = test_workspace['id']
        unique_item = f"ITEM-{uuid.uuid4().hex[:6].upper()}"
        so_ref = f"SO-FULL-{uuid.uuid4().hex[:6].upper()}"
        
        # Seed opening balance of 100 units
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "item_description": "Test Item for Full Release",
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "opening_balance",
            "quantity_delta": 100,
            "unit_of_measure": "units"
        })
        
        # Create order_commitment for 80 units
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "item_description": "Test Item for Full Release",
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -80,
            "unit_of_measure": "units",
            "source_type": "sales_order_commitment",
            "reference_type": "sales_order",
            "reference_id": so_ref
        })
        
        # Full release of all 80 units
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/release", json={
            "sales_order_id": so_ref,
            "lines": [{"item": unique_item, "qty": 80}]
        })
        assert res.status_code == 200
        data = res.json()
        assert data['released'] == 1
        
        # Verify after full release: on_hand=100, committed=0, available=100
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/balances?item={unique_item}")
        assert res.status_code == 200
        bal = res.json()['balances'][0]
        assert bal['on_hand'] == 100
        assert bal['committed'] == 0, f"Expected committed=0 after full release, got {bal['committed']}"
        assert bal['available'] == 100, f"Expected available=100 after full release, got {bal['available']}"


class TestOrderReleaseValidation:
    """Test validation and error handling for order_release"""

    def test_over_release_rejection(self, api_client, test_workspace):
        """Release qty > outstanding committed → HTTP 422"""
        workspace_id = test_workspace['id']
        unique_item = f"ITEM-{uuid.uuid4().hex[:6].upper()}"
        so_ref = f"SO-OVER-{uuid.uuid4().hex[:6].upper()}"
        
        # Seed balance and commitment
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "item_description": "Test Over-release",
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "opening_balance",
            "quantity_delta": 100,
            "unit_of_measure": "units"
        })
        
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -50,
            "unit_of_measure": "units",
            "reference_type": "sales_order",
            "reference_id": so_ref
        })
        
        # Try to release 60 units when only 50 committed → 422
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/release", json={
            "sales_order_id": so_ref,
            "lines": [{"item": unique_item, "qty": 60}]
        })
        assert res.status_code == 422, f"Expected 422 for over-release, got {res.status_code}"
        assert "exceeds outstanding commitment" in res.json()['detail'].lower() or "exceeds" in res.json()['detail'].lower()

    def test_nonexistent_so_rejection(self, api_client):
        """Release for non-existent SO → HTTP 422"""
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/release", json={
            "sales_order_id": f"SO-NONEXISTENT-{uuid.uuid4().hex[:8]}",
            "lines": [{"item": "FAKE-ITEM", "qty": 10}]
        })
        assert res.status_code == 422, f"Expected 422 for non-existent SO, got {res.status_code}"
        assert "no order_commitment" in res.json()['detail'].lower()

    def test_release_after_full_release_rejected(self, api_client, test_workspace):
        """Cannot release more after fully released"""
        workspace_id = test_workspace['id']
        unique_item = f"ITEM-{uuid.uuid4().hex[:6].upper()}"
        so_ref = f"SO-DOUBLE-{uuid.uuid4().hex[:6].upper()}"
        
        # Seed and commit
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "opening_balance",
            "quantity_delta": 100,
            "unit_of_measure": "units"
        })
        
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -30,
            "unit_of_measure": "units",
            "reference_type": "sales_order",
            "reference_id": so_ref
        })
        
        # Full release
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/release", json={
            "sales_order_id": so_ref,
            "lines": [{"item": unique_item, "qty": 30}]
        })
        assert res.status_code == 200
        
        # Try to release again → should fail (nothing to release)
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/release", json={
            "sales_order_id": so_ref,
            "lines": [{"item": unique_item, "qty": 10}]
        })
        # Should return 200 but with error in response OR 422
        if res.status_code == 200:
            data = res.json()
            assert data['released'] == 0 or len(data['errors']) > 0
        else:
            assert res.status_code == 422


class TestMultiLineRelease:
    """Test multi-line release functionality"""

    def test_multiline_release(self, api_client, test_workspace):
        """Release multiple items in one request"""
        workspace_id = test_workspace['id']
        item1 = f"ITEM1-{uuid.uuid4().hex[:6].upper()}"
        item2 = f"ITEM2-{uuid.uuid4().hex[:6].upper()}"
        so_ref = f"SO-MULTI-{uuid.uuid4().hex[:6].upper()}"
        
        # Seed balances for both items
        for item in [item1, item2]:
            api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
                "item": item,
                "warehouse": "MAIN",
                "ownership_type": "customer_owned",
                "movement_type": "opening_balance",
                "quantity_delta": 100,
                "unit_of_measure": "units"
            })
            api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
                "item": item,
                "warehouse": "MAIN",
                "ownership_type": "customer_owned",
                "movement_type": "order_commitment",
                "quantity_delta": -50,
                "unit_of_measure": "units",
                "reference_type": "sales_order",
                "reference_id": so_ref
            })
        
        # Multi-line release
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/release", json={
            "sales_order_id": so_ref,
            "lines": [
                {"item": item1, "qty": 20},
                {"item": item2, "qty": 30}
            ]
        })
        assert res.status_code == 200
        data = res.json()
        assert data['released'] == 2, f"Expected 2 items released, got {data['released']}"
        assert len(data['movement_ids']) == 2
        
        # Verify balances for item1: committed=30 (50-20)
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/balances?item={item1}")
        bal1 = res.json()['balances'][0]
        assert bal1['committed'] == 30
        
        # Verify balances for item2: committed=20 (50-30)
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/balances?item={item2}")
        bal2 = res.json()['balances'][0]
        assert bal2['committed'] == 20


class TestDeriveBalancesFormula:
    """Test balance derivation formula correctness"""

    def test_on_hand_excludes_commitment_and_release(self, api_client, test_workspace):
        """on_hand excludes BOTH order_commitment AND order_release"""
        workspace_id = test_workspace['id']
        unique_item = f"ITEM-{uuid.uuid4().hex[:6].upper()}"
        so_ref = f"SO-ONHAND-{uuid.uuid4().hex[:6].upper()}"
        
        # Seed 100 units
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "opening_balance",
            "quantity_delta": 100,
            "unit_of_measure": "units"
        })
        
        # Commit 40
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -40,
            "unit_of_measure": "units",
            "reference_type": "sales_order",
            "reference_id": so_ref
        })
        
        # Release 15
        api_client.post(f"{BASE_URL}/api/inventory-ledger/release", json={
            "sales_order_id": so_ref,
            "lines": [{"item": unique_item, "qty": 15}]
        })
        
        # on_hand should still be 100 (doesn't include commitment or release movements)
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/balances?item={unique_item}")
        bal = res.json()['balances'][0]
        assert bal['on_hand'] == 100, f"on_hand should be 100, got {bal['on_hand']}"

    def test_committed_formula(self, api_client, test_workspace):
        """committed = abs(commitment_raw) + release_raw (commitment -100, release -30 → committed = 100 + (-30) = 70)"""
        workspace_id = test_workspace['id']
        unique_item = f"ITEM-{uuid.uuid4().hex[:6].upper()}"
        so_ref = f"SO-COMMIT-{uuid.uuid4().hex[:6].upper()}"
        
        # Seed 200 units
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "opening_balance",
            "quantity_delta": 200,
            "unit_of_measure": "units"
        })
        
        # Commit 100 (delta = -100)
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -100,
            "unit_of_measure": "units",
            "reference_type": "sales_order",
            "reference_id": so_ref
        })
        
        # Release 30 (delta = -30)
        api_client.post(f"{BASE_URL}/api/inventory-ledger/release", json={
            "sales_order_id": so_ref,
            "lines": [{"item": unique_item, "qty": 30}]
        })
        
        # committed = (-1 * -100) + (-30) = 100 - 30 = 70
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/balances?item={unique_item}")
        bal = res.json()['balances'][0]
        assert bal['committed'] == 70, f"committed should be 70, got {bal['committed']}"
        # available = on_hand + incoming - committed = 200 + 0 - 70 = 130
        assert bal['available'] == 130, f"available should be 130, got {bal['available']}"


class TestRegressionExistingFunctionality:
    """REGRESSION: Ensure existing ledger behavior unchanged"""

    def test_list_customers_still_works(self, api_client):
        """GET /api/inventory-ledger/customers - still lists workspaces"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        # At minimum should have Hormel and Karlin from seed data
        assert len(data) >= 2

    def test_create_movement_opening_balance_still_works(self, api_client, test_workspace):
        """POST /api/inventory-ledger/customers/{id}/movements - opening_balance works"""
        workspace_id = test_workspace['id']
        unique_item = f"REG-OPEN-{uuid.uuid4().hex[:6].upper()}"
        
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "item_description": "Regression Test Opening Balance",
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "opening_balance",
            "quantity_delta": 500,
            "unit_of_measure": "cases"
        })
        assert res.status_code == 200
        data = res.json()
        assert data['success'] == True
        assert data['movement']['movement_type'] == 'opening_balance'
        assert data['movement']['quantity_delta'] == 500

    def test_create_movement_order_commitment_still_works(self, api_client, test_workspace):
        """POST /api/inventory-ledger/customers/{id}/movements - order_commitment works"""
        workspace_id = test_workspace['id']
        unique_item = f"REG-COMMIT-{uuid.uuid4().hex[:6].upper()}"
        
        # First create opening balance
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "opening_balance",
            "quantity_delta": 100,
            "unit_of_measure": "units"
        })
        
        # Create commitment
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/movements", json={
            "item": unique_item,
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -25,
            "unit_of_measure": "units",
            "source_type": "sales_order_commitment",
            "reference_type": "sales_order",
            "reference_id": "SO-REG-TEST"
        })
        assert res.status_code == 200
        data = res.json()
        assert data['success'] == True
        assert data['movement']['movement_type'] == 'order_commitment'

    def test_derive_balances_still_works(self, api_client, test_workspace):
        """GET /api/inventory-ledger/customers/{id}/balances - derives balances"""
        workspace_id = test_workspace['id']
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{workspace_id}/balances")
        assert res.status_code == 200
        data = res.json()
        assert 'balances' in data
        assert 'count' in data
        assert 'customer_id' in data

    def test_meta_includes_order_release(self, api_client):
        """GET /api/inventory-ledger/meta - includes order_release movement type"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/meta")
        assert res.status_code == 200
        data = res.json()
        assert 'order_release' in data['movement_types']
        assert 'order_commitment' in data['movement_types']


class TestPreflightRegressionWithInventory:
    """REGRESSION: Preflight still returns inventory_summary and inventory_workspace"""

    @pytest.fixture(scope="class")
    def sales_order_doc_id(self, api_client):
        """Get a Sales_Order document for preflight testing"""
        res = api_client.get(f"{BASE_URL}/api/documents?document_type=Sales_Order&limit=5")
        docs = res.json().get('documents', [])
        if docs:
            return docs[0]['id']
        pytest.skip("No Sales_Order documents found")

    def test_preflight_still_returns_inventory_fields(self, api_client, sales_order_doc_id):
        """POST /api/gpi-integration/sales-orders/preflight/{doc_id} - still returns inventory_summary"""
        res = api_client.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{sales_order_doc_id}")
        assert res.status_code == 200
        data = res.json()
        assert 'inventory_summary' in data
        assert 'inventory_workspace' in data
