"""Invariants for the /api/dashboard/inbox-stats endpoint.

Specifically guards the `auto_validation_rate` ratio against the
batch_parent leak that produced the observed 101.3% reading on the
production dashboard. The numerator must apply the SAME
`{"status": {"$ne": "batch_parent"}}` filter the denominator
applies; the rate must never exceed 100 or fall below 0; an empty
denominator must yield 0, never NaN/Infinity.

Pure unit tests — no live Mongo. The dashboard router is exercised
with `get_db()` patched to return a tiny fake that answers the two
`count_documents` calls the auto-rate math makes.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest


def _matches(doc: Dict[str, Any], q: Dict[str, Any]) -> bool:
    """Tiny subset of Mongo query matching; only the operators the
    dashboard route actually uses. Keeps the test fixture honest
    without pulling in mongomock just for two queries."""
    if not q:
        return True
    for key, cond in q.items():
        if key == "$and":
            if not all(_matches(doc, sub) for sub in cond):
                return False
            continue
        if key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
            continue
        val = doc.get(key)
        if isinstance(cond, dict):
            for op, expected in cond.items():
                if op == "$ne":
                    if val == expected:
                        return False
                elif op == "$nin":
                    if val in expected:
                        return False
                elif op == "$in":
                    if val not in expected:
                        return False
                elif op == "$gte":
                    if val is None or val < expected:
                        return False
                elif op == "$exists":
                    if expected and key not in doc:
                        return False
                    if not expected and key in doc:
                        return False
                else:
                    raise NotImplementedError(
                        f"fake mongo: op {op!r} not supported")
        else:
            if val != cond:
                return False
    return True


class _FakeCollection:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = list(docs)

    async def count_documents(self, query: Dict[str, Any]) -> int:
        return sum(1 for d in self._docs if _matches(d, query))

    def find(self, query, projection=None):  # pragma: no cover
        return _FakeCursor(
            [d for d in self._docs if _matches(d, query)])


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_, **__):
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, _length):
        return self._docs


class _FakeDB:
    def __init__(self, docs: List[Dict[str, Any]]):
        self.hub_documents = _FakeCollection(docs)


def _run_inbox_stats(monkeypatch, docs: List[Dict[str, Any]]
                     ) -> Dict[str, Any]:
    from routers import dashboard as dashboard_mod
    monkeypatch.setattr(dashboard_mod, "get_db",
                        lambda: _FakeDB(docs))
    return asyncio.get_event_loop().run_until_complete(
        dashboard_mod.get_inbox_stats())


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

def test_batch_parent_auto_doc_does_not_inflate_numerator(monkeypatch):
    """The exact production bug: a batch_parent carrying
    automation_decision='auto' must NOT count toward auto-rate."""
    docs = [
        # 1 leaking parent (was the bug source)
        {"id": "p1", "status": "batch_parent",
         "automation_decision": "auto"},
        # 1 normal auto doc, 2 normal non-auto docs
        {"id": "a1", "status": "Extracted",
         "automation_decision": "auto"},
        {"id": "a2", "status": "Extracted",
         "automation_decision": "manual"},
        {"id": "a3", "status": "Extracted",
         "automation_decision": "manual"},
    ]
    out = _run_inbox_stats(monkeypatch, docs)
    # Without the fix this would be (2 / 3) * 100 = 66.7 (parent + a1
    # over the 3 non-batch docs). With the fix it's (1 / 3) * 100 = 33.3.
    assert out["auto_validation_rate"] == 33.3, (
        f"batch_parent leaked into numerator; rate={out['auto_validation_rate']}")


def test_all_eligible_docs_auto_yields_exactly_100(monkeypatch):
    docs = [
        {"id": f"d{i}", "status": "Extracted", "auto_cleared": True}
        for i in range(10)
    ]
    out = _run_inbox_stats(monkeypatch, docs)
    assert out["auto_validation_rate"] == 100.0, out["auto_validation_rate"]


def test_zero_non_batch_denominator_yields_zero(monkeypatch):
    """Empty denominator must not produce Infinity or NaN."""
    docs = [
        # Only batch_parent docs → denominator becomes 0.
        {"id": "p1", "status": "batch_parent",
         "automation_decision": "auto"},
    ]
    out = _run_inbox_stats(monkeypatch, docs)
    assert out["auto_validation_rate"] == 0
    # Belt: must be a real number, never NaN/Inf.
    val = out["auto_validation_rate"]
    assert val == val  # noqa: PLR0124 — NaN check
    assert val not in (float("inf"), float("-inf"))


def test_invariant_rate_in_zero_to_hundred(monkeypatch):
    """Property check across a mix that includes leaking parents,
    duplicates, and various auto signals. Rate must always land in
    [0, 100]."""
    docs = [
        # leaking parents (would have inflated numerator pre-fix)
        {"id": "p1", "status": "batch_parent",
         "automation_decision": "auto"},
        {"id": "p2", "status": "batch_parent",
         "auto_cleared": True},
        {"id": "p3", "status": "batch_parent",
         "sales_review_status": "auto_approved"},
        # Non-batch mix using all three auto signals
        {"id": "a1", "status": "Extracted",
         "automation_decision": "auto"},
        {"id": "a2", "status": "NeedsReview",
         "auto_cleared": True},
        {"id": "a3", "status": "Extracted",
         "sales_review_status": "auto_approved"},
        # Non-auto docs
        {"id": "n1", "status": "Extracted"},
        {"id": "n2", "status": "NeedsReview"},
        {"id": "n3", "status": "Extracted",
         "automation_decision": "manual"},
        {"id": "n4", "status": "Extracted"},
    ]
    out = _run_inbox_stats(monkeypatch, docs)
    rate = out["auto_validation_rate"]
    assert 0 <= rate <= 100, f"invariant violated; rate={rate}"
    # And: 3 auto / 7 non-batch = 42.857... -> 42.9
    assert rate == 42.9, rate


def test_other_kpis_still_render_after_fix(monkeypatch):
    """Smoke check that the rest of the inbox-stats payload is still
    structurally well-formed; the fix touched only auto_rate math."""
    docs = [
        {"id": "a1", "status": "Extracted",
         "automation_decision": "auto",
         "ai_confidence": 0.92},
        {"id": "n1", "status": "NeedsReview",
         "workflow_status": "needs_review",
         "ai_confidence": 0.55},
    ]
    out = _run_inbox_stats(monkeypatch, docs)
    for key in (
        "ingested_today",
        "avg_daily_7d",
        "auto_validation_rate",
        "pending_review",
        "bounds_alerts",
        "avg_ai_confidence",
        "total_documents",
        "posted_to_bc_7d",
        "ready_for_post",
    ):
        assert key in out, f"missing field {key}"
        assert out[key] is not None, f"field {key} is None"
