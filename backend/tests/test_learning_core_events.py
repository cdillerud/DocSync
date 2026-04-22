"""
Tests for learning_core.events_service — U1 (v2.4.1)
────────────────────────────────────────────────────

Covers the canonical event log writer + reader + summary.
"""

import pytest


class FakeCursor:
    def __init__(self, docs): self._docs = list(docs)
    def __aiter__(self): return self
    async def __anext__(self):
        if not self._docs: raise StopAsyncIteration
        return self._docs.pop(0)
    def sort(self, *a, **kw): return self
    def limit(self, n):
        self._docs = self._docs[:n]
        return self
    async def to_list(self, n):
        out = list(self._docs[:n]); self._docs = []
        return out


class FakeColl:
    def __init__(self):
        self.docs = []
    async def insert_one(self, d):
        self.docs.append(d)
        class R: inserted_id = "x"
        return R()
    def find(self, q=None, proj=None):
        docs = list(self.docs)
        if q:
            out = []
            for d in docs:
                ok = True
                for k, v in q.items():
                    if isinstance(v, dict):
                        for op, opv in v.items():
                            if op == "$gte" and not (d.get(k) and d.get(k) >= opv):
                                ok = False
                    elif d.get(k) != v:
                        ok = False
                if ok: out.append(d)
            docs = out
        return FakeCursor(docs)
    async def count_documents(self, q):
        return len(self.docs)
    def aggregate(self, pipeline):
        # Tiny pipeline interpreter supporting $group by domain/event_type + $sort + $limit
        docs = list(self.docs)
        groups = {}
        for stage in pipeline:
            if "$group" in stage:
                field = stage["$group"]["_id"].lstrip("$")
                for d in docs:
                    k = d.get(field)
                    groups[k] = groups.get(k, 0) + 1
                docs = [{"_id": k, "c": v} for k, v in groups.items()]
            elif "$sort" in stage:
                docs.sort(key=lambda x: x.get("c", 0), reverse=True)
            elif "$limit" in stage:
                docs = docs[:stage["$limit"]]
        return FakeCursor(docs)
    async def create_index(self, spec, name=None):
        return name


class FakeDb:
    def __init__(self):
        self.coll = FakeColl()
    def __getitem__(self, name):
        return self.coll


@pytest.mark.asyncio
async def test_record_event_happy_path():
    from workflows.core.learning_core import record_event, EVENTS_COLL
    db = FakeDb()
    res = await record_event(
        domain="sales_intake",
        event_type="suggestion_accepted",
        scope_type="customer",
        scope_value="C-10250",
        target={"item_no": "OIPALLET"},
        actor="user",
        source="test",
        db=db,
    )
    assert res["id"]
    assert res["domain"] == "sales_intake"
    assert res["scope_value"] == "C-10250"
    assert res["target"]["item_no"] == "OIPALLET"
    assert "_id" not in res
    assert len(db[EVENTS_COLL].docs) == 1


@pytest.mark.asyncio
async def test_record_event_coerces_unknown_domain_to_generic():
    from workflows.core.learning_core import record_event
    db = FakeDb()
    res = await record_event(domain="bogus_domain", event_type="x", db=db)
    assert res["domain"] == "generic"


@pytest.mark.asyncio
async def test_list_events_filters_by_domain():
    from workflows.core.learning_core import record_event, list_events
    db = FakeDb()
    await record_event(domain="sales_intake", event_type="a", db=db)
    await record_event(domain="ap_posting",  event_type="b", db=db)
    await record_event(domain="sales_intake", event_type="c", db=db)
    intake_events = await list_events(domain="sales_intake", db=db)
    assert len(intake_events) == 2
    assert all(e["domain"] == "sales_intake" for e in intake_events)


@pytest.mark.asyncio
async def test_get_domain_summary_shape():
    from workflows.core.learning_core import record_event, get_domain_summary
    db = FakeDb()
    await record_event(domain="sales_intake", event_type="suggestion_accepted", db=db)
    await record_event(domain="sales_intake", event_type="suggestion_accepted", db=db)
    await record_event(domain="ap_posting",   event_type="draft_bc_feedback", db=db)
    s = await get_domain_summary(db=db)
    assert s["total_events"] == 3
    assert s["by_domain"]["sales_intake"] == 2
    assert s["by_domain"]["ap_posting"] == 1
    assert s["top_event_types"]["suggestion_accepted"] == 2
    assert len(s["recent_events"]) == 3


@pytest.mark.asyncio
async def test_get_trend_returns_dense_series_with_zero_fill():
    """7-day trend must always return exactly `days` buckets, zero-filled."""
    from datetime import datetime, timezone, timedelta
    from workflows.core.learning_core import get_trend, EVENTS_COLL

    db = FakeDb()
    now = datetime.now(timezone.utc)
    # 2 events today, 1 event 3 days ago, 1 outside the 7-day window (10d ago)
    for offset, count in [(0, 2), (3, 1), (10, 1)]:
        ts = (now - timedelta(days=offset)).isoformat()
        for _ in range(count):
            await db[EVENTS_COLL].insert_one({
                "id": f"t-{offset}-{_}", "domain": "sales_intake",
                "event_type": "x", "scope_type": "global", "scope_value": None,
                "target": {}, "extra": {}, "source": "test",
                "created_at": ts,
            })

    trend = await get_trend(domain="sales_intake", days=7, db=db)
    assert len(trend) == 7, f"expected 7 buckets, got {len(trend)}"
    assert all("date" in b and "count" in b for b in trend)
    # Dates are ascending
    assert [b["date"] for b in trend] == sorted(b["date"] for b in trend)
    # Today bucket has 2 events; 3-days-ago bucket has 1; 10-days-ago excluded
    assert sum(b["count"] for b in trend) == 3
    assert trend[-1]["count"] == 2  # last bucket = today


