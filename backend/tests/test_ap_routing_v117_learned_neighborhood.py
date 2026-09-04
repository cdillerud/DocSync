import asyncio
import json

from services import ap_routing_learned_evaluation_service as learned_eval
from services.ap_routing_evaluation_service import promotion_gate, split_train_holdout
from services.ap_routing_learned_autonomy_service import evaluate_learned_autonomy
from services.ap_routing_learned_features_service import (
    feature_similarity,
    reference_family,
    semantic_features,
)
from services.ap_routing_learned_neighborhood_service import summarize_authority_neighborhood
from services.ap_routing_learned_pipeline_service import decide_ap_route_learned
from services.ap_routing_learned_safety_service import apply_learned_autonomy_safety
from services.ap_routing_relevant_learning_service import build_relevant_learning_examples


WAREHOUSE = "Warehouse Not International/Ball Orders"
DROPSHIP = "Dropship Not International/Ball"
DROP_ALL = "Dropship Not International/Drop Ship All Others"
DNP = "DO NOT PAY"
DETENTION = "Vendor Credit Memos/Ball Detention Credits"
CREDIT = "Vendor Credit Memos"
FREIGHT = "Dropship Not International/Freight"


def contract(*routes):
    return {
        "version": "v117-neighborhood-test",
        "static_routes": list(routes or (WAREHOUSE, DROPSHIP, DROP_ALL, DNP, DETENTION, CREDIT, FREIGHT)),
        "dynamic_routes": [],
        "manual_only_routes": [],
        "review_route": "",
    }


def doc(
    vendor="Ball Metal Beverage Container",
    document_type="AP_Invoice",
    file_name="116278_Ball_123.pdf",
    text="",
    bc_context=None,
):
    return {
        "file_name": file_name,
        "vendor_name": vendor,
        "vendor_canonical": vendor,
        "document_type": document_type,
        "suggested_job_type": document_type,
        "raw_text": text,
        "extracted_fields": {"vendor": vendor, "document_type": document_type},
        "bc_context": bc_context or {},
    }


def ex(
    route,
    *,
    vendor="Ball Metal Beverage Container",
    document_type="AP_Invoice",
    file_name="116100_Ball_111.pdf",
    text="",
    fingerprint="x",
    source="accounting_temp",
    **extra,
):
    row = {
        "fingerprint": fingerprint,
        "vendor_name": vendor,
        "normalized_vendor": vendor,
        "document_type": document_type,
        "route_path": route,
        "label_source": source,
        "active": True,
        "split": "train",
        "file_name": file_name,
        "raw_text_excerpt": text,
        "extracted_fields": {"vendor": vendor, "document_type": document_type},
        "bc_context": {},
    }
    row.update(extra)
    return row


def ai(route, confidence=0.98):
    return {
        "proposed_route": route,
        "route_path": route,
        "confidence": confidence,
        "prediction": {
            "proposed_route": route,
            "confidence": confidence,
            "unresolved": [],
            "bc_refs_used": [],
            "matched_example_ids": [],
        },
    }


def test_reference_family_separates_w_wtr_and_numeric():
    assert reference_family(doc(file_name="W118446_Ball_6388627.pdf")) == "w_reference"
    assert reference_family(doc(file_name="WTR1036_Koch_083126.pdf")) == "wtr_reference"
    assert reference_family(doc(file_name="116278_Ball_6396902.pdf")) == "numeric_reference"


def test_w_reference_similarity_prefers_w_examples_over_numeric():
    current = doc(file_name="W118446_Ball_6388627.pdf")
    w = ex(WAREHOUSE, file_name="W118073_Ball_6396992.pdf", fingerprint="w")
    numeric = ex(DROPSHIP, file_name="116278_Ball_6396902.pdf", fingerprint="n")
    assert feature_similarity(current, w)["score"] > feature_similarity(current, numeric)["score"]


def test_wtr_reference_is_not_treated_as_plain_w_reference():
    current = doc(file_name="WTR1036_Koch_083126.pdf", vendor="Koch Logistics")
    wtr = ex(WAREHOUSE, vendor="Koch Logistics", file_name="WTR1001_Koch.pdf", fingerprint="wtr")
    w = ex(WAREHOUSE, vendor="Koch Logistics", file_name="W118000_Koch.pdf", fingerprint="w")
    assert feature_similarity(current, wtr)["score"] > feature_similarity(current, w)["score"]


