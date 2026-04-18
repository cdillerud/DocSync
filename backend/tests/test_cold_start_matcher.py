"""
Tests for cold_start_matcher_service — the v2.4.0 peer-matching engine.

Covers:
  • Tokenization handles SKU-style tokens, drops stopwords, keeps SKU prefixes
  • Fingerprint build produces TF + unique counts
  • find_similar_customers returns the closest known customer
  • find_similar_customers excludes the target itself
  • find_similar_customers returns empty when no fingerprints exist
  • promote_inherited_suggestion seeds a fresh pattern for a cold customer
  • promote_inherited_suggestion handles already-present line
"""

import pytest
import uuid
from datetime import datetime, timezone


# ─────────────────────────────────────────────────────────────
# Fake DB (reuses the shape from test_intake_learning_feedback)
# ─────────────────────────────────────────────────────────────

class FakeCursor:
    def __init__(self, docs): self._docs = list(docs)
    def __aiter__(self): return self
    async def __anext__(self):
        if not self._docs: raise StopAsyncIteration
        return self._docs.pop(0)
    def sort(self, *a, **kw): return self
    def limit(self, n): return self
    async def to_list(self, n):
        out = list(self._docs); self._docs = []
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
        return None
    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items() if not isinstance(v, dict)):
                if "$set" in upd:
                    d.update(upd["$set"])
                return
        if upsert:
            new_doc = dict(q)
            if "$set" in upd:
                new_doc.update(upd["$set"])
            self.docs.append(new_doc)
    def find(self, q=None, proj=None):
        docs = list(self.docs)
        if q:
            # Very simple filter
            filtered = []
            for d in docs:
                ok = True
                for k, v in q.items():
                    if isinstance(v, dict):
                        if "$gt" in v and not (d.get(k, 0) > v["$gt"]):
                            ok = False; break
                        if "$ne" in v and d.get(k) == v["$ne"]:
                            ok = False; break
                    elif d.get(k) != v:
                        ok = False; break
                if ok: filtered.append(d)
            docs = filtered
        return FakeCursor(docs)
    async def count_documents(self, q):
        return len(self.docs)
    async def distinct(self, field):
        return list({d.get(field) for d in self.docs if d.get(field) is not None})


class FakeDb:
    def __init__(self):
        self.order_line_patterns = FakeColl()
        self.intake_customer_fingerprints = FakeColl()
        self.intake_learning_events = FakeColl()
        self._extra_colls = {}
    def __getitem__(self, name):
        if hasattr(self, name) and name != "_extra_colls":
            return getattr(self, name)
        if name not in self._extra_colls:
            self._extra_colls[name] = FakeColl()
        return self._extra_colls[name]


# ─────────────────────────────────────────────────────────────
# Tokenizer
# ─────────────────────────────────────────────────────────────

def test_tokenize_preserves_sku_style():
    from services.cold_start_matcher_service import tokenize
    toks = tokenize("OI Pallet - RETURN REQUIRED · C-9874-10001833")
    assert "c-9874-10001833" in toks
    assert "pallet" in toks
    assert "required" not in toks       # stopword
    assert "return" not in toks         # stopword
    assert "oi" not in toks             # stopword


def test_tokenize_drops_pure_numbers_and_short_tokens():
    from services.cold_start_matcher_service import tokenize
    toks = tokenize("24oz 123 A widget")
    assert "123" not in toks
    assert "a" not in toks
    assert "24oz" in toks
    assert "widget" in toks


# ─────────────────────────────────────────────────────────────
# Fingerprint
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_fingerprint_counts_tokens():
    from services import cold_start_matcher_service as cs
    db = FakeDb()
    db.order_line_patterns.docs.append({
        "customer_no": "C-10250",
        "trigger_item_no": "C-9874",
        "associated_lines": [
            {"item_no": "OIPALLET", "description": "OI Pallet"},
            {"item_no": "OITIERSHEET", "description": "OI Tier Sheet"},
            {"item_no": "RETIRED-THING", "description": "ignored", "retired": True},
        ],
    })
    fp = await cs.build_fingerprint("C-10250", db=db)
    # tokens: c-9874, oipallet, pallet, oitiersheet, tier, sheet (retired row excluded)
    assert fp["token_count"] >= 5
    assert "oipallet" in fp["tf"]
    assert "retired-thing" not in fp["tf"]   # retired lines are skipped
    assert fp["pattern_count"] == 1


