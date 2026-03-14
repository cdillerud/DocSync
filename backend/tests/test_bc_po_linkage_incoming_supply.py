"""
Backend API tests for BC PO Linkage to Incoming Supply (iteration_79)

Tests:
1. PO draft → incoming supply conversion stores po_draft_id on created supply records
2. GET /api/inventory-ledger/po-drafts/{id}/incoming-supply returns linked supply records
3. BC response created advances planned supply to ordered
4. BC response created sets bc_po_number and bc_document_id on linked supply
5. BC response linkage is idempotent (repeat created response doesn't break anything)
6. BC response rejected does NOT alter linked supply status
7. BC response pending does NOT alter linked supply status
8. PO draft detail GET returns linked_supply_count, linked_supply_status_counts, linked_supply_has_bc_po_number
9. Linked incoming supply endpoint returns 404 for nonexistent draft
10. Regression: BC export still works
11. Regression: Vendor assignment still works
12. Regression: Submission log still works
13. Regression: BC response capture still works
14. Regression: Create Incoming Supply conversion still works
"""

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Known test customer (Hormel Foods)
CUSTOMER_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"

# Known draft with existing data - bc_response_status=created, has linked supply
DRAFT_WITH_BC_CREATED = "PO-DRAFT-20260314163256-689B67"


class TestLinkedIncomingSupplyEndpoint:
    """Tests for GET /api/inventory-ledger/po-drafts/{id}/incoming-supply endpoint"""

    def test_get_linked_supply_returns_records(self):
        """GET /api/inventory-ledger/po-drafts/{id}/incoming-supply returns linked supply records"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/incoming-supply")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        
        # Validate response structure
        assert "po_draft_id" in data
        assert data["po_draft_id"] == DRAFT_WITH_BC_CREATED
        assert "total" in data
        assert "records" in data
        assert isinstance(data["records"], list)
        
        # Should have at least some records (SPAM-LITE, TEST-ITEM-WARN)
        assert data["total"] >= 2, f"Expected at least 2 records, got {data['total']}"
        print(f"PASS: GET linked supply returns {data['total']} records for draft {DRAFT_WITH_BC_CREATED}")

    def test_linked_supply_has_expected_fields(self):
        """Linked supply records have item, qty, status, bc_po_number fields"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/incoming-supply")
        assert res.status_code == 200
        data = res.json()
        
        for record in data["records"]:
            assert "item" in record, "Record missing 'item' field"
            assert "incoming_qty" in record, "Record missing 'incoming_qty' field"
            assert "status" in record, "Record missing 'status' field"
            # bc_po_number and bc_document_id may or may not be present
            
        print(f"PASS: All {len(data['records'])} linked supply records have expected fields")

    def test_linked_supply_404_for_nonexistent_draft(self):
        """GET /api/inventory-ledger/po-drafts/{id}/incoming-supply returns 404 for nonexistent draft"""
        fake_draft_id = f"PO-DRAFT-FAKE-{uuid.uuid4().hex[:8].upper()}"
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{fake_draft_id}/incoming-supply")
        assert res.status_code == 404, f"Expected 404, got {res.status_code}: {res.text}"
        print(f"PASS: GET linked supply returns 404 for nonexistent draft {fake_draft_id}")


