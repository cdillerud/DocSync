"""Tests for PO Resolution Service v2 — Hardened."""
import pytest
from services.po_resolution_service import (
    normalize_po,
    extract_po_candidates,
    is_valid_po_format,
    is_known_non_po,
    requires_po_resolution,
    PO_REQUIRED_DOC_TYPES,
    MISS_NO_PO_EXTRACTED,
    MISS_INVALID_FORMAT,
    MISS_NO_BC_MATCH,
    MISS_BC_LOOKUP_ERROR,
    MISS_VENDOR_CONFLICT,
    STATUS_RESOLVED,
    STATUS_AMBIGUOUS,
    STATUS_NOT_FOUND,
    STATUS_SKIPPED,
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

    def test_preserve_hyphens(self):
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


class TestValidPOFormat:
    """Test against real BC PO format patterns from cache analysis."""

    def test_pure_numeric_5_to_7_digits(self):
        assert is_valid_po_format("100092") is True
        assert is_valid_po_format("109023") is True
        assert is_valid_po_format("1234567") is True
        assert is_valid_po_format("12345") is True

    def test_w_prefix(self):
        assert is_valid_po_format("W102008") is True
        assert is_valid_po_format("W117397") is True

    def test_wa_prefix(self):
        assert is_valid_po_format("WA1848") is True

    def test_wr_prefix(self):
        assert is_valid_po_format("WR106124") is True

    def test_pr_prefix(self):
        assert is_valid_po_format("PR10088") is True

    def test_suffix_variants(self):
        assert is_valid_po_format("104718B") is True

    def test_too_short(self):
        assert is_valid_po_format("12") is False
        assert is_valid_po_format("") is False

    def test_too_long_pure_alpha(self):
        assert is_valid_po_format("ABCDEFGH") is False


class TestKnownNonPO:
    """Shipping references and other non-PO patterns."""

    def test_si_prefix(self):
        assert is_known_non_po("SI-02-26-31488") is True
        assert is_known_non_po("SI-02-26-31489") is True

    def test_ssh_prefix(self):
        assert is_known_non_po("SSH-EVEKI-63") is True

    def test_container_patterns(self):
        assert is_known_non_po("MSKU1234567") is True
        assert is_known_non_po("TCNU1234567") is True

    def test_valid_po_not_flagged(self):
        assert is_known_non_po("109023") is False
        assert is_known_non_po("W117397") is False
        assert is_known_non_po("107346") is False


class TestExtractPOCandidates:
    def test_from_extracted_fields(self):
        fields = {"po_number": "109023"}
        candidates = extract_po_candidates("", fields)
        assert len(candidates) >= 1
        assert candidates[0]["normalized"] == "109023"
        assert candidates[0]["valid_format"] is True
        assert candidates[0]["is_non_po"] is False

    def test_comma_separated(self):
        fields = {"po_number": "PO.107459,107460"}
        candidates = extract_po_candidates("", fields)
        norms = {c["normalized"] for c in candidates}
        assert "107459" in norms
        assert "107460" in norms

    def test_non_po_gets_downgraded(self):
        fields = {"po_number": "SI-02-26-31488"}
        candidates = extract_po_candidates("", fields)
        assert len(candidates) >= 1
        si_cand = [c for c in candidates if c["normalized"] == "SI-02-26-31488"]
        assert si_cand[0]["is_non_po"] is True
        assert si_cand[0]["confidence"] <= 0.15  # heavily downgraded

    def test_invalid_format_downgraded(self):
        fields = {"po_number": "SSH-EVEKI-63"}
        candidates = extract_po_candidates("", fields)
        ssh_cand = [c for c in candidates if "SSH" in c["normalized"]]
        if ssh_cand:
            assert ssh_cand[0]["is_non_po"] is True

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


class TestMissTaxonomy:
    """Verify miss reason constants exist and are string values."""

    def test_miss_reasons_are_strings(self):
        assert isinstance(MISS_NO_PO_EXTRACTED, str)
        assert isinstance(MISS_INVALID_FORMAT, str)
        assert isinstance(MISS_NO_BC_MATCH, str)
        assert isinstance(MISS_BC_LOOKUP_ERROR, str)
        assert isinstance(MISS_VENDOR_CONFLICT, str)

    def test_statuses_are_strings(self):
        assert isinstance(STATUS_RESOLVED, str)
        assert isinstance(STATUS_AMBIGUOUS, str)
        assert isinstance(STATUS_NOT_FOUND, str)
        assert isinstance(STATUS_SKIPPED, str)


class TestDocTypes:
    def test_shipping_doc_requires_po(self):
        assert requires_po_resolution("Shipping_Document")

    def test_warehouse_receipt_requires_po(self):
        assert requires_po_resolution("Warehouse_Receipt")

    def test_freight_doc_requires_po(self):
        assert requires_po_resolution("Freight_Document")

    def test_ap_invoice_does_not(self):
        assert not requires_po_resolution("AP_Invoice")

    def test_empty_does_not(self):
        assert not requires_po_resolution("")
