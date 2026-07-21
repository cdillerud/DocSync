from typing import Any, Dict, Optional

import pytest


class StaticCollection:
    def __init__(self, value=None):
        self.value = value
        self.inserted = []
        self.updated = []

    async def find_one(self, query, projection=None):
        return dict(self.value) if self.value else None

    async def insert_one(self, value):
        self.inserted.append(value)

    async def update_one(self, query, update):
        self.updated.append((query, update))


class HistoryDocuments:
    def __init__(self, canonical=None, extracted=None):
        self.canonical = canonical
        self.extracted = extracted

    async def find_one(self, query, projection=None):
        if "vendor_canonical" in query:
            return dict(self.canonical) if self.canonical else None
        return dict(self.extracted) if self.extracted else None


def test_strict_identity_rejects_generic_packaging_overlap():
    from services.vendor_name_helpers import vendor_identity_agrees

    assert vendor_identity_agrees(
        "O-I PACKAGING SOLUTIONS LLC",
        "Gamer Packaging, Inc.",
    ) is False

    assert vendor_identity_agrees(
        "Cargo Modules, LLC",
        "CARGOMO",
    ) is True

    assert vendor_identity_agrees(
        "BALL METAL BEVERAGE CONTAINER CORP",
        "Ball Corp",
    ) is True


@pytest.mark.asyncio
async def test_sender_guard_recovers_extracted_vendor_from_document(monkeypatch):
    import services.vendor_matching as matching

    class FakeDB:
        hub_documents = StaticCollection({
            "normalized_fields": {
                "vendor": "O-I PACKAGING SOLUTIONS LLC",
            },
        })
        sender_vendor_map = StaticCollection({
            "sender_email": "invoice@example.test",
            "vendor_canonical": "VIT1",
            "vendor_name": "Gamer Packaging, Inc.",
            "vendor_no": "VIT1",
        })
        workflow_events = StaticCollection()

    db = FakeDB()
    monkeypatch.setattr(matching, "get_db", lambda: db)
    monkeypatch.setenv("SENDER_STAMP_GUARD_ENABLED", "true")

    result = await matching.lookup_vendor_by_sender(
        "invoice@example.test",
        document_id="doc-oi",
    )

    assert result["vendor_canonical"] is None
    assert result["vendor_match_method"] == "sender_disagreed"
    assert result["sender_hint"]["extracted_vendor"] == (
        "O-I PACKAGING SOLUTIONS LLC"
    )
    assert len(db.workflow_events.inserted) == 1


@pytest.mark.asyncio
async def test_document_history_rejects_poisoned_oi_record():
    from services.unified_vendor_matcher import UnifiedVendorMatcher

    poisoned = {
        "vendor_canonical": "Gamer Packaging, Inc.",
        "bc_vendor_number": "VIT1",
        "extracted_fields": {
            "vendor": "O-I PACKAGING SOLUTIONS LLC",
        },
        "routing_details": {
            "validation_results": {
                "bc_record_info": {
                    "displayName": "Gamer Packaging, Inc.",
                    "number": "VIT1",
                },
            },
        },
    }

    class FakeDB:
        hub_documents = HistoryDocuments(extracted=poisoned)
        vendor_matches = StaticCollection()

    matcher = object.__new__(UnifiedVendorMatcher)
    matcher.db = FakeDB()

    result = await matcher._match_from_document_history(
        "O-I PACKAGING SOLUTIONS LLC",
        "oi packaging solutions",
    )

    assert result is None


@pytest.mark.asyncio
async def test_document_history_accepts_agreeing_ball_record():
    from services.unified_vendor_matcher import UnifiedVendorMatcher

    valid = {
        "vendor_canonical": "BALLCOR",
        "bc_vendor_number": "BALLCOR",
        "extracted_fields": {
            "vendor": "BALL METAL BEVERAGE CONTAINER CORP",
        },
        "routing_details": {
            "validation_results": {
                "bc_record_info": {
                    "displayName": "Ball Corp",
                    "number": "BALLCOR",
                },
            },
        },
    }

    class FakeDB:
        hub_documents = HistoryDocuments(extracted=valid)
        vendor_matches = StaticCollection()

    matcher = object.__new__(UnifiedVendorMatcher)
    matcher.db = FakeDB()

    result = await matcher._match_from_document_history(
        "BALL METAL BEVERAGE CONTAINER CORP",
        "ball metal beverage container",
    )

    assert result is not None
    assert result["name"] == "Ball Corp"
    assert result["vendor_number"] == "BALLCOR"
    assert result["method"] == "document_history_extracted_agreement"


@pytest.mark.asyncio
async def test_vendor_match_cache_rejects_conflicting_identity():
    from services.unified_vendor_matcher import UnifiedVendorMatcher

    class FakeDB:
        hub_documents = HistoryDocuments()
        vendor_matches = StaticCollection({
            "input_normalized": "oi packaging solutions",
            "matched_name": "Gamer Packaging, Inc.",
            "bc_vendor_number": "VIT1",
            "score": 1.0,
        })

    matcher = object.__new__(UnifiedVendorMatcher)
    matcher.db = FakeDB()

    result = await matcher._match_from_document_history(
        "O-I PACKAGING SOLUTIONS LLC",
        "oi packaging solutions",
    )

    assert result is None
