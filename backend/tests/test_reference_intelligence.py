"""Regression tests for Reference Intelligence scoring.

Tests the new domain-aware, multi-signal scoring system:
- Domain classification (Requirement 1)
- Source doc type awareness (Requirement 2)
- Context gate (Requirement 3)
- Reference semantic typing (Requirement 4)
- Reduced naked number weight (Requirement 5)
- Counterparty consistency (Requirement 6)
- Two-signal minimum for Likely Match (Requirement 7)
- Surfaced/suppressed/rejected states (Requirement 8)
- Explainable scoring output (Requirement 9)
- Updated labels (Requirement 10)
"""

import pytest
import sys
sys.path.insert(0, "/app/backend")

from services.reference_intelligence_service import (
    score_bc_match,
    determine_match_outcome,
    determine_candidate_state,
    ReferenceCandidate,
    BCMatch,
    MatchOutcome,
    SourceDocumentType,
    CandidateDomain,
    CandidateState,
    ReferenceSemanticType,
    ReferenceLabel,
)


def make_candidate(ref_value="110353", label="PO", confidence=0.85,
                    predicted_domain="purchase", predicted_entity_types=None,
                    semantic_type=None):
    if predicted_entity_types is None:
        predicted_entity_types = ["purchase_order"]
    if semantic_type is None:
        semantic_type = ReferenceSemanticType.PO_NUMBER.value
    return ReferenceCandidate(
        reference_value_raw=ref_value,
        reference_value_normalized=ref_value,
        detected_label=label,
        source_text=f"PO: {ref_value}",
        confidence=confidence,
        predicted_domain=predicted_domain,
        predicted_entity_types=predicted_entity_types,
        semantic_type=semantic_type,
    )


def make_bc_record(number="110353", vendor_name="", customer_name=""):
    return {"number": number, "vendorName": vendor_name, "customerName": customer_name}


def make_document(doc_type="AP_Invoice", vendor_raw="PGP Glass USA, Inc.", category="AP"):
    return {"id": "test-doc-001", "document_type": doc_type, "vendor_raw": vendor_raw, "category": category}


class TestCriticalRegression:
    def test_ap_invoice_po_vs_sales_shipment(self):
        candidate = make_candidate(ref_value="110353")
        doc = make_document(vendor_raw="PGP Glass USA, Inc.")
        purchase_record = make_bc_record(number="110353", vendor_name="PGP Glass USA, Inc.")
        sales_record = make_bc_record(number="110353", customer_name="Gamer Packaging")

        p_score, _, _, p_domain, _, p_pos, _ = score_bc_match(
            candidate, purchase_record, "purchase_order", doc,
            source_doc_type=SourceDocumentType.AP_INVOICE
        )
        s_score, _, _, s_domain, _, _, s_neg = score_bc_match(
            candidate, sales_record, "sales_shipment", doc,
            source_doc_type=SourceDocumentType.AP_INVOICE
        )
        assert p_score > s_score
        assert p_domain == CandidateDomain.PURCHASE.value
        assert s_domain == CandidateDomain.SALES.value
        assert "domain_alignment" in p_pos
        assert any("domain_mismatch" in s for s in s_neg)

    def test_sales_side_suppressed_not_likely(self):
        candidate = make_candidate(ref_value="110353")
        doc = make_document()
        sales_record = make_bc_record(number="110353", customer_name="Gamer Packaging")
        s_score, _, _, s_domain, _, s_pos, s_neg = score_bc_match(
            candidate, sales_record, "sales_shipment", doc,
            source_doc_type=SourceDocumentType.AP_INVOICE
        )
        sales_match = BCMatch(
            entity_type="sales_shipment", bc_record_id="test", bc_document_no="110353",
            bc_record_info=sales_record, match_score=s_score, match_reasoning="test",
            candidate_domain=s_domain, positive_signals=s_pos, negative_signals=s_neg,
        )
        outcome = determine_match_outcome(s_score, 1, [s_score], best_match=sales_match, source_doc_type=SourceDocumentType.AP_INVOICE)
        assert outcome != MatchOutcome.LIKELY_MATCH.value
        assert outcome != MatchOutcome.STRONG_MATCH.value
        state = determine_candidate_state(sales_match, SourceDocumentType.AP_INVOICE, outcome)
        assert state in (CandidateState.SUPPRESSED.value, CandidateState.REJECTED.value)


