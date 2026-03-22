"""
Test PDF Page Operations: GET /pages, POST /split, POST /delete-pages

Tests:
1. GET /{doc_id}/pages — returns page count and text previews
2. POST /{doc_id}/split — splits PDF into independent documents
3. POST /{doc_id}/delete-pages — deletes pages in place
4. Validation: duplicate pages, invalid ranges, delete all, single split
5. File-not-on-disk handling
"""
import pytest
import requests
import os
import uuid
from datetime import datetime, timezone
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "gpi_document_hub")
UPLOAD_DIR = "/app/backend/uploads"


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


def _create_test_pdf(doc_id: str, num_pages: int = 5):
    """Create a multi-page test PDF on disk and seed a hub_documents record."""
    from pypdf import PdfWriter
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    import io

    writer = PdfWriter()
    for i in range(num_pages):
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        c.drawString(100, 700, f"Page {i+1} of {num_pages}")
        c.drawString(100, 680, f"Invoice #{chr(65 + i)}-{1000 + i}")
        c.drawString(100, 660, f"Amount: ${1000 * (i+1):.2f}")
        c.save()
        buf.seek(0)
        from pypdf import PdfReader
        reader = PdfReader(buf)
        writer.add_page(reader.pages[0])

    path = os.path.join(UPLOAD_DIR, doc_id)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def _seed_doc(db, doc_id: str, **overrides):
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": doc_id,
        "file_name": f"test_{doc_id[:8]}.pdf",
        "content_type": "application/pdf",
        "document_type": "AP_Invoice",
        "suggested_job_type": "AP_Invoice",
        "workflow_status": "received",
        "vendor_canonical": "TEST-VENDOR",
        "email_sender": "test@example.com",
        "created_utc": now,
        "updated_utc": now,
    }
    doc.update(overrides)
    db.hub_documents.update_one({"id": doc_id}, {"$set": doc}, upsert=True)
    return doc


def _cleanup(db, doc_id: str):
    db.hub_documents.delete_one({"id": doc_id})
    path = os.path.join(UPLOAD_DIR, doc_id)
    if os.path.exists(path):
        os.remove(path)


def _uid():
    return f"test-pdf-{uuid.uuid4().hex[:10]}"


class TestGetPages:
    def test_returns_page_count_and_previews(self, db):
        doc_id = _uid()
        _create_test_pdf(doc_id, 3)
        _seed_doc(db, doc_id)
        try:
            resp = requests.get(f"{BASE_URL}/api/documents/{doc_id}/pages")
            assert resp.status_code == 200
            data = resp.json()
            assert data["page_count"] == 3
            assert len(data["pages"]) == 3
            assert data["pages"][0]["page_number"] == 1
            assert "Page 1" in data["pages"][0]["text_preview"]
            assert data["pages"][2]["page_number"] == 3
            print(f"[PASS] Pages: {data['page_count']} with previews")
        finally:
            _cleanup(db, doc_id)

    def test_404_nonexistent(self):
        resp = requests.get(f"{BASE_URL}/api/documents/nonexistent-doc/pages")
        assert resp.status_code == 404
        print("[PASS] 404 for nonexistent doc")

    def test_file_not_on_disk(self, db):
        doc_id = _uid()
        _seed_doc(db, doc_id, sharepoint_web_url="https://sp.example.com/doc.pdf")
        try:
            resp = requests.get(f"{BASE_URL}/api/documents/{doc_id}/pages")
            assert resp.status_code == 200
            data = resp.json()
            assert data["page_count"] is None
            assert data["error"] == "file_not_on_disk"
            assert data["sharepoint_url"] == "https://sp.example.com/doc.pdf"
            print("[PASS] File not on disk returns graceful error")
        finally:
            _cleanup(db, doc_id)


