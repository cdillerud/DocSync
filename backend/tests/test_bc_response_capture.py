"""
BC PO Response Capture Tests (iteration_78)

Tests the PATCH /api/inventory-ledger/po-drafts/{id}/bc-response endpoint and related functionality:
- Record BC processing result (created/rejected/pending)
- Auto-create submission log entry with mapped status
- Validate bc_response_status, bc_po_number, bc_document_id, bc_response_notes
- PO draft detail enrichment with BC response fields
- PO Drafts list shows bc_response_status and bc_po_number
- Item detail last_po_draft includes bc_po_number and bc_response_status
"""
import pytest
import requests
import os
import uuid as _uuid
from datetime import datetime

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Known test data from previous iterations
CUSTOMER_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"  # Hormel Foods
DRAFT_WITH_VENDOR = "PO-DRAFT-20260314163256-689B67"  # Has vendor V10045/Acme Bottle Supply, has bc_response already
DRAFT_WITH_VENDOR_2 = "PO-DRAFT-20260314170144-8ED5A8"  # Has vendor UI-TEST-V001/UI Test Vendor Inc


class TestBCResponseEndpoint:
    """Tests for PATCH /api/inventory-ledger/po-drafts/{id}/bc-response"""
    
    def test_bc_response_created_status(self):
        """PATCH bc-response records 'created' status with bc_po_number and bc_document_id"""
        # Use the draft that already has vendor assigned
        unique_po = f"PO-TEST-{_uuid.uuid4().hex[:6].upper()}"
        unique_doc = f"BC_DOC_{_uuid.uuid4().hex[:6].upper()}"
        
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-response",
            json={
                "bc_response_status": "created",
                "bc_po_number": unique_po,
                "bc_document_id": unique_doc,
                "bc_response_notes": ""
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("bc_response_status") == "created"
        assert data.get("bc_po_number") == unique_po
        assert data.get("bc_document_id") == unique_doc
        assert "bc_response_at" in data
        print(f"✓ Created status recorded: PO#{unique_po}, Doc#{unique_doc}")

    def test_bc_response_pending_status(self):
        """PATCH bc-response records 'pending' status (notes optional)"""
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-response",
            json={
                "bc_response_status": "pending",
                "bc_po_number": "",
                "bc_document_id": "",
                "bc_response_notes": "Awaiting BC processing"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("bc_response_status") == "pending"
        assert data.get("bc_response_notes") == "Awaiting BC processing"
        print("✓ Pending status recorded with optional notes")

    def test_bc_response_rejected_requires_notes(self):
        """PATCH bc-response rejected status requires bc_response_notes (422 without)"""
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-response",
            json={
                "bc_response_status": "rejected",
                "bc_po_number": "",
                "bc_document_id": "",
                "bc_response_notes": ""  # Empty notes
            }
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        assert "notes" in response.json().get("detail", "").lower() or "required" in response.json().get("detail", "").lower()
        print("✓ Rejected status requires notes (422 as expected)")

    def test_bc_response_rejected_with_notes(self):
        """PATCH bc-response rejected status succeeds with notes provided"""
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-response",
            json={
                "bc_response_status": "rejected",
                "bc_po_number": "",
                "bc_document_id": "",
                "bc_response_notes": "Invalid vendor code in BC"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("bc_response_status") == "rejected"
        assert data.get("bc_response_notes") == "Invalid vendor code in BC"
        print("✓ Rejected status recorded with required notes")

    def test_bc_response_invalid_status(self):
        """PATCH bc-response with invalid status returns 422"""
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-response",
            json={
                "bc_response_status": "invalid_status",
                "bc_po_number": "",
                "bc_document_id": "",
                "bc_response_notes": ""
            }
        )
        assert response.status_code == 422
        assert "invalid" in response.json().get("detail", "").lower() or "created" in response.json().get("detail", "").lower()
        print("✓ Invalid status rejected (422)")

    def test_bc_response_nonexistent_draft(self):
        """PATCH bc-response for nonexistent draft returns 404"""
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/NONEXISTENT-DRAFT-123/bc-response",
            json={
                "bc_response_status": "created",
                "bc_po_number": "PO-999",
                "bc_document_id": "",
                "bc_response_notes": ""
            }
        )
        assert response.status_code == 404
        print("✓ Nonexistent draft returns 404")


class TestBCResponseSubmissionLog:
    """Tests that BC response auto-creates submission log entry with mapped status"""
    
    def test_bc_response_created_maps_to_acknowledged_log(self):
        """BC response 'created' auto-creates log with status 'acknowledged'"""
        unique_po = f"PO-LOG-{_uuid.uuid4().hex[:6].upper()}"
        
        # Get current log count
        logs_before = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log")
        before_count = logs_before.json().get("total", 0)
        
        # Record created response
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-response",
            json={
                "bc_response_status": "created",
                "bc_po_number": unique_po,
                "bc_document_id": "doc123",
                "bc_response_notes": ""
            }
        )
        assert response.status_code == 200
        
        # Check new log entry was created
        logs_after = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log")
        after_data = logs_after.json()
        after_count = after_data.get("total", 0)
        
        assert after_count > before_count, "No new log entry created"
        
        # Latest entry should be 'acknowledged' (mapped from 'created')
        latest_log = after_data["entries"][0]
        assert latest_log["status"] == "acknowledged"
        assert "BC response: created" in latest_log.get("notes", "")
        assert f"PO#: {unique_po}" in latest_log.get("notes", "")
        print(f"✓ 'created' response auto-logged as 'acknowledged': {latest_log['submission_id']}")

    def test_bc_response_rejected_maps_to_failed_log(self):
        """BC response 'rejected' auto-creates log with status 'failed'"""
        # Get current log count
        logs_before = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log")
        before_count = logs_before.json().get("total", 0)
        
        # Record rejected response
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-response",
            json={
                "bc_response_status": "rejected",
                "bc_po_number": "",
                "bc_document_id": "",
                "bc_response_notes": "Vendor validation failed"
            }
        )
        assert response.status_code == 200
        
        # Check new log entry
        logs_after = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log")
        after_data = logs_after.json()
        
        latest_log = after_data["entries"][0]
        assert latest_log["status"] == "failed"
        assert "BC response: rejected" in latest_log.get("notes", "")
        assert "Vendor validation failed" in latest_log.get("notes", "")
        print(f"✓ 'rejected' response auto-logged as 'failed': {latest_log['submission_id']}")

    def test_bc_response_pending_maps_to_submitted_log(self):
        """BC response 'pending' auto-creates log with status 'submitted'"""
        logs_before = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log")
        before_count = logs_before.json().get("total", 0)
        
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-response",
            json={
                "bc_response_status": "pending",
                "bc_po_number": "",
                "bc_document_id": "",
                "bc_response_notes": "Processing in BC"
            }
        )
        assert response.status_code == 200
        
        logs_after = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log")
        latest_log = logs_after.json()["entries"][0]
        
        assert latest_log["status"] == "submitted"
        assert "BC response: pending" in latest_log.get("notes", "")
        print(f"✓ 'pending' response auto-logged as 'submitted': {latest_log['submission_id']}")

    def test_bc_response_log_contains_bc_payload_snapshot(self):
        """Auto-created submission log includes bc_payload_snapshot"""
        unique_po = f"PO-SNAP-{_uuid.uuid4().hex[:6].upper()}"
        
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-response",
            json={
                "bc_response_status": "created",
                "bc_po_number": unique_po,
                "bc_document_id": "snap_doc",
                "bc_response_notes": ""
            }
        )
        assert response.status_code == 200
        
        logs = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log")
        latest_log = logs.json()["entries"][0]
        
        assert "bc_payload_snapshot" in latest_log
        snapshot = latest_log["bc_payload_snapshot"]
        assert "poDraftId" in snapshot
        assert "vendor" in snapshot
        assert "lines" in snapshot
        assert snapshot["poDraftId"] == DRAFT_WITH_VENDOR
        print(f"✓ Log entry contains bc_payload_snapshot with required structure")


