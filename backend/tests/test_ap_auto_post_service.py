"""
Test AP Auto-Post Service - Strict Binary Workflow

Tests the new strict AP invoice workflow:
1. check_ap_ready_to_post() returns ready=True only when ALL 4 conditions are met
2. check_ap_ready_to_post() returns ready=False with correct failure reasons
3. server.py routes AP_Invoice through ap_auto_post_service (not old auto_clear)
4. auto-clear block SKIPS AP_Invoice documents
5. mark-ready endpoint calls ap_auto_post_service
6. reprocess pipeline routes AP_Invoice through ap_auto_post_service
"""

import pytest
import requests
import os
import sys

# Add backend to path for direct imports
sys.path.insert(0, '/app/backend')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://invoice-trace.preview.emergentagent.com').rstrip('/')


class TestHealthEndpoint:
    """Basic health check"""
    
    def test_health_returns_200(self):
        """GET /api/health returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print("PASS: /api/health returns 200 with status=healthy")


class TestCheckApReadyToPost:
    """Unit tests for check_ap_ready_to_post function"""
    
    def test_all_conditions_met_returns_ready_true(self):
        """When all 4 conditions are met, ready=True"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "AP_Invoice",
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc"
            },
            "bc_vendor_number": "V00123",
            "vendor_match_method": "exact",
            "validation_results": {
                "checks": [
                    {"check_name": "po_validation", "passed": True}
                ]
            }
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        assert ready is True, f"Expected ready=True but got {ready}. Reason: {reason}, Failures: {failures}"
        assert len(failures) == 0, f"Expected no failures but got: {failures}"
        print(f"PASS: All conditions met → ready=True, reason='{reason}'")
    
    def test_missing_invoice_number_returns_ready_false(self):
        """Missing invoice number → ready=False"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "AP_Invoice",
            "extracted_fields": {
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc"
            },
            "bc_vendor_number": "V00123",
            "validation_results": {
                "checks": [{"check_name": "po_validation", "passed": True}]
            }
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        assert ready is False, f"Expected ready=False but got {ready}"
        assert "Missing invoice number" in failures, f"Expected 'Missing invoice number' in failures: {failures}"
        print(f"PASS: Missing invoice number → ready=False, failures={failures}")
    
    def test_missing_amount_returns_ready_false(self):
        """Missing amount → ready=False"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "AP_Invoice",
            "extracted_fields": {
                "invoice_number": "INV-001",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc"
            },
            "bc_vendor_number": "V00123",
            "validation_results": {
                "checks": [{"check_name": "po_validation", "passed": True}]
            }
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        assert ready is False, f"Expected ready=False but got {ready}"
        assert "Missing amount" in failures, f"Expected 'Missing amount' in failures: {failures}"
        print(f"PASS: Missing amount → ready=False, failures={failures}")
    
    def test_missing_invoice_date_returns_ready_false(self):
        """Missing invoice date → ready=False"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "AP_Invoice",
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "vendor": "Test Vendor Inc"
            },
            "bc_vendor_number": "V00123",
            "validation_results": {
                "checks": [{"check_name": "po_validation", "passed": True}]
            }
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        assert ready is False, f"Expected ready=False but got {ready}"
        assert "Missing invoice date" in failures, f"Expected 'Missing invoice date' in failures: {failures}"
        print(f"PASS: Missing invoice date → ready=False, failures={failures}")
    
    def test_missing_vendor_returns_ready_false(self):
        """Missing vendor name → ready=False"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "AP_Invoice",
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15"
            },
            "bc_vendor_number": "V00123",
            "validation_results": {
                "checks": [{"check_name": "po_validation", "passed": True}]
            }
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        assert ready is False, f"Expected ready=False but got {ready}"
        assert "Missing vendor name from extraction" in failures, f"Expected 'Missing vendor name' in failures: {failures}"
        print(f"PASS: Missing vendor → ready=False, failures={failures}")
    
    def test_vendor_not_resolved_returns_ready_false(self):
        """Vendor not resolved to BC vendor number → ready=False"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "AP_Invoice",
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc"
            },
            # No bc_vendor_number
            "validation_results": {
                "checks": [{"check_name": "po_validation", "passed": True}]
            }
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        assert ready is False, f"Expected ready=False but got {ready}"
        assert "Vendor not resolved to BC vendor number" in failures, f"Expected vendor resolution failure: {failures}"
        print(f"PASS: Vendor not resolved → ready=False, failures={failures}")
    
    def test_po_extracted_but_not_matched_returns_ready_false(self):
        """PO extracted but not matched in BC → ready=False"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "AP_Invoice",
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
                    {"check_name": "po_validation", "passed": False}  # But not matched
                ]
            }
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        assert ready is False, f"Expected ready=False but got {ready}"
        assert "PO extracted but not found/matched in BC" in failures, f"Expected PO match failure: {failures}"
        print(f"PASS: PO not matched → ready=False, failures={failures}")
    
    def test_no_po_extracted_is_acceptable(self):
        """No PO extracted (legitimately no PO) → ready=True if other conditions met"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "AP_Invoice",
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc"
                # No po_number - legitimately no PO
            },
            "bc_vendor_number": "V00123",
            "validation_results": {
                "checks": []  # No PO validation check
            }
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        assert ready is True, f"Expected ready=True (no PO is acceptable) but got {ready}. Failures: {failures}"
        print(f"PASS: No PO extracted (acceptable) → ready=True")
    
    def test_wrong_doc_type_returns_ready_false(self):
        """Non-AP_Invoice doc type → ready=False"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "Sales_Order",  # Wrong type
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc"
            },
            "bc_vendor_number": "V00123",
            "validation_results": {
                "checks": [{"check_name": "po_validation", "passed": True}]
            }
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        assert ready is False, f"Expected ready=False for wrong doc type but got {ready}"
        assert "Not classified as AP_Invoice" in failures, f"Expected classification failure: {failures}"
        print(f"PASS: Wrong doc type → ready=False, failures={failures}")
    
    def test_multiple_failures_all_reported(self):
        """Multiple failures should all be reported"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "Other",  # Wrong type
            "extracted_fields": {},  # Missing all fields
            # No bc_vendor_number
            "validation_results": {}
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        assert ready is False
        assert len(failures) >= 4, f"Expected at least 4 failures but got {len(failures)}: {failures}"
        print(f"PASS: Multiple failures all reported: {failures}")


class TestMarkReadyEndpoint:
    """Test POST /api/ap-review/documents/{doc_id}/mark-ready endpoint"""
    
    def test_mark_ready_returns_404_for_missing_doc(self):
        """mark-ready returns 404 for non-existent document"""
        response = requests.post(f"{BASE_URL}/api/ap-review/documents/nonexistent-doc-id/mark-ready")
        assert response.status_code == 404, f"Expected 404 but got {response.status_code}"
        print("PASS: mark-ready returns 404 for missing document")
    
    def test_mark_ready_returns_404_for_uuid_format(self):
        """mark-ready returns 404 for valid UUID format but non-existent doc"""
        import uuid
        fake_uuid = str(uuid.uuid4())
        response = requests.post(f"{BASE_URL}/api/ap-review/documents/{fake_uuid}/mark-ready")
        assert response.status_code == 404, f"Expected 404 but got {response.status_code}"
        print(f"PASS: mark-ready returns 404 for non-existent UUID {fake_uuid[:8]}...")


class TestPostToBCEndpoint:
    """Test POST /api/ap-review/documents/{doc_id}/post-to-bc endpoint"""
    
    def test_post_to_bc_returns_404_for_missing_doc(self):
        """post-to-bc returns 404 for non-existent document"""
        response = requests.post(f"{BASE_URL}/api/ap-review/documents/nonexistent-doc-id/post-to-bc")
        assert response.status_code == 404, f"Expected 404 but got {response.status_code}"
        print("PASS: post-to-bc returns 404 for missing document")


class TestCodePathVerification:
    """Verify code paths are correctly wired"""
    
    def test_server_imports_ap_auto_post_service(self):
        """Verify server.py imports ap_auto_post_service"""
        with open('/app/backend/server.py', 'r') as f:
            content = f.read()
        
        assert 'from services.ap_auto_post_service import attempt_ap_auto_post' in content, \
            "server.py should import attempt_ap_auto_post from ap_auto_post_service"
        print("PASS: server.py imports ap_auto_post_service.attempt_ap_auto_post")
    
    def test_server_skips_auto_clear_for_ap_invoice(self):
        """Verify server.py skips auto-clear for AP_Invoice"""
        with open('/app/backend/server.py', 'r') as f:
            content = f.read()
        
        # Check for the skip logic
        assert 'is_ap_invoice = suggested_type in ("AP_Invoice", "AP Invoice")' in content, \
            "server.py should check for AP_Invoice type"
        assert 'SKIPPED for AP_Invoice' in content, \
            "server.py should log skip message for AP_Invoice"
        print("PASS: server.py skips auto-clear for AP_Invoice documents")
    
    def test_ap_review_router_calls_ap_auto_post_service(self):
        """Verify ap_review.py mark-ready calls ap_auto_post_service"""
        with open('/app/backend/routers/ap_review.py', 'r') as f:
            content = f.read()
        
        assert 'from services.ap_auto_post_service import attempt_ap_auto_post' in content, \
            "ap_review.py should import attempt_ap_auto_post"
        assert 'await attempt_ap_auto_post(doc_id, db, source="mark_ready")' in content, \
            "ap_review.py mark-ready should call attempt_ap_auto_post with source='mark_ready'"
        print("PASS: ap_review.py mark-ready calls ap_auto_post_service")
    
    def test_document_handlers_routes_ap_through_auto_post(self):
        """Verify document_handlers.py reprocess routes AP through ap_auto_post_service"""
        with open('/app/backend/services/document_handlers.py', 'r') as f:
            content = f.read()
        
        assert 'from services.ap_auto_post_service import attempt_ap_auto_post' in content, \
            "document_handlers.py should import attempt_ap_auto_post"
        assert 'AP_INVOICE' in content.upper() or 'ap_invoice' in content.lower(), \
            "document_handlers.py should handle AP_Invoice type"
        print("PASS: document_handlers.py reprocess routes AP through ap_auto_post_service")


class TestAPMetricsEndpoint:
    """Test AP metrics endpoint"""
    
    def test_ap_metrics_returns_200(self):
        """GET /api/dashboard/ap-metrics returns 200"""
        response = requests.get(f"{BASE_URL}/api/dashboard/ap-metrics")
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
        data = response.json()
        # Verify structure
        assert "total_ap" in data, "Response should have total_ap field"
        assert "posted_to_bc" in data, "Response should have posted_to_bc field"
        assert "pending_review" in data, "Response should have pending_review field"
        print(f"PASS: /api/dashboard/ap-metrics returns 200 with data: {data}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
