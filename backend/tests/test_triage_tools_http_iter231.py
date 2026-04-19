"""
Live HTTP regression tests for v2.5.9 triage tools (iter231).

Seeds ephemeral TEST_iter231_* docs via pymongo, then drives the 4 new
admin endpoints over the public preview URL. All seeded docs are torn
down in the module fixture. The live hub_documents collection is never
mutated.
"""
import os
import uuid
from datetime import datetime, timezone

import pymongo
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    # Fallback to frontend/.env
    with open("/app/frontend/.env") as fh:
        for line in fh:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE = line.split("=", 1)[1].strip().rstrip("/")

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "gpi_document_hub"

TEST_PREFIX = "TEST_iter231_"
TEST_ACTOR = "TEST_iter231_actor"


# ────────── fixtures ──────────

@pytest.fixture(scope="module")
def mongo_db():
    client = pymongo.MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    # Cleanup — remove any leftover TEST_iter231_* docs and runs
    db.hub_documents.delete_many({"id": {"$regex": f"^{TEST_PREFIX}"}})
    db.duplicate_resolve_runs.delete_many({"actor": TEST_ACTOR})
    client.close()


@pytest.fixture
def seed_docs(mongo_db):
    """Returns a factory that inserts and tracks doc ids for cleanup."""
    inserted = []

    def _insert(docs):
        for d in docs:
            assert d["id"].startswith(TEST_PREFIX), "All test docs must be TEST_iter231_*"
        mongo_db.hub_documents.insert_many(docs)
        inserted.extend(d["id"] for d in docs)
        return [d["id"] for d in docs]

    yield _insert
    if inserted:
        mongo_db.hub_documents.delete_many({"id": {"$in": inserted}})


def _now():
    return datetime.now(timezone.utc).isoformat()


def _unk(name_suffix, file_name, vendor, **extra):
    base = {
        "id": f"{TEST_PREFIX}{name_suffix}_{uuid.uuid4().hex[:6]}",
        "doc_type": "Unknown",
        "document_type": "Unknown",
        "suggested_job_type": "Unknown",
        "status": "NeedsReview",
        "file_name": file_name,
        "vendor_canonical": vendor,
        "created_utc": _now(),
    }
    base.update(extra)
    return base


# ────────── GET /filename-heuristics/unmatched-sample ──────────

