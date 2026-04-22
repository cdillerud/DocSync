"""
Lane A A1 — Historical posting-attempts array.

Contract under test:
  * Every BC write appends one entry to hub_documents.bc_posting_attempts[].
  * Entries are append-only — no overwrite, no delete.
  * Status values are one of: posted | failed | partial | pending_retry.
  * `bc_posting_error` string stays as the fast-access projection of the
    most recent failing attempt (dashboard aggregations still read it).
  * Legacy migration synthesizes entries for documents that had a prior
    bc_posting_error string but no bc_posting_attempts array.

These tests exercise the service surfaces directly (no HTTP) so they can
mock BC cleanly without triggering real tenant writes.
"""

import os
import uuid
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from motor.motor_asyncio import AsyncIOMotorClient


def _load_env():
    raw = open("/app/backend/.env").read()
    out = {}
    for line in raw.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


@pytest_asyncio.fixture
async def test_db():
    """Real motor DB + isolated doc cleanup."""
    env = _load_env()
    client = AsyncIOMotorClient(env["MONGO_URL"])
    db = client[env["DB_NAME"]]
    created_ids: list[str] = []
    yield db, created_ids
    # Cleanup: drop all docs we created (not real customer data).
    if created_ids:
        await db.hub_documents.delete_many({"id": {"$in": created_ids}})
    client.close()


# ---------------------------------------------------------------------------
# build_attempt shape invariants
# ---------------------------------------------------------------------------


def test_build_attempt_shape_is_stable():
    from services.bc_posting_attempts import build_attempt, new_correlation_id

    attempt = build_attempt(
        attempt_n=1,
        status="posted",
        actor="user:hub-admin@gamerpackaging.com",
        source="manual_post_to_bc",
        correlation_id=new_correlation_id(),
        bc_record_no="PI-001",
        bc_document_id="guid-1",
    )

    # Every field from the spec must be present, with None placeholders
    # where not provided — the shape is stable across attempts.
    required = {
        "attempt_n", "attempt_id", "correlation_id", "started_utc",
        "finished_utc", "elapsed_ms", "status", "actor", "source",
        "bc_record_no", "bc_document_id", "error", "error_full",
        "retry_reason", "gate_id", "bc_response_snippet", "partial_lines",
    }
    assert set(attempt.keys()) == required
    assert attempt["attempt_n"] == 1
    assert attempt["status"] == "posted"
    assert attempt["bc_record_no"] == "PI-001"


def test_build_attempt_truncates_long_errors_and_preserves_full():
    from services.bc_posting_attempts import build_attempt, new_correlation_id, ERROR_SUMMARY_MAX

    long_err = "x" * (ERROR_SUMMARY_MAX + 500)
    attempt = build_attempt(
        attempt_n=1,
        status="failed",
        actor="engine:auto_post",
        source="ap_auto_post_service",
        correlation_id=new_correlation_id(),
        error=long_err,
    )
    assert len(attempt["error"]) <= ERROR_SUMMARY_MAX
    assert attempt["error_full"] == long_err


def test_build_attempt_short_error_does_not_populate_error_full():
    from services.bc_posting_attempts import build_attempt, new_correlation_id

    attempt = build_attempt(
        attempt_n=1,
        status="failed",
        actor="engine:auto_post",
        source="ap_auto_post_service",
        correlation_id=new_correlation_id(),
        error="short error",
    )
    assert attempt["error"] == "short error"
    assert attempt["error_full"] is None


# ---------------------------------------------------------------------------
# next_attempt_n / append semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_attempt_n_on_empty_doc_returns_1(test_db):
    db, created = test_db
    doc_id = f"test-a1-{uuid.uuid4().hex[:8]}"
    created.append(doc_id)
    await db.hub_documents.insert_one({"id": doc_id})

    from services.bc_posting_attempts import next_attempt_n
    assert await next_attempt_n(db, doc_id) == 1


@pytest.mark.asyncio
async def test_next_attempt_n_increments_with_existing_attempts(test_db):
    db, created = test_db
    doc_id = f"test-a1-{uuid.uuid4().hex[:8]}"
    created.append(doc_id)
    await db.hub_documents.insert_one({
        "id": doc_id,
        "bc_posting_attempts": [
            {"attempt_n": 1}, {"attempt_n": 2}, {"attempt_n": 3},
        ],
    })
    from services.bc_posting_attempts import next_attempt_n
    assert await next_attempt_n(db, doc_id) == 4


