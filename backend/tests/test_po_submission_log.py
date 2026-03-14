"""
PO Submission Log Tracking Tests (iteration_77)

Tests for the new po_submission_logs collection and related API endpoints:
- POST /api/inventory-ledger/po-drafts/{id}/submission-log - creates log entries
- GET /api/inventory-ledger/po-drafts/{id}/submission-log - lists entries reverse-chronologically
- BC export auto-logs with status='exported'
- PO Drafts list enriched with latest_submission_status
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL')
CUSTOMER_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"  # Hormel Foods

# Draft with vendor already assigned (from previous tests)
DRAFT_WITH_VENDOR = "PO-DRAFT-20260314163256-689B67"
# Draft with vendor UI-TEST-V001 - good for fresh testing
DRAFT_WITH_VENDOR_2 = "PO-DRAFT-20260314170144-8ED5A8"


class TestSubmissionLogEndpoints:
    """Test POST and GET submission-log endpoints"""
    
    def test_get_submission_logs_returns_list(self):
        """GET /submission-log returns entries for existing draft"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        data = res.json()
        assert "po_draft_id" in data
        assert data["po_draft_id"] == DRAFT_WITH_VENDOR
        assert "total" in data
        assert "entries" in data
        assert isinstance(data["entries"], list)
        print(f"SUCCESS: GET submission-log returns {data['total']} entries")
    
    def test_submission_logs_reverse_chronological_order(self):
        """Logs should be returned in reverse chronological order (newest first)"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log")
        assert res.status_code == 200
        
        data = res.json()
        entries = data["entries"]
        
        if len(entries) > 1:
            # Verify reverse chronological order
            for i in range(len(entries) - 1):
                current_ts = entries[i]["submitted_at"]
                next_ts = entries[i + 1]["submitted_at"]
                assert current_ts >= next_ts, f"Entries not in reverse chronological order: {current_ts} < {next_ts}"
            print(f"SUCCESS: {len(entries)} entries in reverse chronological order")
        else:
            print(f"SUCCESS: Only {len(entries)} entry, order check not applicable")
    
    def test_get_submission_logs_returns_404_for_nonexistent_draft(self):
        """GET /submission-log returns 404 for nonexistent draft"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/NONEXISTENT-DRAFT/submission-log")
        assert res.status_code == 404, f"Expected 404, got {res.status_code}"
        print("SUCCESS: Returns 404 for nonexistent draft")
    
    def test_post_submission_log_valid_statuses(self):
        """POST /submission-log accepts valid statuses: submitted, acknowledged, failed"""
        # Test with draft that has vendor assigned
        for status in ["submitted", "acknowledged", "failed"]:
            payload = {"status": status, "notes": f"Test log entry for {status}"}
            res = requests.post(
                f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log",
                json=payload
            )
            assert res.status_code == 200, f"Expected 200 for status '{status}', got {res.status_code}: {res.text}"
            
            data = res.json()
            assert data["status"] == status
            assert data["po_draft_id"] == DRAFT_WITH_VENDOR
            assert "submission_id" in data
            assert data["submission_id"].startswith("SUB-")
            print(f"SUCCESS: POST submission-log accepts status '{status}'")
    
    def test_post_submission_log_creates_entry_with_all_fields(self):
        """POST /submission-log creates entry with all required fields"""
        payload = {"status": "submitted", "notes": "Full field test entry"}
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log",
            json=payload
        )
        assert res.status_code == 200
        
        data = res.json()
        # Required fields
        assert "submission_id" in data
        assert "po_draft_id" in data
        assert "submitted_at" in data
        assert "vendor_id" in data
        assert "vendor_name" in data
        assert "status" in data
        assert "notes" in data
        assert "bc_payload_snapshot" in data
        
        # Validate bc_payload_snapshot structure
        snapshot = data["bc_payload_snapshot"]
        assert "poDraftId" in snapshot
        assert "vendor" in snapshot
        assert "documentDate" in snapshot
        assert "lines" in snapshot
        assert isinstance(snapshot["lines"], list)
        print(f"SUCCESS: Created entry with all fields, snapshot has {len(snapshot['lines'])} lines")
    
    def test_post_submission_log_rejects_invalid_status(self):
        """POST /submission-log returns 422 for invalid status"""
        for invalid_status in ["pending", "completed", "approved", "", "SUBMITTED"]:
            payload = {"status": invalid_status, "notes": "Testing invalid status"}
            res = requests.post(
                f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log",
                json=payload
            )
            assert res.status_code == 422, f"Expected 422 for status '{invalid_status}', got {res.status_code}"
        print("SUCCESS: Returns 422 for invalid statuses")
    
    def test_post_submission_log_rejects_archived_draft(self):
        """POST /submission-log returns 422 for archived draft"""
        # First get list of drafts to find an archived one
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}&status=archived&limit=1")
        assert res.status_code == 200
        data = res.json()
        
        if data["drafts"]:
            archived_draft = data["drafts"][0]["po_draft_id"]
            payload = {"status": "submitted", "notes": "Testing archived draft"}
            res = requests.post(
                f"{BASE_URL}/api/inventory-ledger/po-drafts/{archived_draft}/submission-log",
                json=payload
            )
            assert res.status_code == 422, f"Expected 422 for archived draft, got {res.status_code}"
            assert "archived" in res.text.lower()
            print(f"SUCCESS: Returns 422 for archived draft {archived_draft}")
        else:
            pytest.skip("No archived drafts available for testing")
    
    def test_post_submission_log_rejects_draft_without_vendor(self):
        """POST /submission-log returns 422 for draft without vendor assigned"""
        # Find a draft without vendor (or create a new one for test)
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}&status=draft&limit=50")
        assert res.status_code == 200
        data = res.json()
        
        draft_without_vendor = None
        for d in data["drafts"]:
            if not d.get("vendor_id") or not d.get("vendor_name"):
                draft_without_vendor = d["po_draft_id"]
                break
        
        if draft_without_vendor:
            payload = {"status": "submitted", "notes": "Testing draft without vendor"}
            res = requests.post(
                f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_without_vendor}/submission-log",
                json=payload
            )
            assert res.status_code == 422, f"Expected 422 for draft without vendor, got {res.status_code}: {res.text}"
            assert "vendor" in res.text.lower()
            print(f"SUCCESS: Returns 422 for draft without vendor: {draft_without_vendor}")
        else:
            pytest.skip("No draft without vendor available for testing")
    
    def test_post_submission_log_returns_404_for_nonexistent_draft(self):
        """POST /submission-log returns 404 for nonexistent draft"""
        payload = {"status": "submitted", "notes": "Testing nonexistent draft"}
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/NONEXISTENT-DRAFT-123/submission-log",
            json=payload
        )
        assert res.status_code == 404, f"Expected 404, got {res.status_code}"
        print("SUCCESS: Returns 404 for nonexistent draft")