class TestSplit:
    def test_split_happy_path(self, db):
        doc_id = _uid()
        _create_test_pdf(doc_id, 5)
        _seed_doc(db, doc_id)
        try:
            resp = requests.post(
                f"{BASE_URL}/api/documents/{doc_id}/split",
                json={"splits": [
                    {"pages": [1, 2, 3], "label": "Part A"},
                    {"pages": [4, 5], "label": "Part B"},
                ]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert len(data["new_documents"]) == 2
            assert data["new_documents"][0]["pages"] == [1, 2, 3]
            assert data["new_documents"][1]["pages"] == [4, 5]

            # Verify original marked as split
            orig = db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
            assert orig["workflow_status"] == "split"
            assert len(orig["split_into"]) == 2

            # Verify new docs exist with correct page counts
            for new_doc in data["new_documents"]:
                new_id = new_doc["doc_id"]
                nd = db.hub_documents.find_one({"id": new_id}, {"_id": 0})
                assert nd is not None
                assert nd["parent_doc_id"] == doc_id
                assert nd["split_from"] == doc_id
                assert nd["workflow_status"] in ("received", "captured", "classified")

                # Verify file on disk
                assert os.path.exists(os.path.join(UPLOAD_DIR, new_id))

                # Cleanup
                _cleanup(db, new_id)

            print("[PASS] Split: 2 new docs, original marked split")
        finally:
            _cleanup(db, doc_id)

    def test_rejects_single_split(self, db):
        doc_id = _uid()
        _create_test_pdf(doc_id, 3)
        _seed_doc(db, doc_id)
        try:
            resp = requests.post(
                f"{BASE_URL}/api/documents/{doc_id}/split",
                json={"splits": [{"pages": [1, 2, 3]}]},
            )
            assert resp.status_code == 400
            assert "2 splits" in resp.json()["detail"]
            print("[PASS] Rejected single split")
        finally:
            _cleanup(db, doc_id)

    def test_rejects_duplicate_pages(self, db):
        doc_id = _uid()
        _create_test_pdf(doc_id, 3)
        _seed_doc(db, doc_id)
        try:
            resp = requests.post(
                f"{BASE_URL}/api/documents/{doc_id}/split",
                json={"splits": [
                    {"pages": [1, 2]},
                    {"pages": [2, 3]},
                ]},
            )
            assert resp.status_code == 400
            assert "multiple splits" in resp.json()["detail"]
            print("[PASS] Rejected duplicate pages")
        finally:
            _cleanup(db, doc_id)

    def test_rejects_invalid_page(self, db):
        doc_id = _uid()
        _create_test_pdf(doc_id, 3)
        _seed_doc(db, doc_id)
        try:
            resp = requests.post(
                f"{BASE_URL}/api/documents/{doc_id}/split",
                json={"splits": [
                    {"pages": [1]},
                    {"pages": [99]},
                ]},
            )
            assert resp.status_code == 400
            assert "Invalid page 99" in resp.json()["detail"]
            print("[PASS] Rejected invalid page number")
        finally:
            _cleanup(db, doc_id)

    def test_file_not_on_disk(self, db):
        doc_id = _uid()
        _seed_doc(db, doc_id)
        try:
            resp = requests.post(
                f"{BASE_URL}/api/documents/{doc_id}/split",
                json={"splits": [{"pages": [1]}, {"pages": [2]}]},
            )
            assert resp.status_code == 400
            assert "not on disk" in resp.json()["detail"]
            print("[PASS] Split rejects when file not on disk")
        finally:
            _cleanup(db, doc_id)


class TestDeletePages:
    def test_delete_happy_path(self, db):
        doc_id = _uid()
        _create_test_pdf(doc_id, 5)
        _seed_doc(db, doc_id)
        try:
            resp = requests.post(
                f"{BASE_URL}/api/documents/{doc_id}/delete-pages",
                json={"pages_to_delete": [2, 4]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["pages_deleted"] == [2, 4]
            assert data["page_count_original"] == 5
            assert data["page_count_current"] == 3
            assert data["pages_remaining"] == [1, 3, 5]

            # Verify DB updated
            updated = db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
            assert updated["page_count_current"] == 3
            assert updated["pages_deleted"] == [2, 4]

            # Verify file has 3 pages
            pages_resp = requests.get(f"{BASE_URL}/api/documents/{doc_id}/pages")
            assert pages_resp.json()["page_count"] == 3
            print("[PASS] Deleted pages 2,4 — 3 remaining")
        finally:
            _cleanup(db, doc_id)

    def test_rejects_delete_all(self, db):
        doc_id = _uid()
        _create_test_pdf(doc_id, 3)
        _seed_doc(db, doc_id)
        try:
            resp = requests.post(
                f"{BASE_URL}/api/documents/{doc_id}/delete-pages",
                json={"pages_to_delete": [1, 2, 3]},
            )
            assert resp.status_code == 400
            assert "all pages" in resp.json()["detail"]
            print("[PASS] Rejected deleting all pages")
        finally:
            _cleanup(db, doc_id)

    def test_rejects_invalid_page(self, db):
        doc_id = _uid()
        _create_test_pdf(doc_id, 3)
        _seed_doc(db, doc_id)
        try:
            resp = requests.post(
                f"{BASE_URL}/api/documents/{doc_id}/delete-pages",
                json={"pages_to_delete": [50]},
            )
            assert resp.status_code == 400
            assert "Invalid page 50" in resp.json()["detail"]
            print("[PASS] Rejected invalid page number")
        finally:
            _cleanup(db, doc_id)

    def test_rejects_empty_list(self, db):
        doc_id = _uid()
        _create_test_pdf(doc_id, 3)
        _seed_doc(db, doc_id)
        try:
            resp = requests.post(
                f"{BASE_URL}/api/documents/{doc_id}/delete-pages",
                json={"pages_to_delete": []},
            )
            assert resp.status_code == 400
            print("[PASS] Rejected empty pages list")
        finally:
            _cleanup(db, doc_id)

    def test_file_not_on_disk(self, db):
        doc_id = _uid()
        _seed_doc(db, doc_id)
        try:
            resp = requests.post(
                f"{BASE_URL}/api/documents/{doc_id}/delete-pages",
                json={"pages_to_delete": [1]},
            )
            assert resp.status_code == 400
            assert "not on disk" in resp.json()["detail"]
            print("[PASS] Delete rejects when file not on disk")
        finally:
            _cleanup(db, doc_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
