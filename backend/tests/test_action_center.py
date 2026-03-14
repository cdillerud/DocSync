"""
Action Center Endpoint Tests
Tests for GET /api/inventory-ledger/action-center endpoint.
Verifies: action_types, priority_score, sorting, filtering, action_summary counts.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
HORMEL_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"

# Priority weights from the implementation
PRIORITY_WEIGHTS = {
    "shortage": 50,
    "coverage_risk": 30,
    "demand_gap": 20,
    "reorder": 10,
    "no_incoming": 5,
}


class TestActionCenterEndpoint:
    """Tests for GET /api/inventory-ledger/action-center"""

    def test_action_center_returns_total_summary_and_actions(self):
        """Verify endpoint returns total, action_summary, and actions array"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/action-center",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "total" in data
        assert "action_summary" in data
        assert "actions" in data
        assert isinstance(data["total"], int)
        assert isinstance(data["action_summary"], dict)
        assert isinstance(data["actions"], list)

    def test_action_summary_structure(self):
        """Verify action_summary contains expected counts"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/action-center",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        summary = response.json()["action_summary"]
        
        assert "shortage_count" in summary
        assert "coverage_risk_count" in summary
        assert "demand_gap_count" in summary
        assert "reorder_count" in summary
        assert "no_incoming_count" in summary
        assert "total_action_items" in summary

    def test_shortage_action_type_present_for_short_items(self):
        """SHORT items should have 'shortage' in action_types"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/action-center",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        actions = response.json()["actions"]
        
        short_items = [a for a in actions if a.get("status") == "SHORT"]
        assert len(short_items) > 0, "Expected at least one SHORT item"
        
        for item in short_items:
            assert "shortage" in item["action_types"], f"SHORT item {item['item']} missing 'shortage' action type"

    def test_coverage_risk_action_type_present_for_at_risk_items(self):
        """Items with coverage < 0 should have 'coverage_risk' in action_types"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/action-center",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        actions = response.json()["actions"]
        
        at_risk_items = [a for a in actions if a.get("coverage_status") == "at_risk"]
        assert len(at_risk_items) > 0, "Expected at least one at_risk coverage item"
        
        for item in at_risk_items:
            assert "coverage_risk" in item["action_types"], f"At-risk item {item['item']} missing 'coverage_risk' action type"

    def test_demand_gap_action_type_present_for_demand_gap_items(self):
        """Items with demand_gap > 0 should have 'demand_gap' in action_types"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/action-center",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        actions = response.json()["actions"]
        
        demand_gap_items = [a for a in actions if a.get("demand_gap", 0) > 0]
        assert len(demand_gap_items) > 0, "Expected at least one item with demand_gap > 0"
        
        for item in demand_gap_items:
            assert "demand_gap" in item["action_types"], f"Item {item['item']} with demand_gap={item.get('demand_gap')} missing 'demand_gap' action type"

    def test_reorder_action_type_with_recommended_qty(self):
        """Items with 'reorder' action_type should have recommended_qty"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/action-center",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        actions = response.json()["actions"]
        
        reorder_items = [a for a in actions if "reorder" in a.get("action_types", [])]
        assert len(reorder_items) > 0, "Expected at least one item with 'reorder' action type"
        
        for item in reorder_items:
            assert "recommended_qty" in item, f"Reorder item {item['item']} missing 'recommended_qty'"
            assert item["recommended_qty"] > 0, f"Reorder item {item['item']} has recommended_qty <= 0"

    def test_no_incoming_action_type_for_items_without_incoming(self):
        """Items with (is_short or is_low) and incoming=0 should have 'no_incoming'"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/action-center",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        actions = response.json()["actions"]
        
        no_incoming_items = [a for a in actions if "no_incoming" in a.get("action_types", [])]
        assert len(no_incoming_items) > 0, "Expected at least one item with 'no_incoming' action type"
        
        for item in no_incoming_items:
            assert item["incoming"] == 0, f"Item {item['item']} has 'no_incoming' but incoming={item['incoming']}"
            # Should be SHORT or LOW status
            assert item["status"] in ["SHORT", "LOW"], f"Item {item['item']} has 'no_incoming' but status={item['status']}"

    def test_merged_rows_have_multiple_action_types(self):
        """Items can have multiple action_types (merged classification)"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/action-center",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        actions = response.json()["actions"]
        
        multi_type_items = [a for a in actions if len(a.get("action_types", [])) > 1]
        assert len(multi_type_items) > 0, "Expected at least one item with multiple action_types"
        
        # Items with all 5 action types should have highest priority score (115)
        all_five_items = [a for a in actions if len(a.get("action_types", [])) == 5]
        if all_five_items:
            for item in all_five_items:
                assert item["priority_score"] == 115, f"Item with all 5 action types has priority_score={item['priority_score']}, expected 115"

    def test_priority_score_calculation(self):
        """Priority score should equal sum of weights for action_types"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/action-center",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        actions = response.json()["actions"]
        
        for item in actions:
            action_types = item.get("action_types", [])
            expected_score = sum(PRIORITY_WEIGHTS.get(t, 0) for t in action_types)
            actual_score = item.get("priority_score", 0)
            assert actual_score == expected_score, f"Item {item['item']}: expected priority_score={expected_score}, got {actual_score}. Action types: {action_types}"

    def test_sorting_by_priority_score_desc_then_available_asc(self):
        """Results sorted by priority_score desc, then available asc for ties"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/action-center",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        actions = response.json()["actions"]
        
        # Verify sorting
        for i in range(1, len(actions)):
            prev = actions[i-1]
            curr = actions[i]
            
            # Primary sort: priority_score descending
            if prev["priority_score"] != curr["priority_score"]:
                assert prev["priority_score"] >= curr["priority_score"], \
                    f"Sort error: {prev['item']} (score={prev['priority_score']}) before {curr['item']} (score={curr['priority_score']})"
            else:
                # Secondary sort: available ascending (for ties)
                assert prev["available"] <= curr["available"], \
                    f"Tie-break error: {prev['item']} (avail={prev['available']}) before {curr['item']} (avail={curr['available']}) at same priority_score={prev['priority_score']}"

    def test_action_summary_counts_match_returned_rows(self):
        """action_summary counts should match the action_types in returned rows"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/action-center",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        data = response.json()
        summary = data["action_summary"]
        actions = data["actions"]
        
        # Count action types from all rows
        actual_counts = {
            "shortage": 0,
            "coverage_risk": 0,
            "demand_gap": 0,
            "reorder": 0,
            "no_incoming": 0,
        }
        for item in actions:
            for action_type in item.get("action_types", []):
                if action_type in actual_counts:
                    actual_counts[action_type] += 1
        
        assert summary["shortage_count"] == actual_counts["shortage"], f"shortage_count mismatch"
        assert summary["coverage_risk_count"] == actual_counts["coverage_risk"], f"coverage_risk_count mismatch"
        assert summary["demand_gap_count"] == actual_counts["demand_gap"], f"demand_gap_count mismatch"
        assert summary["reorder_count"] == actual_counts["reorder"], f"reorder_count mismatch"
        assert summary["no_incoming_count"] == actual_counts["no_incoming"], f"no_incoming_count mismatch"
        assert summary["total_action_items"] == len(actions), f"total_action_items mismatch"

    def test_filter_by_action_type_shortage(self):
        """Filter by action_type=shortage should return only items with shortage"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/action-center",
            params={"customer_id": HORMEL_ID, "action_type": "shortage"}
        )
        assert response.status_code == 200
        actions = response.json()["actions"]
        
        for item in actions:
            assert "shortage" in item["action_types"], f"Filtered item {item['item']} missing 'shortage' action type"

    def test_empty_customer_returns_zeros(self):
        """Non-existent customer returns empty results with all zeros"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/action-center",
            params={"customer_id": "NONEXISTENT"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["total"] == 0
        assert data["action_summary"]["shortage_count"] == 0
        assert data["action_summary"]["coverage_risk_count"] == 0
        assert data["action_summary"]["demand_gap_count"] == 0
        assert data["action_summary"]["reorder_count"] == 0
        assert data["action_summary"]["no_incoming_count"] == 0
        assert data["action_summary"]["total_action_items"] == 0
        assert data["actions"] == []

    def test_missing_customer_id_returns_422(self):
        """Missing customer_id parameter should return 422"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/action-center")
        assert response.status_code == 422


class TestItemDetailActionSummary:
    """Tests for action_summary in item-detail endpoint"""

    def test_item_detail_action_summary_present_for_items_with_actions(self):
        """Items with actions should have action_summary in item-detail"""
        # Use SPAM-LITE which has actions
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/item-detail",
            params={"customer_id": HORMEL_ID, "item": "SPAM-LITE"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "action_summary" in data
        assert data["action_summary"] is not None
        assert "action_types" in data["action_summary"]
        assert "priority_score" in data["action_summary"]
        assert len(data["action_summary"]["action_types"]) > 0
        assert data["action_summary"]["priority_score"] > 0

    def test_item_detail_action_summary_null_for_ok_items(self):
        """Items without actions should have action_summary=null"""
        # Use SPAM-12OZ which is OK status
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/item-detail",
            params={"customer_id": HORMEL_ID, "item": "SPAM-12OZ"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # OK items without issues should have null action_summary
        assert data["action_summary"] is None


class TestRegressionOtherTabs:
    """Regression tests to ensure other tabs still work"""

    def test_dashboard_summary_still_works(self):
        """Dashboard summary endpoint should still work"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/dashboard-summary",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_items" in data
        assert "items_ok" in data
        assert "items_low" in data
        assert "items_short" in data

    def test_supply_coverage_still_works(self):
        """Supply coverage endpoint should still work"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/supply-coverage",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "coverage" in data

    def test_demand_signals_still_works(self):
        """Demand signals endpoint should still work"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/demand-signals",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "demand_signals" in data

    def test_exceptions_still_works(self):
        """Exceptions endpoint should still work"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/exceptions",
            params={"customer_id": HORMEL_ID}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "exception_summary" in data
        assert "exceptions" in data
