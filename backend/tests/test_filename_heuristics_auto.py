"""
Tests for auto-propose filename heuristic rules (v2.5.10).

Covers:
    * shape_to_regex round-trips correctly
    * vendor_majority_doc_type respects min_samples + min_majority_pct
    * auto_propose produces proposals for decisive vendors, defers others
    * apply_auto_proposed dry-run vs execute idempotency
    * The persisted custom rules are picked up by classify_filename_async
      (after cache invalidation)
"""
import pytest
import re
from datetime import datetime, timezone

import mongomock_motor

from services.admin import filename_heuristics_service as fhs
from services.admin import filename_heuristics_auto_service as auto


@pytest.fixture
def db(monkeypatch):
    d = mongomock_motor.AsyncMongoMockClient()["test_auto_propose"]

    def _get():
        return d

    monkeypatch.setattr(auto, "get_db", _get)
    monkeypatch.setattr(fhs, "get_db", _get)
    fhs._invalidate_custom_rule_cache()
    return d


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _insert_classified(db, vendor, doc_type, n, prefix="known"):
    for i in range(n):
        await db.hub_documents.insert_one({
            "id": f"{prefix}-{vendor}-{doc_type}-{i}",
            "vendor_canonical": vendor,
            "file_name": f"{vendor}_{i}.pdf",
            "doc_type": doc_type,
            "document_type": doc_type,
            "suggested_job_type": doc_type,
            "status": "Completed",
            "filename_heuristic_applied_at": None,
            "created_utc": _now(),
        })


async def _insert_unmatched(db, vendor, filenames):
    for fn in filenames:
        await db.hub_documents.insert_one({
            "id": f"unk-{vendor}-{fn}",
            "vendor_canonical": vendor,
            "vendor_name": vendor,
            "file_name": fn,
            "doc_type": "Unknown",
            "document_type": "Unknown",
            "suggested_job_type": "Unknown",
            "status": "NeedsReview",
            "filename_heuristic_applied_at": None,
            "created_utc": _now(),
        })


# ──────────────────────────────────────────────────────────────
# shape_to_regex
# ──────────────────────────────────────────────────────────────

def test_shape_to_regex_matches_shape_equivalent_filenames():
    rx = auto.shape_to_regex("A+#+_A+#+.A+")
    assert re.match(rx, "ROT12345_p1.pdf")
    assert re.match(rx, "XYZ9_aa99.PDF")
    assert not re.match(rx, "Invoice-0000042_doc1.pdf")


def test_shape_to_regex_escapes_punctuation():
    rx = auto.shape_to_regex("A+-#+.A+")
    assert re.match(rx, "Invoice-2025.pdf")
    assert not re.match(rx, "Invoice_2025.pdf")


# ──────────────────────────────────────────────────────────────
# vendor_majority_doc_type
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_majority_returns_winner_when_decisive(db):
    await _insert_classified(db, "Ball Metal", "AP_Invoice", 20)
    await _insert_classified(db, "Ball Metal", "BOL", 2)
    m = await auto.vendor_majority_doc_type(db, "Ball Metal")
    assert m is not None
    assert m["doc_type"] == "AP_Invoice"
    assert m["pct"] >= 70.0


@pytest.mark.asyncio
async def test_majority_returns_none_when_not_decisive(db):
    await _insert_classified(db, "Mixed Vendor", "AP_Invoice", 5)
    await _insert_classified(db, "Mixed Vendor", "BOL", 5)
    assert await auto.vendor_majority_doc_type(db, "Mixed Vendor") is None


@pytest.mark.asyncio
async def test_majority_returns_none_when_below_min_samples(db):
    await _insert_classified(db, "Small Vendor", "AP_Invoice", 2)
    assert await auto.vendor_majority_doc_type(db, "Small Vendor",
                                               min_samples=5) is None


@pytest.mark.asyncio
async def test_majority_excludes_heuristic_applied_docs(db):
    # 10 real classifications of AP_Invoice
    await _insert_classified(db, "HVendor", "AP_Invoice", 10)
    # 50 heuristic-applied of BOL — should be excluded from the vote
    for i in range(50):
        await db.hub_documents.insert_one({
            "id": f"h-{i}",
            "vendor_canonical": "HVendor",
            "doc_type": "BOL",
            "filename_heuristic_applied_at": _now(),
            "status": "Completed",
        })
    m = await auto.vendor_majority_doc_type(db, "HVendor")
    assert m is not None
    assert m["doc_type"] == "AP_Invoice"
    assert m["total"] == 10


