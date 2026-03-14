"""
Test Suite: Inventory Ledger History & Audit Feature (Iteration 60)

Tests:
1. GET /api/inventory-ledger/history - movement history with display_effect
2. GET /api/inventory-ledger/history/summary - per-type totals + current balances
3. Filters: item, movement_type, reference, pagination
4. display_effect sign flip for order_release
5. REGRESSION: reconcile-sales-order, from-shortage, status transitions, release
"""

import pytest
import requests
import uuid
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestInventoryHistoryEndpoint:
    """Tests for GET /api/inventory-ledger/history endpoint."""

    @pytest.fixture(scope="class")
    def test_workspace(self):
        """Create a test workspace with movements for history testing."""
        suffix = uuid.uuid4().hex[:5].upper()
        name = f"TEST_HIST_{suffix}"
        code = f"HIST{suffix}"

        # Create workspace
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers",
            json={"name": name, "code": code, "negative_balance_policy": "warn_only"}
        )
        assert res.status_code == 200
        workspace = res.json()
        customer_id = workspace["id"]

        # Create opening balance movement
        item = f"HIST-ITEM-{suffix}"
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}/movements",
            json={
                "item": item,
                "item_description": "History test item",
                "warehouse": "MAIN",
                "ownership_type": "customer_owned",
                "movement_type": "opening_balance",
                "quantity_delta": 500,
                "unit_of_measure": "cases",
                "source_type": "spreadsheet_import",
                "reference_id": "SEED-001",
                "notes": "Initial seed for history test"
            }
        )
        assert res.status_code == 200

        # Create order_commitment movement
        so_ref = f"SO-HIST-{suffix}"
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}/movements",
            json={
                "item": item,
                "warehouse": "MAIN",
                "ownership_type": "customer_owned",
                "movement_type": "order_commitment",
                "quantity_delta": -100,
                "unit_of_measure": "cases",
                "source_type": "sales_order_commitment",
                "reference_type": "sales_order",
                "reference_id": so_ref,
                "notes": "Commitment for SO"
            }
        )
        assert res.status_code == 200

        # Create order_release movement (to test display_effect sign flip)
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}/movements",
            json={
                "item": item,
                "warehouse": "MAIN",
                "ownership_type": "customer_owned",
                "movement_type": "order_release",
                "quantity_delta": -30,  # Negative delta (releases committed)
                "unit_of_measure": "cases",
                "source_type": "sales_order_release",
                "reference_type": "sales_order",
                "reference_id": so_ref,
                "notes": "Partial release"
            }
        )
        assert res.status_code == 200

        # Create receipt movement
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}/movements",
            json={
                "item": item,
                "warehouse": "MAIN",
                "ownership_type": "customer_owned",
                "movement_type": "receipt",
                "quantity_delta": 200,
                "unit_of_measure": "cases",
                "source_type": "receipt",
                "reference_id": "PO-001",
                "notes": "Received from vendor"
            }
        )
        assert res.status_code == 200

        yield {"customer_id": customer_id, "item": item, "so_ref": so_ref, "code": code}

        # Cleanup: deactivate workspace
        requests.put(f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}", json={"active": False})

    def test_history_returns_movements_reverse_chronological(self, test_workspace):
        """GET /api/inventory-ledger/history returns movements in reverse chronological order."""
        res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/history",
            params={"customer_id": test_workspace["customer_id"], "limit": 10}
        )
        assert res.status_code == 200
        data = res.json()
        assert "movements" in data
        assert "total" in data
        assert data["total"] >= 4  # We created 4 movements

        # Check reverse chronological order
        movements = data["movements"]
        assert len(movements) >= 4
        for i in range(len(movements) - 1):
            assert movements[i]["created_at"] >= movements[i + 1]["created_at"], \
                "Movements should be in reverse chronological order"

        print(f"✓ History returns {data['total']} movements in reverse chronological order")

    def test_history_display_effect_enrichment(self, test_workspace):
        """History endpoint returns display_effect field on each movement."""
        res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/history",
            params={"customer_id": test_workspace["customer_id"]}
        )
        assert res.status_code == 200
        movements = res.json()["movements"]

        for m in movements:
            assert "display_effect" in m, "display_effect should be present"

        print("✓ display_effect field present on all movements")

    def test_history_display_effect_order_release_sign_flip(self, test_workspace):
        """order_release movements have display_effect sign flipped (negative delta → positive effect)."""
        res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/history",
            params={
                "customer_id": test_workspace["customer_id"],
                "movement_type": "order_release"
            }
        )
        assert res.status_code == 200
        movements = res.json()["movements"]
        assert len(movements) >= 1, "Should have at least one order_release"

        for m in movements:
            # order_release has negative quantity_delta but positive display_effect
            assert m["quantity_delta"] < 0, "order_release delta should be negative"
            assert m["display_effect"] > 0, "order_release display_effect should be positive (sign flipped)"
            assert m["display_effect"] == -m["quantity_delta"], "display_effect = -quantity_delta"

        print(f"✓ order_release sign flip verified: delta={movements[0]['quantity_delta']}, display_effect={movements[0]['display_effect']}")

    def test_history_movement_type_filter(self, test_workspace):
        """movement_type filter works correctly."""
        res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/history",
            params={
                "customer_id": test_workspace["customer_id"],
                "movement_type": "opening_balance"
            }
        )
        assert res.status_code == 200
        movements = res.json()["movements"]

        for m in movements:
            assert m["movement_type"] == "opening_balance"

        print(f"✓ movement_type filter returned {len(movements)} opening_balance movements")

    def test_history_reference_filter(self, test_workspace):
        """reference filter works correctly."""
        so_ref = test_workspace["so_ref"]
        res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/history",
            params={
                "customer_id": test_workspace["customer_id"],
                "reference": so_ref
            }
        )
        assert res.status_code == 200
        data = res.json()

        # Should have commitment and release for this SO
        assert data["total"] >= 2
        for m in data["movements"]:
            assert m["reference_id"] == so_ref

        print(f"✓ reference filter returned {data['total']} movements for {so_ref}")

    def test_history_item_filter(self, test_workspace):
        """item filter works correctly."""
        res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/history",
            params={
                "customer_id": test_workspace["customer_id"],
                "item": test_workspace["item"]
            }
        )
        assert res.status_code == 200
        data = res.json()

        assert data["total"] >= 4
        for m in data["movements"]:
            assert m["item"] == test_workspace["item"]

        print(f"✓ item filter returned {data['total']} movements for item")

    def test_history_pagination(self, test_workspace):
        """pagination (limit/offset) works correctly."""
        # Get first page
        res1 = requests.get(
            f"{BASE_URL}/api/inventory-ledger/history",
            params={"customer_id": test_workspace["customer_id"], "limit": 2, "offset": 0}
        )
        assert res1.status_code == 200
        page1 = res1.json()

        # Get second page
        res2 = requests.get(
            f"{BASE_URL}/api/inventory-ledger/history",
            params={"customer_id": test_workspace["customer_id"], "limit": 2, "offset": 2}
        )
        assert res2.status_code == 200
        page2 = res2.json()

        # Total should be same across pages
        assert page1["total"] == page2["total"]

        # Pages should have different items
        page1_ids = [m["id"] for m in page1["movements"]]
        page2_ids = [m["id"] for m in page2["movements"]]
        assert set(page1_ids).isdisjoint(set(page2_ids)), "Pages should have different movements"

        print(f"✓ Pagination working: page1={len(page1['movements'])}, page2={len(page2['movements'])}, total={page1['total']}")

    def test_history_empty_result_non_existent_item(self, test_workspace):
        """Returns empty result (not error) for non-existent item."""
        res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/history",
            params={
                "customer_id": test_workspace["customer_id"],
                "item": f"NONEXISTENT_{uuid.uuid4().hex[:8]}"
            }
        )
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 0
        assert data["movements"] == []

        print("✓ Non-existent item returns empty result (no server error)")


