"""
Tests for services/bc_post_claim.py — atomic claim primitive that
prevents duplicate BC purchase-invoice / sales-order creation under
concurrent callers.

Two layers of verification:

1. **Filter-logic tests (mongomock)** — verify the atomic
   ``find_one_and_update`` filter correctly accepts/rejects claims for
   every state × TTL × holder combination.

2. **Real-concurrency test (localhost MongoDB)** — launch N concurrent
   ``asyncio`` tasks all trying to claim the same document; assert
   exactly one wins and the rest see ``reason="active_claim"``. This is
   the test that would have caught the pre-fix defect.

The integration test is marked ``asyncio`` and skipped if
``MONGO_URL`` is unreachable.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import List

import mongomock_motor
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from services.bc_post_claim import (
    CLAIM_TTL_SECONDS,
    IN_FLIGHT_STATES,
    TERMINAL_SUCCESS_STATES,
    ClaimRejectionReason,
    claim_for_bc_post,
    release_claim,
)


# ---------------------------------------------------------------------------
# Filter-logic tests — mongomock-backed, isolated, fast.
# ---------------------------------------------------------------------------

@pytest.fixture
def mongo_db():
    """Isolated per-test mongomock database."""
    client = mongomock_motor.AsyncMongoMockClient()
    return client[f"test_bc_claim_{uuid.uuid4().hex[:8]}"]


async def _insert(db, **fields):
    doc_id = fields.pop("id", None) or str(uuid.uuid4())
    doc = {"id": doc_id, **fields}
    await db.hub_documents.insert_one(doc)
    return doc_id


@pytest.mark.asyncio
class TestClaimFilterLogic:

    async def test_fresh_doc_with_no_status_is_claimable(self, mongo_db):
        doc_id = await _insert(mongo_db, file_name="a.pdf")
        result = await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting", worker_id="w1"
        )
        assert result.claimed is True
        assert result.document["bc_posting_status"] == "auto_posting"
        assert result.document["bc_posting_claimed_by"] == "w1"
        assert result.document["bc_posting_claimed_at"] is not None

    async def test_doc_in_failed_state_is_claimable(self, mongo_db):
        """A prior failed attempt should not block retry."""
        doc_id = await _insert(
            mongo_db, bc_posting_status="auto_post_failed",
            bc_posting_error="prior BC 500",
        )
        result = await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting", worker_id="retry"
        )
        assert result.claimed is True

    @pytest.mark.parametrize("terminal_state", TERMINAL_SUCCESS_STATES)
    async def test_terminal_success_states_block_new_claims(
        self, mongo_db, terminal_state
    ):
        doc_id = await _insert(
            mongo_db, bc_posting_status=terminal_state,
            bc_document_number="PI-42",
        )
        result = await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting", worker_id="dup-attempt"
        )
        assert result.claimed is False
        assert result.reason == ClaimRejectionReason.ALREADY_TERMINAL
        assert result.existing_status == terminal_state

    async def test_missing_doc_returns_not_found(self, mongo_db):
        result = await claim_for_bc_post(
            mongo_db, "nonexistent-id", target_state="auto_posting",
            worker_id="w1",
        )
        assert result.claimed is False
        assert result.reason == ClaimRejectionReason.NOT_FOUND

    async def test_fresh_in_flight_claim_blocks_new_claim(self, mongo_db):
        doc_id = await _insert(mongo_db, file_name="b.pdf")
        first = await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting", worker_id="w1"
        )
        assert first.claimed is True

        second = await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting", worker_id="w2"
        )
        assert second.claimed is False
        assert second.reason == ClaimRejectionReason.ACTIVE_CLAIM
        assert second.existing_holder == "w1"
        assert second.existing_status == "auto_posting"

    async def test_stale_claim_is_reclaimable_after_ttl(self, mongo_db):
        """A claim that's older than the TTL should be reclaimable — this
        is the self-healing path for crashed workers / pod evictions."""
        doc_id = await _insert(mongo_db, file_name="c.pdf")
        # Seed a stale claim directly (older than TTL).
        stale_iso = (
            datetime.now(timezone.utc) - timedelta(seconds=CLAIM_TTL_SECONDS + 60)
        ).isoformat()
        await mongo_db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "bc_posting_status": "auto_posting",
                "bc_posting_claimed_at": stale_iso,
                "bc_posting_claimed_by": "dead-worker",
            }},
        )

        result = await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting",
            worker_id="survivor",
        )
        assert result.claimed is True
        assert result.document["bc_posting_claimed_by"] == "survivor"

    async def test_in_flight_missing_claimed_at_is_reclaimable(self, mongo_db):
        """Legacy rows that were left in an in-flight state by pre-fix code
        don't have the bc_posting_claimed_at field — they must be treated
        as stale so they can be retried after deployment."""
        doc_id = await _insert(mongo_db, file_name="d.pdf")
        await mongo_db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {"bc_posting_status": "auto_posting"}},
        )  # no claimed_at field

        result = await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting", worker_id="w1"
        )
        assert result.claimed is True

    async def test_short_ttl_override_allows_fast_reclaim(self, mongo_db):
        """Tests using ttl_seconds=0 can verify stale handling without
        actually sleeping for 5 minutes."""
        doc_id = await _insert(mongo_db, file_name="e.pdf")
        first = await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting", worker_id="w1"
        )
        assert first.claimed is True

        # Default TTL — second attempt must still be blocked.
        second = await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting", worker_id="w2"
        )
        assert second.claimed is False

        # With ttl_seconds=0 every claim looks stale -> reclaimable.
        third = await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting",
            worker_id="w3", ttl_seconds=0,
        )
        assert third.claimed is True
        assert third.document["bc_posting_claimed_by"] == "w3"

    async def test_invalid_target_state_raises(self, mongo_db):
        doc_id = await _insert(mongo_db, file_name="f.pdf")
        with pytest.raises(ValueError):
            await claim_for_bc_post(
                mongo_db, doc_id, target_state="not_a_real_state",
                worker_id="w1",
            )

    async def test_extra_set_fields_are_written_atomically(self, mongo_db):
        doc_id = await _insert(mongo_db, file_name="g.pdf")
        await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting", worker_id="w1",
            extra_set={"auto_post_attempted": True, "custom_field": 42},
        )
        doc = await mongo_db.hub_documents.find_one({"id": doc_id})
        assert doc["auto_post_attempted"] is True
        assert doc["custom_field"] == 42


@pytest.mark.asyncio
class TestReleaseClaim:

    async def test_release_writes_final_state_and_clears_claim_fields(
        self, mongo_db
    ):
        doc_id = await _insert(mongo_db, file_name="h.pdf")
        await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting", worker_id="w1"
        )
        await release_claim(
            mongo_db, doc_id, final_state="posted",
            extra_set={"bc_document_number": "PI-42"},
        )
        doc = await mongo_db.hub_documents.find_one({"id": doc_id})
        assert doc["bc_posting_status"] == "posted"
        assert doc["bc_posting_claimed_at"] is None
        assert doc["bc_posting_claimed_by"] is None
        assert doc["bc_document_number"] == "PI-42"

    async def test_release_after_success_blocks_future_claims(self, mongo_db):
        """A released-to-posted document must not be re-claimable."""
        doc_id = await _insert(mongo_db, file_name="i.pdf")
        await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting", worker_id="w1"
        )
        await release_claim(mongo_db, doc_id, final_state="posted")

        result = await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting", worker_id="w2"
        )
        assert result.claimed is False
        assert result.reason == ClaimRejectionReason.ALREADY_TERMINAL

    async def test_release_to_failed_state_permits_retry(self, mongo_db):
        """After a failed BC call, the doc must be re-claimable."""
        doc_id = await _insert(mongo_db, file_name="j.pdf")
        await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting", worker_id="w1"
        )
        await release_claim(
            mongo_db, doc_id, final_state="auto_post_failed",
            extra_set={"bc_posting_error": "timeout"},
        )

        retry = await claim_for_bc_post(
            mongo_db, doc_id, target_state="auto_posting", worker_id="w2"
        )
        assert retry.claimed is True


# ---------------------------------------------------------------------------
# Real-concurrency regression — localhost MongoDB required.
# This is the test that would have caught the pre-fix defect.
# ---------------------------------------------------------------------------

MONGO_URL = os.environ.get("MONGO_URL")


async def _real_mongo_available() -> bool:
    if not MONGO_URL:
        return False
    try:
        client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=500)
        await client.admin.command("ping")
        client.close()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
class TestConcurrentClaims:
    """Fires many concurrent claim attempts at a real MongoDB instance.
    Asserts exactly one wins — this is the contract the original
    ``update_one`` pattern violated."""

    CONCURRENCY = 50

    async def _setup_real_db(self):
        if not await _real_mongo_available():
            pytest.skip(f"MONGO_URL not reachable: {MONGO_URL!r}")
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[f"test_bc_claim_concurrent_{uuid.uuid4().hex[:8]}"]
        return client, db

    async def test_exactly_one_wins_under_concurrency(self):
        client, db = await self._setup_real_db()
        try:
            doc_id = str(uuid.uuid4())
            await db.hub_documents.insert_one({
                "id": doc_id,
                "file_name": "concurrent-test.pdf",
                "review_status": "ready_for_post",
            })

            async def try_claim(i: int):
                return await claim_for_bc_post(
                    db, doc_id, target_state="auto_posting",
                    worker_id=f"racer-{i}",
                )

            results = await asyncio.gather(
                *[try_claim(i) for i in range(self.CONCURRENCY)]
            )

            winners = [r for r in results if r.claimed]
            losers = [r for r in results if not r.claimed]

            assert len(winners) == 1, (
                f"Expected exactly one winner, got {len(winners)} — "
                f"this is the race condition. Winners: "
                f"{[w.document.get('bc_posting_claimed_by') for w in winners]}"
            )
            assert len(losers) == self.CONCURRENCY - 1
            # Every loser should see ACTIVE_CLAIM (not NOT_FOUND / TERMINAL).
            loser_reasons = {loser.reason for loser in losers}
            assert loser_reasons == {ClaimRejectionReason.ACTIVE_CLAIM}, (
                f"Unexpected loser reasons: {loser_reasons}"
            )

            # DB must reflect the winner's worker id.
            doc = await db.hub_documents.find_one({"id": doc_id})
            assert doc["bc_posting_status"] == "auto_posting"
            assert doc["bc_posting_claimed_by"] == (
                winners[0].document["bc_posting_claimed_by"]
            )
        finally:
            await db.hub_documents.drop()
            client.close()

    async def test_release_permits_exactly_one_retry_winner(self):
        """After a failed attempt releases the claim to 'auto_post_failed',
        a new concurrent retry wave must again see exactly one winner."""
        client, db = await self._setup_real_db()
        try:
            doc_id = str(uuid.uuid4())
            await db.hub_documents.insert_one({
                "id": doc_id,
                "file_name": "retry-concurrent.pdf",
            })

            # Wave 1 — one claims, fails, releases.
            first = await claim_for_bc_post(
                db, doc_id, target_state="auto_posting", worker_id="w-1"
            )
            assert first.claimed is True
            await release_claim(db, doc_id, final_state="auto_post_failed",
                                extra_set={"bc_posting_error": "simulated"})

            # Wave 2 — a thundering herd retries.
            async def retry(i: int):
                return await claim_for_bc_post(
                    db, doc_id, target_state="auto_posting",
                    worker_id=f"retry-{i}",
                )

            results: List = await asyncio.gather(*[retry(i) for i in range(20)])
            winners = [r for r in results if r.claimed]
            assert len(winners) == 1
        finally:
            await db.hub_documents.drop()
            client.close()

    async def test_posted_doc_rejects_all_concurrent_attempts(self):
        """A document that's already been posted must reject every single
        concurrent attempt with ALREADY_TERMINAL — no race can cause a
        re-post that would double-invoice BC."""
        client, db = await self._setup_real_db()
        try:
            doc_id = str(uuid.uuid4())
            await db.hub_documents.insert_one({
                "id": doc_id,
                "bc_posting_status": "posted",
                "bc_document_number": "PI-EXISTING",
            })

            async def try_claim(i: int):
                return await claim_for_bc_post(
                    db, doc_id, target_state="auto_posting",
                    worker_id=f"dup-{i}",
                )

            results = await asyncio.gather(*[try_claim(i) for i in range(30)])
            assert not any(r.claimed for r in results)
            assert {r.reason for r in results} == {
                ClaimRejectionReason.ALREADY_TERMINAL
            }

            # DB state unchanged — bc_document_number still original.
            doc = await db.hub_documents.find_one({"id": doc_id})
            assert doc["bc_document_number"] == "PI-EXISTING"
            assert doc["bc_posting_status"] == "posted"
        finally:
            await db.hub_documents.drop()
            client.close()
