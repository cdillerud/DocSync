import pytest

from services.bc_drop_parity_metadata_service import (
    build_bc_drop_parity_metadata,
    normalize_system_id,
    validate_bc_drop_source_contract,
)


SYSTEM_ID = "7d1f89f5-85fd-4ff9-a56c-4610b9415e3b"


@pytest.mark.parametrize(
    "entity,table_id,doc_type",
    [
        ("purchaseInvoices", 38, "Purchase Invoice"),
        ("purchaseInvoices", 122, "Posted Purchase Invoice"),
        ("purchaseOrders", 38, "Purchase Order"),
        ("postedSalesShipments", 110, "Posted Sales Shipment"),
    ],
)
def test_allowed_ap_warehouse_source_contracts(entity, table_id, doc_type):
    assert validate_bc_drop_source_contract(entity, table_id, doc_type) == (
        entity,
        table_id,
        doc_type,
    )


@pytest.mark.parametrize(
    "entity,table_id,doc_type",
    [
        ("salesOrders", 36, "Sales Order"),
        ("salesInvoices", 112, "Posted Sales Invoice"),
        ("purchaseInvoices", 38, "Posted Purchase Invoice"),
        ("purchaseInvoices", 122, "Purchase Invoice"),
    ],
)
def test_sales_and_mismatched_lifecycle_contracts_fail_closed(entity, table_id, doc_type):
    with pytest.raises(ValueError):
        validate_bc_drop_source_contract(entity, table_id, doc_type)


def test_invalid_system_id_fails_closed():
    with pytest.raises(ValueError):
        normalize_system_id("not-a-guid")


def test_staged_metadata_is_not_import_ready_until_bc_link_exists():
    metadata = build_bc_drop_parity_metadata(
        bc_entity="purchaseInvoices",
        bc_document_no="PI-1001",
        bc_system_id=SYSTEM_ID,
        source_table_id=38,
        source_document_type="Purchase Invoice",
        original_file_name="invoice.pdf",
        sharepoint_file_name="invoice.pdf",
        sharepoint_path="AP_Invoices",
        sharepoint_url="https://example.sharepoint.com/invoice.pdf",
        ready=False,
    )
    assert metadata["GPI_SourceTableID"] == 38
    assert metadata["GPI_SourceSystemId"] == SYSTEM_ID
    assert metadata["GPI_Status"] == "NeedsBCLink"
    assert metadata["ImportReady"] is False
    assert metadata["GPI_MatchMethod"] == "bc_factbox_exact_system_id"


def test_final_metadata_becomes_import_ready_after_bc_link():
    metadata = build_bc_drop_parity_metadata(
        bc_entity="postedSalesShipments",
        bc_document_no="S-1001",
        bc_system_id=SYSTEM_ID,
        source_table_id=110,
        source_document_type="Posted Sales Shipment",
        original_file_name="receipt.pdf",
        sharepoint_file_name="receipt.pdf",
        sharepoint_path="Warehouse",
        sharepoint_url="https://example.sharepoint.com/receipt.pdf",
        ready=True,
    )
    assert metadata["GPI_SourceTableID"] == 110
    assert metadata["GPI_Status"] == "ImportReady"
    assert metadata["ImportReady"] is True
