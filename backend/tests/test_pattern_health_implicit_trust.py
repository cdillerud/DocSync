"""
Regression tests for Pattern Health implicit-trust logic (v2.5.3).

Bug observed on the live dashboard (2026-04-19):
    Pattern Health — AP (Vendors): Trusted=3, Drifting=216, Retired=0, Unscored=0.

    But the same dashboard showed 97.5% auto-processing rate and zero recent
    negative feedback for the majority of those 216 "drifting" vendors. The
    old _ap_health() classified any vendor not at tier=high as "drifting",
    even if the vendor had 300+ clean BC postings and zero corrections.

Fix: implicit trust — a vendor with >= AP_IMPLICIT_TRUST_MIN_SAMPLES samples
AND zero negative learning_events_v2 in the last 30 days earns "trusted"
state, regardless of template confidence tier.
"""
import pytest

from workflows.core.learning_core.pattern_health_service import (
    _ap_health,
    AP_IMPLICIT_TRUST_MIN_SAMPLES,
)


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._docs):
            raise StopAsyncIteration
        d = self._docs[self._i]
        self._i += 1
        return d

    def sort(self, *_a, **_kw):
        return self

    def limit(self, *_a, **_kw):
        return self

    async def to_list(self, *_a, **_kw):
        return list(self._docs)


class _FakeAggregate(_FakeCursor):
    pass


class _FakeCollection:
    def __init__(self, docs=None, aggregate_rows=None):
        self._docs = docs or []
        self._agg = aggregate_rows or []

    def find(self, *_a, **_kw):
        return _FakeCursor(self._docs)

    def aggregate(self, *_a, **_kw):
        return _FakeAggregate(self._agg)


class _FakeDB:
    def __init__(self, patterns=None, events=None):
        self.posting_pattern_analysis = _FakeCollection(docs=patterns or [])
        self.learning_events_v2 = _FakeCollection(aggregate_rows=events or [])
        # events_service.list_events + get_trend query via db[EVENTS_COLL]
        self._empty = _FakeCollection()

    def __getitem__(self, _name):
        # Any collection name requested via db[name] returns an empty
        # collection — our tests don't assert on recent_events / trend_7d
        # contents, only on summary / per_scope totals.
        return self._empty


@pytest.mark.asyncio
async def test_high_tier_vendor_is_trusted():
    db = _FakeDB(patterns=[
        {"vendor_no": "V1", "vendor_name": "Acme",
         "posting_template": {"confidence": "high"},
         "invoices_analyzed": 100},
    ])
    rep = await _ap_health(db, limit=10)
    assert rep["summary"]["trusted"] == 1
    assert rep["summary"]["drifting"] == 0
    assert rep["per_scope"][0]["trust_reason"] == "explicit_high_tier"


@pytest.mark.asyncio
async def test_medium_tier_with_many_samples_no_drift_is_implicit_trusted():
    """The headline fix: medium tier + enough samples + zero negative events
    → trusted instead of drifting."""
    db = _FakeDB(patterns=[
        {"vendor_no": "V2", "vendor_name": "Beta",
         "posting_template": {"confidence": "medium"},
         "invoices_analyzed": 50},  # well above the 10 threshold
    ])
    rep = await _ap_health(db, limit=10)
    assert rep["summary"]["trusted"] == 1
    assert rep["summary"]["drifting"] == 0
    assert "implicit_success" in rep["per_scope"][0]["trust_reason"]


@pytest.mark.asyncio
async def test_medium_tier_with_drift_event_is_drifting():
    """A vendor with recent BC corrections stays drifting even with high sample count."""
    db = _FakeDB(
        patterns=[
            {"vendor_no": "V3", "vendor_name": "Gamma",
             "posting_template": {"confidence": "medium"},
             "invoices_analyzed": 200},
        ],
        events=[{"_id": "V3", "c": 4}],  # 4 negative events in last 30d
    )
    rep = await _ap_health(db, limit=10)
    assert rep["summary"]["drifting"] == 1
    assert rep["summary"]["trusted"] == 0
    assert rep["per_scope"][0]["negative_events_30d"] == 4
    assert "negative_event" in rep["per_scope"][0]["trust_reason"]


