"""
Test suite for Customer Inventory Ledger Module
Tests all API endpoints for the ledger-based inventory management system.

Features tested:
- Customer workspace CRUD
- Derived balances from movement ledger
- Movement creation with negative balance policy enforcement
- Incoming supply management
- Seed/import functionality
- Meta endpoint for valid enums
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
def hormel_id(api_client):
    """Get Hormel customer ID (warn_only policy)"""
    res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers")
    customers = res.json()
    hormel = next((c for c in customers if c['code'] == 'HORMEL'), None)
    if hormel:
        return hormel['id']
    pytest.skip("Hormel customer not found")


@pytest.fixture(scope="module")
def karlin_id(api_client):
    """Get Karlin customer ID (block_commitment policy)"""
    res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers")
    customers = res.json()
    karlin = next((c for c in customers if c['code'] == 'KARLIN'), None)
    if karlin:
        return karlin['id']
    pytest.skip("Karlin customer not found")


class TestCustomerEndpoints:
    """Tests for customer workspace endpoints"""

    def test_list_customers(self, api_client):
        """GET /api/inventory-ledger/customers - list customer workspaces"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) >= 2  # Hormel and Karlin seeded
        
        # Verify structure
        cust = data[0]
        assert 'id' in cust
        assert 'name' in cust
        assert 'code' in cust
        assert 'negative_balance_policy' in cust
        assert cust['negative_balance_policy'] in ['warn_only', 'block_commitment']

    def test_get_customer(self, api_client, hormel_id):
        """GET /api/inventory-ledger/customers/{id} - get single customer"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_id}")
        assert res.status_code == 200
        data = res.json()
        assert data['id'] == hormel_id
        assert data['name'] == 'Hormel Foods'
        assert data['code'] == 'HORMEL'
        assert data['negative_balance_policy'] == 'warn_only'

    def test_create_customer(self, api_client):
        """POST /api/inventory-ledger/customers - create new workspace"""
        unique_code = f"TEST{uuid.uuid4().hex[:6].upper()}"
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers", json={
            "name": f"TEST_Customer_{unique_code}",
            "code": unique_code,
            "negative_balance_policy": "block_commitment"
        })
        assert res.status_code == 200
        data = res.json()
        assert 'id' in data
        assert data['name'] == f"TEST_Customer_{unique_code}"
        assert data['code'] == unique_code
        assert data['negative_balance_policy'] == 'block_commitment'
        assert data['active'] == True

    def test_customer_not_found(self, api_client):
        """GET /api/inventory-ledger/customers/{invalid_id} - 404"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/invalid-uuid")
        assert res.status_code == 404


class TestBalancesEndpoint:
    """Tests for derived balance endpoint"""

    def test_get_balances(self, api_client, hormel_id):
        """GET /api/inventory-ledger/customers/{id}/balances - returns derived balances"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_id}/balances")
        assert res.status_code == 200
        data = res.json()
        assert data['customer_id'] == hormel_id
        assert 'balances' in data
        assert 'count' in data
        assert isinstance(data['balances'], list)
        
        if len(data['balances']) > 0:
            bal = data['balances'][0]
            # Verify balance structure
            assert 'item' in bal
            assert 'warehouse' in bal
            assert 'ownership_type' in bal
            assert 'unit_of_measure' in bal
            assert 'on_hand' in bal
            assert 'incoming' in bal
            assert 'committed' in bal
            assert 'available' in bal
            assert 'is_short' in bal
            assert 'is_low' in bal

    def test_balance_math_spam_12oz(self, api_client, hormel_id):
        """Verify balance derivation math for SPAM-12OZ"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_id}/balances?item=SPAM-12OZ&warehouse=GPI-MAIN")
        assert res.status_code == 200
        data = res.json()
        
        # Find the SPAM-12OZ GPI-MAIN bucket
        spam_bucket = next((b for b in data['balances'] if b['item'] == 'SPAM-12OZ' and b['warehouse'] == 'GPI-MAIN'), None)
        if spam_bucket:
            # Expected: 500(opening) + 100(receipt) = 600 on_hand, 300 incoming, 200 committed -> 700 available
            assert spam_bucket['on_hand'] == 600
            assert spam_bucket['incoming'] == 300
            assert spam_bucket['committed'] == 200
            assert spam_bucket['available'] == 700
            assert spam_bucket['is_short'] == False

    def test_shortage_detection(self, api_client, hormel_id):
        """Verify shortage detection for SPAM-LITE (over-committed)"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_id}/balances")
        assert res.status_code == 200
        data = res.json()
        
        # Find SPAM-LITE which should be short
        spam_lite = next((b for b in data['balances'] if b['item'] == 'SPAM-LITE'), None)
        if spam_lite:
            assert spam_lite['is_short'] == True
            assert spam_lite['available'] < 0


class TestSummaryEndpoint:
    """Tests for customer summary endpoint"""

    def test_get_summary(self, api_client, hormel_id):
        """GET /api/inventory-ledger/customers/{id}/summary - returns summary counts"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_id}/summary")
        assert res.status_code == 200
        data = res.json()
        
        assert data['customer_id'] == hormel_id
        assert data['customer_name'] == 'Hormel Foods'
        assert 'total_items' in data
        assert 'total_buckets' in data
        assert 'total_on_hand' in data
        assert 'total_incoming' in data
        assert 'total_committed' in data
        assert 'shortage_count' in data
        assert 'low_count' in data
        
        # Hormel should have at least 1 shortage (SPAM-LITE)
        assert data['shortage_count'] >= 1


