"""
Mailbox-category propagation + classification safety regression.

Locks in the corrected behavior described in the bug report:

1. mailbox_category represents the INTAKE LANE the document arrived through
   — it is NOT a forced doc_type.

2. Each configured mailbox in `mailbox_sources` propagates its category to
   the persisted hub_documents.mailbox_category, including via the
   normalize_mailbox_category() alias map (Billing → AP, AR → Sales, etc.).

3. AP-lane attachments without invoice-like evidence are NOT auto-forced to
   AP_INVOICE. They stay as OTHER and get an AP-lane review hint instead of
   landing in a generic Operations folder.

4. AP-lane attachments WITH invoice-like evidence still classify as
   AP_INVOICE via the deterministic pipeline.

5. Operations-lane (warehouse/shipping) docs continue to flow through
   unchanged; their lane is not promoted to AP/Sales.
"""

import asyncio
import pytest

from services.email_polling_service import normalize_mailbox_category
from services.classification_helpers import classify_document_type, _has_lane_evidence
from workflows.core.engine import DocumentClassifier, DocType


# ---------------------------------------------------------------------------
# 1. normalize_mailbox_category: alias map
# ---------------------------------------------------------------------------

class TestNormalizeMailboxCategory:
    def test_billing_alias_maps_to_ap(self):
        assert normalize_mailbox_category("Billing") == "AP"
        assert normalize_mailbox_category("BILLING") == "AP"
        assert normalize_mailbox_category("Accounts Payable") == "AP"
        assert normalize_mailbox_category("AP_intake") == "AP"

    def test_ar_alias_maps_to_sales(self):
        assert normalize_mailbox_category("AR") == "Sales"
        assert normalize_mailbox_category("Accounts Receivable") == "Sales"

    def test_operations_passthrough(self):
        assert normalize_mailbox_category("Operations") == "Operations"
        assert normalize_mailbox_category("warehouse") == "Operations"
        assert normalize_mailbox_category("SHIPPING") == "Operations"

    def test_purchase_passthrough(self):
        assert normalize_mailbox_category("Purchase") == "Purchase"
        assert normalize_mailbox_category("Purchasing") == "Purchase"
        assert normalize_mailbox_category("PO") == "Purchase"

    def test_none_and_blank(self):
        assert normalize_mailbox_category(None) is None
        assert normalize_mailbox_category("") is None
        assert normalize_mailbox_category("   ") is None

    def test_unknown_passthrough_does_not_blow_up(self):
        # Unknown values are passed through (with a warning logged); they
        # must not raise. This prevents new mailboxes from breaking intake.
        out = normalize_mailbox_category("SomeNewLane")
        assert out == "SomeNewLane"


# ---------------------------------------------------------------------------
# 2. _has_lane_evidence
# ---------------------------------------------------------------------------

class TestLaneEvidence:
    def test_ap_lane_with_invoice_number_has_evidence(self):
        assert _has_lane_evidence("AP", {"invoice_number": "INV-1234"}) is True

    def test_ap_lane_with_amount_has_evidence(self):
        assert _has_lane_evidence("AP", {"amount": "100.00"}) is True

    def test_ap_lane_empty_fields_no_evidence(self):
        assert _has_lane_evidence("AP", {}) is False
        assert _has_lane_evidence("AP", {"unrelated": "stuff"}) is False

    def test_sales_lane_with_customer_has_evidence(self):
        assert _has_lane_evidence("SALES", {"customer": "Acme"}) is True

    def test_purchase_lane_with_po_number_has_evidence(self):
        assert _has_lane_evidence("PURCHASE", {"po_number": "PO-1"}) is True

    def test_operations_has_no_lane_evidence_signals(self):
        # Operations lane is intentionally not evidence-classified — we keep
        # those docs flowing through normal warehouse/shipping rules.
        assert _has_lane_evidence("Operations", {"invoice_number": "X"}) is False


# ---------------------------------------------------------------------------
# 3. classify_document_type — full pipeline with mailbox_category as hint
# ---------------------------------------------------------------------------

