import pytest

import services.migration.delivery as delivery
from services.migration.sources import LegacyDocument, LegacyDocumentMetadata


class _Source:
    def __init__(self, payload=b"pdf-bytes"):
        self.payload = payload
        self.read_count = 0

    def read_binary(self, legacy_doc):
        self.read_count += 1
        return self.payload


def _legacy():
    return LegacyDocument(
        metadata=LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id="S9-1",
            legacy_bc_doc_no="PI100",
        ),
        binary_reference="/legacy/ap/invoice.pdf",
    )


def _gpi(**overrides):
    base = {
        "id": "doc-1",
        "legacy_id": "S9-1",
        "doc_type": "AP_INVOICE",
        "migration_identity_required": True,
        "migration_identity_status": "resolved",
        "GPI_SourceTableID": 122,
        "GPI_SourceSystemId": "11111111-2222-3333-4444-555555555555",
        "GPI_SourceDocumentType": "Posted Purchase Invoice",
        "GPI_SourceDocumentNo": "PI100",
        "GPI_SourcePartyType": "Vendor",
        "GPI_SourcePartyNo": "V100",
        "GPI_OriginalFileName": "invoice.pdf",
    }
    base.update(overrides)
    return base


def test_metadata_override_only_ready_with_required_system_id():
    ready = delivery.build_migration_metadata_override(_gpi())
    assert ready["ImportReady"] is True
    assert ready["GPI_Status"] == "ImportReady"
    assert ready["GPI_SourceSystemId"] == "11111111-2222-3333-4444-555555555555"

    pending = delivery.build_migration_metadata_override(
        _gpi(GPI_SourceSystemId="", bc_system_id="", migration_identity_status="resolution_failed")
    )
    assert pending["ImportReady"] is False
    assert pending["GPI_Status"] == "MigrationNeedsSystemId"


@pytest.mark.asyncio
async def test_delivers_binary_through_existing_sharepoint_boundary(monkeypatch):
    source = _Source()
    seen = {}

    async def upload(**kwargs):
        seen.update(kwargs)
        metadata = dict(kwargs["parity_metadata_override"])
        metadata.update({
            "GPI_OriginalFileName": kwargs["file_name"],
            "GPI_SharePointFileName": "PI100 Vendor.pdf",
            "GPI_SharePointPath": "/AP/V100",
            "GPI_SharePointURL": "https://sharepoint/doc",
        })
        return {
            "drive_id": "drive-1",
            "item_id": "item-1",
            "web_url": "https://sharepoint/doc",
            "folder_path": "/AP/V100",
            "uploaded_file_name": "PI100 Vendor.pdf",
            "parity_metadata": metadata,
        }

    monkeypatch.setattr(delivery, "upload_to_sharepoint_with_routing", upload)
    doc = await delivery.deliver_migrated_document(source, _legacy(), _gpi())

    assert source.read_count == 1
    assert seen["file_content"] == b"pdf-bytes"
    assert seen["file_name"] == "invoice.pdf"
    assert seen["parity_metadata_override"]["GPI_SourceSystemId"].startswith("11111111")
    assert doc["sharepoint_item_id"] == "item-1"
    assert doc["GPI_SharePointURL"] == "https://sharepoint/doc"
    assert doc["ImportReady"] is True
    assert doc["migration_binary_status"] == "delivered"
    assert doc["status"] == "migrated_delivered"


@pytest.mark.asyncio
async def test_empty_binary_fails_before_sharepoint_upload(monkeypatch):
    source = _Source(payload=b"")

    async def upload(**kwargs):
        raise AssertionError("SharePoint upload must not run for empty binary")

    monkeypatch.setattr(delivery, "upload_to_sharepoint_with_routing", upload)

    with pytest.raises(ValueError, match="body is empty"):
        await delivery.deliver_migrated_document(source, _legacy(), _gpi())


@pytest.mark.asyncio
async def test_unresolved_identity_can_stage_file_but_never_be_import_ready(monkeypatch):
    source = _Source()

    async def upload(**kwargs):
        metadata = dict(kwargs["parity_metadata_override"])
        metadata.update({
            "GPI_SharePointFileName": kwargs["file_name"],
            "GPI_SharePointPath": "/AP/Review",
            "GPI_SharePointURL": "https://sharepoint/review",
        })
        return {
            "drive_id": "d",
            "item_id": "i",
            "web_url": "https://sharepoint/review",
            "folder_path": "/AP/Review",
            "uploaded_file_name": kwargs["file_name"],
            "parity_metadata": metadata,
        }

    monkeypatch.setattr(delivery, "upload_to_sharepoint_with_routing", upload)
    doc = await delivery.deliver_migrated_document(
        source,
        _legacy(),
        _gpi(
            GPI_SourceSystemId="",
            bc_system_id="",
            migration_identity_status="resolution_failed",
        ),
    )

    assert doc["ImportReady"] is False
    assert doc["delivery_status"] == "MigrationNeedsSystemId"
    assert doc["status"] == "migration_staged"
    assert doc["migration_binary_status"] == "delivered"
