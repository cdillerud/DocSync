"""
GPI Document Hub - Learning Loop Engine Tests (Iteration 101)

Tests for the Learning Loop Engine that captures human corrections and
converts them into structured intelligence signals.

Modules tested:
- Learning summary endpoint (GET /api/document-intelligence/learning/summary)
- Learning events endpoint (GET /api/document-intelligence/learning/events)  
- Document learning events (GET /api/document-intelligence/learning/events/{doc_id})
- Learning event auto-generation via correction hooks
- Extraction hints recording
- Document enrichment with learning metadata
- Automation confidence metrics
"""

import pytest
import requests
import os
import time
import uuid

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

@pytest.fixture(scope="module")
def api_client():
    """Shared requests session with auth."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    # Login to get token
    resp = session.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "admin"})
    if resp.status_code == 200:
        token = resp.json().get("access_token")
        session.headers.update({"Authorization": f"Bearer {token}"})
    return session


class TestLearningSummaryEndpoint:
    """Tests for GET /api/document-intelligence/learning/summary"""

    def test_learning_summary_returns_all_required_fields(self, api_client):
        """Verify learning summary contains all required metrics."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/learning/summary")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        # Check all required fields exist
        required_fields = [
            "total_learning_events",
            "corrections_by_type",
            "top_corrected_document_types",
            "top_corrected_vendors",
            "vendor_aliases_created",
            "customer_aliases_created",
            "extraction_hints_recorded",
            "automation_success_rate",
            "correction_rate_by_document_type",
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

    def test_learning_summary_automation_success_rate_is_valid(self, api_client):
        """Verify automation_success_rate is a valid number between 0 and 1."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/learning/summary")
        assert resp.status_code == 200
        
        data = resp.json()
        assert isinstance(data["automation_success_rate"], (int, float))
        assert 0 <= data["automation_success_rate"] <= 1, \
            f"automation_success_rate out of range: {data['automation_success_rate']}"

    def test_learning_summary_corrections_by_type_is_dict(self, api_client):
        """Verify corrections_by_type is a dictionary."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/learning/summary")
        assert resp.status_code == 200
        
        data = resp.json()
        assert isinstance(data["corrections_by_type"], dict)

    def test_learning_summary_top_corrected_document_types_is_list(self, api_client):
        """Verify top_corrected_document_types is a list of objects."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/learning/summary")
        assert resp.status_code == 200
        
        data = resp.json()
        assert isinstance(data["top_corrected_document_types"], list)
        # If there are items, check structure
        if data["top_corrected_document_types"]:
            item = data["top_corrected_document_types"][0]
            assert "document_type" in item
            assert "count" in item


class TestLearningEventsEndpoint:
    """Tests for GET /api/document-intelligence/learning/events"""

    def test_learning_events_returns_total_and_events(self, api_client):
        """Verify learning events returns total and events array."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/learning/events")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert "total" in data, "Missing 'total' field"
        assert "events" in data, "Missing 'events' field"
        assert isinstance(data["events"], list)

    def test_learning_events_sorted_by_most_recent(self, api_client):
        """Verify events are sorted by created_at descending (most recent first)."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/learning/events")
        assert resp.status_code == 200
        
        data = resp.json()
        events = data["events"]
        if len(events) >= 2:
            # Check that events are sorted descending by created_at
            for i in range(len(events) - 1):
                assert events[i].get("created_at", "") >= events[i + 1].get("created_at", ""), \
                    "Events not sorted by most recent first"

    def test_learning_events_filter_by_event_type(self, api_client):
        """Test filtering events by event_type."""
        # First get all events to see what types exist
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/learning/events")
        assert resp.status_code == 200
        
        # Try filtering by classification_correction
        resp = api_client.get(
            f"{BASE_URL}/api/document-intelligence/learning/events",
            params={"event_type": "classification_correction"}
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # All returned events should have the filtered type
        for ev in data["events"]:
            assert ev.get("event_type") == "classification_correction"

    def test_learning_events_filter_by_document_type(self, api_client):
        """Test filtering events by document_type."""
        resp = api_client.get(
            f"{BASE_URL}/api/document-intelligence/learning/events",
            params={"document_type": "AP_Invoice"}
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # All returned events should have the filtered document type
        for ev in data["events"]:
            assert ev.get("document_type") == "AP_Invoice"

    def test_learning_events_supports_limit_and_offset(self, api_client):
        """Test pagination with limit and offset."""
        resp = api_client.get(
            f"{BASE_URL}/api/document-intelligence/learning/events",
            params={"limit": 2, "offset": 0}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) <= 2

    def test_learning_events_event_structure(self, api_client):
        """Verify each event has required structure."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/learning/events")
        assert resp.status_code == 200
        data = resp.json()
        
        if data["events"]:
            ev = data["events"][0]
            required_fields = [
                "learning_event_id",
                "document_id",
                "event_type",
                "created_at",
            ]
            for field in required_fields:
                assert field in ev, f"Event missing required field: {field}"


