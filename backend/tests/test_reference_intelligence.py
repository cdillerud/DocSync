"""
Tests for Reference Intelligence Service APIs
- POST /api/documents/{doc_id}/resolve-intelligence
- GET /api/documents/{doc_id}/reference-intelligence
- POST /api/bc/resolve-reference
- GET /api/bc/write-guard/status
- Events emitted: reference.extraction.completed, reference.resolve.completed/ambiguous
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://doc-hub-refactor.preview.emergentagent.com').rstrip('/')

# Test document IDs from the context
DOC_WITH_PO = "a1dec76a-17a2-46d4-a9f9-a0f6fb818208"  # Has PO 110463, type AP_Invoice
DOC_WITHOUT_PO = "92f29b5f-3e6f-495e-8899-b77a4d0ba38c"  # No extracted fields yet


class TestBCReferenceResolver:
    """Tests for POST /api/bc/resolve-reference endpoint"""
    
    def test_resolve_reference_found(self):
        """Test resolving a known reference number against BC"""
        response = requests.post(
            f"{BASE_URL}/api/bc/resolve-reference",
            params={"reference_number": "110463"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["reference_number"] == "110463"
        assert data["status"] == "found"
        assert data["reference_type"] is not None
        assert data["bc_record_id"] is not None
        assert data["bc_document_no"] is not None
        assert "tables_checked" in data
        assert len(data["tables_checked"]) > 0
        print(f"Reference 110463 resolved: type={data['reference_type']}, bc_doc={data['bc_document_no']}")
    
    def test_resolve_reference_not_found(self):
        """Test resolving an unknown reference number"""
        response = requests.post(
            f"{BASE_URL}/api/bc/resolve-reference",
            params={"reference_number": "NOTEXIST123456"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["reference_number"] == "NOTEXIST123456"
        assert data["status"] == "not_found"
        assert data["reference_type"] == "not_found"
        assert "tables_checked" in data
        print(f"Reference NOTEXIST123456 correctly reported as not found")
    
    def test_resolve_reference_with_specific_tables(self):
        """Test resolving with specific tables filter"""
        response = requests.post(
            f"{BASE_URL}/api/bc/resolve-reference",
            params={"reference_number": "110463", "tables": "salesShipments"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "salesShipments" in data["tables_checked"]
        print(f"Filtered search tables_checked: {data['tables_checked']}")


class TestBCWriteGuard:
    """Tests for BC Write Safety Guard"""
    
    def test_write_guard_status(self):
        """Test GET /api/bc/write-guard/status returns blocked status"""
        response = requests.get(f"{BASE_URL}/api/bc/write-guard/status")
        assert response.status_code == 200
        
        data = response.json()
        assert "write_enabled" in data
        assert "environment" in data
        assert "is_production" in data
        assert "status" in data
        assert "message" in data
        
        # Per context, writes should be blocked for production safety
        assert data["write_enabled"] == False
        assert data["status"] == "blocked"
        assert data["is_production"] == True
        print(f"Write guard status: {data['status']}, env={data['environment']}")
    
    def test_write_guard_check_permission(self):
        """Test POST /api/bc/write-guard/check for permission check"""
        response = requests.post(
            f"{BASE_URL}/api/bc/write-guard/check",
            params={"document_id": DOC_WITH_PO, "action": "create_purchase_invoice"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "allowed" in data
        assert "reason" in data or data["allowed"] == True
        
        # Should be blocked since production writes disabled
        assert data["allowed"] == False
        print(f"Write permission check: allowed={data['allowed']}, reason={data.get('reason')}")


class TestReferenceIntelligenceResolve:
    """Tests for POST /api/documents/{doc_id}/resolve-intelligence"""
    
    def test_resolve_intelligence_with_po(self):
        """Test resolving reference intelligence for document with PO"""
        response = requests.post(
            f"{BASE_URL}/api/documents/{DOC_WITH_PO}/resolve-intelligence"
        )
        assert response.status_code == 200
        
        data = response.json()
        
        # Check required response fields
        assert data["document_id"] == DOC_WITH_PO
        assert "document_type" in data
        assert "resolver_strategy" in data
        assert "search_order" in data
        assert "reference_candidates" in data
        assert "match_outcome" in data
        assert "resolved_at" in data
        assert "total_bc_queries" in data
        assert "processing_time_ms" in data
        
        # Validate reference candidates structure
        assert len(data["reference_candidates"]) > 0
        for candidate in data["reference_candidates"]:
            assert "reference_value_raw" in candidate
            assert "reference_value_normalized" in candidate
            assert "detected_label" in candidate
            assert "confidence" in candidate
            assert "predicted_domain" in candidate
        
        # Check match outcome
        assert data["match_outcome"] in ["exact_match", "likely_match", "ambiguous_match", "no_match"]
        
        # If best match exists, validate structure
        if data.get("best_match"):
            best = data["best_match"]
            assert "entity_type" in best
            assert "bc_record_id" in best
            assert "bc_document_no" in best
            assert "match_score" in best
            assert "match_reasoning" in best
        
        print(f"Resolved: outcome={data['match_outcome']}, candidates={len(data['reference_candidates'])}, bc_queries={data['total_bc_queries']}, time={data['processing_time_ms']}ms")
    
    def test_resolve_intelligence_404_for_nonexistent_doc(self):
        """Test 404 returned for non-existent document"""
        response = requests.post(
            f"{BASE_URL}/api/documents/nonexistent-doc-id/resolve-intelligence"
        )
        assert response.status_code == 404


class TestReferenceIntelligenceGet:
    """Tests for GET /api/documents/{doc_id}/reference-intelligence"""
    
    def test_get_reference_intelligence_with_data(self):
        """Test getting stored reference intelligence for document with resolved data"""
        response = requests.get(
            f"{BASE_URL}/api/documents/{DOC_WITH_PO}/reference-intelligence"
        )
        assert response.status_code == 200
        
        data = response.json()
        
        # If resolved, should have full intelligence data
        if data.get("status") != "not_resolved":
            assert "document_id" in data
            assert "match_outcome" in data
            assert "reference_candidates" in data
            assert "resolved_at" in data
            print(f"Got intelligence: outcome={data['match_outcome']}, candidates={len(data.get('reference_candidates', []))}")
        else:
            print("Document has not been resolved yet - expected for fresh documents")
    
    def test_get_reference_intelligence_not_resolved(self):
        """Test getting intelligence for document that hasn't been resolved returns proper message"""
        # First check if the doc without PO has been resolved
        response = requests.get(
            f"{BASE_URL}/api/documents/{DOC_WITHOUT_PO}/reference-intelligence"
        )
        assert response.status_code == 200
        
        data = response.json()
        
        # Should either have data or show not_resolved status
        if data.get("status") == "not_resolved":
            assert "message" in data
            assert "resolve-intelligence" in data["message"].lower()
            print(f"Document not yet resolved: {data['message']}")
        else:
            print(f"Document already resolved: outcome={data.get('match_outcome')}")
    
    def test_get_reference_intelligence_404_for_nonexistent(self):
        """Test 404 for non-existent document"""
        response = requests.get(
            f"{BASE_URL}/api/documents/nonexistent-doc-id/reference-intelligence"
        )
        assert response.status_code == 404


