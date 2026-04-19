"""
Regression tests for v2.5.6 smart + skip_noise reclaim modes.

Covers:
    • _is_noise() — positive & negative cases across the denylist
    • smart=True: batch-split children with classified parent inherit
      doc_type + vendor, kept in the reclaimed bucket (not noise)
    • smart=True: child with no parent or with unclassified parent falls
      through to the plain path
    • smart=True: original child doc_type is preserved under
      `doc_type_from_reclaim_ai` for audit
    • skip_noise=True: denylist matches are marked `noise_filtered`,
      NOT routed to NeedsReview, but still counted toward idempotency
    • skip_noise=True: non-noise docs unaffected
    • combined smart + skip_noise: noise wins (even a batch child with
      a classified parent, if its filename is noise, is filtered out)
    • preview with modes populates smart_inheritable + filtered_as_noise
      breakdown counts without mutating anything
    • run result shape: reclaimed_plain_count / reclaimed_inherited_count
      / filtered_noise_count / total_mutated all present
"""
import pytest
from datetime import datetime, timezone

import mongomock_motor

from services.admin.unknown_doc_reclaim_service import (
    preview, run, _is_noise,
)


@pytest.fixture
def db():
    return mongomock_motor.AsyncMongoMockClient()["test_reclaim_v256"]


