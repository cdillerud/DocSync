"""
Test derived_state_service.py fix for ReadyForPost decision handling.

The bug: automation.decision.completed events with both auto_clear=True and decision=ReadyForPost
were handled by the auto_clear branch first, never reaching the ReadyForPost branch which sets
validation_state='pass'.

The fix: Check the 'decision' field FIRST (ReadyForPost/Posted/NeedsReview) before checking
'auto_clear'/'auto_post' booleans.
"""
import pytest
import requests
import os
import uuid
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'gpi_document_hub')


@pytest.fixture(scope="module")
def db():
    """MongoDB connection fixture"""
    client = MongoClient(MONGO_URL)
    database = client[DB_NAME]
    yield database
    client.close()


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestHealthCheck:
    """Basic health check"""
    
    def test_api_health(self, api_client):
        """Verify API is healthy"""
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print("PASS: API health check")


class TestDerivedStateReadyForPost:
    """Test derived_state_service correctly handles ReadyForPost decision"""
    
    @pytest.fixture(autouse=True)
    def setup_test_document(self, db):
        """Create a test document with ReadyForPost status and workflow events in the workflow_events collection"""
        self.doc_id = f"TEST_readyforpost_{uuid.uuid4().hex[:8]}"
        base_time = datetime.now(timezone.utc)
        
        # Create document with ReadyForPost status and auto_cleared=True
        # This simulates what ap_auto_post_service does when BC_WRITE_ENABLED=false
        test_doc = {
            "id": self.doc_id,
            "file_name": f"test_readyforpost_{self.doc_id}.pdf",
            "document_type": "AP_Invoice",
            "status": "ReadyForPost",
            "workflow_status": "ready_for_post",
            "auto_cleared": True,
            "auto_post_attempted": True,
            "auto_post_reason": "All checks passed but BC_WRITE_ENABLED=false",
            "created_utc": base_time.isoformat(),
            "updated_utc": base_time.isoformat(),
            "source": "test",
            # Validation results with a failed PO check (to verify it gets overridden)
            "validation_results": {
                "validation_status": "fail",
                "checks": [
                    {"check_name": "vendor_match", "passed": True, "required": True},
                    {"check_name": "po_match", "passed": False, "required": False, "details": "PO not found"},
                ]
            },
        }
        
        db.hub_documents.insert_one(test_doc)
        
        # Insert events into the workflow_events collection with DIFFERENT timestamps
        # Events must be in chronological order for proper processing
        events = [
            {
                "event_id": f"evt_{uuid.uuid4().hex[:8]}",
                "document_id": self.doc_id,
                "event_type": "document.received",
                "timestamp": (base_time - timedelta(minutes=5)).isoformat(),  # 5 min ago
                "source_service": "intake",
                "payload": {}
            },
            {
                "event_id": f"evt_{uuid.uuid4().hex[:8]}",
                "document_id": self.doc_id,
                "event_type": "classification.completed",
                "timestamp": (base_time - timedelta(minutes=4)).isoformat(),  # 4 min ago
                "source_service": "classification",
                "payload": {"document_type": "AP_Invoice", "confidence": 0.95}
            },
            {
                "event_id": f"evt_{uuid.uuid4().hex[:8]}",
                "document_id": self.doc_id,
                "event_type": "vendor.match.completed",
                "timestamp": (base_time - timedelta(minutes=3)).isoformat(),  # 3 min ago
                "source_service": "vendor_resolution",
                "payload": {"vendor_no": "TESTVENDOR", "match_method": "exact"}
            },
            {
                "event_id": f"evt_{uuid.uuid4().hex[:8]}",
                "document_id": self.doc_id,
                "event_type": "bc.validation.completed",
                "timestamp": (base_time - timedelta(minutes=2)).isoformat(),  # 2 min ago
                "source_service": "bc_validation",
                "payload": {
                    "validation_status": "fail",
                    "checks": [
                        {"check_name": "vendor_match", "passed": True},
                        {"check_name": "po_match", "passed": False}
                    ],
                    "failed_checks": ["po_match"]
                }
            },
            # The key event: decision=ReadyForPost with auto_clear=True
            # The fix ensures decision is checked FIRST
            {
                "event_id": f"evt_{uuid.uuid4().hex[:8]}",
                "document_id": self.doc_id,
                "event_type": "automation.decision.completed",
                "timestamp": (base_time - timedelta(minutes=1)).isoformat(),  # 1 min ago (most recent)
                "source_service": "ap_auto_post",
                "payload": {
                    "decision": "ReadyForPost",
                    "auto_clear": True,
                    "auto_post": False,
                    "reason": "All checks passed — BC writes disabled, queued for manual post",
                    "source": "ap_auto_post"
                }
            }
        ]
        
        for event in events:
            db.workflow_events.insert_one(event)
        
        yield
        # Cleanup
        db.hub_documents.delete_one({"id": self.doc_id})
        db.workflow_events.delete_many({"document_id": self.doc_id})
    
    def test_get_document_returns_derived_state_pass(self, api_client):
        """GET /api/documents/{doc_id} should return derived_state.validation_state='pass' for ReadyForPost"""
        response = api_client.get(f"{BASE_URL}/api/documents/{self.doc_id}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "derived_state" in data, "Response should include derived_state"
        
        derived_state = data["derived_state"]
        
        # The key assertion: validation_state should be 'pass' not 'fail'
        assert derived_state.get("validation_state") == "pass", \
            f"Expected validation_state='pass', got '{derived_state.get('validation_state')}'"
        
        # workflow_state should be 'ready' not 'completed'
        assert derived_state.get("workflow_state") == "ready", \
            f"Expected workflow_state='ready', got '{derived_state.get('workflow_state')}'"
        
        # needs_review should be False
        assert derived_state.get("needs_review") == False, \
            f"Expected needs_review=False, got '{derived_state.get('needs_review')}'"
        
        # blocking_issues should be empty (ReadyForPost clears them)
        blocking_issues = derived_state.get("blocking_issues", [])
        assert len(blocking_issues) == 0, \
            f"Expected empty blocking_issues, got {blocking_issues}"
        
        print(f"PASS: ReadyForPost document has validation_state='pass', workflow_state='ready'")
    
    def test_derived_state_from_events(self, api_client):
        """Verify derived_state is computed from events (not legacy fields)"""
        response = api_client.get(f"{BASE_URL}/api/documents/{self.doc_id}")
        assert response.status_code == 200
        
        data = response.json()
        derived_state = data.get("derived_state", {})
        
        # Should be derived from events since workflow_events exist
        assert derived_state.get("derived_from") == "events", \
            f"Expected derived_from='events', got '{derived_state.get('derived_from')}'"
        
        print("PASS: derived_state is computed from events")


class TestDerivedStateNeedsReview:
    """Test NeedsReview decision still works correctly"""
    
    @pytest.fixture(autouse=True)
    def setup_test_document(self, db):
        """Create a test document with NeedsReview decision"""
        self.doc_id = f"TEST_needsreview_{uuid.uuid4().hex[:8]}"
        base_time = datetime.now(timezone.utc)
        
        test_doc = {
            "id": self.doc_id,
            "file_name": f"test_needsreview_{self.doc_id}.pdf",
            "document_type": "AP_Invoice",
            "status": "NeedsReview",
            "workflow_status": "needs_review",
            "created_utc": base_time.isoformat(),
            "updated_utc": base_time.isoformat(),
            "source": "test",
        }
        
        db.hub_documents.insert_one(test_doc)
        
        # Insert events into workflow_events collection with different timestamps
        events = [
            {
                "event_id": f"evt_{uuid.uuid4().hex[:8]}",
                "document_id": self.doc_id,
                "event_type": "document.received",
                "timestamp": (base_time - timedelta(minutes=2)).isoformat(),
                "source_service": "intake",
                "payload": {}
            },
            {
                "event_id": f"evt_{uuid.uuid4().hex[:8]}",
                "document_id": self.doc_id,
                "event_type": "automation.decision.completed",
                "timestamp": (base_time - timedelta(minutes=1)).isoformat(),
                "source_service": "ap_auto_post",
                "payload": {
                    "decision": "NeedsReview",
                    "auto_clear": False,
                    "auto_post": False,
                    "reason": "Vendor not matched",
                    "failures": ["vendor_not_matched"]
                }
            }
        ]
        
        for event in events:
            db.workflow_events.insert_one(event)
        
        yield
        db.hub_documents.delete_one({"id": self.doc_id})
        db.workflow_events.delete_many({"document_id": self.doc_id})
    
    def test_needs_review_derived_state(self, api_client):
        """NeedsReview decision should set workflow_state='reviewing', needs_review=True"""
        response = api_client.get(f"{BASE_URL}/api/documents/{self.doc_id}")
        assert response.status_code == 200
        
        data = response.json()
        derived_state = data.get("derived_state", {})
        
        assert derived_state.get("workflow_state") == "reviewing", \
            f"Expected workflow_state='reviewing', got '{derived_state.get('workflow_state')}'"
        
        assert derived_state.get("needs_review") == True, \
            f"Expected needs_review=True, got '{derived_state.get('needs_review')}'"
        
        print("PASS: NeedsReview decision correctly sets workflow_state='reviewing', needs_review=True")


class TestDerivedStatePosted:
    """Test Posted decision correctly maps to workflow_state=completed, validation_state=pass"""
    
    @pytest.fixture(autouse=True)
    def setup_test_document(self, db):
        """Create a test document with Posted decision"""
        self.doc_id = f"TEST_posted_{uuid.uuid4().hex[:8]}"
        base_time = datetime.now(timezone.utc)
        
        test_doc = {
            "id": self.doc_id,
            "file_name": f"test_posted_{self.doc_id}.pdf",
            "document_type": "AP_Invoice",
            "status": "Posted",
            "workflow_status": "posted",
            "auto_cleared": True,
            "auto_post_success": True,
            "bc_record_no": "PI-00001",
            "created_utc": base_time.isoformat(),
            "updated_utc": base_time.isoformat(),
            "source": "test",
        }
        
        db.hub_documents.insert_one(test_doc)
        
        # Insert events into workflow_events collection with different timestamps
        events = [
            {
                "event_id": f"evt_{uuid.uuid4().hex[:8]}",
                "document_id": self.doc_id,
                "event_type": "document.received",
                "timestamp": (base_time - timedelta(minutes=2)).isoformat(),
                "source_service": "intake",
                "payload": {}
            },
            {
                "event_id": f"evt_{uuid.uuid4().hex[:8]}",
                "document_id": self.doc_id,
                "event_type": "automation.decision.completed",
                "timestamp": (base_time - timedelta(minutes=1)).isoformat(),
                "source_service": "ap_auto_post",
                "payload": {
                    "decision": "Posted",
                    "auto_clear": True,
                    "auto_post": True,
                    "bc_record_no": "PI-00001",
                    "reason": "Successfully posted to BC"
                }
            }
        ]
        
        for event in events:
            db.workflow_events.insert_one(event)
        
        yield
        db.hub_documents.delete_one({"id": self.doc_id})
        db.workflow_events.delete_many({"document_id": self.doc_id})
    
    def test_posted_derived_state(self, api_client):
        """Posted decision should set workflow_state='completed', validation_state='pass'"""
        response = api_client.get(f"{BASE_URL}/api/documents/{self.doc_id}")
        assert response.status_code == 200
        
        data = response.json()
        derived_state = data.get("derived_state", {})
        
        assert derived_state.get("workflow_state") == "completed", \
            f"Expected workflow_state='completed', got '{derived_state.get('workflow_state')}'"
        
        assert derived_state.get("validation_state") == "pass", \
            f"Expected validation_state='pass', got '{derived_state.get('validation_state')}'"
        
        assert derived_state.get("needs_review") == False, \
            f"Expected needs_review=False, got '{derived_state.get('needs_review')}'"
        
        print("PASS: Posted decision correctly sets workflow_state='completed', validation_state='pass'")


class TestDerivedStateLegacyFallback:
    """Test legacy fallback correctly handles ReadyForPost status"""
    
    @pytest.fixture(autouse=True)
    def setup_test_document(self, db):
        """Create a test document with ReadyForPost status but NO workflow_events (legacy)"""
        self.doc_id = f"TEST_legacy_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        
        test_doc = {
            "id": self.doc_id,
            "file_name": f"test_legacy_{self.doc_id}.pdf",
            "document_type": "AP_Invoice",
            "status": "ReadyForPost",
            "workflow_status": "ready_for_post",
            "auto_cleared": True,
            "created_utc": now,
            "updated_utc": now,
            "source": "test",
            # NO workflow_events - forces legacy fallback
        }
        
        db.hub_documents.insert_one(test_doc)
        # Don't insert any events - this forces legacy fallback
        yield
        db.hub_documents.delete_one({"id": self.doc_id})
    
    def test_legacy_readyforpost_derived_state(self, api_client):
        """Legacy ReadyForPost status should map to validation_state='pass', workflow_state='ready'"""
        response = api_client.get(f"{BASE_URL}/api/documents/{self.doc_id}")
        assert response.status_code == 200
        
        data = response.json()
        derived_state = data.get("derived_state", {})
        
        # Should use legacy fallback
        assert derived_state.get("derived_from") == "legacy", \
            f"Expected derived_from='legacy', got '{derived_state.get('derived_from')}'"
        
        assert derived_state.get("validation_state") == "pass", \
            f"Expected validation_state='pass', got '{derived_state.get('validation_state')}'"
        
        assert derived_state.get("workflow_state") == "ready", \
            f"Expected workflow_state='ready', got '{derived_state.get('workflow_state')}'"
        
        print("PASS: Legacy ReadyForPost status correctly maps to validation_state='pass', workflow_state='ready'")


class TestDerivedStateAutoClearBackwardCompat:
    """Test auto_clear=True without decision still maps to workflow_state=completed (backward compat)"""
    
    @pytest.fixture(autouse=True)
    def setup_test_document(self, db):
        """Create a test document with auto_clear=True but no decision field"""
        self.doc_id = f"TEST_autoclear_{uuid.uuid4().hex[:8]}"
        base_time = datetime.now(timezone.utc)
        
        test_doc = {
            "id": self.doc_id,
            "file_name": f"test_autoclear_{self.doc_id}.pdf",
            "document_type": "AP_Invoice",
            "status": "Completed",
            "workflow_status": "completed",
            "auto_cleared": True,
            "created_utc": base_time.isoformat(),
            "updated_utc": base_time.isoformat(),
            "source": "test",
        }
        
        db.hub_documents.insert_one(test_doc)
        
        # Insert events into workflow_events collection with different timestamps
        events = [
            {
                "event_id": f"evt_{uuid.uuid4().hex[:8]}",
                "document_id": self.doc_id,
                "event_type": "document.received",
                "timestamp": (base_time - timedelta(minutes=2)).isoformat(),
                "source_service": "intake",
                "payload": {}
            },
            {
                "event_id": f"evt_{uuid.uuid4().hex[:8]}",
                "document_id": self.doc_id,
                "event_type": "automation.decision.completed",
                "timestamp": (base_time - timedelta(minutes=1)).isoformat(),
                "source_service": "auto_clear",
                "payload": {
                    # No decision field - just auto_clear
                    "auto_clear": True,
                    "reason": "Auto-cleared by system"
                }
            }
        ]
        
        for event in events:
            db.workflow_events.insert_one(event)
        
        yield
        db.hub_documents.delete_one({"id": self.doc_id})
        db.workflow_events.delete_many({"document_id": self.doc_id})
    
    def test_autoclear_backward_compat(self, api_client):
        """auto_clear=True without decision should still set workflow_state='completed'"""
        response = api_client.get(f"{BASE_URL}/api/documents/{self.doc_id}")
        assert response.status_code == 200
        
        data = response.json()
        derived_state = data.get("derived_state", {})
        
        assert derived_state.get("workflow_state") == "completed", \
            f"Expected workflow_state='completed', got '{derived_state.get('workflow_state')}'"
        
        assert derived_state.get("validation_state") == "pass", \
            f"Expected validation_state='pass', got '{derived_state.get('validation_state')}'"
        
        print("PASS: auto_clear=True without decision correctly sets workflow_state='completed'")


class TestCleanup:
    """Cleanup any remaining test documents"""
    
    def test_cleanup_test_documents(self, db):
        """Remove all TEST_ prefixed documents"""
        result = db.hub_documents.delete_many({"id": {"$regex": "^TEST_"}})
        events_result = db.workflow_events.delete_many({"document_id": {"$regex": "^TEST_"}})
        print(f"Cleaned up {result.deleted_count} test documents and {events_result.deleted_count} test events")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
