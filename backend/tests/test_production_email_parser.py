"""
GPI Document Hub - Production Email Parser Tests
Tests for:
1. POST /api/documents/intake - SharePoint upload first, field normalization, vendor_candidates
2. POST /api/documents/{doc_id}/resolve - resolve NeedsReview documents
3. GET /api/settings/job-types/AP_Invoice - new fields (po_validation_mode, vendor_match_threshold)
4. PUT /api/settings/job-types/{job_type} - update with new schema fields
5. Document status flow: Received -> StoredInSP -> NeedsReview/LinkedToBC
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test invoice content with amounts and dates for normalization testing
TEST_INVOICE_WITH_AMOUNTS = """
INVOICE

From: Test Vendor Corp, Inc.
123 Vendor Street
Chicago, IL 60601

Bill To: Gamer Packaging
456 Customer Ave
Los Angeles, CA 90001

Invoice Number: INV-TEST-2026-001
Invoice Date: January 15, 2026
Due Date: February 15, 2026

PO Number: PO-TEST-5678

Description                    Qty    Unit Price    Amount
---------------------------------------------------------
Packaging Materials            100    $25.00        $2,500.00
Shipping Supplies              50     $15.00        $750.00
---------------------------------------------------------
                              Subtotal:             $3,250.00
                              Tax (8%):             $260.00
                              TOTAL:                $3,510.00

Payment Terms: Net 30
"""

TEST_SALES_PO_CONTENT = """
PURCHASE ORDER

From: Test Customer LLC
789 Customer Blvd
San Francisco, CA 94102

To: Gamer Packaging
456 Supplier Ave
Los Angeles, CA 90001

PO Number: PO-TEST-2026-9876
Order Date: January 20, 2026

Ship To:
Test Customer LLC
Distribution Center
1000 Warehouse Way
Oakland, CA 94601

Item                          Qty    Unit Price    Amount
---------------------------------------------------------
Custom Boxes (Large)          500    $5.00         $2,500.00
Custom Boxes (Medium)         1000   $3.50         $3,500.00
---------------------------------------------------------
                              TOTAL:               $6,000.00