class TestPODraftDetailEnrichment:
    """Tests that PO draft detail returns BC response fields"""
    
    def test_po_draft_detail_includes_bc_response_fields(self):
        """GET /api/inventory-ledger/po-drafts/{id} returns BC response fields"""
        # First set a BC response
        unique_po = f"PO-DETAIL-{_uuid.uuid4().hex[:6].upper()}"
        requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-response",
            json={
                "bc_response_status": "created",
                "bc_po_number": unique_po,
                "bc_document_id": "detail_doc_123",
                "bc_response_notes": "Test notes for detail"
            }
        )
        
        # Get draft detail
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("bc_response_status") == "created"
        assert data.get("bc_po_number") == unique_po
        assert data.get("bc_document_id") == "detail_doc_123"
        assert "bc_response_at" in data
        assert data.get("bc_response_notes") == "Test notes for detail"
        print(f"✓ PO draft detail includes all BC response fields")


class TestPODraftsListEnrichment:
    """Tests that PO Drafts list shows bc_response_status and bc_po_number"""
    
    def test_po_drafts_list_includes_bc_fields(self):
        """GET /api/inventory-ledger/po-drafts returns bc_response_status and bc_po_number"""
        # Set a unique BC response
        unique_po = f"PO-LIST-{_uuid.uuid4().hex[:6].upper()}"
        requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-response",
            json={
                "bc_response_status": "created",
                "bc_po_number": unique_po,
                "bc_document_id": "list_doc",
                "bc_response_notes": ""
            }
        )
        
        # Get drafts list
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}")
        assert response.status_code == 200
        
        data = response.json()
        drafts = data.get("drafts", [])
        
        # Find our test draft
        test_draft = next((d for d in drafts if d["po_draft_id"] == DRAFT_WITH_VENDOR), None)
        assert test_draft is not None, f"Draft {DRAFT_WITH_VENDOR} not found in list"
        
        assert test_draft.get("bc_response_status") == "created"
        assert test_draft.get("bc_po_number") == unique_po
        print(f"✓ PO Drafts list includes bc_response_status and bc_po_number")