def test_unmatched_sample_returns_expected_shape():
    r = requests.get(
        f"{BASE}/api/admin/filename-heuristics/unmatched-sample",
        params={"limit": 100, "top_n": 5, "min_group_size": 2},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    for key in (
        "generated_at", "total_scanned", "groups_total", "groups_shown",
        "min_group_size", "rule_candidates", "still_matched_after_rescan",
    ):
        assert key in data, f"Missing key: {key}"
    assert data["min_group_size"] == 2
    assert isinstance(data["rule_candidates"], list)


def test_unmatched_sample_groups_by_shape_and_vendor(seed_docs):
    # 3 ROTONDO with same shape + 2 MYSTERY + 1 singleton
    ids = seed_docs([
        _unk("r1", "ROT11111_p1.pdf", "TEST_ITER231_ROTONDO"),
        _unk("r2", "ROT22222_p3.pdf", "TEST_ITER231_ROTONDO"),
        _unk("r3", "ROT33333_p9.pdf", "TEST_ITER231_ROTONDO"),
        _unk("m1", "asdf_foo_xyz.pdf", "TEST_ITER231_MYSTERY"),
        _unk("m2", "asdf_foo_abc.pdf", "TEST_ITER231_MYSTERY"),
        _unk("s1", "oneoff_singleton.pdf", "TEST_ITER231_SOLO"),
    ])
    r = requests.get(
        f"{BASE}/api/admin/filename-heuristics/unmatched-sample",
        params={"limit": 5000, "top_n": 200, "min_group_size": 2},
        timeout=30,
    )
    assert r.status_code == 200
    data = r.json()
    cands = data["rule_candidates"]

    rot = [g for g in cands
           if g.get("vendor") == "TEST_ITER231_ROTONDO"
           and g.get("shape") == "A+#+_A+#+.A+"]
    assert rot and rot[0]["count"] >= 3, f"ROTONDO group missing: {rot}"

    mys = [g for g in cands
           if g.get("vendor") == "TEST_ITER231_MYSTERY"]
    assert mys and mys[0]["count"] >= 2

    # Singleton vendor never in candidates (min_group_size=2)
    assert not any(g.get("vendor") == "TEST_ITER231_SOLO" for g in cands)


def test_unmatched_sample_excludes_docs_matching_existing_rule(seed_docs):
    """A filename that the existing rule-set WOULD classify must be excluded
    from rule_candidates and counted in still_matched_after_rescan."""
    seed_docs([
        _unk("tum1", "0303382.pdf", "TUMALOC"),
        _unk("tum2", "0305586.pdf", "TUMALOC"),
    ])
    r = requests.get(
        f"{BASE}/api/admin/filename-heuristics/unmatched-sample",
        params={"limit": 5000, "top_n": 200, "min_group_size": 2},
        timeout=30,
    )
    assert r.status_code == 200
    data = r.json()
    cands = data["rule_candidates"]
    # TUMALOC numeric-shape docs must not leak through
    leaked = [g for g in cands
              if g.get("vendor") == "TUMALOC" and g.get("shape") == "#+.A+"]
    assert not leaked, f"TUMALOC-matching docs leaked: {leaked}"
    assert data["still_matched_after_rescan"] >= 2


def test_unmatched_sample_respects_min_group_size(seed_docs):
    # 4 same-shape docs, then demand min_group_size=10 → must exclude
    seed_docs([
        _unk(f"v{i}", f"X{i}_p{i}.pdf", "TEST_ITER231_MINGRP")
        for i in range(4)
    ])
    r_big = requests.get(
        f"{BASE}/api/admin/filename-heuristics/unmatched-sample",
        params={"limit": 5000, "top_n": 200, "min_group_size": 10},
        timeout=30,
    )
    assert r_big.status_code == 200
    assert not any(g.get("vendor") == "TEST_ITER231_MINGRP"
                   for g in r_big.json()["rule_candidates"])

    r_sm = requests.get(
        f"{BASE}/api/admin/filename-heuristics/unmatched-sample",
        params={"limit": 5000, "top_n": 200, "min_group_size": 2},
        timeout=30,
    )
    assert r_sm.status_code == 200
    hit = [g for g in r_sm.json()["rule_candidates"]
           if g.get("vendor") == "TEST_ITER231_MINGRP"]
    assert hit and hit[0]["count"] == 4


def test_unmatched_sample_zero_mutations(mongo_db, seed_docs):
    ids = seed_docs([
        _unk("nm1", "nomut_foo_bar.pdf", "TEST_ITER231_NOMUT"),
        _unk("nm2", "nomut_baz_qux.pdf", "TEST_ITER231_NOMUT"),
    ])
    before = list(mongo_db.hub_documents.find({"id": {"$in": ids}}, {"_id": 0}))
    requests.get(
        f"{BASE}/api/admin/filename-heuristics/unmatched-sample",
        params={"limit": 5000, "min_group_size": 2}, timeout=30,
    )
    after = list(mongo_db.hub_documents.find({"id": {"$in": ids}}, {"_id": 0}))
    assert before == after, "unmatched-sample should be pure read"


# ────────── GET /duplicate-docs/scan ──────────

def test_duplicate_scan_same_day_groups(seed_docs):
    fname = f"GAMMIN_AR_{uuid.uuid4().hex[:8]}.xls"
    day = "2026-04-10T"
    seed_docs([
        _unk("g1", fname, "TEST_ITER231_GAMMIN", created_utc=f"{day}10:00:00+00:00"),
        _unk("g2", fname, "TEST_ITER231_GAMMIN", created_utc=f"{day}12:00:00+00:00"),
        _unk("g3", fname, "TEST_ITER231_GAMMIN", created_utc="2026-04-11T08:00:00+00:00"),
    ])
    r = requests.get(
        f"{BASE}/api/admin/duplicate-docs/scan",
        params={"same_day": "true", "min_count": 2, "limit": 5000},
        timeout=30,
    )
    assert r.status_code == 200
    data = r.json()
    target = [g for g in data["groups"]
              if g.get("file_name") == fname
              and g.get("vendor_canonical") == "TEST_ITER231_GAMMIN"]
    assert target, f"Target group missing: {data['groups'][:3]}"
    # Same-day: only g1+g2 should collapse (count==2). g3 is different day.
    assert target[0]["count"] == 2


def test_duplicate_scan_cross_day_collapse(seed_docs):
    fname = f"GAMMIN_CROSSDAY_{uuid.uuid4().hex[:8]}.xls"
    seed_docs([
        _unk("d1", fname, "TEST_ITER231_CROSSDAY", created_utc="2026-04-10T10:00:00+00:00"),
        _unk("d2", fname, "TEST_ITER231_CROSSDAY", created_utc="2026-04-11T10:00:00+00:00"),
        _unk("d3", fname, "TEST_ITER231_CROSSDAY", created_utc="2026-04-12T10:00:00+00:00"),
    ])
    r = requests.get(
        f"{BASE}/api/admin/duplicate-docs/scan",
        params={"same_day": "false", "min_count": 2, "limit": 5000},
        timeout=30,
    )
    assert r.status_code == 200
    target = [g for g in r.json()["groups"]
              if g.get("file_name") == fname]
    assert target and target[0]["count"] == 3


def test_duplicate_scan_skips_already_resolved(mongo_db, seed_docs):
    fname = f"ALREADY_RES_{uuid.uuid4().hex[:8]}.pdf"
    seed_docs([
        _unk("ar1", fname, "TEST_ITER231_AR",
             created_utc="2026-04-10T10:00:00+00:00",
             duplicate_resolved_at=_now()),
        _unk("ar2", fname, "TEST_ITER231_AR",
             created_utc="2026-04-10T11:00:00+00:00"),
        _unk("ar3", fname, "TEST_ITER231_AR",
             created_utc="2026-04-10T12:00:00+00:00"),
    ])
    r = requests.get(
        f"{BASE}/api/admin/duplicate-docs/scan",
        params={"same_day": "true", "min_count": 2, "limit": 5000},
        timeout=30,
    )
    assert r.status_code == 200
    target = [g for g in r.json()["groups"]
              if g.get("file_name") == fname]
    assert target and target[0]["count"] == 2  # resolved one excluded


# ────────── POST /duplicate-docs/resolve ──────────

def test_duplicate_resolve_dry_run_no_mutation(mongo_db, seed_docs):
    fname = f"DRYRUN_{uuid.uuid4().hex[:8]}.pdf"
    ids = seed_docs([
        _unk("dry1", fname, "TEST_ITER231_DRY",
             created_utc="2026-04-10T10:00:00+00:00"),
        _unk("dry2", fname, "TEST_ITER231_DRY",
             created_utc="2026-04-10T12:00:00+00:00"),
    ])
    r = requests.post(
        f"{BASE}/api/admin/duplicate-docs/resolve",
        params={"actor": TEST_ACTOR}, timeout=30,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["execute"] is False
    assert data["would_mark_duplicate"] >= 1
    # No mutation on our seeded docs
    docs = list(mongo_db.hub_documents.find({"id": {"$in": ids}}, {"_id": 0}))
    for d in docs:
        assert d.get("duplicate_of") in (None, "", False)
        assert d.get("status") == "NeedsReview"


def test_duplicate_resolve_keep_oldest_marks_others(mongo_db, seed_docs):
    fname = f"KEEPOLD_{uuid.uuid4().hex[:8]}.pdf"
    ids = seed_docs([
        _unk("old_keeper", fname, "TEST_ITER231_OLD",
             created_utc="2026-04-10T10:00:00+00:00"),
        _unk("drop_a", fname, "TEST_ITER231_OLD",
             created_utc="2026-04-10T12:00:00+00:00"),
        _unk("drop_b", fname, "TEST_ITER231_OLD",
             created_utc="2026-04-10T15:00:00+00:00"),
    ])
    r = requests.post(
        f"{BASE}/api/admin/duplicate-docs/resolve",
        params={"execute": "true", "keep": "oldest", "actor": TEST_ACTOR},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["execute"] is True
    assert data["docs_marked_duplicate"] >= 2

    keeper_id = next(i for i in ids if "old_keeper" in i)
    keeper = mongo_db.hub_documents.find_one({"id": keeper_id}, {"_id": 0})
    assert keeper.get("duplicate_of") in (None, "", False)
    assert keeper.get("status") == "NeedsReview"

    for did in ids:
        if did == keeper_id:
            continue
        d = mongo_db.hub_documents.find_one({"id": did}, {"_id": 0})
        assert d["duplicate_of"] == keeper_id
        assert d["status"] == "Completed"
        assert d.get("workflow_status") == "completed"
        assert d.get("queue_visible") is False
        assert d.get("duplicate_resolved_strategy") == "oldest"
        hist = d.get("workflow_history", [])
        assert any(h.get("event") == "duplicate_resolved" for h in hist), \
            f"No duplicate_resolved in history of {did}: {hist}"


def test_duplicate_resolve_keep_newest(mongo_db, seed_docs):
    fname = f"KEEPNEW_{uuid.uuid4().hex[:8]}.pdf"
    ids = seed_docs([
        _unk("older", fname, "TEST_ITER231_NEW",
             created_utc="2026-04-10T10:00:00+00:00"),
        _unk("newer_keeper", fname, "TEST_ITER231_NEW",
             created_utc="2026-04-10T15:00:00+00:00"),
    ])
    r = requests.post(
        f"{BASE}/api/admin/duplicate-docs/resolve",
        params={"execute": "true", "keep": "newest", "actor": TEST_ACTOR},
        timeout=30,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["docs_marked_duplicate"] >= 1

    keeper_id = next(i for i in ids if "newer_keeper" in i)
    older_id = next(i for i in ids if "older" in i)
    keeper = mongo_db.hub_documents.find_one({"id": keeper_id}, {"_id": 0})
    loser = mongo_db.hub_documents.find_one({"id": older_id}, {"_id": 0})
    assert keeper.get("duplicate_of") in (None, "", False)
    assert loser["duplicate_of"] == keeper_id
    assert loser.get("duplicate_resolved_strategy") == "newest"


def test_duplicate_resolve_idempotent(mongo_db, seed_docs):
    fname = f"IDEMP_{uuid.uuid4().hex[:8]}.pdf"
    seed_docs([
        _unk("id1", fname, "TEST_ITER231_IDEMP",
             created_utc="2026-04-10T10:00:00+00:00"),
        _unk("id2", fname, "TEST_ITER231_IDEMP",
             created_utc="2026-04-10T12:00:00+00:00"),
    ])
    r1 = requests.post(
        f"{BASE}/api/admin/duplicate-docs/resolve",
        params={"execute": "true", "keep": "oldest", "actor": TEST_ACTOR},
        timeout=30,
    )
    assert r1.status_code == 200
    assert r1.json()["docs_marked_duplicate"] >= 1

    r2 = requests.post(
        f"{BASE}/api/admin/duplicate-docs/resolve",
        params={"execute": "true", "keep": "oldest", "actor": TEST_ACTOR},
        timeout=30,
    )
    assert r2.status_code == 200
    # The specific group we just resolved should no longer re-appear
    # We check by fname directly (other live groups might exist but
    # shouldn't include ours).
    scan = requests.get(
        f"{BASE}/api/admin/duplicate-docs/scan",
        params={"same_day": "true", "min_count": 2, "limit": 5000}, timeout=30,
    ).json()
    assert not any(g.get("file_name") == fname for g in scan["groups"])


def test_duplicate_resolve_invalid_keep_defaults_oldest(mongo_db, seed_docs):
    fname = f"INVKEEP_{uuid.uuid4().hex[:8]}.pdf"
    ids = seed_docs([
        _unk("ik_old", fname, "TEST_ITER231_IK",
             created_utc="2026-04-10T10:00:00+00:00"),
        _unk("ik_new", fname, "TEST_ITER231_IK",
             created_utc="2026-04-10T15:00:00+00:00"),
    ])
    r = requests.post(
        f"{BASE}/api/admin/duplicate-docs/resolve",
        params={"execute": "true", "keep": "garbage_value", "actor": TEST_ACTOR},
        timeout=30,
    )
    assert r.status_code == 200
    old_id = next(i for i in ids if "ik_old" in i)
    new_id = next(i for i in ids if "ik_new" in i)
    # Invalid keep → sanitized to oldest → old kept, new marked dup
    old_doc = mongo_db.hub_documents.find_one({"id": old_id}, {"_id": 0})
    new_doc = mongo_db.hub_documents.find_one({"id": new_id}, {"_id": 0})
    assert old_doc.get("duplicate_of") in (None, "", False)
    assert new_doc["duplicate_of"] == old_id


def test_gammin_12x_prod_scenario(mongo_db, seed_docs):
    """Exactly the prod scenario: 12 identical GAMMIN docs on same day.
    keep=oldest → exactly 11 marked duplicate; oldest untouched."""
    fname = f"GAMMIN_12X_{uuid.uuid4().hex[:8]}.xls"
    day = "2026-04-10T"
    ids = seed_docs([
        _unk(f"g12_{i:02d}", fname, "TEST_ITER231_GAMMIN12",
             created_utc=f"{day}{10 + i:02d}:00:00+00:00")
        for i in range(12)
    ])
    r = requests.post(
        f"{BASE}/api/admin/duplicate-docs/resolve",
        params={"execute": "true", "keep": "oldest", "actor": TEST_ACTOR},
        timeout=30,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["docs_marked_duplicate"] >= 11

    # Find the oldest seeded id — the one with _00 suffix (10:00 UTC)
    keeper_id = next(i for i in ids if "g12_00" in i)
    keeper = mongo_db.hub_documents.find_one({"id": keeper_id}, {"_id": 0})
    assert keeper.get("duplicate_of") in (None, "", False)
    assert keeper.get("status") == "NeedsReview"

    marked = mongo_db.hub_documents.count_documents(
        {"id": {"$in": ids}, "duplicate_of": keeper_id}
    )
    assert marked == 11, f"Expected 11 marked, got {marked}"


# ────────── GET /duplicate-docs/runs ──────────

def test_duplicate_runs_audit_trail(mongo_db):
    r = requests.get(
        f"{BASE}/api/admin/duplicate-docs/runs",
        params={"limit": 50}, timeout=30,
    )
    assert r.status_code == 200
    data = r.json()
    assert "total" in data and "runs" in data
    assert isinstance(data["runs"], list)
    # At least one of our TEST_iter231_actor runs should be in there
    mine = [run for run in data["runs"] if run.get("actor") == TEST_ACTOR]
    assert mine, "Expected at least one run by TEST_iter231_actor"
    sample = mine[0]
    for key in ("groups_resolved", "docs_marked_duplicate"):
        assert key in sample


# ────────── Regression sanity on prior endpoints ──────────

@pytest.mark.parametrize("path", [
    "/api/admin/unknown-doc-reclaim/preview",
    "/api/admin/filename-heuristics/preview",
    "/api/dashboard/inbox-stats",
    "/api/learning/pattern-health/unified",
])
def test_prior_endpoints_still_200(path):
    r = requests.get(f"{BASE}{path}", timeout=30)
    assert r.status_code == 200, f"{path} → {r.status_code}: {r.text[:200]}"
