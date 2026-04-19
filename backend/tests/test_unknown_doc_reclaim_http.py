"""HTTP integration tests for the Unknown-Doc Reclaim endpoints (v2.5.5).

Uses the live preview DB through REACT_APP_BACKEND_URL.
IMPORTANT: These tests mutate real preview-env documents intentionally.
A test seed doc (TEST_iter227_*) is added and cleaned up at end.
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def seed_doc(mongo_db):
    """Seed one clean test candidate to guarantee at least one doc in the
    reclaim candidate set. Cleaned up after tests."""
    doc_id = f"TEST_iter227_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": doc_id,
        "doc_type": "Unknown",
        "document_type": "Unknown",
        "suggested_job_type": "Unknown",
        "status": "Completed",
        "workflow_status": "exported",
        "auto_cleared": True,
        "auto_cleared_at": now,
        "file_name": f"{doc_id}.pdf",
        "bc_purchase_invoice_no": None,
        "bc_record_no": None,
        "bc_document_no": None,
        "bc_record_id": None,
        "reclaim_to_needs_review_at": None,
        "queue_visible": False,
        "created_utc": now,
    }
    mongo_db.hub_documents.insert_one(doc)
    yield doc_id
    # Cleanup
    mongo_db.hub_documents.delete_one({"id": doc_id})


@pytest.fixture(scope="module")
def seed_bc_safe_doc(mongo_db):
    """Seed a doc with BC evidence — must NEVER be reclaimed."""
    doc_id = f"TEST_iter227_bcsafe_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": doc_id,
        "doc_type": "Unknown",
        "document_type": "Unknown",
        "suggested_job_type": "Unknown",
        "status": "Completed",
        "workflow_status": "exported",
        "auto_cleared": True,
        "bc_purchase_invoice_no": "TEST_PI-iter227",
        "reclaim_to_needs_review_at": None,
        "created_utc": now,
    }
    mongo_db.hub_documents.insert_one(doc)
    yield doc_id
    mongo_db.hub_documents.delete_one({"id": doc_id})


@pytest.fixture(scope="module")
def seed_known_type_doc(mongo_db):
    """Seed a doc with a known doc_type — must NEVER be reclaimed."""
    doc_id = f"TEST_iter227_ap_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": doc_id,
        "doc_type": "AP_Invoice",
        "document_type": "AP_Invoice",
        "suggested_job_type": "AP_Invoice",
        "status": "Completed",
        "workflow_status": "exported",
        "auto_cleared": True,
        "reclaim_to_needs_review_at": None,
        "created_utc": now,
    }
    mongo_db.hub_documents.insert_one(doc)
    yield doc_id
    mongo_db.hub_documents.delete_one({"id": doc_id})


class TestReclaimHTTP:
    def test_preview_returns_expected_shape(self, seed_doc):
        r = requests.get(f"{BASE_URL}/api/admin/unknown-doc-reclaim/preview")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "total_candidates" in data
        assert "sample_size" in data
        assert "sample_breakdown" in data
        assert "sample" in data
        assert isinstance(data["total_candidates"], int)
        assert data["total_candidates"] >= 1  # our seeded test doc at minimum
        # Our seeded doc should appear in the sample
        sample_ids = {d.get("id") for d in data["sample"]}
        assert seed_doc in sample_ids, f"Seeded test doc not in sample: {sample_ids}"

    def test_run_dry_run_is_zero_writes(self, seed_doc, mongo_db):
        before = mongo_db.hub_documents.find_one({"id": seed_doc}, {"_id": 0})
        r = requests.post(f"{BASE_URL}/api/admin/unknown-doc-reclaim/run")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("execute") is False
        assert "hint" in data
        assert "total_candidates" in data

        # Confirm doc unchanged
        after = mongo_db.hub_documents.find_one({"id": seed_doc}, {"_id": 0})
        assert after["status"] == before["status"] == "Completed"
        assert after.get("reclaim_to_needs_review_at") in (None, "", False)

    def test_run_execute_limit1_mutates_one_doc(self, seed_doc, seed_bc_safe_doc,
                                                 seed_known_type_doc, mongo_db):
        # Capture preview count first
        pre = requests.get(f"{BASE_URL}/api/admin/unknown-doc-reclaim/preview").json()
        pre_count = pre["total_candidates"]

        r = requests.post(
            f"{BASE_URL}/api/admin/unknown-doc-reclaim/run",
            params={"execute": "true", "limit": 1, "actor": "ci_test"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["execute"] is True
        assert data["actor"] == "ci_test"
        assert data["limit_applied"] == 1
        assert data["reclaimed_count"] == 1
        assert len(data["reclaimed_ids"]) == 1

        reclaimed_id = data["reclaimed_ids"][0]
        doc = mongo_db.hub_documents.find_one({"id": reclaimed_id}, {"_id": 0})
        assert doc["status"] == "NeedsReview"
        assert doc["workflow_status"] == "needs_review"
        assert doc["queue_visible"] is True
        assert doc["reclaim_to_needs_review_at"]
        assert doc["reclaim_actor"] == "ci_test"
        # workflow_history has the reclaim event
        assert any(h.get("event") == "reclaim_to_needs_review"
                   for h in doc.get("workflow_history", []))

        # Safety: BC-evidence and known-type docs must remain untouched
        bc_doc = mongo_db.hub_documents.find_one({"id": seed_bc_safe_doc}, {"_id": 0})
        assert bc_doc["status"] == "Completed"
        assert bc_doc.get("reclaim_to_needs_review_at") in (None, "", False)

        ap_doc = mongo_db.hub_documents.find_one({"id": seed_known_type_doc}, {"_id": 0})
        assert ap_doc["status"] == "Completed"
        assert ap_doc.get("reclaim_to_needs_review_at") in (None, "", False)

        # preview count should have decreased by 1
        post = requests.get(f"{BASE_URL}/api/admin/unknown-doc-reclaim/preview").json()
        assert post["total_candidates"] == pre_count - 1

        # Store for idempotency test
        pytest.reclaimed_id = reclaimed_id

    def test_idempotency_second_execute_does_not_reclaim_same_docs(self, mongo_db):
        # Run again — the already-reclaimed doc must NOT be re-picked.
        reclaimed_id = getattr(pytest, "reclaimed_id", None)
        assert reclaimed_id, "Previous test did not set reclaimed_id"

        # Get the current preview count before second execute
        pre = requests.get(f"{BASE_URL}/api/admin/unknown-doc-reclaim/preview").json()
        # We expect only docs remaining that haven't been reclaimed yet.
        # Previously reclaimed id must NOT appear in preview anymore.
        assert reclaimed_id not in {d.get("id") for d in pre["sample"]}

        # Re-run execute against just that id's candidacy — since it has
        # reclaim_to_needs_review_at set, it should not be picked up.
        # Use limit=0... but endpoint requires ge=1. Use limit=1 and verify
        # it doesn't mutate our already-reclaimed doc.
        doc_before = mongo_db.hub_documents.find_one({"id": reclaimed_id},
                                                     {"_id": 0, "status": 1,
                                                      "reclaim_to_needs_review_at": 1})

        # Only re-run execute=true (unbounded) if preview has 0 remaining,
        # else it would legitimately reclaim other real docs. Pass limit=1.
        if pre["total_candidates"] > 0:
            # It's fine — there are still other candidates. Just verify our
            # already-reclaimed doc is not among them.
            pass
        r = requests.post(
            f"{BASE_URL}/api/admin/unknown-doc-reclaim/run",
            params={"execute": "true", "limit": 1, "actor": "ci_test_idem"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # The already-reclaimed doc must not be in the new reclaimed_ids
        assert reclaimed_id not in data.get("reclaimed_ids", [])

        # And its state is unchanged
        doc_after = mongo_db.hub_documents.find_one({"id": reclaimed_id},
                                                    {"_id": 0, "status": 1,
                                                     "reclaim_to_needs_review_at": 1})
        assert doc_after["status"] == "NeedsReview"
        assert doc_after["reclaim_to_needs_review_at"] == doc_before["reclaim_to_needs_review_at"]

    def test_runs_endpoint_lists_recent(self):
        r = requests.get(f"{BASE_URL}/api/admin/unknown-doc-reclaim/runs")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "total" in data
        assert "runs" in data
        assert isinstance(data["runs"], list)
        # Our ci_test run should be at/near the top
        actors = [r.get("actor") for r in data["runs"][:5]]
        assert "ci_test" in actors or "ci_test_idem" in actors, \
            f"ci_test run not found in top-5 actors: {actors}"


class TestRegressionStillOK:
    def test_inbox_stats_still_200(self):
        r = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        assert r.status_code == 200, r.text

    def test_pattern_health_unified_still_200(self):
        r = requests.get(f"{BASE_URL}/api/learning/pattern-health/unified")
        assert r.status_code == 200, r.text