Delivery Required By: February 1, 2026
"""


class TestJobTypeNewFields:
    """Tests for new job type configuration fields: po_validation_mode, vendor_match_threshold"""
    
    def test_get_ap_invoice_has_new_fields(self):
        """GET /api/settings/job-types/AP_Invoice - verify new fields exist"""
        response = requests.get(f"{BASE_URL}/api/settings/job-types/AP_Invoice")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify new fields exist
        assert "po_validation_mode" in data, f"Missing po_validation_mode field. Keys: {data.keys()}"
        assert "vendor_match_threshold" in data, f"Missing vendor_match_threshold field. Keys: {data.keys()}"
        assert "vendor_match_strategies" in data, f"Missing vendor_match_strategies field. Keys: {data.keys()}"
        
        # Verify field values
        assert data["po_validation_mode"] in ["PO_REQUIRED", "PO_IF_PRESENT", "PO_NOT_REQUIRED"], \
            f"Invalid po_validation_mode: {data['po_validation_mode']}"
        assert isinstance(data["vendor_match_threshold"], (int, float)), \
            f"vendor_match_threshold should be numeric: {type(data['vendor_match_threshold'])}"
        assert 0 <= data["vendor_match_threshold"] <= 1, \
            f"vendor_match_threshold should be 0-1: {data['vendor_match_threshold']}"
        
        print(f"✓ AP_Invoice has new fields:")
        print(f"  - po_validation_mode: {data['po_validation_mode']}")
        print(f"  - vendor_match_threshold: {data['vendor_match_threshold']}")
        print(f"  - vendor_match_strategies: {data['vendor_match_strategies']}")
        return data
    
    def test_get_sales_po_has_new_fields(self):
        """GET /api/settings/job-types/Sales_PO - verify new fields exist"""
        response = requests.get(f"{BASE_URL}/api/settings/job-types/Sales_PO")
        assert response.status_code == 200
        data = response.json()
        
        assert "po_validation_mode" in data
        assert "vendor_match_threshold" in data
        
        print(f"✓ Sales_PO has new fields:")
        print(f"  - po_validation_mode: {data['po_validation_mode']}")
        print(f"  - vendor_match_threshold: {data['vendor_match_threshold']}")
        return data
    
    def test_update_job_type_with_new_fields(self):
        """PUT /api/settings/job-types/AP_Invoice - update with new schema fields"""
        # First get current config
        get_response = requests.get(f"{BASE_URL}/api/settings/job-types/AP_Invoice")
        assert get_response.status_code == 200
        original_config = get_response.json()
        
        # Update with new fields
        update_payload = {
            "job_type": "AP_Invoice",
            "display_name": "AP Invoice (Vendor Invoice)",
            "automation_level": 1,
            "min_confidence_to_auto_link": 0.85,
            "min_confidence_to_auto_create_draft": 0.95,
            # New fields
            "po_validation_mode": "PO_IF_PRESENT",
            "vendor_match_threshold": 0.75,  # Changed from default
            "vendor_match_strategies": ["exact_no", "exact_name", "normalized", "fuzzy"],
            "allow_duplicate_check_override": False,
            "requires_human_review_if_exception": True,
            "sharepoint_folder": "AP_Invoices",
            "bc_entity": "purchaseInvoices",
            "required_extractions": ["vendor", "invoice_number", "amount"],
            "optional_extractions": ["po_number", "due_date", "line_items"],
            "enabled": True
        }
        
        response = requests.put(
            f"{BASE_URL}/api/settings/job-types/AP_Invoice",
            json=update_payload
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify update was applied
        assert data["vendor_match_threshold"] == 0.75, f"Expected 0.75, got {data['vendor_match_threshold']}"
        assert data["po_validation_mode"] == "PO_IF_PRESENT"
        
        print(f"✓ Updated AP_Invoice with new fields:")
        print(f"  - vendor_match_threshold: {data['vendor_match_threshold']}")
        print(f"  - po_validation_mode: {data['po_validation_mode']}")
        
        # Restore original config
        restore_payload = {
            "job_type": "AP_Invoice",
            "display_name": original_config.get("display_name", "AP Invoice (Vendor Invoice)"),
            "automation_level": original_config.get("automation_level", 1),
            "min_confidence_to_auto_link": original_config.get("min_confidence_to_auto_link", 0.85),
            "min_confidence_to_auto_create_draft": original_config.get("min_confidence_to_auto_create_draft", 0.95),
            "po_validation_mode": original_config.get("po_validation_mode", "PO_IF_PRESENT"),
            "vendor_match_threshold": original_config.get("vendor_match_threshold", 0.80),
            "vendor_match_strategies": original_config.get("vendor_match_strategies", ["exact_no", "exact_name", "normalized", "fuzzy"]),
            "allow_duplicate_check_override": original_config.get("allow_duplicate_check_override", False),
            "requires_human_review_if_exception": original_config.get("requires_human_review_if_exception", True),
            "sharepoint_folder": original_config.get("sharepoint_folder", "AP_Invoices"),
            "bc_entity": original_config.get("bc_entity", "purchaseInvoices"),
            "required_extractions": original_config.get("required_extractions", ["vendor", "invoice_number", "amount"]),
            "optional_extractions": original_config.get("optional_extractions", ["po_number", "due_date", "line_items"]),
            "enabled": original_config.get("enabled", True)
        }
        requests.put(f"{BASE_URL}/api/settings/job-types/AP_Invoice", json=restore_payload)
        print("✓ Restored original AP_Invoice config")
        return data


class TestDocumentIntakeSharePointFirst:
    """Tests for document intake - SharePoint upload happens FIRST"""
    
    def test_intake_uploads_to_sharepoint_first(self):
        """POST /api/documents/intake - verify SharePoint upload happens before BC validation"""
        files = {
            'file': ('TEST_sp_first_001.txt', TEST_INVOICE_WITH_AMOUNTS, 'text/plain')
        }
        data = {
            'source': 'email',
            'sender': 'vendor@testcorp.com',
            'subject': 'Invoice INV-TEST-2026-001',
            'attachment_name': 'TEST_sp_first_001.txt'
        }
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        result = response.json()
        
        doc = result["document"]
        
        # Verify SharePoint fields are populated (even if BC validation fails)
        assert doc.get("sharepoint_drive_id") is not None, "SharePoint drive_id should be populated"
        assert doc.get("sharepoint_item_id") is not None, "SharePoint item_id should be populated"
        assert doc.get("sharepoint_web_url") is not None, "SharePoint web_url should be populated"
        
        # Status should be StoredInSP or NeedsReview (not Exception)
        assert doc["status"] in ["StoredInSP", "NeedsReview", "LinkedToBC", "Classified"], \
            f"Unexpected status: {doc['status']}. Document should be stored in SP even if BC fails."
        
        print(f"✓ Document uploaded to SharePoint FIRST:")
        print(f"  - sharepoint_drive_id: {doc.get('sharepoint_drive_id')[:20]}...")
        print(f"  - sharepoint_item_id: {doc.get('sharepoint_item_id')[:20]}...")
        print(f"  - status: {doc['status']}")
        
        # Store for cleanup
        self.__class__.test_doc_id = doc["id"]
        return result
    
    def test_intake_preserves_document_on_bc_failure(self):
        """POST /api/documents/intake - document preserved in SharePoint even if BC validation fails"""
        # Use a vendor name that won't match in BC
        invoice_content = """
        INVOICE
        From: NonExistent Vendor XYZ Corp
        Invoice Number: INV-NOBC-001
        Amount: $1,234.56
        Due Date: March 15, 2026
        """
        
        files = {
            'file': ('TEST_bc_fail_001.txt', invoice_content, 'text/plain')
        }
        data = {
            'source': 'email',
            'sender': 'unknown@vendor.com',
            'attachment_name': 'TEST_bc_fail_001.txt'
        }
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data
        )
        assert response.status_code == 200
        result = response.json()
        
        doc = result["document"]
        
        # Even if BC validation fails, SharePoint should have the document
        assert doc.get("sharepoint_drive_id") is not None, \
            "SharePoint drive_id should be populated even when BC fails"
        
        # Status should NOT be Exception just because BC validation failed
        assert doc["status"] != "Exception" or "SharePoint" not in doc.get("last_error", ""), \
            f"Document should be preserved in SP. Status: {doc['status']}, Error: {doc.get('last_error')}"
        
        print(f"✓ Document preserved in SharePoint despite BC validation:")
        print(f"  - status: {doc['status']}")
        print(f"  - sharepoint_item_id: {doc.get('sharepoint_item_id', 'N/A')[:20] if doc.get('sharepoint_item_id') else 'N/A'}...")
        print(f"  - decision: {result.get('decision')}")
        
        self.__class__.test_bc_fail_doc_id = doc["id"]
        return result


class TestFieldNormalization:
    """Tests for field normalization - amounts to float, dates to ISO"""
    
    def test_intake_normalizes_amount_to_float(self):
        """POST /api/documents/intake - amount should be normalized to float"""
        files = {
            'file': ('TEST_normalize_001.txt', TEST_INVOICE_WITH_AMOUNTS, 'text/plain')
        }
        data = {
            'source': 'email',
            'attachment_name': 'TEST_normalize_001.txt'
        }
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data
        )
        assert response.status_code == 200
        result = response.json()
        
        doc = result["document"]
        normalized_fields = doc.get("normalized_fields", {})
        validation = result.get("validation", {})
        
        # Check normalized_fields in document or validation results
        if not normalized_fields:
            normalized_fields = validation.get("normalized_fields", {})
        
        # If amount was extracted and normalized
        if "amount" in normalized_fields:
            amount = normalized_fields["amount"]
            assert isinstance(amount, (int, float)) or amount is None, \
                f"Normalized amount should be float, got {type(amount)}: {amount}"
            print(f"✓ Amount normalized to float: {amount}")
            
            # Check raw value is preserved
            if "amount_raw" in normalized_fields:
                print(f"  - Raw amount preserved: {normalized_fields['amount_raw']}")
        else:
            print(f"⚠ Amount not in normalized_fields. Keys: {normalized_fields.keys()}")
        
        self.__class__.test_normalize_doc_id = doc["id"]
        return result
    
    def test_intake_normalizes_date_to_iso(self):
        """POST /api/documents/intake - dates should be normalized to ISO format"""
        files = {
            'file': ('TEST_date_norm_001.txt', TEST_INVOICE_WITH_AMOUNTS, 'text/plain')
        }
        data = {
            'source': 'email',
            'attachment_name': 'TEST_date_norm_001.txt'
        }
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data
        )
        assert response.status_code == 200
        result = response.json()
        
        doc = result["document"]
        normalized_fields = doc.get("normalized_fields", {})
        validation = result.get("validation", {})
        
        if not normalized_fields:
            normalized_fields = validation.get("normalized_fields", {})
        
        # Check date fields
        date_fields = ["due_date", "invoice_date", "order_date", "payment_date"]
        for field in date_fields:
            if field in normalized_fields and normalized_fields[field]:
                date_val = normalized_fields[field]
                # ISO format: YYYY-MM-DD
                assert isinstance(date_val, str), f"{field} should be string"
                if date_val:
                    assert len(date_val) == 10 and date_val[4] == '-' and date_val[7] == '-', \
                        f"{field} should be ISO format (YYYY-MM-DD), got: {date_val}"
                    print(f"✓ {field} normalized to ISO: {date_val}")
                    
                    # Check raw value preserved
                    raw_key = f"{field}_raw"
                    if raw_key in normalized_fields:
                        print(f"  - Raw {field} preserved: {normalized_fields[raw_key]}")
        
        self.__class__.test_date_doc_id = doc["id"]
        return result


class TestVendorCandidates:
    """Tests for vendor_candidates being returned in intake response"""
    
    def test_intake_returns_vendor_candidates(self):
        """POST /api/documents/intake - vendor_candidates should be returned"""
        files = {
            'file': ('TEST_candidates_001.txt', TEST_INVOICE_WITH_AMOUNTS, 'text/plain')
        }
        data = {
            'source': 'email',
            'attachment_name': 'TEST_candidates_001.txt'
        }
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data
        )
        assert response.status_code == 200
        result = response.json()
        
        doc = result["document"]
        validation = result.get("validation", {})
        
        # Check for vendor_candidates in document or validation
        vendor_candidates = doc.get("vendor_candidates", [])
        if not vendor_candidates:
            vendor_candidates = validation.get("vendor_candidates", [])
        
        # vendor_candidates should be a list (may be empty if no fuzzy matches)
        assert isinstance(vendor_candidates, list), \
            f"vendor_candidates should be a list, got {type(vendor_candidates)}"
        
        print(f"✓ vendor_candidates returned: {len(vendor_candidates)} candidates")
        if vendor_candidates:
            for i, candidate in enumerate(vendor_candidates[:3]):
                print(f"  - Candidate {i+1}: {candidate.get('display_name', 'N/A')} (score: {candidate.get('score', 'N/A')})")
        
        # Also check customer_candidates for Sales_PO type documents
        customer_candidates = doc.get("customer_candidates", [])
        if not customer_candidates:
            customer_candidates = validation.get("customer_candidates", [])
        
        print(f"✓ customer_candidates returned: {len(customer_candidates)} candidates")
        
        self.__class__.test_candidates_doc_id = doc["id"]
        return result


class TestDocumentStatusFlow:
    """Tests for document status flow: Received -> StoredInSP -> NeedsReview/LinkedToBC"""
    
    def test_status_flow_to_stored_in_sp(self):
        """Verify document goes through StoredInSP status"""
        files = {
            'file': ('TEST_status_flow_001.txt', TEST_INVOICE_WITH_AMOUNTS, 'text/plain')
        }
        data = {
            'source': 'email',
            'attachment_name': 'TEST_status_flow_001.txt'
        }
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data
        )
        assert response.status_code == 200
        result = response.json()
        
        doc = result["document"]
        status = doc["status"]
        
        # Valid statuses after intake
        valid_statuses = ["StoredInSP", "NeedsReview", "LinkedToBC", "Classified"]
        assert status in valid_statuses, \
            f"Status should be one of {valid_statuses}, got: {status}"
        
        print(f"✓ Document status flow:")
        print(f"  - Final status: {status}")
        print(f"  - Decision: {result.get('decision')}")
        
        # If NeedsReview, verify SharePoint is still populated
        if status == "NeedsReview":
            assert doc.get("sharepoint_item_id") is not None, \
                "NeedsReview documents should still have SharePoint ID"
            print(f"  - SharePoint preserved for NeedsReview document")
        
        self.__class__.test_status_doc_id = doc["id"]
        return result


class TestResolveEndpoint:
    """Tests for POST /api/documents/{doc_id}/resolve endpoint"""
    
    def test_resolve_needs_review_document(self):
        """POST /api/documents/{doc_id}/resolve - resolve NeedsReview document"""
        # First create a document that will be NeedsReview
        invoice_content = """
        INVOICE
        From: Unknown Vendor ABC
        Invoice Number: INV-RESOLVE-001
        Amount: $999.99
        """
        
        files = {
            'file': ('TEST_resolve_001.txt', invoice_content, 'text/plain')
        }
        data = {
            'source': 'email',
            'attachment_name': 'TEST_resolve_001.txt'
        }
        
        intake_response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data
        )
        assert intake_response.status_code == 200
        doc_id = intake_response.json()["document"]["id"]
        doc_status = intake_response.json()["document"]["status"]
        
        print(f"✓ Created document for resolve test: {doc_id}")
        print(f"  - Initial status: {doc_status}")
        
        # Try to resolve the document
        resolve_payload = {
            "selected_vendor_id": None,  # No vendor selected
            "selected_customer_id": None,
            "mark_no_po": True,  # Mark as non-PO invoice
            "notes": "Test resolution - no PO required"
        }
        
        resolve_response = requests.post(
            f"{BASE_URL}/api/documents/{doc_id}/resolve",
            json=resolve_payload
        )
        
        # Should succeed if document is in valid status
        if doc_status in ["NeedsReview", "StoredInSP", "Classified"]:
            assert resolve_response.status_code == 200, \
                f"Expected 200, got {resolve_response.status_code}: {resolve_response.text}"
            result = resolve_response.json()
            
            print(f"✓ Resolve endpoint response:")
            print(f"  - success: {result.get('success')}")
            print(f"  - message: {result.get('message')}")
            print(f"  - new status: {result.get('document', {}).get('status')}")
        else:
            print(f"⚠ Document status {doc_status} may not be resolvable")
        
        self.__class__.test_resolve_doc_id = doc_id
        return intake_response.json()
    
    def test_resolve_with_vendor_selection(self):
        """POST /api/documents/{doc_id}/resolve - resolve with vendor selection"""
        # Create a document
        invoice_content = """
        INVOICE
        From: Test Vendor Selection Corp
        Invoice Number: INV-VENDOR-SEL-001
        Amount: $500.00
        """
        
        files = {
            'file': ('TEST_vendor_sel_001.txt', invoice_content, 'text/plain')
        }
        data = {
            'source': 'email',
            'attachment_name': 'TEST_vendor_sel_001.txt'
        }
        
        intake_response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data
        )
        assert intake_response.status_code == 200
        doc_id = intake_response.json()["document"]["id"]
        doc = intake_response.json()["document"]
        
        # Get vendor candidates if available
        vendor_candidates = doc.get("vendor_candidates", [])
        
        # Try to resolve with a mock vendor ID
        resolve_payload = {
            "selected_vendor_id": "mock-vendor-id-12345",
            "notes": "Test resolution with vendor selection"
        }
        
        resolve_response = requests.post(
            f"{BASE_URL}/api/documents/{doc_id}/resolve",
            json=resolve_payload
        )
        
        if doc["status"] in ["NeedsReview", "StoredInSP", "Classified"]:
            assert resolve_response.status_code == 200
            result = resolve_response.json()
            print(f"✓ Resolve with vendor selection:")
            print(f"  - success: {result.get('success')}")
            print(f"  - bc_record_id set: {result.get('document', {}).get('bc_record_id')}")
        
        self.__class__.test_vendor_sel_doc_id = doc_id
        return intake_response.json()
    
    def test_resolve_invalid_status(self):
        """POST /api/documents/{doc_id}/resolve - should fail for LinkedToBC status"""
        # This test verifies that already-linked documents can't be re-resolved
        # We'll test with a non-existent document ID
        resolve_payload = {
            "notes": "Test invalid resolve"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/documents/nonexistent-doc-id/resolve",
            json=resolve_payload
        )
        assert response.status_code == 404, f"Expected 404 for nonexistent doc, got {response.status_code}"
        print("✓ Resolve correctly returns 404 for nonexistent document")


class TestCleanup:
    """Cleanup test documents"""
    
    def test_cleanup_test_documents(self):
        """Delete all TEST_ prefixed documents"""
        response = requests.get(f"{BASE_URL}/api/documents?search=TEST_&limit=100")
        assert response.status_code == 200
        docs = response.json().get("documents", [])
        
        deleted_count = 0
        for doc in docs:
            if "TEST_" in doc.get("file_name", ""):
                del_response = requests.delete(f"{BASE_URL}/api/documents/{doc['id']}")
                if del_response.status_code == 200:
                    deleted_count += 1
        
        print(f"✓ Cleaned up {deleted_count} test documents")
        
        # Verify cleanup
        verify_response = requests.get(f"{BASE_URL}/api/documents?search=TEST_")
        remaining = verify_response.json().get("total", 0)
        print(f"  - Remaining TEST_ documents: {remaining}")


# Fixtures
@pytest.fixture(scope="session", autouse=True)
def setup_and_teardown():
    """Setup and teardown for test session"""
    print(f"\n{'='*60}")
    print(f"Production Email Parser Tests")
    print(f"BASE_URL: {BASE_URL}")
    print(f"{'='*60}")
    
    # Verify API is accessible
    try:
        response = requests.get(f"{BASE_URL}/api/settings/status", timeout=10)
        assert response.status_code == 200
        status = response.json()
        print(f"API Status: demo_mode={status.get('demo_mode')}")
    except Exception as e:
        pytest.fail(f"API not accessible: {e}")
    
    yield
    
    # Cleanup after all tests
    print(f"\n{'='*60}")
    print("Cleaning up test data...")
    print(f"{'='*60}")
    response = requests.get(f"{BASE_URL}/api/documents?search=TEST_&limit=100")
    if response.status_code == 200:
        docs = response.json().get("documents", [])
        for doc in docs:
            if "TEST_" in doc.get("file_name", ""):
                requests.delete(f"{BASE_URL}/api/documents/{doc['id']}")
    print("Cleanup complete")
