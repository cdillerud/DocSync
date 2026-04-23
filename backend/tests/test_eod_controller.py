"""Pytest for Lane C Step 3B — EOD controller.

Tests run against mongomock_motor. Delegates are injected so the
controller's own logic is exercised without pulling readiness /
validation / reconciliation modules into the test path.

Covers exit criteria 3-10 from the 3B Pre-Change Declaration:
  - Flag-off router → 501 (in test_admin_eod_endpoints.py instead)
  - Dry-run → eod_run_log rows, zero hub_documents writes
  - Each step's write behavior
  - Step 3 scope fence (only 2 types; other Posted docs no-op)
  - Step 4 emits NO exceptions[] entry (b.ii amendment)
  - Semantic dedupe by (type, source_step, utc_day)
  - Idempotency: second run same day is effectively a no-op
  - No writes to unlisted hub_documents fields
  - No new collections beyond eod_run_log
"""

from __future__ import annotations

import uuid
from typing import Any

import mongomock_motor
import pytest

from workflows.batch.eod_controller import (
    ALL_STEPS,
    EodController,
    StepReport,
    get_last_run,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mongo_db():
    client = mongomock_motor.AsyncMongoMockClient()
    return client[f"test_eod_{uuid.uuid4().hex[:8]}"]


async def _insert(db, **fields):
    doc_id = fields.pop("id", None) or str(uuid.uuid4())
    doc = {"id": doc_id, **fields}
    await db.hub_documents.insert_one(doc)
    return doc_id


def _fake_delegates(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a delegate injection that neutralizes real I/O paths."""

    async def _noop_run_readiness(doc_id):
        return {"status": "ready"}

    async def _noop_retry_ready(limit=50):
        return {"success": True, "total": 0, "posted": 0, "failed": 0, "details": []}

    async def _noop_retry_failed(limit=100, force_escalate=False):
        return {"retried": 0, "escalated_to_exception": 0, "details": []}

    async def _noop_reconcile(line):
        return (0.0, 0.0, None)

    delegates = {
        "run_readiness": _noop_run_readiness,
        "retry_ready_to_post": _noop_retry_ready,
        "retry_failed_extractions": _noop_retry_failed,
        "reconcile_line_amounts": _noop_reconcile,
    }
    if overrides:
        delegates.update(overrides)
    return delegates


# ---------------------------------------------------------------------------
# 1. Dry-run semantics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestDryRun:
    async def test_dry_run_writes_run_log_with_dry_run_true(self, mongo_db):
        controller = EodController(mongo_db, delegates=_fake_delegates())
        await _insert(mongo_db, readiness={"status": "blocked"}, file_name="a.pdf")

        report = await controller.run_close_day(dry_run=True)

        assert report["dry_run"] is True
        rows = await mongo_db.eod_run_log.find({}).to_list(length=10)
        assert len(rows) == 5
        assert {r["step_name"] for r in rows} == set(ALL_STEPS)
        assert all(r["dry_run"] is True for r in rows)

    async def test_dry_run_writes_nothing_to_hub_documents(self, mongo_db):
        controller = EodController(mongo_db, delegates=_fake_delegates())
        doc_id = await _insert(
            mongo_db,
            readiness={"status": "blocked", "blocking_reasons": ["missing vendor"]},
            file_name="a.pdf",
        )

        await controller.run_close_day(dry_run=True)

        doc = await mongo_db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        assert "exceptions" not in doc
        assert "eod_send_surfaced_utc" not in doc
        # All originally-set fields remain untouched.
        assert doc["readiness"]["status"] == "blocked"


# ---------------------------------------------------------------------------
# 2. Step 1 — advance_readiness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAdvanceReadiness:
    async def test_blocked_after_reeval_emits_missing_master_data(self, mongo_db):
        async def _still_blocked(doc_id):
            return {"status": "blocked", "blocking_reasons": ["vendor_no missing"]}

        controller = EodController(
            mongo_db,
            delegates=_fake_delegates({"run_readiness": _still_blocked}),
        )
        doc_id = await _insert(mongo_db, readiness={"status": "blocked"})

        report = await controller.advance_readiness(
            run_id="r1", utc_day="2026-02-15"
        )

        assert isinstance(report, StepReport)
        assert report.processed == 1
        assert report.exceptions_by_type.get("missing_master_data") == 1

        doc = await mongo_db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        assert len(doc["exceptions"]) == 1
        ex = doc["exceptions"][0]
        assert ex["exception_type"] == "missing_master_data"
        assert ex["severity"] == "warn"
        assert ex["source_step"] == "advance_readiness"
        assert ex["utc_day"] == "2026-02-15"

    async def test_ready_after_reeval_emits_nothing(self, mongo_db):
        controller = EodController(mongo_db, delegates=_fake_delegates())
        await _insert(mongo_db, readiness={"status": "blocked"})

        report = await controller.advance_readiness(
            run_id="r1", utc_day="2026-02-15"
        )
        assert report.exceptions_by_type == {}


# ---------------------------------------------------------------------------
# 3. Step 2 — post_ready_docs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestPostReadyDocs:
    async def test_partial_post_error_emits_partial_post_record(self, mongo_db):
        doc_id = await _insert(mongo_db, status="ReadyForPost")

        async def _retry(limit=50):
            return {
                "posted": 0,
                "failed": 1,
                "details": [
                    {"doc_id": doc_id[:8], "action": "failed",
                     "error": "partial_post: 2 of 5 lines posted"},
                ],
            }

        controller = EodController(
            mongo_db,
            delegates=_fake_delegates({"retry_ready_to_post": _retry}),
        )
        report = await controller.post_ready_docs(
            run_id="r1", utc_day="2026-02-15"
        )
        assert report.exceptions_by_type.get("partial_post") == 1

        doc = await mongo_db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        assert doc["exceptions"][0]["exception_type"] == "partial_post"
        assert doc["exceptions"][0]["severity"] == "block"

    async def test_archived_collision_error_emits_archived_doc_collision(self, mongo_db):
        doc_id = await _insert(mongo_db, status="ReadyForPost")

        async def _retry(limit=50):
            return {
                "posted": 0,
                "failed": 1,
                "details": [
                    {"doc_id": doc_id[:8], "action": "failed",
                     "error": "doc already exists in archived set"},
                ],
            }

        controller = EodController(
            mongo_db,
            delegates=_fake_delegates({"retry_ready_to_post": _retry}),
        )
        report = await controller.post_ready_docs(
            run_id="r1", utc_day="2026-02-15"
        )
        assert report.exceptions_by_type.get("archived_doc_collision") == 1


# ---------------------------------------------------------------------------
# 4. Step 3 — send_posted_docs  (scope fence)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendPostedDocs:
    async def test_zero_amount_posted_surfaces_intentional_send_skip(self, mongo_db):
        doc_id = await _insert(mongo_db, status="Posted", amount_float=0.0)
        controller = EodController(mongo_db, delegates=_fake_delegates())

        report = await controller.send_posted_docs(
            run_id="r1", utc_day="2026-02-15"
        )

        assert report.exceptions_by_type.get("intentional_send_skip") == 1
        doc = await mongo_db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        assert doc["exceptions"][0]["exception_type"] == "intentional_send_skip"
        assert doc["exceptions"][0]["severity"] == "info"
        assert "eod_send_surfaced_utc" in doc

    async def test_archived_sibling_surfaces_collision(self, mongo_db):
        doc_id = await _insert(
            mongo_db, status="Posted", amount_float=100.0,
            archived_sibling_id="archived-123",
        )
        controller = EodController(mongo_db, delegates=_fake_delegates())

        report = await controller.send_posted_docs(
            run_id="r1", utc_day="2026-02-15"
        )

        assert report.exceptions_by_type.get("archived_doc_collision") == 1
        doc = await mongo_db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        assert doc["exceptions"][0]["exception_type"] == "archived_doc_collision"
        assert doc["exceptions"][0]["severity"] == "block"
        assert "eod_send_surfaced_utc" in doc

    async def test_normal_posted_doc_is_noop_no_flag(self, mongo_db):
        """Per user guardrail: only the 2 declared types may fire in Step 3."""
        doc_id = await _insert(mongo_db, status="Posted", amount_float=250.75)
        controller = EodController(mongo_db, delegates=_fake_delegates())

        report = await controller.send_posted_docs(
            run_id="r1", utc_day="2026-02-15"
        )

        assert report.exceptions_by_type == {}
        assert report.skipped == 1
        doc = await mongo_db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        assert "exceptions" not in doc
        assert "eod_send_surfaced_utc" not in doc  # flag ONLY set when exception fires

    async def test_flag_prevents_rescan(self, mongo_db):
        await _insert(mongo_db, status="Posted", amount_float=0.0)
        controller = EodController(mongo_db, delegates=_fake_delegates())

        await controller.send_posted_docs(run_id="r1", utc_day="2026-02-15")
        # Second pass: the doc has eod_send_surfaced_utc set; should be skipped.
        report2 = await controller.send_posted_docs(run_id="r2", utc_day="2026-02-16")
        assert report2.processed == 0


# ---------------------------------------------------------------------------
# 5. Step 4 — escalate_stuck  (b.ii: NO exceptions[] emission)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEscalateStuck:
    async def test_step_4_never_appends_to_exceptions_array(self, mongo_db):
        doc_id = await _insert(mongo_db, status="captured", retry_count=5)

        captured_id = doc_id

        async def _delegate(limit=100, force_escalate=False):
            # Simulate the existing escalation path doing its own hub_documents
            # writes (escalation_reason, status=Exception). Step 4 must NOT
            # add a typed entry to exceptions[] on top of that.
            await mongo_db.hub_documents.update_one(
                {"id": captured_id},
                {"$set": {"status": "Exception",
                          "workflow_status": "exception_review",
                          "escalation_reason": "max retries"}},
            )
            return {"retried": 0, "escalated_to_exception": 1,
                    "details": [{"doc_id": captured_id[:8], "action": "exception_queue"}]}

        controller = EodController(
            mongo_db,
            delegates=_fake_delegates({"retry_failed_extractions": _delegate}),
        )
        report = await controller.escalate_stuck(
            run_id="r1", utc_day="2026-02-15"
        )

        assert report.exceptions_by_type == {}
        doc = await mongo_db.hub_documents.find_one({"id": captured_id}, {"_id": 0})
        assert "exceptions" not in doc
        # Existing delegate writes are preserved.
        assert doc["status"] == "Exception"
        assert doc["escalation_reason"] == "max retries"


# ---------------------------------------------------------------------------
# 6. Step 5 — reconcile_cost_receipt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestReconcile:
    async def test_cost_variance_line_emits_cost_mismatch(self, mongo_db):
        doc_id = await _insert(
            mongo_db,
            status="Posted",
            posted_to_bc_at="2026-02-15T10:00:00+00:00",
            extracted_fields={
                "line_items": [
                    {"qty": 10, "unit_price": 5.0, "total": 55.0},
                ]
            },
        )

        async def _reconcile(line):
            return (50.0, 55.0, {"variance": 5.0, "expected": 50.0, "actual": 55.0})

        controller = EodController(
            mongo_db,
            delegates=_fake_delegates({"reconcile_line_amounts": _reconcile}),
        )
        report = await controller.reconcile_cost_receipt(
            run_id="r1", utc_day="2026-02-15"
        )

        assert report.exceptions_by_type.get("cost_mismatch") == 1
        doc = await mongo_db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        assert doc["exceptions"][0]["exception_type"] == "cost_mismatch"
        assert doc["exceptions"][0]["severity"] == "block"

    async def test_clean_line_reconcile_is_noop(self, mongo_db):
        doc_id = await _insert(
            mongo_db,
            status="Posted",
            posted_to_bc_at="2026-02-15T10:00:00+00:00",
            extracted_fields={"line_items": [{"qty": 1, "unit_price": 10.0, "total": 10.0}]},
        )
        controller = EodController(mongo_db, delegates=_fake_delegates())

        report = await controller.reconcile_cost_receipt(
            run_id="r1", utc_day="2026-02-15"
        )
        assert report.exceptions_by_type == {}
        doc = await mongo_db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        assert "exceptions" not in doc


# ---------------------------------------------------------------------------
# 7. Semantic dedupe + Idempotency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSemanticDedupe:
    async def test_second_run_same_day_does_not_duplicate_exception(self, mongo_db):
        doc_id = await _insert(mongo_db, status="Posted", amount_float=0.0)
        controller = EodController(mongo_db, delegates=_fake_delegates())

        await controller.send_posted_docs(run_id="r1", utc_day="2026-02-15")
        # Clear the per-doc flag so the doc re-enters the candidate set,
        # forcing the semantic dedupe guard to carry the load.
        await mongo_db.hub_documents.update_one(
            {"id": doc_id}, {"$unset": {"eod_send_surfaced_utc": ""}}
        )
        await controller.send_posted_docs(run_id="r2", utc_day="2026-02-15")

        doc = await mongo_db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        # Only one exception entry – semantic dedupe blocked the second append.
        assert len(doc["exceptions"]) == 1

    async def test_different_day_same_doc_allows_new_entry(self, mongo_db):
        doc_id = await _insert(mongo_db, status="Posted", amount_float=0.0)
        controller = EodController(mongo_db, delegates=_fake_delegates())

        await controller.send_posted_docs(run_id="r1", utc_day="2026-02-15")
        # Force eligibility on a new day.
        await mongo_db.hub_documents.update_one(
            {"id": doc_id}, {"$unset": {"eod_send_surfaced_utc": ""}}
        )
        await controller.send_posted_docs(run_id="r2", utc_day="2026-02-16")

        doc = await mongo_db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        assert len(doc["exceptions"]) == 2
        days = {ex["utc_day"] for ex in doc["exceptions"]}
        assert days == {"2026-02-15", "2026-02-16"}


@pytest.mark.asyncio
class TestIdempotency:
    async def test_two_full_runs_same_day_end_in_same_hub_state(self, mongo_db):
        # Seed two representative cases.
        zero_amount = await _insert(mongo_db, status="Posted", amount_float=0.0)
        normal = await _insert(mongo_db, status="Posted", amount_float=50.0)
        blocked = await _insert(mongo_db, readiness={"status": "blocked"})

        async def _still_blocked(doc_id):
            return {"status": "blocked", "blocking_reasons": ["x"]}

        controller = EodController(
            mongo_db,
            delegates=_fake_delegates({"run_readiness": _still_blocked}),
        )

        # Run 1.
        await controller.run_close_day()
        state1 = {
            d["id"]: d for d in
            await mongo_db.hub_documents.find({}, {"_id": 0}).to_list(length=10)
        }
        run_log_1 = await mongo_db.eod_run_log.count_documents({})

        # Run 2 (same day).
        await controller.run_close_day()
        state2 = {
            d["id"]: d for d in
            await mongo_db.hub_documents.find({}, {"_id": 0}).to_list(length=10)
        }
        run_log_2 = await mongo_db.eod_run_log.count_documents({})

        # eod_run_log gets a new set of 5 rows (audit trail is additive).
        assert run_log_2 == run_log_1 + 5
        # hub_documents state: exceptions[] has NOT grown between runs.
        for doc_id in (zero_amount, normal, blocked):
            assert (state1[doc_id].get("exceptions") or []) == (state2[doc_id].get("exceptions") or [])


# ---------------------------------------------------------------------------
# 8. Run-log shape + no new collections
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRunLogAndCollections:
    async def test_run_log_row_shape(self, mongo_db):
        controller = EodController(mongo_db, delegates=_fake_delegates())
        report = await controller.run_close_day(dry_run=True)

        rows = await mongo_db.eod_run_log.find({}).to_list(length=10)
        assert len(rows) == 5
        for row in rows:
            assert set(row.keys()) >= {
                "run_id", "step_name", "utc_day",
                "started_utc", "completed_utc",
                "processed", "succeeded", "skipped",
                "exceptions_by_type", "is_noop", "dry_run",
            }
        # All rows share the same run_id.
        assert len({r["run_id"] for r in rows}) == 1
        assert rows[0]["run_id"] == report["run_id"]

    async def test_only_eod_run_log_and_hub_documents_touched(self, mongo_db):
        controller = EodController(mongo_db, delegates=_fake_delegates())
        await _insert(mongo_db, status="Posted", amount_float=0.0)

        await controller.run_close_day()

        collections = await mongo_db.list_collection_names()
        # No collection other than eod_run_log and hub_documents is written.
        unexpected = set(collections) - {"eod_run_log", "hub_documents"}
        assert unexpected == set(), f"unexpected collections written: {unexpected}"

    async def test_unknown_step_name_raises(self, mongo_db):
        controller = EodController(mongo_db, delegates=_fake_delegates())
        with pytest.raises(ValueError):
            await controller.run_close_day(steps=["not_a_real_step"])

    async def test_subset_of_steps_runs_only_those(self, mongo_db):
        controller = EodController(mongo_db, delegates=_fake_delegates())
        await controller.run_close_day(
            steps=["advance_readiness", "send_posted_docs"]
        )
        rows = await mongo_db.eod_run_log.find({}).to_list(length=10)
        assert {r["step_name"] for r in rows} == {"advance_readiness", "send_posted_docs"}


# ---------------------------------------------------------------------------
# 9. get_last_run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGetLastRun:
    async def test_returns_latest_per_step_when_unfiltered(self, mongo_db):
        controller = EodController(mongo_db, delegates=_fake_delegates())
        await controller.run_close_day()
        await controller.run_close_day()

        result = await get_last_run(mongo_db)
        assert set(result["latest_per_step"].keys()) == set(ALL_STEPS)

    async def test_returns_single_step_when_filtered(self, mongo_db):
        controller = EodController(mongo_db, delegates=_fake_delegates())
        await controller.run_close_day()

        result = await get_last_run(mongo_db, step="advance_readiness")
        assert result["step"] == "advance_readiness"
        assert result["last_run"]["step_name"] == "advance_readiness"

    async def test_unknown_step_raises(self, mongo_db):
        with pytest.raises(ValueError):
            await get_last_run(mongo_db, step="nope")


# ---------------------------------------------------------------------------
# 10. Write-fence: no step mutates status/readiness/bc_* except via delegates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWriteFence:
    async def test_advance_readiness_does_not_mutate_status(self, mongo_db):
        async def _still_blocked(doc_id):
            return {"status": "blocked", "blocking_reasons": ["x"]}

        controller = EodController(
            mongo_db,
            delegates=_fake_delegates({"run_readiness": _still_blocked}),
        )
        doc_id = await _insert(
            mongo_db, readiness={"status": "blocked"}, status="Captured",
        )
        await controller.advance_readiness(run_id="r1", utc_day="2026-02-15")
        doc = await mongo_db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        # Step 1 touches ONLY exceptions[]; status stays as originally seeded.
        assert doc["status"] == "Captured"

    async def test_reconcile_does_not_mutate_bc_or_status_fields(self, mongo_db):
        doc_id = await _insert(
            mongo_db,
            status="Posted",
            posted_to_bc_at="2026-02-15T10:00:00+00:00",
            bc_record_no="PI-1001",
            extracted_fields={"line_items": [{"x": 1}]},
        )

        async def _reconcile(line):
            return (0, 1, {"variance": 1})

        controller = EodController(
            mongo_db,
            delegates=_fake_delegates({"reconcile_line_amounts": _reconcile}),
        )
        await controller.reconcile_cost_receipt(run_id="r1", utc_day="2026-02-15")
        doc = await mongo_db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        assert doc["status"] == "Posted"
        assert doc["bc_record_no"] == "PI-1001"
        assert doc["posted_to_bc_at"] == "2026-02-15T10:00:00+00:00"
