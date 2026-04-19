"""
Iter 223 — HTTP-level tests for /api/admin/workflow-observer/phase-b-readiness.

Tests against the live backend (REACT_APP_BACKEND_URL) and seeds / cleans up
data directly in MongoDB using doc_id prefix 'readiness-test-iter223-'.
"""

import os
import pytest
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
COLL = "workflow_state_observations"
SEED_PREFIX = "readiness-test-iter223-"


@pytest.fixture(scope="module")
def mongo_coll():
    # Load .env just in case
    env_path = "/app/backend/.env"
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ.setdefault(k, v.strip('"').strip("'"))
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "test_database")]
    coll = db[COLL]
    # Pre-cleanup in case of prior run
    coll.delete_many({"doc_id": {"$regex": f"^{SEED_PREFIX}"}})
    yield coll
    # Post-cleanup
    coll.delete_many({"doc_id": {"$regex": f"^{SEED_PREFIX}"}})
    client.close()


URL = f"{BASE_URL}/api/admin/workflow-observer/phase-b-readiness"


# ── Empty-data / default case ───────────────────────────────────────────
def test_empty_data_returns_not_ready(mongo_coll):
    r = requests.get(URL, params={"days": 7}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    # Required keys per spec
    for key in ("window_days", "since", "total_calls", "min_coverage",
                "ready_to_extract", "verdict", "counts", "matrix", "markdown"):
        assert key in d, f"missing key {key}"
    assert d["window_days"] == 7
    assert isinstance(d["ready_to_extract"], bool)
    assert isinstance(d["counts"], dict)
    assert {"must_preserve", "should_cover", "edge_case"} <= set(d["counts"].keys())
    # In clean state — collection is empty per iter_222 cleanup contract
    if d["total_calls"] == 0:
        assert d["ready_to_extract"] is False
        assert d["matrix"] == []
        assert d["counts"] == {"must_preserve": 0, "should_cover": 0, "edge_case": 0}
        assert "NOT READY" in d["verdict"]
        assert "no observer data captured yet" in d["verdict"]


# ── Format=markdown ────────────────────────────────────────────────────
def test_format_markdown_returns_text_markdown():
    r = requests.get(URL, params={"format": "markdown"}, timeout=30)
    assert r.status_code == 200
    assert "text/markdown" in r.headers.get("content-type", "")
    body = r.text
    assert body.startswith("# Phase B Readiness Report")
    assert "**Total calls observed:**" in body
    assert "## Verdict" in body


# ── Parameter validation (422s) ────────────────────────────────────────
@pytest.mark.parametrize("params", [
    {"format": "foobar"},
    {"days": 0},
    {"days": 999},
    {"min_coverage": 1},
    {"min_coverage": 101},
])
def test_invalid_params_return_422(params):
    r = requests.get(URL, params=params, timeout=30)
    assert r.status_code == 422, f"{params} → {r.status_code}: {r.text[:200]}"


# ── Populated-data case ────────────────────────────────────────────────
def test_populated_data_categorizes_and_verdicts_ready(mongo_coll):
    now_iso = datetime.now(timezone.utc).isoformat()
    seed_plan = [
        ("readiness_test_handler.py", "readiness_test_caller_big",    "TEST_SALES_ORDER", 10),
        ("readiness_test_handler.py", "readiness_test_caller_medium", "TEST_SHIPMENT",     3),
        ("readiness_test_handler.py", "readiness_test_caller_rare",   "TEST_RECEIPT",      1),
    ]
    docs = []
    idx = 0
    for cfile, cfunc, dtype, count in seed_plan:
        for _ in range(count):
            docs.append({
                "id": f"{SEED_PREFIX}{idx}",
                "doc_id": f"{SEED_PREFIX}{idx}",
                "doc_type": dtype,
                "confidence": 0.9,
                "has_normalized_fields": True,
                "caller_file": cfile,
                "caller_func": cfunc,
                "caller_line": 1,
                "created_at": now_iso,
                "week_key": "2026-W01",
            })
            idx += 1
    mongo_coll.insert_many(docs)

    try:
        r = requests.get(URL, params={"days": 7, "min_coverage": 5}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        # At least our seed counts are present
        assert d["total_calls"] >= 14
        assert d["ready_to_extract"] is True
        assert "READY" in d["verdict"]

        # Find our seeded rows in the matrix (scope to our test caller funcs)
        ours = [row for row in d["matrix"]
                if row["caller"].startswith("readiness_test_handler.py::readiness_test_caller_")]
        assert len(ours) == 3
        # Sort-desc-by-calls check (globally)
        all_calls = [row["calls"] for row in d["matrix"]]
        assert all_calls == sorted(all_calls, reverse=True)

        by_dt = {row["doc_type"]: row for row in ours}
        assert by_dt["TEST_SALES_ORDER"]["calls"] == 10
        assert by_dt["TEST_SALES_ORDER"]["category"] == "must_preserve"
        assert by_dt["TEST_SHIPMENT"]["calls"] == 3
        assert by_dt["TEST_SHIPMENT"]["category"] == "should_cover"
        assert by_dt["TEST_RECEIPT"]["calls"] == 1
        assert by_dt["TEST_RECEIPT"]["category"] == "edge_case"

        # Counts include our 3 rows (there may be none others in clean DB)
        assert d["counts"]["must_preserve"] >= 1
        assert d["counts"]["should_cover"] >= 1
        assert d["counts"]["edge_case"] >= 1

        # Markdown output for populated case has all 3 section headers
        r_md = requests.get(URL, params={
            "days": 7, "min_coverage": 5, "format": "markdown",
        }, timeout=30)
        assert r_md.status_code == 200
        assert "text/markdown" in r_md.headers.get("content-type", "")
        md = r_md.text
        assert md.startswith("# Phase B Readiness Report")
        assert "Must-preserve paths" in md
        assert "Should-cover paths" in md
        assert "Edge cases" in md
        # Table header present
        assert "| Caller | Doc Type | Calls |" in md
        # Our seeded rows
        assert "TEST_SALES_ORDER" in md
        assert "TEST_SHIPMENT" in md
        assert "TEST_RECEIPT" in md
    finally:
        mongo_coll.delete_many({"doc_id": {"$regex": f"^{SEED_PREFIX}"}})


# ── Below-threshold case ───────────────────────────────────────────────
def test_below_threshold_returns_not_ready(mongo_coll):
    now_iso = datetime.now(timezone.utc).isoformat()
    docs = [{
        "id": f"{SEED_PREFIX}lt-{i}",
        "doc_id": f"{SEED_PREFIX}lt-{i}",
        "doc_type": "TEST_BELOW",
        "confidence": 0.5,
        "has_normalized_fields": False,
        "caller_file": "readiness_test_lt.py",
        "caller_func": "readiness_test_lt_caller",
        "caller_line": 1,
        "created_at": now_iso,
        "week_key": "2026-W01",
    } for i in range(2)]
    mongo_coll.insert_many(docs)

    try:
        r = requests.get(URL, params={"days": 7, "min_coverage": 5}, timeout=30)
        assert r.status_code == 200
        d = r.json()
        # Scope check: our 2 seed rows → should_cover (since 2 >= 2, < 5)
        ours = [row for row in d["matrix"]
                if row["caller"] == "readiness_test_lt.py::readiness_test_lt_caller"]
        assert len(ours) == 1
        assert ours[0]["calls"] == 2
        assert ours[0]["category"] == "should_cover"
        # If DB was otherwise clean, no must_preserve exists → NOT READY
        if d["counts"]["must_preserve"] == 0:
            assert d["ready_to_extract"] is False
            assert "NOT READY" in d["verdict"]
            assert "min_coverage=5" in d["verdict"]
    finally:
        mongo_coll.delete_many({"doc_id": {"$regex": f"^{SEED_PREFIX}"}})


# ── Regression: other observer endpoints still 200 ─────────────────────
@pytest.mark.parametrize("path", [
    "/api/admin/workflow-observer/summary",
    "/api/admin/workflow-observer/recent",
    "/api/learning/digest/latest",
    "/api/learning/pattern-health/unified",
    "/api/documents",
    "/api/health",
])
def test_regression_endpoints_200(path):
    r = requests.get(f"{BASE_URL}{path}", timeout=30)
    assert r.status_code == 200, f"{path} → {r.status_code}: {r.text[:200]}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
