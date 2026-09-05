import asyncio
import json

from services.ap_routing_ai_primary_service import propose_ap_route_ai_primary
from services.ap_routing_anchor_authority_service import (
    summarize_high_specificity_anchor_authority,
)
from services.ap_routing_learned_autonomy_service import evaluate_learned_autonomy
from services.ap_routing_learned_pipeline_service import decide_ap_route_learned
from services.ap_routing_train_context_service import build_train_learning_context


DNP = "DO NOT PAY"
DROP = "Dropship Not International/Drop Ship All Others"
DROP_INTL = "Dropship International"
WTR = "Warehouse Not International/WTR Transfers"
FREIGHT = "Dropship Not International/Freight"


def contract():
    return {
        "version": "v117-train-context-anchor-test",
        "static_routes": [DNP, DROP, DROP_INTL, WTR, FREIGHT],
        "dynamic_routes": [
            {
                "prefix": DROP_INTL,
                "leaf_pattern": "[A-Z0-9_-]{4,20}",
                "requires_verified_bc_reference": True,
            }
        ],
        "manual_only_routes": [],
        "review_route": "",
    }


def doc(
    *,
    vendor="Current Vendor",
    document_type="AP_Invoice",
    file_name="118000_Current.pdf",
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
    fingerprint,
    vendor="Current Vendor",
    document_type="AP_Invoice",
    file_name="118000_Current_history.pdf",
    text="",
    source="accounting_temp",
    split="train",
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
        "split": split,
        "file_name": file_name,
        "raw_text_excerpt": text,
        "extracted_fields": {"vendor": vendor, "document_type": document_type},
        "bc_context": {},
    }
    row.update(extra)
    return row


def ai(route, confidence=0.99):
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


def test_train_context_uses_full_human_train_set_beyond_eight_raw_examples():
    rows = [ex(DNP, fingerprint=f"d{i}", vendor=f"Vendor {i}", text="DO NOT PAY") for i in range(15)]
    result = build_train_learning_context(
        doc(vendor="New Vendor", text="DO NOT PAY"), rows, contract=contract()
    )
    assert result["eligible_train_example_count"] == 15
    assert result["purpose"] == "TRAIN_HUMAN_PROMPT_CONTEXT_ONLY_NOT_ROUTING_AUTHORITY"


def test_train_context_excludes_holdout_and_unreviewed_ai_rows():
    good = [ex(DNP, fingerprint=f"good{i}") for i in range(4)]
    holdout = ex(DROP, fingerprint="holdout", split="holdout")
    ai_row = ex(DROP, fingerprint="ai", source="ai_prediction")
    ai_row["ai_generated"] = True
    result = build_train_learning_context(doc(), good + [holdout, ai_row], contract=contract())
    assert result["eligible_train_example_count"] == 4
    assert result["same_vendor_route_counts"] == [{"route_path": DNP, "count": 4}]


def test_train_context_reports_same_vendor_and_same_type_route_distributions():
    rows = [
        ex(DNP, fingerprint="a", document_type="AP_Invoice"),
        ex(DNP, fingerprint="b", document_type="Credit_Memo"),
        ex(DROP, fingerprint="c", document_type="AP_Invoice"),
    ]
    result = build_train_learning_context(
        doc(document_type="AP_Invoice"), rows, contract=contract()
    )
    assert result["same_vendor_example_count"] == 3
    assert result["same_vendor_same_type_example_count"] == 2
    same_type = {row["route_path"]: row["count"] for row in result["same_vendor_same_type_route_counts"]}
    assert same_type == {DNP: 1, DROP: 1}


def test_train_context_exposes_current_semantics_and_reference_family():
    result = build_train_learning_context(
        doc(file_name="WTR1036_Koch.pdf", text="freight transfer"),
        [ex(WTR, fingerprint="wtr", file_name="WTR1001_Koch.pdf")],
        contract=contract(),
    )
    assert result["current_reference_family"] == "wtr_reference"
    assert "freight" in result["current_semantic_features"]