class TestBCExportAutoLog:
    """Test that BC export auto-creates 'exported' submission log entry"""
    
    def test_bc_export_creates_auto_log_entry(self):
        """GET bc-export should auto-create submission log with status='exported'"""
        # First get current log count for the draft
        logs_before = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log").json()
        count_before = logs_before["total"]
        
        # Trigger BC export
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-export")
        assert res.status_code == 200, f"BC export failed: {res.text}"
        
        # Verify new log entry was created
        logs_after = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log").json()
        count_after = logs_after["total"]
        
        assert count_after > count_before, f"Expected new log entry, count before: {count_before}, after: {count_after}"
        
        # Verify the latest entry is 'exported' status
        latest_entry = logs_after["entries"][0]  # First entry (newest)
        assert latest_entry["status"] == "exported", f"Expected 'exported' status, got: {latest_entry['status']}"
        assert "Auto-logged" in latest_entry.get("notes", "") or latest_entry.get("notes", "") == "Auto-logged on BC payload export"
        print(f"SUCCESS: BC export auto-created 'exported' log entry with submission_id: {latest_entry['submission_id']}")
    
    def test_bc_export_auto_log_has_payload_snapshot(self):
        """BC export auto-log should include bc_payload_snapshot"""
        # Trigger BC export
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-export")
        assert res.status_code == 200
        
        # Get latest log entry
        logs = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log").json()
        latest = logs["entries"][0]
        
        assert "bc_payload_snapshot" in latest
        snapshot = latest["bc_payload_snapshot"]
        
        # Validate snapshot structure matches BC export payload
        assert snapshot.get("poDraftId") == DRAFT_WITH_VENDOR
        assert "vendor" in snapshot
        assert "vendorId" in snapshot["vendor"]
        assert "vendorName" in snapshot["vendor"]
        assert "documentDate" in snapshot
        assert "lines" in snapshot
        print(f"SUCCESS: bc_payload_snapshot matches BC export structure with {len(snapshot['lines'])} lines")


