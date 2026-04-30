"""Live HTTP integration tests for v2.5.7 retroactive post-process sweep.

Seeds ephemeral TEST_iter229_* docs directly in MongoDB (via pymongo),
hits the real preview-env endpoints, verifies behaviour, then cleans up.
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://contract-intel-9.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "gpi_document_hub")

PP_BASE = f"{BASE_URL}/api/admin/unknown-doc-reclaim/post-process"

TAG = "TEST_iter229_pp"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _reclaimed(doc_id, **over):
    base = {
        "id": doc_id,
        "doc_type": "Unknown",
        "document_type": "Unknown",
        "suggested_job_type": "Unknown",
        "status": "NeedsReview",
        "workflow_status": "needs_review",
        "queue_visible": True,
        "auto_cleared": True,
        "auto_cleared_at": _now(),
        "file_name": f"{doc_id}.pdf",
        "reclaim_to_needs_review_at": _now(),
        "reclaim_actor": "iter229",
        "bc_purchase_invoice_no": None,
        "bc_record_no": None,
        "bc_document_no": None,
        "bc_record_id": None,
        "_iter229": TAG,
    }
    base.update(over)
    return base


def _parent(doc_id, doc_type="AP_Invoice", vendor="TUMALOC"):
    return {
        "id": doc_id,
        "doc_type": doc_type,
        "document_type": doc_type,
        "suggested_job_type": doc_type,
        "vendor_canonical": vendor,
        "status": "Completed",
        "_iter229": TAG,
    }


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    # safety-net cleanup before + after
    db.hub_documents.delete_many({"_iter229": TAG})
    db.unknown_doc_reclaim_post_process_runs.delete_many({"actor": {"$regex": "^iter229"}})
    yield db
    db.hub_documents.delete_many({"_iter229": TAG})
    db.unknown_doc_reclaim_post_process_runs.delete_many({"actor": {"$regex": "^iter229"}})
    client.close()


@pytest.fixture
def seed(mongo):
    """Per-test clean slate + seed."""
    mongo.hub_documents.delete_many({"_iter229": TAG})

    def _do(docs):
        if docs:
            mongo.hub_documents.insert_many(docs)
    yield _do
    mongo.hub_documents.delete_many({"_iter229": TAG})


# ─── 1. dry-run shape + non-mutation ───
def test_dry_run_shape_and_no_mutation(seed, mongo):
    suffix = uuid.uuid4().hex[:6]
    docs = [
        _parent(f"TEST_iter229_pp_P_{suffix}", vendor="TUMALOC"),
        _reclaimed(f"TEST_iter229_pp_N_{suffix}", file_name="linkedin_32x32.png"),
        _reclaimed(f"TEST_iter229_pp_I_{suffix}", batch_parent_id=f"TEST_iter229_pp_P_{suffix}"),
        _reclaimed(f"TEST_iter229_pp_S_{suffix}", file_name="realdoc.pdf"),
    ]
    seed(docs)

    r = requests.post(f"{PP_BASE}?execute=false&smart=true&skip_noise=true", timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["execute"] is False
    assert body["total_candidates"] >= 3  # our 3 + any real prod candidates
    assert "would_filter_noise" in body and "would_inherit" in body and "would_stamp_only" in body
    assert body["modes"] == {"smart": True, "skip_noise": True}
    assert "sample" in body and set(body["sample"].keys()) >= {"noise_ids", "inherit_ids", "stamp_ids"}

    # None of our seeded docs were mutated
    for did in [f"TEST_iter229_pp_N_{suffix}", f"TEST_iter229_pp_I_{suffix}", f"TEST_iter229_pp_S_{suffix}"]:
        d = mongo.hub_documents.find_one({"id": did})
        assert d is not None
        assert d.get("post_process_applied_at") in (None, "", False)
        assert d.get("noise_filtered") is not True


# ─── 2. execute + skip_noise ───
def test_execute_skip_noise_reverts_out_of_queue(seed, mongo):
    suffix = uuid.uuid4().hex[:6]
    noise_id = f"TEST_iter229_pp_noise_{suffix}"
    ok_id = f"TEST_iter229_pp_ok_{suffix}"
    seed([
        _reclaimed(noise_id, file_name="cmn_abcd1234.png"),
        _reclaimed(ok_id, file_name="Invoice-42.pdf"),
    ])

    r = requests.post(
        f"{PP_BASE}?execute=true&skip_noise=true&actor=iter229_noise",
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["execute"] is True
    assert body["filtered_noise_count"] >= 1
    # ok doc gets stamped (no noise, no parent)
    assert body["stamped_only_count"] >= 1

    n = mongo.hub_documents.find_one({"id": noise_id})
    assert n["noise_filtered"] is True
    assert n["status"] == "Completed"
    assert n["queue_visible"] is False
    assert n["post_process_applied_at"]
    hist_events = [h.get("event") for h in n.get("workflow_history", [])]
    assert "post_process_noise_filtered" in hist_events

    ok = mongo.hub_documents.find_one({"id": ok_id})
    assert ok["status"] == "NeedsReview"
    assert ok["post_process_applied_at"]  # stamp-only


# ─── 3. execute + smart (inheritance) ───
def test_execute_smart_inherits_parent(seed, mongo):
    suffix = uuid.uuid4().hex[:6]
    parent_id = f"TEST_iter229_pp_Psm_{suffix}"
    child_id = f"TEST_iter229_pp_Csm_{suffix}"
    seed([
        _parent(parent_id, doc_type="AP_Invoice", vendor="TUMALOC"),
        _reclaimed(child_id, batch_parent_id=parent_id),
    ])

    r = requests.post(
        f"{PP_BASE}?execute=true&smart=true&actor=iter229_smart",
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inherited_count"] >= 1

    c = mongo.hub_documents.find_one({"id": child_id})
    assert c["doc_type"] == "AP_Invoice"
    assert c["vendor_canonical"] == "TUMALOC"
    assert c["parent_inheritance_applied"] is True
    assert c["parent_inheritance_source"] == "reclaim_post_process"
    assert c["status"] == "NeedsReview"  # enriched, not reverted
    assert c["doc_type_from_reclaim_ai"] == "Unknown"
    assert c["post_process_applied_at"]


# ─── 4. noise wins over smart ───
def test_noise_wins_over_smart(seed, mongo):
    suffix = uuid.uuid4().hex[:6]
    parent_id = f"TEST_iter229_pp_Pcn_{suffix}"
    child_id = f"TEST_iter229_pp_CN_{suffix}"
    seed([
        _parent(parent_id, vendor="CARGOMO"),
        _reclaimed(child_id, batch_parent_id=parent_id, file_name="cmn_abcd1234.png"),
    ])

    r = requests.post(
        f"{PP_BASE}?execute=true&smart=true&skip_noise=true&actor=iter229_combo",
        timeout=30,
    )
    assert r.status_code == 200, r.text
    c = mongo.hub_documents.find_one({"id": child_id})
    assert c["noise_filtered"] is True
    assert c["status"] == "Completed"
    assert c.get("parent_inheritance_applied") is not True


# ─── 5. idempotency ───
def test_second_run_picks_zero_for_our_docs(seed, mongo):
    suffix = uuid.uuid4().hex[:6]
    stamp_id = f"TEST_iter229_pp_idem_{suffix}"
    seed([_reclaimed(stamp_id, file_name=f"real-{suffix}.pdf")])

    r1 = requests.post(f"{PP_BASE}?execute=true&actor=iter229_idem1", timeout=30)
    assert r1.status_code == 200
    c1 = mongo.hub_documents.find_one({"id": stamp_id})
    assert c1["post_process_applied_at"]

    # Second run: our doc must NOT be in the candidate set anymore
    r2 = requests.post(f"{PP_BASE}?execute=true&actor=iter229_idem2", timeout=30)
    assert r2.status_code == 200
    body2 = r2.json()
    # our doc's applied_at is unchanged
    c2 = mongo.hub_documents.find_one({"id": stamp_id})
    assert c2["post_process_applied_at"] == c1["post_process_applied_at"]


# ─── 6. safety: no reclaim_to_needs_review_at → never touched ───
def test_organic_needs_review_doc_never_touched(seed, mongo):
    suffix = uuid.uuid4().hex[:6]
    organic_id = f"TEST_iter229_pp_organic_{suffix}"
    organic = {
        "id": organic_id,
        "doc_type": "Unknown",
        "document_type": "Unknown",
        "suggested_job_type": "Unknown",
        "status": "NeedsReview",
        "workflow_status": "needs_review",
        "queue_visible": True,
        "file_name": "organic.pdf",
        "reclaim_to_needs_review_at": None,  # never reclaimed
        "_iter229": TAG,
    }
    seed([organic])

    r = requests.post(f"{PP_BASE}?execute=true&smart=true&skip_noise=true&actor=iter229_safety", timeout=30)
    assert r.status_code == 200

    d = mongo.hub_documents.find_one({"id": organic_id})
    assert d.get("post_process_applied_at") in (None, "", False)
    assert d.get("noise_filtered") is not True
    assert d.get("parent_inheritance_applied") is not True


# ─── 7. safety: BC evidence present → never touched ───
def test_bc_evidence_blocks_post_process(seed, mongo):
    suffix = uuid.uuid4().hex[:6]
    bc_id = f"TEST_iter229_pp_bc_{suffix}"
    seed([_reclaimed(bc_id, bc_purchase_invoice_no="PI-12345")])

    r = requests.post(f"{PP_BASE}?execute=true&smart=true&skip_noise=true&actor=iter229_bc", timeout=30)
    assert r.status_code == 200
    d = mongo.hub_documents.find_one({"id": bc_id})
    assert d.get("post_process_applied_at") in (None, "", False)


# ─── 8. safety: already-resolved docs never touched ───
def test_resolved_doc_never_touched(seed, mongo):
    suffix = uuid.uuid4().hex[:6]
    resolved_id = f"TEST_iter229_pp_res_{suffix}"
    seed([_reclaimed(
        resolved_id,
        status="Completed",
        workflow_status="completed",
        queue_visible=False,
    )])

    r = requests.post(f"{PP_BASE}?execute=true&smart=true&skip_noise=true&actor=iter229_res", timeout=30)
    assert r.status_code == 200
    d = mongo.hub_documents.find_one({"id": resolved_id})
    assert d.get("post_process_applied_at") in (None, "", False)


# ─── 9. audit runs endpoint ───
def test_post_process_runs_endpoint():
    r = requests.get(f"{PP_BASE}/runs?limit=20", timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body and "runs" in body
    assert isinstance(body["runs"], list)
    # We expect at least one run from the tests above (post_process insert works)
    # Note: previous tests with execute=true would have logged here
    actors = {run.get("actor") for run in body["runs"]}
    # Not strict assertion: preview env is shared, but structure must be right
    for run in body["runs"]:
        assert "generated_at" in run or "ran_at" in run
        assert "processed" in run or "total_candidates" in run


# ─── 10. regression: related endpoints still 200 ───
@pytest.mark.parametrize("path", [
    "/api/dashboard/inbox-stats",
    "/api/learning/pattern-health/unified",
    "/api/admin/unknown-doc-reclaim/preview",
    "/api/admin/unknown-doc-reclaim/runs",
])
def test_regression_related_endpoints_200(path):
    r = requests.get(f"{BASE_URL}{path}", timeout=30)
    assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"
