"""
Routing regression test for AP-lane Square9 parity.

Locks in the corrected behavior in services.folder_routing_service:

1. AP-lane invoices (doc_type AP_INVOICE / AP_Invoice / AP Invoice) without
   accounting_routing_override / approved=True default to the AP Temp Folder
   (Square9 parity destination).
2. AP-lane invoices NEVER auto-route into Operations-style folders
   (Warehouse Reports, Dropship*, Warehouse*, Freight Issues, Vendor Credit
   Memos, Miscellaneous) on the auto-ingest path.
3. Documents flagged mailbox_lane_needs_review=True on the AP lane go to
   the AP review subfolder, not Misc / Operations.
4. accounting_routing_override=True (or approved=True) restores the
   detailed accounting structure (e.g. Canpack vendor → Dropship/Canpack).
5. Non-AP documents (Sales_Order, Shipping_Document, Credit_Memo with no
   AP doc type) keep their existing routing.
"""

from services.folder_routing_service import (
    determine_folder_path,
    AP_STAGING_FOLDER,
    AP_LANE_REVIEW_FOLDER,
    _FORBIDDEN_AP_FOLDER_ROOTS,
)


def _route(doc, **kwargs):
    return determine_folder_path(doc, **kwargs)


# ---------------------------------------------------------------------------
# 1. AP-lane staging defaults
# ---------------------------------------------------------------------------

class TestAPStagingDefault:
    def test_ap_invoice_uppercase_doc_type_stages_to_temp_folder(self):
        path, reason, _ = _route({
            "doc_type": "AP_INVOICE",
            "document_type": "AP_Invoice",
            "suggested_job_type": "AP_Invoice",
            "mailbox_category": "AP",
        })
        assert path == AP_STAGING_FOLDER
        assert "AP Temp Folder" in reason

    def test_ap_invoice_with_canpack_vendor_still_stages(self):
        """Canpack rule used to fire first; staging guard now overrides
        until accounting opts in via accounting_routing_override=True."""
        path, _, _ = _route({
            "doc_type": "AP_INVOICE",
            "document_type": "AP_Invoice",
            "vendor_canonical": "Canpack USA",
            "mailbox_category": "AP",
            "extracted_fields": {"description": "Canpack delivery"},
        })
        assert path == AP_STAGING_FOLDER, (
            "AP-lane Canpack invoice must stage in AP Temp Folder by default; "
            "Canpack-specific routing only after accounting override"
        )

    def test_ap_invoice_with_freight_carrier_vendor_still_stages(self):
        """Freight Issues used to fire when vendor matched UPS/FedEx/etc.
        Now AP-lane invoices stage first regardless of vendor lookup."""
        path, _, _ = _route({
            "doc_type": "AP_INVOICE",
            "document_type": "AP_Invoice",
            "vendor_canonical": "UPS",
            "mailbox_category": "AP",
        })
        assert path == AP_STAGING_FOLDER

    def test_ap_invoice_with_credit_memo_keywords_still_stages(self):
        path, _, _ = _route({
            "doc_type": "AP_INVOICE",
            "document_type": "AP_Invoice",
            "mailbox_category": "AP",
            "extracted_fields": {"description": "Credit memo for return"},
        })
        assert path == AP_STAGING_FOLDER


# ---------------------------------------------------------------------------
# 2. Forbidden destinations on auto-ingest
# ---------------------------------------------------------------------------

class TestAPInvoiceForbiddenDestinations:
    """No path returned for an auto-ingest AP_INVOICE may live under any of
    the Operations-style folder roots."""

    def _assert_not_forbidden(self, path):
        assert not any(path.startswith(root) for root in _FORBIDDEN_AP_FOLDER_ROOTS), (
            f"AP-lane auto-ingest must not land in {path!r}"
        )

    def test_ap_invoice_canpack_not_in_dropship(self):
        path, _, _ = _route({
            "doc_type": "AP_INVOICE",
            "document_type": "AP_Invoice",
            "vendor_canonical": "Canpack USA",
            "mailbox_category": "AP",
        })
        self._assert_not_forbidden(path)

    def test_ap_invoice_freight_vendor_not_in_freight_issues(self):
        path, _, _ = _route({
            "doc_type": "AP_INVOICE",
            "document_type": "AP_Invoice",
            "vendor_canonical": "FedEx Freight",
            "mailbox_category": "AP",
        })
        self._assert_not_forbidden(path)

    def test_ap_invoice_credit_memo_not_in_vendor_credit_memos(self):
        path, _, _ = _route({
            "doc_type": "AP_INVOICE",
            "document_type": "AP_Invoice",
            "mailbox_category": "AP",
            "extracted_fields": {"description": "credit memo refund adjustment"},
        })
        self._assert_not_forbidden(path)

    def test_ap_invoice_warehouse_order_not_in_warehouse_documents(self):
        path, _, _ = _route({
            "doc_type": "AP_INVOICE",
            "document_type": "AP_Invoice",
            "vendor_canonical": "Some Vendor",
            "mailbox_category": "AP",
            "is_warehouse_order": True,
            "po_number_extracted": "PO-12345",
        })
        self._assert_not_forbidden(path)

    def test_ap_invoice_unknown_po_does_not_drop_to_misc(self):
        """Previously: PO not in BC → Misc/Misc Invoices - need approval.
        Now: stays in AP staging regardless until accounting reviews."""
        path, _, _ = _route({
            "doc_type": "AP_INVOICE",
            "document_type": "AP_Invoice",
            "mailbox_category": "AP",
            "po_number_extracted": "PO-MISSING",
            "bc_po_resolved": False,
        })
        self._assert_not_forbidden(path)