class TestItemDetailLastPODraft:
    """Tests that item detail last_po_draft includes BC response fields"""
    
    def test_item_detail_last_po_draft_bc_fields(self):
        """GET /api/inventory-ledger/item-detail includes bc_po_number and bc_response_status in last_po_draft"""
        # First get the draft to find an item
        draft_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}")
        if draft_resp.status_code != 200:
            pytest.skip("Draft not found")
        
        draft = draft_resp.json()
        lines = draft.get("lines", [])
        if not lines:
            pytest.skip("Draft has no lines")
        
        item = lines[0].get("item", "")
        
        # Set BC response
        unique_po = f"PO-ITEM-{_uuid.uuid4().hex[:6].upper()}"
        requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-response",
            json={
                "bc_response_status": "created",
                "bc_po_number": unique_po,
                "bc_document_id": "",
                "bc_response_notes": ""
            }
        )
        
        # Get item detail
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/item-detail?customer_id={CUSTOMER_ID}&item={item}"
        )
        
        if response.status_code == 404:
            pytest.skip(f"Item {item} not found in workspace")
        
        assert response.status_code == 200
        data = response.json()
        
        last_po = data.get("last_po_draft")
        if last_po and last_po.get("po_draft_id") == DRAFT_WITH_VENDOR:
            assert last_po.get("bc_response_status") == "created"
            assert last_po.get("bc_po_number") == unique_po
            print(f"✓ Item detail last_po_draft includes bc_po_number and bc_response_status")
        else:
            print(f"⚠ last_po_draft is different draft or None, skipping field assertion")


class TestRegressionExistingFeatures:
    """Regression tests for existing vendor assignment, BC export, submission log, create incoming supply"""
    
    def test_vendor_assignment_still_works(self):
        """PATCH /api/inventory-ledger/po-drafts/{id}/vendor still works"""
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/vendor",
            json={"vendor_id": "REG-V001", "vendor_name": "Regression Vendor"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("vendor_id") == "REG-V001"
        print("✓ Vendor assignment regression passed")

    def test_bc_export_still_works(self):
        """GET /api/inventory-ledger/po-drafts/{id}/bc-export still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-export")
        assert response.status_code == 200
        assert "BC-PO-" in response.headers.get("Content-Disposition", "")
        print("✓ BC export regression passed")

    def test_submission_log_still_works(self):
        """GET /api/inventory-ledger/po-drafts/{id}/submission-log still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log")
        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        print("✓ Submission log regression passed")

    def test_create_incoming_supply_still_works(self):
        """POST /api/inventory-ledger/po-drafts/{id}/create-incoming-supply still works (may 409 if already created)"""
        response = requests.post(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/create-incoming-supply")
        # Either 200 (success) or 409 (already converted) is acceptable
        assert response.status_code in [200, 409]
        print(f"✓ Create incoming supply regression passed (status: {response.status_code})")

    def test_po_drafts_list_still_works(self):
        """GET /api/inventory-ledger/po-drafts still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}")
        assert response.status_code == 200
        data = response.json()
        assert "drafts" in data
        print("✓ PO Drafts list regression passed")

    def test_balances_endpoint_still_works(self):
        """GET /api/inventory-ledger/customers/{id}/balances still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{CUSTOMER_ID}/balances")
        assert response.status_code == 200
        data = response.json()
        assert "balances" in data
        print("✓ Balances endpoint regression passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