class TestMovementsEndpoint:
    """Tests for movement ledger endpoints"""

    def test_list_movements(self, api_client, hormel_id):
        """GET /api/inventory-ledger/customers/{id}/movements - list movement history"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_id}/movements")
        assert res.status_code == 200
        data = res.json()
        
        assert 'movements' in data
        assert 'total' in data
        assert isinstance(data['movements'], list)
        
        if len(data['movements']) > 0:
            mov = data['movements'][0]
            assert 'id' in mov
            assert 'item' in mov
            assert 'movement_type' in mov
            assert 'quantity_delta' in mov
            assert 'created_at' in mov

    def test_create_receipt_movement(self, api_client, hormel_id):
        """POST /api/inventory-ledger/customers/{id}/movements - create receipt"""
        unique_item = f"TEST-RECEIPT-{uuid.uuid4().hex[:6].upper()}"
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_id}/movements", json={
            "item": unique_item,
            "item_description": "Test Receipt Item",
            "warehouse": "GPI-MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "receipt",
            "quantity_delta": 100,
            "unit_of_measure": "cases",
            "source_type": "manual_entry"
        })
        assert res.status_code == 200
        data = res.json()
        assert data['success'] == True
        assert 'movement' in data
        assert data['movement']['item'] == unique_item
        assert data['movement']['quantity_delta'] == 100
        assert data['movement']['movement_type'] == 'receipt'

    def test_warn_only_commitment(self, api_client, hormel_id):
        """POST /api/inventory-ledger/customers/{id}/movements - warn_only allows negative with warning"""
        unique_item = f"TEST-WARNONLY-{uuid.uuid4().hex[:6].upper()}"
        
        # First create some inventory
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_id}/movements", json={
            "item": unique_item,
            "warehouse": "GPI-MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "opening_balance",
            "quantity_delta": 10,
            "unit_of_measure": "cases",
        })
        
        # Now commit more than available - should succeed with warning
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_id}/movements", json={
            "item": unique_item,
            "warehouse": "GPI-MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -100,  # More than 10 available
            "unit_of_measure": "cases",
        })
        assert res.status_code == 200
        data = res.json()
        assert data['success'] == True
        assert data['warning'] is not None  # Should have warning

    def test_block_commitment_policy(self, api_client, karlin_id):
        """POST /api/inventory-ledger/customers/{id}/movements - block_commitment returns 422"""
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{karlin_id}/movements", json={
            "item": "COFFEE-LB",
            "warehouse": "MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -10000,  # Way more than available (10)
            "unit_of_measure": "bags",
        })
        assert res.status_code == 422
        data = res.json()
        assert 'detail' in data
        assert 'blocked' in data['detail'].lower() or 'block' in data['detail'].lower()


class TestIncomingSupplyEndpoint:
    """Tests for incoming supply management"""

    def test_list_incoming(self, api_client, hormel_id):
        """GET /api/inventory-ledger/customers/{id}/incoming - list incoming supply"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_id}/incoming")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)

    def test_create_incoming(self, api_client, hormel_id):
        """POST /api/inventory-ledger/customers/{id}/incoming - create incoming supply"""
        unique_item = f"TEST-INC-{uuid.uuid4().hex[:6].upper()}"
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_id}/incoming", json={
            "item": unique_item,
            "item_description": "Test Incoming Item",
            "warehouse": "GPI-MAIN",
            "ownership_type": "customer_owned",
            "incoming_qty": 500,
            "unit_of_measure": "cases",
            "eta": "2026-05-01",
            "source_reference": "PO-TEST"
        })
        assert res.status_code == 200
        data = res.json()
        assert 'id' in data
        assert data['item'] == unique_item
        assert data['incoming_qty'] == 500
        assert data['status'] == 'expected'
        return data['id']

    def test_update_incoming_status(self, api_client, hormel_id):
        """PUT /api/inventory-ledger/customers/{id}/incoming/{supply_id} - update status"""
        # Create supply first
        unique_item = f"TEST-STATUS-{uuid.uuid4().hex[:6].upper()}"
        create_res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_id}/incoming", json={
            "item": unique_item,
            "warehouse": "GPI-MAIN",
            "ownership_type": "customer_owned",
            "incoming_qty": 100,
            "unit_of_measure": "cases",
        })
        supply_id = create_res.json()['id']
        
        # Update to in_transit
        res = api_client.put(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_id}/incoming/{supply_id}", json={
            "status": "in_transit"
        })
        assert res.status_code == 200
        assert res.json()['status'] == 'in_transit'
        
        # Update to received
        res = api_client.put(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_id}/incoming/{supply_id}", json={
            "status": "received"
        })
        assert res.status_code == 200
        assert res.json()['status'] == 'received'


