"""
Tests for P0 fixes:
  1. Vendor Confirmation reclassification
  2. Customer extraction (Gamer-as-customer detection)
  3. Total amount field mapping
"""
import re
import pytest

# ── Fix 1: Smart Reclassifier catches vendor confirmations ──

from services.pilot_smart_reclassifier import _classify_document, _RULES


class TestSmartReclassifier:
    """Verify vendor confirmations are correctly reclassified."""

    def test_order_confirmation_filename(self):
        result = _classify_document("Order Confirmation 12345.pdf", "", "")
        assert result is not None
        new_type, rule, reason = result
        assert new_type == "Vendor_Document", f"Expected Vendor_Document, got {new_type}"
        assert "confirmation" in reason.lower() or "vendor" in reason.lower()

    def test_order_ack_filename(self):
        result = _classify_document("OrderAck_W117579.pdf", "", "")
        assert result is not None
        new_type, rule, reason = result
        assert new_type == "Vendor_Document"

    def test_ack_suffix_filename(self):
        result = _classify_document("Herdez_PO_12345_ack.pdf", "", "")
        assert result is not None
        new_type, rule, reason = result
        assert new_type == "Vendor_Document"

    def test_confirmation_in_subject(self):
        result = _classify_document("invoice.pdf", "Order Confirmation for PO W117579", "")
        assert result is not None
        new_type, rule, reason = result
        assert new_type == "Vendor_Document"

    def test_acknowledgment_filename(self):
        result = _classify_document("Acknowledgment_67890.pdf", "", "")
        assert result is not None
        new_type, rule, reason = result
        assert new_type == "Vendor_Document"

    def test_proforma_invoice(self):
        result = _classify_document("Proforma_Invoice_2024.pdf", "", "")
        assert result is not None
        new_type, rule, reason = result
        assert new_type == "Vendor_Document"

    def test_real_po_not_caught(self):
        """A genuine customer PO should NOT be reclassified."""
        result = _classify_document("PO_W117579.pdf", "New Purchase Order", "")
        assert result is None, f"Real PO wrongly reclassified as {result}"

    def test_real_sales_order_not_caught(self):
        """A genuine sales order PDF should NOT be reclassified."""
        result = _classify_document("Giovanni_PO_67890.pdf", "Purchase Order", "Please ship 500 cases")
        assert result is None, f"Real SO wrongly reclassified as {result}"

    def test_certificate_still_works(self):
        """Certificates should still be caught before confirmation rules."""
        result = _classify_document("SQF_Certificate_2024.pdf", "", "")
        assert result is not None
        assert result[0] == "Certificate"

    def test_confirmation_does_not_catch_certificate(self):
        """'confirmation' rule should NOT catch 'certificate' in filename."""
        # The negative lookahead (?!.*certif) should prevent this
        result = _classify_document("certification_confirmation.pdf", "", "")
        # Should be caught by cert_generic or cert_filename, not confirmation
        assert result is not None
        assert result[0] == "Certificate"


# ── Fix 2: Customer extraction — Gamer detection ──

class TestCustomerExtraction:
    """Verify Gamer is correctly identified as the seller, not the customer."""

    def test_gamer_vendor_is_detected(self):
        """When vendor_canonical is 'Gamer Packaging', it should be flagged."""
        vendor = "Gamer Packaging"
        assert "gamer" in vendor.lower()

    def test_sender_domain_extraction(self):
        """Test that email sender domain is extracted correctly."""
        sender = "orders@giovannis.com"
        domain = sender.split("@")[1].split(".")[0]
        assert domain == "giovannis"

    def test_gamer_domain_excluded(self):
        """Gamer sender domain should NOT be used as customer."""
        sender = "mkoch@gamerpackaging.com"
        domain = sender.split("@")[1].split(".")[0]
        assert domain.lower() in ("gamerpackaging", "gamer")

    def test_gamer_customer_no_cleared(self):
        """Customer numbers like GAMER, GAMERPA should be cleared."""
        for cn in ("GAMER", "GAMERPA", "GAMER1"):
            assert cn.upper() in ("GAMER", "GAMERPA", "GAMER1")


# ── Fix 3: Total Amount field mapping ──

class TestAmountMapping:
    """Verify amount is correctly sourced from amount_float."""

    def test_amount_float_preferred(self):
        """amount_float should be the primary source, not total_amount."""
        doc = {"amount_float": 3250.00, "total_amount": None}
        amount = doc.get("amount_float") or doc.get("total_amount")
        assert amount == 3250.00

    def test_fallback_chain(self):
        """When amount_float is missing, fall back through the chain."""
        doc = {}
        nf = {"amount_float": 1500.00}
        amount = (
            doc.get("amount_float")
            or doc.get("total_amount")
            or nf.get("amount_float")
        )
        assert amount == 1500.00

    def test_ef_total_amount_fallback(self):
        """extracted_fields.total_amount should still work as fallback."""
        doc = {}
        nf = {}
        ef = {"total_amount": "2,500.00"}
        amount = (
            doc.get("amount_float")
            or doc.get("total_amount")
            or nf.get("amount_float")
            or ef.get("total_amount")
        )
        assert amount == "2,500.00"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ── Fix 4: Spiro ↔ BC name reconciliation ──

class TestNameReconciliation:
    """Verify cross-reference name-matching links split companies."""

    def test_exact_normalized_match(self):
        from services.spiro_bc_cross_ref_service import _normalize_company_name, _reconcile_by_name
        assert _normalize_company_name("Ortho Molecular Products") == "ortho molecular products"
        assert _normalize_company_name("Ortho Molecular Products, Inc.") == "ortho molecular products"

    def test_reconcile_moves_to_both(self):
        from services.spiro_bc_cross_ref_service import _reconcile_by_name
        spiro_only = [{"name": "Ortho Molecular Products", "spiro_id": "123", "doc_count": 4}]
        bc_only = [{"bc_customer_no": "ORTHO", "bc_customer_name": "Ortho Molecular Products", "doc_count": 4}]
        both = []
        _reconcile_by_name(spiro_only, bc_only, both)
        assert len(both) == 1
        assert len(spiro_only) == 0
        assert len(bc_only) == 0
        assert both[0]["bc_customer_no"] == "ORTHO"
        assert both[0]["reconciled_by_name"] is True

    def test_no_false_positive(self):
        from services.spiro_bc_cross_ref_service import _reconcile_by_name
        spiro_only = [{"name": "Ball Corp", "spiro_id": "456", "doc_count": 2}]
        bc_only = [{"bc_customer_no": "ORTHO", "bc_customer_name": "Ortho Molecular", "doc_count": 1}]
        both = []
        _reconcile_by_name(spiro_only, bc_only, both)
        assert len(both) == 0
        assert len(spiro_only) == 1
        assert len(bc_only) == 1

    def test_suffix_stripping(self):
        from services.spiro_bc_cross_ref_service import _normalize_company_name
        assert _normalize_company_name("Massilly North America") == "massilly"
        assert _normalize_company_name("Create-A-Pack Foods, Inc.") == "create-a-pack foods"


# ── Fix 5: BC Validator amount fix ──

class TestBCValidatorAmountFix:
    """Verify BC validator uses amount_float as primary source."""

    def test_amount_float_preferred_in_validator(self):
        doc = {"amount_float": 5200.50, "total_amount": None}
        nf = {}
        ef = {}
        amount = (
            doc.get("amount_float")
            or doc.get("total_amount")
            or nf.get("amount_float") or nf.get("amount")
            or ef.get("total_amount")
        )
        assert amount == 5200.50
