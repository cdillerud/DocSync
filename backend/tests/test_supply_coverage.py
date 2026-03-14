"""
Supply Coverage Endpoint Tests
Tests for GET /api/inventory-ledger/supply-coverage

Coverage = on_hand + incoming - committed
coverage_status = 'covered' (>=0) or 'at_risk' (<0)
Only items with committed > 0 included
Sorted by coverage ascending (largest shortages first)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test customer: Hormel Foods
HORMEL_CUSTOMER_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"


class TestSupplyCoverageEndpoint:
    """Tests for GET /api/inventory-ledger/supply-coverage"""

    def test_returns_total_and_coverage_array(self):
        """Verify endpoint returns total count and coverage array"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/supply-coverage",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "total" in data
        assert "coverage" in data
        assert isinstance(data["total"], int)
        assert isinstance(data["coverage"], list)
        assert data["total"] == len(data["coverage"])

    def test_coverage_calculation(self):
        """Verify coverage = on_hand + incoming - committed"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/supply-coverage",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        for row in data["coverage"]:
            expected_coverage = row["on_hand"] + row["incoming"] - row["committed"]
            assert row["coverage"] == expected_coverage, (
                f"Coverage mismatch for {row['item']}: "
                f"expected {expected_coverage}, got {row['coverage']}"
            )

    def test_coverage_status_covered(self):
        """Verify coverage_status = 'covered' when coverage >= 0"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/supply-coverage",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        covered_items = [r for r in data["coverage"] if r["coverage"] >= 0]
        assert len(covered_items) > 0, "Expected at least one covered item"
        
        for row in covered_items:
            assert row["coverage_status"] == "covered", (
                f"Item {row['item']} has coverage={row['coverage']} "
                f"but status={row['coverage_status']}"
            )

    def test_coverage_status_at_risk(self):
        """Verify coverage_status = 'at_risk' when coverage < 0"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/supply-coverage",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        at_risk_items = [r for r in data["coverage"] if r["coverage"] < 0]
        assert len(at_risk_items) > 0, "Expected at least one at_risk item"
        
        for row in at_risk_items:
            assert row["coverage_status"] == "at_risk", (
                f"Item {row['item']} has coverage={row['coverage']} "
                f"but status={row['coverage_status']}"
            )

    def test_only_committed_items_included(self):
        """Verify only items with committed > 0 are included"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/supply-coverage",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        for row in data["coverage"]:
            assert row["committed"] > 0, (
                f"Item {row['item']} has committed={row['committed']} "
                f"but should only include items with committed > 0"
            )

    def test_sorted_by_coverage_ascending(self):
        """Verify results sorted by coverage ascending (largest shortages first)"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/supply-coverage",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data["coverage"]) > 1:
            coverages = [r["coverage"] for r in data["coverage"]]
            assert coverages == sorted(coverages), (
                f"Coverage values not sorted ascending: {coverages}"
            )

    def test_row_has_required_fields(self):
        """Verify each row has all required fields"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/supply-coverage",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            "item", "on_hand", "incoming", "committed", 
            "available", "coverage", "coverage_status"
        ]
        
        for row in data["coverage"]:
            for field in required_fields:
                assert field in row, f"Missing required field: {field}"

    def test_empty_customer_returns_empty_array(self):
        """Verify empty/nonexistent customer returns empty coverage array"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/supply-coverage",
            params={"customer_id": "nonexistent-customer-id"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["total"] == 0
        assert data["coverage"] == []

    def test_missing_customer_id_returns_422(self):
        """Verify missing customer_id returns 422 error"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/supply-coverage"
        )
        assert response.status_code == 422

    def test_item_filter_works(self):
        """Verify item filter parameter works correctly"""
        # First get all items
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/supply-coverage",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        all_data = response.json()
        
        if len(all_data["coverage"]) > 0:
            # Filter by first item
            test_item = all_data["coverage"][0]["item"]
            filtered_response = requests.get(
                f"{BASE_URL}/api/inventory-ledger/supply-coverage",
                params={"customer_id": HORMEL_CUSTOMER_ID, "item": test_item}
            )
            assert filtered_response.status_code == 200
            filtered_data = filtered_response.json()
            
            assert filtered_data["total"] == 1
            assert filtered_data["coverage"][0]["item"] == test_item


class TestItemDetailSupplyCoverage:
    """Tests for supply_coverage field in GET /api/inventory-ledger/item-detail"""

    def test_supply_coverage_present_when_committed_gt_0(self):
        """Verify supply_coverage field present when committed > 0"""
        # Use TEST-ITEM-WARN which has committed = 5000
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/item-detail",
            params={"customer_id": HORMEL_CUSTOMER_ID, "item": "TEST-ITEM-WARN"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "supply_coverage" in data
        assert data["supply_coverage"] is not None
        assert "coverage" in data["supply_coverage"]
        assert "coverage_status" in data["supply_coverage"]

    def test_supply_coverage_null_when_committed_0(self):
        """Verify supply_coverage is null when committed = 0"""
        # Use IMPORT-ITEM-B which has committed = 0
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/item-detail",
            params={"customer_id": HORMEL_CUSTOMER_ID, "item": "IMPORT-ITEM-B"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["supply_coverage"] is None

    def test_supply_coverage_values_correct(self):
        """Verify supply_coverage.coverage and coverage_status are correct"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/item-detail",
            params={"customer_id": HORMEL_CUSTOMER_ID, "item": "TEST-ITEM-WARN"}
        )
        assert response.status_code == 200
        data = response.json()
        
        balance = data["balance"]
        supply_cov = data["supply_coverage"]
        
        # Verify coverage calculation
        expected_coverage = balance["on_hand"] + balance["incoming"] - balance["committed"]
        assert supply_cov["coverage"] == expected_coverage
        
        # Verify coverage_status
        expected_status = "covered" if expected_coverage >= 0 else "at_risk"
        assert supply_cov["coverage_status"] == expected_status


class TestRegressionExistingEndpoints:
    """Regression tests to ensure existing endpoints still work"""

    def test_dashboard_summary_still_works(self):
        """Verify dashboard-summary endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/dashboard-summary",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_items" in data
        assert "items_ok" in data
        assert "items_low" in data
        assert "items_short" in data

    def test_demand_signals_still_works(self):
        """Verify demand-signals endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/demand-signals",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "demand_signals" in data

    def test_exceptions_still_works(self):
        """Verify exceptions endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "exceptions" in data
        assert "exception_summary" in data

    def test_reorder_recommendations_still_works(self):
        """Verify reorder-recommendations endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/reorder-recommendations",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "recommendations" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