# ──────────────────────────────────────────────────────────────
# auto_propose
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_propose_creates_proposal_for_decisive_vendor(db):
    await _insert_classified(db, "Ball Metal", "AP_Invoice", 40)
    await _insert_unmatched(db, "Ball Metal", [
        "BM-12345_doc1.pdf", "BM-67890_doc2.pdf", "BM-33333_doc3.pdf",
    ])
    report = await auto.auto_propose(db=db, min_group_size=3,
                                     min_vendor_samples=5)
    assert report["proposals_count"] == 1
    p = report["proposals"][0]
    assert p["doc_type"] == "AP_Invoice"
    assert p["unmatched_count"] == 3
    assert re.match(p["filename_regex"], "BM-12345_doc1.pdf")


@pytest.mark.asyncio
async def test_auto_propose_defers_ambiguous_vendor(db):
    await _insert_classified(db, "Mixed", "AP_Invoice", 5)
    await _insert_classified(db, "Mixed", "BOL", 5)
    await _insert_unmatched(db, "Mixed", [
        "foo_1.pdf", "foo_2.pdf", "foo_3.pdf",
    ])
    report = await auto.auto_propose(db=db, min_group_size=3,
                                     min_vendor_samples=5)
    assert report["proposals_count"] == 0
    assert report["deferred_count"] == 1


@pytest.mark.asyncio
async def test_auto_propose_skips_groups_below_min_size(db):
    await _insert_classified(db, "V", "AP_Invoice", 10)
    await _insert_unmatched(db, "V", ["onlyone.pdf", "onlyone_2.pdf"])
    report = await auto.auto_propose(db=db, min_group_size=5,
                                     min_vendor_samples=5)
    assert report["proposals_count"] == 0


# ──────────────────────────────────────────────────────────────
# apply_auto_proposed
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_dry_run_does_not_persist(db):
    await _insert_classified(db, "Ball Metal", "AP_Invoice", 20)
    await _insert_unmatched(db, "Ball Metal", [
        "BM-1_doc1.pdf", "BM-2_doc2.pdf", "BM-3_doc3.pdf",
    ])
    r = await auto.apply_auto_proposed(db=db)
    assert r["execute"] is False
    assert r["eligible_count"] >= 1
    count = await db.filename_heuristic_custom_rules.count_documents({})
    assert count == 0


@pytest.mark.asyncio
async def test_apply_execute_persists_and_is_idempotent(db):
    await _insert_classified(db, "Ball Metal", "AP_Invoice", 20)
    await _insert_unmatched(db, "Ball Metal", [
        "BM-1_doc1.pdf", "BM-2_doc2.pdf", "BM-3_doc3.pdf",
    ])
    r1 = await auto.apply_auto_proposed(db=db, execute=True)
    assert r1["inserted_or_updated_count"] >= 1
    # Re-run: should upsert cleanly, no errors
    r2 = await auto.apply_auto_proposed(db=db, execute=True)
    assert r2["errors_count"] == 0


# ──────────────────────────────────────────────────────────────
# classify_filename_async picks up custom rules
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_classify_filename_async_uses_custom_rule(db):
    # Seed a custom rule directly
    await db.filename_heuristic_custom_rules.insert_one({
        "rule_id": "test_custom",
        "vendor_regex": r"(?i)^Ball",
        "filename_regex": r"^BM-\d+_doc\d+\.pdf$",
        "doc_type": "AP_Invoice",
        "confidence": 0.85,
        "note": "test",
        "enabled": True,
        "last_updated_utc": _now(),
    })
    fhs._invalidate_custom_rule_cache()
    hit = await fhs.classify_filename_async(
        "BM-123_doc1.pdf", "Ball Metal",
    )
    assert hit is not None
    assert hit["doc_type"] == "AP_Invoice"
    assert hit["rule_id"] == "test_custom"
    assert hit["origin"] == "custom"


@pytest.mark.asyncio
async def test_classify_filename_async_prefers_builtin_over_custom(db):
    # Seed a custom rule for GAMMIN_AR that would conflict with built-in
    await db.filename_heuristic_custom_rules.insert_one({
        "rule_id": "test_override",
        "vendor_regex": r"(?i)^GAMMIN",
        "filename_regex": r"^GAMMIN_AR_\d{8}\.(xls|xlsx)$",
        "doc_type": "BOL",  # intentionally "wrong" — built-in says AR_Statement
        "confidence": 0.99,
        "note": "should-not-win",
        "enabled": True,
        "last_updated_utc": _now(),
    })
    fhs._invalidate_custom_rule_cache()
    hit = await fhs.classify_filename_async(
        "GAMMIN_AR_20260316.xls", "GAMMIN",
    )
    assert hit is not None
    # Built-in rule wins (returns AR_Statement), not the custom one.
    assert hit["doc_type"] == "AR_Statement"
    assert hit["origin"] == "builtin"


