"""
Tests for services.workflow_state_observer — Phase B.0 de-risking (v2.5.2)
──────────────────────────────────────────────────────────────────────────

Validates the observability shim:
  • records the caller (not the wrapped function) as caller_func
  • fire-and-forget — swallows errors
  • summary aggregates by caller × doc_type correctly
  • recent list is newest-first and filters by caller_func
"""

import pytest
from datetime import datetime, timezone, timedelta


class FakeCursor:
    def __init__(self, docs): self._docs = list(docs)
    def __aiter__(self): return self
    async def __anext__(self):
        if not self._docs: raise StopAsyncIteration
        return self._docs.pop(0)
    def sort(self, key, direction=1):
        self._docs.sort(key=lambda d: d.get(key) or "", reverse=(direction == -1))
        return self
    def limit(self, n):
        self._docs = self._docs[:n]; return self
    async def to_list(self, n):
        out = list(self._docs[:n]); self._docs = []
        return out


class FakeColl:
    def __init__(self): self.docs = []
    async def insert_one(self, d):
        self.docs.append(d); return type("R", (), {"inserted_id": "x"})()
    def find(self, q=None, proj=None):
        docs = list(self.docs)
        if q:
            out = []
            for d in docs:
                ok = True
                for k, v in q.items():
                    if isinstance(v, dict):
                        for op, opv in v.items():
                            if op == "$gte" and not (d.get(k) and d.get(k) >= opv): ok = False
                    elif d.get(k) != v: ok = False
                if ok: out.append(d)
            docs = out
        return FakeCursor(docs)
    async def create_index(self, spec, name=None, **kw): return name


class FakeDb:
    def __init__(self): self.collections = {}
    def __getitem__(self, name):
        self.collections.setdefault(name, FakeColl())
        return self.collections[name]
    def __getattr__(self, name):
        if name.startswith("_") or name == "collections": raise AttributeError(name)
        return self[name]


@pytest.mark.asyncio
async def test_record_captures_real_caller_not_wrapper():
    """When record is called from a function, that function's name is captured."""
    from services.workflow_state_observer import record_workflow_call, COLL
    db = FakeDb()

    async def my_caller_function():
        await record_workflow_call(
            db, doc_id="d-1", doc_type="SALES_ORDER",
            confidence=0.9, has_normalized_fields=True,
        )

    await my_caller_function()
    obs = db[COLL].docs
    assert len(obs) == 1
    assert obs[0]["doc_id"] == "d-1"
    assert obs[0]["doc_type"] == "SALES_ORDER"
    assert obs[0]["confidence"] == 0.9
    assert obs[0]["has_normalized_fields"] is True
    assert obs[0]["caller_func"] == "my_caller_function"
    assert "id" in obs[0] and "created_at" in obs[0] and "week_key" in obs[0]


@pytest.mark.asyncio
async def test_record_never_raises_on_db_error():
    """If the DB blows up, the caller must not see the exception."""
    from services.workflow_state_observer import record_workflow_call

    class BrokenColl:
        async def insert_one(self, d): raise RuntimeError("db down")
        async def create_index(self, *a, **kw): raise RuntimeError("db down")

    class BrokenDb:
        def __getitem__(self, name): return BrokenColl()

    # Should complete silently — no exception propagation
    await record_workflow_call(
        BrokenDb(), doc_id="d-2", doc_type="X",
        confidence=0.1, has_normalized_fields=False,
    )


@pytest.mark.asyncio
async def test_summary_groups_by_caller_and_doc_type():
    from services.workflow_state_observer import get_observer_summary, COLL
    db = FakeDb()
    now = datetime.now(timezone.utc).isoformat()
    db[COLL].docs = [
        {"caller_file": "a.py", "caller_func": "foo", "doc_type": "SALES_ORDER", "created_at": now},
        {"caller_file": "a.py", "caller_func": "foo", "doc_type": "SALES_ORDER", "created_at": now},
        {"caller_file": "b.py", "caller_func": "bar", "doc_type": "SHIPMENT",    "created_at": now},
    ]
    s = await get_observer_summary(db, days=7)
    assert s["total_calls"] == 3
    assert s["by_caller"]["a.py::foo"] == 2
    assert s["by_caller"]["b.py::bar"] == 1
    assert s["by_doc_type"]["SALES_ORDER"] == 2
    assert s["by_doc_type"]["SHIPMENT"] == 1
    assert s["by_caller_x_doc_type"]["a.py::foo"] == {"SALES_ORDER": 2}


@pytest.mark.asyncio
async def test_summary_clamps_days_range():
    from services.workflow_state_observer import get_observer_summary
    db = FakeDb()
    assert (await get_observer_summary(db, days=0))["window_days"] == 1
    assert (await get_observer_summary(db, days=999))["window_days"] == 90


@pytest.mark.asyncio
async def test_recent_list_filters_and_limits():
    from services.workflow_state_observer import list_recent_observations, COLL
    db = FakeDb()
    for i in range(10):
        db[COLL].docs.append({
            "id": f"o-{i}",
            "caller_func": "foo" if i < 5 else "bar",
            "doc_type": "X",
            "created_at": f"2026-04-19T00:{i:02d}:00+00:00",
        })
    # All
    all_rows = await list_recent_observations(db, limit=100)
    assert len(all_rows) == 10
    # Filter by caller
    foo_rows = await list_recent_observations(db, caller_func="foo")
    assert len(foo_rows) == 5
    assert all(r["caller_func"] == "foo" for r in foo_rows)
    # Newest first
    newest_first = await list_recent_observations(db, limit=3)
    ts = [r["created_at"] for r in newest_first]
    assert ts == sorted(ts, reverse=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
