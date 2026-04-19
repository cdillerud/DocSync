"""
Regression tests for v2.5.9 triage tools.

Verifies:
    • filename_shape() collapses correctly + symmetrically
    • unmatched_sample groups by (vendor, shape) and respects min_group_size
    • unmatched_sample does NOT include docs a rule would match (safety)
    • duplicate_scan respects same_day flag, min_count, and skip
      already-resolved docs
    • duplicate_resolve dry-run / execute / keep=oldest vs newest
    • keeper is never marked duplicate
    • already-resolved docs are not re-scanned (idempotent)
"""
import pytest
from datetime import datetime, timezone

import mongomock_motor

from services.admin.triage_tools_service import (
    filename_shape, unmatched_sample,
    duplicate_scan, duplicate_resolve, recent_duplicate_runs,
)


@pytest.fixture
def db():
    return mongomock_motor.AsyncMongoMockClient()["test_triage"]


def _now(): return datetime.now(timezone.utc).isoformat()


def _unk(doc_id, fn, vendor=None, **o):
    base = {
        "id": doc_id, "doc_type": "Unknown",
        "document_type": "Unknown", "suggested_job_type": "Unknown",
        "status": "NeedsReview", "file_name": fn,
        "vendor_canonical": vendor, "created_utc": _now(),
    }
    base.update(o)
    return base


# ────────── filename_shape ──────────

@pytest.mark.parametrize("name,expected", [
    ("ROT12345.pdf",     "A+#+.A+"),
    ("ROT12345_p1.pdf",  "A+#+_A+#+.A+"),
    ("0303382.pdf",      "#+.A+"),
    ("Invoice-123.pdf",  "A+-#+.A+"),
    ("Apex 112543 Outbound 4-8-26.pdf",
                         "A+ #+ A+ #+-#+-#+.A+"),
    ("",                 ""),
])
def test_filename_shape(name, expected):
    assert filename_shape(name) == expected


def test_filename_shape_is_symmetric():
    """Two different-content filenames with the same shape should collapse equal."""
    assert filename_shape("ROT12345_p1.pdf") == filename_shape("FED99887_p12.pdf")
    assert filename_shape("0303382.pdf") == filename_shape("9999999.pdf")


# ────────── unmatched_sample ──────────

@pytest.mark.asyncio
async def test_unmatched_sample_groups_by_vendor_shape(db):
    # 3 ROT docs that share a shape + 2 FED docs with a different shape
    await db.hub_documents.insert_many([
        _unk("r1", "ROT11111_p1.pdf", "ROTONDO"),
        _unk("r2", "ROT22222_p3.pdf", "ROTONDO"),
        _unk("r3", "ROT33333_p9.pdf", "ROTONDO"),
        _unk("f1", "98765_TRACE.pdf", "FEDEX"),
        _unk("f2", "11223_TRACE.pdf", "FEDEX"),
        # Singleton — excluded by min_group_size=2
        _unk("s1", "oneoff.pdf", "RANDOM"),
    ])
    r = await unmatched_sample(db=db)
    groups = {(g["vendor"], g["shape"]): g["count"] for g in r["rule_candidates"]}
    assert groups[("ROTONDO", "A+#+_A+#+.A+")] == 3
    assert groups[("FEDEX", "#+_A+.A+")] == 2
    # Singleton not returned
    assert not any(g["count"] == 1 for g in r["rule_candidates"])


@pytest.mark.asyncio
async def test_unmatched_sample_excludes_docs_a_rule_would_match(db):
    """Defensive re-check: a doc whose filename matches an existing rule
    must not appear in unmatched-sample, even though it's still
    'unclassified' in the DB sense."""
    await db.hub_documents.insert_many([
        # Would-match rule (tumaloc_numeric_freight)
        _unk("tum1", "0303382.pdf", "TUMALOC"),
        _unk("tum2", "0305586_doc1.pdf", "TUMALOC"),
        # Truly unmatched
        _unk("x1", "asdf_foo_xyz.pdf", "MYSTERY"),
        _unk("x2", "asdf_foo_abc.pdf", "MYSTERY"),
    ])
    r = await unmatched_sample(db=db)
    vendors_in_groups = {g["vendor"] for g in r["rule_candidates"]}
    assert "TUMALOC" not in vendors_in_groups
    assert "MYSTERY" in vendors_in_groups
    assert r["still_matched_after_rescan"] == 2


