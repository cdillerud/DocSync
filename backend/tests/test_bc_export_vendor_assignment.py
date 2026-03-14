"""
Test BC Export and Vendor Assignment endpoints (iteration_76)

Tests for:
1. PATCH /api/inventory-ledger/po-drafts/{draft_id}/vendor - vendor assignment
2. GET /api/inventory-ledger/po-drafts/{draft_id}/bc-export - BC-compatible payload generation

Key validations:
- Vendor assignment updates draft with vendor_id and vendor_name
- BC export returns properly structured JSON payload
- BC export requires vendor assignment (422 if missing)
- BC export rejects archived drafts (422)
- BC export returns 404 for non-existent drafts
- BC export includes Content-Disposition header
"""

import pytest
import requests
import os
import json

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
CUSTOMER_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"  # Hormel Foods
EXISTING_DRAFT_WITH_VENDOR = "PO-DRAFT-20260314163256-689B67"  # Already has vendor V10045/Acme Bottle Supply


@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestVendorAssignment:
    """Tests for PATCH /api/inventory-ledger/po-drafts/{draft_id}/vendor endpoint"""

    def test_vendor_assignment_success(self, api_client):
        """Test successful vendor assignment to a PO draft"""
        # Use existing draft that has a vendor
        draft_id = EXISTING_DRAFT_WITH_VENDOR
        vendor_payload = {
            "vendor_id": "TEST-V-001",
            "vendor_name": "Test Vendor Inc"
        }
        
        response = api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/vendor",
            json=vendor_payload
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "po_draft_id" in data
        assert "vendor_id" in data
        assert "vendor_name" in data
        assert data["po_draft_id"] == draft_id
        assert data["vendor_id"] == "TEST-V-001"
        assert data["vendor_name"] == "Test Vendor Inc"
        
        # Restore original vendor
        restore_payload = {"vendor_id": "V10045", "vendor_name": "Acme Bottle Supply"}
        api_client.patch(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/vendor", json=restore_payload)

    def test_vendor_assignment_persists_on_draft(self, api_client):
        """Test that vendor assignment is persisted and visible in draft GET"""
        draft_id = EXISTING_DRAFT_WITH_VENDOR
        vendor_payload = {"vendor_id": "PERSIST-V-002", "vendor_name": "Persisted Vendor"}
        
        # Update vendor
        patch_response = api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/vendor",
            json=vendor_payload
        )
        assert patch_response.status_code == 200
        
        # GET draft to verify persistence
        get_response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}")
        assert get_response.status_code == 200
        draft_data = get_response.json()
        
        assert draft_data.get("vendor_id") == "PERSIST-V-002"
        assert draft_data.get("vendor_name") == "Persisted Vendor"
        
        # Restore original vendor
        restore_payload = {"vendor_id": "V10045", "vendor_name": "Acme Bottle Supply"}
        api_client.patch(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/vendor", json=restore_payload)

    def test_vendor_assignment_not_found(self, api_client):
        """Test vendor assignment to non-existent draft returns 404"""
        fake_draft_id = "PO-DRAFT-NONEXISTENT-999"
        vendor_payload = {"vendor_id": "V001", "vendor_name": "Some Vendor"}
        
        response = api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{fake_draft_id}/vendor",
            json=vendor_payload
        )
        
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data.get("detail", "").lower()

    def test_vendor_assignment_requires_vendor_id(self, api_client):
        """Test that vendor_id is required"""
        draft_id = EXISTING_DRAFT_WITH_VENDOR
        
        # Missing vendor_id
        response = api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/vendor",
            json={"vendor_name": "Only Name"}
        )
        
        assert response.status_code == 422  # Validation error

    def test_vendor_assignment_requires_vendor_name(self, api_client):
        """Test that vendor_name is required"""
        draft_id = EXISTING_DRAFT_WITH_VENDOR
        
        # Missing vendor_name
        response = api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/vendor",
            json={"vendor_id": "V001"}
        )
        
        assert response.status_code == 422  # Validation error