# ─────────────────────────────────────────────────────────────
# find_similar_customers
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_similar_returns_best_peer():
    from services import cold_start_matcher_service as cs
    db = FakeDb()
    # Giovanni — OI-family packaging
    db.order_line_patterns.docs.append({
        "customer_no": "C-10250",
        "trigger_item_no": "C-9874",
        "associated_lines": [
            {"item_no": "OIPALLET", "description": "OI Pallet"},
            {"item_no": "OITIERSHEET", "description": "OI Tier Sheet"},
            {"item_no": "OITOPFRAME", "description": "OI Top Frame"},
        ],
    })
    # Unrelated customer — corrugated boxes
    db.order_line_patterns.docs.append({
        "customer_no": "C-99999",
        "trigger_item_no": "BOX-1",
        "associated_lines": [
            {"item_no": "CORRUGATED-BOX", "description": "Corrugated Shipper"},
            {"item_no": "KRAFT-TAPE", "description": "Kraft Tape"},
        ],
    })
    await cs.build_fingerprint("C-10250", db=db)
    await cs.build_fingerprint("C-99999", db=db)

    # Cold-start inbound with OI-family items → should match Giovanni
    line_items = [
        {"item_no": "OIPALLET", "description": "OI Pallet RETURN"},
        {"item_no": "OITIERSHEET", "description": "OI Tier Sheet"},
    ]
    results = await cs.find_similar_customers(
        line_items, top_k=3, exclude_customer_no="NEW-COLD", db=db,
    )
    assert len(results) >= 1
    assert results[0]["customer_no"] == "C-10250"
    assert results[0]["similarity"] > 0.20
    assert "oipallet" in results[0]["matched_tokens"]
    # Inherited suggestions should include OITOPFRAME even though it wasn't
    # in the query — that's the whole point of cold-start inheritance
    items = [s["item_no"] for s in results[0]["inherited_suggestions"]]
    assert "OITOPFRAME" in items


@pytest.mark.asyncio
async def test_find_similar_excludes_target():
    from services import cold_start_matcher_service as cs
    db = FakeDb()
    db.order_line_patterns.docs.append({
        "customer_no": "C-10250",
        "trigger_item_no": "C-9874",
        "associated_lines": [{"item_no": "OIPALLET", "description": "OI Pallet"}],
    })
    await cs.build_fingerprint("C-10250", db=db)
    results = await cs.find_similar_customers(
        [{"item_no": "OIPALLET", "description": "OI Pallet"}],
        top_k=3, exclude_customer_no="C-10250", db=db,
    )
    assert results == []


@pytest.mark.asyncio
async def test_find_similar_no_fingerprints_returns_empty():
    from services import cold_start_matcher_service as cs
    db = FakeDb()
    results = await cs.find_similar_customers(
        [{"item_no": "OIPALLET", "description": "OI Pallet"}], db=db,
    )
    assert results == []


@pytest.mark.asyncio
async def test_find_similar_short_query_returns_empty():
    from services import cold_start_matcher_service as cs
    db = FakeDb()
    db.order_line_patterns.docs.append({
        "customer_no": "C-10250", "trigger_item_no": "X",
        "associated_lines": [{"item_no": "A", "description": "B"}],
    })
    await cs.build_fingerprint("C-10250", db=db)
    # Only 1 tiny token → below MIN_TOKENS_IN_QUERY
    results = await cs.find_similar_customers(
        [{"item_no": "xx", "description": ""}], db=db,
    )
    assert results == []


# ─────────────────────────────────────────────────────────────
# Promotion
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_promote_creates_new_pattern_for_cold_customer():
    from services import cold_start_matcher_service as cs
    db = FakeDb()
    # Source: Giovanni
    db.order_line_patterns.docs.append({
        "customer_no": "C-10250",
        "trigger_item_no": "C-9874",
        "associated_lines": [
            {"item_no": "OIPALLET", "description": "OI Pallet", "quantity": 20, "frequency": 1.0, "occurrences": 15},
        ],
    })
    # Target: brand new customer, zero patterns
    result = await cs.promote_inherited_suggestion(
        target_customer_no="C-NEW-001",
        source_customer_no="C-10250",
        item_no="OIPALLET",
        trigger_item="C-9874",
        db=db,
    )
    assert result["action"] == "promoted"
    # New pattern should now exist for C-NEW-001
    new_patterns = [d for d in db.order_line_patterns.docs if d["customer_no"] == "C-NEW-001"]
    assert len(new_patterns) == 1
    lines = new_patterns[0]["associated_lines"]
    assert len(lines) == 1
    assert lines[0]["item_no"] == "OIPALLET"
    assert lines[0]["inherited_from"] == "C-10250"
    # Audit event recorded
    evts = db.intake_learning_events.docs
    assert any(e["event_type"] == "inherited_suggestion_promoted" for e in evts)


@pytest.mark.asyncio
async def test_promote_returns_already_present_on_duplicate():
    from services import cold_start_matcher_service as cs
    db = FakeDb()
    db.order_line_patterns.docs.append({
        "customer_no": "C-10250",
        "trigger_item_no": "C-9874",
        "associated_lines": [{"item_no": "OIPALLET", "description": "OI Pallet", "frequency": 1.0, "occurrences": 15}],
    })
    db.order_line_patterns.docs.append({
        "customer_no": "C-NEW-001",
        "trigger_item_no": "C-9874",
        "associated_lines": [{"item_no": "OIPALLET"}],
    })
    result = await cs.promote_inherited_suggestion(
        target_customer_no="C-NEW-001",
        source_customer_no="C-10250",
        item_no="OIPALLET",
        trigger_item="C-9874",
        db=db,
    )
    assert result["action"] == "already_present"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
