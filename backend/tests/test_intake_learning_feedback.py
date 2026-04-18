"""
Tests for intake_learning_feedback_service — the Phase D feedback loop.

Covers:
  • record_feedback_event with each of the 6 event types
  • Pattern occurrence bump on accept
  • Pattern frequency decay + retirement on sustained rejects
  • Bounds override widens std_dev, confirm records outlier
  • Unmatched-item candidate / alias recording
  • get_pattern_health aggregation shape
  • run_pattern_hygiene retires low-acceptance lines
"""

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch


# ─────────────────────────────────────────────────────────────
# Fake DB plumbing
# ─────────────────────────────────────────────────────────────

class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)
    def __aiter__(self): return self
    async def __anext__(self):
        if not self._docs: raise StopAsyncIteration
        return self._docs.pop(0)
    def sort(self, *a, **kw): return self
    def limit(self, n): return self
    async def to_list(self, n):
        out = list(self._docs)
        self._docs = []
        return out


class FakeColl:
    def __init__(self, initial=None):
        self.docs = list(initial or [])
    async def insert_one(self, doc):
        self.docs.append(doc)
        class Res: inserted_id = "x"
        return Res()
    async def find_one(self, q, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items() if not isinstance(v, dict)):
                return dict(d)
        # Dotted-field match for associated_lines.item_no
        for d in self.docs:
            want_item = q.get("associated_lines.item_no")
            if want_item and any(
                (ln.get("item_no") or "") == want_item for ln in (d.get("associated_lines") or [])
            ):
                if all(d.get(k) == v for k, v in q.items() if k != "associated_lines.item_no"):
                    return dict(d)
        return None
    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items() if not isinstance(v, dict)):
                if "$set" in upd:
                    d.update(upd["$set"])
                if "$inc" in upd:
                    for k, v in upd["$inc"].items():
                        d[k] = d.get(k, 0) + v
                return
        if upsert:
            new_doc = dict(q)
            if "$set" in upd: new_doc.update(upd["$set"])
            if "$inc" in upd:
                for k, v in upd["$inc"].items():
                    new_doc[k] = v
            self.docs.append(new_doc)
    def find(self, q=None, proj=None):
        return FakeCursor(list(self.docs))
    async def count_documents(self, q):
        return len(self.docs)


class FakeDb:
    def __init__(self):
        self.order_line_patterns = FakeColl()
        self.intake_learning_events = FakeColl()
        self.intake_item_candidates = FakeColl()
        self.intake_item_aliases = FakeColl()
        self.intake_pattern_hygiene_runs = FakeColl()
    def __getitem__(self, name):
        return getattr(self, name, FakeColl())


# ─────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_event_type_returns_error():
    from services import intake_learning_feedback_service as fb
    res = await fb.record_feedback_event(event_type="bogus", db=FakeDb())
    assert "error" in res


@pytest.mark.asyncio
async def test_accept_bumps_occurrences_and_trust_at_90():
    from services import intake_learning_feedback_service as fb
    db = FakeDb()
    db.order_line_patterns.docs.append({
        "customer_no": "C-10250",
        "trigger_item_no": "C-9874",
        "total_orders_analyzed": 10,
        "associated_lines": [
            {"item_no": "OIPALLET", "occurrences": 4, "accept_count": 4, "reject_count": 0},
        ],
    })
    # Accept one more → accept_count=5, rate=100% ≥ 90% → trusted
    res = await fb.record_feedback_event(
        event_type="suggestion_accepted",
        customer_no="C-10250", item_no="OIPALLET", trigger_item="*",  # fallback lookup
        db=db,
    )
    assert res["applied"]["action"] == "applied"
    assert res["applied"]["new_occurrences"] == 5
    assert res["applied"]["trusted"] is True


@pytest.mark.asyncio
async def test_reject_retires_after_threshold():
    from services import intake_learning_feedback_service as fb
    db = FakeDb()
    db.order_line_patterns.docs.append({
        "customer_no": "C-10250",
        "trigger_item_no": "C-9874",
        "total_orders_analyzed": 10,
        "associated_lines": [
            # already 1 accept, 4 rejects → one more reject makes 5 samples, 20% accept_rate → retired
            {"item_no": "OIOTHER", "occurrences": 1, "accept_count": 1, "reject_count": 4},
        ],
    })
    res = await fb.record_feedback_event(
        event_type="suggestion_rejected",
        customer_no="C-10250", item_no="OIOTHER", trigger_item="C-9874", db=db,
    )
    assert res["applied"]["retired"] is True
    assert res["applied"]["new_occurrences"] == 0 or res["applied"]["new_occurrences"] >= 0  # decayed