def test_stop_pay_semantics_are_route_neutral_features():
    features = semantic_features(doc(text="Do not pay. Replaced by invoice 12345."))
    assert "explicit_stop_pay" in features
    assert "replacement_or_offset" in features


def test_detention_semantics_distinguish_generic_credit_documents():
    current = doc(document_type="Credit_Memo", text="detention credit for shipment")
    detention = ex(DETENTION, document_type="Credit_Memo", text="detention charge credit", fingerprint="d")
    generic = ex(CREDIT, document_type="Credit_Memo", text="vendor credit memo", fingerprint="g")
    assert feature_similarity(current, detention)["score"] > feature_similarity(current, generic)["score"]


def test_prompt_retrieval_is_hard_capped_at_eight():
    rows = [ex(DNP, vendor=f"Vendor {i}", fingerprint=f"e{i}", text="DO NOT PAY") for i in range(20)]
    selected = build_relevant_learning_examples(doc(vendor="New Vendor", text="DO NOT PAY"), rows, limit=20)
    assert len(selected) == 8


def test_prompt_uses_nearest_workflow_before_route_contrasts():
    rows = [
        ex(WAREHOUSE, file_name=f"W11800{i}_Ball.pdf", fingerprint=f"w{i}") for i in range(6)
    ] + [
        ex(DROPSHIP, file_name=f"11620{i}_Ball.pdf", fingerprint=f"n{i}") for i in range(6)
    ]
    selected = build_relevant_learning_examples(doc(file_name="W118999_Ball.pdf"), rows, limit=8)
    first_six = selected[:6]
    assert sum(1 for row in first_six if row["route_path"] == WAREHOUSE) >= 5


def test_variable_vendor_w_family_can_earn_from_pure_neighborhood():
    rows = [
        ex(WAREHOUSE, file_name=f"W11800{i}_Ball.pdf", fingerprint=f"w{i}") for i in range(4)
    ] + [
        ex(DROPSHIP, file_name=f"11620{i}_Ball.pdf", fingerprint=f"n{i}") for i in range(4)
    ]
    result = summarize_authority_neighborhood(
        document=doc(file_name="W118999_Ball.pdf"),
        proposed_route=WAREHOUSE,
        train_examples=rows,
    )
    assert result["scope"] == "same_vendor"
    assert result["authority_ready"] is True
    assert result["support_count"] >= 3


def test_variable_vendor_wrong_ai_route_is_not_authorized_by_distant_history():
    rows = [
        ex(WAREHOUSE, file_name=f"W11800{i}_Ball.pdf", fingerprint=f"w{i}") for i in range(4)
    ] + [
        ex(DROPSHIP, file_name=f"11620{i}_Ball.pdf", fingerprint=f"n{i}") for i in range(4)
    ]
    result = summarize_authority_neighborhood(
        document=doc(file_name="W118999_Ball.pdf"),
        proposed_route=DROPSHIP,
        train_examples=rows,
    )
    assert result["authority_ready"] is False


def test_cross_vendor_stop_pay_can_earn_with_semantic_anchor():
    rows = [
        ex(DNP, vendor=f"Stop Vendor {i}", fingerprint=f"d{i}", text="DO NOT PAY replaced by invoice")
        for i in range(6)
    ] + [
        ex(DROP_ALL, vendor=f"Pay Vendor {i}", fingerprint=f"p{i}", text="standard payable invoice")
        for i in range(6)
    ]
    result = summarize_authority_neighborhood(
        document=doc(vendor="Brand New Vendor", text="DO NOT PAY, replaced by another invoice"),
        proposed_route=DNP,
        train_examples=rows,
    )
    assert result["scope"] == "semantic_cross_vendor"
    assert result["semantic_anchor"] is True
    assert result["authority_ready"] is True


def test_cross_vendor_generic_frequency_cannot_grant_autonomy_without_anchor():
    rows = [ex(DROP_ALL, vendor=f"Vendor {i}", fingerprint=f"g{i}") for i in range(10)]
    result = summarize_authority_neighborhood(
        document=doc(vendor="Unknown New Vendor", file_name="invoice.pdf", text=""),
        proposed_route=DROP_ALL,
        train_examples=rows,
    )
    assert result["scope"] == "semantic_cross_vendor"
    assert result["semantic_anchor"] is False
    assert result["authority_ready"] is False