class TestHistorySummaryEndpoint:
    """Tests for GET /api/inventory-ledger/history/summary endpoint."""

    @pytest.fixture(scope="class")
    def summary_workspace(self):
        """Create workspace with diverse movements for summary testing."""
        suffix = uuid.uuid4().hex[:5].upper()
        code = f"SUM{suffix}"

        # Create workspace
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers",
            json={"name": f"TEST_SUMMARY_{suffix}", "code": code, "negative_balance_policy": "warn_only"}
        )
        assert res.status_code == 200
        customer_id = res.json()["id"]
        item = f"SUM-ITEM-{suffix}"

        # Opening balance: +500
        requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}/movements",
            json={"item": item, "warehouse": "MAIN", "ownership_type": "customer_owned",
                  "movement_type": "opening_balance", "quantity_delta": 500, "unit_of_measure": "units"}
        )

        # Receipt: +100
        requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}/movements",
            json={"item": item, "warehouse": "MAIN", "ownership_type": "customer_owned",
                  "movement_type": "receipt", "quantity_delta": 100, "unit_of_measure": "units"}
        )

        # Order commitment: -200
        requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}/movements",
            json={"item": item, "warehouse": "MAIN", "ownership_type": "customer_owned",
                  "movement_type": "order_commitment", "quantity_delta": -200, "unit_of_measure": "units",
                  "reference_id": "SO-SUM-001"}
        )

        # Order release: -50 (partial release)
        requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}/movements",
            json={"item": item, "warehouse": "MAIN", "ownership_type": "customer_owned",
                  "movement_type": "order_release", "quantity_delta": -50, "unit_of_measure": "units",
                  "reference_id": "SO-SUM-001"}
        )

        # Create incoming supply (ordered status)
        inc_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}/incoming",
            json={"item": item, "warehouse": "MAIN", "ownership_type": "customer_owned",
                  "incoming_qty": 300, "unit_of_measure": "units", "notes": "Expected supply"}
        )
        supply_id = inc_res.json()["id"]
        # Transition to ordered (counts as incoming)
        requests.post(f"{BASE_URL}/api/incoming-supply/{supply_id}/status", json={"status": "ordered"})

        yield {"customer_id": customer_id, "item": item, "code": code}

        # Cleanup
        requests.put(f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}", json={"active": False})

    def test_summary_returns_per_type_totals(self, summary_workspace):
        """Summary returns movement_type_totals with count and total_qty per type."""
        res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/history/summary",
            params={"customer_id": summary_workspace["customer_id"], "item": summary_workspace["item"]}
        )
        assert res.status_code == 200
        data = res.json()

        assert "movement_type_totals" in data
        totals = data["movement_type_totals"]

        # Check expected types exist
        assert "opening_balance" in totals
        assert totals["opening_balance"]["total_qty"] == 500
        assert totals["opening_balance"]["count"] == 1

        assert "receipt" in totals
        assert totals["receipt"]["total_qty"] == 100
        assert totals["receipt"]["count"] == 1

        assert "order_commitment" in totals
        assert totals["order_commitment"]["total_qty"] == -200
        assert totals["order_commitment"]["count"] == 1

        assert "order_release" in totals
        assert totals["order_release"]["total_qty"] == -50
        assert totals["order_release"]["count"] == 1

        print(f"✓ movement_type_totals correct: {list(totals.keys())}")

    def test_summary_current_balances_correct(self, summary_workspace):
        """Summary returns correct current_balances (on_hand, incoming, committed, available)."""
        res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/history/summary",
            params={"customer_id": summary_workspace["customer_id"], "item": summary_workspace["item"]}
        )
        assert res.status_code == 200
        data = res.json()

        assert "current_balances" in data
        bal = data["current_balances"]

        # on_hand = opening_balance + receipt = 500 + 100 = 600
        assert bal["on_hand"] == 600, f"Expected on_hand=600, got {bal['on_hand']}"

        # incoming = 300 (from ordered incoming supply)
        assert bal["incoming"] == 300, f"Expected incoming=300, got {bal['incoming']}"

        # committed = abs(commitment) + release = 200 + (-50) = 150
        assert bal["committed"] == 150, f"Expected committed=150, got {bal['committed']}"

        # available = on_hand + incoming - committed = 600 + 300 - 150 = 750
        assert bal["available"] == 750, f"Expected available=750, got {bal['available']}"

        print(f"✓ current_balances correct: on_hand={bal['on_hand']}, incoming={bal['incoming']}, committed={bal['committed']}, available={bal['available']}")

    def test_summary_includes_balance_details(self, summary_workspace):
        """Summary includes balance_details with per-bucket breakdown."""
        res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/history/summary",
            params={"customer_id": summary_workspace["customer_id"], "item": summary_workspace["item"]}
        )
        assert res.status_code == 200
        data = res.json()

        assert "balance_details" in data
        details = data["balance_details"]
        assert len(details) >= 1

        bucket = details[0]
        assert "item" in bucket
        assert "warehouse" in bucket
        assert "on_hand" in bucket
        assert "incoming" in bucket
        assert "committed" in bucket
        assert "available" in bucket

        print(f"✓ balance_details contains {len(details)} bucket(s)")


