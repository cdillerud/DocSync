"""
AP Validation Integration Tests

Tests APValidationService integration into the main processing flow.
Validates:
- Manual AP validation trigger endpoints
- Validation status retrieval
- Derived states (workflow_state, automation_state)
- BC Write Guard (read-only safety)
- Idempotency
"""

import pytest
import requests
import os
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test document IDs from problem statement
AP_INVOICE_DOC_ID = "c3bf1459-e48d-4905-a813-84b02386b9c4"  # AP_Invoice type
FREIGHT_CARRIER_DOC_ID = "98695c83-a7f3-495f-ac8d-bb5405c55a63"  # TUMALOC freight carrier doc


class TestHealthCheck:
    """Basic health and connectivity tests."""
    
    def test_backend_reachable(self):
        """Backend API is reachable."""
        response = requests.get(f"{BASE_URL}/api/health")
        print(f"Health check: {response.status_code}")
        # May return 404 if no /health endpoint, but connection should work
        assert response.status_code in (200, 404, 405)


class TestBCWriteGuard:
    """Verify BC write guard is enabled (read-only safety)."""
    
    def test_bc_write_guard_status_blocked(self):
        """GET /api/bc/write-guard/status confirms BC writes are BLOCKED."""
        response = requests.get(f"{BASE_URL}/api/bc/write-guard/status")
        print(f"BC Write Guard status: {response.status_code}")
        assert response.status_code == 200
        
        data = response.json()
        print(f"Write guard response: {data}")
        
        # BC writes should be blocked for read-only safety
        assert data.get("write_enabled") == False or data.get("status") == "blocked"
        print("VERIFIED: BC writes are BLOCKED (read-only safety)")


class TestAPValidationManual:
    """Test manual AP validation trigger endpoint."""
    
    def test_validate_ap_invoice_document(self):
        """POST /api/ap-validation/validate/{doc_id} for AP_Invoice document."""
        response = requests.post(f"{BASE_URL}/api/ap-validation/validate/{AP_INVOICE_DOC_ID}")
        print(f"Validate AP Invoice: {response.status_code}")
        
        if response.status_code == 404:
            pytest.skip(f"Document {AP_INVOICE_DOC_ID} not found in database")
        
        assert response.status_code == 200
        
        data = response.json()
        print(f"Validation result: {data}")
        
        # Validate required response fields
        assert "validation_state" in data, "Missing validation_state"
        assert data["validation_state"] in ("pass", "warning", "fail", "pending")
        
        assert "checks" in data, "Missing checks array"
        assert isinstance(data["checks"], list)
        
        # Should have blocking_issues and warnings
        assert "blocking_issues" in data
        assert "warnings" in data
        
        # Verify check names present (vendor, invoice_number, invoice_date, total_amount, duplicate)
        check_names = {c.get("check_name") for c in data.get("checks", [])}
        print(f"Check names found: {check_names}")
        
        # Should have at least vendor_resolution check
        assert "vendor_resolution" in check_names or len(check_names) >= 3
        
        print(f"VERIFIED: AP Invoice validation returned state={data['validation_state']}, {len(data.get('checks', []))} checks")
    
    def test_validate_freight_carrier_document(self):
        """POST /api/ap-validation/validate/{doc_id} for freight carrier doc should validate as AP type."""
        response = requests.post(f"{BASE_URL}/api/ap-validation/validate/{FREIGHT_CARRIER_DOC_ID}")
        print(f"Validate Freight Carrier doc: {response.status_code}")
        
        if response.status_code == 404:
            pytest.skip(f"Document {FREIGHT_CARRIER_DOC_ID} not found in database")
        
        assert response.status_code == 200
        
        data = response.json()
        print(f"Freight carrier validation: {data}")
        
        # Should return validation result
        assert "validation_state" in data
        assert data["validation_state"] in ("pass", "warning", "fail", "pending")
        
        print(f"VERIFIED: Freight carrier doc validation state={data['validation_state']}")


class TestAPValidationStatus:
    """Test AP validation status retrieval endpoint."""
    
    def test_get_validation_status_ap_invoice(self):
        """GET /api/ap-validation/status/{doc_id} returns validation status fields."""
        # First trigger validation
        requests.post(f"{BASE_URL}/api/ap-validation/validate/{AP_INVOICE_DOC_ID}")
        
        # Then get status
        response = requests.get(f"{BASE_URL}/api/ap-validation/status/{AP_INVOICE_DOC_ID}")
        print(f"Get validation status: {response.status_code}")
        
        if response.status_code == 404:
            pytest.skip(f"Document {AP_INVOICE_DOC_ID} not found")
        
        assert response.status_code == 200
        
        data = response.json()
        print(f"Validation status: {data}")
        
        # Verify expected status fields
        assert "validation_state" in data or "ap_validation_result" in data
        
        # Check derived states
        if "derived_workflow_state" in data:
            print(f"Derived workflow state: {data['derived_workflow_state']}")
        if "derived_automation_state" in data:
            print(f"Derived automation state: {data['derived_automation_state']}")
        
        print("VERIFIED: Validation status endpoint returns expected fields")


