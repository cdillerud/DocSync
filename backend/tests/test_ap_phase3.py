"""
Integration tests for AP Invoice Advisory Phase 3:
 - Suggestion approve/reject/apply workflow
 - Learning impact review
 - Profile drift
 - Vendor hotspots
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone, timedelta


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "gpi_hub")

TEST_VENDOR_NO = "_TEST_V999"
TEST_VENDOR_NAME = "Test Vendor Phase3"


@pytest_asyncio.fixture
async def db():
    client = AsyncIOMotorClient(MONGO_URL)
    database = client[DB_NAME]
    yield database
    # Cleanup
    await database.ap_learning_suggestions.delete_many({"vendor_no": TEST_VENDOR_NO})
    await database.ap_reviewer_feedback.delete_many({"vendor_no": TEST_VENDOR_NO})
    await database.ap_learning_apply_audit.delete_many({"vendor_no": TEST_VENDOR_NO})
    await database.vendor_invoice_profiles.delete_many({"vendor_no": TEST_VENDOR_NO})
    client.close()


async def _seed_vendor_profile(db):
    await db.vendor_invoice_profiles.update_one(
        {"vendor_no": TEST_VENDOR_NO},
        {"$set": {
            "vendor_no": TEST_VENDOR_NO,
            "vendor_name": TEST_VENDOR_NAME,
            "bc_invoice_count": 25,
            "posting_confidence": "medium",
            "template_confidence": "medium",
            "amount_stats": {"min": 100, "max": 5000, "mean": 1200},
            "po_expected": True,
            "known_aliases": ["TEST VENDOR"],
            "accepted_reference_patterns": [],
            "vendor_variability_index": 0.5,
            "default_item_code": "TESTITEM",
        }},
        upsert=True,
    )


async def _seed_feedback(db, count=4):
    now = datetime.now(timezone.utc)
    for i in range(count):
        await db.ap_reviewer_feedback.insert_one({
            "document_id": f"test-doc-{i}",
            "vendor_no": TEST_VENDOR_NO,
            "vendor_name": TEST_VENDOR_NAME,
            "reviewer_assessment": "incorrect" if i < 3 else "correct",
            "disagreed_fields": ["vendor_match", "po_reference"] if i < 2 else [],
            "timestamp": (now - timedelta(days=i)).isoformat(),
        })


async def _seed_suggestion(db, stype="add_vendor_alias", status="pending"):
    sid = f"test-sugg-{stype[:8]}"
    await db.ap_learning_suggestions.update_one(
        {"suggestion_id": sid},
        {"$set": {
            "suggestion_id": sid,
            "suggestion_type": stype,
            "vendor_no": TEST_VENDOR_NO,
            "vendor_name": TEST_VENDOR_NAME,
            "supporting_documents": ["test-doc-0", "test-doc-1"],
            "supporting_feedback_count": 2,
            "evidence_summary": "Test evidence",
            "confidence": 0.75,
            "status": status,
            "fingerprint": f"{TEST_VENDOR_NO}:{stype}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return sid


# =============================================================================
# Suggestion Workflow Tests
# =============================================================================

@pytest.mark.asyncio
async def test_approve_suggestion(db):
    await _seed_suggestion(db, status="pending")
    from services.ap_invoice_learning_suggestion_apply_service import approve_ap_suggestion
    result = await approve_ap_suggestion(db, "test-sugg-add_vend", "tester")
    assert result["status"] == "approved"
    assert result["previous_status"] == "pending"


@pytest.mark.asyncio
async def test_reject_suggestion(db):
    await _seed_suggestion(db, status="pending")
    from services.ap_invoice_learning_suggestion_apply_service import reject_ap_suggestion
    result = await reject_ap_suggestion(db, "test-sugg-add_vend", "tester")
    assert result["status"] == "rejected"


@pytest.mark.asyncio
async def test_apply_requires_approved(db):
    await _seed_suggestion(db, status="pending")
    from services.ap_invoice_learning_suggestion_apply_service import apply_ap_suggestion
    result = await apply_ap_suggestion(db, "test-sugg-add_vend", "tester")
    assert "error" in result
    assert "must be 'approved'" in result["error"]


@pytest.mark.asyncio
async def test_apply_suggestion_success(db):
    await _seed_vendor_profile(db)
    sid = await _seed_suggestion(db, status="pending")
    from services.ap_invoice_learning_suggestion_apply_service import (
        approve_ap_suggestion, apply_ap_suggestion,
    )
    await approve_ap_suggestion(db, sid, "approver")
    result = await apply_ap_suggestion(db, sid, "applier")
    assert result["status"] == "applied"
    assert result["no_op"] is False
    # Verify audit record
    audit = await db.ap_learning_apply_audit.find_one(
        {"suggestion_id": sid}, {"_id": 0}
    )
    assert audit is not None
    assert audit["applied_by"] == "applier"


@pytest.mark.asyncio
async def test_apply_idempotent_alias(db):
    """Applying same alias twice should be no-op the second time."""
    await _seed_vendor_profile(db)
    # First apply
    sid1 = await _seed_suggestion(db, stype="add_vendor_alias", status="pending")
    from services.ap_invoice_learning_suggestion_apply_service import (
        approve_ap_suggestion, apply_ap_suggestion,
    )
    await approve_ap_suggestion(db, sid1, "a")
    r1 = await apply_ap_suggestion(db, sid1, "a")
    assert r1["status"] == "applied"

    # Second apply with same vendor name
    sid2 = "test-sugg-dup"
    await db.ap_learning_suggestions.update_one(
        {"suggestion_id": sid2},
        {"$set": {
            "suggestion_id": sid2,
            "suggestion_type": "add_vendor_alias",
            "vendor_no": TEST_VENDOR_NO,
            "vendor_name": TEST_VENDOR_NAME,
            "status": "approved",
            "approved_by": "a",
            "fingerprint": f"{TEST_VENDOR_NO}:add_vendor_alias_2",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    r2 = await apply_ap_suggestion(db, sid2, "a")
    assert r2["status"] == "applied"
    assert r2["no_op"] is True


# =============================================================================
# Impact Review Tests
# =============================================================================

@pytest.mark.asyncio
async def test_impact_review_empty(db):
    from services.ap_invoice_learning_impact_review_service import run_ap_learning_impact_review
    result = await run_ap_learning_impact_review(db)
    assert result["total_applied"] == 0


@pytest.mark.asyncio
async def test_impact_review_with_data(db):
    await _seed_vendor_profile(db)
    await _seed_feedback(db, count=4)
    sid = await _seed_suggestion(db, status="pending")
    from services.ap_invoice_learning_suggestion_apply_service import (
        approve_ap_suggestion, apply_ap_suggestion,
    )
    await approve_ap_suggestion(db, sid, "a")
    await apply_ap_suggestion(db, sid, "a")

    from services.ap_invoice_learning_impact_review_service import run_ap_learning_impact_review
    result = await run_ap_learning_impact_review(db, vendor_no=TEST_VENDOR_NO)
    assert result["total_applied"] >= 1
    assert result["vendors_affected"] >= 1


# =============================================================================
# Profile Drift Tests
# =============================================================================

@pytest.mark.asyncio
async def test_drift_empty(db):
    from services.ap_invoice_profile_drift_service import get_ap_profile_drift_summary
    result = await get_ap_profile_drift_summary(db)
    assert "total_vendors" in result


@pytest.mark.asyncio
async def test_drift_with_data(db):
    await _seed_vendor_profile(db)
    await _seed_feedback(db)
    sid = await _seed_suggestion(db, status="pending")
    from services.ap_invoice_learning_suggestion_apply_service import (
        approve_ap_suggestion, apply_ap_suggestion,
    )
    await approve_ap_suggestion(db, sid, "a")
    await apply_ap_suggestion(db, sid, "a")

    from services.ap_invoice_profile_drift_service import get_ap_profile_drift_summary, get_ap_vendor_drift_detail
    summary = await get_ap_profile_drift_summary(db, vendor_no=TEST_VENDOR_NO)
    assert summary["total_vendors"] >= 1

    detail = await get_ap_vendor_drift_detail(db, TEST_VENDOR_NO)
    assert "drift_risk" in detail
    assert "timeline" in detail
    assert len(detail["timeline"]) >= 1


@pytest.mark.asyncio
async def test_change_history(db):
    await _seed_vendor_profile(db)
    sid = await _seed_suggestion(db, status="pending")
    from services.ap_invoice_learning_suggestion_apply_service import (
        approve_ap_suggestion, apply_ap_suggestion,
    )
    await approve_ap_suggestion(db, sid, "a")
    await apply_ap_suggestion(db, sid, "a")

    from services.ap_invoice_profile_drift_service import get_ap_change_history
    result = await get_ap_change_history(db, TEST_VENDOR_NO)
    assert result["total"] >= 1
    assert len(result["changes"]) >= 1


# =============================================================================
# Vendor Hotspot Tests
# =============================================================================

@pytest.mark.asyncio
async def test_hotspots_empty(db):
    from services.ap_invoice_vendor_hotspot_review_service import get_ap_vendor_hotspots
    result = await get_ap_vendor_hotspots(db)
    assert "total_vendors_analyzed" in result


@pytest.mark.asyncio
async def test_hotspots_with_data(db):
    await _seed_vendor_profile(db)
    await _seed_feedback(db, count=5)

    from services.ap_invoice_vendor_hotspot_review_service import get_ap_vendor_hotspots, get_ap_vendor_hotspot_detail
    result = await get_ap_vendor_hotspots(db, vendor_no=TEST_VENDOR_NO)
    assert result["total_vendors_analyzed"] >= 1
    hotspots = result["hotspots"]
    assert len(hotspots) >= 1
    h = hotspots[0]
    assert h["vendor_no"] == TEST_VENDOR_NO
    assert h["hotspot_score"] > 0
    assert "root_causes" in h

    detail = await get_ap_vendor_hotspot_detail(db, TEST_VENDOR_NO)
    assert "recent_feedback" in detail
    assert "pending_suggestions" in detail