# ---------------------------------------------------------------------------
# 3. Mailbox-lane needs-review routing
# ---------------------------------------------------------------------------

class TestMailboxLaneNeedsReview:
    def test_ap_lane_needs_review_goes_to_ap_review_folder(self):
        path, reason, _ = _route({
            "document_type": "Other",
            "doc_type": "OTHER",
            "mailbox_category": "AP",
            "mailbox_lane_needs_review": True,
        })
        assert path == AP_LANE_REVIEW_FOLDER
        assert "AP review" in reason or "AP-lane" in reason

    def test_sales_lane_needs_review_does_not_drop_into_operations(self):
        path, _, _ = _route({
            "document_type": "Other",
            "doc_type": "OTHER",
            "mailbox_category": "Sales",
            "mailbox_lane_needs_review": True,
        })
        assert not any(path.startswith(root) for root in _FORBIDDEN_AP_FOLDER_ROOTS)

    def test_operations_lane_no_review_hint_routes_normally(self):
        """Operations lane docs do not get AP-review treatment — they flow
        through normal warehouse/shipping rules. (Sanity check: routing
        does not raise and does not assert AP staging.)"""
        path, _, _ = _route({
            "document_type": "Shipping_Document",
            "doc_type": "OTHER",
            "mailbox_category": "Operations",
            "vendor_canonical": "Some Carrier",
        })
        assert path != AP_STAGING_FOLDER
        assert path != AP_LANE_REVIEW_FOLDER


# ---------------------------------------------------------------------------
# 4. Accounting override restores the detailed structure
# ---------------------------------------------------------------------------

class TestAccountingOverrideRestoresDetailedRouting:
    def test_override_canpack_routes_to_dropship_canpack(self):
        path, reason, _ = _route({
            "document_type": "AP_Invoice",
            "doc_type": "AP_INVOICE",
            "vendor_canonical": "Canpack USA",
            "mailbox_category": "AP",
            "extracted_fields": {"description": "Canpack delivery"},
            "accounting_routing_override": True,
        })
        assert path.startswith("Dropship Not International Documents/Canpack")

    def test_approved_credit_memo_routes_to_vendor_credit_memos(self):
        path, _, _ = _route({
            "document_type": "AP_Invoice",
            "doc_type": "AP_INVOICE",
            "vendor_canonical": "Anchor",
            "mailbox_category": "AP",
            "extracted_fields": {"description": "credit memo"},
            "approved": True,
        })
        assert path.startswith("Vendor Credit Memos")


# ---------------------------------------------------------------------------
# 5. Non-AP doc types keep their existing routing (no regression)
# ---------------------------------------------------------------------------

class TestNonAPRoutingUnchanged:
    def test_sales_order_with_warehouse_order_routes_to_warehouse(self):
        path, _, _ = _route({
            "document_type": "Sales_Order",
            "doc_type": "SALES_INVOICE",
            "vendor_canonical": "Customer X",
            "is_warehouse_order": True,
            "po_number_extracted": "SO-99",
            "mailbox_category": "Sales",
        })
        # Sales orders still flow through their own rule.
        assert AP_STAGING_FOLDER not in path

    def test_inventory_report_routes_to_warehouse_reports(self):
        path, _, _ = _route({
            "document_type": "Inventory_Report",
            "doc_type": "OTHER",
            "vendor_canonical": "Some Vendor",
        })
        assert path.startswith("Warehouse Reports")