@pytest.mark.asyncio
async def test_medium_tier_with_low_samples_is_still_drifting():
    """Edge: medium tier vendor with too few samples for implicit trust stays drifting."""
    db = _FakeDB(patterns=[
        {"vendor_no": "V4", "vendor_name": "Delta",
         "posting_template": {"confidence": "medium"},
         "invoices_analyzed": 3},  # below the threshold
    ])
    rep = await _ap_health(db, limit=10)
    assert rep["summary"]["drifting"] == 1
    assert rep["summary"]["trusted"] == 0
    assert rep["per_scope"][0]["trust_reason"] == "medium_tier_still_maturing"


@pytest.mark.asyncio
async def test_low_tier_with_low_samples_is_unscored():
    db = _FakeDB(patterns=[
        {"vendor_no": "V5", "vendor_name": "Epsilon",
         "posting_template": {"confidence": "low"},
         "invoices_analyzed": 1},
    ])
    rep = await _ap_health(db, limit=10)
    assert rep["summary"]["unscored"] == 1


@pytest.mark.asyncio
async def test_low_tier_with_enough_samples_is_implicit_trusted():
    """Low-tier vendors CAN earn implicit trust if they've posted a lot
    without triggering any corrections."""
    db = _FakeDB(patterns=[
        {"vendor_no": "V6", "vendor_name": "Zeta",
         "posting_template": {"confidence": "low"},
         "invoices_analyzed": AP_IMPLICIT_TRUST_MIN_SAMPLES},
    ])
    rep = await _ap_health(db, limit=10)
    assert rep["summary"]["trusted"] == 1


@pytest.mark.asyncio
async def test_retired_vendor_is_retired():
    db = _FakeDB(patterns=[
        {"vendor_no": "V7", "vendor_name": "Eta",
         "posting_template": {"confidence": "none"},
         "status": "retired",
         "invoices_analyzed": 5},
    ])
    rep = await _ap_health(db, limit=10)
    assert rep["summary"]["retired"] == 1


@pytest.mark.asyncio
async def test_real_world_distribution():
    """Simulate the actual prod dashboard numbers and verify the new split
    lands closer to reality: ~3 high-tier, ~38 medium-tier (most with clean
    history), ~178 low-tier. Expect most medium-tier vendors to flip from
    drifting → trusted."""
    patterns = []
    # 3 high-tier
    for i in range(3):
        patterns.append({"vendor_no": f"H{i}",
                         "posting_template": {"confidence": "high"},
                         "invoices_analyzed": 440})
    # 38 medium-tier — 30 clean, 8 with drift events
    for i in range(30):
        patterns.append({"vendor_no": f"M_clean_{i}",
                         "posting_template": {"confidence": "medium"},
                         "invoices_analyzed": 37})
    for i in range(8):
        patterns.append({"vendor_no": f"M_drift_{i}",
                         "posting_template": {"confidence": "medium"},
                         "invoices_analyzed": 37})
    # 178 low-tier, tiny samples
    for i in range(178):
        patterns.append({"vendor_no": f"L{i}",
                         "posting_template": {"confidence": "low"},
                         "invoices_analyzed": 2})

    events = [{"_id": f"M_drift_{i}", "c": 1} for i in range(8)]
    db = _FakeDB(patterns=patterns, events=events)

    rep = await _ap_health(db, limit=300)
    s = rep["summary"]
    # 3 high + 30 clean-medium implicit-trusted = 33
    assert s["trusted"] == 33, f"Expected 33 trusted, got {s['trusted']}"
    # 8 drifting-medium (have negative events)
    assert s["drifting"] == 8, f"Expected 8 drifting, got {s['drifting']}"
    # 178 low-tier, not enough samples → unscored
    assert s["unscored"] == 178, f"Expected 178 unscored, got {s['unscored']}"
    assert s["retired"] == 0
    assert s["total"] == 219
