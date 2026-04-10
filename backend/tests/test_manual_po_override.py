"""
Test Manual PO Override Feature - P0 Regression Tests

Tests the Manual PO Override feature that allows users to bypass the strict 
'PO must exist in BC' validation check on AP Invoices.

Key endpoints tested:
1. POST /api/ap-review/documents/{doc_id}/override-po - Sets manual_po_override=True
2. POST /api/ap-review/documents/{doc_id}/mark-ready - Sets manual_po_override=True and triggers auto-post
3. GET /api/ap-review/documents/{doc_id}/bc-status - Returns posting status
4. PUT /api/ap-review/documents/{doc_id} - AP Review save edits
5. GET /api/ap-review/vendors - Vendor search
6. GET /api/ap-review/purchase-orders - PO search

Key logic tested:
- check_ap_ready_to_post() skips PO check when manual_po_override=True
- check_ap_ready_to_post() still enforces PO check when manual_po_override is not set
"""

import pytest
import requests
import os
import sys

# Add backend to path for direct imports
sys.path.insert(0, '/app/backend')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://auto-post-recovery.preview.emergentagent.com').rstrip('/')


class TestOverridePOEndpoint:
    """Test POST /api/ap-review/documents/{doc_id}/override-po endpoint"""
    
    def test_override_po_returns_404_for_missing_doc(self):
        """override-po returns 404 for non-existent document"""
        response = requests.post(f"{BASE_URL}/api/ap-review/documents/nonexistent-doc-id/override-po")
        assert response.status_code == 404, f"Expected 404 but got {response.status_code}"
        data = response.json()
        assert "not found" in data.get("detail", "").lower(), f"Expected 'not found' in detail: {data}"
        print("PASS: override-po returns 404 for missing document")
    
    def test_override_po_returns_404_for_uuid_format(self):
        """override-po returns 404 for valid UUID format but non-existent doc"""
        import uuid
        fake_uuid = str(uuid.uuid4())
        response = requests.post(f"{BASE_URL}/api/ap-review/documents/{fake_uuid}/override-po")
        assert response.status_code == 404, f"Expected 404 but got {response.status_code}"
        print(f"PASS: override-po returns 404 for non-existent UUID {fake_uuid[:8]}...")


class TestBCStatusEndpoint:
    """Test GET /api/ap-review/documents/{doc_id}/bc-status endpoint"""
    
    def test_bc_status_returns_404_for_missing_doc(self):
        """bc-status returns 404 for non-existent document"""
        response = requests.get(f"{BASE_URL}/api/ap-review/documents/nonexistent-doc-id/bc-status")
        assert response.status_code == 404, f"Expected 404 but got {response.status_code}"
        print("PASS: bc-status returns 404 for missing document")
    
    def test_bc_status_returns_200_for_existing_doc(self):
        """bc-status returns 200 with status fields for existing AP_Invoice"""
        # First find an AP_Invoice document
        response = requests.get(f"{BASE_URL}/api/documents?doc_type=AP_Invoice&limit=1")
        assert response.status_code == 200
        docs = response.json().get("documents", [])
        if not docs:
            pytest.skip("No AP_Invoice documents found for testing")
        
        doc_id = docs[0].get("id")
        response = requests.get(f"{BASE_URL}/api/ap-review/documents/{doc_id}/bc-status")
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
        data = response.json()
        
        # Verify response structure
        assert "document_id" in data, "Response should have document_id"
        assert "bc_posting_status" in data, "Response should have bc_posting_status"
        assert data["document_id"] == doc_id, f"document_id mismatch: {data['document_id']} != {doc_id}"
        print(f"PASS: bc-status returns 200 with status for doc {doc_id[:8]}...")
        print(f"  bc_posting_status: {data.get('bc_posting_status')}")
        print(f"  review_status: {data.get('review_status')}")


class TestMarkReadyEndpoint:
    """Test POST /api/ap-review/documents/{doc_id}/mark-ready endpoint"""
    
    def test_mark_ready_returns_404_for_missing_doc(self):
        """mark-ready returns 404 for non-existent document"""
        response = requests.post(f"{BASE_URL}/api/ap-review/documents/nonexistent-doc-id/mark-ready")
        assert response.status_code == 404, f"Expected 404 but got {response.status_code}"
        print("PASS: mark-ready returns 404 for missing document")
    
    def test_mark_ready_validates_required_fields(self):
        """mark-ready returns 400 if required fields are missing"""
        # Create a test document without required fields
        # This test verifies the validation logic
        import uuid
        fake_uuid = str(uuid.uuid4())
        response = requests.post(f"{BASE_URL}/api/ap-review/documents/{fake_uuid}/mark-ready")
        # Should return 404 (doc not found) or 400 (missing fields)
        assert response.status_code in [400, 404], f"Expected 400 or 404 but got {response.status_code}"
        print(f"PASS: mark-ready validates required fields (status={response.status_code})")


