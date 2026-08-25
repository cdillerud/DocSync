import pytest

from services.document_link_visibility_service import (
    build_bc_document_link_filter,
    build_hub_document_link_query,
    canonical_document_type,
)


def test_purchase_invoice_query_binds_number_and_type():
    query = build_hub_document_link_query("purchaseInvoices", "12345")

    assert query["bc_document_no"] == "12345"
    type_clause = query["$and"][1]["$or"]
    assert {"document_type": {"$in": [
        "AP_Invoice", "APInvoice", "AP Invoice", "PurchaseInvoice", "Purchase_Invoice"
    ]}} in type_clause
    assert {"bc_entity": "purchaseInvoices"} in type_clause


def test_same_number_for_purchase_order_uses_different_type_family():
    invoice_query = build_hub_document_link_query("purchaseInvoices", "12345")
    order_query = build_hub_document_link_query("purchaseOrders", "12345")

    assert invoice_query["bc_document_no"] == order_query["bc_document_no"]
    assert invoice_query != order_query
    assert canonical_document_type("purchaseInvoices") == "AP_Invoice"
    assert canonical_document_type("purchaseOrders") == "Purchase_Order"


def test_bc_api_filter_includes_number_and_document_type():
    filt = build_bc_document_link_filter("purchaseInvoices", "PI'100")
    assert "bcDocumentNo eq 'PI''100'" in filt
    assert "documentType eq 'AP_Invoice'" in filt
    assert " and " in filt


def test_unsupported_entity_fails_closed():
    with pytest.raises(ValueError, match="Unsupported BC document entity"):
        build_hub_document_link_query("mysteryRecords", "100")

    with pytest.raises(ValueError, match="Unsupported BC document entity"):
        build_bc_document_link_filter("mysteryRecords", "100")
