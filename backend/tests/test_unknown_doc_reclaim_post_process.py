"""
Regression tests for v2.5.7 retroactive post-process sweep.

Scenario reproduced:
    Operator ran v2.5.5 plain reclaim on 372 prod docs. Then we shipped
    v2.5.6 (smart + skip_noise flags). Post-process sweep now applies
    those flags retroactively to docs already in NeedsReview.

Covers:
    • filter correctness — only picks docs with reclaim_to_needs_review_at
      set AND not already post-processed AND still visible in queue AND
      no BC evidence
    • dry-run: zero mutations, populates would_* counters
    • execute + skip_noise: reverts noise docs from NeedsReview → Completed
      with noise_filtered=true, queue_visible=false
    • execute + smart: batch children with classified parent get
      doc_type/vendor inherited, stay in NeedsReview
    • docs with neither noise nor inheritable-parent get stamp-only
      (post_process_applied_at set, no status change)
    • idempotency: second run picks up zero candidates
    • safety: docs without reclaim_to_needs_review_at are never touched
    • safety: docs with BC evidence are excluded
    • safety: already post-processed docs are skipped
"""
import pytest
from datetime import datetime, timezone

import mongomock_motor

from services.admin.unknown_doc_reclaim_service import (
    post_process, recent_post_process_runs,
)


@pytest.fixture
def db():
    return mongomock_motor.AsyncMongoMockClient()["test_pp"]


def _now():
    return datetime.now(timezone.utc).isoformat()


def _reclaimed_doc(doc_id, **overrides):
    """A doc as it would look *after* the v2.5.5 plain reclaim."""
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
        "reclaim_to_needs_review_at": _now(),  # previously reclaimed
        "reclaim_actor": "meghan",
        "bc_purchase_invoice_no": None,
        "bc_record_no": None,
        "bc_document_no": None,
        "bc_record_id": None,
    }
    base.update(overrides)
    return base


def _parent(doc_id, doc_type="AP_Invoice", vendor="TUMALOC"):
    return {
        "id": doc_id,
        "doc_type": doc_type,
        "document_type": doc_type,
        "suggested_job_type": doc_type,
        "vendor_canonical": vendor,
        "status": "Completed",
    }


async def _seed(db, docs):
    if docs:
        await db.hub_documents.insert_many(docs)


# ────────── Filter correctness ──────────

@pytest.mark.asyncio
async def test_only_reclaimed_and_visible_are_candidates(db):
    await _seed(db, [
        _reclaimed_doc("A"),                               # candidate
        _reclaimed_doc("B", status="Completed",
                       workflow_status="completed",
                       queue_visible=False),               # NOT candidate — already resolved
        {"id": "C", "status": "NeedsReview",
         "reclaim_to_needs_review_at": None,
         "queue_visible": True},                           # NOT — never reclaimed
        _reclaimed_doc("D", post_process_applied_at=_now()),  # NOT — already processed
        _reclaimed_doc("E", bc_purchase_invoice_no="PI-1"),   # NOT — BC evidence
    ])
    p = await post_process(db=db)
    assert p["total_candidates"] == 1


# ────────── Dry-run ──────────

@pytest.mark.asyncio
async def test_dry_run_does_not_mutate(db):
    await _seed(db, [
        _parent("P1"),
        _reclaimed_doc("N1", file_name="linkedin_32x32.png"),
        _reclaimed_doc("I1", batch_parent_id="P1"),
        _reclaimed_doc("S1"),  # stamp-only (no noise, no inheritable parent)
    ])
    p = await post_process(db=db, smart=True, skip_noise=True)
    assert p["execute"] is False
    assert p["would_filter_noise"] == 1
    assert p["would_inherit"] == 1
    assert p["would_stamp_only"] == 1
    # Nothing mutated
    n1 = await db.hub_documents.find_one({"id": "N1"}, {"_id": 0})
    assert n1.get("noise_filtered") is not True
    assert n1.get("post_process_applied_at") in (None, "", False)


# ────────── Execute — noise path ──────────

@pytest.mark.asyncio
async def test_noise_reverted_out_of_needs_review(db):
    await _seed(db, [
        _reclaimed_doc("N-spr", file_name="cmn_abcd1234.png"),
        _reclaimed_doc("N-img", file_name="image.png"),
        _reclaimed_doc("OK",    file_name="Invoice-123.pdf"),
    ])
    r = await post_process(db=db, execute=True, skip_noise=True, actor="ci")
    assert r["filtered_noise_count"] == 2
    assert r["inherited_count"] == 0
    assert r["stamped_only_count"] == 1

    n = await db.hub_documents.find_one({"id": "N-spr"}, {"_id": 0})
    assert n["noise_filtered"] is True
    assert n["status"] == "Completed"
    assert n["queue_visible"] is False
    assert n["post_process_applied_at"]

    ok = await db.hub_documents.find_one({"id": "OK"}, {"_id": 0})
    assert ok["status"] == "NeedsReview"  # unchanged
    assert ok["post_process_applied_at"]  # but stamped


# ────────── Execute — smart path ──────────

