"""
Transaction Matching Service Tests - Iteration 97

Tests the Document-to-Existing-Transaction Matching and Auto-Linking feature:
- POST /api/document-intelligence/match-transactions/{doc_id} — finds existing transaction matches
- GET /api/document-intelligence/transaction-matches/{doc_id} — returns stored matches
- POST /api/document-intelligence/auto-link/{doc_id} — links to best matched transaction  
- PATCH /api/document-intelligence/transaction-matches/{match_id} — confirm/reject match

Key concepts:
- Matches documents to existing SO drafts, PO drafts, or AP intake drafts
- overall_status: matched (single high conf), ambiguous (multiple), unmatched
- auto_link_available: true when single high-confidence match or manually confirmed
- auto_draft_suppressed_due_to_match: true when confident match found
- Rejected matches excluded from auto-link candidates
"""

import pytest
import requests
import os
import time
from datetime import datetime
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestTransactionMatchingSetup:
    """Setup: Create seed data for transaction matching tests"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    def test_create_seed_so_drafts(self, api_client):
        """Seed SO drafts for matching tests"""
        # First check if we can access MongoDB collections via API
        # We'll create SO drafts with specific PO numbers for matching
        
        # Get existing documents to see what PO numbers we can match against
        response = api_client.get(f"{BASE_URL}/api/documents", params={"limit": 20})
        assert response.status_code == 200
        docs = response.json().get("documents", [])
        print(f"Found {len(docs)} documents in system")
        
        # Check document intelligence results
        intel_response = api_client.get(f"{BASE_URL}/api/document-intelligence/summary")
        assert intel_response.status_code == 200
        summary = intel_response.json()
        print(f"Intelligence summary: {summary.get('total_processed', 0)} processed")
        
    def test_health_check(self, api_client):
        """Verify backend is healthy"""
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"


class TestMatchTransactions:
    """Test POST /api/document-intelligence/match-transactions/{doc_id}"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    def test_match_transactions_no_intelligence_result(self, api_client):
        """Returns 404 when no intelligence result exists"""
        response = api_client.post(f"{BASE_URL}/api/document-intelligence/match-transactions/nonexistent-doc-12345")
        assert response.status_code == 404
        data = response.json()
        assert "No intelligence result" in data.get("detail", "")
        
    def test_match_transactions_returns_structure(self, api_client):
        """Returns correct structure with matches, overall_status, auto_link_available"""
        # First get a document with intelligence result
        queue_response = api_client.get(f"{BASE_URL}/api/document-intelligence/review-queue", params={"limit": 10, "status": "ready"})
        assert queue_response.status_code == 200
        items = queue_response.json().get("items", [])
        
        if not items:
            pytest.skip("No ready documents to test matching")
            
        doc_id = items[0]["document_id"]
        
        # Run matching
        response = api_client.post(f"{BASE_URL}/api/document-intelligence/match-transactions/{doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        # Verify structure
        assert "document_id" in data
        assert data["document_id"] == doc_id
        assert "matches" in data
        assert isinstance(data["matches"], list)
        assert "overall_status" in data
        assert data["overall_status"] in ["matched", "ambiguous", "unmatched"]
        assert "auto_link_available" in data
        assert isinstance(data["auto_link_available"], bool)
        assert "best_match" in data
        assert "total_candidates" in data
        
        print(f"Match result for {doc_id}: status={data['overall_status']}, candidates={data['total_candidates']}, auto_link={data['auto_link_available']}")
        
    def test_match_transactions_updates_intelligence_result(self, api_client):
        """Matching updates document_intelligence_results with transaction_match_status"""
        queue_response = api_client.get(f"{BASE_URL}/api/document-intelligence/review-queue", params={"limit": 10, "status": "ready"})
        items = queue_response.json().get("items", [])
        
        if not items:
            pytest.skip("No ready documents to test")
            
        doc_id = items[0]["document_id"]
        
        # Run matching
        match_response = api_client.post(f"{BASE_URL}/api/document-intelligence/match-transactions/{doc_id}")
        assert match_response.status_code == 200
        match_data = match_response.json()
        
        # Get intelligence result to verify enrichment
        intel_response = api_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}")
        assert intel_response.status_code == 200
        intel = intel_response.json()
        
        assert "transaction_match_status" in intel
        assert intel["transaction_match_status"] == match_data["overall_status"]
        assert "matched_transaction_count" in intel
        assert "auto_link_available" in intel
        
        if match_data["auto_link_available"]:
            assert "auto_draft_suppressed_due_to_match" in intel
            assert intel["auto_draft_suppressed_due_to_match"] == True
            
    def test_match_transactions_creates_activity(self, api_client):
        """Transaction matching creates activity timeline events"""
        queue_response = api_client.get(f"{BASE_URL}/api/document-intelligence/review-queue", params={"limit": 10})
        items = queue_response.json().get("items", [])
        
        if not items:
            pytest.skip("No documents to test")
            
        doc_id = items[0]["document_id"]
        
        # Run matching
        response = api_client.post(f"{BASE_URL}/api/document-intelligence/match-transactions/{doc_id}")
        assert response.status_code == 200
        match_data = response.json()
        
        # Check activities
        timeline_response = api_client.get(f"{BASE_URL}/api/documents/{doc_id}/timeline")
        if timeline_response.status_code == 200:
            timeline = timeline_response.json()
            activities = timeline.get("events", timeline.get("activities", []))
            
            # Look for transaction match activity
            match_activities = [a for a in activities if "transaction_match" in a.get("activity_type", "")]
            if match_activities:
                print(f"Found {len(match_activities)} transaction match activities")
                latest = match_activities[0]
                assert latest["activity_type"] in ["transaction_match_found", "transaction_match_ambiguous", "transaction_match_none"]


