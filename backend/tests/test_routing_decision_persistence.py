"""
Regression test: routing decisions are persisted on hub_documents at intake
time, not synthesized after the fact.

This test exercises the intake-path persistence pattern by:
  - building the same routing_input_doc shape used inside
    services.document_handlers.intake_document_from_bytes
    (and the parallel _process_email_intake path), and
  - calling services.folder_routing_service.determine_ap_routing_decision
    directly to confirm the persisted shape is correct and complete.

This is a unit-level lock on the persistence contract. Full end-to-end
coverage is operational (run a billing poll, then read hub_documents and
assert routing_status / routing_reason / routing_details are present —
captured in scripts/ap_cutover_readiness_report.py).
"""

from services.folder_routing_service import (
    determine_ap_routing_decision,
    AP_STAGING_FOLDER,
    AP_LANE_REVIEW_FOLDER,
    ROUTING_STATUS_AUTO_ROUTED,
    ROUTING_STATUS_NEEDS_REVIEW,
    ROUTING_STATUS_MANUAL_OVERRIDE,
)


REQUIRED_AUDIT_FIELDS = (
    "mailbox_category",
    "doc_type",
    "suggested_job_type",
    "classification_method",
    "ai_confidence",
    "vendor_canonical",
    "evidence_signals_used",
    "manual_override_applied",
    "mailbox_lane_needs_review",
)


def _intake_shape(**overrides):
    """Same shape `intake_document_from_bytes` builds when calling
    determine_ap_routing_decision at the persistence point. Keeping it in
    one place here so a future intake change has to break this test."""
    base = {
        "document_type": "AP_Invoice",
        "doc_type": "AP_INVOICE",
        "suggested_job_type": "AP_Invoice",
        "mailbox_category": "AP",
        "mailbox_lane_needs_review": False,
        "classification_method": "mailbox:AP+evidence",
        "ai_confidence": 0.94,
        "vendor_canonical": "Canpack USA",
        "vendor_match_method": "alias",
        "po_number_clean": "PO12345",
        "po_number_extracted": "PO12345",
        "invoice_number_clean": "INV-99",
        "amount_float": 1234.56,
        "validation_results": {"all_passed": True, "bc_po_resolved": True},
        "possible_duplicate": False,
        "extracted_fields": {"description": "Canpack delivery", "po_number": "PO12345"},
        "normalized_fields": {"po_number_clean": "PO12345"},
        "file_name": "Canpack_Invoice_99.pdf",
        "bc_po_resolved": True,
        "accounting_routing_override": False,
        "approved": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Persistence shape: every call to the decision function returns the
#    fields the intake path persists.
# ---------------------------------------------------------------------------

class TestPersistenceShape:

    def test_decision_keys_match_persisted_fields(self):
        d = determine_ap_routing_decision(_intake_shape())
        # These three top-level keys are exactly what intake assigns to
        # update_data["routing_status"|"routing_reason"|"routing_details"].
        for k in ("folder_path", "routing_status", "routing_reason", "routing_details"):
            assert k in d

    def test_routing_reason_is_non_empty(self):
        d = determine_ap_routing_decision(_intake_shape())
        assert d["routing_reason"]
        assert isinstance(d["routing_reason"], str)
        assert len(d["routing_reason"]) > 0

    def test_routing_details_carries_required_audit_fields(self):
        d = determine_ap_routing_decision(_intake_shape())
        rd = d["routing_details"]
        for k in REQUIRED_AUDIT_FIELDS:
            assert k in rd, f"routing_details must include '{k}' (intake persistence contract)"

    def test_evidence_signals_used_is_list(self):
        d = determine_ap_routing_decision(_intake_shape())
        signals = d["routing_details"]["evidence_signals_used"]
        assert isinstance(signals, list)
        # high-confidence Canpack input → at least vendor_canonical and PO
        assert "vendor_canonical" in signals
        assert "po_number" in signals


# ---------------------------------------------------------------------------
# 2. Status correctness across the four intake scenarios
# ---------------------------------------------------------------------------

class TestStatusCorrectness:

    def test_high_confidence_ap_invoice_persists_auto_routed(self):
        """billing@ + Canpack vendor + clean PO → auto_routed at intake."""
        d = determine_ap_routing_decision(_intake_shape())
        assert d["routing_status"] == ROUTING_STATUS_AUTO_ROUTED
        assert d["folder_path"].startswith("Dropship Not International Documents/Canpack")

    def test_unresolved_po_persists_needs_review(self):
        """BC contradicts → needs_review at intake (no human re-derivation)."""
        d = determine_ap_routing_decision(_intake_shape(
            vendor_canonical="Some Vendor",
            extracted_fields={"po_number": "PO99999", "order_number": "PO99999"},
            validation_results={"all_passed": False, "bc_po_resolved": False},
            bc_po_resolved=False,
            file_name="Random.pdf",
        ))
        assert d["routing_status"] == ROUTING_STATUS_NEEDS_REVIEW
        assert d["folder_path"] == AP_STAGING_FOLDER

    def test_mailbox_lane_review_persists_needs_review(self):
        """Non-invoice on billing lane → needs_review at intake."""
        d = determine_ap_routing_decision(_intake_shape(
            document_type="Other", doc_type="OTHER", suggested_job_type="Other",
            mailbox_lane_needs_review=True,
            vendor_canonical=None,
            extracted_fields={},
            normalized_fields={},
            po_number_clean=None,
            po_number_extracted=None,
            invoice_number_clean=None,
            file_name="meeting_agenda.pdf",
            bc_po_resolved=None,
        ))
        assert d["routing_status"] == ROUTING_STATUS_NEEDS_REVIEW
        assert d["folder_path"] == AP_LANE_REVIEW_FOLDER

    def test_manual_override_persists_override_status(self):
        d = determine_ap_routing_decision(_intake_shape(
            vendor_canonical="RandomVendor",
            extracted_fields={"po_number": "PO-MISSING", "order_number": "PO-MISSING"},
            validation_results={"all_passed": False, "bc_po_resolved": False},
            bc_po_resolved=False,
            accounting_routing_override=True,
            file_name="random.pdf",
        ))
        assert d["routing_status"] == ROUTING_STATUS_MANUAL_OVERRIDE
        assert d["routing_details"]["manual_override_applied"] is True


# ---------------------------------------------------------------------------
# 3. Audit field values are populated, not None when input has them
# ---------------------------------------------------------------------------

class TestAuditFieldsPopulated:

    def test_audit_fields_carry_input_values(self):
        d = determine_ap_routing_decision(_intake_shape(
            mailbox_category="AP",
            classification_method="mailbox:AP+evidence",
            ai_confidence=0.93,
            vendor_canonical="Canpack USA",
        ))
        rd = d["routing_details"]
        assert rd["mailbox_category"] == "AP"
        assert rd["classification_method"] == "mailbox:AP+evidence"
        assert rd["ai_confidence"] == 0.93
        assert rd["vendor_canonical"] == "Canpack USA"
        assert rd["doc_type"] == "AP_INVOICE"
        assert rd["suggested_job_type"] == "AP_Invoice"
        assert rd["manual_override_applied"] is False