class TestRegressionEndpoints:
    """Regression tests for existing endpoints."""

    @pytest.fixture(scope="class")
    def regression_workspace(self):
        """Create workspace for regression testing."""
        suffix = uuid.uuid4().hex[:5].upper()
        code = f"REG{suffix}"

        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers",
            json={"name": f"TEST_REGRESSION_{suffix}", "code": code, "negative_balance_policy": "warn_only"}
        )
        assert res.status_code == 200
        customer_id = res.json()["id"]
        item = f"REG-ITEM-{suffix}"

        # Seed opening balance
        requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}/movements",
            json={"item": item, "warehouse": "MAIN", "ownership_type": "customer_owned",
                  "movement_type": "opening_balance", "quantity_delta": 100, "unit_of_measure": "units"}
        )

        yield {"customer_id": customer_id, "item": item, "code": code}

        requests.put(f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}", json={"active": False})

    def test_regression_reconcile_sales_order(self, regression_workspace):
        """REGRESSION: POST /api/inventory-ledger/reconcile-sales-order still works."""
        # First create a commitment
        so_ref = f"SO-REG-{uuid.uuid4().hex[:6]}"
        requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers/{regression_workspace['customer_id']}/movements",
            json={
                "item": regression_workspace["item"],
                "warehouse": "MAIN",
                "ownership_type": "customer_owned",
                "movement_type": "order_commitment",
                "quantity_delta": -50,
                "unit_of_measure": "units",
                "reference_id": so_ref
            }
        )

        # Reconcile (decrease to 30)
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order",
            json={"sales_order_id": so_ref, "lines": [{"item": regression_workspace["item"], "qty": 30}]}
        )
        assert res.status_code == 200
        data = res.json()
        assert "adjustments" in data
        print(f"✓ REGRESSION: reconcile-sales-order works, adjustments={data['adjustments']}")

    def test_regression_from_shortage(self, regression_workspace):
        """REGRESSION: POST /api/incoming-supply/from-shortage still works."""
        so_ref = f"SO-SHORT-{uuid.uuid4().hex[:6]}"

        # First, create a commitment for this SO (required by from-shortage)
        requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers/{regression_workspace['customer_id']}/movements",
            json={
                "item": regression_workspace["item"],
                "warehouse": "MAIN",
                "ownership_type": "customer_owned",
                "movement_type": "order_commitment",
                "quantity_delta": -200,
                "unit_of_measure": "units",
                "reference_id": so_ref
            }
        )

        res = requests.post(
            f"{BASE_URL}/api/incoming-supply/from-shortage",
            json={
                "sales_order_id": so_ref,
                "lines": [{"item": regression_workspace["item"], "qty_needed": 200, "qty_available": 50}]
            }
        )
        # Should succeed (200) or return 409 if duplicate
        assert res.status_code in [200, 409]
        if res.status_code == 200:
            data = res.json()
            assert "created" in data
            print(f"✓ REGRESSION: from-shortage works, created={data['created']}")
        else:
            print("✓ REGRESSION: from-shortage correctly returns 409 for duplicate")

    def test_regression_status_transition(self, regression_workspace):
        """REGRESSION: POST /api/incoming-supply/{id}/status still works."""
        # Create incoming supply
        inc_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers/{regression_workspace['customer_id']}/incoming",
            json={
                "item": regression_workspace["item"],
                "warehouse": "MAIN",
                "ownership_type": "customer_owned",
                "incoming_qty": 100,
                "unit_of_measure": "units"
            }
        )
        assert inc_res.status_code == 200
        supply_id = inc_res.json()["id"]

        # Transition to ordered
        res = requests.post(
            f"{BASE_URL}/api/incoming-supply/{supply_id}/status",
            json={"status": "ordered"}
        )
        assert res.status_code == 200
        data = res.json()
        # Response has nested structure: {supply: {...}, receipt_movement_id: ...}
        supply_status = data.get("supply", {}).get("status") or data.get("status")
        assert supply_status == "ordered", f"Expected status=ordered, got {supply_status}"
        print("✓ REGRESSION: status transition (expected→ordered) works")

    def test_regression_release(self, regression_workspace):
        """REGRESSION: POST /api/inventory-ledger/release still works."""
        so_ref = f"SO-REL-{uuid.uuid4().hex[:6]}"

        # Create commitment first
        requests.post(
            f"{BASE_URL}/api/inventory-ledger/customers/{regression_workspace['customer_id']}/movements",
            json={
                "item": regression_workspace["item"],
                "warehouse": "MAIN",
                "ownership_type": "customer_owned",
                "movement_type": "order_commitment",
                "quantity_delta": -40,
                "unit_of_measure": "units",
                "reference_id": so_ref
            }
        )

        # Release
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/release",
            json={"sales_order_id": so_ref, "lines": [{"item": regression_workspace["item"], "qty": 20}]}
        )
        assert res.status_code == 200
        data = res.json()
        assert "released" in data or "movements_created" in data
        print("✓ REGRESSION: release endpoint works")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
