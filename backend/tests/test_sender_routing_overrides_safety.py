import pytest

from services.sender_routing_overrides import (
    COLLECTION_NAME,
    apply_manual_routing_correction,
    get_sender_routing_override,
)


class FakeCollection:
    def __init__(self, find_one_result=None):
        self.find_one_result = find_one_result
        self.update_calls = []

    async def find_one(self, query, projection=None):
        return self.find_one_result

    async def update_one(self, query, update, upsert=False):
        self.update_calls.append(
            {
                "query": query,
                "update": update,
                "upsert": upsert,
            }
        )
        return object()


class FakeDb:
    def __init__(self, sender_rule=None):
        self.hub_documents = FakeCollection()
        self.sender_rules = FakeCollection(sender_rule)

    def __getitem__(self, name):
        assert name == COLLECTION_NAME
        return self.sender_rules


@pytest.mark.asyncio
async def test_manual_lane_correction_is_document_only_by_default():
    db = FakeDb()

    result = await apply_manual_routing_correction(
        db,
        "doc-1",
        {
            "mailbox_category": "Operations",
            "email_sender": "person@example.com",
        },
        "AP",
        "human_decision_queue",
        "2026-08-04T12:00:00+00:00",
    )

    assert result["routing_changed"] is True
    assert result["sender_rule_requested"] is False
    assert result["sender_rule_written"] is False
    assert db.sender_rules.update_calls == []

    update = db.hub_documents.update_calls[0]["update"]["$set"]
    assert update["mailbox_category"] == "AP"
    assert update["routing_override"]["scope"] == "document"
    assert (
        update["routing_override"]["sender_learning_requested"]
        is False
    )


@pytest.mark.asyncio
async def test_explicit_sender_learning_writes_rule(monkeypatch):
    monkeypatch.setenv("SALES_EMAIL_POLLING_ENABLED", "false")
    db = FakeDb()

    result = await apply_manual_routing_correction(
        db,
        "doc-2",
        {
            "mailbox_category": "Operations",
            "email_sender": " Person@Example.com ",
        },
        "AP",
        "reviewer",
        "2026-08-04T12:00:00+00:00",
        learn_sender_rule=True,
    )

    assert result["sender_rule_requested"] is True
    assert result["sender_rule_written"] is True
    assert result["sender_email"] == "person@example.com"
    assert len(db.sender_rules.update_calls) == 1

    call = db.sender_rules.update_calls[0]
    assert call["query"] == {"sender_email": "person@example.com"}
    assert call["update"]["$set"]["target_mailbox_category"] == "AP"
    assert call["upsert"] is True


@pytest.mark.asyncio
async def test_paused_sales_rule_is_ignored(monkeypatch):
    monkeypatch.setenv("SALES_EMAIL_POLLING_ENABLED", "false")
    db = FakeDb({"target_mailbox_category": "Sales"})

    result = await get_sender_routing_override(
        db,
        "person@example.com",
    )

    assert result is None


@pytest.mark.asyncio
async def test_explicit_sales_learning_is_blocked_while_paused(
    monkeypatch,
):
    monkeypatch.setenv("SALES_EMAIL_POLLING_ENABLED", "false")
    db = FakeDb()

    result = await apply_manual_routing_correction(
        db,
        "doc-3",
        {
            "mailbox_category": "Operations",
            "email_sender": "person@example.com",
        },
        "Sales",
        "reviewer",
        "2026-08-04T12:00:00+00:00",
        learn_sender_rule=True,
    )

    assert result["routing_changed"] is True
    assert result["sender_rule_requested"] is True
    assert result["sender_rule_written"] is False
    assert (
        result["sender_rule_blocked_reason"]
        == "sales_routing_paused"
    )
    assert db.sender_rules.update_calls == []