@pytest.mark.asyncio
async def test_record_standalone_attempt_is_append_only(test_db):
    db, created = test_db
    doc_id = f"test-a1-{uuid.uuid4().hex[:8]}"
    created.append(doc_id)
    await db.hub_documents.insert_one({"id": doc_id})

    from services.bc_posting_attempts import (
        build_attempt, new_correlation_id, record_standalone_attempt,
    )

    cid = new_correlation_id()
    for n, status in enumerate(["pending_retry", "pending_retry", "posted"], start=1):
        a = build_attempt(
            attempt_n=n, status=status,
            actor="engine:auto_post", source="ap_auto_post_service",
            correlation_id=cid,
            error=f"error {n}" if status != "posted" else None,
        )
        await record_standalone_attempt(db, doc_id, a, also_set={
            "bc_posting_status": status,
            "bc_posting_error": a.get("error"),
        })

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    attempts = doc["bc_posting_attempts"]
    assert len(attempts) == 3, "every attempt must be appended; no overwrite"
    assert [a["status"] for a in attempts] == ["pending_retry", "pending_retry", "posted"]
    # Chronological — attempt_n monotonic.
    assert [a["attempt_n"] for a in attempts] == [1, 2, 3]
    # All share correlation_id (same logical retry chain).
    assert all(a["correlation_id"] == cid for a in attempts)


# ---------------------------------------------------------------------------
# release_claim integration — success / failure / partial path each append
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_claim_with_attempt_appends_atomically(test_db):
    db, created = test_db
    doc_id = f"test-a1-{uuid.uuid4().hex[:8]}"
    created.append(doc_id)
    # Seed an in-flight doc (claim already acquired).
    await db.hub_documents.insert_one({
        "id": doc_id,
        "bc_posting_status": "posting",
        "bc_posting_claimed_by": "test-worker",
        "bc_posting_claimed_at": "2026-04-22T00:00:00+00:00",
    })

    from services.bc_post_claim import release_claim
    from services.bc_posting_attempts import build_attempt, new_correlation_id

    attempt = build_attempt(
        attempt_n=1, status="posted",
        actor="user:test", source="manual_post_to_bc",
        correlation_id=new_correlation_id(),
        bc_record_no="PI-42",
    )
    await release_claim(
        db, doc_id=doc_id, final_state="posted",
        extra_set={"bc_document_number": "PI-42"},
        attempt=attempt,
    )

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    # Terminal state written.
    assert doc["bc_posting_status"] == "posted"
    assert doc["bc_posting_claimed_by"] is None
    # Attempt appended in the same update_one.
    assert len(doc["bc_posting_attempts"]) == 1
    assert doc["bc_posting_attempts"][0]["status"] == "posted"
    assert doc["bc_posting_attempts"][0]["bc_record_no"] == "PI-42"


@pytest.mark.asyncio
async def test_release_claim_without_attempt_does_not_break_legacy_callers(test_db):
    """Backwards-compat: callers that haven't migrated still work."""
    db, created = test_db
    doc_id = f"test-a1-{uuid.uuid4().hex[:8]}"
    created.append(doc_id)
    await db.hub_documents.insert_one({
        "id": doc_id,
        "bc_posting_status": "posting",
    })

    from services.bc_post_claim import release_claim
    await release_claim(db, doc_id=doc_id, final_state="failed",
                        extra_set={"bc_posting_error": "legacy"})

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    assert doc["bc_posting_status"] == "failed"
    # No attempt appended when attempt=None — that's the legacy path.
    assert "bc_posting_attempts" not in doc or doc["bc_posting_attempts"] == []


# ---------------------------------------------------------------------------
# Legacy migration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_migration_synthesizes_single_entry(test_db):
    db, created = test_db
    doc_id = f"test-a1-legacy-{uuid.uuid4().hex[:8]}"
    created.append(doc_id)
    await db.hub_documents.insert_one({
        "id": doc_id,
        "bc_posting_status": "failed",
        "bc_posting_error": "BC server 500",
        "updated_utc": "2026-04-20T10:00:00+00:00",
    })

    from services.bc_posting_attempts import migrate_legacy_bc_posting_error
    stats = await migrate_legacy_bc_posting_error(db)

    assert stats["migrated"] >= 1
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    assert len(doc["bc_posting_attempts"]) == 1
    entry = doc["bc_posting_attempts"][0]
    assert entry["status"] == "failed"
    assert entry["error"] == "BC server 500"
    assert entry["actor"] == "legacy_migration"
    assert entry["source"] == "legacy_migration"
    # bc_posting_error preserved as fast-access summary.
    assert doc["bc_posting_error"] == "BC server 500"