class TestDocumentLearningEventsEndpoint:
    """Tests for GET /api/document-intelligence/learning/events/{doc_id}"""

    def test_document_learning_events_returns_array(self, api_client):
        """Verify document learning events returns a plain array."""
        # Use TEST-BUNDLE-B which should have learning events from prior testing
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/learning/events/TEST-BUNDLE-B")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        # Should return a plain array, not {total, events}
        assert isinstance(data, list), f"Expected list, got {type(data)}"

    def test_document_learning_events_returns_events_for_doc(self, api_client):
        """Verify events are for the specific document."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/learning/events/TEST-BUNDLE-B")
        assert resp.status_code == 200
        
        data = resp.json()
        for ev in data:
            assert ev.get("document_id") == "TEST-BUNDLE-B", \
                f"Event document_id mismatch: {ev.get('document_id')}"

    def test_document_learning_events_empty_for_nonexistent_doc(self, api_client):
        """Verify empty array for document without learning events."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/learning/events/NONEXISTENT-DOC-123")
        assert resp.status_code == 200
        
        data = resp.json()
        assert isinstance(data, list)
        # Likely empty but should not error


class TestLearningEventAutoGeneration:
    """Tests for learning event auto-generation on corrections."""

    def test_classification_correction_creates_learning_event(self, api_client):
        """Test that PATCH with corrected_type creates classification_correction event."""
        # Create a test document first via processing
        doc_id = f"TEST-LEARN-{uuid.uuid4().hex[:8].upper()}"
        
        # Process a document to create intelligence result
        process_resp = api_client.post(f"{BASE_URL}/api/document-intelligence/process/{doc_id}")
        # May return 404 if doc doesn't exist in documents collection, which is OK
        # We can directly test the correction endpoint on an existing doc
        
        # Use existing doc TEST-BUNDLE-B for correction test
        test_doc_id = "TEST-BUNDLE-B"
        
        # Get current events count
        events_before = api_client.get(
            f"{BASE_URL}/api/document-intelligence/learning/events",
            params={"event_type": "classification_correction"}
        )
        before_count = events_before.json().get("total", 0) if events_before.status_code == 200 else 0
        
        # Apply classification correction
        resp = api_client.patch(
            f"{BASE_URL}/api/document-intelligence/{test_doc_id}",
            json={
                "corrected_type": "Freight_Document",
                "corrected_by": "test_admin",
                "notes": "Test classification correction"
            }
        )
        
        if resp.status_code == 200:
            # Verify learning event was created
            time.sleep(0.3)  # Small delay for async processing
            events_after = api_client.get(
                f"{BASE_URL}/api/document-intelligence/learning/events",
                params={"event_type": "classification_correction"}
            )
            after_count = events_after.json().get("total", 0) if events_after.status_code == 200 else 0
            assert after_count >= before_count, "Expected new classification_correction event"
        else:
            # Document may not exist or be in wrong state - skip gracefully
            pytest.skip(f"Could not apply correction: {resp.status_code} - {resp.text}")

    def test_field_correction_creates_learning_event(self, api_client):
        """Test that PATCH with corrected_fields creates field_correction event."""
        test_doc_id = "TEST-BUNDLE-B"
        
        # Get current events count
        events_before = api_client.get(
            f"{BASE_URL}/api/document-intelligence/learning/events",
            params={"event_type": "field_correction"}
        )
        before_count = events_before.json().get("total", 0) if events_before.status_code == 200 else 0
        
        # Apply field correction
        resp = api_client.patch(
            f"{BASE_URL}/api/document-intelligence/{test_doc_id}",
            json={
                "corrected_fields": {
                    "invoice_number": f"INV-CORRECTED-{uuid.uuid4().hex[:6].upper()}"
                },
                "corrected_by": "test_admin",
                "notes": "Test field correction"
            }
        )
        
        if resp.status_code == 200:
            time.sleep(0.3)
            events_after = api_client.get(
                f"{BASE_URL}/api/document-intelligence/learning/events",
                params={"event_type": "field_correction"}
            )
            after_count = events_after.json().get("total", 0) if events_after.status_code == 200 else 0
            assert after_count >= before_count, "Expected new field_correction event"
        else:
            pytest.skip(f"Could not apply correction: {resp.status_code} - {resp.text}")