def test_reviewer_correction_in_neighborhood_blocks_bootstrap():
    rows = [
        ex(WAREHOUSE, file_name=f"W11800{i}_Ball.pdf", fingerprint=f"w{i}") for i in range(4)
    ] + [
        ex(
            DROPSHIP,
            file_name="W118777_Ball.pdf",
            fingerprint="correction",
            source="reviewer_correction",
        )
    ]
    result = summarize_authority_neighborhood(
        document=doc(file_name="W118999_Ball.pdf"),
        proposed_route=WAREHOUSE,
        train_examples=rows,
    )
    assert result["reviewer_correction_contradictions"] == 1
    assert result["authority_ready"] is False


def test_holdout_and_unreviewed_ai_rows_cannot_enter_neighborhood():
    good = [ex(DNP, fingerprint=f"good{i}", text="DO NOT PAY") for i in range(5)]
    holdout = ex(DROP_ALL, fingerprint="holdout")
    holdout["split"] = "holdout"
    ai_row = ex(DROP_ALL, fingerprint="ai", source="ai_prediction")
    ai_row["ai_generated"] = True
    result = summarize_authority_neighborhood(
        document=doc(text="DO NOT PAY"),
        proposed_route=DNP,
        train_examples=good + [holdout, ai_row],
    )
    assert "holdout" not in result["neighbor_ids"]
    assert "ai" not in result["neighbor_ids"]


def test_autonomy_uses_neighborhood_not_vendor_wide_route_frequency():
    rows = [
        ex(WAREHOUSE, file_name=f"W11800{i}_Ball.pdf", fingerprint=f"w{i}") for i in range(4)
    ] + [
        ex(DROPSHIP, file_name=f"11620{i}_Ball.pdf", fingerprint=f"n{i}") for i in range(10)
    ]
    decision = evaluate_learned_autonomy(
        document=doc(file_name="W118999_Ball.pdf"),
        ai_decision=ai(WAREHOUSE),
        train_examples=rows,
    )
    assert decision["decision"] == "auto_route"
    assert decision["route_path"] == WAREHOUSE


def test_pipeline_actual_prompt_is_max_eight_and_ai_route_is_preserved():
    rows = [ex(DNP, vendor=f"Vendor {i}", fingerprint=f"e{i}", text="DO NOT PAY") for i in range(12)]

    async def fake_send(prompt, model):
        payload = json.loads(prompt.split("INPUT:\n", 1)[1])
        assert len(payload["similar_labeled_examples"]) <= 8
        return json.dumps({
            "proposed_route": DNP,
            "confidence": 0.99,
            "evidence": ["explicit stop pay"],
            "reasoning_summary": "current document says do not pay",
            "bc_refs_used": [],
            "unresolved": [],
            "matched_example_ids": [],
        })

    result = asyncio.run(decide_ap_route_learned(
        document=doc(vendor="New Vendor", text="DO NOT PAY replaced by invoice"),
        bc_context={},
        contract=contract(),
        train_examples=rows,
        relevant_limit=99,
        llm_send=fake_send,
    ))
    assert result["prompt_example_count"] <= 8
    assert result["ai_proposed_route"] == DNP
    assert result["route_path"] in {"", DNP}
    assert result["deterministic_route_substitution"] is False


def test_special_dnp_route_is_not_blocked_by_unrelated_bc_vendor_mismatch():
    rows = [ex(DNP, fingerprint=f"d{i}", text="DO NOT PAY") for i in range(5)]
    autonomy = evaluate_learned_autonomy(
        document=doc(text="DO NOT PAY"), ai_decision=ai(DNP), train_examples=rows
    )
    final = apply_learned_autonomy_safety(
        document=doc(text="DO NOT PAY"),
        autonomy_decision=autonomy,
        contract=contract(),
        bc_context={"status": "resolved", "bc_vendor_name": "Completely Different Vendor", "verified_order_numbers": ["123456"]},
        support_examples=rows,
    )
    assert "resolved Business Central vendor conflicts" not in " ".join(final.get("safety_blockers") or [])


