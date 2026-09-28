"""Regression coverage for routes/bc_document_events.py.

This module had zero test coverage before this file: four helper functions
(_document_id, _infer_doc_type, _document_event_key, _event_id) were called
throughout the file but never defined anywhere, so every write endpoint
(delivery-sent, delivery-failed, attachment-linked, attachment-sync-failed)
crashed with a NameError on every single call. Nothing caught it because
py_compile only checks syntax, not undefined names used inside function
bodies, and no test ever actually invoked these functions.
"""

from copy import deepcopy

import pytest
from fastapi import HTTPException

from routes import bc_document_events


def _get_dotted(document, dotted_key):
    value = document
    for part in dotted_key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _matches(document, query):
    for key, condition in query.items():
        if key == "$nin":
            continue
        actual = _get_dotted(document, key)
        if isinstance(condition, dict) and "$nin" in condition:
            if actual in condition["$nin"]:
                return False
        elif actual != condition:
            return False
    return True


class FakeCursor:
    def __init__(self, documents):
        self._documents = documents

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, _n):
        return self

    async def to_list(self, _n):
        return [deepcopy(d) for d in self._documents]


class FakeCollection:
    def __init__(self):
        self.documents = []

    async def find_one(self, query, projection=None):
        for document in self.documents:
            if _matches(document, query):
                result = deepcopy(document)
                if projection and projection.get("_id") == 0:
                    result.pop("_id", None)
                return result
        return None

    def find(self, query, projection=None):
        matched = [d for d in self.documents if _matches(document=d, query=query)]
        results = []
        for document in matched:
            result = deepcopy(document)
            if projection and projection.get("_id") == 0:
                result.pop("_id", None)
            results.append(result)
        return FakeCursor(results)

    async def insert_one(self, document):
        stored = deepcopy(document)
        stored.setdefault("_id", f"fake-{len(self.documents)}")
        self.documents.append(stored)
        return stored

    async def count_documents(self, query):
        return sum(1 for d in self.documents if _matches(d, query))

    async def distinct(self, field, query=None):
        query = query or {}
        values = set()
        for d in self.documents:
            if _matches(d, query):
                v = _get_dotted(d, field)
                if v is not None:
                    values.add(v)
        return list(values)

    async def update_one(self, query, update, upsert=False):
        for document in self.documents:
            if _matches(document, query):
                self._apply_update(document, update)
                return document
        if upsert:
            new_doc = {}
            for key, value in query.items():
                if not key.startswith("$"):
                    new_doc[key] = value
            if "$setOnInsert" in update:
                new_doc.update(deepcopy(update["$setOnInsert"]))
            self._apply_update(new_doc, {k: v for k, v in update.items() if k != "$setOnInsert"})
            self.documents.append(new_doc)
            return new_doc
        return None

    @staticmethod
    def _apply_update(document, update):
        for key, value in update.get("$set", {}).items():
            document[key] = value
        for key, value in update.get("$push", {}).items():
            document.setdefault(key, []).append(value)
        for key, value in update.get("$addToSet", {}).items():
            existing = document.setdefault(key, [])
            if value not in existing:
                existing.append(value)


class FakeDatabase:
    def __init__(self):
        self.bc_document_events = FakeCollection()
        self.hub_documents = FakeCollection()


@pytest.fixture
def fake_database():
    database = FakeDatabase()
    bc_document_events.set_db(database)
    return database


def delivery_payload(idempotency_key="idem-1", record_no="114679", event_id=None):
    return {
        "event_id": event_id,
        "idempotency_key": idempotency_key,
        "bc_record": {
            "company_id": "gpi-co",
            "record_type": "Sales Invoice",
            "record_no": record_no,
        },
        "document_no": record_no,
        "delivery_status": "sent",
        "recipients": {"to": ["customer@example.com"], "cc": [], "bcc": []},
    }


@pytest.mark.asyncio
async def test_delivery_sent_creates_document_and_event(fake_database):
    payload = bc_document_events.DeliveryEventPayload(**delivery_payload())

    result = await bc_document_events._record_delivery_event(
        bc_document_events.EventType.DELIVERY_SENT.value, payload
    )

    assert result["success"] is True
    assert result["duplicate"] is False
    assert result["document_id"]
    assert result["event_id"]

    doc = await fake_database.hub_documents.find_one({"id": result["document_id"]})
    assert doc["status"] == "sent"
    assert doc["source"] == "bc_document_event"
    assert doc["delivery"]["to"] == ["customer@example.com"]

    event = await fake_database.bc_document_events.find_one({"event_id": result["event_id"]})
    assert event["event_type"] == "delivery_sent"


