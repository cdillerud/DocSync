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
    assert {"bc_entity": {"$in": ["purchaseInvoices", "purchase_invoice", "purchaseInvoice"]}} in type_clause


def test_same_number_for_purchase_order_uses_different_type_family():
    invoice_query = build_hub_document_link_query("purchaseInvoices", "12345")
    order_query = build_hub_document_link_query("purchaseOrders", "12345")

    assert invoice_query["bc_document_no"] == order_query["bc_document_no"]
    assert invoice_query != order_query
    assert canonical_document_type("purchaseInvoices") == "AP_Invoice"
    assert canonical_document_type("purchaseOrders") == "Purchase_Order"


def test_posted_sales_shipment_query_accepts_resolver_storage_identity():
    query = build_hub_document_link_query("postedSalesShipments", "PSH-100")

    assert query["bc_document_no"] == "PSH-100"
    type_clause = query["$and"][1]["$or"]
    assert {"bc_entity_type": {"$in": [
        "postedSalesShipments", "posted_sales_shipment", "postedSalesShipment"
    ]}} in type_clause
    assert {"document_type": {"$in": [
        "Posted_Sales_Shipment",
        "Posted Sales Shipment",
        "Warehouse_Receipt",
        "Shipping_Document",
        "Freight_Document",
    ]}} in type_clause
    assert canonical_document_type("postedSalesShipments") == "Posted_Sales_Shipment"


def test_posted_sales_shipment_bc_filter_binds_shipment_type():
    filt = build_bc_document_link_filter("postedSalesShipments", "PSH'100")
    assert "bcDocumentNo eq 'PSH''100'" in filt
    assert "documentType eq 'Posted_Sales_Shipment'" in filt


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