@pytest.mark.asyncio
async def test_legacy_migration_is_idempotent(test_db):
    db, created = test_db
    doc_id = f"test-a1-legacy-idem-{uuid.uuid4().hex[:8]}"
    created.append(doc_id)
    await db.hub_documents.insert_one({
        "id": doc_id,
        "bc_posting_status": "failed",
        "bc_posting_error": "one-time error",
    })

    from services.bc_posting_attempts import migrate_legacy_bc_posting_error
    first = await migrate_legacy_bc_posting_error(db)
    await migrate_legacy_bc_posting_error(db)
    assert first["migrated"] >= 1
    # Second run must not re-synthesize the same doc.
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    assert len(doc["bc_posting_attempts"]) == 1


# ---------------------------------------------------------------------------
# ap_auto_post_service — four write paths each append ONE attempt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ap_auto_post_success_appends_posted_attempt(test_db):
    db, created = test_db
    doc_id = f"test-a1-auto-{uuid.uuid4().hex[:8]}"
    created.append(doc_id)
    await db.hub_documents.insert_one({
        "id": doc_id,
        "document_type": "AP_Invoice",
        "doc_type": "AP_Invoice",
        "status": "ReadyForPost",
        "bc_vendor_number": "V1",
    })

    from services import ap_auto_post_service
    with patch.dict(os.environ, {"BC_WRITE_ENABLED": "true"}), \
         patch.object(ap_auto_post_service, "check_ap_ready_to_post",
                      return_value=(True, "ready", [])), \
         patch("routers.gpi_integration.create_purchase_invoice_from_document",
               AsyncMock(return_value={
                   "success": True,
                   "bc_record_no": "PI-AUTO-1",
                   "bc_system_id": "guid-auto-1",
               })), \
         patch.object(ap_auto_post_service, "_write_event", AsyncMock()), \
         patch.object(ap_auto_post_service, "_record_success_feedback", AsyncMock()):
        await ap_auto_post_service.attempt_ap_auto_post(doc_id, db, source="test")

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    assert len(doc["bc_posting_attempts"]) == 1
    a = doc["bc_posting_attempts"][0]
    assert a["status"] == "posted"
    assert a["actor"] == "engine:auto_post"
    assert a["bc_record_no"] == "PI-AUTO-1"


@pytest.mark.asyncio
async def test_ap_auto_post_partial_post_appends_partial_attempt(test_db):
    db, created = test_db
    doc_id = f"test-a1-auto-pp-{uuid.uuid4().hex[:8]}"
    created.append(doc_id)
    await db.hub_documents.insert_one({
        "id": doc_id,
        "document_type": "AP_Invoice",
        "doc_type": "AP_Invoice",
        "status": "ReadyForPost",
        "bc_vendor_number": "V1",
    })

    from services import ap_auto_post_service
    partial_result = {
        "success": False,
        "error": "partial_post",
        "partial_post": True,
        "linesAdded": 0,
        "linesTotal": 2,
    }
    with patch.dict(os.environ, {"BC_WRITE_ENABLED": "true"}), \
         patch.object(ap_auto_post_service, "check_ap_ready_to_post",
                      return_value=(True, "ready", [])), \
         patch("routers.gpi_integration.create_purchase_invoice_from_document",
               AsyncMock(return_value=partial_result)), \
         patch.object(ap_auto_post_service, "_write_event", AsyncMock()), \
         patch.object(ap_auto_post_service, "_record_success_feedback", AsyncMock()):
        await ap_auto_post_service.attempt_ap_auto_post(doc_id, db, source="test")

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    assert len(doc["bc_posting_attempts"]) == 1
    a = doc["bc_posting_attempts"][0]
    # Partial post status is recorded as its own category, not lumped as "failed".
    assert a["status"] == "partial"
    assert a["partial_lines"] == {"added": 0, "total": 2}
    # bc_posting_status on the doc must NOT be "posted" (Work Item B regression).
    assert doc["bc_posting_status"] != "posted"