class TestPODraftDetailLinkedSupplyEnrichment:
    """Tests for PO draft detail enrichment with linked supply summary"""

    def test_po_draft_detail_has_linked_supply_count(self):
        """PO draft detail GET returns linked_supply_count"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        
        assert "linked_supply_count" in data, "Missing linked_supply_count in draft detail"
        assert data["linked_supply_count"] >= 2, f"Expected linked_supply_count >= 2, got {data['linked_supply_count']}"
        print(f"PASS: Draft detail has linked_supply_count = {data['linked_supply_count']}")

    def test_po_draft_detail_has_linked_supply_status_counts(self):
        """PO draft detail GET returns linked_supply_status_counts"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}")
        assert res.status_code == 200
        data = res.json()
        
        assert "linked_supply_status_counts" in data, "Missing linked_supply_status_counts in draft detail"
        assert isinstance(data["linked_supply_status_counts"], dict)
        
        # Since BC response was 'created', supply should be in 'ordered' status
        status_counts = data["linked_supply_status_counts"]
        assert "ordered" in status_counts or "planned" in status_counts, f"Expected 'ordered' or 'planned' in status_counts: {status_counts}"
        print(f"PASS: Draft detail has linked_supply_status_counts = {status_counts}")

    def test_po_draft_detail_has_linked_supply_has_bc_po_number(self):
        """PO draft detail GET returns linked_supply_has_bc_po_number"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}")
        assert res.status_code == 200
        data = res.json()
        
        assert "linked_supply_has_bc_po_number" in data, "Missing linked_supply_has_bc_po_number in draft detail"
        assert isinstance(data["linked_supply_has_bc_po_number"], bool)
        
        # This draft has bc_response_status=created with PO-9999
        assert data["linked_supply_has_bc_po_number"] is True, f"Expected linked_supply_has_bc_po_number=True, got {data['linked_supply_has_bc_po_number']}"
        print(f"PASS: Draft detail has linked_supply_has_bc_po_number = {data['linked_supply_has_bc_po_number']}")


class TestBCResponseLinkage:
    """Tests for BC response linkage to incoming supply"""

    def test_bc_response_created_sets_bc_fields_on_supply(self):
        """BC response created sets bc_po_number and bc_document_id on linked supply"""
        # Get linked supply for the draft that has bc_response_status=created
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/incoming-supply")
        assert res.status_code == 200
        data = res.json()
        
        # Verify records have BC fields set
        records_with_bc_po = [r for r in data["records"] if r.get("bc_po_number")]
        assert len(records_with_bc_po) > 0, "Expected some records to have bc_po_number set"
        
        for record in records_with_bc_po:
            # Per the context, bc_po_number should be PO-9999
            assert record["bc_po_number"] == "PO-9999", f"Expected bc_po_number='PO-9999', got {record['bc_po_number']}"
            print(f"PASS: Supply record {record['item']} has bc_po_number={record['bc_po_number']}")

    def test_bc_response_created_advances_planned_to_ordered(self):
        """BC response created advances planned supply to ordered"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/incoming-supply")
        assert res.status_code == 200
        data = res.json()
        
        # Per context, both supply records should now be at status=ordered
        for record in data["records"]:
            assert record["status"] == "ordered", f"Expected status='ordered' for {record['item']}, got {record['status']}"
        
        print(f"PASS: All {len(data['records'])} linked supply records are in 'ordered' status")


class TestBCResponseIdempotency:
    """Tests for BC response linkage idempotency"""

    def test_bc_response_idempotent_on_already_ordered(self):
        """Repeat BC created response on already ordered records doesn't break anything"""
        # Send another BC response 'created' to the same draft
        res = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/bc-response",
            json={
                "bc_response_status": "created",
                "bc_po_number": "PO-9999-REPEAT",
                "bc_document_id": "DOC-REPEAT-001",
                "bc_response_notes": "Idempotency test - repeat created response"
            }
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        # Check supply records are still valid
        supply_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/incoming-supply")
        assert supply_res.status_code == 200
        supply_data = supply_res.json()
        
        # All records should still be ordered and have updated BC PO number
        for record in supply_data["records"]:
            assert record["status"] == "ordered", f"Expected status='ordered' for {record['item']}, got {record['status']}"
            # BC fields should be updated with new values
            assert record.get("bc_po_number") == "PO-9999-REPEAT", f"Expected bc_po_number='PO-9999-REPEAT', got {record.get('bc_po_number')}"
        
        print(f"PASS: BC response linkage is idempotent - all {len(supply_data['records'])} records updated correctly")


