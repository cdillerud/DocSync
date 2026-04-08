"""
Iteration 194: Test missing_required_fields fix

KEY CHANGES BEING TESTED:
1. evaluate_readiness: Broadened required_fields check to look at vendor_canonical, 
   bc_vendor_number, normalized_fields, external_document_no (Lines 157-190)
2. evaluate_readiness: Downgraded missing_required_fields from blocking to warning 
   when vendor is resolved (Lines 270-285)
3. check_ap_ready_to_post: Broadened field lookup for invoice_no (+ external_document_no), 
   amount (+ invoice_amount, total_amount from nf), vendor_raw (+ vendor_canonical) (Lines 59-62)

TEST SCENARIOS:
- AP_Invoice with bc_vendor_number='TUMALOC' but no invoice_number/amount in extracted_fields 
  → should be ready_auto_draft with missing_required_fields as WARNING
- No vendor anywhere → should be blocked
- BOL doc_type with vendor but no amount/inv# → should be ready_auto_draft
- check_ap_ready_to_post: vendor_canonical set but ef.vendor empty → should NOT fail on 'Missing vendor name'
- check_ap_ready_to_post: external_document_no set → should NOT fail on 'Missing invoice number'
"""

import pytest
import requests
import os
import sys

# Add backend to path for direct imports
sys.path.insert(0, '/app/backend')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestEvaluateReadinessDirectImport:
    """Test evaluate_readiness function directly with mock documents"""
    
    def test_ap_invoice_with_bc_vendor_number_but_missing_fields_gets_ready_auto_draft(self):
        """
        Scenario: AP_Invoice with bc_vendor_number='TUMALOC' but no invoice_number/amount in extracted_fields
        Expected: should be ready_auto_draft with missing_required_fields as WARNING (not blocking)
        """
        from services.document_readiness_service import evaluate_readiness
        
        # Mock document: vendor resolved via bc_vendor_number, but missing invoice_number and amount
        doc = {
            "id": "test-doc-tumaloc-001",
            "doc_type": "AP_Invoice",
            "document_type": "AP_Invoice",
            "suggested_job_type": "AP_Invoice",
            "bc_vendor_number": "TUMALOC",  # Vendor IS resolved
            "vendor_canonical": "TUMALOC LOGISTICS",
            "vendor_resolution": {"status": "resolved", "vendor_no": "TUMALOC"},
            "extracted_fields": {
                # NO vendor, invoice_number, or amount in extracted_fields
                "invoice_date": "2024-01-15",
            },
            "normalized_fields": {},
            "validation_results": {},
            "ai_confidence": 0.85,
        }
        
        result = evaluate_readiness(doc)
        
        print(f"Status: {result['status']}")
        print(f"Blocking reasons: {result['blocking_reasons']}")
        print(f"Warning reasons: {result['warning_reasons']}")
        print(f"Signals: {result['signals']}")
        
        # CRITICAL ASSERTION: Should be ready_auto_draft, NOT blocked
        assert result["status"] == "ready_auto_draft", f"Expected ready_auto_draft but got {result['status']}"
        
        # missing_required_fields should be in warnings, NOT in blocking
        assert "missing_required_fields" not in result["blocking_reasons"], \
            "missing_required_fields should NOT be blocking when vendor is resolved"
        assert "missing_required_fields" in result["warning_reasons"], \
            "missing_required_fields should be a WARNING when vendor is resolved"
        
        # vendor_resolved signal should be True
        assert result["signals"]["vendor_resolved"] is True, "vendor_resolved signal should be True"
        
        print("PASS: AP_Invoice with bc_vendor_number but missing fields gets ready_auto_draft")
    
    def test_document_with_no_vendor_anywhere_gets_blocked(self):
        """
        Scenario: Document with NO vendor at all
        Expected: should be blocked with vendor_unresolved and missing_required_fields
        """
        from services.document_readiness_service import evaluate_readiness
        
        # Mock document: NO vendor anywhere
        doc = {
            "id": "test-doc-no-vendor-001",
            "doc_type": "AP_Invoice",
            "document_type": "AP_Invoice",
            "suggested_job_type": "AP_Invoice",
            # NO bc_vendor_number, vendor_canonical, vendor_resolution
            "extracted_fields": {
                "invoice_number": "INV-12345",
                "amount": "1500.00",
                "invoice_date": "2024-01-15",
                # NO vendor in extracted_fields either
            },
            "normalized_fields": {},
            "validation_results": {},
            "ai_confidence": 0.85,
        }
        
        result = evaluate_readiness(doc)
        
        print(f"Status: {result['status']}")
        print(f"Blocking reasons: {result['blocking_reasons']}")
        print(f"Warning reasons: {result['warning_reasons']}")
        print(f"Signals: {result['signals']}")
        
        # CRITICAL ASSERTION: Should be blocked
        assert result["status"] == "blocked", f"Expected blocked but got {result['status']}"
        
        # vendor_unresolved should be in blocking reasons
        assert "vendor_unresolved" in result["blocking_reasons"], \
            "vendor_unresolved should be in blocking_reasons"
        
        # missing_required_fields should also be blocking (since vendor is missing)
        assert "missing_required_fields" in result["blocking_reasons"], \
            "missing_required_fields should be blocking when vendor is missing"
        
        # vendor_resolved signal should be False
        assert result["signals"]["vendor_resolved"] is False, "vendor_resolved signal should be False"
        
        print("PASS: Document with no vendor gets blocked")
    
    def test_bol_doc_type_with_vendor_but_no_amount_gets_ready_auto_draft(self):
        """
        Scenario: BOL doc_type with vendor resolved but no invoice_number/amount
        Expected: should be ready_auto_draft (BOL doesn't require invoice_number/amount)
        """
        from services.document_readiness_service import evaluate_readiness
        
        # Mock document: BOL with vendor but no invoice_number/amount
        doc = {
            "id": "test-doc-bol-001",
            "doc_type": "BOL",  # Bill of Lading - not an invoice type
            "document_type": "BOL",
            "suggested_job_type": "BOL",
            "bc_vendor_number": "CARGOMO",
            "vendor_canonical": "CARGOMO FREIGHT",
            "vendor_resolution": {"status": "resolved", "vendor_no": "CARGOMO"},
            "extracted_fields": {
                # NO invoice_number or amount - but that's OK for BOL
                "shipment_date": "2024-01-15",
                "tracking_number": "TRK-98765",
            },
            "normalized_fields": {},
            "validation_results": {},
            "ai_confidence": 0.80,
        }
        
        result = evaluate_readiness(doc)
        
        print(f"Status: {result['status']}")
        print(f"Blocking reasons: {result['blocking_reasons']}")
        print(f"Warning reasons: {result['warning_reasons']}")
        print(f"Signals: {result['signals']}")
        
        # CRITICAL ASSERTION: Should be ready_auto_draft (BOL doesn't need invoice_number/amount)
        assert result["status"] == "ready_auto_draft", f"Expected ready_auto_draft but got {result['status']}"
        
        # Should NOT be blocked
        assert len(result["blocking_reasons"]) == 0, \
            f"BOL should not have blocking reasons, got: {result['blocking_reasons']}"
        
        # vendor_resolved signal should be True
        assert result["signals"]["vendor_resolved"] is True, "vendor_resolved signal should be True"
        
        # required_fields_complete should be True for BOL (only needs vendor)
        assert result["signals"]["required_fields_complete"] is True, \
            "required_fields_complete should be True for BOL with vendor"
        
        print("PASS: BOL doc_type with vendor but no amount gets ready_auto_draft")
    
    def test_vendor_resolved_via_vendor_canonical_only(self):
        """
        Scenario: Vendor resolved via vendor_canonical but not bc_vendor_number
        Expected: should recognize vendor as resolved
        """
        from services.document_readiness_service import evaluate_readiness
        
        doc = {
            "id": "test-doc-canonical-001",
            "doc_type": "AP_Invoice",
            "document_type": "AP_Invoice",
            "vendor_canonical": "ROTONDO SHIPPING",  # Only vendor_canonical set
            # NO bc_vendor_number
            "extracted_fields": {
                "invoice_number": "INV-99999",
                "amount": "2500.00",
                "invoice_date": "2024-01-15",
            },
            "normalized_fields": {},
            "validation_results": {},
            "ai_confidence": 0.85,
        }
        
        result = evaluate_readiness(doc)
        
        print(f"Status: {result['status']}")
        print(f"Blocking reasons: {result['blocking_reasons']}")
        print(f"Signals: {result['signals']}")
        
        # vendor_resolved should be True (vendor_canonical is set)
        assert result["signals"]["vendor_resolved"] is True, \
            "vendor_resolved should be True when vendor_canonical is set"
        
        print("PASS: Vendor resolved via vendor_canonical only")
    
    def test_vendor_resolved_via_unified_vendor_match(self):
        """
        Scenario: Vendor resolved via unified_vendor_match.bc_vendor_no
        Expected: should recognize vendor as present for required_fields check
        """
        from services.document_readiness_service import evaluate_readiness
        
        doc = {
            "id": "test-doc-unified-001",
            "doc_type": "AP_Invoice",
            "document_type": "AP_Invoice",
            "unified_vendor_match": {"bc_vendor_no": "TUMALOC"},  # Vendor via unified match
            "vendor_resolution": {"status": "resolved", "vendor_no": "TUMALOC"},
            "extracted_fields": {
                "invoice_number": "INV-88888",
                "amount": "3500.00",
                "invoice_date": "2024-01-15",
            },
            "normalized_fields": {},
            "validation_results": {},
            "ai_confidence": 0.85,
        }
        
        result = evaluate_readiness(doc)
        
        print(f"Status: {result['status']}")
        print(f"Blocking reasons: {result['blocking_reasons']}")
        print(f"Signals: {result['signals']}")
        
        # Should be ready_auto_draft with all fields complete
        assert result["status"] == "ready_auto_draft", f"Expected ready_auto_draft but got {result['status']}"
        assert result["signals"]["required_fields_complete"] is True
        
        print("PASS: Vendor resolved via unified_vendor_match")


