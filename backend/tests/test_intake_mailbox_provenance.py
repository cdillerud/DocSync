from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from services.document_bytes_intake_service import (
    intake_document_from_bytes,
)
from services.intake_provenance_service import (
    build_intake_provenance_fields,
    inherit_intake_provenance,
    persist_intake_provenance,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class _UpdateResult:
    matched_count = 1
    modified_count = 1


class _FakeDocuments:
    def __init__(self):
        self.query = None
        self.update = None

    async def update_one(self, query, update):
        self.query = query
        self.update = update
        return _UpdateResult()


class _FakeDb:
    def __init__(self):
        self.hub_documents = _FakeDocuments()


def test_canonical_intake_signature_remains_unchanged():
    assert list(
        inspect.signature(
            intake_document_from_bytes
        ).parameters
    ) == [
        "file_content",
        "filename",
        "content_type",
        "source",
        "sender",
        "subject",
        "email_id",
        "mailbox_category",
    ]


def test_build_fields_records_actual_mailbox_and_original_lane():
    fields = build_intake_provenance_fields(
        source_mailbox="whdocuments@gamerpackaging.com",
        source_mailbox_id="warehouse-source",
        source_lane="Operations",
        mailbox_category="Operations",
        routing_override_applied=False,
    )

    assert fields["source_mailbox"] == (
        "whdocuments@gamerpackaging.com"
    )
    assert fields["source_mailbox_id"] == "warehouse-source"
    assert fields["source_lane"] == "Operations"
    assert fields["original_mailbox_category"] == "Operations"
    assert fields["mailbox_category"] == "Operations"
    assert fields["routing_override_applied"] is False
    assert fields["routing_override_from"] is None
    assert fields["routing_override_to"] is None


def test_build_fields_records_sender_override_without_losing_source():
    fields = build_intake_provenance_fields(
        source_mailbox="whdocuments@gamerpackaging.com",
        source_mailbox_id="warehouse-source",
        source_lane="Operations",
        mailbox_category="AP",
        routing_override_applied=True,
    )

    assert fields["source_mailbox"] == (
        "whdocuments@gamerpackaging.com"
    )
    assert fields["source_lane"] == "Operations"
    assert fields["original_mailbox_category"] == "Operations"
    assert fields["mailbox_category"] == "AP"
    assert fields["routing_override_applied"] is True
    assert fields["routing_override_from"] == "Operations"
    assert fields["routing_override_to"] == "AP"


@pytest.mark.asyncio
async def test_new_document_provenance_is_persisted():
    db = _FakeDb()

    result = await persist_intake_provenance(
        db,
        {"document_id": "doc-1"},
        source_mailbox="hub-ap-intake@gamerpackaging.com",
        source_mailbox_id=None,
        source_lane="AP",
        mailbox_category="AP",
        routing_override_applied=False,
        email_id="message-1",
    )

    assert result["updated"] is True
    assert db.hub_documents.query == {"id": "doc-1"}

    persisted = db.hub_documents.update["$set"]

    assert persisted["source_mailbox"] == (
        "hub-ap-intake@gamerpackaging.com"
    )
    assert persisted["source_lane"] == "AP"
    assert persisted["original_mailbox_category"] == "AP"


@pytest.mark.asyncio
async def test_duplicate_retry_only_fills_same_email_missing_provenance():
    db = _FakeDb()

    await persist_intake_provenance(
        db,
        {
            "document_id": "doc-2",
            "skipped_duplicate": True,
        },
        source_mailbox="whdocuments@gamerpackaging.com",
        source_mailbox_id="warehouse-source",
        source_lane="Operations",
        mailbox_category="Operations",
        routing_override_applied=False,
        email_id="<same-message@example>",
    )

    assert db.hub_documents.query["id"] == "doc-2"
    assert db.hub_documents.query["email_id"] == (
        "<same-message@example>"
    )
    assert "$or" in db.hub_documents.query


@pytest.mark.asyncio
async def test_duplicate_without_email_identity_is_not_rewritten():
    db = _FakeDb()

    result = await persist_intake_provenance(
        db,
        {
            "document_id": "doc-3",
            "skipped_duplicate": True,
        },
        source_mailbox="other@example.com",
        source_lane="Operations",
        mailbox_category="Operations",
        email_id=None,
    )

    assert result["updated"] is False
    assert result["reason"] == (
        "duplicate_without_email_identity"
    )
    assert db.hub_documents.query is None


def test_split_child_inherits_only_provenance_fields():
    inherited = inherit_intake_provenance(
        {
            "source_mailbox": (
                "whdocuments@gamerpackaging.com"
            ),
            "source_mailbox_id": "warehouse-source",
            "source_lane": "Operations",
            "original_mailbox_category": "Operations",
            "routing_override_applied": True,
            "routing_override_from": "Operations",
            "routing_override_to": "AP",
            "vendor_name": "DO NOT COPY",
        }
    )

    assert inherited == {
        "source_mailbox": (
            "whdocuments@gamerpackaging.com"
        ),
        "source_mailbox_id": "warehouse-source",
        "source_lane": "Operations",
        "original_mailbox_category": "Operations",
        "routing_override_applied": True,
        "routing_override_from": "Operations",
        "routing_override_to": "AP",
    }


def test_live_email_callers_persist_provenance():
    source = (
        BACKEND_ROOT
        / "services"
        / "email_polling_service.py"
    ).read_text(encoding="utf-8")

    assert "source_mailbox=EMAIL_POLLING_USER" in source
    assert "source_lane=resolved_category" in source

    assert (
        "configured_category = "
        "normalize_mailbox_category(default_category)"
        in source
    )
    assert "source_mailbox=mailbox_address" in source
    assert "source_mailbox_id=source_id" in source
    assert "source_lane=configured_category" in source
    assert (
        "routing_override_applied="
        "routing_override_applied"
        in source
    )


def test_batch_split_children_inherit_provenance():
    source = (
        BACKEND_ROOT
        / "services"
        / "batch_po_splitter.py"
    ).read_text(encoding="utf-8")

    assert '"source_mailbox": 1' in source
    assert '"original_mailbox_category": 1' in source
    assert (
        "child_provenance = "
        "inherit_intake_provenance("
        in source
    )
    assert "**child_provenance" in source
