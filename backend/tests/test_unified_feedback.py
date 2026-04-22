"""
Tests for learning_core.feedback_service — U4 (v2.5.2)
──────────────────────────────────────────────────────

Validates the unified cross-domain feedback dispatcher:
  • scope_type="customer" routes to intake_learning_feedback_service
  • scope_type="vendor" routes to ap_invoice_feedback_service AND
    dual-writes to learning_events_v2 (telemetry tick for sparklines)
  • Unknown / missing-required-field errors surface as 200 + {error}
"""

import pytest


# ─────────────────────────────────────────────────────────────
# Fake DB — supports both motor-style __getitem__ and attribute access
# ─────────────────────────────────────────────────────────────

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
    async def insert_many(self, ds):
        self.docs.extend(ds)
    async def find_one(self, q=None, proj=None):
        for d in self.docs:
            ok = True
            for k, v in (q or {}).items():
                if d.get(k) != v:
                    ok = False
                    break
            if ok:
                return dict(d)
        return None
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
    async def update_one(self, q, update, **kw):
        class R: matched_count = 0; modified_count = 0
        return R()
    async def count_documents(self, q):
        return len(self.docs)
    def aggregate(self, pipeline):
        return FakeCursor([])
    async def create_index(self, spec, name=None):
        return name


class FakeDb:
    def __init__(self):
        self.collections = {}
    def __getitem__(self, name):
        self.collections.setdefault(name, FakeColl())
        return self.collections[name]
    def __getattr__(self, name):
        # legacy code uses db.coll_name attribute access
        if name.startswith("_") or name in ("collections",):
            raise AttributeError(name)
        return self[name]


# ─────────────────────────────────────────────────────────────
# Dispatch validation
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_scope_type_returns_error():
    from workflows.core.learning_core import record_unified_feedback
    db = FakeDb()
    res = await record_unified_feedback(scope_type="alien", db=db)
    assert "error" in res
    assert "alien" in res["error"]
    assert res["known"] == ["customer", "vendor"]


@pytest.mark.asyncio
async def test_customer_without_event_type_returns_error():
    from workflows.core.learning_core import record_unified_feedback
    db = FakeDb()
    res = await record_unified_feedback(scope_type="customer", db=db)
    assert "error" in res
    assert "event_type" in res["error"]
    assert res["scope_type"] == "customer"
    assert "known_event_types" in res


@pytest.mark.asyncio
async def test_vendor_without_document_id_returns_error():
    from workflows.core.learning_core import record_unified_feedback
    db = FakeDb()
    res = await record_unified_feedback(
        scope_type="vendor",
        reviewer_assessment="correct",
        db=db,
    )
    assert "error" in res
    assert "document_id" in res["error"]
    assert res["scope_type"] == "vendor"


@pytest.mark.asyncio
async def test_vendor_without_reviewer_assessment_returns_error():
    from workflows.core.learning_core import record_unified_feedback
    db = FakeDb()
    res = await record_unified_feedback(
        scope_type="vendor",
        document_id="doc-abc",
        db=db,
    )
    assert "error" in res
    assert "reviewer_assessment" in res["error"]


# ─────────────────────────────────────────────────────────────
# Happy paths
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_customer_feedback_routes_and_dual_writes():
    """scope_type='customer' goes through intake_learning_feedback_service
    which dual-writes to intake_learning_events + learning_events_v2."""
    from workflows.core.learning_core import record_unified_feedback
    db = FakeDb()
    res = await record_unified_feedback(
        scope_type="customer",
        scope_value="C-10250",
        event_type="suggestion_accepted",
        item_no="OIPALLET",
        doc_id="doc-123",
        db=db,
    )
    # Dispatcher tags response
    assert res.get("scope_type") == "customer"
    assert res.get("ok") is True or "error" not in res
    # Legacy intake event written
    legacy = db["intake_learning_events"].docs
    assert len(legacy) == 1
    assert legacy[0]["customer_no"] == "C-10250"
    assert legacy[0]["event_type"] == "suggestion_accepted"
    # Unified v2 event written
    unified = db["learning_events_v2"].docs
    assert len(unified) == 1
    assert unified[0]["domain"] == "sales_intake"
    assert unified[0]["scope_value"] == "C-10250"


@pytest.mark.asyncio
async def test_vendor_feedback_routes_and_writes_unified_telemetry():
    """scope_type='vendor' goes through ap_invoice_feedback_service AND
    drops a learning_events_v2 row so the 7-day sparklines light up."""
    from workflows.core.learning_core import record_unified_feedback
    db = FakeDb()
    # Seed a minimal hub_documents record so submit_ap_feedback succeeds
    await db["hub_documents"].insert_one({
        "id": "doc-ap-1",
        "bc_vendor_number": "V-00123",
        "vendor_canonical": "Acme Supplies",
        "vendor_raw": "ACME SUPPLIES INC.",
        "ap_advisory_review": {
            "readiness_status": "ready",
            "confidence": 0.92,
            "model_used": "gpt-4o-mini",
            "profile_state": "trusted",
            "vendor_profile_id": "vp-xyz",
        },
    })
    res = await record_unified_feedback(
        scope_type="vendor",
        scope_value="V-00123",
        document_id="doc-ap-1",
        reviewer_assessment="correct",
        final_human_decision="ready",
        disagreed_fields=[],
        notes="LGTM",
        actor="sally",
        db=db,
    )
    assert res.get("scope_type") == "vendor"
    assert "error" not in res
    assert res.get("reviewer_assessment") == "correct"
    # Legacy ap_reviewer_feedback written
    assert len(db["ap_reviewer_feedback"].docs) == 1
    # Unified v2 event written (new telemetry tick — sparklines will light up)
    unified = db["learning_events_v2"].docs
    assert len(unified) == 1
    assert unified[0]["domain"] == "ap_posting"
    assert unified[0]["event_type"] == "ap_review_correct"
    assert unified[0]["scope_value"] == "V-00123"
    assert unified[0]["target"]["doc_id"] == "doc-ap-1"


@pytest.mark.asyncio
async def test_vendor_feedback_propagates_invalid_assessment_error():
    """If the underlying AP service rejects the assessment, the
    dispatcher must surface the error and NOT write a telemetry event."""
    from workflows.core.learning_core import record_unified_feedback
    db = FakeDb()
    await db["hub_documents"].insert_one({
        "id": "doc-ap-bad", "bc_vendor_number": "V-BAD",
        "vendor_canonical": "x", "vendor_raw": "x",
        "ap_advisory_review": {},
    })
    res = await record_unified_feedback(
        scope_type="vendor",
        scope_value="V-BAD",
        document_id="doc-ap-bad",
        reviewer_assessment="bogus_assessment_xyz",
        db=db,
    )
    assert "error" in res
    assert res["scope_type"] == "vendor"
    # NO telemetry row should be written on error
    assert len(db["learning_events_v2"].docs) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
