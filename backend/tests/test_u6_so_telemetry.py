"""
Tests for U6 — SO Suggestion telemetry tick into learning_events_v2
────────────────────────────────────────────────────────────────────

Verifies that sales_order_learning_suggestion_apply_service now emits
unified events for approve / reject / apply actions so reviewer
activity on sales-order learning suggestions shows up in the Learning
Ops leaderboard + weekly digest.
"""

import pytest
from datetime import datetime, timezone


class FakeCursor:
    def __init__(self, docs): self._docs = list(docs)
    def __aiter__(self): return self
    async def __anext__(self):
        if not self._docs: raise StopAsyncIteration
        return self._docs.pop(0)
    def sort(self, *a, **kw): return self
    def limit(self, n):
        self._docs = self._docs[:n]; return self
    async def to_list(self, n):
        out = list(self._docs[:n]); self._docs = []
        return out


class FakeColl:
    def __init__(self): self.docs = []
    async def insert_one(self, d):
        self.docs.append(d); return type("R", (), {"inserted_id": "x"})()
    async def find_one(self, q=None, proj=None):
        for d in self.docs:
            ok = True
            for k, v in (q or {}).items():
                if d.get(k) != v: ok = False; break
            if ok: return dict(d)
        return None
    def find(self, q=None, proj=None): return FakeCursor(self.docs)
    async def update_one(self, q, update, **kw):
        setv = update.get("$set", {})
        for i, d in enumerate(self.docs):
            if all(d.get(k) == v for k, v in q.items()):
                self.docs[i] = {**d, **setv}
                return type("R", (), {"matched_count": 1, "modified_count": 1})()
        return type("R", (), {"matched_count": 0, "modified_count": 0})()
    async def create_index(self, spec, name=None): return name


class FakeDb:
    def __init__(self): self.collections = {}
    def __getitem__(self, name):
        self.collections.setdefault(name, FakeColl())
        return self.collections[name]
    def __getattr__(self, name):
        if name.startswith("_") or name == "collections":
            raise AttributeError(name)
        return self[name]


# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_suggestion_emits_unified_event():
    from services.sales_order_learning_suggestion_apply_service import approve_suggestion

    db = FakeDb()
    await db["so_learning_suggestions"].insert_one({
        "suggestion_id": "s-1",
        "status": "pending",
        "customer_no": "C-10250",
        "suggestion_type": "add_item",
    })

    res = await approve_suggestion(db, "s-1", approver="sally.rep")
    assert res.get("status") == "approved" or res.get("to_status") == "approved"

    # Unified event was ticked
    unified = db["learning_events_v2"].docs
    assert len(unified) == 1
    ev = unified[0]
    assert ev["domain"] == "sales_intake"
    assert ev["event_type"] == "so_suggestion_approved"
    assert ev["scope_value"] == "C-10250"
    assert ev["actor"] == "sally.rep"
    assert ev["source"] == "sales_order_learning_suggestion_apply_service"
    assert ev["applied"]["from_status"] == "pending"
    assert ev["applied"]["to_status"] == "approved"
    assert ev["target"]["suggestion_id"] == "s-1"


@pytest.mark.asyncio
async def test_reject_suggestion_emits_unified_event():
    from services.sales_order_learning_suggestion_apply_service import reject_suggestion

    db = FakeDb()
    await db["so_learning_suggestions"].insert_one({
        "suggestion_id": "s-2",
        "status": "pending",
        "customer_no": "C-99999",
        "suggestion_type": "add_uom",
    })
    await reject_suggestion(db, "s-2", approver="marcus.ap")

    unified = db["learning_events_v2"].docs
    assert len(unified) == 1
    ev = unified[0]
    assert ev["event_type"] == "so_suggestion_rejected"
    assert ev["actor"] == "marcus.ap"


@pytest.mark.asyncio
async def test_invalid_transition_does_not_emit_event():
    """If the state transition is invalid, NO unified event should be written."""
    from services.sales_order_learning_suggestion_apply_service import approve_suggestion

    db = FakeDb()
    await db["so_learning_suggestions"].insert_one({
        "suggestion_id": "s-3",
        "status": "applied",  # terminal — cannot approve again
        "customer_no": "C-10250",
    })
    res = await approve_suggestion(db, "s-3", approver="sally.rep")
    assert "error" in res

    # Critically — no telemetry row was written
    assert len(db["learning_events_v2"].docs) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
