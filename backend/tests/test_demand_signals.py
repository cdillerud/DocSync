"""
Test suite for Demand Signals feature (iteration_70)
Tests GET /api/inventory-ledger/demand-signals endpoint and item-detail demand integration
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Hormel Foods customer ID with demand data
HORMEL_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"

class TestDemandSignals:
    """Tests for /api/inventory-ledger/demand-signals endpoint"""

    def test_demand_signals_returns_array(self):
        """GET /api/inventory-ledger/demand-signals returns total and demand_signals array"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/demand-signals", params={"customer_id": HORMEL_ID})
        assert res.status_code == 200
        data = res.json()
        assert "total" in data
        assert "demand_signals" in data
        assert isinstance(data["demand_signals"], list)
        assert data["total"] >= 0
        print(f"✓ Returned {data['total']} demand signals")

    def test_demand_signal_row_fields(self):
        """Each demand signal row has required fields"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/demand-signals", params={"customer_id": HORMEL_ID})
        assert res.status_code == 200
        data = res.json()
        
        if data["total"] > 0:
            row = data["demand_signals"][0]
            required_fields = [
                "item", "total_open_order_qty", "total_committed_qty", 
                "on_hand", "incoming", "available", "demand_gap", "status"
            ]
            for field in required_fields:
                assert field in row, f"Missing field: {field}"
            print(f"✓ Row has all required fields: {', '.join(required_fields)}")
        else:
            pytest.skip("No demand signals to validate fields")

    def test_demand_gap_calculation(self):
        """demand_gap = total_open_order_qty - available"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/demand-signals", params={"customer_id": HORMEL_ID})
        assert res.status_code == 200
        data = res.json()
        
        for row in data["demand_signals"]:
            expected_gap = row["total_open_order_qty"] - row["available"]
            actual_gap = row["demand_gap"]
            assert abs(actual_gap - expected_gap) < 0.01, f"Gap mismatch for {row['item']}: expected {expected_gap}, got {actual_gap}"
        print(f"✓ demand_gap calculation verified for {len(data['demand_signals'])} items")

    def test_sorted_by_demand_gap_descending(self):
        """Rows sorted by demand_gap descending (highest risk first)"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/demand-signals", params={"customer_id": HORMEL_ID})
        assert res.status_code == 200
        data = res.json()
        
        if len(data["demand_signals"]) > 1:
            gaps = [row["demand_gap"] for row in data["demand_signals"]]
            for i in range(len(gaps) - 1):
                assert gaps[i] >= gaps[i+1], f"Not sorted descending: {gaps[i]} < {gaps[i+1]}"
            print(f"✓ Sorted descending by demand_gap: {gaps}")
        else:
            pytest.skip("Need 2+ rows to verify sorting")

    def test_only_items_with_open_orders(self):
        """Only items with total_open_order_qty > 0 included"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/demand-signals", params={"customer_id": HORMEL_ID})
        assert res.status_code == 200
        data = res.json()
        
        for row in data["demand_signals"]:
            assert row["total_open_order_qty"] > 0, f"Item {row['item']} has 0 open orders but was included"
        print(f"✓ All {len(data['demand_signals'])} items have positive open order qty")

    def test_empty_customer_returns_empty_array(self):
        """Empty/nonexistent customer returns empty array"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/demand-signals", params={"customer_id": "nonexistent-fake-id"})
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 0
        assert data["demand_signals"] == []
        print("✓ Empty customer returns empty demand_signals array")

    def test_missing_customer_id_returns_422(self):
        """Missing customer_id returns 422"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/demand-signals")
        assert res.status_code == 422
        print("✓ Missing customer_id returns 422")

    def test_item_filter_works(self):
        """Item filter parameter works correctly"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/demand-signals", params={"customer_id": HORMEL_ID, "item": "SPAM-LITE"})
        assert res.status_code == 200
        data = res.json()
        
        if data["total"] > 0:
            assert len(data["demand_signals"]) == 1
            assert data["demand_signals"][0]["item"] == "SPAM-LITE"
            print("✓ Item filter returns only matching item")
        else:
            # Item might not have open orders
            print("✓ Item filter returns empty (item has no open orders)")


class TestItemDetailDemand:
    """Tests for demand field in item-detail endpoint"""

    def test_demand_present_when_committed_positive(self):
        """Item detail has demand field when committed > 0"""
        # SPAM-LITE has committed > 0 (999)
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/item-detail", params={"customer_id": HORMEL_ID, "item": "SPAM-LITE"})
        assert res.status_code == 200
        data = res.json()
        
        assert data["balance"]["committed"] > 0, "Test requires item with committed > 0"
        assert data["demand"] is not None, "demand should be present when committed > 0"
        assert "total_open_order_qty" in data["demand"]
        assert "demand_gap" in data["demand"]
        print(f"✓ demand field present for SPAM-LITE (committed={data['balance']['committed']})")

    def test_demand_null_when_committed_zero(self):
        """Item detail demand is null when committed = 0"""
        # IMPORT-ITEM-B has committed = 0
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/item-detail", params={"customer_id": HORMEL_ID, "item": "IMPORT-ITEM-B"})
        assert res.status_code == 200
        data = res.json()
        
        assert data["balance"]["committed"] == 0, "Test requires item with committed = 0"
        assert data["demand"] is None, "demand should be null when committed = 0"
        print(f"✓ demand is null for IMPORT-ITEM-B (committed=0)")

    def test_demand_values_correct(self):
        """Item detail demand.total_open_order_qty and demand.demand_gap are correct"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/item-detail", params={"customer_id": HORMEL_ID, "item": "SPAM-LITE"})
        assert res.status_code == 200
        data = res.json()
        
        committed = data["balance"]["committed"]
        available = data["balance"]["available"]
        demand = data["demand"]
        
        assert demand["total_open_order_qty"] == committed
        expected_gap = committed - available
        assert abs(demand["demand_gap"] - expected_gap) < 0.01
        print(f"✓ demand values correct: total_open_order_qty={committed}, demand_gap={demand['demand_gap']}")


class TestRegressionSuite:
    """Regression tests for existing features"""

    def test_dashboard_summary_still_works(self):
        """Dashboard summary endpoint still returns data"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/dashboard-summary", params={"customer_id": HORMEL_ID})
        assert res.status_code == 200
        data = res.json()
        assert "total_items" in data
        assert "items_ok" in data
        print("✓ Dashboard summary working")

    def test_exceptions_endpoint_still_works(self):
        """Exceptions endpoint still returns data"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/exceptions", params={"customer_id": HORMEL_ID})
        assert res.status_code == 200
        data = res.json()
        assert "exceptions" in data
        assert "exception_summary" in data
        print("✓ Exceptions endpoint working")

    def test_reorder_recommendations_still_works(self):
        """Reorder recommendations endpoint still returns data"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/reorder-recommendations", params={"customer_id": HORMEL_ID})
        assert res.status_code == 200
        data = res.json()
        assert "recommendations" in data
        print("✓ Reorder recommendations working")

    def test_snapshot_export_still_works(self):
        """Snapshot export endpoint still returns JSON"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot", params={"customer_id": HORMEL_ID})
        assert res.status_code == 200
        data = res.json()
        assert "summary" in data
        assert "balances" in data
        print("✓ Snapshot export working")

    def test_item_settings_still_works(self):
        """Item settings endpoint still returns data"""
        res = requests.get(f"{BASE_URL}/api/inventory-items/settings", params={"customer_id": HORMEL_ID})
        assert res.status_code == 200
        data = res.json()
        assert "settings" in data
        print("✓ Item settings working")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
