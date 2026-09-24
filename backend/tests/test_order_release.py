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
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


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