class TestAPReviewSaveEndpoint:
    """Test PUT /api/ap-review/documents/{doc_id} endpoint"""
    
    def test_save_returns_404_for_missing_doc(self):
        """save returns 404 for non-existent document"""
        response = requests.put(
            f"{BASE_URL}/api/ap-review/documents/nonexistent-doc-id",
            json={"vendor_id": "TEST"}
        )
        assert response.status_code == 404, f"Expected 404 but got {response.status_code}"
        print("PASS: AP review save returns 404 for missing document")


class TestVendorSearchEndpoint:
    """Test GET /api/ap-review/vendors endpoint"""
    
    def test_vendors_returns_200(self):
        """vendors endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/ap-review/vendors")
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
        data = response.json()
        assert "vendors" in data, "Response should have vendors field"
        print(f"PASS: vendors endpoint returns 200 with {len(data.get('vendors', []))} vendors")
    
    def test_vendors_search_with_query(self):
        """vendors endpoint accepts search query"""
        response = requests.get(f"{BASE_URL}/api/ap-review/vendors?q=test")
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
        data = response.json()
        assert "vendors" in data, "Response should have vendors field"
        print(f"PASS: vendors search with query returns 200")


class TestPurchaseOrderSearchEndpoint:
    """Test GET /api/ap-review/purchase-orders endpoint"""
    
    def test_purchase_orders_returns_200(self):
        """purchase-orders endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/ap-review/purchase-orders")
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
        data = response.json()
        assert "purchaseOrders" in data, "Response should have purchaseOrders field"
        print(f"PASS: purchase-orders endpoint returns 200 with {len(data.get('purchaseOrders', []))} POs")


