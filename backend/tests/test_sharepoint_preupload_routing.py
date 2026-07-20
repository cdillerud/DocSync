import asyncio

from services import folder_routing_service
from services import po_resolution_service
from services import sharepoint_service as svc
import deps


class Result:
    def __init__(self, modified_count=0):
        self.modified_count = modified_count


class FakeDocuments:
    def __init__(self, record, events=None):
        self.record = dict(record)
        self.events = events if events is not None else []
        self.updates = []

    async def find_one(self, query, projection=None):
        if query.get("id") != self.record.get("id"):
            return None
        if not projection:
            return dict(self.record)
        return {
            key: self.record.get(key)
            for key, included in projection.items()
            if included and key != "_id"
        }

    async def update_one(self, query, update):
        values = dict(update.get("$set", {}))
        self.updates.append(values)
        if "routing_suggestion_snapshot" in values:
            self.events.append("snapshot")
        self.record.update(values)
        return Result(modified_count=1)


class FakeDB:
    def __init__(self, record, events=None):
        self.hub_documents = FakeDocuments(record, events=events)


def test_structured_po_prefers_clean_alphanumeric_po():
    doc = {
        "po_number_clean": "W118410",
        "po_number_extracted": "6333386",
        "normalized_fields": {"po_number": "507240"},
        "extracted_fields": {
            "po_number": "W118410",
            "invoice_number": "6333386",
        },
    }

    assert svc._structured_po_number(doc) == "W118410"


def test_prepare_routing_document_resolves_structured_po_before_routing(monkeypatch):
    record = {
        "id": "ball-doc",
        "file_name": "507240_6333386_2026-07-18.pdf",
        "document_type": "AP_Invoice",
        "vendor_canonical": "BALLCOR",
        "extracted_fields": {
            "vendor": "BALL METAL BEVERAGE CONTAINER CORP",
            "po_number": "W118410",
            "invoice_number": "6333386",
        },
    }
    db = FakeDB(record)
    captured = {}

    async def fake_resolve(doc):
        captured["po_number_clean"] = doc.get("po_number_clean")
        captured["extracted_po"] = (doc.get("extracted_fields") or {}).get("po_number")
        return {
            "status": "resolved",
            "po_number": "W118410",
            "miss_reason": None,
            "candidates_raw": ["W118410", "507240", "6333386"],
            "best_match": {
                "bc_document_no": "W118410",
                "location_code": "00",
            },
        }

    monkeypatch.setattr(deps, "get_db", lambda: db)
    monkeypatch.setattr(po_resolution_service, "resolve_po_from_document", fake_resolve)

    prepared, returned_db, result = asyncio.run(svc._prepare_routing_document(record))

    assert returned_db is db
    assert result["status"] == "resolved"
    assert captured == {
        "po_number_clean": "W118410",
        "extracted_po": "W118410",
    }
    assert prepared["bc_po_resolved"] is True
    assert prepared["resolved_location_code"] == "00"
    assert db.hub_documents.record["po_candidates"][0] == "W118410"


def test_snapshot_is_persisted_before_sharepoint_upload(monkeypatch):
    events = []
    doc = {
        "id": "ball-doc",
        "file_name": "ball.pdf",
        "document_type": "AP_Invoice",
        "vendor_canonical": "BALLCOR",
        "vendor_raw": "BALL METAL BEVERAGE CONTAINER CORP",
        "po_number_clean": "W118410",
        "invoice_number_clean": "6333386",
        "invoice_date": "2026-07-18",
        "extracted_fields": {
            "vendor": "BALL METAL BEVERAGE CONTAINER CORP",
            "po_number": "W118410",
            "invoice_number": "6333386",
        },
    }
    db = FakeDB(doc, events=events)

    async def fake_prepare(supplied):
        prepared = dict(supplied)
        prepared["bc_po_resolved"] = True
        return prepared, db, {"status": "resolved", "po_number": "W118410"}

    async def fake_route(*args, **kwargs):
        return (
            "Warehouse Not International",
            "Learned from feedback (vendor=BALLCOR, type=AP_Invoice)",
            {
                "source": "feedback_loop",
                "vendor": "BALLCOR",
                "order_number": "W118410",
            },
        )

    async def fake_ensure(folder):
        events.append("ensure_folder")
        return True

    async def fake_upload(content, name, folder):
        events.append("upload")
        return {
            "drive_id": "drive-1",
            "item_id": "item-1",
            "web_url": "https://example.test/file",
            "name": name,
        }

    monkeypatch.setattr(svc, "_prepare_routing_document", fake_prepare)
    monkeypatch.setattr(folder_routing_service, "route_with_feedback", fake_route)
    monkeypatch.setattr(svc, "ensure_sharepoint_folder_exists", fake_ensure)
    monkeypatch.setattr(svc, "upload_to_sharepoint", fake_upload)
    monkeypatch.setattr(svc, "SHAREPOINT_BASE_FOLDER", "")

    result = asyncio.run(svc.upload_to_sharepoint_with_routing(
        b"pdf-content",
        "ball.pdf",
        doc,
    ))

    assert events.index("snapshot") < events.index("upload")
    assert result["folder_path"] == "/Warehouse Not International"
    assert result["routing_snapshot"]["capture_type"] == "pre_filing_routing"
    assert result["routing_snapshot"]["source"] == "feedback_loop"
    assert db.hub_documents.record["initial_suggested_folder"] == "Warehouse Not International"
    assert db.hub_documents.record["initial_routing_source"] == "feedback_loop"