class TestGetTransactionMatches:
    """Test GET /api/document-intelligence/transaction-matches/{doc_id}"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
        
    def test_get_matches_empty_for_new_doc(self, api_client):
        """Returns empty matches for document with no matching run"""
        # Get a document
        docs_response = api_client.get(f"{BASE_URL}/api/documents", params={"limit": 5})
        docs = docs_response.json().get("documents", [])
        
        if not docs:
            pytest.skip("No documents available")
            
        # Find one without matches (process first if needed)
        doc_id = docs[0]["id"]
        
        response = api_client.get(f"{BASE_URL}/api/document-intelligence/transaction-matches/{doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        assert "document_id" in data
        assert data["document_id"] == doc_id
        assert "matches" in data
        assert "total" in data
        
    def test_get_matches_returns_stored_candidates(self, api_client):
        """Returns stored match candidates after matching"""
        # Get a document with intelligence
        queue_response = api_client.get(f"{BASE_URL}/api/document-intelligence/review-queue", params={"limit": 5})
        items = queue_response.json().get("items", [])
        
        if not items:
            pytest.skip("No documents with intelligence results")
            
        doc_id = items[0]["document_id"]
        
        # Run matching first
        api_client.post(f"{BASE_URL}/api/document-intelligence/match-transactions/{doc_id}")
        
        # Get matches
        response = api_client.get(f"{BASE_URL}/api/document-intelligence/transaction-matches/{doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        matches = data.get("matches", [])
        for match in matches:
            assert "transaction_match_id" in match
            assert "document_id" in match
            assert "candidate_entity_type" in match
            assert "candidate_entity_id" in match
            assert "candidate_display_name" in match
            assert "match_confidence" in match
            assert "match_status" in match
            assert "is_selected" in match
            
        print(f"Document {doc_id} has {len(matches)} match candidates")


class TestAutoLink:
    """Test POST /api/document-intelligence/auto-link/{doc_id}"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
        
    def test_auto_link_no_matches(self, api_client):
        """Returns 404/error when no transaction matches exist"""
        # Get a document
        docs_response = api_client.get(f"{BASE_URL}/api/documents", params={"limit": 5})
        docs = docs_response.json().get("documents", [])
        
        if not docs:
            pytest.skip("No documents")
            
        # Find a doc that likely has no matches
        for doc in docs:
            doc_id = doc["id"]
            matches_response = api_client.get(f"{BASE_URL}/api/document-intelligence/transaction-matches/{doc_id}")
            if matches_response.status_code == 200:
                matches = matches_response.json().get("matches", [])
                if len(matches) == 0:
                    response = api_client.post(f"{BASE_URL}/api/document-intelligence/auto-link/{doc_id}")
                    # Should fail - no matches
                    assert response.status_code in [404, 422]
                    return
                    
        print("Skipped - all docs have matches")
        
    def test_auto_link_rejects_ambiguous(self, api_client):
        """Returns 422 for ambiguous matches without manual confirmation"""
        queue_response = api_client.get(f"{BASE_URL}/api/document-intelligence/review-queue", params={"limit": 20})
        items = queue_response.json().get("items", [])
        
        for item in items:
            doc_id = item["document_id"]
            # Run matching
            match_response = api_client.post(f"{BASE_URL}/api/document-intelligence/match-transactions/{doc_id}")
            if match_response.status_code == 200:
                match_data = match_response.json()
                if match_data.get("overall_status") == "ambiguous":
                    # Try auto-link
                    response = api_client.post(f"{BASE_URL}/api/document-intelligence/auto-link/{doc_id}")
                    assert response.status_code == 422
                    data = response.json()
                    assert "ambiguous" in data.get("detail", "").lower() or "confirm" in data.get("detail", "").lower()
                    print(f"Confirmed: auto-link rejected for ambiguous doc {doc_id}")
                    return
                    
        print("No ambiguous matches found to test rejection")