@pytest.mark.asyncio
async def test_unmatched_sample_respects_min_group_size(db):
    await db.hub_documents.insert_many([
        _unk(f"v{i}", f"X{i}_p{i}.pdf", "V1") for i in range(4)
    ])
    r = await unmatched_sample(db=db, min_group_size=5)
    assert r["groups_shown"] == 0
    r2 = await unmatched_sample(db=db, min_group_size=2)
    assert r2["groups_shown"] == 1


# ────────── duplicate_scan ──────────

@pytest.mark.asyncio
async def test_duplicate_scan_groups_by_filename_vendor_day(db):
    t1 = "2026-04-10T10:00:00+00:00"
    t2 = "2026-04-10T12:00:00+00:00"
    t3 = "2026-04-11T08:00:00+00:00"
    await db.hub_documents.insert_many([
        # 2 same-day GAMMIN dupes
        _unk("g1", "GAMMIN_AR_20260316.xls", "GAMMIN", created_utc=t1),
        _unk("g2", "GAMMIN_AR_20260316.xls", "GAMMIN", created_utc=t2),
        # Next-day same name — NOT a dupe with same_day=True
        _unk("g3", "GAMMIN_AR_20260316.xls", "GAMMIN", created_utc=t3),
        # Different filename — not a dup
        _unk("other", "statement.pdf", "GAMMIN", created_utc=t1),
        # No vendor — skipped
        _unk("novendor", "foo.pdf", None, created_utc=t1),
    ])
    r = await duplicate_scan(db=db, same_day=True)
    assert r["groups_total"] == 1
    assert r["duplicate_docs_total"] == 2
    assert r["groups"][0]["count"] == 2


@pytest.mark.asyncio
async def test_duplicate_scan_without_same_day(db):
    t1 = "2026-04-10T10:00:00+00:00"
    t2 = "2026-04-11T10:00:00+00:00"
    t3 = "2026-04-12T10:00:00+00:00"
    await db.hub_documents.insert_many([
        _unk(f"d{i}", "GAMMIN_AR.xls", "GAMMIN", created_utc=t)
        for i, t in enumerate([t1, t2, t3])
    ])
    r = await duplicate_scan(db=db, same_day=False)
    # All 3 collapse into 1 group since day is ignored
    assert r["groups_total"] == 1
    assert r["groups"][0]["count"] == 3


@pytest.mark.asyncio
async def test_duplicate_scan_skips_already_resolved(db):
    t = "2026-04-10T10:00:00+00:00"
    await db.hub_documents.insert_many([
        _unk("a", "same.pdf", "V", created_utc=t,
             duplicate_resolved_at=_now()),  # already done
        _unk("b", "same.pdf", "V", created_utc=t),
        _unk("c", "same.pdf", "V", created_utc=t),
    ])
    r = await duplicate_scan(db=db)
    # Only b + c visible — still a dupe pair
    assert r["groups_total"] == 1
    assert r["groups"][0]["count"] == 2


# ────────── duplicate_resolve ──────────

@pytest.mark.asyncio
async def test_duplicate_resolve_dry_run_no_mutation(db):
    t = "2026-04-10T10:00:00+00:00"
    await db.hub_documents.insert_many([
        _unk("a", "x.pdf", "V", created_utc=t),
        _unk("b", "x.pdf", "V", created_utc=t),
    ])
    r = await duplicate_resolve(db=db)
    assert r["execute"] is False
    assert r["would_mark_duplicate"] == 1
    a = await db.hub_documents.find_one({"id": "a"}, {"_id": 0})
    assert a.get("duplicate_of") in (None, "", False)


@pytest.mark.asyncio
async def test_duplicate_resolve_keep_oldest(db):
    t_old = "2026-04-10T10:00:00+00:00"
    t_new = "2026-04-10T15:00:00+00:00"
    await db.hub_documents.insert_many([
        _unk("keep", "dup.pdf", "V", created_utc=t_old),
        _unk("drop1", "dup.pdf", "V", created_utc=t_new),
        _unk("drop2", "dup.pdf", "V", created_utc=t_new),
    ])
    r = await duplicate_resolve(db=db, execute=True, keep="oldest", actor="ci")
    assert r["docs_marked_duplicate"] == 2

    keeper = await db.hub_documents.find_one({"id": "keep"}, {"_id": 0})
    assert keeper.get("duplicate_of") is None
    assert keeper.get("status") == "NeedsReview"  # untouched

    for did in ("drop1", "drop2"):
        d = await db.hub_documents.find_one({"id": did}, {"_id": 0})
        assert d["duplicate_of"] == "keep"
        assert d["status"] == "Completed"
        assert d["queue_visible"] is False
        assert d["duplicate_resolved_strategy"] == "oldest"
        assert any(h.get("event") == "duplicate_resolved"
                   for h in d.get("workflow_history", []))


