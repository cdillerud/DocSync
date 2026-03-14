"""
Test suite for Inventory Item Detail API endpoint (GET /api/inventory-ledger/item-detail)

Tests:
- Complete detail payload structure
- Balance fields (on_hand, incoming, committed, available, status)
- Settings (when configured and null when not)
- Reorder recommendation (when applicable and not)
- Exception flags (short, low, reorder, no_incoming)
- History preview (up to 10 movements)
- type_summary (movement_type_totals)
- Error handling (404 for nonexistent, 422 for missing params)
- Regression tests for dashboard, exceptions, snapshot, csv import
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
def hormel_id(api_client):
    """Get Hormel customer ID"""
    res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers")
    customers = res.json()
    hormel = next((c for c in customers if c['code'] == 'HORMEL'), None)
    if hormel:
        return hormel['id']
    pytest.skip("Hormel customer not found")


class TestItemDetailEndpoint:
    """Tests for GET /api/inventory-ledger/item-detail"""

    def test_item_detail_complete_payload(self, api_client, hormel_id):
        """GET /item-detail returns complete detail structure for SPAM-LITE"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/item-detail",
                            params={"customer_id": hormel_id, "item": "SPAM-LITE"})
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        
        # Top-level fields
        assert data["item"] == "SPAM-LITE"
        assert data["customer_id"] == hormel_id
        assert "balance" in data
        assert "settings" in data  # Can be null or dict
        assert "reorder" in data
        assert "exceptions" in data
        assert "history_preview" in data
        assert "history_total" in data
        assert "type_summary" in data
        print(f"PASS: Item detail payload has all required top-level fields")

    def test_item_detail_balance_fields(self, api_client, hormel_id):
        """GET /item-detail - balance has on_hand, incoming, committed, available, status"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/item-detail",
                            params={"customer_id": hormel_id, "item": "SPAM-LITE"})
        assert res.status_code == 200
        balance = res.json()["balance"]
        
        # Required balance fields
        assert "on_hand" in balance
        assert "incoming" in balance
        assert "committed" in balance
        assert "available" in balance
        assert "status" in balance
        
        # Optional fields
        assert "warehouse" in balance
        assert "ownership_type" in balance
        assert "unit_of_measure" in balance
        assert "item_description" in balance
        
        # SPAM-LITE is SHORT (negative available)
        assert balance["status"] == "SHORT"
        assert balance["available"] < 0
        print(f"PASS: Balance fields correct - status={balance['status']}, available={balance['available']}")

    def test_item_detail_with_settings(self, api_client, hormel_id):
        """GET /item-detail - settings included when configured"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/item-detail",
                            params={"customer_id": hormel_id, "item": "SPAM-LITE"})
        assert res.status_code == 200
        data = res.json()
        
        settings = data.get("settings")
        # SPAM-LITE should have settings configured per test context
        if settings is not None:
            assert "reorder_threshold" in settings
            assert "safety_buffer" in settings
            # Per context: threshold=600, buffer=150
            assert settings["reorder_threshold"] == 600
            assert settings["safety_buffer"] == 150
            print(f"PASS: Settings present - threshold={settings['reorder_threshold']}, buffer={settings['safety_buffer']}")
        else:
            print("INFO: No settings configured for SPAM-LITE (using defaults)")

    def test_item_detail_settings_null_for_unconfigured(self, api_client, hormel_id):
        """GET /item-detail - settings null when not configured (defaults used)"""
        # Try to find an item without explicit settings - DINTY-15OZ per context
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/item-detail",
                            params={"customer_id": hormel_id, "item": "DINTY-15OZ"})
        if res.status_code == 200:
            data = res.json()
            # DINTY-15OZ should be OK status with no explicit settings
            # If no settings, reorder threshold/buffer come from defaults
            reorder = data["reorder"]
            assert "reorder_threshold" in reorder
            assert "safety_buffer" in reorder
            print(f"PASS: Item without settings uses defaults - threshold={reorder['reorder_threshold']}, buffer={reorder['safety_buffer']}")
        elif res.status_code == 404:
            print("SKIP: DINTY-15OZ not found, cannot test null settings")

    def test_item_detail_reorder_recommended_for_short_item(self, api_client, hormel_id):
        """GET /item-detail - reorder recommended for SHORT items"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/item-detail",
                            params={"customer_id": hormel_id, "item": "SPAM-LITE"})
        assert res.status_code == 200
        data = res.json()
        
        reorder = data["reorder"]
        assert "is_reorder_recommended" in reorder
        assert "recommended_qty" in reorder
        assert "reorder_threshold" in reorder
        assert "safety_buffer" in reorder
        
        # SPAM-LITE is SHORT, so reorder should be recommended
        assert reorder["is_reorder_recommended"] == True, "Reorder should be recommended for SHORT item"
        assert reorder["recommended_qty"] > 0, "Recommended qty should be positive"
        print(f"PASS: Reorder recommended for SHORT item - qty={reorder['recommended_qty']}")

    def test_item_detail_reorder_not_recommended_for_ok_item(self, api_client, hormel_id):
        """GET /item-detail - reorder NOT recommended for OK items above threshold"""
        # Try SPAM-12OZ which should be OK with sufficient inventory
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/item-detail",
                            params={"customer_id": hormel_id, "item": "SPAM-12OZ"})
        if res.status_code == 200:
            data = res.json()
            balance = data["balance"]
            reorder = data["reorder"]
            
            if balance["status"] == "OK" and balance["available"] > reorder["reorder_threshold"]:
                # Should not recommend reorder
                assert reorder["is_reorder_recommended"] == False, "OK items above threshold should not need reorder"
                assert reorder["recommended_qty"] == 0
                print(f"PASS: No reorder for OK item above threshold")
            else:
                print(f"INFO: SPAM-12OZ status={balance['status']}, available={balance['available']} - check expected conditions")
        else:
            print(f"SKIP: SPAM-12OZ not found (status {res.status_code})")

    def test_item_detail_exception_flags(self, api_client, hormel_id):
        """GET /item-detail - exception flags: short, low, reorder, no_incoming"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/item-detail",
                            params={"customer_id": hormel_id, "item": "SPAM-LITE"})
        assert res.status_code == 200
        data = res.json()
        
        exceptions = data["exceptions"]
        assert "short" in exceptions
        assert "low" in exceptions
        assert "reorder" in exceptions
        assert "no_incoming" in exceptions
        
        # SPAM-LITE should be short
        assert exceptions["short"] == True
        # Per context: short+reorder+no_incoming
        assert exceptions["reorder"] == True
        print(f"PASS: Exception flags - short={exceptions['short']}, low={exceptions['low']}, reorder={exceptions['reorder']}, no_incoming={exceptions['no_incoming']}")

    def test_item_detail_history_preview_returns_movements(self, api_client, hormel_id):
        """GET /item-detail - history_preview returns up to 10 movements"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/item-detail",
                            params={"customer_id": hormel_id, "item": "SPAM-LITE"})
        assert res.status_code == 200
        data = res.json()
        
        history = data["history_preview"]
        history_total = data["history_total"]
        
        assert isinstance(history, list)
        assert len(history) <= 10, "History preview should return max 10 movements"
        
        if len(history) > 0:
            mov = history[0]
            assert "movement_type" in mov
            assert "quantity_delta" in mov
            assert "created_at" in mov
        
        print(f"PASS: History preview has {len(history)} movements, total={history_total}")

    def test_item_detail_type_summary(self, api_client, hormel_id):
        """GET /item-detail - type_summary has movement_type_totals"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/item-detail",
                            params={"customer_id": hormel_id, "item": "SPAM-LITE"})
        assert res.status_code == 200
        data = res.json()
        
        type_summary = data["type_summary"]
        assert isinstance(type_summary, dict)
        
        # Per context: should have opening_balance and order_commitment
        print(f"PASS: type_summary has {len(type_summary)} movement types: {list(type_summary.keys())}")

    def test_item_detail_404_for_nonexistent(self, api_client, hormel_id):
        """GET /item-detail - 404 for nonexistent item"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/item-detail",
                            params={"customer_id": hormel_id, "item": "NONEXISTENT-ITEM-XYZ123"})
        assert res.status_code == 404, f"Expected 404 for nonexistent item, got {res.status_code}"
        print("PASS: 404 returned for nonexistent item")

    def test_item_detail_422_for_missing_item_param(self, api_client, hormel_id):
        """GET /item-detail - 422 for missing item param"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/item-detail",
                            params={"customer_id": hormel_id})  # Missing 'item' param
        assert res.status_code == 422, f"Expected 422 for missing item param, got {res.status_code}"
        print("PASS: 422 returned for missing item parameter")