def test_train_context_reports_dynamic_parent_vs_child_usage_without_recommending_route():
    rows = [
        ex(DROP_INTL, fingerprint="p1"),
        ex(DROP_INTL, fingerprint="p2"),
        ex(f"{DROP_INTL}/114001", fingerprint="c1"),
    ]
    result = build_train_learning_context(doc(), rows, contract=contract())
    usage = result["dynamic_route_usage_same_vendor"][0]
    assert usage["prefix"] == DROP_INTL
    assert usage["parent_count"] == 2
    assert usage["dynamic_child_count"] == 1
    assert "recommended_route" not in result


def test_ai_prompt_carries_full_train_context_and_granularity_rules():
    seen = {}

    async def fake_send(prompt, model):
        seen["prompt"] = prompt
        seen["payload"] = json.loads(prompt.split("INPUT:\n", 1)[1])
        return json.dumps({
            "proposed_route": DROP_INTL,
            "confidence": 0.99,
            "evidence": ["human parent pattern"],
            "reasoning_summary": "uses observed parent granularity",
            "bc_refs_used": ["114022"],
            "unresolved": [],
            "matched_example_ids": [],
        })

    context = {
        "purpose": "TRAIN_HUMAN_PROMPT_CONTEXT_ONLY_NOT_ROUTING_AUTHORITY",
        "eligible_train_example_count": 20,
        "dynamic_route_usage_same_vendor": [
            {"prefix": DROP_INTL, "parent_count": 7, "dynamic_child_count": 0, "dynamic_children": []}
        ],
    }
    asyncio.run(propose_ap_route_ai_primary(
        document=doc(),
        bc_context={"verified_order_numbers": ["114022"]},
        contract=contract(),
        examples=[],
        learning_context=context,
        llm_send=fake_send,
    ))
    assert seen["payload"]["train_learning_context"]["eligible_train_example_count"] == 20
    assert "verified BC/order reference does NOT by itself justify a dynamic child" in seen["prompt"]
    assert "BC open/posted/receipt status alone is insufficient" in seen["prompt"]
    assert "DO NOT PAY is exceptional" in seen["prompt"]


def test_pipeline_keeps_raw_prompt_at_eight_while_summary_sees_full_train():
    seen = {}
    rows = [ex(DNP, fingerprint=f"d{i}", vendor=f"Vendor {i}", text="DO NOT PAY") for i in range(12)]

    async def fake_send(prompt, model):
        payload = json.loads(prompt.split("INPUT:\n", 1)[1])
        seen["raw_count"] = len(payload["similar_labeled_examples"])
        seen["train_count"] = payload["train_learning_context"]["eligible_train_example_count"]
        return json.dumps({
            "proposed_route": DNP,
            "confidence": 0.99,
            "evidence": ["stop pay"],
            "reasoning_summary": "current stop-pay evidence",
            "bc_refs_used": [],
            "unresolved": [],
            "matched_example_ids": [],
        })

    result = asyncio.run(decide_ap_route_learned(
        document=doc(vendor="New Vendor", text="DO NOT PAY"),
        bc_context={},
        contract=contract(),
        train_examples=rows,
        relevant_limit=99,
        llm_send=fake_send,
    ))
    assert seen["raw_count"] == 8
    assert seen["train_count"] == 12
    assert result["train_learning_context_active"] is True
    assert result["deterministic_route_substitution"] is False


def test_unanimous_explicit_stop_pay_anchor_can_confirm_exact_ai_dnp():
    rows = [
        ex(DNP, fingerprint=f"d{i}", vendor=f"Vendor {i}", document_type="Credit_Memo" if i % 2 else "AP_Invoice", text="DO NOT PAY")
        for i in range(6)
    ]
    result = summarize_high_specificity_anchor_authority(
        document=doc(vendor="New Vendor", text="DO NOT PAY"),
        proposed_route=DNP,
        train_examples=rows,
    )
    assert result["authority_ready"] is True
    assert result["earned_anchor"] == "explicit_stop_pay"
    assert result["support_count"] == 6


def test_any_human_route_contradiction_blocks_high_specificity_anchor():
    rows = [
        ex(DNP, fingerprint=f"d{i}", vendor=f"Vendor {i}", text="DO NOT PAY")
        for i in range(5)
    ] + [ex(DROP, fingerprint="contradiction", vendor="Other", text="DO NOT PAY")]
    result = summarize_high_specificity_anchor_authority(
        document=doc(vendor="New Vendor", text="DO NOT PAY"),
        proposed_route=DNP,
        train_examples=rows,
    )
    assert result["authority_ready"] is False
    assert result["measurements"][0]["contradiction_count"] == 1


