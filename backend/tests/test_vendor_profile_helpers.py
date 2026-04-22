"""
Tests for services.vendor_profile_helpers — extracted from server.py
─────────────────────────────────────────────────────────────────────

Validates the Orchestration Extraction (v2.5.2, option A) pass:
  • update_vendor_profile_incremental is self-contained
  • normalizes vendor names consistently
  • correctly increments counters, computes rates, flags stable vendors
  • the server.py compat wrapper still delegates properly
"""

import pytest


class FakeColl:
    def __init__(self):
        self.docs = []
    async def find_one_and_update(self, q, update, upsert=False, return_document=False):
        # Simple fake: find match by normalized key, apply $inc/$set/$setOnInsert/$addToSet
        doc = None
        idx = None
        for i, d in enumerate(self.docs):
            if all(d.get(k) == v for k, v in q.items()):
                doc = d; idx = i; break
        if not doc:
            if not upsert:
                return None
            doc = {**q}
            self.docs.append(doc)
            idx = len(self.docs) - 1
        for k, v in update.get("$setOnInsert", {}).items():
            doc.setdefault(k, v)
        for k, v in update.get("$inc", {}).items():
            doc[k] = doc.get(k, 0) + v
        for k, v in update.get("$set", {}).items():
            doc[k] = v
        for k, v in update.get("$addToSet", {}).items():
            arr = doc.setdefault(k, [])
            if v not in arr:
                arr.append(v)
        self.docs[idx] = doc
        return dict(doc) if return_document else None
    async def update_one(self, q, update, **kw):
        for i, d in enumerate(self.docs):
            if all(d.get(k) == v for k, v in q.items()):
                for k, v in update.get("$set", {}).items():
                    d[k] = v
                return type("R", (), {"matched_count": 1, "modified_count": 1})()
        return type("R", (), {"matched_count": 0, "modified_count": 0})()
    async def find_one(self, q, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return dict(d)
        return None


class FakeDb:
    def __init__(self):
        self.collections = {}
    def __getattr__(self, name):
        if name.startswith("_") or name == "collections":
            raise AttributeError(name)
        self.collections.setdefault(name, FakeColl())
        return self.collections[name]


@pytest.mark.asyncio
async def test_noop_on_empty_vendor_name():
    from workflows.ap_invoice.rules.vendor_profile import update_vendor_profile_incremental
    db = FakeDb()
    await update_vendor_profile_incremental(db, "doc-1", "", {}, "completed")
    assert db.vendor_intelligence_profiles.docs == []


@pytest.mark.asyncio
async def test_creates_new_profile_with_counters():
    from workflows.ap_invoice.rules.vendor_profile import update_vendor_profile_incremental
    db = FakeDb()
    await update_vendor_profile_incremental(
        db, "doc-1", "Acme Supplies Inc.",
        {"auto_cleared": True, "vendor_canonical": "ACME SUPPLIES", "validation_results": {"all_passed": True}},
        "Completed",
    )
    docs = db.vendor_intelligence_profiles.docs
    assert len(docs) == 1
    p = docs[0]
    assert p["vendor_name"] == "Acme Supplies Inc."
    assert p["vendor_name_normalized"] == "acme supplies"
    assert p["invoice_count"] == 1
    assert p["automation_success_count"] == 1
    assert p["validation_pass_count"] == 1
    assert p["resolution_success_count"] == 1
    assert p["automation_success_rate"] == 1.0
    assert p["validation_pass_rate"] == 1.0
    assert p["stable_vendor_flag"] is False  # Only 1 invoice — below the 10 threshold
    assert "Acme Supplies Inc." in p["name_variants"]


@pytest.mark.asyncio
async def test_increments_existing_profile():
    from workflows.ap_invoice.rules.vendor_profile import update_vendor_profile_incremental
    db = FakeDb()
    for i in range(3):
        await update_vendor_profile_incremental(
            db, f"doc-{i}", "Acme Supplies Inc.",
            {"auto_cleared": True, "vendor_canonical": "ACME SUPPLIES"},
            "ValidationPassed",
        )
    docs = db.vendor_intelligence_profiles.docs
    assert len(docs) == 1
    p = docs[0]
    assert p["invoice_count"] == 3
    assert p["automation_success_count"] == 3
    assert p["validation_pass_count"] == 3
    assert p["resolution_success_count"] == 3


@pytest.mark.asyncio
async def test_flags_stable_vendor_after_threshold():
    """>=10 invoices + high rates → is_stable=True."""
    from workflows.ap_invoice.rules.vendor_profile import update_vendor_profile_incremental
    db = FakeDb()
    for i in range(12):
        await update_vendor_profile_incremental(
            db, f"doc-{i}", "Globex Corp",
            {"auto_cleared": True, "vendor_canonical": "GLOBEX",
             "validation_results": {"all_passed": True}},
            "Posted",
        )
    p = db.vendor_intelligence_profiles.docs[0]
    assert p["invoice_count"] == 12
    assert p["automation_success_rate"] == 1.0
    assert p["validation_pass_rate"] == 1.0
    assert p["stable_vendor_flag"] is True
    assert 0 < p["stable_vendor_score"] <= 1.0


@pytest.mark.asyncio
async def test_server_compat_wrapper_delegates():
    """The server.py compatibility wrapper must still work so legacy
    callers inside server.py that reference _update_vendor_profile_incremental
    do not break during the dual-path window."""
    # Import from server via the wrapper — smoke test only
    import importlib
    import sys

    # Force a clean import of server to validate the compat wrapper's shape
    if "server" in sys.modules:
        srv = sys.modules["server"]
    else:
        srv = importlib.import_module("server")

    assert hasattr(srv, "_update_vendor_profile_incremental")
    assert callable(srv._update_vendor_profile_incremental)

    db = FakeDb()
    await srv._update_vendor_profile_incremental(
        db, "doc-X", "WrapperTest LLC",
        {"auto_cleared": False, "vendor_canonical": "WRAPPERTEST"},
        "Completed",
    )
    docs = db.vendor_intelligence_profiles.docs
    assert len(docs) == 1
    assert docs[0]["vendor_name_normalized"] == "wrappertest"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
