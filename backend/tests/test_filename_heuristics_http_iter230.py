"""
Live HTTP regression for v2.5.8 filename heuristics endpoints (iteration 230).
Uses pymongo for simple synchronous seeding/verification.
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TAG = "TEST_iter230"

_mc = MongoClient(MONGO_URL)
_db = _mc[DB_NAME]


def _now():
    return datetime.now(timezone.utc).isoformat()


def _mk(fname, vendor, **overrides):
    d = {
        "id": f"{TAG}_{uuid.uuid4().hex[:8]}",
        "file_name": fname,
        "vendor_canonical": vendor,
        "doc_type": "Unknown",
        "document_type": "Unknown",
        "suggested_job_type": "Unknown",
        "status": "NeedsReview",
        "created_utc": _now(),
        "reclaim_to_needs_review_at": _now(),
        "tags": [TAG],
    }
    d.update(overrides)
    return d


@pytest.fixture(scope="module")
def seeded():
    _db.hub_documents.delete_many({"tags": TAG})
    _db.filename_heuristic_runs.delete_many({"actor": {"$regex": f"^{TAG}"}})

    docs = [
        _mk("0303382.pdf", "TUMALOC"),                                # 0.85
        _mk("W117508.pdf", "GROUPWA"),                                # 0.80
        _mk("Invoice-0493680_doc1.pdf", "CARGOMO"),                   # 0.85
        _mk("112803.pdf", "Lone Star Integrated Distribution"),       # 0.75
        _mk("completely_unrecognized_thing_xyz.pdf", "NoVend"),       # unmatched
        _mk("0303382.pdf", "TUMALOC", bc_record_no="TEST-R-1"),       # BC safety
        _mk("0303382.pdf", "TUMALOC",                                 # known-type safety
            doc_type="AP_Invoice", document_type="AP_Invoice",
            suggested_job_type="AP_Invoice"),
    ]
    _db.hub_documents.insert_many(docs)
    ids = [d["id"] for d in docs]
    yield ids, docs
    _db.hub_documents.delete_many({"tags": TAG})
    _db.filename_heuristic_runs.delete_many({"actor": {"$regex": f"^{TAG}"}})


def _fetch(doc_id):
    return _db.hub_documents.find_one({"id": doc_id}, {"_id": 0})


# ── endpoint: rules ─────────────────────────────────────────────
def test_rules_endpoint():
    r = requests.get(f"{BASE}/api/admin/filename-heuristics/rules", timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 12
    assert len(body["rules"]) == 12
    for rule in body["rules"]:
        for k in ("rule_id", "filename_regex", "doc_type", "confidence", "note"):
            assert k in rule
        assert len(rule["note"]) > 10


# ── endpoint: preview ───────────────────────────────────────────
def test_preview_readonly(seeded):
    ids, _ = seeded
    r = requests.get(f"{BASE}/api/admin/filename-heuristics/preview", timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("total_candidates", "matched", "unmatched",
              "by_rule", "by_target_type", "sample_matches"):
        assert k in body
    d = _fetch(ids[0])
    assert d["doc_type"] == "Unknown"
    assert d.get("filename_heuristic_applied_at") in (None, "", False)


# ── endpoint: apply dry-run ─────────────────────────────────────
def test_apply_dryrun_default():
    r = requests.post(f"{BASE}/api/admin/filename-heuristics/apply", timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("execute") is False


# ── endpoint: apply execute=true ────────────────────────────────
def test_apply_execute_enriches(seeded):
    ids, _ = seeded
    r = requests.post(
        f"{BASE}/api/admin/filename-heuristics/apply",
        params={"execute": "true", "actor": f"{TAG}_run1", "limit": 500},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["execute"] is True
    assert body["applied_count"] >= 4  # TUMALOC+GROUPWA+CARGOMO+LoneStar
    assert body["by_target_type"].get("AP_Invoice", 0) >= 3
    assert body["by_target_type"].get("BOL", 0) >= 1

    t = _fetch(ids[0])
    assert t["doc_type"] == "AP_Invoice"
    assert t["document_type"] == "AP_Invoice"
    assert t["suggested_job_type"] == "AP_Invoice"
    assert t["doc_type_before_heuristic"] == "Unknown"
    assert t["filename_heuristic_rule"] == "tumaloc_numeric_freight"
    assert t["filename_heuristic_confidence"] == 0.85
    assert t["filename_heuristic_note"]
    assert t["filename_heuristic_applied_at"]
    assert t["filename_heuristic_applied"] is True
    assert t["status"] == "NeedsReview"  # never auto-clear
    assert any(h.get("event") == "filename_heuristic_classified"
               for h in t.get("workflow_history", []))


# ── safety: BC evidence ─────────────────────────────────────────
def test_safety_bc_evidence(seeded):
    ids, _ = seeded
    d = _fetch(ids[5])
    assert d["doc_type"] == "Unknown"
    assert d.get("filename_heuristic_applied_at") in (None, "", False)


# ── safety: known doc_type ──────────────────────────────────────
def test_safety_known_doctype(seeded):
    ids, _ = seeded
    d = _fetch(ids[6])
    assert d["doc_type"] == "AP_Invoice"
    assert d.get("filename_heuristic_rule") in (None, "", False)


# ── idempotency ─────────────────────────────────────────────────
def test_idempotency_second_run(seeded):
    ids, _ = seeded
    applied_ids_before = {
        d["id"] for d in _db.hub_documents.find(
            {"tags": TAG, "filename_heuristic_applied_at": {"$exists": True, "$ne": None}},
            {"_id": 0, "id": 1},
        )
    }
    r = requests.post(
        f"{BASE}/api/admin/filename-heuristics/apply",
        params={"execute": "true", "actor": f"{TAG}_run2", "limit": 500},
        timeout=60,
    )
    assert r.status_code == 200
    applied_sample_ids = {row["id"] for row in r.json().get("applied_sample", [])}
    overlap = applied_sample_ids & applied_ids_before
    assert not overlap, f"Re-applied to idempotent sentinel docs: {overlap}"


# ── min_confidence gating ───────────────────────────────────────
def test_min_confidence_gating():
    did = f"{TAG}_minconf_{uuid.uuid4().hex[:6]}"
    _db.hub_documents.insert_one({
        "id": did,
        "file_name": "112803.pdf",
        "vendor_canonical": "Lone Star Integrated Distribution",
        "doc_type": "Unknown",
        "document_type": "Unknown",
        "suggested_job_type": "Unknown",
        "status": "NeedsReview",
        "tags": [TAG],
    })
    try:
        r = requests.post(
            f"{BASE}/api/admin/filename-heuristics/apply",
            params={"execute": "true", "min_confidence": 0.80,
                    "actor": f"{TAG}_minconf", "limit": 500},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["below_threshold_count"] >= 1
        d = _db.hub_documents.find_one({"id": did}, {"_id": 0})
        assert d["doc_type"] == "Unknown"
        assert d.get("filename_heuristic_applied_at") in (None, "", False)
    finally:
        _db.hub_documents.delete_one({"id": did})


# ── runs audit log ──────────────────────────────────────────────
def test_runs_audit_log():
    r = requests.get(
        f"{BASE}/api/admin/filename-heuristics/runs",
        params={"limit": 50},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body and "runs" in body
    actors = {run.get("actor") for run in body["runs"]}
    assert any(a and a.startswith(TAG) for a in actors)


# ── regression: prior endpoints still 200 ───────────────────────
@pytest.mark.parametrize("path", [
    "/api/admin/unknown-doc-reclaim/preview",
    "/api/admin/unknown-doc-reclaim/post-process/runs",
    "/api/dashboard/inbox-stats",
    "/api/learning/pattern-health/unified",
])
def test_prior_get_endpoints_200(path):
    r = requests.get(f"{BASE}{path}", timeout=60)
    assert r.status_code == 200, f"{path} → {r.status_code}: {r.text[:200]}"


def test_prior_post_process_dryrun_200():
    r = requests.post(
        f"{BASE}/api/admin/unknown-doc-reclaim/post-process",
        params={"execute": "false"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
