import asyncio
import json

import pytest

from services.ap_routing_ai_primary_service import propose_ap_route_ai_primary
from services.ap_routing_autonomy_performance_service import (
    learned_pattern_signature,
    summarize_pattern_performance,
    wilson_lower_bound,
)
from services.ap_routing_feedback_service import (
    outcome_as_learning_example,
    prepare_reviewed_routing_outcome,
)
from services.ap_routing_learned_autonomy_service import evaluate_learned_autonomy
from services.ap_routing_learned_pipeline_service import decide_ap_route_learned
from services.ap_routing_learned_safety_service import apply_learned_autonomy_safety
from services.ap_routing_relevant_learning_service import build_relevant_learning_examples


ROUTE_A = "Dropship Not International/Drop Ship All Others"
ROUTE_B = "Warehouse Not International/Ball Orders"
ROUTE_CHILD = "Vendor Credit Memos/Ball Detention Credits"
ROUTE_PARENT = "Vendor Credit Memos"
DNP = "DO NOT PAY"


def contract(*routes):
    return {
        "version": "v117-learned-test",
        "static_routes": list(routes or (ROUTE_A, ROUTE_B, ROUTE_PARENT, ROUTE_CHILD, DNP)),
        "dynamic_routes": [],
        "review_route": "",
    }


def doc(vendor="Ball Metal Beverage Container", document_type="AP_Invoice", text="", file_name="x.pdf"):
    return {
        "file_name": file_name,
        "vendor_canonical": vendor,
        "vendor_name": vendor,
        "document_type": document_type,
        "raw_text": text,
        "extracted_fields": {"vendor": vendor, "document_type": document_type},
        "bc_context": {"order_family": "standard"},
    }


def ex(route, vendor="Ball Metal Beverage Container", document_type="AP_Invoice", source="accounting_temp", **extra):
    row = {
        "fingerprint": extra.pop("fingerprint", f"{vendor}|{document_type}|{route}|{id(extra)}"),
        "vendor_name": vendor,
        "normalized_vendor": vendor,
        "document_type": document_type,
        "route_path": route,
        "label_source": source,
        "active": True,
        "split": "train",
        "file_name": extra.pop("file_name", "evidence.pdf"),
    }
    row.update(extra)
    return row


def ai(route, confidence=0.97):
    return {
        "proposed_route": route,
        "route_path": route,
        "confidence": confidence,
        "prediction": {
            "proposed_route": route,
            "confidence": confidence,
            "unresolved": [],
        },
    }


def outcome(route=ROUTE_A, final=None, vendor="Ball Metal Beverage Container", document_type="AP_Invoice"):
    final = final or route
    return {
        "human_resolved": True,
        "vendor_name": vendor,
        "document_type": document_type,
        "bc_context": {"order_family": "standard"},
        "ai_proposed_route": route,
        "final_human_route": final,
        "resolved_at": "2026-09-01T12:00:00+00:00",
        "label_source": "reviewer_confirmation" if route == final else "reviewer_correction",
    }


def five(route=ROUTE_A, **kwargs):
    return [ex(route, fingerprint=f"same-{i}", **kwargs) for i in range(5)]


def test_relevant_retrieval_rejects_holdout_truth():
    rows = five() + [ex(ROUTE_B, fingerprint="holdout", split="holdout")]
    selected = build_relevant_learning_examples(doc(), rows, limit=20)
    assert "holdout" not in {r.get("fingerprint") for r in selected}


def test_relevant_retrieval_rejects_unreviewed_ai_predictions():
    rows = five() + [ex(ROUTE_B, fingerprint="ai", source="ai_prediction", ai_generated=True)]
    selected = build_relevant_learning_examples(doc(), rows, limit=20)
    assert "ai" not in {r.get("fingerprint") for r in selected}


def test_reviewer_correction_is_prioritized_in_retrieval():
    rows = [
        ex(ROUTE_A, fingerprint="ordinary-1"),
        ex(ROUTE_A, fingerprint="ordinary-2"),
        ex(ROUTE_B, fingerprint="correction", source="reviewer_correction"),
    ]
    selected = build_relevant_learning_examples(doc(), rows, limit=2)
    assert any(r.get("fingerprint") == "correction" for r in selected)


def test_same_vendor_contradictory_routes_are_deliberately_exposed():
    rows = five(ROUTE_A) + [ex(ROUTE_B, fingerprint="contrast")]
    selected = build_relevant_learning_examples(doc(), rows, limit=8)
    routes = {r["route_path"] for r in selected}
    assert {ROUTE_A, ROUTE_B}.issubset(routes)