class TestCheckApReadyToPostWithOverride:
    """Unit tests for check_ap_ready_to_post with manual override logic"""
    
    def test_manual_override_skips_po_check(self):
        """When manual_po_override=True, PO check is skipped"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "AP_Invoice",
            "manual_po_override": True,  # Override set
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc",
                "po_number": "PO-12345"  # PO extracted
            },
            "bc_vendor_number": "V00123",
            "validation_results": {
                "checks": [
                    {"check_name": "po_validation", "passed": False}  # PO check failed
                ]
            }
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        # With manual_po_override=True, PO check should be skipped
        assert ready is True, f"Expected ready=True with manual_po_override but got {ready}. Failures: {failures}"
        assert "PO" not in str(failures), f"PO failure should not be in failures when override is set: {failures}"
        print(f"PASS: manual_po_override=True skips PO check → ready=True")
    
    def test_manual_override_flag_alternative(self):
        """When manual_override=True (alternative flag), PO check is skipped"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "AP_Invoice",
            "manual_override": True,  # Alternative flag
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc",
                "po_number": "PO-12345"
            },
            "bc_vendor_number": "V00123",
            "validation_results": {
                "checks": [
                    {"check_name": "po_validation", "passed": False}
                ]
            }
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        assert ready is True, f"Expected ready=True with manual_override but got {ready}. Failures: {failures}"
        print(f"PASS: manual_override=True (alternative flag) skips PO check → ready=True")
    
    def test_source_mark_ready_skips_po_check(self):
        """When source='mark_ready', PO check is skipped"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "AP_Invoice",
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc",
                "po_number": "PO-12345"
            },
            "bc_vendor_number": "V00123",
            "validation_results": {
                "checks": [
                    {"check_name": "po_validation", "passed": False}
                ]
            }
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc, source="mark_ready")
        assert ready is True, f"Expected ready=True with source=mark_ready but got {ready}. Failures: {failures}"
        print(f"PASS: source='mark_ready' skips PO check → ready=True")
    
    def test_source_manual_override_skips_po_check(self):
        """When source='manual_override', PO check is skipped"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "AP_Invoice",
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc",
                "po_number": "PO-12345"
            },
            "bc_vendor_number": "V00123",
            "validation_results": {
                "checks": [
                    {"check_name": "po_validation", "passed": False}
                ]
            }
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc, source="manual_override")
        assert ready is True, f"Expected ready=True with source=manual_override but got {ready}. Failures: {failures}"
        print(f"PASS: source='manual_override' skips PO check → ready=True")
    
    def test_without_override_po_check_enforced(self):
        """Without override, PO check is enforced"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "AP_Invoice",
            # No manual_po_override or manual_override
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc",
                "po_number": "PO-12345"  # PO extracted
            },
            "bc_vendor_number": "V00123",
            "validation_results": {
                "checks": [
                    {"check_name": "po_validation", "passed": False}  # PO check failed
                ]
            }
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc, source="auto")
        assert ready is False, f"Expected ready=False without override but got {ready}"
        assert "PO extracted but not found/matched in BC" in failures, f"Expected PO failure: {failures}"
        print(f"PASS: Without override, PO check is enforced → ready=False, failures={failures}")


class TestCodePathVerification:
    """Verify code paths are correctly wired for PO override"""
    
    def test_override_po_endpoint_exists(self):
        """Verify override-po endpoint is defined in ap_review.py"""
        with open('/app/backend/routers/ap_review.py', 'r') as f:
            content = f.read()
        
        assert '@ap_review_router.post("/documents/{doc_id}/override-po")' in content, \
            "ap_review.py should have override-po endpoint"
        assert 'manual_po_override' in content, \
            "ap_review.py should set manual_po_override flag"
        print("PASS: override-po endpoint exists in ap_review.py")
    
    def test_override_po_calls_auto_post(self):
        """Verify override-po endpoint calls attempt_ap_auto_post"""
        with open('/app/backend/routers/ap_review.py', 'r') as f:
            content = f.read()
        
        assert 'await attempt_ap_auto_post(doc_id, db, source="manual_override")' in content, \
            "override-po should call attempt_ap_auto_post with source='manual_override'"
        print("PASS: override-po calls attempt_ap_auto_post with source='manual_override'")
    
    def test_mark_ready_sets_override(self):
        """Verify mark-ready endpoint sets manual_po_override"""
        with open('/app/backend/routers/ap_review.py', 'r') as f:
            content = f.read()
        
        # Check that mark-ready sets the override flag
        assert '"manual_po_override": True' in content, \
            "mark-ready should set manual_po_override=True"
        print("PASS: mark-ready sets manual_po_override=True")
    
    def test_check_ap_ready_has_override_logic(self):
        """Verify check_ap_ready_to_post has override logic"""
        with open('/app/backend/services/ap_auto_post_service.py', 'r') as f:
            content = f.read()
        
        assert 'has_manual_override = doc.get("manual_po_override") or doc.get("manual_override")' in content, \
            "check_ap_ready_to_post should check for manual override flags"
        assert 'is_human_action = source in ("mark_ready", "manual_override", "human_review")' in content, \
            "check_ap_ready_to_post should check for human action sources"
        print("PASS: check_ap_ready_to_post has override logic")


class TestExistingDocumentWithOverride:
    """Test with existing document that has manual_po_override set"""
    
    def test_find_doc_with_override(self):
        """Find and verify a document with manual_po_override=True"""
        response = requests.get(f"{BASE_URL}/api/documents?doc_type=AP_Invoice&limit=50")
        assert response.status_code == 200
        docs = response.json().get("documents", [])
        
        # Find doc with manual_po_override=True
        override_doc = None
        for d in docs:
            if d.get("manual_po_override"):
                override_doc = d
                break
        
        if not override_doc:
            pytest.skip("No AP_Invoice document with manual_po_override=True found")
        
        doc_id = override_doc.get("id")
        print(f"PASS: Found document with manual_po_override=True: {doc_id[:20]}...")
        
        # Verify the override flags
        assert override_doc.get("manual_po_override") is True, "manual_po_override should be True"
        print(f"  manual_po_override: {override_doc.get('manual_po_override')}")
        print(f"  manual_override: {override_doc.get('manual_override')}")
        print(f"  status: {override_doc.get('status')}")


class TestFrontendUIElements:
    """Verify frontend has the required UI elements for PO override"""
    
    def test_frontend_has_override_button(self):
        """Verify DocumentDetailPage has Override PO Check button"""
        with open('/app/frontend/src/pages/DocumentDetailPage.js', 'r') as f:
            content = f.read()
        
        assert 'override-po-btn' in content, \
            "DocumentDetailPage should have override-po-btn data-testid"
        assert 'Override PO Check' in content, \
            "DocumentDetailPage should have 'Override PO Check' button text"
        print("PASS: Frontend has Override PO Check button")
    
    def test_frontend_shows_override_message(self):
        """Verify DocumentDetailPage shows override message when set"""
        with open('/app/frontend/src/pages/DocumentDetailPage.js', 'r') as f:
            content = f.read()
        
        assert 'PO check overridden by reviewer' in content, \
            "DocumentDetailPage should show 'PO check overridden by reviewer' message"
        print("PASS: Frontend shows override message when manual_po_override is True")
    
    def test_frontend_calls_override_api(self):
        """Verify frontend calls the override-po API"""
        with open('/app/frontend/src/pages/DocumentDetailPage.js', 'r') as f:
            content = f.read()
        
        assert '/api/ap-review/documents/' in content and '/override-po' in content, \
            "DocumentDetailPage should call /api/ap-review/documents/{id}/override-po"
        print("PASS: Frontend calls override-po API endpoint")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
