"""Tests for learning_core.pattern_health_service (U3, v2.5.2)."""

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
        out = list(self._docs[:n]); self._docs = []; return out


class FakeColl:
    def __init__(self, initial=None):
        self.docs = list(initial or [])
    async def insert_one(self, d):
        self.docs.append(d)
        class R: inserted_id = "x"
        return R()
    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            ok = all(d.get(k) == v for k, v in q.items() if not isinstance(v, dict))
            if ok and "$set" in upd:
                d.update(upd["$set"])
                return
    def find(self, q=None, proj=None):
        docs = list(self.docs)
        if q:
            out = []
            for d in docs:
                ok = True
                for k, v in q.items():
                    if isinstance(v, dict):
                        if "$ne" in v and d.get(k) == v["$ne"]:
                            ok = False
                    elif d.get(k) != v:
                        ok = False
                if ok: out.append(d)
            docs = out
        return FakeCursor(docs)
    async def count_documents(self, q):
        return len(self.docs)


class FakeDb:
    def __init__(self):
        self.order_line_patterns = FakeColl()
        self.posting_pattern_analysis = FakeColl()
        self.intake_pattern_hygiene_runs = FakeColl()
        self.intake_learning_events = FakeColl()
        self.intake_item_candidates = FakeColl()
        self.intake_item_aliases = FakeColl()
        self._extras = {}
    _FIXED = {"order_line_patterns", "posting_pattern_analysis",
              "intake_pattern_hygiene_runs", "intake_learning_events",
              "intake_item_candidates", "intake_item_aliases"}
    def __getitem__(self, name):
        if name in self._FIXED:
            return getattr(self, name)
        if name not in self._extras:
            self._extras[name] = FakeColl()
        return self._extras[name]


@pytest.mark.asyncio
async def test_intake_health_aggregates_four_states():
    from workflows.core.learning_core import pattern_health_service as ph
    db = FakeDb()
    db.order_line_patterns.docs.append({
        "customer_no": "C-10250",
        "associated_lines": [
            {"item_no": "A", "trusted": True},
            {"item_no": "B", "retired": True},
            {"item_no": "C", "accept_count": 1, "reject_count": 0},
            {"item_no": "D"},  # unscored
        ],
    })
    r = await ph.get_health("sales_intake", db=db)
    assert r["summary"] == {"trusted": 1, "drifting": 1, "retired": 1, "unscored": 1, "total": 4}
    assert r["per_scope"][0]["scope_value"] == "C-10250"


@pytest.mark.asyncio
async def test_ap_health_maps_confidence_tiers():
    from workflows.core.learning_core import pattern_health_service as ph
    db = FakeDb()
    db.posting_pattern_analysis.docs.extend([
        {"vendor_no": "V-A", "posting_template": {"confidence": "high"}, "invoices_analyzed": 10},
        {"vendor_no": "V-B", "posting_template": {"confidence": "medium"}, "invoices_analyzed": 3},
        {"vendor_no": "V-C", "posting_template": {"confidence": "low"}, "invoices_analyzed": 1},
        {"vendor_no": "V-D", "posting_template": {"confidence": "none"}, "invoices_analyzed": 0},
    ])
    r = await ph.get_health("ap_posting", db=db)
    # New (v2.5.3) semantics:
    #   V-A  (high, 10 samples)  → trusted   (explicit high tier)
    #   V-B  (medium, 3 samples) → drifting  (medium_tier_still_maturing,
    #                                         samples < implicit-trust min)
    #   V-C  (low, 1 sample)     → unscored  (insufficient_samples — was
    #                                         incorrectly "drifting" pre-fix)
    #   V-D  (none, 0 samples)   → retired   (tier=none)
    assert r["summary"]["trusted"] == 1
    assert r["summary"]["drifting"] == 1
    assert r["summary"]["unscored"] == 1
    assert r["summary"]["retired"] == 1
    assert r["summary"]["total"] == 4


@pytest.mark.asyncio
async def test_combined_health_aggregates_both_domains():
    from workflows.core.learning_core import pattern_health_service as ph
    db = FakeDb()
    db.order_line_patterns.docs.append({
        "customer_no": "C-1",
        "associated_lines": [{"item_no": "A", "trusted": True}],
    })
    db.posting_pattern_analysis.docs.append({
        "vendor_no": "V-1",
        "posting_template": {"confidence": "high"}, "invoices_analyzed": 5,
    })
    r = await ph.get_health(db=db)
    assert r["combined_summary"]["trusted"] == 2
    assert r["combined_summary"]["total"] == 2
    domains = {d["domain"] for d in r["domains"]}
    assert domains == {"sales_intake", "ap_posting"}


@pytest.mark.asyncio
async def test_run_hygiene_all_retires_ap_none_tier_and_scans_intake():
    from workflows.core.learning_core import pattern_health_service as ph
    db = FakeDb()
    db.posting_pattern_analysis.docs.append({
        "vendor_no": "V-RETIRE", "status": "analyzed",
        "posting_template": {"confidence": "none"},
    })
    db.posting_pattern_analysis.docs.append({
        "vendor_no": "V-KEEP", "status": "analyzed",
        "posting_template": {"confidence": "high"},
    })
    # Add one intake pattern so intake hygiene has something to scan
    db.order_line_patterns.docs.append({
        "customer_no": "C-X",
        "trigger_item_no": "*",
        "associated_lines": [
            {"item_no": "FOO", "accept_count": 9, "reject_count": 1},   # → trusted
        ],
    })
    r = await ph.run_hygiene("all", db=db)
    assert r["total_retired"] >= 1    # V-RETIRE should flip
    # Confirm AP retirement actually applied
    retired = next(d for d in db.posting_pattern_analysis.docs if d["vendor_no"] == "V-RETIRE")
    assert retired["status"] == "retired"
    keep = next(d for d in db.posting_pattern_analysis.docs if d["vendor_no"] == "V-KEEP")
    assert keep["status"] == "analyzed"


@pytest.mark.asyncio
async def test_unknown_domain_returns_error_shape():
    from workflows.core.learning_core import pattern_health_service as ph
    db = FakeDb()
    r = await ph.get_health("alien", db=db)
    assert "error" in r


@pytest.mark.asyncio
async def test_hygiene_records_audit_run():
    from workflows.core.learning_core import pattern_health_service as ph
    db = FakeDb()
    await ph.run_hygiene("all", db=db)
    assert len(db["pattern_hygiene_runs"].docs) == 1
    run = db["pattern_hygiene_runs"].docs[0]
    assert "id" in run
    assert "ran_at" in run
    assert "per_domain" in run


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
