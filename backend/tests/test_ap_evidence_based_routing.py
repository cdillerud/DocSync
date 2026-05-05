"""
Evidence-based AP routing decision contract.

Locks in the structured routing decision in
:func:`services.folder_routing_service.determine_ap_routing_decision` and
the GPI Hub mission alignment:

- billing@ → mailbox_category="AP" (preserved)
- mailbox_category="AP" is *source context*, not a forced doc_type.
- High-confidence AP invoices auto-route to the correct final accounting
  folder (status="auto_routed"), no manual approval required.
- Low-confidence / contradictory / lane-mismatched documents route to AP
  review (status="needs_review").
- AP-lane scatter guard (defense-in-depth) blocks any AP-lane landing in
  an Operations folder root unless the routing reason carries a strong
  AP-rule signal; status="exception".
- accounting_routing_override / approved=True → status="manual_override".
- Existing non-AP routing unchanged.
"""

from services.folder_routing_service import (
    determine_ap_routing_decision,
    AP_STAGING_FOLDER,
    AP_LANE_REVIEW_FOLDER,
    ROUTING_STATUS_AUTO_ROUTED,
    ROUTING_STATUS_NEEDS_REVIEW,
    ROUTING_STATUS_EXCEPTION,
    ROUTING_STATUS_MANUAL_OVERRIDE,
)


def _decide(doc, **kwargs):
    return determine_ap_routing_decision(doc, **kwargs)


# ---------------------------------------------------------------------------
# Contract: decision shape
# ---------------------------------------------------------------------------

class TestDecisionShape:
    def test_returns_required_keys(self):
        d = _decide({
            "document_type": "AP_Invoice", "doc_type": "AP_INVOICE",
            "vendor_canonical": "Canpack USA", "mailbox_category": "AP",
            "extracted_fields": {"description": "Canpack delivery"},
        })
        assert set(d.keys()) == {"folder_path", "routing_status", "routing_reason", "routing_details"}

    def test_routing_details_carries_audit_fields(self):
        d = _decide({
            "document_type": "AP_Invoice", "doc_type": "AP_INVOICE",
            "vendor_canonical": "Canpack USA", "mailbox_category": "AP",
            "ai_confidence": 0.94, "classification_method": "mailbox:AP+evidence",
            "po_number_extracted": "PO-1234", "invoice_number_clean": "INV-9",
            "extracted_fields": {"description": "Canpack delivery"},
        })
        rd = d["routing_details"]
        for k in ("mailbox_category", "doc_type", "classification_method",
                  "ai_confidence", "vendor_canonical", "po_number_clean",
                  "invoice_number_clean", "manual_override_applied",
                  "evidence_signals_used", "mailbox_lane_needs_review"):
            assert k in rd, f"missing audit field: {k}"
        assert "vendor_canonical" in rd["evidence_signals_used"]
        assert "po_number" in rd["evidence_signals_used"]


# ---------------------------------------------------------------------------
# auto_routed: high-confidence AP invoices reach final destinations
# ---------------------------------------------------------------------------

class TestAutoRoutedHighConfidence:

    def test_canpack_vendor_auto_routes(self):
        d = _decide({
            "document_type": "AP_Invoice", "doc_type": "AP_INVOICE",
            "vendor_canonical": "Canpack USA", "mailbox_category": "AP",
            "extracted_fields": {"description": "Canpack delivery"},
        })
        assert d["routing_status"] == ROUTING_STATUS_AUTO_ROUTED
        assert d["folder_path"].startswith("Dropship Not International Documents/Canpack")

    def test_credit_memo_description_auto_routes(self):
        d = _decide({
            "document_type": "AP_Invoice", "doc_type": "AP_INVOICE",
            "vendor_canonical": "Anchor Glass", "mailbox_category": "AP",
            "extracted_fields": {"description": "credit memo refund adjustment"},
        })
        assert d["routing_status"] == ROUTING_STATUS_AUTO_ROUTED
        assert d["folder_path"].startswith("Vendor Credit Memos")

    def test_wh_pattern_auto_routes_to_warehouse(self):
        d = _decide({
            "file_name": "WH_112320_Ball_PO88701_031192026.pdf",
            "document_type": "AP_Invoice", "doc_type": "AP_INVOICE",
            "vendor_canonical": "BALL CORPORATION",
            "mailbox_category": "AP",
            "extracted_fields": {"order_number": "PO88701"},
        })
        assert d["routing_status"] == ROUTING_STATUS_AUTO_ROUTED
        assert "Warehouse" in d["folder_path"]
        assert "filename_pattern" in d["routing_details"]["evidence_signals_used"]

    def test_resolved_bc_po_auto_routes(self):
        d = _decide({
            "document_type": "AP_Invoice", "doc_type": "AP_INVOICE",
            "vendor_canonical": "Some Vendor", "mailbox_category": "AP",
            "extracted_fields": {"po_number": "PO12345", "order_number": "PO12345"},
            "bc_po_resolved": True,
        })
        assert d["routing_status"] == ROUTING_STATUS_AUTO_ROUTED
        assert "bc_po_resolved" in d["routing_details"]["evidence_signals_used"]