class TestDomainClassification:
    def test_purchase_order_classified_as_purchase(self):
        candidate = make_candidate()
        rec = make_bc_record()
        _, _, _, domain, _, _, _ = score_bc_match(candidate, rec, "purchase_order", make_document(), source_doc_type=SourceDocumentType.AP_INVOICE)
        assert domain == CandidateDomain.PURCHASE.value

    def test_sales_shipment_classified_as_sales(self):
        candidate = make_candidate()
        rec = make_bc_record()
        _, _, _, domain, _, _, _ = score_bc_match(candidate, rec, "sales_shipment", make_document(), source_doc_type=SourceDocumentType.AP_INVOICE)
        assert domain == CandidateDomain.SALES.value


class TestTwoSignalMinimum:
    def test_single_signal_not_likely_match(self):
        match = BCMatch(entity_type="purchase_order", bc_record_id="t", bc_document_no="12345",
            bc_record_info={}, match_score=0.35, match_reasoning="",
            candidate_domain=CandidateDomain.PURCHASE.value,
            positive_signals=["exact_doc_no_match"], negative_signals=[])
        outcome = determine_match_outcome(0.35, 1, [0.35], best_match=match, source_doc_type=SourceDocumentType.AP_INVOICE)
        assert outcome != MatchOutcome.LIKELY_MATCH.value

    def test_two_signals_with_contextual_gets_likely(self):
        match = BCMatch(entity_type="purchase_order", bc_record_id="t", bc_document_no="12345",
            bc_record_info={}, match_score=0.60, match_reasoning="",
            candidate_domain=CandidateDomain.PURCHASE.value,
            positive_signals=["exact_doc_no_match", "domain_alignment"], negative_signals=[])
        outcome = determine_match_outcome(0.60, 1, [0.60], best_match=match, source_doc_type=SourceDocumentType.AP_INVOICE)
        assert outcome == MatchOutcome.LIKELY_MATCH.value


class TestCounterpartyScoring:
    def test_vendor_match_boosts_score(self):
        candidate = make_candidate()
        doc = make_document(vendor_raw="PGP Glass USA, Inc.")
        rec = make_bc_record(vendor_name="PGP Glass USA, Inc.")
        _, _, breakdown, _, _, pos, _ = score_bc_match(candidate, rec, "purchase_order", doc, source_doc_type=SourceDocumentType.AP_INVOICE)
        assert breakdown.get("counterparty_alignment", 0) > 0
        assert "counterparty_alignment" in pos

    def test_counterparty_mismatch_penalizes(self):
        candidate = make_candidate()
        doc = make_document(vendor_raw="PGP Glass USA, Inc.")
        rec = make_bc_record(customer_name="Gamer Packaging")
        _, _, breakdown, _, _, _, neg = score_bc_match(candidate, rec, "sales_shipment", doc, source_doc_type=SourceDocumentType.AP_INVOICE)
        assert breakdown.get("counterparty_alignment", 0) < 0
        assert "counterparty_mismatch" in neg


class TestExplainableScoring:
    def test_score_breakdown_returned(self):
        candidate = make_candidate()
        doc = make_document()
        rec = make_bc_record(vendor_name="PGP Glass USA, Inc.")
        _, _, breakdown, _, _, pos, neg = score_bc_match(candidate, rec, "purchase_order", doc, source_doc_type=SourceDocumentType.AP_INVOICE)
        assert "exact_doc_no_match" in breakdown
        assert "domain_alignment" in breakdown
        assert "counterparty_alignment" in breakdown
        assert "semantic_alignment" in breakdown
        assert isinstance(pos, list)
        assert isinstance(neg, list)


