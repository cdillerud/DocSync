"""
Tests for learning_core.digest_service — Weekly Digest (v2.5.2)
────────────────────────────────────────────────────────────────

Validates the digest assembly pipeline: window bounds, headline
narrative, reviewer aggregation, drift inclusion, idempotent upsert
by week_key.
"""

import pytest
from datetime import datetime, date, timezone, timedelta


# Reuse the FakeDb from test_unified_feedback (motor-style getitem + getattr)
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
    def __init__(self):
        self.docs = []
    async def insert_one(self, d):
        self.docs.append(d); return type("R", (), {"inserted_id": "x"})()
    async def insert_many(self, ds):
        self.docs.extend(ds)
    async def find_one(self, q=None, proj=None, sort=None):
        docs = list(self.docs)
        if q:
            out = []
            for d in docs:
                ok = True
                for k, v in q.items():
                    if d.get(k) != v:
                        ok = False; break
                if ok: out.append(d)
            docs = out
        if sort:
            key, direction = sort[0]
            docs.sort(key=lambda x: x.get(key) or "", reverse=(direction == -1))
        return dict(docs[0]) if docs else None
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
                            elif op == "$lt" and not (d.get(k) and d.get(k) < opv): ok = False
                    elif d.get(k) != v:
                        ok = False
                if ok: out.append(d)
            docs = out
        return FakeCursor(docs)
    async def update_one(self, q, update, upsert=False, **kw):
        setv = update.get("$set", {})
        # find match
        idx = None
        for i, d in enumerate(self.docs):
            if all(d.get(k) == v for k, v in q.items()):
                idx = i; break
        if idx is not None:
            self.docs[idx] = {**self.docs[idx], **setv}
        elif upsert:
            self.docs.append({**q, **setv})
        return type("R", (), {"matched_count": 1 if idx is not None else 0,
                              "modified_count": 1 if idx is not None else 0,
                              "upserted_id": "x" if idx is None and upsert else None})()
    async def count_documents(self, q):
        return len(self.docs)
    def aggregate(self, pipeline): return FakeCursor([])
    async def create_index(self, spec, name=None): return name


class FakeDb:
    def __init__(self):
        self.collections = {}
    def __getitem__(self, name):
        self.collections.setdefault(name, FakeColl())
        return self.collections[name]
    def __getattr__(self, name):
        if name.startswith("_") or name == "collections":
            raise AttributeError(name)
        return self[name]


def _seed_events(db, events):
    """events = [(actor, domain, event_type, datetime-iso), ...]"""
    from workflows.core.learning_core.events_service import EVENTS_COLL
    for (actor, dom, et, ts) in events:
        db[EVENTS_COLL].docs.append({
            "id": f"e-{actor}-{et}-{ts[:10]}",
            "actor": actor, "domain": dom, "event_type": et,
            "scope_type": "global", "scope_value": None,
            "target": {}, "extra": {}, "source": "test",
            "created_at": ts,
        })


# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_digest_empty_week_returns_quiet_headline():
    from workflows.core.learning_core import build_weekly_digest, DIGESTS_COLL
    db = FakeDb()
    d = await build_weekly_digest(week_of="2026-04-15", db=db)
    assert d["week_key"] == "2026-W16"
    assert d["week_start"] == "2026-04-13"
    assert d["week_end"] == "2026-04-19"
    assert d["events"]["total"] == 0
    assert d["top_reviewers"] == []
    assert "Quiet week" in d["headline"]
    # Persisted
    assert len(db[DIGESTS_COLL].docs) == 1
    assert db[DIGESTS_COLL].docs[0]["week_key"] == "2026-W16"


@pytest.mark.asyncio
async def test_digest_aggregates_reviewers_and_narrative():
    from workflows.core.learning_core import build_weekly_digest

    db = FakeDb()
    # Seed events inside the target week (2026-W16, Apr 13–19)
    events = [
        ("sally.rep",   "sales_intake", "suggestion_accepted", "2026-04-14T10:00:00+00:00"),
        ("sally.rep",   "sales_intake", "suggestion_accepted", "2026-04-15T10:00:00+00:00"),
        ("sally.rep",   "ap_posting",   "ap_review_correct",   "2026-04-16T10:00:00+00:00"),
        ("marcus.ap",   "ap_posting",   "ap_review_correct",   "2026-04-14T10:00:00+00:00"),
        ("test",        "sales_intake", "suggestion_rejected", "2026-04-14T10:00:00+00:00"),  # bot → skipped
        # Outside the window — should NOT be counted
        ("alice",       "sales_intake", "suggestion_accepted", "2026-04-06T10:00:00+00:00"),
    ]
    _seed_events(db, events)

    d = await build_weekly_digest(week_of="2026-04-15", db=db)
    assert d["events"]["total"] == 4  # 'test' actor + out-of-window skipped
    assert d["events"]["by_domain"] == {"sales_intake": 2, "ap_posting": 2}
    # sally led; note leaderboard uses rolling 7d ending today, but the
    # headline pulls from it — so it should name *someone*
    assert d["headline"]
    assert d["events"]["by_event_type"]  # dict ordered by count


@pytest.mark.asyncio
async def test_digest_idempotent_upsert_by_week_key():
    """Rebuilding for the same week should not create duplicate rows."""
    from workflows.core.learning_core import build_weekly_digest, DIGESTS_COLL
    db = FakeDb()
    await build_weekly_digest(week_of="2026-04-15", db=db)
    await build_weekly_digest(week_of="2026-04-15", db=db)
    await build_weekly_digest(week_of="2026-04-17", db=db)  # same week
    assert len(db[DIGESTS_COLL].docs) == 1
    assert db[DIGESTS_COLL].docs[0]["week_key"] == "2026-W16"


@pytest.mark.asyncio
async def test_digest_rejects_invalid_week_of():
    from workflows.core.learning_core import build_weekly_digest
    db = FakeDb()
    r = await build_weekly_digest(week_of="not-a-date", db=db)
    assert "error" in r
    assert "invalid" in r["error"]


@pytest.mark.asyncio
async def test_get_latest_returns_most_recent_week():
    from workflows.core.learning_core import build_weekly_digest, get_latest_digest
    db = FakeDb()
    await build_weekly_digest(week_of="2026-04-01", db=db)  # earlier
    await build_weekly_digest(week_of="2026-04-15", db=db)  # later
    latest = await get_latest_digest(db=db)
    assert latest["week_key"] == "2026-W16"


@pytest.mark.asyncio
async def test_list_digests_returns_newest_first_and_clamps_limit():
    from workflows.core.learning_core import build_weekly_digest, list_digests
    db = FakeDb()
    for off in range(0, 40, 7):  # 6 different weeks
        dt = (date(2026, 4, 15) - timedelta(days=off)).isoformat()
        await build_weekly_digest(week_of=dt, db=db)
    out = await list_digests(limit=3, db=db)
    assert len(out) == 3
    # Newest first
    ws = [d["week_start"] for d in out]
    assert ws == sorted(ws, reverse=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