@pytest.mark.asyncio
async def test_repeat_event_with_same_idempotency_key_is_duplicate(fake_database):
    payload = bc_document_events.DeliveryEventPayload(**delivery_payload(idempotency_key="idem-repeat"))

    first = await bc_document_events._record_delivery_event(
        bc_document_events.EventType.DELIVERY_SENT.value, payload
    )
    second = await bc_document_events._record_delivery_event(
        bc_document_events.EventType.DELIVERY_SENT.value, payload
    )

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["event_id"] == first["event_id"]
    assert second["document_id"] == first["document_id"]
    assert len(fake_database.hub_documents.documents) == 1
    assert len(fake_database.bc_document_events.documents) == 1


@pytest.mark.asyncio
async def test_different_event_types_for_same_bc_document_share_one_hub_document(fake_database):
    sent_payload = bc_document_events.DeliveryEventPayload(
        **delivery_payload(idempotency_key="idem-a", record_no="SAME-DOC")
    )
    attach_payload = bc_document_events.AttachmentEventPayload(
        idempotency_key="idem-b",
        bc_record={"company_id": "gpi-co", "record_type": "Sales Invoice", "record_no": "SAME-DOC"},
        document_no="SAME-DOC",
    )

    sent_result = await bc_document_events._record_delivery_event(
        bc_document_events.EventType.DELIVERY_SENT.value, sent_payload
    )
    attach_result = await bc_document_events._record_attachment_event(
        bc_document_events.EventType.ATTACHMENT_LINKED.value, attach_payload
    )

    assert sent_result["document_id"] == attach_result["document_id"]
    assert len(fake_database.hub_documents.documents) == 1

    doc = fake_database.hub_documents.documents[0]
    assert set(doc["bc_event_types"]) == {"delivery_sent", "attachment_linked"}


@pytest.mark.asyncio
async def test_repair_orphan_event_recreates_missing_hub_document(fake_database):
    payload = bc_document_events.DeliveryEventPayload(**delivery_payload(idempotency_key="idem-orphan"))
    result = await bc_document_events._record_delivery_event(
        bc_document_events.EventType.DELIVERY_SENT.value, payload
    )

    # Simulate an orphan: the event row exists but its hub_documents row was lost.
    fake_database.hub_documents.documents.clear()
    assert await fake_database.hub_documents.find_one({"id": result["document_id"]}) is None

    repair_result = await bc_document_events.repair_orphan_events()

    assert repair_result["repaired_documents"] == 1
    restored = await fake_database.hub_documents.find_one({"id": result["document_id"]})
    assert restored is not None
    assert restored["status"] == "sent"


@pytest.mark.asyncio
async def test_status_endpoint_reports_counts_and_no_bc_writes(fake_database):
    payload = bc_document_events.DeliveryEventPayload(**delivery_payload(idempotency_key="idem-status"))
    await bc_document_events._record_delivery_event(bc_document_events.EventType.DELIVERY_SENT.value, payload)

    status = await bc_document_events.get_bc_document_events_status()

    assert status["events_recorded"] == 1
    assert status["bc_event_documents"] == 1
    assert status["orphan_events"] == 0
    assert status["writes_to_bc"] is False
    assert status["mailbox_polling"] is False


@pytest.mark.asyncio
async def test_api_key_dependency_rejects_missing_and_wrong_key(monkeypatch):
    monkeypatch.setattr(bc_document_events, "BC_DOCUMENT_EVENTS_REQUIRE_API_KEY", True)
    monkeypatch.setattr(bc_document_events, "BC_DOCUMENT_EVENTS_API_KEY", "correct-key")

    with pytest.raises(HTTPException) as missing:
        await bc_document_events.require_bc_document_events_api_key(x_gpi_hub_api_key=None)
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as wrong:
        await bc_document_events.require_bc_document_events_api_key(x_gpi_hub_api_key="nope")
    assert wrong.value.status_code == 401

    # Correct key should not raise.
    await bc_document_events.require_bc_document_events_api_key(x_gpi_hub_api_key="correct-key")


@pytest.mark.asyncio
async def test_explicit_event_id_is_honored_over_idempotency_key(fake_database):
    payload = bc_document_events.DeliveryEventPayload(
        **delivery_payload(idempotency_key="ignored", event_id="explicit-event-id")
    )

    result = await bc_document_events._record_delivery_event(
        bc_document_events.EventType.DELIVERY_SENT.value, payload
    )

    assert result["event_id"] == "explicit-event-id"


@pytest.mark.asyncio
async def test_explicit_hub_document_id_is_honored(fake_database):
    payload = bc_document_events.DeliveryEventPayload(
        **delivery_payload(idempotency_key="idem-explicit-doc")
    )
    payload.hub_document_id = "already-existing-doc-id"

    result = await bc_document_events._record_delivery_event(
        bc_document_events.EventType.DELIVERY_SENT.value, payload
    )

    assert result["document_id"] == "already-existing-doc-id"