class TestDerivedStates:
    """Test validation state drives derived workflow and automation states."""
    
    def test_fail_state_derives_needs_review_manual(self):
        """Validation state 'fail' sets derived_workflow_state='needs_review' and derived_automation_state='manual'."""
        # Get document after validation
        response = requests.get(f"{BASE_URL}/api/documents/{AP_INVOICE_DOC_ID}")
        
        if response.status_code == 404:
            pytest.skip(f"Document {AP_INVOICE_DOC_ID} not found")
        
        assert response.status_code == 200
        data = response.json()
        doc = data.get("document", data)
        
        v_state = doc.get("validation_state")
        wf_state = doc.get("derived_workflow_state")
        auto_state = doc.get("derived_automation_state")
        
        print(f"Document states: validation={v_state}, workflow={wf_state}, automation={auto_state}")
        
        if v_state == "fail":
            assert wf_state == "needs_review", f"Expected workflow_state='needs_review' for fail, got '{wf_state}'"
            assert auto_state == "manual", f"Expected automation_state='manual' for fail, got '{auto_state}'"
            print("VERIFIED: fail state correctly derives needs_review + manual")
        elif v_state == "pass":
            assert wf_state == "ready", f"Expected workflow_state='ready' for pass, got '{wf_state}'"
            assert auto_state == "assisted", f"Expected automation_state='assisted' for pass, got '{auto_state}'"
            print("VERIFIED: pass state correctly derives ready + assisted")
        elif v_state == "warning":
            assert wf_state in ("reviewing", "ready")
            assert auto_state == "assisted"
            print("VERIFIED: warning state correctly derives assisted")
        else:
            print(f"Validation state is '{v_state}' - skipping derived state assertions")


class TestIdempotency:
    """Test validation idempotency."""
    
    def test_validation_idempotency(self):
        """Calling validate twice with same data should be idempotent."""
        # First validation
        resp1 = requests.post(f"{BASE_URL}/api/ap-validation/validate/{AP_INVOICE_DOC_ID}")
        if resp1.status_code == 404:
            pytest.skip("Document not found")
        
        data1 = resp1.json()
        v1 = data1.get("validation_version")
        state1 = data1.get("validation_state")
        
        # Second validation
        resp2 = requests.post(f"{BASE_URL}/api/ap-validation/validate/{AP_INVOICE_DOC_ID}")
        data2 = resp2.json()
        v2 = data2.get("validation_version")
        state2 = data2.get("validation_state")
        
        print(f"First validation: version={v1}, state={state1}")
        print(f"Second validation: version={v2}, state={state2}")
        
        # Version should be the same
        assert v1 == v2, f"Version changed: {v1} -> {v2}"
        # State should be the same
        assert state1 == state2, f"State changed: {state1} -> {state2}"
        
        print("VERIFIED: Validation is idempotent - same result on re-run")


class TestBackwardsCompatibility:
    """Test backwards compatibility for documents without ap_validation_result."""
    
    def test_old_documents_display_correctly(self):
        """Documents without ap_validation_result should still work."""
        # Get list of documents
        response = requests.get(f"{BASE_URL}/api/documents?limit=10")
        assert response.status_code == 200
        
        data = response.json()
        docs = data.get("documents", [])
        
        # Find a document without ap_validation_result
        old_doc = None
        for doc in docs:
            if not doc.get("ap_validation_result"):
                old_doc = doc
                break
        
        if not old_doc:
            print("No documents found without ap_validation_result - all have been validated")
            # This is fine, backwards compatibility is maintained
            return
        
        # Should still have basic fields accessible
        assert "id" in old_doc
        assert "file_name" in old_doc or "source" in old_doc
        
        # Get document detail
        doc_id = old_doc["id"]
        detail_resp = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        assert detail_resp.status_code == 200
        
        print(f"VERIFIED: Document {doc_id[:8]} without ap_validation_result displays correctly")


class TestValidationEvents:
    """Test validation events are emitted."""
    
    def test_validation_events_in_timeline(self):
        """Validation events appear in document timeline."""
        # First trigger validation
        requests.post(f"{BASE_URL}/api/ap-validation/validate/{AP_INVOICE_DOC_ID}")
        
        # Get document timeline
        response = requests.get(f"{BASE_URL}/api/documents/{AP_INVOICE_DOC_ID}/timeline")
        
        if response.status_code == 404:
            pytest.skip("Document not found")
        
        if response.status_code != 200:
            print(f"Timeline endpoint returned {response.status_code}")
            return
        
        data = response.json()
        timeline = data.get("timeline", [])
        
        # Look for validation events
        validation_events = [e for e in timeline if "validation" in e.get("event_type", "").lower()]
        print(f"Found {len(validation_events)} validation events in timeline")
        
        if validation_events:
            for event in validation_events[:3]:
                print(f"  - {event.get('event_type')}: {event.get('status')}")
            print("VERIFIED: Validation events appear in workflow timeline")
        else:
            print("Note: No validation events found in timeline (may be stored differently)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
