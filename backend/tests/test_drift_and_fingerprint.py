"""
Tests for drift_alert_service + learning_core.fingerprint_service
────────────────────────────────────────────────────────────────

Covers v2.5.0 drift alerts and v2.5.1 U2 shared fingerprinting.
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
        self._docs = self._docs[:n]
        return self
    async def to_list(self, n):
        out = list(self._docs[:n]); self._docs = []
        return out


class FakeColl:
    def __init__(self, initial=None):
        self.docs = list(initial or [])
    async def insert_one(self, d):
        self.docs.append(d)
        class R: inserted_id = "x"
        return R()
    async def find_one(self, q, proj=None):
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict):
                    if "$in" in v and d.get(k) not in v["$in"]:
                        ok = False
                    if "$ne" in v and d.get(k) == v["$ne"]:
                        ok = False
                    if "$gt" in v and not (d.get(k, 0) > v["$gt"]):
                        ok = False
                elif d.get(k) != v:
                    ok = False
            if ok: return dict(d)
        return None
    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict):
                    if "$in" in v and d.get(k) not in v["$in"]:
                        ok = False
                elif d.get(k) != v:
                    ok = False
            if ok:
                if "$set" in upd: d.update(upd["$set"])
                return
        if upsert:
            new_doc = dict(q)
            if "$set" in upd: new_doc.update(upd["$set"])
            self.docs.append(new_doc)
    def find(self, q=None, proj=None):
        docs = list(self.docs)
        if q:
            out = []
            for d in docs:
                ok = True
                for k, v in q.items():
                    if isinstance(v, dict):
                        if "$gt" in v and not (d.get(k, 0) > v["$gt"]):
                            ok = False
                        if "$ne" in v and d.get(k) == v["$ne"]:
                            ok = False
                        if "$gte" in v and not (d.get(k) and d.get(k) >= v["$gte"]):
                            ok = False
                    elif d.get(k) != v:
                        ok = False
                if ok: out.append(d)
            docs = out
        return FakeCursor(docs)
    async def count_documents(self, q):
        cnt = 0
        for d in self.docs:
            ok = True
            for k, v in (q or {}).items():
                if isinstance(v, dict):
                    if "$gte" in v and not (d.get(k) and d.get(k) >= v["$gte"]):
                        ok = False
                elif d.get(k) != v:
                    ok = False
            if ok: cnt += 1
        return cnt
    async def distinct(self, field):
        return list({d.get(field) for d in self.docs if d.get(field)})
    async def create_index(self, *a, **kw):
        return None
    def aggregate(self, pipeline):
        # Tiny pipeline runner for $match → $group → $match
        docs = list(self.docs)
        for stage in pipeline:
            if "$match" in stage:
                m = stage["$match"]
                out = []
                for d in docs:
                    ok = True
                    for k, v in m.items():
                        dk = d
                        for part in k.split("."):
                            dk = dk.get(part) if isinstance(dk, dict) else None
                        if isinstance(v, dict):
                            if "$ne" in v and dk == v["$ne"]:
                                ok = False
                            if "$gte" in v and not (dk and dk >= v["$gte"]):
                                ok = False
                            if "$in" in v and dk not in v["$in"]:
                                ok = False
                        elif dk != v:
                            ok = False
                    if ok: out.append(d)
                docs = out
            elif "$group" in stage:
                gid = stage["$group"]["_id"]
                groups = {}
                for d in docs:
                    key_field = gid.lstrip("$") if isinstance(gid, str) else None
                    key = d.get(key_field) if key_field else None
                    g = groups.setdefault(key, {"_id": key, "count": 0, "items": set()})
                    for field, spec in stage["$group"].items():
                        if field == "_id": continue
                        if isinstance(spec, dict):
                            if "$sum" in spec:
                                g.setdefault(field, 0)
                                g[field] += 1 if spec["$sum"] == 1 else 1
                            if "$addToSet" in spec:
                                val = d
                                for part in spec["$addToSet"].lstrip("$").split("."):
                                    val = val.get(part) if isinstance(val, dict) else None
                                if val:
                                    g.setdefault(field, set())
                                    g[field].add(val)
                docs = []
                for g in groups.values():
                    for k, v in list(g.items()):
                        if isinstance(v, set): g[k] = list(v)
                    docs.append(g)
        return FakeCursor(docs)


class FakeDb:
    def __init__(self):
        self.collections = {}
    def __getitem__(self, name):
        self.collections.setdefault(name, FakeColl())
        return self.collections[name]
    def __getattr__(self, name):
        return self[name]


# ─────────────────────────────────────────────────────────────
# Drift Alerts (v2.5.0)
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_drift_scan_fires_reject_spike():
    from services import drift_alert_service as da
    db = FakeDb()
    now_iso = datetime.now(timezone.utc).isoformat()
    # 5 rejects of same customer = exactly the default threshold
    for _ in range(5):
        await db["learning_events_v2"].insert_one({
            "event_type": "suggestion_rejected",
            "domain": "sales_intake",
            "scope_type": "customer",
            "scope_value": "C-TEST-REJECT",
            "target": {"item_no": "WIDGET-A"},
            "created_at": now_iso,
        })
    result = await da.run_drift_scan(db=db)
    assert result["rules_fired"] >= 1
    # Verify alert was written
    alerts = db["learning_drift_alerts"].docs
    assert any(a["alert_type"] == "customer_reject_spike" for a in alerts)
    assert any(a["scope_value"] == "C-TEST-REJECT" for a in alerts)


@pytest.mark.asyncio
async def test_drift_alerts_are_idempotent():
    from services import drift_alert_service as da
    db = FakeDb()
    now_iso = datetime.now(timezone.utc).isoformat()
    for _ in range(5):
        await db["learning_events_v2"].insert_one({
            "event_type": "suggestion_rejected",
            "domain": "sales_intake",
            "scope_type": "customer",
            "scope_value": "C-TEST",
            "target": {"item_no": "X"},
            "created_at": now_iso,
        })
    await da.run_drift_scan(db=db)
    await da.run_drift_scan(db=db)
    # Should still only be 1 open alert
    open_alerts = [a for a in db["learning_drift_alerts"].docs if a["status"] == "open"]
    assert len(open_alerts) == 1


@pytest.mark.asyncio
async def test_drift_alerts_no_spurious_fires_when_below_threshold():
    from services import drift_alert_service as da
    db = FakeDb()
    now_iso = datetime.now(timezone.utc).isoformat()
    # Only 2 rejects — below the default min of 5
    for _ in range(2):
        await db["learning_events_v2"].insert_one({
            "event_type": "suggestion_rejected",
            "domain": "sales_intake",
            "scope_type": "customer",
            "scope_value": "C-QUIET",
            "target": {"item_no": "X"},
            "created_at": now_iso,
        })
    result = await da.run_drift_scan(db=db)
    assert result["rules_fired"] == 0


@pytest.mark.asyncio
async def test_acknowledge_alert_moves_to_acknowledged():
    from services import drift_alert_service as da
    db = FakeDb()
    await db["learning_drift_alerts"].insert_one({
        "id": "alert-1", "status": "open", "severity": "warn",
        "scope_type": "customer", "scope_value": "C-TEST",
        "alert_type": "x", "domain": "sales_intake",
    })
    res = await da.acknowledge_alert("alert-1", db=db)
    assert res.get("status") == "acknowledged"


# ─────────────────────────────────────────────────────────────
# U2 — Fingerprint Service (v2.5.1)
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_fingerprint_customer_from_patterns():
    from services.learning_core import fingerprint_service as fp
    db = FakeDb()
    await db.order_line_patterns.insert_one({
        "customer_no": "C-10250",
        "trigger_item_no": "C-9874",
        "associated_lines": [
            {"item_no": "OIPALLET", "description": "OI Pallet"},
            {"item_no": "OITIERSHEET", "description": "Tier Sheet"},
            {"item_no": "RETIRED-X", "description": "ignored", "retired": True},
        ],
    })
    result = await fp.build_fingerprint("customer", "C-10250", db=db)
    assert result["scope_type"] == "customer"
    assert result["scope_value"] == "C-10250"
    assert "oipallet" in result["tf"]
    assert "retired-x" not in result["tf"]
    assert result["source_count"] == 1


@pytest.mark.asyncio
async def test_build_fingerprint_vendor_from_posting_profile():
    from services.learning_core import fingerprint_service as fp
    db = FakeDb()
    await db.posting_pattern_analysis.insert_one({
        "vendor_no": "V-ACME",
        "vendor_name": "Acme Shipping Co",
        "top_items": [
            {"item_no": "FRT-STD", "description": "Standard Freight"},
            {"item_no": "FUEL", "description": "Fuel Surcharge"},
        ],
        "top_gl_accounts": [{"gl_account": "6100-20"}],
    })
    result = await fp.build_fingerprint("vendor", "V-ACME", db=db)
    assert result["scope_type"] == "vendor"
    assert "acme" in result["tf"]
    assert "shipping" in result["tf"]
    assert "frt-std" in result["tf"]


@pytest.mark.asyncio
async def test_find_similar_shared_math():
    from services.learning_core import fingerprint_service as fp
    db = FakeDb()
    # Seed two customer fingerprints
    await db["scope_fingerprints"].insert_one({
        "scope_type": "customer", "scope_value": "C-1",
        "token_count": 4, "tf": {"oipallet": 1, "oitiersheet": 1, "pallet": 1, "sheet": 1},
        "computed_at": "2026-04-18T00:00:00+00:00",
    })
    await db["scope_fingerprints"].insert_one({
        "scope_type": "customer", "scope_value": "C-2",
        "token_count": 2, "tf": {"box": 1, "tape": 1},
        "computed_at": "2026-04-18T00:00:00+00:00",
    })
    results = await fp.find_similar(
        ["oipallet", "pallet", "sheet"],
        scope_type="customer", top_k=3, exclude_scope_value="NEW", db=db,
    )
    assert len(results) == 1
    assert results[0]["scope_value"] == "C-1"
    assert results[0]["similarity"] > 0


@pytest.mark.asyncio
async def test_fingerprint_invalidate_ages_timestamp():
    from services.learning_core import fingerprint_service as fp
    db = FakeDb()
    await db["scope_fingerprints"].insert_one({
        "scope_type": "customer", "scope_value": "C-1",
        "computed_at": "2026-04-18T00:00:00+00:00",
    })
    await fp.invalidate("customer", "C-1", db=db)
    stored = await db["scope_fingerprints"].find_one(
        {"scope_type": "customer", "scope_value": "C-1"}, {"_id": 0},
    )
    assert stored["computed_at"] == "1970-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_fingerprint_rejects_unknown_scope_type():
    from services.learning_core import fingerprint_service as fp
    db = FakeDb()
    result = await fp.build_fingerprint("alien", "X", db=db)
    assert "error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