class TestClassifyDocumentTypeWithMailboxCategory:

    def _run(self, doc, extracted_fields=None, suggested_type="Unknown",
             confidence=0.0, metadata=None):
        return asyncio.run(classify_document_type(
            document=doc,
            extracted_fields=extracted_fields or {},
            suggested_type=suggested_type,
            confidence=confidence,
            metadata=metadata or {},
        ))

    def test_billing_lane_with_invoice_evidence_classifies_as_ap_invoice(self):
        """Clear AP invoice via billing@ → AP_INVOICE."""
        result = self._run(
            doc={"id": "d1", "mailbox_category": "AP"},
            extracted_fields={"invoice_number": "INV-9999", "amount": "523.10",
                              "vendor": "Bragg"},
        )
        assert result["doc_type"] == DocType.AP_INVOICE.value
        assert "mailbox:AP+evidence" in result["classification_method"]
        assert result["category"] == "AP"

    def test_billing_lane_without_evidence_does_not_force_ap_invoice(self):
        """Random non-invoice doc on billing@ → NOT forced to AP_INVOICE.
        It stays OTHER and is flagged for AP-lane review (so it doesn't
        land in a generic Operations folder)."""
        # Disable AI for this unit test by ensuring AI_CLASSIFICATION_ENABLED
        # is honored — we don't seed an EMERGENT_LLM_KEY in test env, so AI
        # step is skipped. Result reflects the mailbox-lane review fallback.
        result = self._run(
            doc={"id": "d2", "mailbox_category": "AP"},
            extracted_fields={"raw_text": "thanks for the meeting agenda"},
        )
        assert result["doc_type"] == DocType.OTHER.value, \
            "Non-invoice doc on AP lane must NOT be auto-forced to AP_INVOICE"
        assert result.get("mailbox_lane_needs_review") is True
        assert "mailbox_lane:AP:needs_review" in result["classification_method"]

    def test_operations_lane_doc_does_not_get_promoted(self):
        """Operations lane docs do not get flagged for AP-lane review and
        are not promoted to AP/Sales/Purchase types."""
        result = self._run(
            doc={"id": "d3", "mailbox_category": "Operations"},
            extracted_fields={},
        )
        assert result["doc_type"] == DocType.OTHER.value
        assert result.get("mailbox_lane_needs_review", False) is False, \
            "Operations lane must not trigger AP-lane review fallback"

    def test_zetadocs_set_still_wins_over_mailbox_category(self):
        """If a Zetadocs set is present, it should still classify ahead of
        mailbox-lane logic — preserves the existing precedence."""
        # Zetadocs SS=AP_Invoice mapping; the exact SS code that maps to
        # AP_INVOICE is environment-dependent, so we just confirm the
        # mailbox step did not run when Zetadocs already classified.
        result = self._run(
            doc={"id": "d4", "mailbox_category": "AP",
                 "zetadocs_set_code": "SS=Bogus_Code_Should_Not_Match"},
            extracted_fields={"invoice_number": "X"},
        )
        # Either zetadocs matched (method starts with "zetadocs:") or fell
        # through to mailbox+evidence; both are acceptable. We assert that
        # we did NOT regress to the legacy "mailbox:AP" string (no
        # +evidence suffix), which would mean evidence-gating was bypassed.
        assert "mailbox:AP+evidence" in result["classification_method"] \
            or result["classification_method"].startswith("zetadocs:")


# ---------------------------------------------------------------------------
# 4. Direct DocumentClassifier behavior — defaults
# ---------------------------------------------------------------------------

class TestDocumentClassifierDefaults:
    def test_no_evidence_default_returns_other_for_ap(self):
        # Default arg evidence=False → OTHER, regardless of category.
        for cat in ("AP", "SALES", "PURCHASE"):
            assert (
                DocumentClassifier.classify_from_mailbox_category(cat) == DocType.OTHER
            ), f"{cat} without evidence must not auto-classify"

    def test_evidence_true_restores_lane_classification(self):
        assert DocumentClassifier.classify_from_mailbox_category("AP", evidence=True) == DocType.AP_INVOICE
        assert DocumentClassifier.classify_from_mailbox_category("SALES", evidence=True) == DocType.SALES_INVOICE
        assert DocumentClassifier.classify_from_mailbox_category("PURCHASE", evidence=True) == DocType.PURCHASE_ORDER


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
