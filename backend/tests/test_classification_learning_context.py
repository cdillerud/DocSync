# Tests for the shared learning-signal prompt enrichment used by both the
# on-demand classification pipeline (classification_pipeline.stage_classify_llm)
# and the live intake path (document_intel_helpers._call_llm_for_extraction).

from __future__ import annotations

import pytest


async def _fake_get_db():
    return "FAKE_DB"


@pytest.mark.asyncio
async def test_known_vendor_gets_every_injection(monkeypatch):
    from services import classification_learning_context as ctx
    from services import (
        vendor_extraction_profile_service,
        classification_feedback_service,
        feedback_loop_service,
        vendor_context_builder,
        deep_learning_engine,
        advanced_learning_engine,
    )
    import deps

    class FakeVEP:
        async def get_profile(self, vendor):
            assert vendor == "ACME"
            return {
                "enabled": True,
                "reference_priority_order": ["top-right header"],
                "document_type_bias": "AP_Invoice",
                "reference_label_bias": {"Reference": {"target_label": "PO Number"}},
            }

    monkeypatch.setattr(vendor_extraction_profile_service, "get_vep_service", lambda: FakeVEP())

    async def fake_few_shot(vendor_no=""):
        return "== FEW-SHOT EXAMPLES ==" if vendor_no == "ACME" else ""

    async def fake_vendor_hints(vendor_name):
        # Only the full name has a hint on file, not the short code -- proves
        # the vendor_id-first-then-vendor_name fallback actually falls back,
        # not just that some hint happens to fire.
        return f"Vendor '{vendor_name}' hint" if vendor_name == "Acme Corp" else ""

    monkeypatch.setattr(classification_feedback_service, "build_few_shot_prompt_section", fake_few_shot)
    monkeypatch.setattr(classification_feedback_service, "build_vendor_hints_prompt_section", fake_vendor_hints)

    async def fake_feedback_context(db, vendor_id="", doc_type=""):
        return f"feedback:{vendor_id}:{doc_type}" if vendor_id else ""

    monkeypatch.setattr(feedback_loop_service, "build_feedback_context_for_prompt", fake_feedback_context)

    async def fake_classification_context(db, vendor_no="", vendor_name="", sender_email=""):
        return f"bc_intel:{vendor_no}:{sender_email}" if vendor_name else ""

    async def fake_amount_context(db, vendor):
        return f"amount_intel:{vendor}" if vendor else ""

    monkeypatch.setattr(vendor_context_builder, "build_classification_context", fake_classification_context)
    monkeypatch.setattr(vendor_context_builder, "build_amount_intelligence_context", fake_amount_context)

    async def fake_extraction_hints(db, vendor):
        return {"reliable_fields": ["vendor"], "expected_fields": ["po_number"]}

    monkeypatch.setattr(deep_learning_engine, "get_extraction_hints_for_vendor", fake_extraction_hints)

    async def fake_field_predictions(db, pred_doc):
        return [{"feature": "has_po", "predicted_type": "AP_Invoice", "confidence": 0.9, "samples": 10}]

    monkeypatch.setattr(advanced_learning_engine, "get_field_predictions", fake_field_predictions)
    monkeypatch.setattr(deps, "get_db", lambda: "FAKE_DB")

    prompt, profile_used = await ctx.build_learning_enriched_prompt(
        "BASE",
        doc={
            "vendor_no": "ACME",
            "vendor_canonical": "Acme Corp",
            "suggested_job_type": "AP_Invoice",
            "email_sender": "billing@acme.com",
            "extracted_fields": {"invoice_number": "INV-1"},
        },
    )

    assert profile_used is True
    for expected in (
        "VENDOR EXTRACTION PROFILE", "top-right header",
        "FEW-SHOT EXAMPLES", "Vendor 'Acme Corp' hint",
        "feedback:ACME:AP_Invoice", "bc_intel:ACME:billing@acme.com",
        "LEARNED EXTRACTION PATTERNS", "amount_intel:ACME",
        "FIELD CORRELATION PREDICTIONS",
    ):
        assert expected in prompt, f"missing {expected!r} in enriched prompt"


@pytest.mark.asyncio
async def test_no_context_leaves_prompt_unchanged():
    from services.classification_learning_context import build_learning_enriched_prompt

    prompt, profile_used = await build_learning_enriched_prompt("BASE", doc=None)

    assert prompt == "BASE"
    assert profile_used is False


@pytest.mark.asyncio
async def test_one_source_failing_does_not_block_others(monkeypatch):
    from services import classification_learning_context as ctx
    from services import vendor_extraction_profile_service, feedback_loop_service

    class FakeVEP:
        async def get_profile(self, vendor):
            return {"enabled": True, "document_type_bias": "AP_Invoice"}

    monkeypatch.setattr(vendor_extraction_profile_service, "get_vep_service", lambda: FakeVEP())

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated outage")

    monkeypatch.setattr(feedback_loop_service, "build_feedback_context_for_prompt", boom)

    prompt, profile_used = await ctx.build_learning_enriched_prompt(
        "BASE", doc={"vendor_no": "ACME"},
    )

    assert profile_used is True
    assert "VENDOR EXTRACTION PROFILE" in prompt


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, n):
        return self._docs[:n]


class _FakeEventsCollection:
    def __init__(self):
        self.inserted = []

    async def insert_one(self, doc):
        self.inserted.append(doc)

    def find(self, query, projection=None):
        return _FakeCursor(list(self.inserted))


class _FakeDB:
    def __init__(self):
        self.learning_injection_events = _FakeEventsCollection()


@pytest.mark.asyncio
async def test_injection_event_recorded_and_summarized(monkeypatch):
    """The self-instrumentation added after the VEP bug: every call records
    which sources fired/were empty/errored, and the summary aggregates it.
    This is the mechanism meant to catch the next silent-no-op bug in days,
    not the ~6 months VEP went undetected."""
    from services import classification_learning_context as ctx
    from services import vendor_extraction_profile_service, feedback_loop_service
    import deps

    fake_db = _FakeDB()
    monkeypatch.setattr(deps, "get_db", lambda: fake_db)
    monkeypatch.setattr(vendor_extraction_profile_service, "get_vep_service", lambda: None)

    async def boom(*a, **kw):
        raise RuntimeError("simulated outage")

    monkeypatch.setattr(feedback_loop_service, "build_feedback_context_for_prompt", boom)

    await ctx.build_learning_enriched_prompt(
        "BASE", doc={"vendor_no": "ACME"}, log_prefix="TESTPATH",
    )

    assert len(fake_db.learning_injection_events.inserted) == 1
    event = fake_db.learning_injection_events.inserted[0]
    assert event["log_prefix"] == "TESTPATH"
    assert event["vendor"] == "ACME"
    assert event["sources"]["vep"] == "empty"  # get_vep_service() returned None
    assert event["sources"]["feedback_loop"] == "error:RuntimeError"

    summary = await ctx.get_injection_health_summary(hours=24)
    assert summary["total_events"] == 1
    assert summary["sources"]["vep"]["empty"] == 1
    assert summary["sources"]["vep"]["fired_rate"] == 0.0
    assert summary["sources"]["feedback_loop"]["error"] == 1
    assert summary["sources"]["feedback_loop"]["sample_error"] == "error:RuntimeError"
