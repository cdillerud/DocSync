import io

import pytest
from pypdf import PdfWriter

import services.batch_po_splitter as splitter
import services.document_bytes_intake_service as intake_service


class _Collection:
    def __init__(self, docs):
        self.docs = {doc["id"]: dict(doc) for doc in docs}

    async def find_one(self, query, projection=None, **kwargs):
        if "id" in query:
            doc = self.docs.get(query["id"])
            return dict(doc) if doc else None
        if "sha256_hash" in query:
            wanted = query["sha256_hash"]
            for doc in self.docs.values():
                if doc.get("sha256_hash") == wanted and not doc.get("is_duplicate"):
                    return dict(doc)
        return None

    async def update_one(self, query, update):
        doc = self.docs[query["id"]]
        for key, value in update.get("$set", {}).items():
            doc[key] = value
        for key, value in update.get("$addToSet", {}).items():
            values = doc.setdefault(key, [])
            if value not in values:
                values.append(value)


class _DB:
    def __init__(self):
        self.hub_documents = _Collection([
            {
                "id": "parent-1234567890",
                "document_type": "AP_Invoice",
                "mailbox_category": "AP",
                "vendor_canonical": "Vendor A",
            }
        ])


def _two_page_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=600, height=780)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_partial_split_replay_reuses_successful_sibling_and_creates_only_missing_child(monkeypatch):
    db = _DB()
    source_pdf = _two_page_pdf()
    calls = []
    attempt = {"count": 1}

    async def fake_intake(**kwargs):
        calls.append((attempt["count"], kwargs["filename"]))
        # Deliberately fail child 2 only on the first split attempt.
        if attempt["count"] == 1 and kwargs["filename"].endswith("_p2.pdf"):
            raise RuntimeError("forced child 2 failure")

        import hashlib
        child_id = f"child-{len(db.hub_documents.docs)}"
        db.hub_documents.docs[child_id] = {
            "id": child_id,
            "sha256_hash": hashlib.sha256(kwargs["file_content"]).hexdigest(),
            "document_type": "AP_Invoice",
            "classification_confidence": 0.99,
        }
        return {"document_id": child_id, "document_type": "AP_Invoice"}

    monkeypatch.setattr(intake_service, "intake_document_from_bytes", fake_intake)

    first = await splitter.split_and_ingest_batch(
        db=db,
        parent_doc_id="parent-1234567890",
        parent_filename="batch.pdf",
        file_content=source_pdf,
        sender="ap@example.com",
        source="batch_split",
        subject="Batch invoice",
    )

    assert first["status"] == "partial"
    assert first["children_success"] == 1
    assert first["children_errors"] == 1
    first_child_id = first["children"][0]["child_doc_id"]
    first_child_hash = first["children"][0]["content_hash"]

    attempt["count"] = 2
    second = await splitter.split_and_ingest_batch(
        db=db,
        parent_doc_id="parent-1234567890",
        parent_filename="batch.pdf",
        file_content=source_pdf,
        sender="ap@example.com",
        source="batch_split",
        subject="Batch invoice",
    )

    assert second["status"] == "success"
    assert second["children_success"] == 2
    assert second["children_errors"] == 0
    assert second["children_reused"] == 1

    replayed_first = second["children"][0]
    assert replayed_first["reused_existing"] is True
    assert replayed_first["child_doc_id"] == first_child_id
    assert replayed_first["content_hash"] == first_child_hash

    # p1 was ingested once total; replay only called intake for missing p2.
    p1_calls = [name for _, name in calls if name.endswith("_p1.pdf")]
    p2_calls = [name for _, name in calls if name.endswith("_p2.pdf")]
    assert len(p1_calls) == 1
    assert len(p2_calls) == 2

    parent = db.hub_documents.docs["parent-1234567890"]
    assert parent["batch_split_errors"] == 0
    assert parent["batch_split_reused_count"] == 1
    assert len(parent["batch_children_ids"]) == 2

    successful_child = db.hub_documents.docs[first_child_id]
    assert successful_child["batch_parent_ids"] == ["parent-1234567890"]


@pytest.mark.asyncio
async def test_replay_of_fully_successful_split_creates_no_new_children(monkeypatch):
    db = _DB()
    source_pdf = _two_page_pdf()
    intake_calls = []

    async def fake_intake(**kwargs):
        import hashlib
        intake_calls.append(kwargs["filename"])
        child_id = f"child-{len(db.hub_documents.docs)}"
        db.hub_documents.docs[child_id] = {
            "id": child_id,
            "sha256_hash": hashlib.sha256(kwargs["file_content"]).hexdigest(),
            "document_type": "AP_Invoice",
            "classification_confidence": 0.99,
        }
        return {"document_id": child_id, "document_type": "AP_Invoice"}

    monkeypatch.setattr(intake_service, "intake_document_from_bytes", fake_intake)

    first = await splitter.split_and_ingest_batch(
        db=db,
        parent_doc_id="parent-1234567890",
        parent_filename="batch.pdf",
        file_content=source_pdf,
    )
    first_ids = [child["child_doc_id"] for child in first["children"]]

    second = await splitter.split_and_ingest_batch(
        db=db,
        parent_doc_id="parent-1234567890",
        parent_filename="batch.pdf",
        file_content=source_pdf,
    )
    second_ids = [child["child_doc_id"] for child in second["children"]]

    assert first_ids == second_ids
    assert second["children_reused"] == 2
    assert len(intake_calls) == 2
