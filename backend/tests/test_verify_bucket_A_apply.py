"""Tests for verify_bucket_A_apply (read-only, mongomock-backed)."""
from __future__ import annotations

import mongomock

from scripts import verify_bucket_A_apply as vfy


def _coll(docs):
    c = mongomock.MongoClient().db.hub_documents
    if docs:
        c.insert_many(docs)
    return c


def test_fetch_docs_returns_one_record_per_id_in_order():
    coll = _coll([
        {"id": "doc-1", "mailbox_category": "AP", "doc_type": "AP_INVOICE"},
        {"id": "doc-2", "mailbox_category": "AP", "doc_type": "AP_INVOICE"},
    ])
    records = vfy.fetch_docs(coll, ["doc-1", "doc-2", "doc-missing"])
    assert list(records.keys()) == ["doc-1", "doc-2", "doc-missing"]
    assert records["doc-1"]["mailbox_category"] == "AP"
    assert records["doc-missing"] is None


def test_fetch_docs_excludes_internal_id():
    coll = _coll([{"id": "doc-1", "mailbox_category": "AP"}])
    records = vfy.fetch_docs(coll, ["doc-1"])
    assert "_id" not in records["doc-1"]


def test_fetch_docs_only_projects_known_fields():
    coll = _coll([
        {"id": "doc-1", "mailbox_category": "AP",
         "doc_type": "AP_INVOICE", "extra": "should_not_show"},
    ])
    records = vfy.fetch_docs(coll, ["doc-1"])
    assert "extra" not in records["doc-1"]
    assert records["doc-1"]["doc_type"] == "AP_INVOICE"


def test_render_shows_all_seven_required_fields():
    coll = _coll([{
        "id": "doc-1",
        "file_name": "x.pdf",
        "email_sender": "x@y.com",
        "mailbox_category": "AP",
        "doc_type": "AP_INVOICE",
        "suggested_job_type": "AP_Invoice",
        "remediation_audit": {"source": "bucket_A_one_shot_patch",
                              "applied_at": "2026-05-06T22:00:00Z",
                              "cohort_key": {"email_sender": "x@y.com"}},
    }])
    records = vfy.fetch_docs(coll, ["doc-1"])
    text = vfy.render(records)
    for label in ("file_name", "email_sender", "mailbox_category",
                  "doc_type", "suggested_job_type", "remediation_audit"):
        assert label in text
    assert "bucket_A_one_shot_patch" in text
    assert "READ-ONLY" in text


def test_render_marks_not_found_for_missing_doc():
    text = vfy.render({"doc-missing": None})
    assert "NOT FOUND" in text