def test_document_type_mismatch_loses_local_authority():
    rows = five(ROUTE_A, document_type="Shipping_Document")
    decision = evaluate_learned_autonomy(document=doc(document_type="AP_Invoice"), ai_decision=ai(ROUTE_A), train_examples=rows)
    assert decision["decision"] == "needs_review"
    assert decision["support_count"] == 0


def test_high_ai_confidence_without_human_evidence_stays_review():
    decision = evaluate_learned_autonomy(document=doc(), ai_decision=ai(ROUTE_A, 0.999), train_examples=[])
    assert decision["decision"] == "needs_review"
    assert decision["autonomy_tier"] == "review"


def test_five_unanimous_local_human_examples_can_bootstrap_earned_autonomy():
    decision = evaluate_learned_autonomy(document=doc(), ai_decision=ai(ROUTE_A), train_examples=five())
    assert decision["decision"] == "auto_route"
    assert decision["route_path"] == ROUTE_A
    assert decision["earned_by"] == "human_consensus_bootstrap"
    assert decision["route_preserved"] is True


def test_reviewer_correction_against_ai_route_deauthorizes_pattern():
    rows = five(ROUTE_A) + [ex(ROUTE_B, fingerprint="human-correction", source="reviewer_correction")]
    decision = evaluate_learned_autonomy(document=doc(), ai_decision=ai(ROUTE_A), train_examples=rows)
    assert decision["decision"] == "needs_review"
    assert decision["reviewer_correction_contradictions"] == 1


def test_parent_route_history_does_not_authorize_child_route():
    decision = evaluate_learned_autonomy(document=doc(), ai_decision=ai(ROUTE_CHILD), train_examples=five(ROUTE_PARENT))
    assert decision["decision"] == "needs_review"
    assert decision["support_count"] == 0


def test_unknown_vendor_does_not_earn_from_cross_vendor_examples():
    rows = five(ROUTE_A, vendor="Other Vendor")
    decision = evaluate_learned_autonomy(document=doc(vendor="Brand New Vendor"), ai_decision=ai(ROUTE_A), train_examples=rows)
    assert decision["decision"] == "needs_review"


def test_shipping_document_does_not_inherit_invoice_authority():
    rows = five(ROUTE_A, document_type="AP_Invoice")
    decision = evaluate_learned_autonomy(document=doc(document_type="Shipping_Document"), ai_decision=ai(ROUTE_A), train_examples=rows)
    assert decision["decision"] == "needs_review"


def test_human_confirmation_feedback_has_trustworthy_provenance():
    prepared = prepare_reviewed_routing_outcome(document=doc(), ai_decision=ai(ROUTE_A), final_human_route=ROUTE_A, reviewer_id="accounting")
    assert prepared["accepted"] is True
    assert prepared["label_source"] == "reviewer_confirmation"
    assert prepared["human_resolved"] is True
    assert prepared["label_weight"] == 1.0


def test_human_correction_feedback_is_heavier_learning_evidence():
    prepared = prepare_reviewed_routing_outcome(document=doc(), ai_decision=ai(ROUTE_A), final_human_route=ROUTE_B)
    learned = outcome_as_learning_example(prepared)
    assert prepared["corrected"] is True
    assert learned["label_source"] == "reviewer_correction"
    assert learned["label_weight"] == 3.0
    assert learned["route_path"] == ROUTE_B


def test_ai_prediction_without_route_cannot_become_human_learning_evidence():
    with pytest.raises(ValueError):
        prepare_reviewed_routing_outcome(document=doc(), ai_decision={"confidence": 0.9}, final_human_route=ROUTE_A)


def test_unresolved_outcome_cannot_be_converted_to_learning_example():
    with pytest.raises(ValueError):
        outcome_as_learning_example({"human_resolved": False, "route_path": ROUTE_A})


def test_wilson_lower_bound_is_conservative():
    assert 0.50 < wilson_lower_bound(5, 5) < 1.0
    assert wilson_lower_bound(0, 0) == 0.0


def test_performance_ignores_unreviewed_predictions():
    rows = [outcome() for _ in range(5)] + [{"human_resolved": False, "ai_proposed_route": ROUTE_A, "final_human_route": ROUTE_B}]
    result = summarize_pattern_performance(document=doc(), proposed_route=ROUTE_A, outcomes=rows)
    assert result["observations"] == 5
    assert result["wrong"] == 0


def test_historical_human_resolved_ai_error_suspends_pattern():
    rows = [outcome() for _ in range(5)] + [outcome(final=ROUTE_B)]
    result = summarize_pattern_performance(document=doc(), proposed_route=ROUTE_A, outcomes=rows)
    assert result["wrong"] == 1
    assert result["suspended"] is True