class TestSemanticTyping:
    def test_po_semantic_type_boosts_purchase(self):
        candidate = make_candidate(semantic_type=ReferenceSemanticType.PO_NUMBER.value)
        _, _, breakdown, _, _, pos, _ = score_bc_match(candidate, make_bc_record(), "purchase_order", make_document(), source_doc_type=SourceDocumentType.AP_INVOICE)
        assert breakdown.get("semantic_alignment", 0) > 0

    def test_po_semantic_type_penalizes_sales(self):
        candidate = make_candidate(semantic_type=ReferenceSemanticType.PO_NUMBER.value)
        _, _, breakdown, _, _, _, neg = score_bc_match(candidate, make_bc_record(), "sales_shipment", make_document(), source_doc_type=SourceDocumentType.AP_INVOICE)
        assert breakdown.get("semantic_alignment", 0) < 0


class TestUpdatedLabels:
    def test_strong_match_label(self):
        match = BCMatch(entity_type="purchase_order", bc_record_id="t", bc_document_no="12345",
            bc_record_info={}, match_score=0.85, match_reasoning="",
            candidate_domain=CandidateDomain.PURCHASE.value,
            positive_signals=["exact_doc_no_match", "domain_alignment", "counterparty_alignment"],
            negative_signals=[])
        outcome = determine_match_outcome(0.85, 1, [0.85], best_match=match, source_doc_type=SourceDocumentType.AP_INVOICE)
        assert outcome == MatchOutcome.STRONG_MATCH.value

    def test_suppressed_cross_domain_label(self):
        match = BCMatch(entity_type="sales_shipment", bc_record_id="t", bc_document_no="12345",
            bc_record_info={}, match_score=0.10, match_reasoning="",
            candidate_domain=CandidateDomain.SALES.value,
            positive_signals=["exact_doc_no_match"],
            negative_signals=["domain_mismatch_sales_vs_ap_invoice"])
        outcome = determine_match_outcome(0.10, 1, [0.10], best_match=match, source_doc_type=SourceDocumentType.AP_INVOICE)
        assert outcome == MatchOutcome.SUPPRESSED_CROSS_DOMAIN.value


class TestCandidateState:
    def test_surfaced_for_good_match(self):
        match = BCMatch(entity_type="purchase_order", bc_record_id="t", bc_document_no="12345",
            bc_record_info={}, match_score=0.70, match_reasoning="",
            candidate_domain=CandidateDomain.PURCHASE.value,
            positive_signals=["exact_doc_no_match", "domain_alignment"], negative_signals=[])
        state = determine_candidate_state(match, SourceDocumentType.AP_INVOICE, MatchOutcome.LIKELY_MATCH.value)
        assert state == CandidateState.SURFACED.value

    def test_suppressed_for_cross_domain_numeric_only(self):
        match = BCMatch(entity_type="sales_shipment", bc_record_id="t", bc_document_no="12345",
            bc_record_info={}, match_score=0.15, match_reasoning="",
            candidate_domain=CandidateDomain.SALES.value,
            positive_signals=["exact_doc_no_match"],
            negative_signals=["domain_mismatch_sales_vs_ap_invoice"])
        state = determine_candidate_state(match, SourceDocumentType.AP_INVOICE, MatchOutcome.SUPPRESSED_CROSS_DOMAIN.value)
        assert state == CandidateState.SUPPRESSED.value


class TestAmbiguousCase:
    def test_ambiguous_resolves_to_needs_review(self):
        match = BCMatch(entity_type="purchase_order", bc_record_id="t", bc_document_no="12345",
            bc_record_info={}, match_score=0.50, match_reasoning="",
            candidate_domain=CandidateDomain.PURCHASE.value,
            positive_signals=["exact_doc_no_match", "domain_alignment"], negative_signals=[])
        outcome = determine_match_outcome(0.50, 2, [0.50, 0.50], best_match=match, source_doc_type=SourceDocumentType.AP_INVOICE)
        assert outcome == MatchOutcome.NEEDS_REVIEW.value


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
