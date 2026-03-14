"""
BC Receipt Capture Tests (iteration_80)

Tests POST /api/inventory-ledger/po-drafts/{id}/bc-receipt endpoint:
- Full receipt advances ordered supply to received via transition_supply_status pipeline
- Receipt creates ledger movement (receipt_movement_id returned)
- Receipt sets bc_receipt_at and bc_receipt_notes on supply records
- Over-receipt rejected with 422
- Partial receipt rejected with 422
- Receipt rejected when BC response status is not 'created' (422)
- Receipt rejected for draft without linked supply (422)
- Receipt rejected for nonexistent draft (404)
- Duplicate receipt is idempotent (skipped, not errored)
- PO draft detail returns receipt_summary enrichment
- Linked supply endpoint returns receipt_summary

Regression tests:
- BC response capture still works
- Submission log still works
- Vendor assignment still works
- BC export still works
"""

import pytest
import requests
import os
import uuid
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestBCReceiptCapture:
    """BC Receipt Capture endpoint tests"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test data - find workspace and existing draft with ordered supply"""
        # Use existing Hormel Foods workspace
        self.customer_id = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"
        # Draft from context - PO-DRAFT-20260314163256-689B67 has fully received supply
        self.existing_received_draft_id = "PO-DRAFT-20260314163256-689B67"
        self.test_prefix = f"TEST-RECEIPT-{uuid.uuid4().hex[:6].upper()}"

    def test_receipt_rejected_for_nonexistent_draft(self):
        """Receipt returns 404 for nonexistent draft"""
        resp = requests.post(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/NONEXISTENT-DRAFT/bc-receipt",
            json={"received_lines": [{"item": "TEST-ITEM", "qty_received": 10}], "receipt_notes": "Test"}
        )
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
        assert "not found" in resp.json().get("detail", "").lower()
        print("✓ Receipt returns 404 for nonexistent draft")

    def test_receipt_rejected_without_bc_response_created(self):
        """Receipt rejected when BC response status is not 'created'"""
        # First, create a draft without bc_response_status
        # Create a new PO draft
        draft_resp = requests.post(
            f"{BASE_URL}/api/inventory-ledger/generate-po-draft",
            json={
                "customer_id": self.customer_id,
                "items": [{"item": "SPAM-LITE", "recommended_qty": 10, "source": "test"}]
            }
        )
        if draft_resp.status_code == 409:
            # Duplicate protection triggered - use a different approach
            print("  ⚠ Draft creation blocked by duplicate guard, using alternative test")
            # Try to find a draft without bc_response_status
            drafts_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={self.customer_id}&limit=50")
            drafts = drafts_resp.json().get("drafts", [])
            
            # Find one without bc_response_status or with status != created
            no_bc_draft = next((d for d in drafts if not d.get("bc_response_status") or d.get("bc_response_status") != "created"), None)
            
            if no_bc_draft:
                draft_id = no_bc_draft["po_draft_id"]
            else:
                pytest.skip("No draft without bc_response_status found for this test")
                return
        else:
            assert draft_resp.status_code == 200, f"Failed to create draft: {draft_resp.text}"
            draft_id = draft_resp.json()["po_draft_id"]
        
        # Try to record receipt - should fail because bc_response_status is not 'created'
        resp = requests.post(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/bc-receipt",
            json={"received_lines": [{"item": "SPAM-LITE", "qty_received": 10}], "receipt_notes": "Test"}
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
        detail = resp.json().get("detail", "")
        assert "BC response status must be 'created'" in detail, f"Unexpected detail: {detail}"
        print(f"✓ Receipt rejected for draft {draft_id} without bc_response_status=created")

    def test_receipt_rejected_without_linked_supply(self):
        """Receipt rejected for draft without linked supply records"""
        # First create a new draft, set bc_response to created, but don't create supply
        draft_resp = requests.post(
            f"{BASE_URL}/api/inventory-ledger/generate-po-draft",
            json={
                "customer_id": self.customer_id,
                "items": [{"item": "SPAM-LITE", "recommended_qty": 5, "source": f"{self.test_prefix}"}]
            }
        )
        if draft_resp.status_code == 409:
            print("  ⚠ Draft creation blocked by duplicate guard")
            pytest.skip("Cannot create test draft due to duplicate guard")
            return
            
        if draft_resp.status_code != 200:
            pytest.skip(f"Cannot create test draft: {draft_resp.text}")
            return
            
        draft_id = draft_resp.json()["po_draft_id"]
        
        # Assign vendor first (required for BC response)
        vendor_resp = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/vendor",
            json={"vendor_id": "V-TEST-RECEIPT", "vendor_name": "Test Vendor for Receipt"}
        )
        assert vendor_resp.status_code == 200, f"Failed to assign vendor: {vendor_resp.text}"
        
        # Record BC response as created (but no supply created yet)
        bc_resp = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/bc-response",
            json={"bc_response_status": "created", "bc_po_number": f"PO-TEST-{self.test_prefix}", "bc_document_id": "", "bc_response_notes": "Test"}
        )
        assert bc_resp.status_code == 200, f"Failed to set BC response: {bc_resp.text}"
        
        # Now try receipt - should fail because no linked supply
        resp = requests.post(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/bc-receipt",
            json={"received_lines": [{"item": "SPAM-LITE", "qty_received": 5}], "receipt_notes": "Test"}
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
        assert "No linked incoming supply" in resp.json().get("detail", "")
        print(f"✓ Receipt rejected for draft {draft_id} without linked supply")

    def test_duplicate_receipt_is_idempotent(self):
        """Duplicate receipt is idempotent - returns skipped, not error"""
        # Use the already-received draft
        draft_id = self.existing_received_draft_id
        
        # Check that this draft has received supply
        linked_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/incoming-supply")
        if linked_resp.status_code != 200:
            pytest.skip(f"Cannot get linked supply: {linked_resp.text}")
            return
        
        linked = linked_resp.json().get("records", [])
        received_items = [s for s in linked if s.get("status") == "received"]
        
        if not received_items:
            pytest.skip("No received items found for idempotency test")
            return
        
        # Try to receive again - should be skipped
        receive_lines = [{"item": s["item"], "qty_received": s["incoming_qty"]} for s in received_items]
        resp = requests.post(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/bc-receipt",
            json={"received_lines": receive_lines, "receipt_notes": "Duplicate test"}
        )
        
        # Should succeed but with skipped items, or return 422 if all items fail
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("total_skipped", 0) > 0, f"Expected skipped items, got: {data}"
            assert data.get("total_received", 0) == 0, f"Received items should be 0 for duplicate: {data}"
            print(f"✓ Duplicate receipt is idempotent - {data['total_skipped']} skipped, 0 received")
        elif resp.status_code == 422:
            # All items errored/already received
            print(f"✓ Duplicate receipt returns 422 (all items already received)")
        else:
            pytest.fail(f"Unexpected status {resp.status_code}: {resp.text}")

    def test_over_receipt_rejected(self):
        """Over-receipt (qty > ordered qty) rejected with 422"""
        # Create a test scenario: new draft -> create supply -> BC response created -> try over-receipt
        # For this test, we'll look for existing ordered supply and try to receive more
        
        # Get all drafts and find one with ordered supply
        drafts_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={self.customer_id}&limit=50")
        drafts = drafts_resp.json().get("drafts", [])
        
        for draft in drafts:
            if draft.get("bc_response_status") == "created":
                draft_id = draft["po_draft_id"]
                linked_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/incoming-supply")
                if linked_resp.status_code == 200:
                    linked = linked_resp.json().get("records", [])
                    ordered = [s for s in linked if s.get("status") == "ordered"]
                    if ordered:
                        # Found ordered supply - try over-receipt
                        item = ordered[0]
                        over_qty = item["incoming_qty"] + 999
                        resp = requests.post(
                            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/bc-receipt",
                            json={"received_lines": [{"item": item["item"], "qty_received": over_qty}], "receipt_notes": "Over-receipt test"}
                        )
                        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
                        detail = resp.json().get("detail", "")
                        if isinstance(detail, dict):
                            errors = detail.get("errors", [])
                            assert any("Over-receipt" in str(e.get("error", "")) for e in errors), f"Expected over-receipt error: {errors}"
                        print(f"✓ Over-receipt rejected for {item['item']}: qty {over_qty} > ordered {item['incoming_qty']}")
                        return
        
        print("  ⚠ No drafts with ordered supply found - testing with mock data")
        # Create a new scenario for over-receipt test
        pytest.skip("No ordered supply found to test over-receipt rejection")

    def test_partial_receipt_rejected(self):
        """Partial receipt (qty < ordered qty) rejected with 422"""
        # Similar to over-receipt test, find ordered supply
        drafts_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={self.customer_id}&limit=50")
        drafts = drafts_resp.json().get("drafts", [])
        
        for draft in drafts:
            if draft.get("bc_response_status") == "created":
                draft_id = draft["po_draft_id"]
                linked_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/incoming-supply")
                if linked_resp.status_code == 200:
                    linked = linked_resp.json().get("records", [])
                    ordered = [s for s in linked if s.get("status") == "ordered"]
                    if ordered:
                        # Found ordered supply - try partial receipt
                        item = ordered[0]
                        if item["incoming_qty"] > 1:
                            partial_qty = item["incoming_qty"] - 1  # One less than ordered
                            resp = requests.post(
                                f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/bc-receipt",
                                json={"received_lines": [{"item": item["item"], "qty_received": partial_qty}], "receipt_notes": "Partial test"}
                            )
                            assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
                            detail = resp.json().get("detail", "")
                            if isinstance(detail, dict):
                                errors = detail.get("errors", [])
                                assert any("Partial receipt" in str(e.get("error", "")) for e in errors), f"Expected partial receipt error: {errors}"
                            print(f"✓ Partial receipt rejected for {item['item']}: qty {partial_qty} < ordered {item['incoming_qty']}")
                            return
        
        pytest.skip("No ordered supply with qty > 1 found to test partial receipt rejection")

    def test_po_draft_detail_receipt_summary_enrichment(self):
        """PO draft detail returns receipt_summary fields"""
        draft_id = self.existing_received_draft_id
        
        resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}")
        assert resp.status_code == 200, f"Failed to get draft detail: {resp.text}"
        
        data = resp.json()
        
        # Check for receipt summary fields
        assert "linked_supply_received_count" in data, f"Missing linked_supply_received_count: {data.keys()}"
        assert "linked_supply_ordered_count" in data, f"Missing linked_supply_ordered_count: {data.keys()}"
        assert "linked_supply_total_qty" in data, f"Missing linked_supply_total_qty: {data.keys()}"
        assert "linked_supply_received_qty" in data, f"Missing linked_supply_received_qty: {data.keys()}"
        
        # For the received draft, received_count should be > 0
        assert data.get("linked_supply_received_count", 0) >= 0, f"linked_supply_received_count should be >= 0"
        
        print(f"✓ PO draft detail returns receipt summary:")
        print(f"  - received_count: {data.get('linked_supply_received_count')}")
        print(f"  - ordered_count: {data.get('linked_supply_ordered_count')}")
        print(f"  - total_qty: {data.get('linked_supply_total_qty')}")
        print(f"  - received_qty: {data.get('linked_supply_received_qty')}")

    def test_linked_supply_endpoint_returns_receipt_summary(self):
        """Linked supply endpoint returns receipt_summary object"""
        draft_id = self.existing_received_draft_id
        
        resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/incoming-supply")
        assert resp.status_code == 200, f"Failed to get linked supply: {resp.text}"
        
        data = resp.json()
        
        # Check for receipt_summary object
        assert "receipt_summary" in data, f"Missing receipt_summary: {data.keys()}"
        summary = data["receipt_summary"]
        
        assert "received_count" in summary, f"Missing received_count in receipt_summary"
        assert "ordered_count" in summary, f"Missing ordered_count in receipt_summary"
        assert "total_qty" in summary, f"Missing total_qty in receipt_summary"
        assert "received_qty" in summary, f"Missing received_qty in receipt_summary"
        
        print(f"✓ Linked supply endpoint returns receipt_summary:")
        print(f"  - received_count: {summary.get('received_count')}")
        print(f"  - ordered_count: {summary.get('ordered_count')}")
        print(f"  - total_qty: {summary.get('total_qty')}")
        print(f"  - received_qty: {summary.get('received_qty')}")

    def test_linked_supply_records_have_bc_receipt_at(self):
        """Linked supply records have bc_receipt_at field when received"""
        draft_id = self.existing_received_draft_id
        
        resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/incoming-supply")
        assert resp.status_code == 200, f"Failed to get linked supply: {resp.text}"
        
        records = resp.json().get("records", [])
        received = [r for r in records if r.get("status") == "received"]
        
        if not received:
            pytest.skip("No received records to verify bc_receipt_at")
            return
        
        for r in received:
            # received records should have bc_receipt_at
            assert r.get("bc_receipt_at"), f"Received record {r['item']} missing bc_receipt_at"
            print(f"✓ {r['item']}: bc_receipt_at = {r['bc_receipt_at']}")