async def _seed(db, docs):
    if docs:
        await db.hub_documents.insert_many(docs)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _candidate(doc_id, **overrides):
    base = {
        "id": doc_id,
        "doc_type": "Unknown",
        "status": "Completed",
        "workflow_status": "completed",
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


def _parent(doc_id, doc_type="AP_Invoice", vendor="TEST_VENDOR"):
    """A fully-classified parent doc that children should inherit from."""
    return {
        "id": doc_id,
        "doc_type": doc_type,
        "document_type": doc_type,
        "suggested_job_type": doc_type,
        "vendor_canonical": vendor,
        "status": "Completed",
        "auto_cleared": False,  # parent itself is not a reclaim candidate
    }


# ────────── _is_noise direct unit tests ──────────

def test_is_noise_positive():
    assert _is_noise("linkedin_32x32_abcd.png")
    assert _is_noise("LinkedIn_64x64.png")  # case-insensitive
    assert _is_noise("cmn_b3532cd1-5508-4db6-950a-b55451277b9c.png")
    assert _is_noise("QRd50a4ca1-df2b-c73b-bcc2-ac76807d692d.png")
    assert _is_noise("image.png")
    assert _is_noise("image12.jpg")
    assert _is_noise("signature.png")
    assert _is_noise("logo.svg")
    assert _is_noise("pixel.gif")


def test_is_noise_negative():
    assert not _is_noise("Invoice-0493680.pdf")
    assert not _is_noise("W117505.pdf")
    assert not _is_noise("0303382.pdf")
    assert not _is_noise("MARCH 2026 ACTIVITY.pdf")
    assert not _is_noise("")
    assert not _is_noise(None)
    # Real image of a scanned doc — don't accidentally drop
    assert not _is_noise("scan_20260101.png")
    assert not _is_noise("Gamer Ship 3626.pdf")


# ────────── smart=True: parent inheritance ──────────

@pytest.mark.asyncio
async def test_smart_mode_child_inherits_parent_doc_type(db):
    await _seed(db, [
        _parent("P-1", doc_type="AP_Invoice", vendor="TUMALOC"),
        _candidate("C-1", batch_parent_id="P-1", vendor_canonical=None),
    ])
    r = await run(execute=True, smart=True, db=db)
    assert r["reclaimed_inherited_count"] == 1
    assert r["reclaimed_plain_count"] == 0

    child = await db.hub_documents.find_one({"id": "C-1"}, {"_id": 0})
    assert child["doc_type"] == "AP_Invoice"
    assert child["document_type"] == "AP_Invoice"
    assert child["suggested_job_type"] == "AP_Invoice"
    assert child["vendor_canonical"] == "TUMALOC"
    assert child["vendor_inherited_from_parent"] is True
    assert child["parent_inheritance_applied"] is True
    assert child["status"] == "NeedsReview"  # still goes to review
    # Audit: original bad classification preserved
    assert child["doc_type_from_reclaim_ai"] == "Unknown"


@pytest.mark.asyncio
async def test_smart_mode_does_not_overwrite_existing_child_vendor(db):
    """If the child already has a vendor_canonical, smart mode must not clobber."""
    await _seed(db, [
        _parent("P-2", vendor="PARENT_VENDOR"),
        _candidate("C-2", batch_parent_id="P-2", vendor_canonical="CHILD_VENDOR"),
    ])
    await run(execute=True, smart=True, db=db)
    child = await db.hub_documents.find_one({"id": "C-2"}, {"_id": 0})
    assert child["vendor_canonical"] == "CHILD_VENDOR"


@pytest.mark.asyncio
async def test_smart_mode_no_parent_falls_through_to_plain(db):
    await _seed(db, [_candidate("C-3", batch_parent_id=None)])
    r = await run(execute=True, smart=True, db=db)
    assert r["reclaimed_inherited_count"] == 0
    assert r["reclaimed_plain_count"] == 1
    child = await db.hub_documents.find_one({"id": "C-3"}, {"_id": 0})
    assert child.get("parent_inheritance_applied") is not True
    assert child["doc_type"] == "Unknown"  # unchanged in plain mode
    assert child["status"] == "NeedsReview"


@pytest.mark.asyncio
async def test_smart_mode_unclassified_parent_falls_through(db):
    """Parent itself is Unknown — nothing to inherit."""
    await _seed(db, [
        _parent("P-4", doc_type="Unknown"),
        _candidate("C-4", batch_parent_id="P-4"),
    ])
    r = await run(execute=True, smart=True, db=db)
    assert r["reclaimed_inherited_count"] == 0
    assert r["reclaimed_plain_count"] == 1


# ────────── skip_noise=True ──────────

@pytest.mark.asyncio
async def test_skip_noise_removes_from_review_queue(db):
    await _seed(db, [
        _candidate("N-1", file_name="linkedin_32x32_abcd.png"),
        _candidate("N-2", file_name="image.png"),
        _candidate("REAL-1", file_name="Invoice-123.pdf"),
    ])
    r = await run(execute=True, skip_noise=True, db=db)
    assert r["filtered_noise_count"] == 2
    assert r["reclaimed_plain_count"] == 1

    noise = await db.hub_documents.find_one({"id": "N-1"}, {"_id": 0})
    assert noise["noise_filtered"] is True
    assert noise["status"] == "Completed"  # NOT NeedsReview
    assert noise["queue_visible"] is False

    real = await db.hub_documents.find_one({"id": "REAL-1"}, {"_id": 0})
    assert real["status"] == "NeedsReview"


@pytest.mark.asyncio
async def test_skip_noise_respected_in_idempotency(db):
    """A noise-filtered doc carries reclaim_to_needs_review_at so the
    second run doesn't pick it up again."""
    await _seed(db, [_candidate("N-5", file_name="image.png")])
    first = await run(execute=True, skip_noise=True, db=db)
    assert first["filtered_noise_count"] == 1
    second = await run(execute=True, skip_noise=True, db=db)
    assert second["filtered_noise_count"] == 0
    assert second["reclaimed_plain_count"] == 0


# ────────── Combined modes ──────────

@pytest.mark.asyncio
async def test_noise_wins_over_smart_even_with_classified_parent(db):
    """A child with noisy filename should be filtered even if its parent
    is classified — email sprites never belong in the inbox."""
    await _seed(db, [
        _parent("P-N", doc_type="AP_Invoice", vendor="CARGOMO"),
        _candidate("CN-1", batch_parent_id="P-N", file_name="cmn_abcd1234.png"),
    ])
    r = await run(execute=True, smart=True, skip_noise=True, db=db)
    assert r["filtered_noise_count"] == 1
    assert r["reclaimed_inherited_count"] == 0
    child = await db.hub_documents.find_one({"id": "CN-1"}, {"_id": 0})
    assert child["noise_filtered"] is True
    assert child["status"] == "Completed"


# ────────── preview mode surface ──────────

@pytest.mark.asyncio
async def test_preview_surfaces_smart_and_noise_counts(db):
    await _seed(db, [
        _parent("P-X", doc_type="AP_Invoice", vendor="V"),
        _candidate("I1", batch_parent_id="P-X"),
        _candidate("I2", batch_parent_id="P-X"),
        _candidate("NS1", file_name="linkedin_32x32.png"),
        _candidate("PL1", file_name="real.pdf"),  # plain
    ])
    p = await preview(smart=True, skip_noise=True, db=db)
    assert p["total_candidates"] == 4
    assert p["sample_breakdown"]["smart_inheritable"] == 2
    assert p["sample_breakdown"]["filtered_as_noise"] == 1
    assert p["modes"] == {"smart": True, "skip_noise": True}
    # No mutations
    for did in ("I1", "I2", "NS1", "PL1"):
        d = await db.hub_documents.find_one({"id": did}, {"_id": 0})
        assert d["status"] == "Completed"
        assert d.get("reclaim_to_needs_review_at") in (None, "", False)


# ────────── Run result shape ──────────

@pytest.mark.asyncio
async def test_run_result_contains_all_mode_counters(db):
    await _seed(db, [
        _parent("P-R", doc_type="AP_Invoice", vendor="V"),
        _candidate("R-inh", batch_parent_id="P-R"),
        _candidate("R-plain"),
        _candidate("R-noise", file_name="signature.png"),
    ])
    r = await run(execute=True, smart=True, skip_noise=True, db=db)
    assert r["reclaimed_inherited_count"] == 1
    assert r["reclaimed_plain_count"] == 1
    assert r["filtered_noise_count"] == 1
    assert r["total_mutated"] == 3
    assert r["modes"] == {"smart": True, "skip_noise": True}
    # Legacy/back-compat field (inherited + plain only — noise is separate)
    assert r["reclaimed_count"] == 2