@pytest.mark.asyncio
async def test_duplicate_resolve_keep_newest(db):
    t_old = "2026-04-10T10:00:00+00:00"
    t_new = "2026-04-10T15:00:00+00:00"
    await db.hub_documents.insert_many([
        _unk("drop", "dup.pdf", "V", created_utc=t_old),
        _unk("keep", "dup.pdf", "V", created_utc=t_new),
    ])
    r = await duplicate_resolve(db=db, execute=True, keep="newest")
    assert r["docs_marked_duplicate"] == 1
    keeper = await db.hub_documents.find_one({"id": "keep"}, {"_id": 0})
    loser = await db.hub_documents.find_one({"id": "drop"}, {"_id": 0})
    assert keeper.get("duplicate_of") is None
    assert loser["duplicate_of"] == "keep"


@pytest.mark.asyncio
async def test_duplicate_resolve_idempotent(db):
    t = "2026-04-10T10:00:00+00:00"
    await db.hub_documents.insert_many([
        _unk("a", "y.pdf", "V", created_utc=t),
        _unk("b", "y.pdf", "V", created_utc=t),
    ])
    first = await duplicate_resolve(db=db, execute=True)
    assert first["docs_marked_duplicate"] == 1
    second = await duplicate_resolve(db=db, execute=True)
    assert second["docs_marked_duplicate"] == 0
    assert second["groups_resolved"] == 0


@pytest.mark.asyncio
async def test_gammin_12x_prod_scenario(db):
    """Exactly the situation in prod: 12 identical GAMMIN_AR files on the
    same day. Expect 11 marked as duplicate + 1 keeper untouched."""
    day = "2026-04-10T"
    await db.hub_documents.insert_many([
        _unk(f"g{i}", "GAMMIN_AR_20260316.xls", "GAMMIN",
             created_utc=f"{day}{10+i:02d}:00:00+00:00")
        for i in range(12)
    ])
    r = await duplicate_resolve(db=db, execute=True, keep="oldest", actor="meghan")
    assert r["groups_resolved"] == 1
    assert r["docs_marked_duplicate"] == 11
    keeper = await db.hub_documents.find_one({"id": "g0"}, {"_id": 0})
    assert keeper.get("duplicate_of") is None
    # Audit row exists
    runs = await recent_duplicate_runs(db=db)
    assert len(runs) == 1
    assert runs[0]["docs_marked_duplicate"] == 11
    assert runs[0]["actor"] == "meghan"



# ──────────────────────────────────────────────────────────────
# v2.5.12 — cap / limit regression
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_scan_max_groups_returned_cap(db):
    """Response cap should shorten `.groups` without affecting
    `.groups_total` / `.duplicate_docs_total`."""
    # Seed 5 dup groups (2 docs each)
    for gi in range(5):
        keeper = _unk(f"g{gi}-a", f"file_{gi}.pdf", vendor="V")
        dup = _unk(f"g{gi}-b", f"file_{gi}.pdf", vendor="V")
        await db.hub_documents.insert_many([keeper, dup])
    r = await duplicate_scan(db=db, max_groups_returned=2)
    assert r["groups_total"] == 5
    assert r["wasted_docs_estimate"] == 5  # 5 groups × (2-1)
    assert len(r["groups"]) == 2  # response cap


@pytest.mark.asyncio
async def test_duplicate_resolve_clears_full_backlog_single_call(db):
    """With the new max_groups_returned=10000 in duplicate_resolve,
    one call must resolve ALL groups (previously capped at 100)."""
    # 150 dup groups, 2 docs each
    for gi in range(150):
        await db.hub_documents.insert_many([
            _unk(f"g{gi}-a", f"file_{gi}.pdf", vendor="V"),
            _unk(f"g{gi}-b", f"file_{gi}.pdf", vendor="V"),
        ])
    r = await duplicate_resolve(db=db, execute=True, keep="oldest")
    assert r["groups_resolved"] == 150
    assert r["docs_marked_duplicate"] == 150
    # Follow-up scan should find nothing left
    after = await duplicate_scan(db=db)
    assert after["groups_total"] == 0
