"""
Tests for S9-mirroring routing fix:
- AP Invoices with unresolved POs (bc_po_resolved=False) → Miscellaneous
- AP Invoices with no PO → Miscellaneous
- AP Invoices with resolved POs → Dropship Not International
- International/warehouse routing unaffected
"""
import pytest
from services.folder_routing_service import determine_folder_path


def make_doc(doc_type="AP_Invoice", vendor="acme corp", po="PO12345",
             bc_po_resolved=None, is_international=False, file_name="inv.pdf"):
    doc = {
        "document_type": doc_type,
        "vendor_canonical": vendor,
        "extracted_fields": {"po_number": po, "order_number": po},
        "file_name": file_name,
        "is_international": is_international,
    }
    if bc_po_resolved is not None:
        doc["bc_po_resolved"] = bc_po_resolved
    return doc


class TestS9UnresolvedPORouting:
    """S9 workflow: PO not found in BC → Miscellaneous."""

    def test_ap_invoice_unresolved_po_goes_to_miscellaneous(self):
        doc = make_doc(po="PO99999", bc_po_resolved=False)
        path, reason, _ = determine_folder_path(doc)
        assert "Miscellaneous" in path
        assert "need approval" in path

    def test_ap_invoice_resolved_po_goes_to_dropship(self):
        doc = make_doc(po="PO12345", bc_po_resolved=True)
        path, reason, _ = determine_folder_path(doc)
        assert "Dropship Not International Documents" in path
        assert "PO12345" in path

    def test_ap_invoice_no_bc_check_goes_to_dropship(self):
        """When bc_po_resolved is None (no BC check done), normal routing."""
        doc = make_doc(po="PO12345", bc_po_resolved=None)
        path, reason, _ = determine_folder_path(doc)
        assert "Dropship Not International Documents" in path

    def test_ap_invoice_no_po_domestic_goes_to_miscellaneous(self):
        doc = make_doc(po="", bc_po_resolved=None)
        path, reason, _ = determine_folder_path(doc)
        assert "Miscellaneous" in path
        assert "need approval" in path

    def test_ap_invoice_no_po_international_still_routes_international(self):
        """International AP invoices without PO should NOT go to Misc."""
        doc = make_doc(po="", is_international=True)
        path, reason, _ = determine_folder_path(doc)
        assert "International" in path
        assert "Miscellaneous" not in path

    def test_ap_invoice_unresolved_po_freight_vendor_goes_to_freight(self):
        """Freight vendors override S9 PO check."""
        doc = make_doc(vendor="fedex", po="PO99999", bc_po_resolved=False)
        path, reason, _ = determine_folder_path(doc)
        assert "Freight" in path

    def test_ap_invoice_unresolved_po_international_goes_to_miscellaneous(self):
        """Even international docs with unresolved PO go to Misc per S9."""
        doc = make_doc(po="PO99999", bc_po_resolved=False, is_international=True)
        path, reason, _ = determine_folder_path(doc)
        assert "Miscellaneous" in path

    def test_ap_invoice_resolved_po_warehouse_goes_to_warehouse(self):
        """Warehouse orders with resolved PO route normally."""
        doc = make_doc(po="PO12345", bc_po_resolved=True, file_name="wh_order.pdf")
        path, reason, _ = determine_folder_path(doc)
        assert "Warehouse" in path


class TestExistingRoutingUnchanged:
    """Verify existing routing rules are not broken."""

    def test_canpack_still_routes_to_canpack(self):
        doc = make_doc(vendor="canpack usa", po="PO123")
        path, _, _ = determine_folder_path(doc)
        assert "Canpack" in path

    def test_credit_memo_still_routes_to_credit(self):
        doc = make_doc(doc_type="Credit_Memo", vendor="ball", po="PO123")
        path, _, _ = determine_folder_path(doc)
        assert "Vendor Credit Memos" in path

    def test_shipping_doc_still_routes(self):
        doc = make_doc(doc_type="Shipping_Document", vendor="acme", po="PO123")
        path, _, _ = determine_folder_path(doc)
        assert "Dropship" in path or "Warehouse" in path or "Freight" in path

    def test_unknown_doc_goes_to_miscellaneous(self):
        doc = make_doc(doc_type="Unknown", vendor="acme", po="")
        path, _, _ = determine_folder_path(doc)
        assert "Miscellaneous" in path

    def test_international_vendor_detected(self):
        doc = make_doc(vendor="envases de mexico s.a. de c.v.", po="PO123", bc_po_resolved=True)
        path, _, _ = determine_folder_path(doc, is_international=False)
        assert "International" in path

    def test_location_code_msc_goes_to_miscellaneous(self):
        doc = make_doc(po="PO123")
        path, _, _ = determine_folder_path(doc, location_code="MSC")
        assert "Miscellaneous" in path
