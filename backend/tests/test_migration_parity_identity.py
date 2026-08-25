import pytest

import services.migration.parity_identity as parity
from services.migration.sources import LegacyDocumentMetadata


def _doc():
    return {
        "id": "migrated-1",
        "legacy_file_reference": r"C:\Exports\invoice.pdf",
        "status": "migrated",
    }


def _metadata(**overrides):
    values = {
        "legacy_system": "SQUARE9",
        "legacy_id": "S9-1",
        "legacy_bc_doc_no": "PI100",
        "vendor_no": "V100",
    }
    values.update(overrides)
    return LegacyDocumentMetadata(**values)


def test_ap_migration_stages_not_ready_until_system_id():
    doc = parity.stage_migration_parity_fields(_doc(), _metadata(), "AP_INVOICE")

    assert doc["GPI_SourceTableID"] == 122
    assert doc["GPI_SourceDocumentType"] == "Posted Purchase Invoice"
    assert doc["GPI_SourceDocumentNo"] == "PI100"
    assert doc["GPI_SourceSystemId"] == ""
    assert doc["GPI_SourcePartyType"] == "Vendor"
    assert doc["GPI_SourcePartyNo"] == "V100"
    assert doc["GPI_OriginalFileName"] == "invoice.pdf"
    assert doc["ImportReady"] is False
    assert doc["import_ready"] is False
    assert doc["GPI_Status"] == "MigrationNeedsSystemId"
    assert doc["status"] == "migration_staged"


def test_purchase_order_without_bc_number_fails_closed():
    doc = parity.stage_migration_parity_fields(
        _doc(), _metadata(legacy_bc_doc_no=None), "PURCHASE_ORDER"
    )

    assert doc["GPI_SourceTableID"] == 38
    assert doc["ImportReady"] is False
    assert doc["delivery_status"] == "MigrationNeedsRecord"
    assert doc["migration_identity_status"] == "missing_record_number"


@pytest.mark.asyncio
async def test_real_migration_resolution_sets_exact_production_system_id(monkeypatch):
    doc = parity.stage_migration_parity_fields(_doc(), _metadata(), "AP_INVOICE")
    seen = {}

    async def resolve(entity, number, *, environment=None):
        seen.update(entity=entity, number=number, environment=environment)
        return {
            "bc_system_id": "11111111-2222-3333-4444-555555555555",
            "bc_document_no": "PI100",
        }

    monkeypatch.setattr(parity, "resolve_bc_document_system_id", resolve)
    monkeypatch.setattr(parity, "BC_READ_ENVIRONMENT", "Production")

    result = await parity.resolve_migration_identity(doc, _metadata(), "AP_INVOICE")

    assert seen == {
        "entity": "purchaseInvoices",
        "number": "PI100",
        "environment": "Production",
    }
    assert result["GPI_SourceSystemId"] == "11111111-2222-3333-4444-555555555555"
    assert result["ImportReady"] is True
    assert result["import_ready"] is True
    assert result["migration_identity_status"] == "resolved"
    assert result["delivery_status"] == "MigrationIdentityReady"


@pytest.mark.asyncio
async def test_resolution_failure_remains_visible_and_not_ready(monkeypatch):
    doc = parity.stage_migration_parity_fields(_doc(), _metadata(), "AP_INVOICE")

    async def resolve(*args, **kwargs):
        raise LookupError("not found")

    monkeypatch.setattr(parity, "resolve_bc_document_system_id", resolve)

    result = await parity.resolve_migration_identity(doc, _metadata(), "AP_INVOICE")

    assert result["ImportReady"] is False
    assert result["import_ready"] is False
    assert result["migration_identity_status"] == "resolution_failed"
    assert result["delivery_status"] == "MigrationNeedsSystemId"
    assert "not found" in result["migration_identity_error"]


@pytest.mark.asyncio
async def test_non_bc_migration_type_never_becomes_import_ready_from_legacy_status(monkeypatch):
    doc = parity.stage_migration_parity_fields(_doc(), _metadata(), "QUALITY_DOC")
    assert doc["ImportReady"] is False
    assert doc["migration_identity_required"] is False
    assert doc["delivery_status"] == "MigrationStaged"

    result = await parity.resolve_migration_identity(doc, _metadata(), "QUALITY_DOC")
    assert result["ImportReady"] is False
