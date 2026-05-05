"""
Routing regression test — Hub auto-classification + auto-routing parity.

Locks in the corrected behavior in services.folder_routing_service:

1. High-confidence AP invoices auto-route to their final accounting folder
   without manual accounting approval (Canpack vendor → Dropship/Canpack;
   credit-memo description → Vendor Credit Memos; WH_ pattern → Warehouse;
   freight vendor → Freight Issues; resolved BC PO → Dropship/Warehouse;
   etc.). No accounting_routing_override needed.

2. Weak-fallback AP-lane routings (rule chain ends in "Default routing for
   ..." or `Misc Invoices - need approval`) are redirected to the AP Temp
   Folder for review, so AP-lane docs never sit unstructured in Misc.

3. Documents flagged mailbox_lane_needs_review=True (set by classification
   for non-invoice docs sent to billing@) go to the AP review subfolder,
   not the generic Operations folders.

4. Non-AP documents (Sales_Order, Shipping_Document, Inventory_Report,
   etc.) keep their existing routing — the weak-fallback wrapper only
   applies to AP-lane docs.
"""

from services.folder_routing_service import (
    determine_folder_path,
    AP_STAGING_FOLDER,
    AP_LANE_REVIEW_FOLDER,
)


def _route(doc, **kwargs):
    return determine_folder_path(doc, **kwargs)


# ---------------------------------------------------------------------------
# 1. High-confidence AP invoices auto-route to FINAL folder (no override)
# ---------------------------------------------------------------------------

class TestHighConfidenceAPAutoRoutes:

    def test_canpack_vendor_routes_to_canpack_subfolder(self):
        """Canpack rule is a strong vendor signal → Dropship/Canpack
        directly. No accounting override. No staging."""
        path, reason, _ = _route({
            "document_type": "AP_Invoice",
            "doc_type": "AP_INVOICE",
            "vendor_canonical": "Canpack USA",
            "mailbox_category": "AP",
            "extracted_fields": {"description": "Canpack delivery"},
        })
        assert path.startswith("Dropship Not International Documents/Canpack"), (
            f"Canpack AP invoice must auto-route to Dropship/Canpack; got {path}"
        )
        assert path != AP_STAGING_FOLDER

    def test_credit_memo_description_routes_to_vendor_credit_memos(self):
        """Description-keyword evidence is enough to land in Vendor Credit
        Memos directly."""
        path, _, _ = _route({
            "document_type": "AP_Invoice",
            "doc_type": "AP_INVOICE",
            "vendor_canonical": "Anchor Glass",
            "mailbox_category": "AP",
            "extracted_fields": {"description": "credit memo refund adjustment"},
        })
        assert path.startswith("Vendor Credit Memos"), (
            f"Description-evidence credit memo must auto-route to Vendor "
            f"Credit Memos; got {path}"
        )

    def test_wh_filename_pattern_routes_to_warehouse(self):
        """WH_ filename + vendor + PO is high-confidence warehouse evidence
        → Warehouse Not International, no override."""
        path, _, _ = _route({
            "file_name": "WH_112320_Ball_PO88701_031192026.pdf",
            "document_type": "AP_Invoice",
            "doc_type": "AP_INVOICE",
            "vendor_canonical": "BALL CORPORATION",
            "mailbox_category": "AP",
            "extracted_fields": {"order_number": "PO88701"},
        })
        assert "Warehouse" in path and "Not International" in path

    def test_freight_vendor_with_resolved_po_routes_to_freight(self):
        """Freight vendor + BC-resolved PO → Freight Issues, no override."""
        path, _, _ = _route({
            "document_type": "AP_Invoice",
            "doc_type": "AP_INVOICE",
            "vendor_canonical": "FedEx Freight",
            "mailbox_category": "AP",
            "extracted_fields": {"po_number": "PO12345", "order_number": "PO12345"},
            "bc_po_resolved": True,
        })
        assert "Freight" in path

    def test_resolved_po_routes_to_dropship(self):
        """AP invoice with BC-resolved PO and no other special signal →
        Dropship Not International, no override."""
        path, _, _ = _route({
            "document_type": "AP_Invoice",
            "doc_type": "AP_INVOICE",
            "vendor_canonical": "Some Vendor",
            "mailbox_category": "AP",
            "extracted_fields": {"po_number": "PO12345", "order_number": "PO12345"},
            "bc_po_resolved": True,
        })
        assert "Dropship Not International Documents" in path

    def test_msc_location_code_still_routes_to_misc(self):
        """LocationCode=MSC is a strong, explicit operator signal → Misc
        is the correct destination here even for AP-lane docs."""
        path, _, _ = _route({
            "document_type": "AP_Invoice",
            "doc_type": "AP_INVOICE",
            "vendor_canonical": "Some Vendor",
            "mailbox_category": "AP",
        }, location_code="MSC")
        # MSC explicit operator signal → "Miscellaneous" is the documented
        # final destination. The reason string starts with "LocationCode=MSC",
        # not "Default routing for", so the weak-fallback wrapper does NOT
        # redirect.
        assert "Miscellaneous" in path