class TestCheckApReadyToPostDirectImport:
    """Test check_ap_ready_to_post function directly"""
    
    def test_vendor_canonical_used_when_extracted_vendor_empty(self):
        """
        Scenario: vendor_canonical set but ef.vendor empty
        Expected: should NOT fail on 'Missing vendor name from extraction'
        """
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "id": "test-ap-vendor-canonical-001",
            "doc_type": "AP_Invoice",
            "document_type": "AP_Invoice",
            "suggested_job_type": "AP_Invoice",
            "vendor_canonical": "TUMALOC LOGISTICS",  # vendor_canonical set
            "bc_vendor_number": "TUMALOC",
            "extracted_fields": {
                # NO vendor in extracted_fields
                "invoice_number": "INV-12345",
                "amount": "1500.00",
                "invoice_date": "2024-01-15",
            },
            "normalized_fields": {},
            "validation_results": {},
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        
        print(f"Ready: {ready}")
        print(f"Reason: {reason}")
        print(f"Failures: {failures}")
        
        # Should NOT have "Missing vendor name from extraction" in failures
        assert "Missing vendor name from extraction" not in failures, \
            f"Should not fail on vendor when vendor_canonical is set. Failures: {failures}"
        
        print("PASS: vendor_canonical used when extracted vendor empty")
    
    def test_external_document_no_used_for_invoice_number(self):
        """
        Scenario: external_document_no set but ef.invoice_number empty
        Expected: should NOT fail on 'Missing invoice number'
        """
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "id": "test-ap-external-doc-001",
            "doc_type": "AP_Invoice",
            "document_type": "AP_Invoice",
            "suggested_job_type": "AP_Invoice",
            "external_document_no": "EXT-DOC-99999",  # external_document_no set
            "vendor_canonical": "CARGOMO FREIGHT",
            "bc_vendor_number": "CARGOMO",
            "extracted_fields": {
                # NO invoice_number in extracted_fields
                "vendor": "CARGOMO",
                "amount": "2500.00",
                "invoice_date": "2024-01-15",
            },
            "normalized_fields": {},
            "validation_results": {},
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        
        print(f"Ready: {ready}")
        print(f"Reason: {reason}")
        print(f"Failures: {failures}")
        
        # Should NOT have "Missing invoice number" in failures
        assert "Missing invoice number" not in failures, \
            f"Should not fail on invoice_number when external_document_no is set. Failures: {failures}"
        
        print("PASS: external_document_no used for invoice number")
    
    def test_normalized_fields_amount_used(self):
        """
        Scenario: amount in normalized_fields but not in extracted_fields
        Expected: should NOT fail on 'Missing amount'
        """
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "id": "test-ap-nf-amount-001",
            "doc_type": "AP_Invoice",
            "document_type": "AP_Invoice",
            "suggested_job_type": "AP_Invoice",
            "vendor_canonical": "ROTONDO SHIPPING",
            "bc_vendor_number": "ROTONDO",
            "extracted_fields": {
                "vendor": "ROTONDO",
                "invoice_number": "INV-77777",
                "invoice_date": "2024-01-15",
                # NO amount in extracted_fields
            },
            "normalized_fields": {
                "total_amount": "4500.00",  # Amount in normalized_fields
            },
            "validation_results": {},
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        
        print(f"Ready: {ready}")
        print(f"Reason: {reason}")
        print(f"Failures: {failures}")
        
        # Should NOT have "Missing amount" in failures
        assert "Missing amount" not in failures, \
            f"Should not fail on amount when normalized_fields.total_amount is set. Failures: {failures}"
        
        print("PASS: normalized_fields amount used")