class TestSeedEndpoint:
    """Tests for batch seed/import endpoint"""

    def test_seed_opening_balances(self, api_client):
        """POST /api/inventory-ledger/customers/{id}/seed - batch seed"""
        # Create a new customer for seeding
        unique_code = f"SEED{uuid.uuid4().hex[:4].upper()}"
        create_res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers", json={
            "name": f"TEST_Seed_Customer_{unique_code}",
            "code": unique_code,
            "negative_balance_policy": "warn_only"
        })
        new_cust_id = create_res.json()['id']
        
        # Seed balances
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{new_cust_id}/seed", json={
            "rows": [
                {"item": "SEED-ITEM-A", "item_description": "Seeded A", "warehouse": "WH1", "quantity": 100, "unit_of_measure": "units"},
                {"item": "SEED-ITEM-B", "item_description": "Seeded B", "warehouse": "WH1", "quantity": 200, "unit_of_measure": "units"},
                {"item": "SEED-ITEM-C", "item_description": "Seeded C", "warehouse": "WH2", "quantity": 300, "unit_of_measure": "units"},
            ]
        })
        assert res.status_code == 200
        data = res.json()
        assert data['seeded'] == 3
        assert data['errors'] == 0
        
        # Verify via balances
        bal_res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{new_cust_id}/balances")
        balances = bal_res.json()['balances']
        assert len(balances) == 3


class TestMetaEndpoint:
    """Tests for meta/enum endpoint"""

    def test_get_meta(self, api_client):
        """GET /api/inventory-ledger/meta - returns valid enums"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/meta")
        assert res.status_code == 200
        data = res.json()
        
        assert 'movement_types' in data
        assert 'source_types' in data
        assert 'ownership_types' in data
        
        # Verify expected movement types
        expected_movements = {'opening_balance', 'receipt', 'order_commitment', 'order_release', 'manual_adjustment', 'transfer', 'writeoff', 'correction'}
        assert set(data['movement_types']) == expected_movements
        
        # Verify expected ownership types
        expected_ownership = {'customer_owned', 'gamer_reserved', 'mixed', 'unknown'}
        assert set(data['ownership_types']) == expected_ownership