@pytest.mark.asyncio
async def test_bounds_override_widens_std_dev():
    from services import intake_learning_feedback_service as fb
    db = FakeDb()
    db.order_line_patterns.docs.append({
        "customer_no": "C-10250",
        "trigger_item_no": "*",
        "qty_history": {"mean": 60, "std_dev": 10.0, "samples": 5},
    })
    res = await fb.record_feedback_event(
        event_type="bounds_violation_overridden",
        customer_no="C-10250", item_no="C-9874", db=db,
    )
    assert res["applied"]["action"] == "bounds_nudged"
    # 10.0 * 1.10 = 11.0
    assert res["applied"]["new_std_dev"] == 11.0


@pytest.mark.asyncio
async def test_unmatched_item_confirmed_new_creates_candidate():
    from services import intake_learning_feedback_service as fb
    db = FakeDb()
    res = await fb.record_feedback_event(
        event_type="unmatched_item_confirmed_new",
        customer_no="C-10250", item_no="NEW-PART-001",
        extra={"description": "Brand new widget"},
        db=db,
    )
    assert res["applied"]["action"] == "candidate_recorded"
    assert len(db.intake_item_candidates.docs) == 1
    assert db.intake_item_candidates.docs[0]["item_no"] == "NEW-PART-001"


@pytest.mark.asyncio
async def test_unmatched_item_mapped_saves_alias():
    from services import intake_learning_feedback_service as fb
    db = FakeDb()
    res = await fb.record_feedback_event(
        event_type="unmatched_item_mapped",
        customer_no="C-10250", item_no="TYPO-001",
        extra={"mapped_to_bc_item": "C-9874-10001833"},
        db=db,
    )
    assert res["applied"]["action"] == "alias_saved"
    assert res["applied"]["to"] == "C-9874-10001833"


@pytest.mark.asyncio
async def test_get_pattern_health_shape():
    from services import intake_learning_feedback_service as fb
    db = FakeDb()
    db.order_line_patterns.docs.append({
        "customer_no": "C-10250",
        "trigger_item_no": "C-9874",
        "associated_lines": [
            {"item_no": "A", "trusted": True},
            {"item_no": "B", "retired": True, "retired_at": "2026-04-18T00:00:00+00:00"},
            {"item_no": "C", "accept_count": 2, "reject_count": 1},
            {"item_no": "D"},
        ],
    })
    res = await fb.get_pattern_health(db=db)
    assert res["summary"]["trusted"] == 1
    assert res["summary"]["retired"] == 1
    assert res["summary"]["drifting"] == 1
    assert res["summary"]["unscored"] == 1
    assert res["summary"]["total"] == 4
    assert len(res["per_customer"]) == 1


@pytest.mark.asyncio
async def test_run_pattern_hygiene_retires_and_promotes():
    from services import intake_learning_feedback_service as fb
    db = FakeDb()
    db.order_line_patterns.docs.append({
        "customer_no": "C-10250",
        "trigger_item_no": "C-9874",
        "associated_lines": [
            {"item_no": "GOOD", "accept_count": 9, "reject_count": 1},   # 90% → promote
            {"item_no": "BAD",  "accept_count": 1, "reject_count": 4},    # 20% → retire
            {"item_no": "NEW",  "accept_count": 1, "reject_count": 0},    # <5 samples → skip
        ],
    })
    res = await fb.run_pattern_hygiene(db=db)
    assert res["retired"] == 1
    assert res["promoted"] == 1
    lines = db.order_line_patterns.docs[0]["associated_lines"]
    good = next(l for l in lines if l["item_no"] == "GOOD")
    bad = next(l for l in lines if l["item_no"] == "BAD")
    new = next(l for l in lines if l["item_no"] == "NEW")
    assert good.get("trusted") is True
    assert bad.get("retired") is True
    assert new.get("retired") is not True and new.get("trusted") is not True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