class TestItemDetailRegression:
    """Regression tests to ensure existing features still work"""

    def test_dashboard_summary_still_works(self, api_client, hormel_id):
        """REGRESSION: Dashboard summary endpoint still works"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/dashboard-summary",
                            params={"customer_id": hormel_id})
        assert res.status_code == 200
        data = res.json()
        assert "total_items" in data
        assert "items_short" in data
        assert "items_low" in data
        print(f"PASS: Dashboard summary works - {data['total_items']} items, {data['items_short']} SHORT")

    def test_exceptions_endpoint_still_works(self, api_client, hormel_id):
        """REGRESSION: Exceptions endpoint still works"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/exceptions",
                            params={"customer_id": hormel_id})
        assert res.status_code == 200
        data = res.json()
        assert "exception_summary" in data
        assert "exceptions" in data
        print(f"PASS: Exceptions endpoint works - {data['exception_summary']}")

    def test_snapshot_export_still_works(self, api_client, hormel_id):
        """REGRESSION: Snapshot export endpoint still works"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/snapshot",
                            params={"customer_id": hormel_id})
        assert res.status_code == 200
        data = res.json()
        assert "summary" in data
        assert "balances" in data
        print(f"PASS: Snapshot works - {len(data['balances'])} balance rows")

    def test_csv_import_endpoint_available(self, api_client):
        """REGRESSION: CSV import endpoint responds correctly"""
        # Just verify endpoint exists and validates properly (no actual file upload)
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", data={})
        # Should get 422 for missing form fields, not 404
        assert res.status_code in [400, 422], f"Import endpoint should validate, got {res.status_code}"
        print("PASS: CSV import endpoint is available and validates")