def test_pattern_signature_separates_document_types():
    a = learned_pattern_signature(doc(document_type="AP_Invoice"), ROUTE_A)
    b = learned_pattern_signature(doc(document_type="Shipping_Document"), ROUTE_A)
    assert a != b


def test_measured_clean_performance_can_earn_with_four_supports():
    supports = [ex(ROUTE_A, fingerprint=f"s{i}") for i in range(4)]
    perf = [outcome() for _ in range(5)]
    decision = evaluate_learned_autonomy(document=doc(), ai_decision=ai(ROUTE_A), train_examples=supports, performance_outcomes=perf)
    assert decision["decision"] == "auto_route"
    assert decision["earned_by"] == "measured_performance"


def test_historical_wrong_suspends_even_with_strong_current_support():
    perf = [outcome() for _ in range(8)] + [outcome(final=ROUTE_B)]
    decision = evaluate_learned_autonomy(document=doc(), ai_decision=ai(ROUTE_A), train_examples=five(), performance_outcomes=perf)
    assert decision["decision"] == "needs_review"
    assert decision["performance"]["suspended"] is True


def test_explicit_do_not_pay_conflict_is_demoted_not_rewritten():
    autonomy = evaluate_learned_autonomy(document=doc(text="DO NOT PAY this invoice"), ai_decision=ai(ROUTE_A), train_examples=five())
    final = apply_learned_autonomy_safety(document=doc(text="DO NOT PAY this invoice"), autonomy_decision=autonomy, contract=contract(), bc_context={})
    assert final["decision"] == "needs_review"
    assert final["route_path"] == ""
    assert final["ai_proposed_route"] == ROUTE_A
    assert final["safety_action"] == "demote_to_review"


def test_explicit_do_not_pay_ai_route_can_pass_when_earned():
    autonomy = evaluate_learned_autonomy(document=doc(text="DO NOT PAY this invoice"), ai_decision=ai(DNP), train_examples=five(DNP))
    final = apply_learned_autonomy_safety(document=doc(text="DO NOT PAY this invoice"), autonomy_decision=autonomy, contract=contract(), bc_context={})
    assert final["decision"] == "auto_route"
    assert final["route_path"] == DNP


def test_cross_vendor_or_other_hard_conflict_demotes_without_replacement():
    autonomy = evaluate_learned_autonomy(document=doc(), ai_decision=ai(ROUTE_A), train_examples=five())
    final = apply_learned_autonomy_safety(document=doc(), autonomy_decision=autonomy, contract=contract(), hard_blockers=["cross_vendor_exact_reference_conflict"])
    assert final["decision"] == "needs_review"
    assert final["route_path"] == ""
    assert final["ai_proposed_route"] == ROUTE_A


def test_disallowed_ai_route_is_demoted_without_substitution():
    autonomy = evaluate_learned_autonomy(document=doc(), ai_decision=ai(ROUTE_A), train_examples=five())
    final = apply_learned_autonomy_safety(document=doc(), autonomy_decision=autonomy, contract=contract(ROUTE_B), bc_context={})
    assert final["decision"] == "needs_review"
    assert final["route_path"] == ""


def test_ai_primary_proposer_never_substitutes_supervised_consensus_route():
    async def fake_send(prompt, model):
        return json.dumps({
            "proposed_route": ROUTE_B,
            "confidence": 0.97,
            "evidence": ["current document semantics"],
            "reasoning_summary": "AI selected warehouse route",
            "bc_refs_used": [],
            "unresolved": [],
            "matched_example_ids": [],
        })

    result = asyncio.run(propose_ap_route_ai_primary(
        document=doc(),
        bc_context={},
        contract=contract(),
        examples=five(ROUTE_A),
        llm_send=fake_send,
    ))
    assert result["proposed_route"] == ROUTE_B
    assert result["route_selected_by"] == "ai_model"
    assert result["supervised_route_substitution"] is False


def test_end_to_end_learned_pipeline_preserves_ai_route_and_blocks_self_training():
    async def fake_send(prompt, model):
        return json.dumps({
            "proposed_route": ROUTE_A,
            "confidence": 0.98,
            "evidence": ["learned examples"],
            "reasoning_summary": "matches learned human pattern",
            "bc_refs_used": [],
            "unresolved": [],
            "matched_example_ids": [],
        })

    result = asyncio.run(decide_ap_route_learned(
        document=doc(),
        bc_context={},
        contract=contract(),
        train_examples=five(ROUTE_A),
        llm_send=fake_send,
    ))
    assert result["decision"] == "auto_route"
    assert result["route_path"] == ROUTE_A
    assert result["ai_proposed_route"] == ROUTE_A
    assert result["ai_primary_router"] is True
    assert result["self_training_blocked"] is True
    assert result["deterministic_route_substitution"] is False
