"""
Feedback Loop Health API Tests
Tests the GET /api/feedback-loop/health endpoint
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestFeedbackLoopHealthAPI:
    """Tests for the Feedback Loop Health dashboard API"""

    def test_health_endpoint_returns_200(self):
        """Test that the feedback-loop health endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/feedback-loop/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ Feedback loop health endpoint returns 200")

    def test_health_response_has_total_events(self):
        """Test that response contains total_events field"""
        response = requests.get(f"{BASE_URL}/api/feedback-loop/health")
        data = response.json()
        assert "total_events" in data, "Missing total_events field"
        assert isinstance(data["total_events"], int), "total_events should be int"
        assert data["total_events"] == 51, f"Expected 51 total events, got {data['total_events']}"
        print(f"✓ total_events: {data['total_events']}")

    def test_health_response_has_applied_events(self):
        """Test that response contains applied_events field"""
        response = requests.get(f"{BASE_URL}/api/feedback-loop/health")
        data = response.json()
        assert "applied_events" in data, "Missing applied_events field"
        assert isinstance(data["applied_events"], int), "applied_events should be int"
        assert data["applied_events"] == 46, f"Expected 46 applied events, got {data['applied_events']}"
        print(f"✓ applied_events: {data['applied_events']}")

    def test_health_response_has_pending_events(self):
        """Test that response contains pending_events field"""
        response = requests.get(f"{BASE_URL}/api/feedback-loop/health")
        data = response.json()
        assert "pending_events" in data, "Missing pending_events field"
        assert data["pending_events"] == 5, f"Expected 5 pending events, got {data['pending_events']}"
        print(f"✓ pending_events: {data['pending_events']}")

    def test_health_response_has_events_by_type(self):
        """Test that response contains events_by_type breakdown"""
        response = requests.get(f"{BASE_URL}/api/feedback-loop/health")
        data = response.json()
        assert "events_by_type" in data, "Missing events_by_type field"
        events_by_type = data["events_by_type"]
        
        # Check expected event types exist
        expected_types = ["vendor_correction", "approval", "classification_correction"]
        for event_type in expected_types:
            assert event_type in events_by_type, f"Missing event type: {event_type}"
        
        # Verify counts
        assert events_by_type.get("vendor_correction") == 18, "vendor_correction count mismatch"
        assert events_by_type.get("approval") == 17, "approval count mismatch"
        assert events_by_type.get("classification_correction") == 9, "classification_correction count mismatch"
        print(f"✓ events_by_type: {events_by_type}")

    def test_health_response_has_learning_signals(self):
        """Test that response contains learning_signals with correct counts"""
        response = requests.get(f"{BASE_URL}/api/feedback-loop/health")
        data = response.json()
        assert "learning_signals" in data, "Missing learning_signals field"
        
        signals = data["learning_signals"]
        assert signals.get("vendor_aliases_learned") == 3, f"Expected 3 vendor aliases, got {signals.get('vendor_aliases_learned')}"
        assert signals.get("classification_examples") == 2, f"Expected 2 classification examples, got {signals.get('classification_examples')}"
        assert signals.get("routing_corrections") == 1, f"Expected 1 routing correction, got {signals.get('routing_corrections')}"
        print(f"✓ learning_signals: {signals}")

    def test_health_response_has_recent_events(self):
        """Test that response contains recent_events array"""
        response = requests.get(f"{BASE_URL}/api/feedback-loop/health")
        data = response.json()
        assert "recent_events" in data, "Missing recent_events field"
        assert isinstance(data["recent_events"], list), "recent_events should be a list"
        assert len(data["recent_events"]) > 0, "recent_events should not be empty"
        
        # Check structure of first event
        first_event = data["recent_events"][0]
        required_fields = ["event_type", "vendor_id", "document_id", "source", "created_at", "applied"]
        for field in required_fields:
            assert field in first_event, f"Missing field in recent event: {field}"
        print(f"✓ recent_events count: {len(data['recent_events'])}")

    def test_health_response_has_daily_activity(self):
        """Test that response contains daily_activity array"""
        response = requests.get(f"{BASE_URL}/api/feedback-loop/health")
        data = response.json()
        assert "daily_activity" in data, "Missing daily_activity field"
        assert isinstance(data["daily_activity"], list), "daily_activity should be a list"
        
        if len(data["daily_activity"]) > 0:
            first_day = data["daily_activity"][0]
            assert "date" in first_day, "Missing date in daily_activity item"
            assert "count" in first_day, "Missing count in daily_activity item"
        print(f"✓ daily_activity count: {len(data['daily_activity'])}")

    def test_health_response_has_top_corrected_vendors(self):
        """Test that response contains top_corrected_vendors array"""
        response = requests.get(f"{BASE_URL}/api/feedback-loop/health")
        data = response.json()
        assert "top_corrected_vendors" in data, "Missing top_corrected_vendors field"
        assert isinstance(data["top_corrected_vendors"], list), "top_corrected_vendors should be a list"
        assert len(data["top_corrected_vendors"]) > 0, "top_corrected_vendors should not be empty"
        
        # Check structure and verify top vendor
        first_vendor = data["top_corrected_vendors"][0]
        assert "vendor_id" in first_vendor, "Missing vendor_id in top vendor"
        assert "event_count" in first_vendor, "Missing event_count in top vendor"
        assert first_vendor["vendor_id"] == "TUMALOC", f"Expected TUMALOC as top vendor, got {first_vendor['vendor_id']}"
        assert first_vendor["event_count"] == 19, f"Expected 19 events for TUMALOC, got {first_vendor['event_count']}"
        print(f"✓ top_corrected_vendors: {[v['vendor_id'] for v in data['top_corrected_vendors'][:3]]}")

    def test_application_rate_calculation(self):
        """Test that applied rate is approximately 90%"""
        response = requests.get(f"{BASE_URL}/api/feedback-loop/health")
        data = response.json()
        
        total = data["total_events"]
        applied = data["applied_events"]
        rate = round((applied / total) * 100) if total > 0 else 0
        
        assert rate == 90, f"Expected 90% application rate, got {rate}%"
        print(f"✓ Application rate: {rate}%")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