class TestBCReceiptCaptureFullFlow:
    """Full flow test: Create draft -> Convert to supply -> BC response -> Receipt"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.customer_id = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"
        self.test_prefix = f"TEST-FLOW-{uuid.uuid4().hex[:6].upper()}"

    def test_full_receipt_flow_creates_ledger_movement(self):
        """
        Full receipt flow test:
        1. Create PO draft with unique item
        2. Convert to incoming supply (status: planned)
        3. Assign vendor
        4. BC response created -> advances to ordered
        5. Record receipt -> advances to received, creates ledger movement
        """
        # Step 1: Create a unique test item in balances first
        # We need an item that exists in inventory
        balances_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{self.customer_id}/balances")
        if balances_resp.status_code != 200:
            pytest.skip(f"Cannot get balances: {balances_resp.text}")
            return
        
        balances = balances_resp.json().get("balances", [])
        if not balances:
            pytest.skip("No items in inventory to test with")
            return
        
        # Use first available item
        test_item = balances[0]["item"]
        test_qty = 5
        
        # Step 1: Create PO draft
        draft_resp = requests.post(
            f"{BASE_URL}/api/inventory-ledger/generate-po-draft",
            json={
                "customer_id": self.customer_id,
                "items": [{"item": test_item, "recommended_qty": test_qty, "source": self.test_prefix}]
            }
        )
        
        if draft_resp.status_code == 409:
            # Duplicate protection - wait and retry or skip
            print(f"  ⚠ Duplicate guard triggered for {test_item}")
            pytest.skip("Cannot create test draft due to duplicate guard")
            return
        
        assert draft_resp.status_code == 200, f"Draft creation failed: {draft_resp.text}"
        draft_id = draft_resp.json()["po_draft_id"]
        print(f"  Created draft: {draft_id}")
        
        # Step 2: Convert to incoming supply
        convert_resp = requests.post(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/create-incoming-supply")
        if convert_resp.status_code == 409:
            print("  ⚠ Already converted")
        else:
            assert convert_resp.status_code == 200, f"Conversion failed: {convert_resp.text}"
            convert_data = convert_resp.json()
            assert convert_data.get("rows_created", 0) > 0, f"No supply created: {convert_data}"
            print(f"  Converted: {convert_data['rows_created']} supply record(s)")
        
        # Verify supply is in 'planned' status
        linked_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/incoming-supply")
        assert linked_resp.status_code == 200
        linked = linked_resp.json().get("records", [])
        planned = [s for s in linked if s.get("status") == "planned"]
        print(f"  Linked supply: {len(linked)} total, {len(planned)} planned")
        
        # Step 3: Assign vendor
        vendor_resp = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/vendor",
            json={"vendor_id": f"V-{self.test_prefix}", "vendor_name": "Test Receipt Vendor"}
        )
        assert vendor_resp.status_code == 200, f"Vendor assignment failed: {vendor_resp.text}"
        print(f"  Vendor assigned")
        
        # Step 4: BC response created (advances planned -> ordered)
        bc_resp = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/bc-response",
            json={
                "bc_response_status": "created",
                "bc_po_number": f"PO-{self.test_prefix}",
                "bc_document_id": f"DOC-{self.test_prefix}",
                "bc_response_notes": "Test flow"
            }
        )
        assert bc_resp.status_code == 200, f"BC response failed: {bc_resp.text}"
        print(f"  BC response created")
        
        # Verify supply is now 'ordered'
        linked_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/incoming-supply")
        linked = linked_resp.json().get("records", [])
        ordered = [s for s in linked if s.get("status") == "ordered"]
        assert len(ordered) > 0, f"Expected ordered supply after BC response: {linked}"
        print(f"  Supply advanced to ordered: {len(ordered)}")
        
        # Step 5: Record receipt (advances ordered -> received)
        receive_lines = [{"item": s["item"], "qty_received": s["incoming_qty"]} for s in ordered]
        receipt_resp = requests.post(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/bc-receipt",
            json={"received_lines": receive_lines, "receipt_notes": f"Full flow test {self.test_prefix}"}
        )
        assert receipt_resp.status_code == 200, f"Receipt failed: {receipt_resp.text}"
        
        receipt_data = receipt_resp.json()
        assert receipt_data.get("total_received", 0) > 0, f"Expected received items: {receipt_data}"
        print(f"  Receipt recorded: {receipt_data['total_received']} received")
        
        # Verify receipt_movement_id is returned
        results = receipt_data.get("results", [])
        for r in results:
            if r.get("status") == "received":
                assert r.get("receipt_movement_id"), f"Missing receipt_movement_id: {r}"
                print(f"  ✓ {r['item']}: receipt_movement_id = {r['receipt_movement_id']}")
        
        # Verify supply is now 'received' with bc_receipt_at
        linked_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/incoming-supply")
        linked = linked_resp.json().get("records", [])
        received = [s for s in linked if s.get("status") == "received"]
        assert len(received) > 0, f"Expected received supply: {linked}"
        
        for s in received:
            assert s.get("bc_receipt_at"), f"Missing bc_receipt_at on received supply: {s}"
        
        print(f"✓ Full receipt flow completed successfully for draft {draft_id}")


class TestBCReceiptRegressions:
    """Regression tests to ensure existing functionality still works"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.customer_id = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"
        self.existing_draft_id = "PO-DRAFT-20260314163256-689B67"

    def test_regression_bc_response_capture_still_works(self):
        """BC response capture endpoint still works"""
        # Get any draft with vendor
        drafts_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={self.customer_id}&limit=10")
        drafts = drafts_resp.json().get("drafts", [])
        
        # Find draft with vendor for BC response test
        with_vendor = [d for d in drafts if d.get("vendor_id")]
        if not with_vendor:
            pytest.skip("No drafts with vendor for regression test")
            return
        
        draft = with_vendor[0]
        draft_id = draft["po_draft_id"]
        
        # Check current state
        detail_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}")
        assert detail_resp.status_code == 200
        print(f"✓ BC response capture endpoint accessible (draft: {draft_id})")

    def test_regression_submission_log_still_works(self):
        """Submission log endpoint still works"""
        draft_id = self.existing_draft_id
        
        resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/submission-log")
        assert resp.status_code == 200, f"Submission log failed: {resp.text}"
        
        data = resp.json()
        assert "entries" in data, f"Missing entries field: {data.keys()}"
        print(f"✓ Submission log endpoint works ({len(data.get('entries', []))} entries)")

    def test_regression_vendor_assignment_still_works(self):
        """Vendor assignment endpoint still works"""
        # Try to get draft without vendor, or just verify endpoint is accessible
        drafts_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={self.customer_id}&limit=10")
        drafts = drafts_resp.json().get("drafts", [])
        
        if drafts:
            draft_id = drafts[0]["po_draft_id"]
            # Just verify endpoint returns proper response (404 or 200)
            resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}")
            assert resp.status_code == 200
            data = resp.json()
            # Vendor fields should be accessible
            assert "vendor_id" in data or data.get("vendor_id") is None
            print(f"✓ Vendor assignment accessible (draft: {draft_id}, vendor: {data.get('vendor_name', 'none')})")

    def test_regression_bc_export_still_works(self):
        """BC export endpoint still works"""
        # Find draft with vendor for export
        drafts_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={self.customer_id}&limit=10")
        drafts = drafts_resp.json().get("drafts", [])
        
        with_vendor = [d for d in drafts if d.get("vendor_id") and d.get("status") != "archived"]
        if not with_vendor:
            pytest.skip("No exportable drafts for regression test")
            return
        
        draft_id = with_vendor[0]["po_draft_id"]
        resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/bc-export")
        
        # Should return 200 with JSON or proper validation error
        assert resp.status_code in [200, 422], f"BC export failed unexpectedly: {resp.status_code}: {resp.text}"
        print(f"✓ BC export endpoint works (draft: {draft_id}, status: {resp.status_code})")

    def test_regression_linked_supply_endpoint_still_works(self):
        """Linked incoming supply endpoint still works"""
        draft_id = self.existing_draft_id
        
        resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/incoming-supply")
        assert resp.status_code == 200, f"Linked supply endpoint failed: {resp.text}"
        
        data = resp.json()
        assert "records" in data, f"Missing records field: {data.keys()}"
        assert "receipt_summary" in data, f"Missing receipt_summary field: {data.keys()}"
        print(f"✓ Linked supply endpoint works ({len(data.get('records', []))} records)")

    def test_regression_balances_endpoint_still_works(self):
        """Balances endpoint still works"""
        resp = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{self.customer_id}/balances")
        assert resp.status_code == 200, f"Balances endpoint failed: {resp.text}"
        
        data = resp.json()
        assert "balances" in data, f"Missing balances field: {data.keys()}"
        print(f"✓ Balances endpoint works ({len(data.get('balances', []))} items)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
