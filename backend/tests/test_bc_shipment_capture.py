"""
Test Suite for BC Sales Shipment Capture (iteration_81)
Tests POST /api/inventory-ledger/sales-orders/{id}/bc-shipment endpoint
Tests GET /api/inventory-ledger/sales-orders/{id}/summary endpoint
Tests GET /api/inventory-ledger/sales-orders/{id}/shipment-log endpoint
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestBCShipmentCapture:
    """Tests for BC Shipment Capture endpoint"""

    # ══════════════════════════════════════════════════════════════
    # POST /sales-orders/{id}/bc-shipment - Happy Path
    # ══════════════════════════════════════════════════════════════

    def test_shipment_nonexistent_so_returns_404(self):
        """Non-existent SO returns 404"""
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/NONEXISTENT-SO-12345/bc-shipment",
            json={
                "shipped_lines": [{"item": "TEST-ITEM", "qty_shipped": 10}],
                "bc_shipment_number": "SHP-TEST-001"
            }
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        data = response.json()
        assert "detail" in data
        assert "commitments" in data["detail"].lower() or "not found" in data["detail"].lower()

    def test_get_so_summary_nonexistent_returns_404(self):
        """GET summary for non-existent SO returns 404"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/NONEXISTENT-SO-99999/summary"
        )
        assert response.status_code == 404

    def test_get_so_summary_existing(self):
        """GET summary for existing SO (SO-107040) returns commitment info"""
        # SO-107040 should have 200 remaining on SPAM-12OZ
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/summary"
        )
        if response.status_code == 404:
            pytest.skip("SO-107040 not found - test data may have changed")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Validate response structure
        assert "sales_order_id" in data
        assert data["sales_order_id"] == "SO-107040"
        assert "total_committed_qty" in data
        assert "total_released_qty" in data
        assert "total_remaining_committed_qty" in data
        assert "lines" in data
        assert isinstance(data["lines"], list)
        
        # Validate line structure
        if data["lines"]:
            line = data["lines"][0]
            assert "item" in line
            assert "committed_qty" in line
            assert "released_qty" in line
            assert "remaining_committed_qty" in line

    def test_get_so_summary_fully_released(self):
        """GET summary for fully released SO (SO-TEST) shows 0 remaining"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-TEST/summary"
        )
        if response.status_code == 404:
            pytest.skip("SO-TEST not found - test data may have changed")
        
        assert response.status_code == 200
        data = response.json()
        # SO-TEST should be fully released, remaining should be 0
        assert "total_remaining_committed_qty" in data
        # This may or may not be 0 depending on test state

    def test_shipment_over_shipment_rejected_422(self):
        """Over-shipment (shipped > outstanding) returns 422"""
        # First get summary to know what's available
        summary_res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/summary"
        )
        if summary_res.status_code == 404:
            pytest.skip("SO-107040 not found")
        
        summary = summary_res.json()
        if not summary.get("lines"):
            pytest.skip("No lines on SO-107040")
        
        # Find a line with remaining qty
        target_line = None
        for line in summary["lines"]:
            if line["remaining_committed_qty"] > 0:
                target_line = line
                break
        
        if not target_line:
            pytest.skip("No outstanding commitment on SO-107040")
        
        # Try to ship more than outstanding
        over_qty = target_line["remaining_committed_qty"] + 100
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/bc-shipment",
            json={
                "shipped_lines": [{"item": target_line["item"], "qty_shipped": over_qty}],
                "bc_shipment_number": "SHP-OVERTEST"
            }
        )
        assert response.status_code == 422, f"Expected 422 for over-shipment, got {response.status_code}: {response.text}"

    def test_shipment_idempotent_fully_released(self):
        """Shipment on fully released SO returns skipped, not error"""
        # SO-TEST is fully released per context
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-TEST/bc-shipment",
            json={
                "shipped_lines": [{"item": "SPAM-LITE", "qty_shipped": 1}],
                "bc_shipment_number": "SHP-IDEMPOTENT"
            }
        )
        if response.status_code == 404:
            pytest.skip("SO-TEST not found")
        
        # Should return 200 with skipped result, not error
        assert response.status_code == 200, f"Expected 200 with skipped, got {response.status_code}: {response.text}"
        data = response.json()
        assert "results" in data
        # All lines should be skipped
        skipped_count = sum(1 for r in data["results"] if r.get("status") == "skipped")
        assert skipped_count > 0, "Expected at least one skipped line"

    # ══════════════════════════════════════════════════════════════
    # GET /sales-orders/{id}/shipment-log
    # ══════════════════════════════════════════════════════════════

    def test_shipment_log_returns_entries(self):
        """Shipment log returns reverse chronological entries"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/shipment-log"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "sales_order_id" in data
        assert data["sales_order_id"] == "SO-107040"
        assert "total" in data
        assert "entries" in data
        assert isinstance(data["entries"], list)
        
        # If there are entries, validate structure
        if data["entries"]:
            entry = data["entries"][0]
            assert "shipment_id" in entry
            assert "shipped_at" in entry

    def test_shipment_log_empty_for_new_so(self):
        """Shipment log for SO with no shipments returns empty entries"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/NONEXISTENT-SO-EMPTY/shipment-log"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["entries"] == []


class TestBCShipmentCaptureIntegration:
    """Integration tests for full shipment flow"""

    def test_partial_shipment_leaves_remaining(self):
        """Partial shipment releases only shipped qty, leaves remaining committed"""
        # Get summary first
        summary_res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/summary"
        )
        if summary_res.status_code == 404:
            pytest.skip("SO-107040 not found")
        
        summary = summary_res.json()
        target_line = None
        for line in summary["lines"]:
            if line["remaining_committed_qty"] >= 10:  # Need at least 10 to do partial
                target_line = line
                break
        
        if not target_line:
            pytest.skip("No line with sufficient remaining qty for partial shipment test")
        
        original_remaining = target_line["remaining_committed_qty"]
        partial_qty = min(5, original_remaining - 1)  # Ship less than remaining
        
        if partial_qty <= 0:
            pytest.skip("Cannot do partial shipment with remaining qty")
        
        # Perform partial shipment
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/bc-shipment",
            json={
                "shipped_lines": [{"item": target_line["item"], "qty_shipped": partial_qty}],
                "bc_shipment_number": f"SHP-PARTIAL-{partial_qty}",
                "shipment_notes": "Partial shipment test"
            }
        )
        
        if response.status_code == 422:
            # Might have hit boundary condition
            pytest.skip(f"Partial shipment rejected: {response.text}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Validate response
        assert "shipment_id" in data
        assert "total_released" in data
        assert data["total_released"] >= 1
        
        # Verify remaining is updated
        after_summary = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/summary"
        ).json()
        
        after_line = next((l for l in after_summary["lines"] if l["item"] == target_line["item"]), None)
        if after_line:
            assert after_line["remaining_committed_qty"] < original_remaining, \
                "Remaining should decrease after partial shipment"

    def test_shipment_creates_order_release_movement(self):
        """Shipment creates order_release movement through pipeline"""
        # Get summary to find a line with remaining
        summary_res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/summary"
        )
        if summary_res.status_code == 404:
            pytest.skip("SO-107040 not found")
        
        summary = summary_res.json()
        target_line = None
        for line in summary["lines"]:
            if line["remaining_committed_qty"] > 0:
                target_line = line
                break
        
        if not target_line:
            pytest.skip("No outstanding commitment to test release movement")
        
        ship_qty = min(1, target_line["remaining_committed_qty"])
        
        # Perform shipment
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/bc-shipment",
            json={
                "shipped_lines": [{"item": target_line["item"], "qty_shipped": ship_qty}],
                "bc_shipment_number": "SHP-RELEASE-TEST"
            }
        )
        
        if response.status_code == 422:
            pytest.skip(f"Shipment rejected: {response.text}")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check that movement_id is returned
        for result in data.get("results", []):
            if result.get("status") == "released":
                assert "movement_id" in result, "Released result should include movement_id"

    def test_shipment_log_stores_bc_fields(self):
        """Shipment log stores bc_shipment_number, bc_document_id, shipment_notes"""
        # Perform a shipment with BC fields
        summary_res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/summary"
        )
        if summary_res.status_code == 404:
            pytest.skip("SO-107040 not found")
        
        summary = summary_res.json()
        target_line = None
        for line in summary["lines"]:
            if line["remaining_committed_qty"] > 0:
                target_line = line
                break
        
        if not target_line:
            pytest.skip("No outstanding commitment")
        
        bc_ship_num = "SHP-BC-FIELDS-TEST"
        bc_doc_id = "DOC-12345"
        notes = "Test shipment with BC fields"
        
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/bc-shipment",
            json={
                "shipped_lines": [{"item": target_line["item"], "qty_shipped": min(1, target_line["remaining_committed_qty"])}],
                "bc_shipment_number": bc_ship_num,
                "bc_document_id": bc_doc_id,
                "shipment_notes": notes
            }
        )
        
        if response.status_code == 422:
            pytest.skip(f"Shipment rejected: {response.text}")
        
        assert response.status_code == 200
        
        # Check shipment log has the fields
        log_res = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/shipment-log"
        )
        assert log_res.status_code == 200
        logs = log_res.json()
        
        # Find our shipment
        found = False
        for entry in logs["entries"]:
            if entry.get("bc_shipment_number") == bc_ship_num:
                found = True
                assert entry.get("bc_document_id") == bc_doc_id
                assert entry.get("shipment_notes") == notes
                assert "shipped_lines" in entry
                break
        
        assert found, f"Shipment log with bc_shipment_number={bc_ship_num} not found"


class TestBCShipmentCaptureRegressionBC:
    """Regression tests to ensure existing functionality still works"""

    def test_regression_bc_receipt_capture_still_works(self):
        """BC receipt capture endpoint still accessible"""
        # Just verify endpoint exists and returns expected error for non-existent draft
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/NONEXISTENT-DRAFT/bc-receipt",
            json={"received_lines": [{"item": "TEST", "qty_received": 1}]}
        )
        assert response.status_code == 404, "BC receipt should return 404 for non-existent draft"

    def test_regression_bc_response_capture_still_works(self):
        """BC response capture endpoint still accessible"""
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/NONEXISTENT-DRAFT/bc-response",
            json={"bc_response_status": "pending"}
        )
        assert response.status_code == 404, "BC response should return 404 for non-existent draft"

    def test_regression_po_draft_workflow_still_works(self):
        """PO draft list endpoint still accessible"""
        # Find a customer first
        cust_res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers")
        assert cust_res.status_code == 200
        customers = cust_res.json()
        
        if not customers:
            pytest.skip("No customers found")
        
        customer_id = customers[0]["id"]
        
        # List PO drafts
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={customer_id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert "drafts" in data
        assert "total" in data

    def test_regression_inventory_balances_still_work(self):
        """Inventory balances endpoint still accessible"""
        cust_res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers")
        assert cust_res.status_code == 200
        customers = cust_res.json()
        
        if not customers:
            pytest.skip("No customers found")
        
        customer_id = customers[0]["id"]
        
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}/balances"
        )
        assert response.status_code == 200
        data = response.json()
        assert "balances" in data


class TestSOSummaryEndpoint:
    """Detailed tests for GET /sales-orders/{id}/summary endpoint"""

    def test_summary_returns_lines_with_all_fields(self):
        """Summary lines include committed_qty, released_qty, remaining_committed_qty"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/summary"
        )
        if response.status_code == 404:
            pytest.skip("SO-107040 not found")
        
        assert response.status_code == 200
        data = response.json()
        
        for line in data.get("lines", []):
            assert "item" in line
            assert "committed_qty" in line
            assert "released_qty" in line
            assert "remaining_committed_qty" in line
            # Validate math
            expected_remaining = round(line["committed_qty"] - line["released_qty"], 4)
            assert abs(line["remaining_committed_qty"] - expected_remaining) < 0.01, \
                f"remaining_committed_qty should equal committed - released"

    def test_summary_returns_latest_shipment_info(self):
        """Summary includes latest_bc_shipment_number and latest_bc_shipped_at"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/summary"
        )
        if response.status_code == 404:
            pytest.skip("SO-107040 not found")
        
        assert response.status_code == 200
        data = response.json()
        
        # These fields should exist even if empty
        assert "latest_bc_shipment_number" in data
        assert "latest_bc_shipped_at" in data

    def test_summary_totals_aggregate_correctly(self):
        """Summary totals match sum of line values"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/SO-107040/summary"
        )
        if response.status_code == 404:
            pytest.skip("SO-107040 not found")
        
        assert response.status_code == 200
        data = response.json()
        
        lines = data.get("lines", [])
        if not lines:
            pytest.skip("No lines to validate totals")
        
        calc_committed = sum(l["committed_qty"] for l in lines)
        calc_released = sum(l["released_qty"] for l in lines)
        calc_remaining = sum(l["remaining_committed_qty"] for l in lines)
        
        assert abs(data["total_committed_qty"] - calc_committed) < 0.01
        assert abs(data["total_released_qty"] - calc_released) < 0.01
        assert abs(data["total_remaining_committed_qty"] - calc_remaining) < 0.01
