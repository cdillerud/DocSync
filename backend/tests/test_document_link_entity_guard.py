"""Tests for fail-closed manual BC entity selection."""

from services.document_link_service import _infer_bc_entity


def test_ap_invoice_maps_to_purchase_invoices():
    assert _infer_bc_entity({"document_type": "AP_INVOICE"}) == "purchaseInvoices"


def test_purchase_order_maps_to_purchase_orders():
    assert _infer_bc_entity({"suggested_job_type": "Purchase_Order"}) == "purchaseOrders"


def test_explicit_entity_is_preserved():
    assert _infer_bc_entity({"bc_entity": "purchaseOrders"}) == "purchaseOrders"


def test_unknown_document_has_no_sales_fallback():
    assert _infer_bc_entity({"document_type": "Unknown"}) == ""
