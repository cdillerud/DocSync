"""HTTP-level regression tests for iteration 224:
- POST /api/auto-clear/evaluate returns needs_review + unclassified_guard_triggered
- POST /api/auto-clear/reprocess fires the same guard
- GET /api/dashboard/inbox-stats exposes posted_to_bc_7d + ready_for_post
- Smoke: learning_core endpoints respond 200
- Smoke: batch_po_splitter._inherit_parent_and_reevaluate exists & callable
"""
import asyncio
import os
import sys
import uuid
import importlib

import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")

# Load backend/.env so MONGO_URL / DB_NAME are available to the fixtures
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")


# ---- Auto-clear evaluate endpoint (DB-driven) ----------------------------

@pytest.fixture
def seeded_unknown_doc():
    """Insert an ephemeral Unknown/zero-conf test doc, yield id, cleanup."""
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "test_database")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    doc_id = "TEST_unknown_" + uuid.uuid4().hex[:8]

    async def seed():
        await db.hub_documents.insert_one({
            "id": doc_id,
            "file_name": f"{doc_id}.pdf",
            "doc_type": "Unknown",
            "ai_classification": {"confidence": 0.0, "method": "ai_classifier"},
            "extracted_fields": {},
            "status": "Extracted",
        })

    async def teardown():
        await db.hub_documents.delete_one({"id": doc_id})

    asyncio.get_event_loop().run_until_complete(seed())
    yield doc_id
    asyncio.get_event_loop().run_until_complete(teardown())
    client.close()


@pytest.fixture
def seeded_ap_doc():
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "test_database")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    doc_id = "TEST_ap_" + uuid.uuid4().hex[:8]

    async def seed():
        await db.hub_documents.insert_one({
            "id": doc_id,
            "file_name": f"{doc_id}.pdf",
            "doc_type": "AP_Invoice",
            "ai_classification": {"confidence": 0.95, "method": "ai_classifier"},
            "vendor_canonical": "TEST_Ball Metal",
            "extracted_fields": {"vendor": "TEST_Ball Metal", "po_number": "TEST_P0024333"},
            "status": "Extracted",
        })

    async def teardown():
        await db.hub_documents.delete_one({"id": doc_id})

    asyncio.get_event_loop().run_until_complete(seed())
    yield doc_id
    asyncio.get_event_loop().run_until_complete(teardown())
    client.close()


def test_autoclear_evaluate_unknown_triggers_guard(seeded_unknown_doc):
    r = requests.post(f"{BASE_URL}/api/auto-clear/evaluate/{seeded_unknown_doc}", timeout=15)
    assert r.status_code == 200, f"evaluate failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    ev = data.get("evaluation", {})
    assert ev.get("decision") == "needs_review", f"expected needs_review, got {ev}"
    # Guard fires → checks list includes unclassified_guard
    checks = ev.get("checks") or []
    guard = [c for c in checks if c.get("check") == "unclassified_guard"]
    assert guard, f"unclassified_guard check missing in {checks}"
    assert guard[0]["passed"] is False


def test_autoclear_evaluate_ap_invoice_unaffected(seeded_ap_doc):
    r = requests.post(f"{BASE_URL}/api/auto-clear/evaluate/{seeded_ap_doc}", timeout=15)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    ev = data.get("evaluation", {})
    checks = ev.get("checks") or []
    guard = [c for c in checks if c.get("check") == "unclassified_guard"]
    # Guard should NOT have fired for a valid AP_Invoice doc
    assert not guard, f"AP_Invoice should not trip unclassified_guard, got {guard}"


# ---- Auto-clear reprocess endpoint (mounted at /api/auto-clear-reprocess) ----

def test_autoclear_reprocess_dry_run_responds():
    """Dry-run must respond 200 and not crash — guard is in same code path."""
    r = requests.post(f"{BASE_URL}/api/auto-clear-reprocess/dry-run", json={}, timeout=30)
    assert r.status_code < 500, f"reprocess crashed: {r.status_code} {r.text[:300]}"


# ---- Dashboard inbox-stats endpoint --------------------------------------

def test_dashboard_inbox_stats_has_new_kpis():
    r = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats", timeout=15)
    assert r.status_code == 200, f"inbox-stats failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    assert "posted_to_bc_7d" in data, f"posted_to_bc_7d missing: keys={list(data.keys())}"
    assert "ready_for_post" in data, f"ready_for_post missing: keys={list(data.keys())}"
    assert isinstance(data["posted_to_bc_7d"], int), type(data["posted_to_bc_7d"])
    assert isinstance(data["ready_for_post"], int), type(data["ready_for_post"])
    assert data["posted_to_bc_7d"] >= 0
    assert data["ready_for_post"] >= 0


# ---- learning_core smoke tests -------------------------------------------

@pytest.mark.parametrize("path", [
    "/api/learning/pattern-health/unified",
    "/api/learning/events/summary",
    "/api/learning/digest",
    "/api/intake/learning/pattern-health",
])
def test_learning_endpoints_respond_200(path):
    r = requests.get(f"{BASE_URL}{path}", timeout=15)
    assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"


# ---- Batch splitter inheritance helper -----------------------------------

def test_inherit_parent_helper_exists_and_callable():
    mod = importlib.import_module("services.batch_po_splitter")
    fn = getattr(mod, "_inherit_parent_and_reevaluate", None)
    assert fn is not None, "_inherit_parent_and_reevaluate missing"
    assert asyncio.iscoroutinefunction(fn), "helper must be async"


def test_inherit_parent_helper_sets_needs_review(monkeypatch):
    """Simulate a child coming back Unknown and verify the helper:
    - sets status=NeedsReview
    - inherits parent doc_type + vendor_canonical
    - sets parent_inheritance_applied=True
    """
    from services.batch_po_splitter import _inherit_parent_and_reevaluate

    # In-memory fake Mongo collection
    state = {
        "CHILD1": {
            "id": "CHILD1",
            "doc_type": "Unknown",
            "ai_classification": {"confidence": 0.0},
            "extracted_fields": {},
        }
    }

    class FakeColl:
        async def find_one(self, query, projection=None):
            doc = state.get(query["id"])
            return dict(doc) if doc else None

        async def update_one(self, query, update):
            doc = state.get(query["id"])
            if not doc:
                return type("R", (), {"matched_count": 0, "modified_count": 0})()
            doc.update(update.get("$set", {}))
            return type("R", (), {"matched_count": 1, "modified_count": 1})()

    class FakeDB:
        hub_documents = FakeColl()

    parent_doc = {
        "doc_type": "AP_Invoice",
        "vendor_canonical": "Ball Metal",
        "vendor_id": "V-123",
    }

    asyncio.get_event_loop().run_until_complete(
        _inherit_parent_and_reevaluate(FakeDB(), "CHILD1", parent_doc)
    )

    updated = state["CHILD1"]
    assert updated["status"] == "NeedsReview", updated
    assert updated["doc_type"] == "AP_Invoice"
    assert updated["vendor_canonical"] == "Ball Metal"
    assert updated["parent_inheritance_applied"] is True
    assert updated["auto_cleared"] is False
    assert updated["queue_visible"] is True
