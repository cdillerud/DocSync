"""HTTP integration tests for v2.5.6 smart + skip_noise reclaim modes.

Uses the live preview DB through REACT_APP_BACKEND_URL. Seeds ephemeral
test docs prefixed TEST_iter228_* per test (function scope) so scenarios
are isolated. Cleanup at teardown.
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")


def _now():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    # Final safety net: delete any lingering TEST_iter228_* docs
    client[DB_NAME].hub_documents.delete_many(
        {"id": {"$regex": "^TEST_iter228_"}}
    )
    client[DB_NAME].unknown_doc_reclaim_runs.delete_many(
        {"actor": {"$regex": "^TEST_iter228_"}}
    )
    client.close()


def _candidate(doc_id, **overrides):
    now = _now()
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
    doc.update(overrides)
    return doc


def _parent(doc_id, doc_type="AP_Invoice", vendor="TEST_iter228_VENDOR"):
    return {
        "id": doc_id,
        "doc_type": doc_type,
        "document_type": doc_type,
        "suggested_job_type": doc_type,
        "vendor_canonical": vendor,
        "status": "Completed",
        "auto_cleared": False,
    }


@pytest.fixture
def scenario(mongo_db, request):
    """Per-test seeder. Usage:
        ids = scenario([("parent", {...}), ("cand", {...}), ...])
    Cleans up all inserted ids on teardown regardless of mutations.
    """
    inserted_ids = []

    def _seed(docs):
        if docs:
            mongo_db.hub_documents.insert_many(docs)
            inserted_ids.extend(d["id"] for d in docs)
        return [d["id"] for d in docs]

    yield _seed
    if inserted_ids:
        mongo_db.hub_documents.delete_many({"id": {"$in": inserted_ids}})


def _new_id(tag):
    return f"TEST_iter228_{tag}_{uuid.uuid4().hex[:8]}"


# ────────── PREVIEW: flag surface ──────────

def test_preview_without_flags_nulls_mode_counters():
    r = requests.get(f"{BASE_URL}/api/admin/unknown-doc-reclaim/preview?limit=5")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["modes"] == {"smart": False, "skip_noise": False}
    assert j["sample_breakdown"]["smart_inheritable"] is None
    assert j["sample_breakdown"]["filtered_as_noise"] is None


def test_preview_with_flags_returns_ints_and_is_non_mutating(scenario, mongo_db):
    p_id = _new_id("p")
    inh_id = _new_id("inh")
    noise_id = _new_id("noise")
    plain_id = _new_id("plain")
    scenario([
        _parent(p_id),
        _candidate(inh_id, batch_parent_id=p_id, vendor_canonical=None),
        _candidate(noise_id, file_name="linkedin_32x32_preview.png"),
        _candidate(plain_id),
    ])
    r = requests.get(
        f"{BASE_URL}/api/admin/unknown-doc-reclaim/preview"
        f"?limit=500&smart=true&skip_noise=true"
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["modes"] == {"smart": True, "skip_noise": True}
    assert isinstance(j["sample_breakdown"]["smart_inheritable"], int)
    assert isinstance(j["sample_breakdown"]["filtered_as_noise"], int)
    assert j["sample_breakdown"]["smart_inheritable"] >= 1
    assert j["sample_breakdown"]["filtered_as_noise"] >= 1

    # Non-mutating
    for did in (inh_id, noise_id, plain_id):
        d = mongo_db.hub_documents.find_one({"id": did})
        assert d["status"] == "Completed", f"{did} mutated by preview"
        assert d.get("reclaim_to_needs_review_at") in (None, "", False)


# ────────── SMART MODE ──────────

def test_smart_mode_child_inherits_parent(scenario, mongo_db):
    p_id = _new_id("p")
    inh_id = _new_id("inh")
    scenario([
        _parent(p_id, doc_type="AP_Invoice", vendor="TEST_iter228_TUMALOC"),
        _candidate(inh_id, batch_parent_id=p_id, vendor_canonical=None),
    ])
    r = requests.post(
        f"{BASE_URL}/api/admin/unknown-doc-reclaim/run"
        f"?execute=true&smart=true&limit=500&actor=TEST_iter228_smart"
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["execute"] is True
    assert j["modes"] == {"smart": True, "skip_noise": False}
    for k in (
        "reclaimed_plain_count", "reclaimed_inherited_count",
        "filtered_noise_count", "total_mutated", "reclaimed_count",
    ):
        assert k in j, f"missing {k}"
    assert j["reclaimed_inherited_count"] >= 1

    child = mongo_db.hub_documents.find_one({"id": inh_id})
    assert child["status"] == "NeedsReview"
    assert child["parent_inheritance_applied"] is True
    assert child["doc_type"] == "AP_Invoice"
    assert child["document_type"] == "AP_Invoice"
    assert child["suggested_job_type"] == "AP_Invoice"
    assert child["vendor_canonical"] == "TEST_iter228_TUMALOC"
    assert child["vendor_inherited_from_parent"] is True
    assert child["doc_type_from_reclaim_ai"] == "Unknown"


def test_smart_mode_no_parent_plain_path(scenario, mongo_db):
    plain_id = _new_id("plain")
    scenario([_candidate(plain_id)])
    r = requests.post(
        f"{BASE_URL}/api/admin/unknown-doc-reclaim/run"
        f"?execute=true&smart=true&limit=500&actor=TEST_iter228_smartplain"
    )
    assert r.status_code == 200
    d = mongo_db.hub_documents.find_one({"id": plain_id})
    assert d["status"] == "NeedsReview"
    assert d.get("parent_inheritance_applied") is not True
    assert d["doc_type"] == "Unknown"


# ────────── SKIP_NOISE MODE ──────────

def test_skip_noise_filters_linkedin_sprite(scenario, mongo_db):
    noise_id = _new_id("noise")
    real_id = _new_id("real")
    scenario([
        _candidate(noise_id, file_name="linkedin_32x32_abc.png"),
        _candidate(real_id, file_name="Invoice-0493680.pdf"),
    ])
    r = requests.post(
        f"{BASE_URL}/api/admin/unknown-doc-reclaim/run"
        f"?execute=true&skip_noise=true&limit=500&actor=TEST_iter228_noise"
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["modes"] == {"smart": False, "skip_noise": True}
    assert j["filtered_noise_count"] >= 1

    noise = mongo_db.hub_documents.find_one({"id": noise_id})
    assert noise["noise_filtered"] is True
    assert noise["status"] == "Completed"
    assert noise["queue_visible"] is False
    assert noise.get("reclaim_to_needs_review_at")  # idempotency sentinel

    real = mongo_db.hub_documents.find_one({"id": real_id})
    assert real["status"] == "NeedsReview"
    assert real.get("noise_filtered") is not True


# ────────── COMBINED: noise wins over smart ──────────

def test_noise_wins_over_smart_under_classified_parent(scenario, mongo_db):
    p_id = _new_id("p")
    np_id = _new_id("np")
    scenario([
        _parent(p_id, doc_type="AP_Invoice", vendor="TEST_iter228_CARGOMO"),
        _candidate(
            np_id,
            batch_parent_id=p_id,
            file_name=f"cmn_{uuid.uuid4().hex[:12]}.png",
        ),
    ])
    r = requests.post(
        f"{BASE_URL}/api/admin/unknown-doc-reclaim/run"
        f"?execute=true&smart=true&skip_noise=true&limit=500&actor=TEST_iter228_combo"
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["modes"] == {"smart": True, "skip_noise": True}
    # total_mutated bookkeeping
    assert j["total_mutated"] == (
        j["reclaimed_plain_count"]
        + j["reclaimed_inherited_count"]
        + j["filtered_noise_count"]
    )
    # Legacy field excludes noise
    assert j["reclaimed_count"] == (
        j["reclaimed_plain_count"] + j["reclaimed_inherited_count"]
    )
    assert j["filtered_noise_count"] >= 1

    np_doc = mongo_db.hub_documents.find_one({"id": np_id})
    assert np_doc["noise_filtered"] is True
    assert np_doc["status"] == "Completed"
    assert np_doc.get("parent_inheritance_applied") is not True
    assert np_doc["doc_type"] == "Unknown"  # NOT inherited


# ────────── IDEMPOTENCY ──────────

def test_idempotent_second_run_no_re_pick(scenario, mongo_db):
    plain_id = _new_id("idem")
    noise_id = _new_id("idemnoise")
    scenario([
        _candidate(plain_id),
        _candidate(noise_id, file_name="image.png"),
    ])
    r1 = requests.post(
        f"{BASE_URL}/api/admin/unknown-doc-reclaim/run"
        f"?execute=true&smart=true&skip_noise=true&limit=500&actor=TEST_iter228_idem1"
    )
    assert r1.status_code == 200
    # Snapshot the just-processed docs' reclaim timestamps
    p_before = mongo_db.hub_documents.find_one({"id": plain_id})
    n_before = mongo_db.hub_documents.find_one({"id": noise_id})
    p_ts = p_before["reclaim_to_needs_review_at"]
    n_ts = n_before["reclaim_to_needs_review_at"]
    assert p_ts and n_ts

    r2 = requests.post(
        f"{BASE_URL}/api/admin/unknown-doc-reclaim/run"
        f"?execute=true&smart=true&skip_noise=true&limit=500&actor=TEST_iter228_idem2"
    )
    assert r2.status_code == 200
    # Seeded docs must not have their timestamps overwritten
    p_after = mongo_db.hub_documents.find_one({"id": plain_id})
    n_after = mongo_db.hub_documents.find_one({"id": noise_id})
    assert p_after["reclaim_to_needs_review_at"] == p_ts
    assert n_after["reclaim_to_needs_review_at"] == n_ts


# ────────── REGRESSION: defaults = v2.5.5 ──────────

def test_defaults_behave_like_v255(scenario, mongo_db):
    """smart=false + skip_noise=false: only plain-reclaim path active.
    No parent_inheritance_applied / noise_filtered fields on any mutated doc."""
    p_id = _new_id("p")
    inh_id = _new_id("v255inh")
    noise_id = _new_id("v255noise")
    scenario([
        _parent(p_id, doc_type="AP_Invoice", vendor="TEST_iter228_V"),
        _candidate(inh_id, batch_parent_id=p_id),
        _candidate(noise_id, file_name="linkedin_32x32_v255.png"),
    ])
    r = requests.post(
        f"{BASE_URL}/api/admin/unknown-doc-reclaim/run"
        f"?execute=true&limit=500&actor=TEST_iter228_v255"
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["modes"] == {"smart": False, "skip_noise": False}
    # Default run: inherited + noise counters stay 0 for seeded docs
    assert j["reclaimed_inherited_count"] == 0
    assert j["filtered_noise_count"] == 0
    # Plain count incremented by at least our 2 docs
    assert j["reclaimed_plain_count"] >= 2

    # Inheritable child: should be plain-reclaimed WITHOUT inheritance fields
    child = mongo_db.hub_documents.find_one({"id": inh_id})
    assert child["status"] == "NeedsReview"
    assert child.get("parent_inheritance_applied") is not True
    assert child["doc_type"] == "Unknown"  # NOT inherited

    # Noise-filename doc: goes to NeedsReview in v2.5.5 defaults (bug the
    # v2.5.6 skip_noise flag fixes).
    noise = mongo_db.hub_documents.find_one({"id": noise_id})
    assert noise["status"] == "NeedsReview"
    assert noise.get("noise_filtered") is not True


def test_defaults_dry_run_response_shape():
    r = requests.post(f"{BASE_URL}/api/admin/unknown-doc-reclaim/run")
    assert r.status_code == 200
    j = r.json()
    assert j["execute"] is False
    assert j["modes"] == {"smart": False, "skip_noise": False}
    assert j["sample_breakdown"]["smart_inheritable"] is None
    assert j["sample_breakdown"]["filtered_as_noise"] is None


# ────────── REGRESSION: unrelated endpoints still 200 ──────────

def test_dashboard_inbox_stats_still_200():
    r = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
    assert r.status_code == 200, r.text


def test_learning_pattern_health_unified_still_200():
    r = requests.get(f"{BASE_URL}/api/learning/pattern-health/unified")
    assert r.status_code == 200, r.text