# ---------------------------------------------------------------------------
# 2. Weak-fallback AP-lane redirects to Temp Folder (NOT Misc)
# ---------------------------------------------------------------------------

class TestWeakFallbackRedirect:

    def test_ap_invoice_no_signals_redirects_to_temp_folder(self):
        """AP invoice with a contradicting/uncertain signal (BC says the
        PO does not exist) → was Misc/need-approval; the wrapper redirects
        to AP Temp Folder for review."""
        path, reason, details = _route({
            "document_type": "AP_Invoice",
            "doc_type": "AP_INVOICE",
            "vendor_canonical": "RandomVendor",
            "mailbox_category": "AP",
            "extracted_fields": {"po_number": "PO-MISSING", "order_number": "PO-MISSING"},
            "bc_po_resolved": False,
        })
        assert path == AP_STAGING_FOLDER
        assert "weak-fallback" in reason
        assert "weak_fallback_redirect_from" in details

    def test_ap_invoice_unresolved_po_redirects_to_temp_folder(self):
        """bc_po_resolved=False is a contradicting signal → was Misc/need-
        approval; redirects to Temp Folder for review."""
        path, _, _ = _route({
            "document_type": "AP_Invoice",
            "doc_type": "AP_INVOICE",
            "vendor_canonical": "Some Vendor",
            "mailbox_category": "AP",
            "extracted_fields": {"po_number": "PO99999", "order_number": "PO99999"},
            "bc_po_resolved": False,
        })
        assert path == AP_STAGING_FOLDER

    def test_non_ap_doc_with_no_signals_keeps_misc_fallback(self):
        """Non-AP-lane docs are NOT redirected by the wrapper. They keep
        the legacy Default-routing/Misc behavior."""
        path, _, _ = _route({
            "document_type": "Unknown",
            "vendor_canonical": "RandomVendor",
            "extracted_fields": {},
        })
        assert "Miscellaneous" in path
        assert path != AP_STAGING_FOLDER


# ---------------------------------------------------------------------------
# 3. Mailbox-lane needs-review routing
# ---------------------------------------------------------------------------

class TestMailboxLaneNeedsReview:

    def test_ap_lane_needs_review_goes_to_review_folder(self):
        path, reason, _ = _route({
            "document_type": "Other",
            "doc_type": "OTHER",
            "mailbox_category": "AP",
            "mailbox_lane_needs_review": True,
        })
        assert path == AP_LANE_REVIEW_FOLDER
        assert "AP review" in reason or "AP-lane" in reason

    def test_sales_lane_needs_review_does_not_drop_into_misc(self):
        path, _, _ = _route({
            "document_type": "Other",
            "doc_type": "OTHER",
            "mailbox_category": "Sales",
            "mailbox_lane_needs_review": True,
        })
        assert path == AP_LANE_REVIEW_FOLDER

    def test_operations_lane_unchanged(self):
        """Operations lane docs flow through normal warehouse/shipping
        rules; the AP review fallback does NOT trigger for them."""
        path, _, _ = _route({
            "document_type": "Shipping_Document",
            "doc_type": "OTHER",
            "mailbox_category": "Operations",
            "vendor_canonical": "Some Carrier",
            "extracted_fields": {"po_number": "PO99", "order_number": "PO99"},
        })
        assert path != AP_STAGING_FOLDER
        assert path != AP_LANE_REVIEW_FOLDER


# ---------------------------------------------------------------------------
# 4. Accounting override force-bypasses the weak-fallback wrapper
# ---------------------------------------------------------------------------

class TestAccountingOverrideForceBypass:
    """Override is now an opt-out from the weak-fallback wrapper for the
    rare case where accounting wants an AP-lane doc to land in the legacy
    Misc bucket regardless. Almost never used in practice."""

    def test_override_keeps_misc_fallback(self):
        path, _, _ = _route({
            "document_type": "AP_Invoice",
            "doc_type": "AP_INVOICE",
            "vendor_canonical": "RandomVendor",
            "mailbox_category": "AP",
            "extracted_fields": {"po_number": "PO-MISSING", "order_number": "PO-MISSING"},
            "bc_po_resolved": False,
            "accounting_routing_override": True,
        })
        assert "Miscellaneous" in path
        assert path != AP_STAGING_FOLDER

    def test_approved_keeps_misc_fallback(self):
        path, _, _ = _route({
            "document_type": "AP_Invoice",
            "doc_type": "AP_INVOICE",
            "vendor_canonical": "RandomVendor",
            "mailbox_category": "AP",
            "extracted_fields": {"po_number": "PO-MISSING", "order_number": "PO-MISSING"},
            "bc_po_resolved": False,
            "approved": True,
        })
        assert "Miscellaneous" in path


# ---------------------------------------------------------------------------
# 5. Non-AP doc types unchanged
# ---------------------------------------------------------------------------

class TestNonAPRoutingUnchanged:
    def test_inventory_report_routes_to_warehouse_reports(self):
        path, _, _ = _route({
            "document_type": "Inventory_Report",
            "doc_type": "OTHER",
            "vendor_canonical": "Some Vendor",
        })
        assert path.startswith("Warehouse Reports")
