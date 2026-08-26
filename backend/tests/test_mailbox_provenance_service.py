import pytest

from services.mailbox_provenance_service import persist_mailbox_provenance


class FakeCollection:
    def __init__(self, doc):
        self.doc = doc
        self.updates = []

    async def find_one(self, query, projection=None):
        if self.doc and self.doc.get("id") == query.get("id"):
            if not projection:
                return dict(self.doc)
            return {
                k: self.doc.get(k)
                for k, include in projection.items()
                if include and k != "_id"
            }
        return None

    async def update_one(self, query, update):
        self.updates.append((query, update))
        for key, value in update.get("$set", {}).items():
            self.doc[key] = value
        for key, value in update.get("$push", {}).items():
            self.doc.setdefault(key, []).append(value)


class FakeDB:
    def __init__(self, doc):
        self.hub_documents = FakeCollection(doc)


@pytest.mark.asyncio
async def test_first_observation_sets_canonical_provenance():
    db = FakeDB({"id": "doc-1"})

    result = await persist_mailbox_provenance(
        db,
        "doc-1",
        mailbox_address="hub-ap-intake@gamerpackaging.com",
        mailbox_id="mbx-ap",
        mailbox_category="AP",
        graph_message_id="graph-1",
        internet_message_id="<internet-1@example.com>",
        attachment_id="att-1",
        source="email_poll",
    )

    doc = db.hub_documents.doc
    assert result["updated"] is True
    assert doc["source_mailbox_address"] == "hub-ap-intake@gamerpackaging.com"
    assert doc["source_mailbox_id"] == "mbx-ap"
    assert doc["source_mailbox_category"] == "AP"
    assert doc["source_graph_message_id"] == "graph-1"
    assert doc["source_internet_message_id"] == "<internet-1@example.com>"
    assert doc["source_attachment_id"] == "att-1"
    assert len(doc["provenance_observations"]) == 1


@pytest.mark.asyncio
async def test_later_observation_does_not_overwrite_original_source():
    db = FakeDB({
        "id": "doc-1",
        "source_mailbox_address": "hub-ap-intake@gamerpackaging.com",
        "source_mailbox_id": "mbx-ap",
        "source_mailbox_category": "AP",
        "source_graph_message_id": "graph-original",
        "source_internet_message_id": "<original@example.com>",
        "source_attachment_id": "att-original",
        "source_provenance_captured_utc": "2026-08-25T00:00:00+00:00",
    })

    await persist_mailbox_provenance(
        db,
        "doc-1",
        mailbox_address="warehouse@gamerpackaging.com",
        mailbox_id="mbx-warehouse",
        mailbox_category="Operations",
        graph_message_id="graph-forward",
        internet_message_id="<forward@example.com>",
        attachment_id="att-forward",
        source="email",
    )

    doc = db.hub_documents.doc
    assert doc["source_mailbox_address"] == "hub-ap-intake@gamerpackaging.com"
    assert doc["source_mailbox_id"] == "mbx-ap"
    assert doc["source_graph_message_id"] == "graph-original"
    assert doc["provenance_observations"][-1]["mailbox_address"] == "warehouse@gamerpackaging.com"
    assert doc["provenance_observations"][-1]["internet_message_id"] == "<forward@example.com>"


@pytest.mark.asyncio
async def test_append_only_observation_never_claims_first_seen_source():
    db = FakeDB({"id": "doc-1"})

    result = await persist_mailbox_provenance(
        db,
        "doc-1",
        mailbox_address="warehouse@gamerpackaging.com",
        mailbox_id="mbx-warehouse",
        mailbox_category="Warehouse",
        graph_message_id="graph-parent",
        internet_message_id="<parent@example.com>",
        attachment_id="att-parent",
        source="batch_split_parent",
        set_first_seen=False,
    )

    doc = db.hub_documents.doc
    assert result["updated"] is True
    assert result["set_first_seen"] is False
    assert result["first_seen_fields_written"] == []
    assert "source_mailbox_address" not in doc
    assert "source_graph_message_id" not in doc
    assert doc["provenance_observations"][-1]["mailbox_address"] == "warehouse@gamerpackaging.com"
    assert doc["provenance_observations"][-1]["source"] == "batch_split_parent"


@pytest.mark.asyncio
async def test_missing_document_fails_without_fabricating_provenance():
    db = FakeDB(None)
    result = await persist_mailbox_provenance(
        db,
        "missing",
        mailbox_address="hub-ap-intake@gamerpackaging.com",
    )
    assert result == {"updated": False, "reason": "document_not_found"}
    assert db.hub_documents.updates == []