class TestPODraftsListEnrichment:
    """Test that PO Drafts list includes latest_submission_status"""
    
    def test_po_drafts_list_includes_latest_submission_status(self):
        """GET /po-drafts should return latest_submission_status per draft"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}")
        assert res.status_code == 200
        
        data = res.json()
        drafts = data["drafts"]
        assert len(drafts) > 0
        
        # Find a draft that has submission logs
        drafts_with_status = [d for d in drafts if d.get("latest_submission_status")]
        
        if drafts_with_status:
            d = drafts_with_status[0]
            assert d["latest_submission_status"] in ["exported", "submitted", "acknowledged", "failed"]
            assert "latest_submission_at" in d or d.get("latest_submission_at") is not None
            print(f"SUCCESS: Draft {d['po_draft_id']} has latest_submission_status: {d['latest_submission_status']}")
        else:
            # This might happen if no drafts have been exported/logged yet
            print("INFO: No drafts with latest_submission_status found - may need to run BC export first")
    
    def test_latest_submission_status_reflects_most_recent(self):
        """latest_submission_status should reflect the most recent log entry"""
        # Create a new log entry with known status
        payload = {"status": "acknowledged", "notes": "Test for latest status verification"}
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log",
            json=payload
        )
        assert res.status_code == 200
        
        # Check the drafts list
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}")
        assert res.status_code == 200
        
        data = res.json()
        target_draft = next((d for d in data["drafts"] if d["po_draft_id"] == DRAFT_WITH_VENDOR), None)
        
        assert target_draft is not None
        assert target_draft.get("latest_submission_status") == "acknowledged", f"Expected 'acknowledged', got: {target_draft.get('latest_submission_status')}"
        print(f"SUCCESS: latest_submission_status correctly reflects 'acknowledged'")


class TestSubmissionLogPayloadSnapshot:
    """Test bc_payload_snapshot structure and content"""
    
    def test_snapshot_structure_matches_bc_export(self):
        """bc_payload_snapshot should match the BC export payload structure"""
        # Create a log entry
        payload = {"status": "submitted", "notes": "Snapshot structure test"}
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/submission-log",
            json=payload
        )
        assert res.status_code == 200
        
        data = res.json()
        snapshot = data["bc_payload_snapshot"]
        
        # Expected BC payload structure
        assert snapshot["poDraftId"] == DRAFT_WITH_VENDOR
        assert "vendor" in snapshot
        assert "vendorId" in snapshot["vendor"]
        assert "vendorName" in snapshot["vendor"]
        assert "documentDate" in snapshot
        # documentDate should be YYYY-MM-DD format
        assert len(snapshot["documentDate"]) == 10, f"documentDate format wrong: {snapshot['documentDate']}"
        assert snapshot["source"] == "GPI_Hub_PO_Draft"
        assert "lines" in snapshot
        assert isinstance(snapshot["lines"], list)
        
        # Validate line structure
        if snapshot["lines"]:
            line = snapshot["lines"][0]
            assert "itemNumber" in line
            assert "quantity" in line
            assert "sourceReference" in line
        
        print(f"SUCCESS: bc_payload_snapshot has correct BC structure")


class TestRegressionTests:
    """Regression tests to ensure existing functionality still works"""
    
    def test_po_drafts_list_endpoint_works(self):
        """PO Drafts list endpoint should still work"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}")
        assert res.status_code == 200
        data = res.json()
        assert "total" in data
        assert "drafts" in data
        print(f"SUCCESS: PO Drafts list returns {data['total']} drafts")
    
    def test_po_draft_detail_endpoint_works(self):
        """PO Draft detail endpoint should still work"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}")
        assert res.status_code == 200
        data = res.json()
        assert data["po_draft_id"] == DRAFT_WITH_VENDOR
        assert "lines" in data
        print(f"SUCCESS: PO Draft detail returns draft with {len(data['lines'])} lines")
    
    def test_vendor_assignment_still_works(self):
        """Vendor assignment endpoint should still work"""
        res = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/vendor",
            json={"vendor_id": "V10045", "vendor_name": "Acme Bottle Supply"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["vendor_id"] == "V10045"
        print("SUCCESS: Vendor assignment still works")
    
    def test_bc_export_still_works(self):
        """BC export endpoint should still work"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/bc-export")
        assert res.status_code == 200
        # Check Content-Disposition header
        assert "attachment" in res.headers.get("content-disposition", "")
        print("SUCCESS: BC export still works")
    
    def test_create_incoming_supply_still_works(self):
        """Create incoming supply endpoint should still work (without actually creating)"""
        # This draft has already been converted, so it should return 409
        res = requests.post(f"{BASE_URL}/api/inventory-ledger/po-drafts/{DRAFT_WITH_VENDOR}/create-incoming-supply")
        # Either 200 (success) or 409 (already converted) is acceptable
        assert res.status_code in [200, 409], f"Expected 200 or 409, got {res.status_code}"
        print(f"SUCCESS: Create incoming supply endpoint works (status: {res.status_code})")
    
    def test_balances_endpoint_works(self):
        """Balances endpoint should still work"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{CUSTOMER_ID}/balances")
        assert res.status_code == 200
        data = res.json()
        assert "balances" in data
        print(f"SUCCESS: Balances endpoint returns {len(data['balances'])} items")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