class TestReferenceIntelligenceEvents:
    """Tests for event emission during reference intelligence resolution"""
    
    def test_events_emitted_after_resolution(self):
        """Verify events are emitted after resolving reference intelligence"""
        # First resolve
        resolve_resp = requests.post(
            f"{BASE_URL}/api/documents/{DOC_WITH_PO}/resolve-intelligence"
        )
        assert resolve_resp.status_code == 200
        
        # Wait a moment for event to be stored
        time.sleep(0.5)
        
        # Get events
        events_resp = requests.get(
            f"{BASE_URL}/api/documents/{DOC_WITH_PO}/events",
            params={"limit": 20}
        )
        assert events_resp.status_code == 200
        
        events_data = events_resp.json()
        assert "events" in events_data
        
        # Check for reference events
        event_types = [e["event_type"] for e in events_data["events"]]
        
        # Should have extraction event
        has_extraction = any("reference.extraction" in t for t in event_types)
        # Should have resolve event (completed or ambiguous)
        has_resolve = any("reference.resolve" in t for t in event_types)
        
        assert has_extraction or has_resolve, f"Expected reference events, got: {event_types[:5]}"
        
        print(f"Found {len(events_data['events'])} events, types include: {event_types[:5]}")
    
    def test_resolve_ambiguous_event(self):
        """Test that ambiguous match emits reference.resolve.ambiguous event"""
        events_resp = requests.get(
            f"{BASE_URL}/api/documents/{DOC_WITH_PO}/events",
            params={"limit": 50}
        )
        assert events_resp.status_code == 200
        
        events = events_resp.json()["events"]
        
        # Find resolve events
        resolve_events = [e for e in events if "reference.resolve" in e["event_type"]]
        
        if resolve_events:
            latest = resolve_events[0]
            print(f"Latest resolve event: {latest['event_type']}, status={latest['status']}")
            assert latest["event_type"] in ["reference.resolve.completed", "reference.resolve.ambiguous"]
            assert "payload" in latest
            assert "match_outcome" in latest["payload"]


class TestReferenceIntelligenceIntegration:
    """Integration tests for reference intelligence with document detail"""
    
    def test_document_detail_includes_intelligence(self):
        """Test that document detail returns reference intelligence data"""
        # First ensure we have resolved
        requests.post(f"{BASE_URL}/api/documents/{DOC_WITH_PO}/resolve-intelligence")
        
        # Get document detail
        response = requests.get(
            f"{BASE_URL}/api/documents/{DOC_WITH_PO}",
            params={"include_events": "true"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "document" in data
        
        doc = data["document"]
        
        # Should have reference_intelligence stored on document
        if doc.get("reference_intelligence"):
            intel = doc["reference_intelligence"]
            assert "match_outcome" in intel
            assert "reference_candidates" in intel
            print(f"Document has stored intelligence: outcome={intel['match_outcome']}")
        else:
            print("Document doesn't have stored reference_intelligence yet")
        
        # Should have event timeline
        assert "event_timeline" in data
        print(f"Document has {len(data.get('event_timeline', []))} events in timeline")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
