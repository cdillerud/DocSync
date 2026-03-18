"""Tests for PO Resolution Service."""
import pytest
from services.po_resolution_service import (
    normalize_po,
    extract_po_candidates,
    PO_REQUIRED_DOC_TYPES,
)


class TestNormalizePO:
    def test_pure_numeric(self):
        assert normalize_po("109023") == "109023"
        assert normalize_po("107346") == "107346"

    def test_strip_po_prefix(self):
        assert normalize_po("PO12345") == "12345"
        assert normalize_po("PO.107459") == "107459"
        assert normalize_po("P.O. 123456") == "123456"
        assert normalize_po("P.O.#123456") == "123456"

    def test_strip_purchase_order(self):
        assert normalize_po("Purchase Order 999888") == "999888"
        assert normalize_po("Purchase Order: 999888") == "999888"

    def test_preserve_alphanumeric(self):
        assert normalize_po("W117397") == "W117397"
        assert normalize_po("SI-02-26-31488") == "SI-02-26-31488"

    def test_empty_and_none(self):
        assert normalize_po("") == ""
        assert normalize_po(None) == ""

    def test_leading_zeros(self):
        assert normalize_po("00123") == "123"
        assert normalize_po("0") == "0"

    def test_whitespace(self):
        assert normalize_po("  109023  ") == "109023"
        assert normalize_po("PO  12345") == "12345"


class TestExtractPOCandidates:
    def test_from_extracted_fields(self):
        fields = {"po_number": "109023"}
        candidates = extract_po_candidates("", fields)
        assert len(candidates) >= 1
        assert candidates[0]["normalized"] == "109023"
        assert candidates[0]["source"].startswith("extracted_field:")

    def test_comma_separated(self):
        fields = {"po_number": "PO.107459,107460"}
        candidates = extract_po_candidates("", fields)
        norms = {c["normalized"] for c in candidates}
        assert "107459" in norms
        assert "107460" in norms

    def test_from_text_regex(self):
        text = "Our PO# 123456 has been shipped"
        candidates = extract_po_candidates(text, {})
        norms = {c["normalized"] for c in candidates}
        assert "123456" in norms

    def test_order_number_field(self):
        fields = {"order_number": "5477796"}
        candidates = extract_po_candidates("", fields)
        assert any(c["normalized"] == "5477796" for c in candidates)

    def test_no_candidates(self):
        candidates = extract_po_candidates("", {})
        assert candidates == []


class TestDocTypes:
    def test_shipping_doc_requires_po(self):
        assert "Shipping_Document" in PO_REQUIRED_DOC_TYPES

    def test_warehouse_receipt_requires_po(self):
        assert "Warehouse_Receipt" in PO_REQUIRED_DOC_TYPES

    def test_freight_doc_requires_po(self):
        assert "Freight_Document" in PO_REQUIRED_DOC_TYPES

    def test_ap_invoice_does_not(self):
        assert "AP_Invoice" not in PO_REQUIRED_DOC_TYPES
