"""
Test suite for Inventory ↔ Sales Order Integration

Tests the integration between Customer Inventory Ledger and SO preflight/creation workflow:
1. Inventory workspace resolution in preflight
2. Line-level inventory enrichment (on_hand, committed, available, status)
3. Preflight response structure with inventory_summary and inventory_workspace
4. Order commitment creation on SO create

Prerequisite: Hormel Foods inventory workspace with SPAM-12OZ item seeded
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
def hormel_workspace(api_client):
    """Get Hormel workspace details"""
    res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers")
    customers = res.json()
    hormel = next((c for c in customers if c['code'] == 'HORMEL'), None)
    if hormel:
        return hormel
    pytest.skip("Hormel customer not found")


@pytest.fixture(scope="module")
def sales_order_doc_id(api_client):
    """Get a Sales_Order document for testing"""
    res = api_client.get(f"{BASE_URL}/api/documents?document_type=Sales_Order&limit=5")
    docs = res.json().get('documents', [])
    if docs:
        return docs[0]['id']
    pytest.skip("No Sales_Order documents found")


class TestPreflightInventoryIntegration:
    """Tests for inventory lookup in SO preflight"""

    def test_preflight_returns_inventory_fields(self, api_client, sales_order_doc_id):
        """POST /api/gpi-integration/sales-orders/preflight/{doc_id} - returns inventory_summary and inventory_workspace"""
        res = api_client.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{sales_order_doc_id}")
        assert res.status_code == 200
        data = res.json()
        
        # Verify inventory fields exist in response
        assert 'inventory_summary' in data
        assert 'inventory_workspace' in data
        
        # inventory_summary should have required structure
        inv_summary = data['inventory_summary']
        if inv_summary:
            # When there are workspaces available
            assert 'lines_matched' in inv_summary or 'total_lines' in inv_summary
            assert 'lines_no_match' in inv_summary or 'available_workspaces' in inv_summary

    def test_preflight_inventory_summary_structure(self, api_client, sales_order_doc_id):
        """Verify inventory_summary has correct structure"""
        res = api_client.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{sales_order_doc_id}")
        assert res.status_code == 200
        data = res.json()
        
        inv_summary = data.get('inventory_summary')
        if inv_summary and inv_summary.get('workspace_id'):
            # When workspace is matched
            required_fields = ['workspace_id', 'lines_matched', 'lines_short', 'lines_no_match', 'total_lines']
            for field in required_fields:
                assert field in inv_summary, f"Missing field: {field}"
        elif inv_summary and inv_summary.get('available_workspaces'):
            # When no workspace matched but workspaces exist
            assert isinstance(inv_summary['available_workspaces'], list)

    def test_preflight_resolved_lines_have_inventory(self, api_client, sales_order_doc_id):
        """Verify resolved_lines contain inventory field when workspace matched"""
        res = api_client.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{sales_order_doc_id}")
        assert res.status_code == 200
        data = res.json()
        
        resolved_lines = data.get('resolved_lines', [])
        inv_workspace = data.get('inventory_workspace')
        
        if inv_workspace and resolved_lines:
            # When workspace is matched, lines should have inventory field
            for line in resolved_lines:
                assert 'inventory' in line, "Line missing inventory field"
                inv = line['inventory']
                assert 'status' in inv
                assert 'matched' in inv
                if inv['matched']:
                    assert 'on_hand' in inv
                    assert 'committed' in inv
                    assert 'available' in inv

    def test_preflight_no_match_has_available_workspaces(self, api_client, sales_order_doc_id):
        """When no workspace matches, available_workspaces should be provided"""
        res = api_client.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{sales_order_doc_id}")
        assert res.status_code == 200
        data = res.json()
        
        if data.get('inventory_workspace') is None and data.get('inventory_summary'):
            inv_summary = data['inventory_summary']
            # Should have available_workspaces when no match
            if inv_summary.get('match_method') == 'no_match':
                assert 'available_workspaces' in inv_summary
                assert isinstance(inv_summary['available_workspaces'], list)


class TestInventoryWorkspaceResolution:
    """Tests for workspace resolution by customer_no/name"""

    def test_preflight_with_hormel_customer(self, api_client, hormel_workspace):
        """Test preflight with a document containing Hormel customer"""
        # Create a test document with Hormel customer
        unique_id = f"test-inv-{uuid.uuid4().hex[:8]}"
        
        # First check if there's an existing doc with Hormel customer
        res = api_client.get(f"{BASE_URL}/api/documents?limit=100")
        docs = res.json().get('documents', [])
        
        # Find doc with customer name containing 'Hormel'
        hormel_doc = next(
            (d for d in docs 
             if 'hormel' in str(d.get('extracted_fields', {}).get('customer', '')).lower()
             or 'HORMEL' in str(d.get('extracted_fields', {}).get('customer', '')).upper()),
            None
        )
        
        if hormel_doc:
            res = api_client.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{hormel_doc['id']}")
            assert res.status_code == 200
            data = res.json()
            
            # If Hormel workspace matched
            if data.get('inventory_workspace'):
                assert data['inventory_workspace']['code'] == 'HORMEL'
                assert data['inventory_summary']['workspace_name'] == 'Hormel Foods'

    def test_inventory_workspace_structure(self, api_client, sales_order_doc_id):
        """Verify inventory_workspace has correct structure when present"""
        res = api_client.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{sales_order_doc_id}")
        assert res.status_code == 200
        data = res.json()
        
        inv_ws = data.get('inventory_workspace')
        if inv_ws:
            required_fields = ['id', 'name', 'code', 'negative_balance_policy']
            for field in required_fields:
                assert field in inv_ws, f"Missing field: {field}"
            assert inv_ws['negative_balance_policy'] in ['warn_only', 'block_commitment']


class TestInventoryLineEnrichment:
    """Tests for line-level inventory enrichment"""

    def test_line_inventory_status_values(self, api_client, sales_order_doc_id):
        """Verify inventory status is one of: OK, LOW, SHORT, NO_MATCH"""
        res = api_client.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{sales_order_doc_id}")
        assert res.status_code == 200
        data = res.json()
        
        resolved_lines = data.get('resolved_lines', [])
        valid_statuses = {'OK', 'LOW', 'SHORT', 'NO_MATCH'}
        
        for line in resolved_lines:
            if 'inventory' in line:
                status = line['inventory'].get('status')
                assert status in valid_statuses, f"Invalid status: {status}"

    def test_inventory_availability_math(self, api_client, hormel_workspace):
        """Test that available = on_hand + incoming - committed"""
        # Get Hormel balances directly
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_workspace['id']}/balances?item=SPAM-12OZ")
        assert res.status_code == 200
        data = res.json()
        
        balances = data.get('balances', [])
        if balances:
            bal = balances[0]
            expected_available = bal['on_hand'] + bal['incoming'] - bal['committed']
            assert bal['available'] == expected_available, f"Available mismatch: got {bal['available']}, expected {expected_available}"


class TestInventoryAPIsCRUD:
    """Tests for inventory CRUD APIs (recap from standalone tests)"""

    def test_list_customers(self, api_client):
        """GET /api/inventory-ledger/customers - list workspaces"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) >= 2  # Hormel and Karlin minimum

    def test_create_movement_order_commitment(self, api_client, hormel_workspace):
        """POST /api/inventory-ledger/customers/{id}/movements - create order_commitment"""
        unique_item = f"TEST-COMMIT-{uuid.uuid4().hex[:6].upper()}"
        
        # First create opening balance
        api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_workspace['id']}/movements", json={
            "item": unique_item,
            "warehouse": "GPI-MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "opening_balance",
            "quantity_delta": 100,
            "unit_of_measure": "cases",
        })
        
        # Create order_commitment
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_workspace['id']}/movements", json={
            "item": unique_item,
            "warehouse": "GPI-MAIN",
            "ownership_type": "customer_owned",
            "movement_type": "order_commitment",
            "quantity_delta": -25,
            "unit_of_measure": "cases",
            "source_type": "sales_order_commitment",
            "reference_type": "sales_order",
            "reference_id": "SO-TEST-001"
        })
        assert res.status_code == 200
        data = res.json()
        assert data['success'] == True
        assert data['movement']['movement_type'] == 'order_commitment'

    def test_get_balances(self, api_client, hormel_workspace):
        """GET /api/inventory-ledger/customers/{id}/balances - returns derived balances"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{hormel_workspace['id']}/balances")
        assert res.status_code == 200
        data = res.json()
        assert 'balances' in data
        assert 'count' in data


class TestPreflightSOCreation:
    """Tests for SO creation with inventory commitments"""

    def test_preflight_eligible_document(self, api_client, sales_order_doc_id):
        """Verify preflight returns eligible=true for Sales_Order documents"""
        res = api_client.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{sales_order_doc_id}")
        assert res.status_code == 200
        data = res.json()
        assert data['eligible'] == True

    def test_preflight_returns_mapped_values(self, api_client, sales_order_doc_id):
        """Verify mapped_values contains BC environment info"""
        res = api_client.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{sales_order_doc_id}")
        assert res.status_code == 200
        data = res.json()
        
        mv = data.get('mapped_values', {})
        assert 'bc_read_environment' in mv
        assert 'bc_write_environment' in mv
        assert 'idempotency_key' in mv

    def test_preflight_returns_document_summary(self, api_client, sales_order_doc_id):
        """Verify document_summary has correct structure"""
        res = api_client.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{sales_order_doc_id}")
        assert res.status_code == 200
        data = res.json()
        
        ds = data.get('document_summary', {})
        required_fields = ['document_id', 'file_name', 'document_type']
        for field in required_fields:
            assert field in ds, f"Missing field in document_summary: {field}"

    def test_preflight_returns_validation_checklist(self, api_client, sales_order_doc_id):
        """Verify validation_checklist has correct structure"""
        res = api_client.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{sales_order_doc_id}")
        assert res.status_code == 200
        data = res.json()
        
        checklist = data.get('validation_checklist', [])
        assert isinstance(checklist, list)
        
        for item in checklist:
            assert 'label' in item
            assert 'passed' in item
            assert 'detail' in item


class TestInventoryMeta:
    """Tests for inventory meta endpoint"""

    def test_meta_endpoint(self, api_client):
        """GET /api/inventory-ledger/meta - returns valid enums"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/meta")
        assert res.status_code == 200
        data = res.json()
        
        assert 'movement_types' in data
        assert 'source_types' in data
        assert 'ownership_types' in data
        assert 'order_commitment' in data['movement_types']
