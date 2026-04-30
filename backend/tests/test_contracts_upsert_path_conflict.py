"""Regression test for the real-MongoDB ``WriteError: Updating the path 'id'
would create a conflict at 'id'`` bug.

Mongomock-motor (used by the rest of the orchestrator suite) tolerates
sending the same path in both ``$set`` and ``$setOnInsert``. Production
MongoDB 6.x does not, and this is what blocked Charlie's first commit
of the Bragg Navigator export. These tests record every ``update_one``
call the persistence helpers make and assert that no immutable field
(``id``, ``created_at``) ever appears in both halves of an upsert
payload — closing the gap with a unit-level guard rather than spinning
up a real Mongo container.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from models.contracts import CONTRACTS_COLLECTIONS
from services.contracts.contract_intelligence_service import (
    ContractIntelligenceService,
)
from services.contracts.navigator_normalizer import normalize_navigator_row


BRAGG = (
    Path(__file__).parent / "fixtures" / "docusign" / "bragg"
    / "bragg_metadata_export_redacted.json"
)


class _RecordingCollection:
    def __init__(self) -> None:
        self.update_calls: List[Dict[str, Any]] = []
        self.insert_calls: List[Dict[str, Any]] = []
        self.delete_calls: List[Dict[str, Any]] = []

    async def update_one(self, filt, update, upsert=False, **_kw):
        self.update_calls.append(
            {"filter": filt, "update": update, "upsert": upsert}
        )

        class _R:
            modified_count = 1
            upserted_id = None
        return _R()

    async def insert_one(self, doc, **_kw):
        self.insert_calls.append(doc)

        class _R:
            inserted_id = doc.get("id")
        return _R()

    async def delete_many(self, filt, **_kw):
        self.delete_calls.append(filt)

        class _R:
            deleted_count = 0
        return _R()

    async def find_one(self, *_a, **_kw):
        return None

    def find(self, *_a, **_kw):
        async def _gen():
            if False:  # pragma: no cover
                yield {}
        return _gen()


class _RecordingDB:
    def __init__(self) -> None:
        self._colls: Dict[str, _RecordingCollection] = {}

    def __getitem__(self, name: str) -> _RecordingCollection:
        if name not in self._colls:
            self._colls[name] = _RecordingCollection()
        return self._colls[name]


def _assert_no_path_conflict(call: Dict[str, Any], path: str) -> None:
    """Fail loudly if ``path`` appears in both ``$set`` and ``$setOnInsert``."""
    update = call["update"]
    in_set = path in (update.get("$set") or {})
    in_insert = path in (update.get("$setOnInsert") or {})
    assert not (in_set and in_insert), (
        f"path {path!r} appears in BOTH $set and $setOnInsert — MongoDB "
        f"will reject this write with code 40. filter={call['filter']}"
    )


@pytest.mark.asyncio
async def test_upsert_parties_does_not_double_write_id_or_created_at():
    db = _RecordingDB()
    svc = ContractIntelligenceService(db)
    row = json.loads(BRAGG.read_text(encoding="utf-8"))["row"]
    normalized = normalize_navigator_row(row)
    await svc._upsert_parties(normalized)
    parties_coll = db[CONTRACTS_COLLECTIONS["agreement_parties"]]
    assert parties_coll.update_calls, "no update issued for parties"
    for call in parties_coll.update_calls:
        _assert_no_path_conflict(call, "id")
        _assert_no_path_conflict(call, "created_at")
        assert call["upsert"] is True
        # ``$set`` must still carry mutable fields like updated_at.
        assert "updated_at" in (call["update"].get("$set") or {})


@pytest.mark.asyncio
async def test_upsert_terms_does_not_double_write_id():
    db = _RecordingDB()
    svc = ContractIntelligenceService(db)
    row = json.loads(BRAGG.read_text(encoding="utf-8"))["row"]
    normalized = normalize_navigator_row(row)
    await svc._upsert_terms(normalized)
    terms_coll = db[CONTRACTS_COLLECTIONS["agreement_terms"]]
    assert terms_coll.update_calls, "no update issued for terms"
    for call in terms_coll.update_calls:
        _assert_no_path_conflict(call, "id")
        _assert_no_path_conflict(call, "created_at")


@pytest.mark.asyncio
async def test_upsert_pricing_does_not_double_write_id_or_created_at():
    db = _RecordingDB()
    svc = ContractIntelligenceService(db)
    # Synthesize a pricing-bearing payload (Navigator has no pricing —
    # use a Connect SIM with a single line tab).
    payload = {
        "data": {
            "envelopeSummary": {
                "envelopeId": "env-pricing-bug-test",
                "status": "completed",
                "recipients": {
                    "signers": [{
                        "recipientId": "1", "name": "Alice", "email": "a@x.co",
                        "companyName": "Alpha", "status": "completed",
                        "tabs": {
                            "numberTabs": [
                                {"tabLabel": "line_1_quantity", "value": "5"},
                                {"tabLabel": "line_1_unit_price", "value": "12"},
                            ],
                            "textTabs": [
                                {"tabLabel": "line_1_item", "value": "WIDGET"},
                            ],
                        },
                    }],
                },
            },
        },
    }
    from services.contracts.agreement_normalizer import normalize_envelope
    normalized = normalize_envelope(payload)
    if not normalized.pricing:
        pytest.skip("normalizer did not synthesize a pricing row")
    await svc._upsert_pricing(normalized)
    pricing_coll = db[CONTRACTS_COLLECTIONS["agreement_pricing"]]
    for call in pricing_coll.update_calls:
        _assert_no_path_conflict(call, "id")
        _assert_no_path_conflict(call, "created_at")


@pytest.mark.asyncio
async def test_upsert_documents_does_not_double_write_id_or_created_at():
    db = _RecordingDB()
    svc = ContractIntelligenceService(db)
    row = json.loads(BRAGG.read_text(encoding="utf-8"))["row"]
    normalized = normalize_navigator_row(row)
    await svc._upsert_documents(normalized)
    docs_coll = db[CONTRACTS_COLLECTIONS["agreement_documents"]]
    assert docs_coll.update_calls, "no update issued for documents"
    for call in docs_coll.update_calls:
        _assert_no_path_conflict(call, "id")
        _assert_no_path_conflict(call, "created_at")
