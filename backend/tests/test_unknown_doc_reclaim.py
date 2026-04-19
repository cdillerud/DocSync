"""
Regression tests for the Unknown-Doc Reclaim sweep (v2.5.5).

Verifies:
    • preview() counts + sample only include truly-unclassified auto-cleared
      docs with no BC evidence and no prior reclaim flag
    • run(execute=False) is a dry-run — zero mutations
    • run(execute=True) mutates: sets status=NeedsReview, adds reclaim
      fields, appends workflow_history, persists audit row
    • idempotency — a doc with reclaim_to_needs_review_at is not picked up
      on the second run
    • safety — docs with any BC evidence field are never touched
    • safety — docs currently in NeedsReview are never touched
    • safety — docs with known doc_types (AP_Invoice, Shipping_Document, etc.)
      are never touched even if auto_cleared
    • limit param caps the sweep
"""
import pytest
from datetime import datetime, timezone

import mongomock_motor

from services.admin.unknown_doc_reclaim_service import preview, run


@pytest.fixture
def db():
    return mongomock_motor.AsyncMongoMockClient()["test_reclaim"]


async def _seed(db, docs):
    if docs:
        await db.hub_documents.insert_many(docs)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _candidate(doc_id, **overrides):
    """Default: a textbook reclaim candidate."""
    base = {
        "id": doc_id,
        "doc_type": "Unknown",
        "status": "Completed",
        "workflow_status": "exported",
        "auto_cleared": True,
        "auto_cleared_at": _now(),
        "file_name": f"{doc_id}.pdf",
        "bc_purchase_invoice_no": None,
        "bc_record_no": None,
        "bc_document_no": None,
        "bc_record_id": None,
        "reclaim_to_needs_review_at": None,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_preview_counts_only_true_candidates(db):
    await _seed(db, [
        _candidate("c1"),
        _candidate("c2", doc_type=None),
        _candidate("c3", doc_type="Other"),
        _candidate("c4", doc_type=""),
        # Known doc_type — NOT a candidate
        _candidate("ap1", doc_type="AP_Invoice"),
        # Already NeedsReview — NOT a candidate
        _candidate("nr1", status="NeedsReview"),
        # Has BC record — NOT a candidate
        _candidate("bc1", bc_purchase_invoice_no="PI-123"),
        # Not auto_cleared — NOT a candidate (manual path)
        _candidate("mn1", auto_cleared=False),
        # Already reclaimed — NOT a candidate (idempotency)
        _candidate("rc1", reclaim_to_needs_review_at=_now()),
    ])
    p = await preview(db=db)
    assert p["total_candidates"] == 4
    sample_ids = {d["id"] for d in p["sample"]}
    assert sample_ids == {"c1", "c2", "c3", "c4"}


@pytest.mark.asyncio
async def test_dry_run_performs_no_mutations(db):
    await _seed(db, [_candidate("d1"), _candidate("d2")])
    r = await run(execute=False, db=db)
    assert r["execute"] is False
    assert r["total_candidates"] == 2
    # Docs untouched
    doc = await db.hub_documents.find_one({"id": "d1"}, {"_id": 0})
    assert doc["status"] == "Completed"
    assert doc.get("reclaim_to_needs_review_at") in (None, "", False)


@pytest.mark.asyncio
async def test_execute_flips_status_and_adds_audit_fields(db):
    await _seed(db, [_candidate("x1"), _candidate("x2")])
    r = await run(execute=True, actor="test_runner", db=db)
    assert r["execute"] is True
    assert r["reclaimed_count"] == 2
    assert set(r["reclaimed_ids"]) == {"x1", "x2"}

    for did in ("x1", "x2"):
        doc = await db.hub_documents.find_one({"id": did}, {"_id": 0})
        assert doc["status"] == "NeedsReview"
        assert doc["workflow_status"] == "needs_review"
        assert doc["square9_stage"] == "needs_review"
        assert doc["queue_visible"] is True
        assert doc["reclaim_to_needs_review_at"]  # populated
        assert doc["reclaim_actor"] == "test_runner"
        # workflow_history appended, not replaced
        assert any(h.get("event") == "reclaim_to_needs_review"
                   for h in doc.get("workflow_history", []))
        # Original audit preserved
        assert doc["auto_cleared"] is True  # history retained


@pytest.mark.asyncio
async def test_idempotent_second_run_is_noop(db):
    await _seed(db, [_candidate("i1")])
    first = await run(execute=True, db=db)
    assert first["reclaimed_count"] == 1

    second = await run(execute=True, db=db)
    assert second["reclaimed_count"] == 0, "Second run must not touch already-reclaimed docs"


@pytest.mark.asyncio
async def test_bc_evidence_blocks_reclaim(db):
    """Never reverse a doc that already hit BC."""
    await _seed(db, [
        _candidate("safe1", bc_purchase_invoice_no="PI-999"),
        _candidate("safe2", bc_record_no="REC-111"),
        _candidate("safe3", bc_document_no="DOC-X"),
        _candidate("safe4", bc_record_id="id-123"),
    ])
    r = await run(execute=True, db=db)
    assert r["reclaimed_count"] == 0
    for did in ("safe1", "safe2", "safe3", "safe4"):
        doc = await db.hub_documents.find_one({"id": did}, {"_id": 0})
        assert doc["status"] == "Completed"


@pytest.mark.asyncio
async def test_known_doc_type_never_reclaimed(db):
    """AP_Invoice / Shipping_Document / etc. docs that were auto-cleared
    correctly must not be rolled back."""
    await _seed(db, [
        _candidate("keep1", doc_type="AP_Invoice"),
        _candidate("keep2", doc_type="Shipping_Document"),
        _candidate("keep3", doc_type="BOL"),
        _candidate("keep4", doc_type="Quality_Doc"),
    ])
    r = await run(execute=True, db=db)
    assert r["reclaimed_count"] == 0


@pytest.mark.asyncio
async def test_limit_caps_mutation_count(db):
    await _seed(db, [_candidate(f"m{i}") for i in range(20)])
    r = await run(execute=True, limit=5, db=db)
    assert r["reclaimed_count"] == 5
    # Remaining 15 still candidates
    p = await preview(db=db)
    assert p["total_candidates"] == 15


@pytest.mark.asyncio
async def test_audit_run_logged(db):
    await _seed(db, [_candidate("a1")])
    await run(execute=True, actor="ci_user", db=db)
    rows = await db.unknown_doc_reclaim_runs.find({}, {"_id": 0}).to_list(10)
    assert len(rows) == 1
    assert rows[0]["actor"] == "ci_user"
    assert rows[0]["reclaimed_count"] == 1
    assert rows[0]["execute"] is True


@pytest.mark.asyncio
async def test_mixed_seed_realistic_scenario(db):
    """The real-world case described by the user: Ball Metal split children
    at doc_type=Unknown, sitting in Completed, with a parent reference."""
    await _seed(db, [
        _candidate("ball_p11", doc_type="Unknown", batch_parent_id="parent-xyz"),
        _candidate("ball_p12", doc_type="Unknown", batch_parent_id="parent-xyz"),
        _candidate("ball_p13", doc_type=None, batch_parent_id="parent-xyz"),
        # Parent itself is classified — should stay as-is
        _candidate("parent-xyz", doc_type="AP_Invoice", status="Completed"),
        # A genuinely posted doc — must never move
        _candidate("posted_ok", doc_type="AP_Invoice",
                   bc_purchase_invoice_no="PI-7788"),
    ])
    p = await preview(db=db)
    assert p["total_candidates"] == 3
    assert p["sample_breakdown"]["from_batch_split"] == 3

    r = await run(execute=True, db=db)
    assert r["reclaimed_count"] == 3
    # Parent + posted doc untouched
    parent = await db.hub_documents.find_one({"id": "parent-xyz"}, {"_id": 0})
    posted = await db.hub_documents.find_one({"id": "posted_ok"}, {"_id": 0})
    assert parent["status"] == "Completed"
    assert posted["status"] == "Completed"
