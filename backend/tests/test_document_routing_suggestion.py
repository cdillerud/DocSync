from types import SimpleNamespace

import pytest

import deps
import services.folder_routing_service as folder_routing_service
from services.document_routing_service import route_document


class FakeCollection:
    def __init__(self, document=None):
        self.document = document
        self.update_calls = []

    async def find_one(self, query, projection=None):
        return dict(self.document) if self.document else None

    async def update_one(self, query, update):
        self.update_calls.append((query, update))
        is_guarded_snapshot_write = "$or" in query
        existing_snapshot = (self.document or {}).get("routing_suggestion_snapshot")
        if is_guarded_snapshot_write and existing_snapshot:
            return SimpleNamespace(modified_count=0)

        if self.document is not None:
            self.document.update(update.get("$set", {}))
        return SimpleNamespace(modified_count=1)


class FakeDB:
    def __init__(self, document, intelligence=None):
        self.hub_documents = FakeCollection(document)
        self.document_intelligence_results = FakeCollection(intelligence)


@pytest.mark.asyncio
async def test_route_document_persists_initial_folder_suggestion(monkeypatch):
    document = {
        "id": "doc-1",
        "file_name": "freight.pdf",
        "suggested_job_type": "AP_Invoice",
        "ai_confidence": 0.99,
        "vendor_canonical": "R+L Carriers, Inc.",
        "extracted_fields": {
            "vendor": "R+L Carriers, Inc.",
            "invoice_number": "INV-1",
            "invoice_date": "2026-07-20",
            "total_amount": "125.00",
            "po_number": "PO12345",
        },
        "validation_results": {"all_passed": True, "checks": []},
    }
    db = FakeDB(document)
    monkeypatch.setattr(deps, "get_db", lambda: db)

    async def fake_route_with_feedback(**kwargs):
        return (
            "Freight Issues",
            "Freight invoice from carrier",
            {"source": "folder_routing_service", "rule": "freight_vendor"},
        )

    monkeypatch.setattr(
        folder_routing_service,
        "route_with_feedback",
        fake_route_with_feedback,
    )

    result = await route_document("doc-1")

    assert result["suggested_folder"] == "Freight Issues"
    assert result["suggestion_persisted"] is True
    snapshot = db.hub_documents.document["routing_suggestion_snapshot"]
    assert snapshot["folder_path"] == "Freight Issues"
    assert snapshot["reason"] == "Freight invoice from carrier"
    assert snapshot["capture_type"] == "pre_filing_routing"
    assert db.hub_documents.document["initial_suggested_folder"] == "Freight Issues"


@pytest.mark.asyncio
async def test_route_document_never_overwrites_existing_snapshot(monkeypatch):
    original_snapshot = {
        "folder_path": "Warehouse Not International",
        "reason": "Original warehouse evidence",
        "source": "folder_routing_service",
        "suggested_at": "2026-07-20T01:00:00+00:00",
        "capture_type": "pre_filing_routing",
    }
    document = {
        "id": "doc-2",
        "file_name": "ball.pdf",
        "suggested_job_type": "AP_Invoice",
        "ai_confidence": 0.99,
        "vendor_canonical": "Ball Corp",
        "extracted_fields": {
            "vendor": "Ball Corp",
            "invoice_number": "INV-2",
            "invoice_date": "2026-07-20",
            "total_amount": "250.00",
            "po_number": "PO99999",
        },
        "validation_results": {"all_passed": True, "checks": []},
        "routing_suggestion_snapshot": dict(original_snapshot),
    }
    db = FakeDB(document)
    monkeypatch.setattr(deps, "get_db", lambda: db)

    async def changed_route_with_feedback(**kwargs):
        return (
            "Dropship Not International",
            "Current rule changed",
            {"source": "folder_routing_service"},
        )

    monkeypatch.setattr(
        folder_routing_service,
        "route_with_feedback",
        changed_route_with_feedback,
    )

    result = await route_document("doc-2")

    assert result["suggestion_persisted"] is False
    assert db.hub_documents.document["routing_suggestion_snapshot"] == original_snapshot