@pytest.mark.asyncio
async def test_smart_inheritance_applied_retroactively(db):
    await _seed(db, [
        _parent("P", doc_type="AP_Invoice", vendor="TUMALOC"),
        _reclaimed_doc("C", batch_parent_id="P", vendor_canonical=None),
    ])
    r = await post_process(db=db, execute=True, smart=True)
    assert r["inherited_count"] == 1
    c = await db.hub_documents.find_one({"id": "C"}, {"_id": 0})
    assert c["doc_type"] == "AP_Invoice"
    assert c["vendor_canonical"] == "TUMALOC"
    assert c["parent_inheritance_applied"] is True
    assert c["parent_inheritance_source"] == "reclaim_post_process"
    assert c["status"] == "NeedsReview"  # still in review, just enriched
    assert c["doc_type_from_reclaim_ai"] == "Unknown"


@pytest.mark.asyncio
async def test_smart_skips_unclassified_parent(db):
    await _seed(db, [
        {"id": "PU", "doc_type": "Unknown", "document_type": "Unknown",
         "suggested_job_type": "Unknown"},
        _reclaimed_doc("CU", batch_parent_id="PU"),
    ])
    r = await post_process(db=db, execute=True, smart=True)
    assert r["inherited_count"] == 0
    assert r["stamped_only_count"] == 1


@pytest.mark.asyncio
async def test_smart_skips_children_already_inherited(db):
    await _seed(db, [
        _parent("P"),
        _reclaimed_doc("C", batch_parent_id="P",
                       parent_inheritance_applied=True,
                       doc_type="AP_Invoice"),
    ])
    r = await post_process(db=db, execute=True, smart=True)
    assert r["inherited_count"] == 0
    # Still stamped to prevent future re-picks
    assert r["stamped_only_count"] == 1


# ────────── Noise precedence & combined ──────────

@pytest.mark.asyncio
async def test_noise_wins_over_smart_in_post_process(db):
    await _seed(db, [
        _parent("P", vendor="CARGOMO"),
        _reclaimed_doc("CN", batch_parent_id="P", file_name="cmn_abcd1234.png"),
    ])
    r = await post_process(db=db, execute=True, smart=True, skip_noise=True)
    assert r["filtered_noise_count"] == 1
    assert r["inherited_count"] == 0
    c = await db.hub_documents.find_one({"id": "CN"}, {"_id": 0})
    assert c["noise_filtered"] is True
    assert c.get("parent_inheritance_applied") is not True


# ────────── Idempotency ──────────

@pytest.mark.asyncio
async def test_second_run_picks_zero(db):
    await _seed(db, [
        _parent("P"),
        _reclaimed_doc("R1", file_name="image.png"),
        _reclaimed_doc("R2", batch_parent_id="P"),
        _reclaimed_doc("R3"),
    ])
    first = await post_process(db=db, execute=True, smart=True, skip_noise=True)
    assert first["processed"] == 3

    second = await post_process(db=db, execute=True, smart=True, skip_noise=True)
    assert second["processed"] == 0
    assert second["total_candidates"] == 0


# ────────── Audit ──────────

@pytest.mark.asyncio
async def test_audit_row_written_and_retrievable(db):
    await _seed(db, [_reclaimed_doc("X")])
    await post_process(db=db, execute=True, actor="meghan")
    runs = await recent_post_process_runs(db=db)
    assert len(runs) == 1
    assert runs[0]["actor"] == "meghan"
    assert runs[0]["processed"] == 1


# ────────── Realistic prod-shape scenario ──────────

@pytest.mark.asyncio
async def test_prod_shape_372_like_mix(db):
    """Simulates the real prod situation: 20 docs already in NeedsReview
    from a plain reclaim, mixed across noise, inheritable, and plain."""
    docs = [_parent("P-TUM", vendor="TUMALOC"),
            _parent("P-CAR", vendor="CARGOMO")]
    # 6 noise
    for i, fn in enumerate([
        "linkedin_32x32_a.png", "cmn_b3532cd1.png", "image.png",
        "signature.png", "QRd50a4ca1.png", "logo.svg",
    ]):
        docs.append(_reclaimed_doc(f"N{i}", file_name=fn))
    # 8 batch children (4 each for 2 classified parents)
    for i in range(4):
        docs.append(_reclaimed_doc(f"T{i}", batch_parent_id="P-TUM"))
    for i in range(4):
        docs.append(_reclaimed_doc(f"C{i}", batch_parent_id="P-CAR"))
    # 6 plain docs
    for i in range(6):
        docs.append(_reclaimed_doc(f"P{i}", file_name=f"real-{i}.pdf"))
    await _seed(db, docs)

    r = await post_process(db=db, execute=True, smart=True, skip_noise=True, actor="meghan")
    assert r["filtered_noise_count"] == 6
    assert r["inherited_count"] == 8
    assert r["stamped_only_count"] == 6
    assert r["processed"] == 20

    # Spot-check: TUMALOC child has inherited metadata
    t0 = await db.hub_documents.find_one({"id": "T0"}, {"_id": 0})
    assert t0["vendor_canonical"] == "TUMALOC"
    assert t0["doc_type"] == "AP_Invoice"
    # Noise doc reverted out of queue
    n0 = await db.hub_documents.find_one({"id": "N0"}, {"_id": 0})
    assert n0["status"] == "Completed"
    assert n0["queue_visible"] is False
