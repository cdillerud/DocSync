"""AI Learning approve/reject go through unified_learning_service (Sales config)."""

import pytest

import services.unified_learning_service as uls


class Coll:
    def __init__(self, docs):
        self.docs = {d["suggestion_id"]: d for d in docs}

    async def find_one(self, query, projection=None):
        d = self.docs.get(query["suggestion_id"])
        return dict(d) if d else None

    async def update_one(self, query, update):
        self.docs[query["suggestion_id"]].update(update["$set"])


class DB(dict):
    pass


@pytest.fixture
def events(monkeypatch):
    recorded = []

    async def record_event(**kwargs):
        recorded.append(kwargs)

    import workflows.core.learning_core.events_service as es
    monkeypatch.setattr(es, "record_event", record_event)
    return recorded


def db_with(status):
    db = DB()
    db["so_learning_suggestions"] = Coll([{"suggestion_id": "s1", "status": status, "customer_no": "C1",
                                           "suggestion_type": "field_alias"}])
    return db


@pytest.mark.asyncio
async def test_approve_pending_sales_suggestion(events):
    db = db_with("pending")

    result = await uls.approve_suggestion(db, uls.SALES_CONFIG, "s1", approver="admin")

    doc = db["so_learning_suggestions"].docs["s1"]
    assert result["status"] == "approved"
    assert doc["approved_by"] == "admin" and doc["approved_at"] and doc["updated_at"]
    assert events[0]["event_type"] == "so_suggestion_approved"
    assert events[0]["scope_value"] == "C1"


@pytest.mark.asyncio
async def test_applied_suggestion_cannot_be_approved(events):
    db = db_with("applied")

    result = await uls.approve_suggestion(db, uls.SALES_CONFIG, "s1", approver="admin")

    assert "error" in result
    assert events == []
