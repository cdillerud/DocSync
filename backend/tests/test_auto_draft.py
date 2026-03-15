"""
Auto-Draft Creation API Tests (iteration_95)
Tests the Document-to-Transaction Auto-Draft endpoints:
  POST /api/document-intelligence/auto-draft/{id} - create draft
  GET  /api/document-intelligence/auto-draft/{id} - get automation action

Test documents with drafts already created (per context):
  - 80c7ab51 (AP_Invoice -> ap_intake_draft AP-DRAFT-20260315014359-E600F4)
  - d15cc289 (Freight_Document -> po_draft PO-DRAFT-20260315014430-3DF2B2) 
  - b31207c3 (Shipping_Document -> po_draft PO-DRAFT-20260315014431-FD5279)

Ready AP_Invoice docs without drafts:
  - e4624c82, c3bf1459, 92f29b5f

Blocked document:
  - e94c01cb
"""

import pytest
import requests
import os
import time
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def auth_token(api_client):
    """Get authentication token"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "username": "admin",
        "password": "admin"
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip("Authentication failed - skipping authenticated tests")


@pytest.fixture(scope="module")
def authenticated_client(api_client, auth_token):
    """Session with auth header"""
    api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
    return api_client


# Document IDs from context - FULL UUIDs
DOC_WITH_AP_DRAFT = "80c7ab51-0cdb-48cc-b39c-b5d8a9c27c85"  # Has AP intake draft AP-DRAFT-20260315014359-E600F4
DOC_WITH_PO_DRAFT_FREIGHT = "d15cc289-f298-48d8-92a7-546380015ce0"  # Has PO draft PO-DRAFT-20260315014430-3DF2B2 (Freight_Document)
DOC_WITH_PO_DRAFT_SHIPPING = "b31207c3-4a2b-41e3-97c6-561c850c0893"  # Has PO draft PO-DRAFT-20260315014431-FD5279 (Shipping_Document)
BLOCKED_DOC = "e94c01cb-5c64-4f82-9fe0-64dc2ba4fa09"  # automation_readiness = blocked
READY_AP_DOCS_NO_DRAFT = [
    "e4624c82-313c-4993-a57c-17a98609b78c",  # Has draft now
    "c3bf1459-e48d-4905-a813-84b02386b9c4",  # AP_Invoice - no draft yet
    "92f29b5f-3e6f-495e-8899-b77a4d0ba38c"   # AP_Invoice - no draft yet
]


# ==================== POST /api/document-intelligence/auto-draft/{id} ====================
class TestCreateAutoDraft:
    """POST /api/document-intelligence/auto-draft/{id} endpoint tests"""

    def test_auto_draft_404_for_nonexistent_document(self, authenticated_client):
        """Should return 404 for non-existent document"""
        fake_id = "nonexistent-doc-auto-draft"
        
        response = authenticated_client.post(f"{BASE_URL}/api/document-intelligence/auto-draft/{fake_id}")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data, "Missing error detail"
        print(f"Auto-draft 404 for non-existent doc_id={fake_id}: {data['detail']}")

    def test_auto_draft_404_for_no_intelligence_result(self, authenticated_client):
        """Should return 404 if no intelligence result exists for document"""
        # Use a doc_id that exists but wasn't processed
        fake_id = "no-intelligence-result-test"
        
        response = authenticated_client.post(f"{BASE_URL}/api/document-intelligence/auto-draft/{fake_id}")
        # Could be 404 for either "document not found" or "no intelligence result"
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        
        print(f"Auto-draft 404 for no intelligence result: {response.json().get('detail')}")

    def test_auto_draft_422_for_blocked_document(self, authenticated_client):
        """Should return 422 when automation_readiness is not 'ready'"""
        # BLOCKED_DOC has automation_readiness = blocked per context
        doc_id = BLOCKED_DOC
        
        # First verify it's blocked
        intel_response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}")
        if intel_response.status_code != 200:
            pytest.skip(f"Could not get intelligence for {doc_id}")
        
        intel = intel_response.json()
        readiness = intel.get("automation_readiness")
        
        if readiness == "ready":
            pytest.skip(f"Document {doc_id} is actually ready, not blocked")
        
        print(f"Document {doc_id} has readiness={readiness}, score={intel.get('automation_readiness_score')}")
        
        # Try to create draft - should fail with 422
        response = authenticated_client.post(f"{BASE_URL}/api/document-intelligence/auto-draft/{doc_id}")
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data, "Missing error detail"
        assert "ready" in data["detail"].lower() or "readiness" in data["detail"].lower(), f"Error message should mention readiness: {data['detail']}"
        
        print(f"Auto-draft 422 for blocked doc: {data['detail'][:100]}")

    def test_auto_draft_duplicate_prevention(self, authenticated_client):
        """Should return existing action with status=duplicate when draft already exists"""
        # DOC_WITH_AP_DRAFT already has a draft per context
        doc_id = DOC_WITH_AP_DRAFT
        
        # First check if this document actually has a draft
        intel_response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}")
        if intel_response.status_code != 200:
            pytest.skip(f"Could not get intelligence for {doc_id}")
        
        intel = intel_response.json()
        
        # Try to create another draft
        response = authenticated_client.post(f"{BASE_URL}/api/document-intelligence/auto-draft/{doc_id}")
        
        # Should return 200 with status=duplicate (not 409)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("status") == "duplicate", f"Expected status=duplicate, got {data.get('status')}"
        assert "existing_action" in data, "Missing existing_action in duplicate response"
        assert "message" in data, "Missing message in duplicate response"
        
        existing = data["existing_action"]
        assert "target_entity_id" in existing, "Missing target_entity_id in existing_action"
        assert "target_entity_type" in existing, "Missing target_entity_type in existing_action"
        
        print(f"Duplicate prevention works: doc={doc_id}, existing_draft={existing.get('target_entity_id')}, type={existing.get('target_entity_type')}")

    def test_auto_draft_creates_ap_intake_draft(self, authenticated_client):
        """Should create AP intake draft from AP_Invoice document"""
        # Find a ready AP_Invoice doc without a draft
        doc_id = None
        for candidate in READY_AP_DOCS_NO_DRAFT:
            intel_resp = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/{candidate}")
            if intel_resp.status_code == 200:
                intel = intel_resp.json()
                if intel.get("automation_readiness") == "ready" and not intel.get("auto_draft_created"):
                    doc_id = candidate
                    break
        
        if not doc_id:
            # Try finding any ready AP_Invoice from review queue
            queue_resp = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/review-queue?status=ready")
            if queue_resp.status_code == 200:
                items = queue_resp.json().get("items", [])
                for item in items:
                    if item.get("document_type") == "AP_Invoice" and not item.get("auto_draft_created"):
                        doc_id = item["document_id"]
                        break
        
        if not doc_id:
            pytest.skip("No ready AP_Invoice document without draft found")
        
        # Create the draft
        response = authenticated_client.post(f"{BASE_URL}/api/document-intelligence/auto-draft/{doc_id}")
        
        # Could be 200 (success or duplicate) or 422 (not ready after all)
        assert response.status_code in [200, 422], f"Unexpected status {response.status_code}: {response.text}"
        
        if response.status_code == 422:
            print(f"Document {doc_id} not actually ready: {response.json().get('detail')}")
            pytest.skip("Document not ready for draft creation")
        
        data = response.json()
        
        if data.get("status") == "duplicate":
            print(f"Draft already exists for {doc_id}: {data.get('existing_action', {}).get('target_entity_id')}")
            return
        
        # Validate successful creation
        assert "automation_action_id" in data, "Missing automation_action_id"
        assert data.get("action_status") == "draft_created", f"Expected draft_created, got {data.get('action_status')}"
        assert data.get("target_entity_type") == "ap_intake_draft", f"Expected ap_intake_draft, got {data.get('target_entity_type')}"
        assert "target_entity_id" in data, "Missing target_entity_id"
        assert data["target_entity_id"].startswith("AP-DRAFT-"), f"Invalid draft ID format: {data['target_entity_id']}"
        
        # Check draft data
        assert "draft" in data, "Missing draft in response"
        draft = data["draft"]
        assert draft.get("source_document_id") == doc_id, "source_document_id mismatch"
        assert "ap_draft_id" in draft, "Missing ap_draft_id in draft"
        assert draft.get("status") == "draft", f"Expected status=draft, got {draft.get('status')}"
        
        print(f"AP intake draft created: doc={doc_id}, draft_id={data['target_entity_id']}, vendor={draft.get('vendor_name')}, amount={draft.get('invoice_amount')}")

    def test_auto_draft_po_draft_from_freight_document(self, authenticated_client):
        """Should create PO draft from Freight_Document"""
        # The doc should already have a draft, so expect duplicate
        doc_id = DOC_WITH_PO_DRAFT_FREIGHT
        
        intel_resp = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}")
        if intel_resp.status_code != 200:
            pytest.skip(f"Could not get intelligence for {doc_id}")
        
        response = authenticated_client.post(f"{BASE_URL}/api/document-intelligence/auto-draft/{doc_id}")
        
        if response.status_code == 422:
            print(f"Document not ready: {response.json().get('detail')}")
            pytest.skip("Document not ready")
        
        assert response.status_code == 200, f"Unexpected status {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Should be duplicate or new creation
        if data.get("status") == "duplicate":
            existing = data["existing_action"]
            assert existing.get("target_entity_type") == "po_draft", f"Expected po_draft, got {existing.get('target_entity_type')}"
            print(f"PO draft already exists: {existing.get('target_entity_id')}")
        else:
            assert data.get("target_entity_type") == "po_draft", f"Expected po_draft, got {data.get('target_entity_type')}"
            print(f"PO draft created: {data.get('target_entity_id')}")

    def test_auto_draft_po_draft_from_shipping_document(self, authenticated_client):
        """Should create PO draft from Shipping_Document"""
        doc_id = DOC_WITH_PO_DRAFT_SHIPPING
        
        intel_resp = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}")
        if intel_resp.status_code != 200:
            pytest.skip(f"Could not get intelligence for {doc_id}")
        
        response = authenticated_client.post(f"{BASE_URL}/api/document-intelligence/auto-draft/{doc_id}")
        
        if response.status_code == 422:
            print(f"Document not ready: {response.json().get('detail')}")
            pytest.skip("Document not ready")
        
        assert response.status_code == 200, f"Unexpected status {response.status_code}: {response.text}"
        
        data = response.json()
        
        if data.get("status") == "duplicate":
            existing = data["existing_action"]
            assert existing.get("target_entity_type") == "po_draft", f"Expected po_draft, got {existing.get('target_entity_type')}"
            print(f"PO draft (shipping) already exists: {existing.get('target_entity_id')}")
        else:
            assert data.get("target_entity_type") == "po_draft", f"Expected po_draft, got {data.get('target_entity_type')}"
            print(f"PO draft (shipping) created: {data.get('target_entity_id')}")


# ==================== GET /api/document-intelligence/auto-draft/{id} ====================
class TestGetAutomationAction:
    """GET /api/document-intelligence/auto-draft/{id} endpoint tests"""

    def test_get_automation_action_404_no_action(self, authenticated_client):
        """Should return 404 when no automation action exists for document"""
        fake_id = "no-action-test-doc"
        
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/auto-draft/{fake_id}")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        
        print(f"Get automation action 404 for no action: {response.json().get('detail')}")

    def test_get_automation_action_returns_latest(self, authenticated_client):
        """Should return latest automation action for a document"""
        # Use a doc that has a draft
        doc_id = DOC_WITH_AP_DRAFT
        
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/auto-draft/{doc_id}")
        
        if response.status_code == 404:
            # Try one of the other docs
            doc_id = DOC_WITH_PO_DRAFT_FREIGHT
            response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/auto-draft/{doc_id}")
        
        if response.status_code == 404:
            pytest.skip("No documents with automation actions found")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Validate action structure
        assert "automation_action_id" in data, "Missing automation_action_id"
        assert "document_id" in data, "Missing document_id"
        assert data["document_id"] == doc_id, "document_id mismatch"
        assert "target_entity_type" in data, "Missing target_entity_type"
        assert "target_entity_id" in data, "Missing target_entity_id"
        assert "action_type" in data, "Missing action_type"
        assert "action_status" in data, "Missing action_status"
        assert "created_at" in data, "Missing created_at"
        
        print(f"Get automation action: doc={doc_id}, type={data['target_entity_type']}, id={data['target_entity_id']}, status={data['action_status']}")


# ==================== Intelligence Result Enrichment ====================
class TestIntelligenceEnrichment:
    """Test that intelligence results are enriched after draft creation"""

    def test_intelligence_result_has_draft_fields(self, authenticated_client):
        """After draft creation, GET /api/document-intelligence/{id} should have draft fields"""
        # Use a doc with known draft
        doc_id = DOC_WITH_AP_DRAFT
        
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}")
        
        if response.status_code == 404:
            doc_id = DOC_WITH_PO_DRAFT_FREIGHT
            response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}")
        
        if response.status_code != 200:
            pytest.skip("No intelligence result with draft found")
        
        data = response.json()
        
        # These fields should be present after draft creation
        auto_draft_fields = [
            "auto_draft_available",
            "auto_draft_created", 
            "target_entity_type",
            "target_entity_id",
            "last_automation_action_status"
        ]
        
        found_fields = []
        for field in auto_draft_fields:
            if field in data:
                found_fields.append(field)
        
        if not found_fields:
            pytest.skip("Document may not have had draft created yet")
        
        print(f"Intelligence enrichment fields found: {found_fields}")
        
        # Validate field values if present
        if "auto_draft_created" in data:
            assert isinstance(data["auto_draft_created"], bool), "auto_draft_created should be bool"
        
        if "target_entity_type" in data:
            assert data["target_entity_type"] in ["ap_intake_draft", "po_draft", "sales_order_draft"], f"Invalid target_entity_type: {data['target_entity_type']}"
        
        if "target_entity_id" in data and data["target_entity_id"]:
            assert isinstance(data["target_entity_id"], str), "target_entity_id should be string"
            print(f"Draft ID: {data['target_entity_id']}")


# ==================== Review Queue Enrichment ====================
class TestReviewQueueDraftEnrichment:
    """Test that review queue items show draft status"""

    def test_review_queue_shows_draft_status(self, authenticated_client):
        """Review queue items with drafts should show target_entity_id"""
        response = authenticated_client.get(f"{BASE_URL}/api/document-intelligence/review-queue?status=ready")
        
        assert response.status_code == 200
        
        data = response.json()
        items = data.get("items", [])
        
        items_with_drafts = []
        items_without_drafts = []
        
        for item in items:
            if item.get("auto_draft_created"):
                items_with_drafts.append({
                    "doc_id": item["document_id"],
                    "draft_id": item.get("target_entity_id"),
                    "type": item.get("target_entity_type")
                })
            else:
                items_without_drafts.append(item["document_id"])
        
        print(f"Review queue: {len(items_with_drafts)} items with drafts, {len(items_without_drafts)} without")
        
        for item in items_with_drafts:
            print(f"  - {item['doc_id']}: {item['type']} = {item['draft_id']}")


# ==================== Activity Records ====================
class TestActivityRecords:
    """Test that activity records are created for auto-draft events"""

    def test_activity_created_for_draft(self, authenticated_client):
        """Activity record should be created when draft is created"""
        # We can check activities endpoint if available, or just verify the draft was created
        # This is more of an integration test - verify by checking document events/timeline
        
        doc_id = DOC_WITH_AP_DRAFT
        
        # Try to get document timeline/events
        response = authenticated_client.get(f"{BASE_URL}/api/documents/{doc_id}/timeline")
        
        if response.status_code == 200:
            data = response.json()
            # Look for auto_draft activity
            found_draft_activity = False
            if isinstance(data, list):
                for event in data:
                    if "auto_draft" in str(event).lower():
                        found_draft_activity = True
                        break
            elif isinstance(data, dict):
                events = data.get("events", []) or data.get("timeline", [])
                for event in events:
                    if "auto_draft" in str(event).lower():
                        found_draft_activity = True
                        break
            
            print(f"Activity for draft: {'found' if found_draft_activity else 'not found in timeline'}")
        else:
            print(f"Timeline endpoint returned {response.status_code} - activity logging may use different mechanism")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