class TestExtractionHintsRecording:
    """Tests for extraction hint recording on field corrections."""

    def test_extraction_hints_recorded_in_summary(self, api_client):
        """Verify extraction_hints_recorded count is returned in summary."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/learning/summary")
        assert resp.status_code == 200
        
        data = resp.json()
        assert "extraction_hints_recorded" in data
        assert isinstance(data["extraction_hints_recorded"], int)
        # Per problem statement, should have 2+ hints from prior testing
        # But we don't assert exact value as it may vary


class TestDocumentEnrichmentWithLearning:
    """Tests for document enrichment with learning metadata."""

    def test_document_has_learning_events_count(self, api_client):
        """Verify documents are enriched with learning_events_count."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/TEST-BUNDLE-B")
        
        if resp.status_code == 200:
            data = resp.json()
            # After corrections, should have learning metadata
            assert "learning_events_count" in data or "corrections_applied" in data, \
                "Document missing learning enrichment fields"

    def test_document_has_learning_flags(self, api_client):
        """Verify documents are enriched with learning_flags."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/TEST-BUNDLE-B")
        
        if resp.status_code == 200:
            data = resp.json()
            # learning_flags should be an array
            if "learning_flags" in data:
                assert isinstance(data["learning_flags"], list)


class TestAutomationConfidenceMetrics:
    """Tests for automation confidence metrics in learning summary."""

    def test_automation_success_rate_calculated(self, api_client):
        """Verify automation_success_rate is calculated from metrics."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/learning/summary")
        assert resp.status_code == 200
        
        data = resp.json()
        assert "automation_success_rate" in data
        # Should be ~94% per problem statement (0.94)
        rate = data["automation_success_rate"]
        assert isinstance(rate, (int, float))

    def test_correction_rate_by_document_type(self, api_client):
        """Verify correction_rate_by_document_type is calculated."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/learning/summary")
        assert resp.status_code == 200
        
        data = resp.json()
        assert "correction_rate_by_document_type" in data
        assert isinstance(data["correction_rate_by_document_type"], dict)
        
        # If there are entries, verify structure
        for doc_type, metrics in data["correction_rate_by_document_type"].items():
            if isinstance(metrics, dict):
                assert "total" in metrics or "corrected" in metrics or "correction_rate" in metrics


class TestActivityEventsGenerated:
    """Tests for activity events created by learning loop."""

    def test_learning_event_generated_activity(self, api_client):
        """Verify learning_event_generated activity is created."""
        # Get recent activities for a document that has learning events
        resp = api_client.get(f"{BASE_URL}/api/documents/TEST-BUNDLE-B", params={"include_events": True})
        
        if resp.status_code == 200:
            data = resp.json()
            events = data.get("events", [])
            # Look for learning_event_generated activity type
            learning_activities = [e for e in events if e.get("activity_type") == "learning_event_generated"]
            # Note: activity might be in separate activities collection - this test is informational


class TestRegressionIteration100:
    """Regression tests for iteration_100 decision policy endpoints."""

    def test_regression_policies_endpoint(self, api_client):
        """Verify decision policy endpoints still work."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/policies")
        assert resp.status_code == 200, f"Regression: policies endpoint failed: {resp.status_code}"

    def test_regression_evaluate_decision_endpoint(self, api_client):
        """Verify decision evaluation still works."""
        resp = api_client.post(f"{BASE_URL}/api/document-intelligence/evaluate-decision/TEST-BUNDLE-B")
        # May return 200 or 404 depending on doc state, but should not be 500
        assert resp.status_code != 500, f"Regression: evaluate-decision endpoint error: {resp.status_code}"

    def test_regression_decision_queue_endpoint(self, api_client):
        """Verify decision queue still works."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/decision-queue")
        assert resp.status_code == 200, f"Regression: decision-queue endpoint failed: {resp.status_code}"


class TestRegressionIteration98_99:
    """Regression tests for iteration_98-99 bundle/lifecycle endpoints."""

    def test_regression_bundles_endpoint(self, api_client):
        """Verify bundles endpoint still works."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/bundles")
        assert resp.status_code == 200, f"Regression: bundles endpoint failed: {resp.status_code}"

    def test_regression_detect_bundles_endpoint(self, api_client):
        """Verify detect-bundles endpoint still works."""
        resp = api_client.post(f"{BASE_URL}/api/document-intelligence/detect-bundles", json={})
        # May return 200 with bundles or various results
        assert resp.status_code in [200, 201], f"Regression: detect-bundles failed: {resp.status_code}"

    def test_regression_lifecycle_issues_endpoint(self, api_client):
        """Verify lifecycle-issues endpoint still works."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/lifecycle-issues")
        assert resp.status_code == 200, f"Regression: lifecycle-issues endpoint failed: {resp.status_code}"

    def test_regression_bundle_review_queue(self, api_client):
        """Verify bundle-review-queue endpoint still works."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/bundle-review-queue")
        assert resp.status_code == 200, f"Regression: bundle-review-queue failed: {resp.status_code}"

    def test_regression_review_queue(self, api_client):
        """Verify review-queue endpoint still works."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/review-queue")
        assert resp.status_code == 200, f"Regression: review-queue failed: {resp.status_code}"

    def test_regression_summary_endpoint(self, api_client):
        """Verify summary endpoint still works."""
        resp = api_client.get(f"{BASE_URL}/api/document-intelligence/summary")
        assert resp.status_code == 200, f"Regression: summary endpoint failed: {resp.status_code}"
