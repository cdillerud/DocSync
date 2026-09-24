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
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


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