class TestBCResponseNonCreatedStatus:
    """Tests for BC response rejected/pending NOT altering supply status"""

    def test_bc_response_rejected_does_not_alter_supply(self):
        """BC response rejected does NOT alter linked supply status"""
        # First, get current supply state
        before_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/incoming-supply")
        assert before_res.status_code == 200
        before_data = before_res.json()
        before_statuses = {r["item"]: r["status"] for r in before_data["records"]}
        
        # Send rejected response (note: rejected requires notes)
        res = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/bc-response",
            json={
                "bc_response_status": "rejected",
                "bc_po_number": "",
                "bc_document_id": "",
                "bc_response_notes": "Test rejection - should not alter supply"
            }
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        # Check supply records are unchanged (rejected doesn't trigger update)
        after_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/incoming-supply")
        assert after_res.status_code == 200
        after_data = after_res.json()
        
        for record in after_data["records"]:
            # Status should be same as before (ordered remains ordered)
            assert record["status"] == before_statuses[record["item"]], \
                f"Expected status unchanged for {record['item']}, was {before_statuses[record['item']]}, now {record['status']}"
        
        print(f"PASS: BC response rejected does NOT alter linked supply status")

    def test_bc_response_pending_does_not_alter_supply(self):
        """BC response pending does NOT alter linked supply status"""
        # First, get current supply state
        before_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/incoming-supply")
        assert before_res.status_code == 200
        before_data = before_res.json()
        before_statuses = {r["item"]: r["status"] for r in before_data["records"]}
        
        # Send pending response
        res = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/bc-response",
            json={
                "bc_response_status": "pending",
                "bc_po_number": "",
                "bc_document_id": "",
                "bc_response_notes": "Test pending - should not alter supply"
            }
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        # Check supply records are unchanged (pending doesn't trigger update)
        after_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/incoming-supply")
        assert after_res.status_code == 200
        after_data = after_res.json()
        
        for record in after_data["records"]:
            # Status should be same as before
            assert record["status"] == before_statuses[record["item"]], \
                f"Expected status unchanged for {record['item']}, was {before_statuses[record['item']]}, now {record['status']}"
        
        print(f"PASS: BC response pending does NOT alter linked supply status")


class TestConversionStoresPoDraftId:
    """Tests for conversion storing po_draft_id on supply records"""

    def test_linked_supply_has_source_reference_matching_draft_id(self):
        """Linked supply records have source_reference matching draft_id"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/incoming-supply")
        assert res.status_code == 200
        data = res.json()
        
        for record in data["records"]:
            assert record.get("source_reference") == DRAFT_WITH_BC_CREATED, \
                f"Expected source_reference='{DRAFT_WITH_BC_CREATED}', got {record.get('source_reference')}"
        
        print(f"PASS: All {len(data['records'])} linked supply records have source_reference matching draft_id")


class TestRegressionEndpoints:
    """Regression tests for existing endpoints"""

    def test_regression_bc_export_still_works(self):
        """Regression: BC export still works"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/bc-export")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        # Verify it's a BC payload
        data = res.json()
        assert "poDraftId" in data
        assert "vendor" in data
        assert "lines" in data
        print("PASS: BC export still works")

    def test_regression_vendor_assignment_still_works(self):
        """Regression: Vendor assignment still works"""
        res = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/vendor",
            json={"vendor_id": "V10045", "vendor_name": "Acme Bottle Supply"}
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["vendor_id"] == "V10045"
        print("PASS: Vendor assignment still works")

    def test_regression_submission_log_still_works(self):
        """Regression: Submission log still works"""
        # GET submission log
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/submission-log")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert "entries" in data
        assert "total" in data
        print("PASS: Submission log GET still works")

    def test_regression_bc_response_capture_still_works(self):
        """Regression: BC response capture still works"""
        res = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_BC_CREATED}/bc-response",
            json={
                "bc_response_status": "created",
                "bc_po_number": "PO-9999",
                "bc_document_id": "DOC-9999",
                "bc_response_notes": "Regression test"
            }
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["bc_response_status"] == "created"
        assert data["bc_po_number"] == "PO-9999"
        print("PASS: BC response capture still works")

    def test_regression_balances_endpoint_still_works(self):
        """Regression: Balances endpoint still works"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{CUSTOMER_ID}/balances")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert "balances" in data
        print("PASS: Balances endpoint still works")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