def test_reviewer_correction_contradiction_is_visible_and_blocks_anchor():
    rows = [
        ex(DNP, fingerprint=f"d{i}", vendor=f"Vendor {i}", text="DO NOT PAY")
        for i in range(5)
    ] + [
        ex(
            DROP,
            fingerprint="correction",
            vendor="Other",
            text="DO NOT PAY",
            source="reviewer_correction",
        )
    ]
    result = summarize_high_specificity_anchor_authority(
        document=doc(vendor="New Vendor", text="DO NOT PAY"),
        proposed_route=DNP,
        train_examples=rows,
    )
    assert result["authority_ready"] is False
    assert result["measurements"][0]["reviewer_correction_contradictions"] == 1


def test_wtr_reference_can_confirm_exact_ai_wtr_across_vendors_and_types():
    rows = [
        ex(
            WTR,
            fingerprint=f"w{i}",
            vendor=f"Warehouse {i}",
            document_type="Shipping_Document" if i % 2 else "Warehouse_Receipt",
            file_name=f"WTR10{i:02d}_Warehouse.pdf",
        )
        for i in range(6)
    ]
    result = summarize_high_specificity_anchor_authority(
        document=doc(vendor="", document_type="Shipping_Document", file_name="WTR1036_Koch.pdf"),
        proposed_route=WTR,
        train_examples=rows,
    )
    assert result["authority_ready"] is True
    assert result["earned_anchor"] == "wtr_reference"


def test_generic_freight_semantics_cannot_create_high_specificity_anchor_authority():
    rows = [
        ex(FREIGHT, fingerprint=f"f{i}", vendor=f"Carrier {i}", text="freight invoice")
        for i in range(10)
    ]
    result = summarize_high_specificity_anchor_authority(
        document=doc(vendor="New Carrier", text="freight invoice"),
        proposed_route=FREIGHT,
        train_examples=rows,
    )
    assert result["current_high_specificity_anchors"] == []
    assert result["authority_ready"] is False


def test_anchor_can_earn_when_same_vendor_neighborhood_is_sparse_or_mixed():
    rows = [
        ex(DNP, fingerprint="same-dnp", text="DO NOT PAY"),
        ex(DROP, fingerprint="same-pay-1", text="ordinary invoice"),
        ex(DROP, fingerprint="same-pay-2", text="ordinary invoice"),
    ] + [
        ex(DNP, fingerprint=f"global-dnp-{i}", vendor=f"Vendor {i}", text="DO NOT PAY")
        for i in range(5)
    ]
    decision = evaluate_learned_autonomy(
        document=doc(text="DO NOT PAY"),
        ai_decision=ai(DNP),
        train_examples=rows,
    )
    assert decision["neighborhood"]["authority_ready"] is False
    assert decision["anchor_authority"]["authority_ready"] is True
    assert decision["decision"] == "auto_route"
    assert decision["earned_by"] == "high_specificity_human_anchor"
    assert decision["route_path"] == DNP


def test_anchor_contradiction_prevents_neighborhood_from_bypassing_conflict():
    rows = [
        ex(DNP, fingerprint=f"same-{i}", text="ordinary historical invoice")
        for i in range(5)
    ] + [
        ex(DNP, fingerprint=f"anchor-{i}", vendor=f"Anchor Vendor {i}", text="DO NOT PAY")
        for i in range(5)
    ] + [
        ex(DROP, fingerprint="anchor-conflict", vendor="Conflict Vendor", text="DO NOT PAY")
    ]
    decision = evaluate_learned_autonomy(
        document=doc(text="DO NOT PAY"),
        ai_decision=ai(DNP),
        train_examples=rows,
    )
    assert decision["neighborhood"]["authority_ready"] is True
    assert decision["anchor_authority"]["authority_ready"] is False
    assert decision["decision"] == "needs_review"
    assert any("high-specificity human anchor" in reason for reason in decision["reasons"])