def test_logistics_route_is_blocked_by_resolved_bc_vendor_mismatch():
    rows = [ex(DROP_ALL, fingerprint=f"p{i}") for i in range(5)]
    autonomy = evaluate_learned_autonomy(
        document=doc(), ai_decision=ai(DROP_ALL), train_examples=rows
    )
    final = apply_learned_autonomy_safety(
        document=doc(),
        autonomy_decision=autonomy,
        contract=contract(),
        bc_context={"status": "resolved", "bc_vendor_name": "Completely Different Vendor", "verified_order_numbers": ["123456"]},
        support_examples=rows,
    )
    assert final["decision"] == "needs_review"
    assert any("Business Central vendor conflicts" in b for b in final.get("safety_blockers") or [])


def test_measured_clean_performance_can_earn_sparse_pattern_without_substitution():
    sparse = [ex(DROP_ALL, fingerprint="a"), ex(DROP_ALL, fingerprint="b")]
    outcomes = [
        {
            "human_resolved": True,
            "vendor_name": "Ball Metal Beverage Container",
            "document_type": "AP_Invoice",
            "bc_context": {},
            "ai_proposed_route": DROP_ALL,
            "final_human_route": DROP_ALL,
        }
        for _ in range(8)
    ]
    decision = evaluate_learned_autonomy(
        document=doc(),
        ai_decision=ai(DROP_ALL),
        train_examples=sparse,
        performance_outcomes=outcomes,
    )
    assert decision["decision"] == "auto_route"
    assert decision["earned_by"] == "measured_performance"
    assert decision["route_path"] == DROP_ALL


def test_historical_wrong_performance_suspends_even_pure_neighborhood():
    rows = [ex(DROP_ALL, fingerprint=f"p{i}") for i in range(5)]
    outcomes = [
        {
            "human_resolved": True,
            "vendor_name": "Ball Metal Beverage Container",
            "document_type": "AP_Invoice",
            "bc_context": {},
            "ai_proposed_route": DROP_ALL,
            "final_human_route": DROP_ALL,
        }
        for _ in range(7)
    ] + [
        {
            "human_resolved": True,
            "vendor_name": "Ball Metal Beverage Container",
            "document_type": "AP_Invoice",
            "bc_context": {},
            "ai_proposed_route": DROP_ALL,
            "final_human_route": DNP,
        }
    ]
    decision = evaluate_learned_autonomy(
        document=doc(), ai_decision=ai(DROP_ALL), train_examples=rows, performance_outcomes=outcomes
    )
    assert decision["decision"] == "needs_review"
    assert decision["performance"]["suspended"] is True


def test_shadow_ai_accuracy_is_measured_even_when_everything_reviews(monkeypatch):
    examples = [
        ex(DNP if i % 2 == 0 else DROP_ALL, vendor=f"V{i}", fingerprint=f"fp{i}", file_name=f"f{i}.pdf")
        for i in range(10)
    ]
    _, holdout = split_train_holdout(examples)
    expected_by_file = {row["file_name"]: row["route_path"] for row in holdout}

    async def fake_adapter(db, *, document, **kwargs):
        route = expected_by_file[document["file_name"]]
        return {
            "decision": "needs_review",
            "route_path": "",
            "ai_proposed_route": route,
            "confidence": 0.99,
            "ai_confidence": 0.99,
            "ai_reason": "shadow correct",
            "prompt_example_count": 8,
            "prompt_routes": [DNP, DROP_ALL],
            "prompt_example_ids": [],
            "prompt_example_relevance_scores": [],
            "ensemble_reconciliation": {"action": "ai_primary_no_route_substitution"},
            "authority_guard": {"action": "learned_review", "blockers": []},
        }

    monkeypatch.setattr(learned_eval, "decide_ap_route_with_learned_autonomy", fake_adapter)
    result = asyncio.run(learned_eval.evaluate_holdout_learned(examples=examples, contract=contract()))
    assert result["coverage"] == 0.0
    assert result["ai_proposal_accuracy"] == 1.0
    assert result["ai_proposal_correct_count"] == result["holdout_count"]
    gate = promotion_gate(result, labeled_example_count=len(examples))
    assert gate["ready_for_runtime_authority"] is False