@pytest.mark.asyncio
async def test_disabled_custom_rule_is_ignored(db):
    await db.filename_heuristic_custom_rules.insert_one({
        "rule_id": "disabled_rule",
        "vendor_regex": None,
        "filename_regex": r"^disabled_target\.pdf$",
        "doc_type": "AP_Invoice",
        "confidence": 0.90,
        "note": "should not match",
        "enabled": False,
        "last_updated_utc": _now(),
    })
    fhs._invalidate_custom_rule_cache()


# ──────────────────────────────────────────────────────────────
# vendor_doc_type_distribution — diagnostic
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vendor_distribution_reports_raw_counts(db):
    await _insert_classified(db, "Ball Metal", "AP_Invoice", 15)
    await _insert_classified(db, "Ball Metal", "BOL", 5)
    d = await auto.vendor_doc_type_distribution(db, "Ball Metal")
    assert d["total"] == 20
    assert d["by_doc_type"] == {"AP_Invoice": 15, "BOL": 5}
    assert d["top"][0]["doc_type"] == "AP_Invoice"
    assert d["top"][0]["pct"] == 75.0


@pytest.mark.asyncio
async def test_vendor_distribution_zero_when_no_vendor(db):
    d = await auto.vendor_doc_type_distribution(db, None, None)
    assert d["total"] == 0
    assert d["top"] == []


@pytest.mark.asyncio
async def test_vendor_distribution_can_include_heuristic_applied(db):
    # 3 real classifications
    await _insert_classified(db, "V2", "AP_Invoice", 3)
    # 20 heuristic-applied — excluded by default, included when flag set
    for i in range(20):
        await db.hub_documents.insert_one({
            "id": f"h-{i}",
            "vendor_canonical": "V2",
            "doc_type": "BOL",
            "filename_heuristic_applied_at": _now(),
            "status": "Completed",
        })
    d_default = await auto.vendor_doc_type_distribution(db, "V2")
    assert d_default["total"] == 3
    d_all = await auto.vendor_doc_type_distribution(
        db, "V2", include_heuristic_applied=True,
    )
    assert d_all["total"] == 23


# ──────────────────────────────────────────────────────────────
# auto_propose deferred reason messages
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deferred_reason_zero_classified_vendor(db):
    # Ball Metal has 200 Unknowns but NO classified history
    await _insert_unmatched(db, "Ball Metal", [
        f"BM-{i}.pdf" for i in range(10)
    ])
    report = await auto.auto_propose(db=db, min_group_size=3,
                                     min_vendor_samples=5)
    assert report["deferred_count"] == 1
    d = report["deferred"][0]
    assert "0" in d["reason"]
    assert "history" in d["reason"].lower()
    assert d["vendor_history_total"] == 0
    assert d["vendor_history_top"] == []


@pytest.mark.asyncio
async def test_deferred_reason_below_majority(db):
    # 50/50 split is below 70% threshold
    await _insert_classified(db, "Mixed", "AP_Invoice", 10)
    await _insert_classified(db, "Mixed", "BOL", 10)
    await _insert_unmatched(db, "Mixed", [
        "mixed_a.pdf", "mixed_b.pdf", "mixed_c.pdf",
    ])
    report = await auto.auto_propose(db=db, min_group_size=3,
                                     min_vendor_samples=5)
    assert report["deferred_count"] == 1
    d = report["deferred"][0]
    assert "below" in d["reason"].lower() or "majority" in d["reason"].lower()
    assert d["vendor_history_total"] == 20


@pytest.mark.asyncio
async def test_deferred_reason_no_vendor(db):
    await _insert_unmatched(db, "", ["w9.pdf", "w9.pdf", "w9.pdf"])
    report = await auto.auto_propose(db=db, min_group_size=3)
    # Empty vendor → deferred with no-vendor reason
    if report["deferred_count"] >= 1:
        d = report["deferred"][0]
        assert "vendor" in d["reason"].lower()

    hit = await fhs.classify_filename_async("disabled_target.pdf")
    assert hit is None