@pytest.mark.asyncio
async def test_get_trend_clamps_days_range():
    """days is clamped to [1, 90]."""
    from workflows.core.learning_core import get_trend
    db = FakeDb()
    assert len(await get_trend(days=0, db=db)) == 1
    assert len(await get_trend(days=-5, db=db)) == 1
    assert len(await get_trend(days=500, db=db)) == 90


@pytest.mark.asyncio
async def test_get_trend_filters_by_domain():
    from datetime import datetime, timezone
    from workflows.core.learning_core import get_trend, EVENTS_COLL

    db = FakeDb()
    now_iso = datetime.now(timezone.utc).isoformat()
    for dom in ("sales_intake", "sales_intake", "ap_posting"):
        await db[EVENTS_COLL].insert_one({
            "id": f"t-{dom}", "domain": dom, "event_type": "x",
            "scope_type": "global", "scope_value": None, "target": {},
            "extra": {}, "source": "test", "created_at": now_iso,
        })
    trend_si = await get_trend(domain="sales_intake", days=7, db=db)
    trend_ap = await get_trend(domain="ap_posting", days=7, db=db)
    assert sum(b["count"] for b in trend_si) == 2
    assert sum(b["count"] for b in trend_ap) == 1


@pytest.mark.asyncio
async def test_leaderboard_ranks_actors_by_event_count():
    """Most active reviewer appears first; bots (actor='test') are skipped."""
    from datetime import datetime, timezone
    from workflows.core.learning_core import get_reviewer_leaderboard, EVENTS_COLL

    db = FakeDb()
    now_iso = datetime.now(timezone.utc).isoformat()
    seed = [
        ("alice", "sales_intake", "suggestion_accepted"),
        ("alice", "sales_intake", "suggestion_accepted"),
        ("alice", "ap_posting",   "ap_review_correct"),
        ("bob",   "ap_posting",   "ap_review_correct"),
        ("test",  "sales_intake", "suggestion_rejected"),  # should be skipped
    ]
    for actor, dom, et in seed:
        await db[EVENTS_COLL].insert_one({
            "id": f"lb-{actor}-{dom}-{et}",
            "actor": actor, "domain": dom, "event_type": et,
            "scope_type": "global", "scope_value": None,
            "target": {}, "extra": {}, "source": "test",
            "created_at": now_iso,
        })

    lb = await get_reviewer_leaderboard(days=7, limit=10, db=db)
    assert lb["total_events"] == 4  # 'test' actor skipped
    assert lb["unique_actors"] == 2
    assert len(lb["reviewers"]) == 2
    assert lb["reviewers"][0]["actor"] == "alice"
    assert lb["reviewers"][0]["events"] == 3
    assert lb["reviewers"][0]["domains"] == {"sales_intake": 2, "ap_posting": 1}
    assert lb["reviewers"][0]["top_event_type"] == "suggestion_accepted"
    assert lb["reviewers"][1]["actor"] == "bob"
    assert lb["reviewers"][1]["events"] == 1


@pytest.mark.asyncio
async def test_leaderboard_respects_window_and_limit():
    from datetime import datetime, timezone
    from workflows.core.learning_core import get_reviewer_leaderboard

    db = FakeDb()
    # Empty DB
    lb = await get_reviewer_leaderboard(days=7, limit=5, db=db)
    assert lb["window_days"] == 7
    assert lb["reviewers"] == []
    assert lb["total_events"] == 0
    # Clamp days
    lb = await get_reviewer_leaderboard(days=999, db=db)
    assert lb["window_days"] == 90
    lb = await get_reviewer_leaderboard(days=0, db=db)
    assert lb["window_days"] == 1






@pytest.mark.asyncio
async def test_intake_feedback_dual_writes_to_learning_core(monkeypatch):
    """record_feedback_event should land in both the legacy intake_learning_events
    AND the unified learning_events_v2 collection."""
    from services import intake_learning_feedback_service as fb

    # Build a FakeDb that tracks both collections separately
    class MultiFakeDb:
        def __init__(self):
            self.collections = {}
        def __getitem__(self, name):
            self.collections.setdefault(name, FakeColl())
            return self.collections[name]
        # legacy code uses attribute access too
        def __getattr__(self, name):
            return self[name]

    db = MultiFakeDb()

    res = await fb.record_feedback_event(
        event_type="suggestion_accepted",
        customer_no="C-10250",
        item_no="OIPALLET",
        trigger_item="*",
        db=db,
    )
    assert res["ok"] is True
    # Legacy collection has the event
    legacy = db["intake_learning_events"].docs
    assert len(legacy) == 1
    assert legacy[0]["event_type"] == "suggestion_accepted"
    # Unified collection has the event too
    unified = db["learning_events_v2"].docs
    assert len(unified) == 1
    assert unified[0]["domain"] == "sales_intake"
    assert unified[0]["scope_value"] == "C-10250"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