class TestReadinessAPIEndpoints:
    """Test the readiness API endpoints"""
    
    def test_get_readiness_metrics(self):
        """GET /api/readiness/metrics returns valid response"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics", timeout=30)
        
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json() if response.status_code == 200 else response.text}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Check required fields
        assert "total_documents" in data, "Missing total_documents"
        assert "by_status" in data, "Missing by_status"
        assert "by_action" in data, "Missing by_action"
        
        print("PASS: GET /api/readiness/metrics returns valid response")
    
    def test_get_automation_rate(self):
        """GET /api/readiness/automation-rate returns valid response"""
        response = requests.get(f"{BASE_URL}/api/readiness/automation-rate", timeout=30)
        
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json() if response.status_code == 200 else response.text}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Check required fields
        assert "automation_rate" in data, "Missing automation_rate"
        assert "total_documents" in data, "Missing total_documents"
        
        print("PASS: GET /api/readiness/automation-rate returns valid response")
    
    def test_post_reevaluate_all(self):
        """POST /api/readiness/reevaluate-all works without errors"""
        response = requests.post(
            f"{BASE_URL}/api/readiness/reevaluate-all",
            json={"limit": 10},  # Small limit for testing
            timeout=60
        )
        
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json() if response.status_code == 200 else response.text}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Check required fields
        assert "total_processed" in data, "Missing total_processed"
        assert "by_status" in data, "Missing by_status"
        
        print("PASS: POST /api/readiness/reevaluate-all works without errors")


class TestMissingRequiredFieldsWarningVsBlocking:
    """Test the specific behavior of missing_required_fields as warning vs blocking"""
    
    def test_missing_fields_warning_when_vendor_resolved(self):
        """
        When vendor IS resolved but invoice_number/amount missing:
        - missing_required_fields should be WARNING (not blocking)
        - Status should be ready_auto_draft
        """
        from services.document_readiness_service import evaluate_readiness
        
        doc = {
            "id": "test-warning-001",
            "doc_type": "AP_Invoice",
            "document_type": "AP_Invoice",
            "bc_vendor_number": "TUMALOC",
            "vendor_canonical": "TUMALOC LOGISTICS",
            "vendor_resolution": {"status": "resolved"},
            "extracted_fields": {
                # Missing invoice_number and amount
                "invoice_date": "2024-01-15",
            },
            "normalized_fields": {},
            "validation_results": {},
            "ai_confidence": 0.85,
        }
        
        result = evaluate_readiness(doc)
        
        print(f"Status: {result['status']}")
        print(f"Blocking: {result['blocking_reasons']}")
        print(f"Warnings: {result['warning_reasons']}")
        
        # Key assertions
        assert result["status"] == "ready_auto_draft", \
            f"Should be ready_auto_draft when vendor resolved, got {result['status']}"
        assert "missing_required_fields" in result["warning_reasons"], \
            "missing_required_fields should be in warnings"
        assert "missing_required_fields" not in result["blocking_reasons"], \
            "missing_required_fields should NOT be in blocking"
        
        print("PASS: missing_required_fields is WARNING when vendor resolved")
    
    def test_missing_fields_blocking_when_vendor_not_resolved(self):
        """
        When vendor is NOT resolved and other fields missing:
        - missing_required_fields should be BLOCKING
        - Status should be blocked
        """
        from services.document_readiness_service import evaluate_readiness
        
        doc = {
            "id": "test-blocking-001",
            "doc_type": "AP_Invoice",
            "document_type": "AP_Invoice",
            # NO vendor anywhere
            "extracted_fields": {
                # Missing vendor, invoice_number, and amount
                "invoice_date": "2024-01-15",
            },
            "normalized_fields": {},
            "validation_results": {},
            "ai_confidence": 0.85,
        }
        
        result = evaluate_readiness(doc)
        
        print(f"Status: {result['status']}")
        print(f"Blocking: {result['blocking_reasons']}")
        print(f"Warnings: {result['warning_reasons']}")
        
        # Key assertions
        assert result["status"] == "blocked", \
            f"Should be blocked when vendor not resolved, got {result['status']}"
        assert "missing_required_fields" in result["blocking_reasons"], \
            "missing_required_fields should be in blocking when vendor missing"
        assert "vendor_unresolved" in result["blocking_reasons"], \
            "vendor_unresolved should be in blocking"
        
        print("PASS: missing_required_fields is BLOCKING when vendor not resolved")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