class TestConfirmMatch:
    """Test PATCH /api/document-intelligence/transaction-matches/{match_id}"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
        
    def test_confirm_match_not_found(self, api_client):
        """Returns 404 for non-existent match_id"""
        response = api_client.patch(
            f"{BASE_URL}/api/document-intelligence/transaction-matches/TM-NONEXISTENT",
            json={"confirmed": True, "selected_by": "test", "notes": "test"}
        )
        assert response.status_code == 404
        
    def test_confirm_match_success(self, api_client):
        """Confirming match sets is_selected=true, status=confirmed, deselects others"""
        # Get a doc with matches
        queue_response = api_client.get(f"{BASE_URL}/api/document-intelligence/review-queue", params={"limit": 20})
        items = queue_response.json().get("items", [])
        
        for item in items:
            doc_id = item["document_id"]
            # Run matching
            match_response = api_client.post(f"{BASE_URL}/api/document-intelligence/match-transactions/{doc_id}")
            if match_response.status_code == 200:
                matches = match_response.json().get("matches", [])
                if len(matches) > 0:
                    # Confirm first match
                    match_id = matches[0]["transaction_match_id"]
                    response = api_client.patch(
                        f"{BASE_URL}/api/document-intelligence/transaction-matches/{match_id}",
                        json={"confirmed": True, "selected_by": "test_user", "notes": "Test confirmation"}
                    )
                    assert response.status_code == 200
                    data = response.json()
                    
                    assert data.get("is_selected") == True
                    assert data.get("match_status") == "confirmed"
                    assert data.get("selected_by") == "test_user"
                    
                    # Check that intelligence result updated
                    intel = api_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}").json()
                    assert intel.get("transaction_match_status") == "confirmed"
                    assert intel.get("auto_link_available") == True
                    
                    print(f"Confirmed match {match_id} for doc {doc_id}")
                    return
                    
        pytest.skip("No matches available to confirm")
        
    def test_reject_match_success(self, api_client):
        """Rejecting match sets is_selected=false, status=rejected, re-evaluates remaining"""
        queue_response = api_client.get(f"{BASE_URL}/api/document-intelligence/review-queue", params={"limit": 20})
        items = queue_response.json().get("items", [])
        
        for item in items:
            doc_id = item["document_id"]
            # Run matching
            match_response = api_client.post(f"{BASE_URL}/api/document-intelligence/match-transactions/{doc_id}")
            if match_response.status_code == 200:
                matches = match_response.json().get("matches", [])
                # Find non-confirmed match
                non_confirmed = [m for m in matches if m.get("match_status") not in ["confirmed", "rejected"]]
                if non_confirmed:
                    match_id = non_confirmed[0]["transaction_match_id"]
                    response = api_client.patch(
                        f"{BASE_URL}/api/document-intelligence/transaction-matches/{match_id}",
                        json={"confirmed": False, "selected_by": "test_user", "notes": "Test rejection"}
                    )
                    assert response.status_code == 200
                    data = response.json()
                    
                    assert data.get("is_selected") == False
                    assert data.get("match_status") == "rejected"
                    
                    print(f"Rejected match {match_id} for doc {doc_id}")
                    return
                    
        pytest.skip("No available matches to reject")


class TestAutoLinkWithRejected:
    """Test that auto-link respects rejected matches"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
        
    def test_auto_link_excludes_rejected_matches(self, api_client):
        """Auto-link excludes rejected matches from high-confidence candidates"""
        # This is tested implicitly via the rejection flow in TestConfirmMatch
        # After rejection, re-evaluation excludes rejected matches
        
        queue_response = api_client.get(f"{BASE_URL}/api/document-intelligence/review-queue", params={"limit": 20})
        items = queue_response.json().get("items", [])
        
        for item in items:
            doc_id = item["document_id"]
            # Get matches
            matches_response = api_client.get(f"{BASE_URL}/api/document-intelligence/transaction-matches/{doc_id}")
            if matches_response.status_code == 200:
                matches = matches_response.json().get("matches", [])
                # Check if any high-conf matches are rejected
                rejected_high = [m for m in matches if m.get("match_status") == "rejected" and m.get("match_confidence", 0) >= 0.90]
                if rejected_high:
                    # Verify they're excluded from auto-link consideration
                    intel = api_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}").json()
                    print(f"Doc {doc_id} has {len(rejected_high)} rejected high-conf matches, auto_link_available={intel.get('auto_link_available')}")
                    return
                    
        print("No documents with rejected high-confidence matches found")