class TestBCExport:
    """Tests for GET /api/inventory-ledger/po-drafts/{draft_id}/bc-export endpoint"""

    def test_bc_export_success_with_vendor(self, api_client):
        """Test successful BC export when vendor is assigned"""
        draft_id = EXISTING_DRAFT_WITH_VENDOR
        
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/bc-export")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        # Check Content-Disposition header for download
        content_disp = response.headers.get("Content-Disposition", "")
        assert "attachment" in content_disp
        assert ".json" in content_disp
        
        # Parse and validate BC payload structure
        payload = response.json()
        
        # Required fields in BC payload
        assert "poDraftId" in payload
        assert "vendor" in payload
        assert "documentDate" in payload
        assert "source" in payload
        assert "lines" in payload
        
        # Vendor structure
        assert "vendorId" in payload["vendor"]
        assert "vendorName" in payload["vendor"]
        assert payload["vendor"]["vendorId"] != ""
        assert payload["vendor"]["vendorName"] != ""
        
        # Document date format (YYYY-MM-DD)
        doc_date = payload["documentDate"]
        assert len(doc_date) == 10
        assert doc_date[4] == "-" and doc_date[7] == "-"
        
        # Source identifier
        assert payload["source"] == "GPI_Hub_PO_Draft"
        
        # Lines validation
        assert isinstance(payload["lines"], list)
        assert len(payload["lines"]) > 0
        
        for line in payload["lines"]:
            assert "itemNumber" in line
            assert "quantity" in line
            assert "sourceReference" in line
            assert isinstance(line["quantity"], (int, float))
            assert line["quantity"] > 0

    def test_bc_export_document_date_format(self, api_client):
        """Test that BC export documentDate is in YYYY-MM-DD format"""
        draft_id = EXISTING_DRAFT_WITH_VENDOR
        
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/bc-export")
        assert response.status_code == 200
        
        payload = response.json()
        doc_date = payload.get("documentDate", "")
        
        # Validate format: YYYY-MM-DD
        import re
        date_pattern = r"^\d{4}-\d{2}-\d{2}$"
        assert re.match(date_pattern, doc_date), f"Document date '{doc_date}' does not match YYYY-MM-DD format"

    def test_bc_export_content_disposition_header(self, api_client):
        """Test that BC export returns Content-Disposition header for download"""
        draft_id = EXISTING_DRAFT_WITH_VENDOR
        
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/bc-export")
        assert response.status_code == 200
        
        content_disp = response.headers.get("Content-Disposition", "")
        assert "attachment" in content_disp
        assert f"BC-PO-{draft_id}.json" in content_disp

    def test_bc_export_missing_vendor_returns_422(self, api_client):
        """Test that BC export fails with 422 when vendor is not assigned"""
        # First, find or create a draft without vendor
        # List drafts and find one without vendor
        drafts_response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}")
        assert drafts_response.status_code == 200
        drafts = drafts_response.json().get("drafts", [])
        
        # Find a draft without vendor that is not archived
        draft_without_vendor = None
        for d in drafts:
            if not d.get("vendor_id") and d.get("status") != "archived":
                draft_without_vendor = d["po_draft_id"]
                break
        
        if draft_without_vendor:
            response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_without_vendor}/bc-export")
            assert response.status_code == 422
            data = response.json()
            assert "vendor" in data.get("detail", "").lower()
        else:
            # If no draft without vendor exists, test by temporarily removing vendor
            # from existing draft, then restore
            temp_draft_id = EXISTING_DRAFT_WITH_VENDOR
            
            # We can't remove vendor directly, so skip this test if no suitable draft found
            pytest.skip("No draft without vendor found for testing; all drafts have vendor assigned")

    def test_bc_export_archived_draft_returns_422(self, api_client):
        """Test that BC export fails with 422 for archived drafts"""
        # Find an archived draft
        drafts_response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}&status=archived")
        assert drafts_response.status_code == 200
        drafts = drafts_response.json().get("drafts", [])
        
        if not drafts:
            pytest.skip("No archived drafts found for testing")
        
        archived_draft = drafts[0]["po_draft_id"]
        
        # First assign vendor to make sure failure is due to archived status, not missing vendor
        api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{archived_draft}/vendor",
            json={"vendor_id": "V999", "vendor_name": "Archived Test Vendor"}
        )
        
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{archived_draft}/bc-export")
        assert response.status_code == 422
        data = response.json()
        assert "archived" in data.get("detail", "").lower()

    def test_bc_export_not_found(self, api_client):
        """Test that BC export returns 404 for non-existent drafts"""
        fake_draft_id = "PO-DRAFT-FAKE-404-TEST"
        
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{fake_draft_id}/bc-export")
        
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data.get("detail", "").lower()

    def test_bc_export_lines_structure(self, api_client):
        """Test that BC export lines contain correct fields"""
        draft_id = EXISTING_DRAFT_WITH_VENDOR
        
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/bc-export")
        assert response.status_code == 200
        
        payload = response.json()
        lines = payload.get("lines", [])
        
        assert len(lines) > 0, "Expected at least one line in BC export"
        
        for i, line in enumerate(lines):
            assert "itemNumber" in line, f"Line {i} missing itemNumber"
            assert "quantity" in line, f"Line {i} missing quantity"
            assert "sourceReference" in line, f"Line {i} missing sourceReference"
            
            # Validate data types
            assert isinstance(line["itemNumber"], str), f"Line {i} itemNumber should be string"
            assert isinstance(line["quantity"], (int, float)), f"Line {i} quantity should be numeric"
            assert line["quantity"] > 0, f"Line {i} quantity should be positive"


class TestRegressionChecks:
    """Regression tests to ensure existing functionality still works"""

    def test_po_draft_list_still_works(self, api_client):
        """Test PO drafts list endpoint still works"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}")
        
        assert response.status_code == 200
        data = response.json()
        assert "drafts" in data
        assert "total" in data
        assert isinstance(data["drafts"], list)

    def test_po_draft_detail_still_works(self, api_client):
        """Test PO draft detail endpoint still works"""
        draft_id = EXISTING_DRAFT_WITH_VENDOR
        
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["po_draft_id"] == draft_id
        assert "lines" in data
        assert "status" in data

    def test_po_draft_export_still_works(self, api_client):
        """Test PO draft JSON export endpoint still works"""
        draft_id = EXISTING_DRAFT_WITH_VENDOR
        
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/export")
        
        assert response.status_code == 200
        content_disp = response.headers.get("Content-Disposition", "")
        assert "attachment" in content_disp

    def test_create_incoming_supply_still_works(self, api_client):
        """Test create incoming supply button functionality still works"""
        # We just verify the endpoint exists and returns expected error for already-converted draft
        draft_id = EXISTING_DRAFT_WITH_VENDOR  # This draft has already had supply created
        
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/create-incoming-supply")
        
        # Should return 409 (already converted) which proves endpoint works
        assert response.status_code == 409
        data = response.json()
        assert "already" in data.get("detail", "").lower()

    def test_balances_endpoint_still_works(self, api_client):
        """Test balances endpoint still works"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{CUSTOMER_ID}/balances")
        
        assert response.status_code == 200
        data = response.json()
        assert "balances" in data

    def test_action_center_endpoint_still_works(self, api_client):
        """Test action center endpoint still works"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/action-center?customer_id={CUSTOMER_ID}")
        
        assert response.status_code == 200
        data = response.json()
        assert "actions" in data
        assert "action_summary" in data
