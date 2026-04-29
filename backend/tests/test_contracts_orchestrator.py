"""Phase 2 — Contract Intelligence orchestrator tests (with mongomock_motor).

Covers:
  * record_event: new event persisted, duplicate event acked without re-write
  * process_event: end-to-end normalize → match → persist → audit
  * audit completeness: every link/exception emits an audit row
  * idempotency on replay: re-processing the same event_id is a no-op
  * manual link / confirm / reject / resolve_exception write paths emit audit

Run:
    cd /app/backend && python -m pytest tests/test_contracts_orchestrator.py -q
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient

from models.contracts import (
    CONTRACTS_COLLECTIONS,
    CONTRACTS_INDEXES,
)
from services.contracts.bc_agreement_matcher import InMemoryBCRepository
from services.contracts.contract_intelligence_service import (
    ContractIntelligenceService,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def db():
    client = AsyncMongoMockClient()
    database = client["contracts_test"]
    # Create the unique indexes that production relies on.
    for coll_name, specs in CONTRACTS_INDEXES.items():
        coll = database[CONTRACTS_COLLECTIONS[coll_name]]
        for spec in specs:
            kwargs = {k: v for k, v in spec.items() if k != "keys"}
            await coll.create_index(spec["keys"], **kwargs)
    yield database


@pytest.fixture()
def repo():
    return InMemoryBCRepository(
        customers=[{"no": "C-001", "name": "Acme Co", "email": "alice@acme.com"}],
        items=[{"no": "ITM-100", "name": "WIDGET-100"}],
    )


@pytest.fixture()
def sim_payload():
    return {
        "event": "envelope-completed",
        "eventId": "evt-abc-1",
        "data": {
            "envelopeId": "env-1234",
            "envelopeSummary": {
                "envelopeId": "env-1234",
                "status": "completed",
                "subject": "MSA — Acme",
                "completedDateTime": "2026-04-29T18:55:30Z",
                "sender": {
                    "userName": "Sue Sender",
                    "email": "sue@gpi.com",
                },
                "recipients": {
                    "signers": [{
                        "recipientId": "1",
                        "name": "Alice Buyer",
                        "email": "alice@acme.com",
                        "companyName": "Acme Co",
                        "status": "completed",
                    }],
                },
                "envelopeDocuments": [
                    {"documentId": "1", "name": "MSA.pdf"},
                ],
                "customFields": {
                    "textCustomFields": [
                        {"name": "effective_date", "value": "2026-05-01"},
                    ],
                },
                "formData": [
                    {"name": "line_1_item", "value": "WIDGET-100"},
                    {"name": "line_1_qty", "value": "100"},
                    {"name": "line_1_price", "value": "2.50"},
                ],
            },
        },
    }


# ---------------------------------------------------------------------------
# Event recording (idempotency)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRecordEvent:
    async def test_new_event_inserted(self, db):
        svc = ContractIntelligenceService(db)
        out = await svc.record_event(
            provider_event_id="evt-1",
            provider_envelope_id="env-1",
            event_type="envelope-sent",
            raw_payload={"foo": "bar"},
            hmac_valid=True,
        )
        assert out["duplicate"] is False
        assert out["event_id"]
        # Stored
        doc = await db[CONTRACTS_COLLECTIONS["agreement_events"]].find_one(
            {"provider_event_id": "evt-1"}, {"_id": 0},
        )
        assert doc is not None
        assert doc["processed"] is False
        assert doc["hmac_valid"] is True

    async def test_duplicate_event_acks_without_double_write(self, db):
        svc = ContractIntelligenceService(db)
        first = await svc.record_event(
            provider_event_id="evt-dup",
            provider_envelope_id="env-1",
            event_type="envelope-sent",
            raw_payload={"v": 1},
            hmac_valid=True,
        )
        second = await svc.record_event(
            provider_event_id="evt-dup",
            provider_envelope_id="env-1",
            event_type="envelope-sent",
            raw_payload={"v": 2},  # different payload should NOT overwrite
            hmac_valid=True,
        )
        assert first["duplicate"] is False
        assert second["duplicate"] is True
        assert second["event_id"] == first["event_id"]
        # Storage still has the ORIGINAL payload (proves no overwrite)
        doc = await db[CONTRACTS_COLLECTIONS["agreement_events"]].find_one(
            {"provider_event_id": "evt-dup"}, {"_id": 0},
        )
        assert doc["raw_payload"] == {"v": 1}


# ---------------------------------------------------------------------------
# End-to-end processing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestProcessEvent:
    async def test_full_pipeline(self, db, repo, sim_payload):
        svc = ContractIntelligenceService(db, repo=repo)
        rec = await svc.record_event(
            provider_event_id="evt-1",
            provider_envelope_id="env-1234",
            event_type="envelope-completed",
            raw_payload=sim_payload,
            hmac_valid=True,
        )
        outcome = await svc.process_event(rec["event_id"])
        assert outcome["status"] == "ok"
        agreement_id = outcome["agreement_id"]

        # Agreement persisted
        agr = await db[CONTRACTS_COLLECTIONS["agreements"]].find_one(
            {"id": agreement_id}, {"_id": 0},
        )
        assert agr is not None
        assert agr["provider_envelope_id"] == "env-1234"
        assert agr["status"] == "completed"

        # Parties (signer + sender)
        parties = await db[CONTRACTS_COLLECTIONS["agreement_parties"]].find(
            {"agreement_id": agreement_id}, {"_id": 0},
        ).to_list(length=None)
        roles = sorted(p["role"] for p in parties)
        assert "signer" in roles and "sender" in roles

        # Terms
        terms = await db[CONTRACTS_COLLECTIONS["agreement_terms"]].find(
            {"agreement_id": agreement_id}, {"_id": 0},
        ).to_list(length=None)
        assert any(t["term_key"] == "effective_date" for t in terms)

        # Pricing
        pricing = await db[CONTRACTS_COLLECTIONS["agreement_pricing"]].find(
            {"agreement_id": agreement_id}, {"_id": 0},
        ).to_list(length=None)
        assert len(pricing) == 1 and pricing[0]["item_label"] == "WIDGET-100"

        # Documents
        docs = await db[CONTRACTS_COLLECTIONS["agreement_documents"]].find(
            {"agreement_id": agreement_id}, {"_id": 0},
        ).to_list(length=None)
        assert len(docs) == 1

        # Links — at least one customer link + one item link
        links = await db[CONTRACTS_COLLECTIONS["agreement_bc_links"]].find(
            {"agreement_id": agreement_id}, {"_id": 0},
        ).to_list(length=None)
        link_types = {link["link_type"] for link in links}
        assert "customer" in link_types
        assert "item" in link_types

        # Audit rows: one per agreement, links and exceptions
        audits = await db[CONTRACTS_COLLECTIONS["agreement_match_audit"]].find(
            {"agreement_id": agreement_id}, {"_id": 0},
        ).to_list(length=None)
        assert any(a["action"] == "agreement_normalized" for a in audits)
        # Every link should have a corresponding audit row referencing it
        for link in links:
            assert any(a.get("link_id") == link["id"] for a in audits), \
                f"missing audit for link {link['id']}"

    async def test_replay_same_event_is_noop(self, db, repo, sim_payload):
        svc = ContractIntelligenceService(db, repo=repo)
        rec = await svc.record_event(
            provider_event_id="evt-replay",
            provider_envelope_id="env-1234",
            event_type="envelope-completed",
            raw_payload=sim_payload,
            hmac_valid=True,
        )
        first = await svc.process_event(rec["event_id"])
        second = await svc.process_event(rec["event_id"])
        assert first["status"] == "ok"
        assert second["status"] == "already_processed"

        # No duplicate audit rows on replay
        audits = await db[CONTRACTS_COLLECTIONS["agreement_match_audit"]].find(
            {"agreement_id": first["agreement_id"], "action": "agreement_normalized"},
        ).to_list(length=None)
        assert len(audits) == 1

    async def test_normalizer_failure_marks_event_with_error(self, db, repo):
        svc = ContractIntelligenceService(db, repo=repo)
        rec = await svc.record_event(
            provider_event_id="evt-bad",
            provider_envelope_id=None,
            event_type="envelope-completed",
            raw_payload={"event": "x"},  # missing envelope id
            hmac_valid=True,
        )
        out = await svc.process_event(rec["event_id"])
        assert out["status"] == "normalizer_failed"
        evt = await db[CONTRACTS_COLLECTIONS["agreement_events"]].find_one(
            {"id": rec["event_id"]}, {"_id": 0},
        )
        assert evt["processed"] is True
        assert "normalizer_failed" in (evt.get("error") or "")


# ---------------------------------------------------------------------------
# Manual mapping write paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestManualPaths:
    async def test_manual_link_writes_audit(self, db):
        svc = ContractIntelligenceService(db)
        # Seed an agreement
        await db[CONTRACTS_COLLECTIONS["agreements"]].insert_one({
            "id": "agr-1", "provider_envelope_id": "env-X",
            "provider": "docusign", "status": "sent",
        })
        link = await svc.manual_link(
            agreement_id="agr-1",
            link_type="customer",
            bc_entity="customers",
            bc_no="C-999",
            bc_name_snapshot="Manual Co",
            actor="alice@gpi.com",
            notes="confirmed in person",
        )
        assert link.status == "confirmed"
        assert link.match_method == "manual"
        audits = await db[CONTRACTS_COLLECTIONS["agreement_match_audit"]].find(
            {"agreement_id": "agr-1"},
        ).to_list(length=None)
        assert any(a["link_id"] == link.id and a["action"] == "confirmed_link"
                   for a in audits)

    async def test_confirm_proposed_link(self, db):
        svc = ContractIntelligenceService(db)
        await db[CONTRACTS_COLLECTIONS["agreement_bc_links"]].insert_one({
            "id": "link-p", "agreement_id": "agr-1", "link_type": "customer",
            "bc_entity": "customers", "bc_no": "C-1", "match_method": "fuzzy",
            "confidence": 0.85, "status": "proposed", "linked_by": "system",
        })
        out = await svc.confirm_link(
            agreement_id="agr-1", link_id="link-p", actor="bob@gpi.com",
        )
        assert out["status"] == "confirmed"
        assert out["confirmed_by"] == "bob@gpi.com"

    async def test_reject_proposed_link(self, db):
        svc = ContractIntelligenceService(db)
        await db[CONTRACTS_COLLECTIONS["agreement_bc_links"]].insert_one({
            "id": "link-r", "agreement_id": "agr-1", "link_type": "vendor",
            "bc_entity": "vendors", "bc_no": "V-1", "match_method": "fuzzy",
            "confidence": 0.82, "status": "proposed", "linked_by": "system",
        })
        out = await svc.reject_link(
            agreement_id="agr-1", link_id="link-r", actor="bob@gpi.com",
            notes="wrong vendor",
        )
        assert out["status"] == "rejected"
        assert out["notes"] == "wrong vendor"

    async def test_resolve_exception(self, db):
        svc = ContractIntelligenceService(db)
        await db[CONTRACTS_COLLECTIONS["agreement_exceptions"]].insert_one({
            "id": "ex-1", "agreement_id": "agr-1", "code": "party_unmatched",
            "severity": "medium", "details": {}, "status": "open",
        })
        out = await svc.resolve_exception(
            exception_id="ex-1", actor="alice@gpi.com", note="created in BC",
        )
        assert out["status"] == "resolved"
        assert out["resolution_note"] == "created in BC"
        audits = await db[CONTRACTS_COLLECTIONS["agreement_match_audit"]].find(
            {"exception_id": "ex-1"},
        ).to_list(length=None)
        assert any(a["action"] == "exception_resolved" for a in audits)

    async def test_replay_does_not_clobber_manual_link(self, db, repo, sim_payload):
        """A user-confirmed manual link must survive a webhook replay."""
        svc = ContractIntelligenceService(db, repo=repo)
        rec = await svc.record_event(
            provider_event_id="evt-1",
            provider_envelope_id="env-1234",
            event_type="envelope-completed",
            raw_payload=sim_payload,
            hmac_valid=True,
        )
        out1 = await svc.process_event(rec["event_id"])
        agreement_id = out1["agreement_id"]

        # User adds a manual link
        manual = await svc.manual_link(
            agreement_id=agreement_id,
            link_type="customer", bc_entity="customers", bc_no="C-MANUAL",
            bc_name_snapshot="Manual Customer", actor="alice@gpi.com",
        )

        # New event for the same envelope (status change)
        rec2 = await svc.record_event(
            provider_event_id="evt-2",
            provider_envelope_id="env-1234",
            event_type="envelope-completed",
            raw_payload=sim_payload,
            hmac_valid=True,
        )
        await svc.process_event(rec2["event_id"])

        # Manual link still present
        survived = await db[CONTRACTS_COLLECTIONS["agreement_bc_links"]].find_one(
            {"id": manual.id}, {"_id": 0},
        )
        assert survived is not None
        assert survived["status"] == "confirmed"
        assert survived["bc_no"] == "C-MANUAL"
