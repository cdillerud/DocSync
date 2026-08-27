import pytest

from services.ap_purchase_invoice_identity_service import build_ap_purchase_invoice_identity_update


def test_draft_purchase_invoice_identity_is_factbox_ready_with_system_id():
    update = build_ap_purchase_invoice_identity_update(
        "PI-1001", "11111111-2222-3333-4444-555555555555", posted=False
    )
    assert update["bc_document_no"] == "PI-1001"
    assert update["bc_entity"] == "purchaseInvoices"
    assert update["bc_record_id"] == "11111111-2222-3333-4444-555555555555"
    assert update["GPI_SourceTableID"] == 38
    assert update["GPI_SourceDocumentType"] == "Purchase Invoice"
    assert update["ImportReady"] is True


def test_posted_purchase_invoice_identity_uses_posted_header_table():
    update = build_ap_purchase_invoice_identity_update(
        "PI-1001", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", posted=True
    )
    assert update["bc_entity"] == "purchaseInvoices"
    assert update["GPI_SourceTableID"] == 122
    assert update["GPI_SourceDocumentType"] == "Posted Purchase Invoice"
    assert update["GPI_Status"] == "ImportReady"


def test_missing_system_id_fails_closed():
    update = build_ap_purchase_invoice_identity_update("PI-1001", "", posted=False)
    assert update["bc_record_id"] is None
    assert update["ImportReady"] is False
    assert update["GPI_Status"] == "NeedsSystemId"
    assert update["delivery_status"] == "NeedsSystemId"


def test_missing_document_number_is_rejected():
    with pytest.raises(ValueError, match="document number"):
        build_ap_purchase_invoice_identity_update("", "system-id", posted=False)