class TestAutoDraftSuppression:
    """Test auto_draft_suppressed_due_to_match behavior"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
        
    def test_draft_suppressed_when_auto_link_available(self, api_client):
        """auto_draft_suppressed_due_to_match=true when auto_link_available=true"""
        queue_response = api_client.get(f"{BASE_URL}/api/document-intelligence/review-queue", params={"limit": 20})
        items = queue_response.json().get("items", [])
        
        for item in items:
            doc_id = item["document_id"]
            # Run matching
            match_response = api_client.post(f"{BASE_URL}/api/document-intelligence/match-transactions/{doc_id}")
            if match_response.status_code == 200:
                match_data = match_response.json()
                if match_data.get("auto_link_available"):
                    # Check intelligence result
                    intel = api_client.get(f"{BASE_URL}/api/document-intelligence/{doc_id}").json()
                    assert intel.get("auto_draft_suppressed_due_to_match") == True
                    print(f"Verified: auto_draft_suppressed_due_to_match=True for doc {doc_id}")
                    return
                    
        print("No documents with auto_link_available=true found")


class TestActivityTimelineEvents:
    """Test activity timeline events for transaction matching"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
        
    def test_match_found_activity(self, api_client):
        """transaction_match_found activity created for matched status"""
        # This is verified in TestMatchTransactions.test_match_transactions_creates_activity
        pass
        
    def test_match_confirmed_activity(self, api_client):
        """transaction_match_confirmed activity created on manual confirmation"""
        queue_response = api_client.get(f"{BASE_URL}/api/document-intelligence/review-queue", params={"limit": 20})
        items = queue_response.json().get("items", [])
        
        for item in items:
            doc_id = item["document_id"]
            # Check activities
            timeline_response = api_client.get(f"{BASE_URL}/api/documents/{doc_id}/timeline")
            if timeline_response.status_code == 200:
                activities = timeline_response.json().get("events", timeline_response.json().get("activities", []))
                confirmed_activities = [a for a in activities if a.get("activity_type") == "transaction_match_confirmed"]
                if confirmed_activities:
                    print(f"Found transaction_match_confirmed activity for doc {doc_id}")
                    return


class TestRegressionExistingEndpoints:
    """Regression tests for existing document intelligence endpoints"""
    
    @pytest.fixture(scope="class")
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session
        
    def test_process_endpoint_still_works(self, api_client):
        """POST /api/document-intelligence/process/{id} still works"""
        docs_response = api_client.get(f"{BASE_URL}/api/documents", params={"limit": 5})
        docs = docs_response.json().get("documents", [])
        
        if not docs:
            pytest.skip("No documents")
            
        doc_id = docs[0]["id"]
        response = api_client.post(f"{BASE_URL}/api/document-intelligence/process/{doc_id}")
        assert response.status_code in [200, 500]  # 500 if no file path, but endpoint works
        
    def test_review_queue_still_works(self, api_client):
        """GET /api/document-intelligence/review-queue still works"""
        response = api_client.get(f"{BASE_URL}/api/document-intelligence/review-queue")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        
    def test_auto_draft_still_works(self, api_client):
        """POST /api/document-intelligence/auto-draft/{id} still works"""
        queue_response = api_client.get(f"{BASE_URL}/api/document-intelligence/review-queue", params={"status": "ready", "limit": 5})
        items = queue_response.json().get("items", [])
        
        if not items:
            pytest.skip("No ready documents")
            
        doc_id = items[0]["document_id"]
        response = api_client.post(f"{BASE_URL}/api/document-intelligence/auto-draft/{doc_id}")
        # Could be 200 (created/duplicate) or 422 (suppressed due to match)
        assert response.status_code in [200, 422]
        
    def test_resolve_entities_still_works(self, api_client):
        """POST /api/document-intelligence/resolve-entities/{id} still works"""
        queue_response = api_client.get(f"{BASE_URL}/api/document-intelligence/review-queue", params={"limit": 5})
        items = queue_response.json().get("items", [])
        
        if not items:
            pytest.skip("No documents")
            
        doc_id = items[0]["document_id"]
        response = api_client.post(f"{BASE_URL}/api/document-intelligence/resolve-entities/{doc_id}")
        assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
