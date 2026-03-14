"""
Inventory Exceptions Endpoint Tests (iteration_68)

Tests for GET /api/inventory-ledger/exceptions endpoint:
- Returns exception items needing attention
- Exception classification (short, low, reorder, no_incoming)
- Exception summary counts
- Filtering by exception_type
- Sorting by available ascending
- Field validation
"""

import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
HORMEL_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"  # Known customer with exceptions


class TestExceptionsEndpoint:
    """Tests for /api/inventory-ledger/exceptions endpoint"""

    def test_exceptions_returns_expected_structure(self):
        """GET /api/inventory-ledger/exceptions returns total, exception_summary, exceptions array"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "total" in data, "Response missing 'total' field"
        assert "exception_summary" in data, "Response missing 'exception_summary' field"
        assert "exceptions" in data, "Response missing 'exceptions' field"
        assert isinstance(data["exceptions"], list), "exceptions should be a list"
        
        print(f"Total exceptions: {data['total']}")
        print(f"Exception summary: {data['exception_summary']}")

    def test_exception_summary_has_all_counts(self):
        """exception_summary has short_count, low_count, reorder_count, no_incoming_count"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        summary = response.json()["exception_summary"]
        
        expected_fields = ["short_count", "low_count", "reorder_count", "no_incoming_count"]
        for field in expected_fields:
            assert field in summary, f"exception_summary missing '{field}'"
            assert isinstance(summary[field], int), f"{field} should be int, got {type(summary[field])}"
        
        print(f"Summary counts: short={summary['short_count']}, low={summary['low_count']}, "
              f"reorder={summary['reorder_count']}, no_incoming={summary['no_incoming_count']}")

    def test_short_items_have_short_in_exception_types(self):
        """SHORT items have 'short' in exception_types"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        short_items = [e for e in data["exceptions"] if e.get("status") == "SHORT"]
        assert len(short_items) > 0, "Expected at least one SHORT item in exceptions"
        
        for item in short_items:
            assert "short" in item["exception_types"], f"SHORT item {item['item']} missing 'short' in exception_types"
        
        print(f"Verified {len(short_items)} SHORT items have 'short' in exception_types")

    def test_low_items_have_low_in_exception_types(self):
        """LOW items have 'low' in exception_types"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        low_items = [e for e in data["exceptions"] if e.get("status") == "LOW"]
        assert len(low_items) > 0, "Expected at least one LOW item in exceptions"
        
        for item in low_items:
            assert "low" in item["exception_types"], f"LOW item {item['item']} missing 'low' in exception_types"
        
        print(f"Verified {len(low_items)} LOW items have 'low' in exception_types")

    def test_reorder_items_have_recommended_qty(self):
        """Reorder items have 'reorder' in exception_types and recommended_qty field"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        reorder_items = [e for e in data["exceptions"] if "reorder" in e.get("exception_types", [])]
        assert len(reorder_items) > 0, "Expected at least one item with 'reorder' exception type"
        
        for item in reorder_items:
            assert "recommended_qty" in item, f"Reorder item {item['item']} missing 'recommended_qty'"
            assert isinstance(item["recommended_qty"], (int, float)), "recommended_qty should be numeric"
        
        print(f"Verified {len(reorder_items)} reorder items have recommended_qty field")

    def test_no_incoming_items_are_short_or_low_with_zero_incoming(self):
        """no_incoming items are SHORT/LOW with incoming=0"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        no_incoming_items = [e for e in data["exceptions"] if "no_incoming" in e.get("exception_types", [])]
        assert len(no_incoming_items) > 0, "Expected at least one item with 'no_incoming' exception type"
        
        for item in no_incoming_items:
            assert item.get("incoming", -1) == 0, f"no_incoming item {item['item']} has incoming={item.get('incoming')}"
            assert item.get("status") in ("SHORT", "LOW"), f"no_incoming item {item['item']} has status={item.get('status')}"
        
        print(f"Verified {len(no_incoming_items)} no_incoming items have incoming=0 and status SHORT/LOW")

    def test_exception_summary_short_count_matches_dashboard(self):
        """exception_summary short_count matches dashboard items_short"""
        # Get dashboard summary
        dash_response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/dashboard-summary",
            params={"customer_id": HORMEL_ID}
        )
        assert dash_response.status_code == 200
        dash_items_short = dash_response.json()["items_short"]
        
        # Get exceptions
        exc_response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID}
        )
        assert exc_response.status_code == 200
        exc_short_count = exc_response.json()["exception_summary"]["short_count"]
        
        assert exc_short_count == dash_items_short, f"short_count {exc_short_count} != dashboard items_short {dash_items_short}"
        print(f"Verified: exception_summary short_count ({exc_short_count}) matches dashboard items_short ({dash_items_short})")

    def test_exception_summary_low_count_matches_dashboard(self):
        """exception_summary low_count matches dashboard items_low"""
        # Get dashboard summary
        dash_response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/dashboard-summary",
            params={"customer_id": HORMEL_ID}
        )
        assert dash_response.status_code == 200
        dash_items_low = dash_response.json()["items_low"]
        
        # Get exceptions
        exc_response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID}
        )
        assert exc_response.status_code == 200
        exc_low_count = exc_response.json()["exception_summary"]["low_count"]
        
        assert exc_low_count == dash_items_low, f"low_count {exc_low_count} != dashboard items_low {dash_items_low}"
        print(f"Verified: exception_summary low_count ({exc_low_count}) matches dashboard items_low ({dash_items_low})")

    def test_filter_by_short_exception_type(self):
        """exception_type=short filters to SHORT items only"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID, "exception_type": "short"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # All returned items should have 'short' in exception_types
        for item in data["exceptions"]:
            assert "short" in item["exception_types"], f"Item {item['item']} doesn't have 'short' exception type"
        
        # Summary should still have complete counts (computed before filter)
        assert "short_count" in data["exception_summary"]
        
        print(f"Filtered to {len(data['exceptions'])} items with 'short' exception type")

    def test_filter_by_low_exception_type(self):
        """exception_type=low filters to LOW items only"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID, "exception_type": "low"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # All returned items should have 'low' in exception_types
        for item in data["exceptions"]:
            assert "low" in item["exception_types"], f"Item {item['item']} doesn't have 'low' exception type"
        
        print(f"Filtered to {len(data['exceptions'])} items with 'low' exception type")

    def test_filter_by_no_incoming_exception_type(self):
        """exception_type=no_incoming filters correctly"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID, "exception_type": "no_incoming"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # All returned items should have 'no_incoming' in exception_types
        for item in data["exceptions"]:
            assert "no_incoming" in item["exception_types"], f"Item {item['item']} doesn't have 'no_incoming' exception type"
        
        print(f"Filtered to {len(data['exceptions'])} items with 'no_incoming' exception type")

    def test_filter_by_reorder_exception_type(self):
        """exception_type=reorder filters to reorder items"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID, "exception_type": "reorder"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # All returned items should have 'reorder' in exception_types
        for item in data["exceptions"]:
            assert "reorder" in item["exception_types"], f"Item {item['item']} doesn't have 'reorder' exception type"
        
        print(f"Filtered to {len(data['exceptions'])} items with 'reorder' exception type")

    def test_results_sorted_by_available_ascending(self):
        """Results are sorted by available ascending (most critical first)"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        exceptions = response.json()["exceptions"]
        
        if len(exceptions) > 1:
            availables = [e.get("available", 0) for e in exceptions]
            sorted_availables = sorted(availables)
            assert availables == sorted_availables, f"Exceptions not sorted by available ascending: {availables}"
        
        print(f"Verified {len(exceptions)} exceptions sorted by available ascending")

    def test_exception_rows_have_required_fields(self):
        """Each exception row has all required fields"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        exceptions = response.json()["exceptions"]
        
        required_fields = ["item", "on_hand", "incoming", "committed", "available", "status", "exception_types"]
        
        for exc in exceptions:
            for field in required_fields:
                assert field in exc, f"Exception row for {exc.get('item', 'unknown')} missing '{field}'"
        
        print(f"All {len(exceptions)} exception rows have required fields")

    def test_empty_customer_returns_zeros_and_empty_array(self):
        """Empty/nonexistent customer returns zeros and empty exceptions array"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": "nonexistent-customer-id-12345"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["total"] == 0, f"Expected total=0, got {data['total']}"
        assert len(data["exceptions"]) == 0, f"Expected empty exceptions, got {len(data['exceptions'])}"
        assert data["exception_summary"]["short_count"] == 0
        assert data["exception_summary"]["low_count"] == 0
        assert data["exception_summary"]["reorder_count"] == 0
        assert data["exception_summary"]["no_incoming_count"] == 0
        
        print("Verified empty customer returns zeros and empty array")

    def test_missing_customer_id_returns_422(self):
        """Missing customer_id returns 422"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/exceptions")
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        print("Verified missing customer_id returns 422")


class TestRegressionAfterExceptions:
    """Regression tests to ensure existing features still work"""

    def test_dashboard_summary_still_works(self):
        """Dashboard summary endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/dashboard-summary",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_items" in data
        assert "items_short" in data
        assert "items_low" in data
        print(f"Dashboard summary: {data['total_items']} items, {data['items_short']} short, {data['items_low']} low")

    def test_balances_endpoint_still_works(self):
        """Balances endpoint still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_ID}/balances")
        assert response.status_code == 200
        data = response.json()
        assert "balances" in data
        assert len(data["balances"]) > 0
        print(f"Balances: {len(data['balances'])} rows")

    def test_reorder_recommendations_still_works(self):
        """Reorder recommendations endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/reorder-recommendations",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        data = response.json()
        assert "recommendations" in data
        print(f"Reorder recommendations: {len(data['recommendations'])} items")

    def test_snapshot_export_still_works(self):
        """Snapshot export endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/snapshot/export",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        assert "Content-Disposition" in response.headers
        print("Snapshot export still works")

    def test_item_settings_endpoint_still_works(self):
        """Item settings endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-items/settings",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        data = response.json()
        assert "settings" in data
        print(f"Item settings: {len(data['settings'])} configured items")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
