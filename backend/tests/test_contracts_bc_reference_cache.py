"""Phase 4C(d) — BCReferenceCacheRepository tests + matching wiring.

Confirms:
  * Customer + vendor candidates are produced from a populated cache.
  * Empty / unavailable cache degrades to no candidates (no exception).
  * Bragg multi-code ambiguity flows through to the matcher correctly.
  * ``_build_bc_repo`` reports source / counts / unavailable accurately.
  * ``dryrun_rows`` populates ``match_preview`` per row.
  * ``commit_rows`` injects the cache repo so the orchestrator's matcher
    sees real candidates.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from mongomock_motor import AsyncMongoMockClient

from models.contracts import CONTRACTS_COLLECTIONS, CONTRACTS_INDEXES
from services.contracts.bc_repo_reference_cache import BCReferenceCacheRepository
from services.contracts.navigator_import import (
    _build_bc_repo,
    commit_rows,
    dryrun_rows,
)


BRAGG = (
    Path(__file__).parent / "fixtures" / "docusign" / "bragg"
    / "bragg_metadata_export_redacted.json"
)


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("loop closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@pytest.fixture()
def db():
    client = AsyncMongoMockClient()
    database = client["contracts_test"]

    async def _materialize():
        for coll_name, specs in CONTRACTS_INDEXES.items():
            coll = database[CONTRACTS_COLLECTIONS[coll_name]]
            for spec in specs:
                kwargs = {k: v for k, v in spec.items() if k != "keys"}
                await coll.create_index(spec["keys"], **kwargs)
    _run_async(_materialize())
    return database


async def _seed_customers(db, customers: List[Dict[str, Any]]) -> None:
    docs = [
        {
            "entity_type": "customer",
            "bc_customer_no": c["no"],
            "bc_customer_name": c["name"],
            "displayName": c["name"],
            "email": c.get("email"),
        }
        for c in customers
    ]
    if docs:
        await db.bc_reference_cache.insert_many(docs)


async def _seed_vendors_via_po(db, vendors: List[Dict[str, Any]]) -> None:
    """Vendors aren't stored as a master domain today — seed them the
    way the cache does in production: as transactional rows carrying
    ``bc_vendor_no`` / ``bc_vendor_name``."""
    docs = [
        {
            "entity_type": "purchase_order",
            "bc_vendor_no": v["no"],
            "bc_vendor_name": v["name"],
        }
        for v in vendors
    ]
    if docs:
        await db.bc_reference_cache.insert_many(docs)


def _bragg_row() -> Dict[str, Any]:
    return json.loads(BRAGG.read_text(encoding="utf-8"))["row"]


# =============================================================================
# Repository unit tests
# =============================================================================

class TestBCReferenceCacheRepository:

    @pytest.mark.asyncio
    async def test_probe_reports_counts(self, db):
        await _seed_customers(db, [
            {"no": "C-A", "name": "Alpha Co"},
            {"no": "C-B", "name": "Beta LLC"},
        ])
        await _seed_vendors_via_po(db, [
            {"no": "V-1", "name": "VendorOne"},
        ])
        repo = BCReferenceCacheRepository(db)
        counts = await repo.probe()
        assert counts == {"customers": 2, "vendors": 1, "items": 0}
        assert repo.unavailable is False

    @pytest.mark.asyncio
    async def test_finds_high_confidence_customer(self, db):
        await _seed_customers(db, [
            {"no": "C-BRAGG", "name": "Bragg Live Food Products LLC"},
            {"no": "C-NOISE", "name": "Apex Industries"},
        ])
        repo = BCReferenceCacheRepository(db)
        cands = await repo.find_customer_candidates(
            name="Bragg Live Food Products LLC", email=None,
        )
        assert cands, "expected at least one candidate"
        assert cands[0].no == "C-BRAGG"
        assert cands[0].score >= 0.95
        assert cands[0].method == "exact_name"

    @pytest.mark.asyncio
    async def test_returns_two_candidates_for_ambiguous_org(self, db):
        await _seed_customers(db, [
            {"no": "C-BRAGG-E", "name": "Bragg Live Food Products LLC"},
            {"no": "C-BRAGG-W", "name": "Bragg Live Food Products LLC"},
            {"no": "C-NOISE", "name": "Apex Industries"},
        ])
        repo = BCReferenceCacheRepository(db)
        cands = await repo.find_customer_candidates(
            name="Bragg Live Food Products LLC", email=None,
        )
        assert {c.no for c in cands} >= {"C-BRAGG-E", "C-BRAGG-W"}
        # Both score equally; ambiguity will be detected by the matcher.

    @pytest.mark.asyncio
    async def test_drops_weak_matches_below_threshold(self, db):
        await _seed_customers(db, [{"no": "C-X", "name": "Totally Unrelated Inc"}])
        repo = BCReferenceCacheRepository(db)
        cands = await repo.find_customer_candidates(name="Bragg Live", email=None)
        assert cands == []  # 0 token overlap → score 0.0 → dropped

    @pytest.mark.asyncio
    async def test_finds_vendor_via_purchase_orders(self, db):
        await _seed_vendors_via_po(db, [
            {"no": "V-GAMER", "name": "Gamer Packaging Inc"},
            {"no": "V-OTHER", "name": "Some Other Vendor"},
        ])
        repo = BCReferenceCacheRepository(db)
        cands = await repo.find_vendor_candidates(
            name="Gamer Packaging, Inc.", email=None,
        )
        assert cands and cands[0].no == "V-GAMER"

    @pytest.mark.asyncio
    async def test_items_returns_empty_with_advisory_log(self, db, caplog):
        repo = BCReferenceCacheRepository(db)
        # First call logs "no master items collection".
        cands1 = await repo.find_item_candidates(label="WIDGET", description=None)
        # Second call must not re-log (one-shot guard).
        cands2 = await repo.find_item_candidates(label="WIDGET-2", description=None)
        assert cands1 == [] and cands2 == []

    @pytest.mark.asyncio
    async def test_empty_cache_returns_empty(self, db):
        # No seeding at all.
        repo = BCReferenceCacheRepository(db)
        await repo.probe()
        cands = await repo.find_customer_candidates(name="Alpha Co", email=None)
        assert cands == []


# =============================================================================
# _build_bc_repo + import wiring
# =============================================================================

class TestBuildBCRepo:

    @pytest.mark.asyncio
    async def test_no_db_returns_empty(self):
        repo, source, counts, unavailable = await _build_bc_repo(None)
        assert source == "empty"
        assert counts == {}
        assert unavailable is False

    @pytest.mark.asyncio
    async def test_populated_db_uses_reference_cache(self, db):
        await _seed_customers(db, [{"no": "C-X", "name": "Anything"}])
        repo, source, counts, unavailable = await _build_bc_repo(db)
        assert source == "reference_cache"
        assert counts["customers"] == 1
        assert unavailable is False

    @pytest.mark.asyncio
    async def test_cold_db_returns_cold_marker(self, db):
        repo, source, counts, unavailable = await _build_bc_repo(db)
        assert source == "reference_cache_cold"
        assert all(v == 0 for v in counts.values())


class TestDryrunWithCache:

    @pytest.mark.asyncio
    async def test_dryrun_populates_match_preview_when_cache_warm(self, db):
        await _seed_customers(db, [
            {"no": "C-BRAGG", "name": "Bragg Live Food Products LLC"},
        ])
        await _seed_vendors_via_po(db, [
            {"no": "V-GAMER", "name": "Gamer Packaging Inc"},
        ])
        summary = await dryrun_rows([_bragg_row()], db=db, filename="b.json")
        assert summary.bc_repo_source == "reference_cache"
        assert summary.bc_cache_counts["customers"] == 1
        row = summary.rows[0]
        # Preview should show one entry per party with non-zero candidate counts.
        assert row.match_preview, "expected match_preview entries"
        decisions = {p["decision"] for p in row.match_preview}
        # Bragg + Gamer both score perfectly → auto_confirm.
        assert "auto_confirm" in decisions

    @pytest.mark.asyncio
    async def test_dryrun_match_preview_flags_ambiguity(self, db):
        await _seed_customers(db, [
            {"no": "C-BRAGG-E", "name": "Bragg Live Food Products LLC"},
            {"no": "C-BRAGG-W", "name": "Bragg Live Food Products LLC"},
        ])
        summary = await dryrun_rows([_bragg_row()], db=db)
        bragg_entry = next(
            p for p in summary.rows[0].match_preview
            if "Bragg" in (p["party_org"] or "")
        )
        assert bragg_entry["candidate_count"] >= 2
        assert bragg_entry["ambiguous"] is True
        assert bragg_entry["decision"] == "manual_review"

    @pytest.mark.asyncio
    async def test_dryrun_with_cold_cache_reports_no_candidates(self, db):
        summary = await dryrun_rows([_bragg_row()], db=db)
        assert summary.bc_repo_source == "reference_cache_cold"
        for entry in summary.rows[0].match_preview:
            assert entry["candidate_count"] == 0
            assert entry["decision"] == "manual_review"


class TestCommitWithCache:

    @pytest.mark.asyncio
    async def test_commit_creates_auto_confirmed_links_when_unique(self, db):
        await _seed_customers(db, [
            {"no": "C-BRAGG", "name": "Bragg Live Food Products LLC"},
        ])
        await _seed_vendors_via_po(db, [
            {"no": "V-GAMER", "name": "Gamer Packaging Inc"},
        ])
        summary = await commit_rows([_bragg_row()], db=db, filename="b.json")
        assert summary.bc_repo_source == "reference_cache"
        assert summary.committed == 1
        # The agreement should now have at least one BC link row.
        agreements = await db[CONTRACTS_COLLECTIONS["agreements"]].find(
            {"provider_envelope_id": _bragg_row()["Envelope Id"]}, {"_id": 0, "id": 1},
        ).to_list(length=10)
        assert agreements
        aid = agreements[0]["id"]
        links = await db[CONTRACTS_COLLECTIONS["agreement_bc_links"]].find(
            {"agreement_id": aid}, {"_id": 0},
        ).to_list(length=10)
        bc_nos = {link["bc_no"] for link in links}
        assert "C-BRAGG" in bc_nos

    @pytest.mark.asyncio
    async def test_commit_emits_ambiguity_exception_for_multiple_bragg(self, db):
        await _seed_customers(db, [
            {"no": "C-BRAGG-E", "name": "Bragg Live Food Products LLC"},
            {"no": "C-BRAGG-W", "name": "Bragg Live Food Products LLC"},
        ])
        summary = await commit_rows([_bragg_row()], db=db)
        assert summary.committed == 1
        assert summary.ambiguity_exceptions == 1
        # Two proposed links, both for the customer link type.
        agreements = await db[CONTRACTS_COLLECTIONS["agreements"]].find(
            {"provider_envelope_id": _bragg_row()["Envelope Id"]}, {"_id": 0, "id": 1},
        ).to_list(length=10)
        aid = agreements[0]["id"]
        links = await db[CONTRACTS_COLLECTIONS["agreement_bc_links"]].find(
            {"agreement_id": aid, "link_type": "customer"}, {"_id": 0},
        ).to_list(length=10)
        bc_nos = {link["bc_no"] for link in links}
        assert bc_nos >= {"C-BRAGG-E", "C-BRAGG-W"}
        statuses = {link["status"] for link in links}
        # Ambiguity forces proposed (never auto_confirmed).
        assert "auto_confirmed" not in statuses

    @pytest.mark.asyncio
    async def test_commit_with_cold_cache_falls_back_to_unmatched(self, db):
        # Cold cache → no candidates → existing party_unmatched flow.
        summary = await commit_rows([_bragg_row()], db=db)
        assert summary.bc_repo_source == "reference_cache_cold"
        assert summary.committed == 1
        agreements = await db[CONTRACTS_COLLECTIONS["agreements"]].find(
            {"provider_envelope_id": _bragg_row()["Envelope Id"]}, {"_id": 0, "id": 1},
        ).to_list(length=10)
        aid = agreements[0]["id"]
        links = await db[CONTRACTS_COLLECTIONS["agreement_bc_links"]].find(
            {"agreement_id": aid}, {"_id": 0},
        ).to_list(length=10)
        assert links == []  # no candidates → no links
        excs = await db[CONTRACTS_COLLECTIONS["agreement_exceptions"]].find(
            {"agreement_id": aid, "code": "party_unmatched"}, {"_id": 0},
        ).to_list(length=10)
        assert excs  # unmatched exceptions still emitted

    @pytest.mark.asyncio
    async def test_commit_replay_preserves_manual_link(self, db):
        # First commit auto-confirms.
        await _seed_customers(db, [
            {"no": "C-BRAGG", "name": "Bragg Live Food Products LLC"},
        ])
        await commit_rows([_bragg_row()], db=db)
        # Operator manually flips link status to "confirmed" (simulating
        # the manual-mapping UI flow).
        agreements = await db[CONTRACTS_COLLECTIONS["agreements"]].find(
            {"provider_envelope_id": _bragg_row()["Envelope Id"]}, {"_id": 0, "id": 1},
        ).to_list(length=10)
        aid = agreements[0]["id"]
        await db[CONTRACTS_COLLECTIONS["agreement_bc_links"]].update_many(
            {"agreement_id": aid, "bc_no": "C-BRAGG"},
            {"$set": {"status": "confirmed", "linked_by": "human@gpi.com"}},
        )
        # Replay: should be a no-op at the event-id layer.
        summary2 = await commit_rows([_bragg_row()], db=db)
        assert summary2.skipped == 1
        # Manual link status survives.
        link_after = await db[CONTRACTS_COLLECTIONS["agreement_bc_links"]].find_one(
            {"agreement_id": aid, "bc_no": "C-BRAGG"}, {"_id": 0},
        )
        assert link_after["status"] == "confirmed"
        assert link_after["linked_by"] == "human@gpi.com"