# ---------------------------------------------------------------------------
# needs_review: weak / contradictory / lane-mismatched docs
# ---------------------------------------------------------------------------

class TestNeedsReview:

    def test_unresolved_bc_po_routes_to_review(self):
        """BC contradicts the vendor signal → review, not silent Misc."""
        d = _decide({
            "document_type": "AP_Invoice", "doc_type": "AP_INVOICE",
            "vendor_canonical": "Some Vendor", "mailbox_category": "AP",
            "extracted_fields": {"po_number": "PO99999", "order_number": "PO99999"},
            "bc_po_resolved": False,
        })
        assert d["routing_status"] == ROUTING_STATUS_NEEDS_REVIEW
        assert d["folder_path"] == AP_STAGING_FOLDER

    def test_non_invoice_on_billing_lane_routes_to_review(self):
        """mailbox_lane_needs_review=True (set by classifier) → AP review
        folder, never Operations."""
        d = _decide({
            "document_type": "Other", "doc_type": "OTHER",
            "mailbox_category": "AP",
            "mailbox_lane_needs_review": True,
        })
        assert d["routing_status"] == ROUTING_STATUS_NEEDS_REVIEW
        assert d["folder_path"] == AP_LANE_REVIEW_FOLDER

    def test_sales_lane_mismatch_routes_to_review(self):
        d = _decide({
            "document_type": "Other", "doc_type": "OTHER",
            "mailbox_category": "Sales",
            "mailbox_lane_needs_review": True,
        })
        assert d["routing_status"] == ROUTING_STATUS_NEEDS_REVIEW
        assert d["folder_path"] == AP_LANE_REVIEW_FOLDER


# ---------------------------------------------------------------------------
# manual_override: opt-out from the AP-lane guards
# ---------------------------------------------------------------------------

class TestManualOverride:

    def test_override_keeps_misc_landing_with_override_status(self):
        d = _decide({
            "document_type": "AP_Invoice", "doc_type": "AP_INVOICE",
            "vendor_canonical": "RandomVendor", "mailbox_category": "AP",
            "extracted_fields": {"po_number": "PO-MISSING", "order_number": "PO-MISSING"},
            "bc_po_resolved": False,
            "accounting_routing_override": True,
        })
        assert d["routing_status"] == ROUTING_STATUS_MANUAL_OVERRIDE
        assert "Miscellaneous" in d["folder_path"]
        assert d["routing_details"]["manual_override_applied"] is True


# ---------------------------------------------------------------------------
# Non-AP routing unchanged
# ---------------------------------------------------------------------------

class TestNonAPUnchanged:

    def test_inventory_report_auto_routes(self):
        d = _decide({
            "document_type": "Inventory_Report", "doc_type": "OTHER",
            "vendor_canonical": "Some Vendor",
        })
        assert d["routing_status"] == ROUTING_STATUS_AUTO_ROUTED
        assert d["folder_path"].startswith("Warehouse Reports")

    def test_shipping_doc_unresolved_po_keeps_misc(self):
        """Shipping_Document with unresolved PO is non-AP → still keeps
        legacy Misc routing (only AP-lane docs are redirected)."""
        d = _decide({
            "document_type": "Shipping_Document", "doc_type": "OTHER",
            "vendor_canonical": "Some Vendor",
            "extracted_fields": {"po_number": "158491", "order_number": "158491"},
            "bc_po_resolved": False,
        })
        # Non-AP doc → guard does not fire; routing_status reflects what
        # the rule chain produced (auto_routed for the rule's chosen path).
        assert d["routing_status"] == ROUTING_STATUS_AUTO_ROUTED
        assert "Miscellaneous" in d["folder_path"]
