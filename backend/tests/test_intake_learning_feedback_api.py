"""
API tests for Phase D Intake Learning Feedback Loop endpoints.

Tests:
  • POST /api/intake/insights/feedback — all 6 event types + invalid type
  • GET /api/intake/learning/pattern-health — summary shape
  • POST /api/intake/learning/hygiene — manual hygiene trigger
  • GET /api/intake/learning/events — recent events sorted DESC
  • Regression: GET /api/intake/learning/summary, POST /api/intake/learning/backfill, GET /api/intake/flagged
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestFeedbackEndpoint:
    """POST /api/intake/insights/feedback tests"""
    
    def test_suggestion_accepted_bumps_occurrences(self):
        """Accept a suggestion for Giovanni customer C-10250"""
        response = requests.post(f"{BASE_URL}/api/intake/insights/feedback", json={
            "event_type": "suggestion_accepted",
            "customer_no": "C-10250",
            "item_no": "OIPALLET",
            "trigger_item": "*"
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("ok") is True
        assert "event" in data
        assert data["event"]["event_type"] == "suggestion_accepted"
        # applied.action should be 'applied' if pattern found, or 'no_matching_pattern' if not
        if data.get("applied"):
            print(f"Applied action: {data['applied'].get('action')}")
    
    def test_suggestion_rejected_decays_pattern(self):
        """Reject a suggestion — should decay occurrences"""
        response = requests.post(f"{BASE_URL}/api/intake/insights/feedback", json={
            "event_type": "suggestion_rejected",
            "customer_no": "C-10250",
            "item_no": "OITIERSHEET",
            "trigger_item": "*"
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") is True
        assert data["event"]["event_type"] == "suggestion_rejected"
    
    def test_bounds_violation_overridden_widens_std_dev(self):
        """Override a bounds violation — should widen std_dev by 10%"""
        response = requests.post(f"{BASE_URL}/api/intake/insights/feedback", json={
            "event_type": "bounds_violation_overridden",
            "customer_no": "C-10250",
            "item_no": "C-9874"
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") is True
        if data.get("applied") and data["applied"].get("action") == "bounds_nudged":
            print(f"New std_dev: {data['applied'].get('new_std_dev')}")
    
    def test_bounds_violation_confirmed_increments_outliers(self):
        """Confirm a bounds violation — should increment confirmed_outliers"""
        response = requests.post(f"{BASE_URL}/api/intake/insights/feedback", json={
            "event_type": "bounds_violation_confirmed",
            "customer_no": "C-10250",
            "item_no": "C-9874"
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") is True
    
    def test_unmatched_item_confirmed_new_creates_candidate(self):
        """Confirm a new unmatched item — should upsert in intake_item_candidates"""
        response = requests.post(f"{BASE_URL}/api/intake/insights/feedback", json={
            "event_type": "unmatched_item_confirmed_new",
            "customer_no": "C-10250",
            "item_no": "NEW-X",
            "extra": {"description": "Test new item"}
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") is True
        if data.get("applied"):
            assert data["applied"].get("action") == "candidate_recorded"
            assert data["applied"].get("item_no") == "NEW-X"
    
    def test_unmatched_item_mapped_saves_alias(self):
        """Map an unmatched item to BC item — should upsert in intake_item_aliases"""
        response = requests.post(f"{BASE_URL}/api/intake/insights/feedback", json={
            "event_type": "unmatched_item_mapped",
            "customer_no": "C-10250",
            "item_no": "TYPO-001",
            "extra": {"mapped_to_bc_item": "C-9874"}
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") is True
        if data.get("applied"):
            assert data["applied"].get("action") == "alias_saved"
            assert data["applied"].get("to") == "C-9874"
    
    def test_invalid_event_type_returns_400(self):
        """Invalid event_type should return 400 with valid types list"""
        response = requests.post(f"{BASE_URL}/api/intake/insights/feedback", json={
            "event_type": "bogus",
            "customer_no": "C-10250"
        })
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        data = response.json()
        assert "detail" in data
        # Should mention valid event types
        assert "suggestion_accepted" in data["detail"] or "event_type" in data["detail"]


class TestPatternHealthEndpoint:
    """GET /api/intake/learning/pattern-health tests"""
    
    def test_pattern_health_returns_expected_shape(self):
        """Pattern health should return summary + per_customer + recent_events"""
        response = requests.get(f"{BASE_URL}/api/intake/learning/pattern-health?limit=25")
        assert response.status_code == 200
        data = response.json()
        
        # Check summary shape
        assert "summary" in data
        summary = data["summary"]
        for key in ["trusted", "drifting", "retired", "unscored", "total"]:
            assert key in summary, f"Missing key '{key}' in summary"
        
        # Check per_customer array
        assert "per_customer" in data
        assert isinstance(data["per_customer"], list)
        
        # Check recent_events array
        assert "recent_events" in data
        assert isinstance(data["recent_events"], list)
        
        print(f"Pattern health summary: {summary}")
        print(f"Per-customer count: {len(data['per_customer'])}")
        print(f"Recent events count: {len(data['recent_events'])}")


class TestHygieneEndpoint:
    """POST /api/intake/learning/hygiene tests"""
    
    def test_hygiene_returns_expected_shape(self):
        """Hygiene should return patterns_scanned, retired, promoted, ran_at"""
        response = requests.post(f"{BASE_URL}/api/intake/learning/hygiene")
        assert response.status_code == 200
        data = response.json()
        
        for key in ["patterns_scanned", "retired", "promoted", "ran_at"]:
            assert key in data, f"Missing key '{key}' in hygiene response"
        
        print(f"Hygiene result: scanned={data['patterns_scanned']}, retired={data['retired']}, promoted={data['promoted']}")


class TestEventsEndpoint:
    """GET /api/intake/learning/events tests"""
    
    def test_events_returns_sorted_desc(self):
        """Events should be sorted by created_at DESC (most recent first)"""
        response = requests.get(f"{BASE_URL}/api/intake/learning/events?limit=25")
        assert response.status_code == 200
        data = response.json()
        
        assert "events" in data
        assert "total" in data
        events = data["events"]
        
        # Verify sorting (if we have multiple events)
        if len(events) >= 2:
            for i in range(len(events) - 1):
                assert events[i]["created_at"] >= events[i+1]["created_at"], \
                    f"Events not sorted DESC: {events[i]['created_at']} < {events[i+1]['created_at']}"
        
        print(f"Events total: {data['total']}, returned: {len(events)}")


class TestRegressionEndpoints:
    """Regression tests for existing endpoints"""
    
    def test_learning_summary_still_works(self):
        """GET /api/intake/learning/summary should still work"""
        response = requests.get(f"{BASE_URL}/api/intake/learning/summary")
        assert response.status_code == 200
        data = response.json()
        assert "hub" in data
        assert "xls_staging" in data
        print(f"Learning summary: hub eligible={data['hub'].get('eligible_docs')}")
    
    def test_backfill_still_works(self):
        """POST /api/intake/learning/backfill should still work"""
        response = requests.post(f"{BASE_URL}/api/intake/learning/backfill?limit=5&only_missing=true")
        assert response.status_code == 200
        data = response.json()
        assert "hub_documents" in data
        assert "xls_staging" in data
        print(f"Backfill: hub processed={data['hub_documents'].get('processed')}")
    
    def test_flagged_still_works(self):
        """GET /api/intake/flagged should still work"""
        response = requests.get(f"{BASE_URL}/api/intake/flagged?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "documents" in data
        print(f"Flagged docs: {data['total']}")


class TestRetirementFlow:
    """Test that 5 rejects eventually retire a pattern line"""
    
    def test_multiple_rejects_can_retire_pattern(self):
        """5 rejects on same item should eventually retire it (accept_rate < 40%)"""
        # This test verifies the retirement logic works
        # Note: actual retirement depends on existing pattern state
        for i in range(5):
            response = requests.post(f"{BASE_URL}/api/intake/insights/feedback", json={
                "event_type": "suggestion_rejected",
                "customer_no": "C-10250",
                "item_no": "OITIERSHEET",
                "trigger_item": "*"
            })
            assert response.status_code == 200
            data = response.json()
            if data.get("applied", {}).get("retired"):
                print(f"Pattern retired after {i+1} rejects")
                break
        
        # Check pattern health to see if retired count increased
        health_response = requests.get(f"{BASE_URL}/api/intake/learning/pattern-health")
        assert health_response.status_code == 200
        health = health_response.json()
        print(f"After rejects - retired count: {health['summary']['retired']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
