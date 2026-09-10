import asyncio
import json

from services.ap_routing_ai_primary_service import propose_ap_route_ai_primary
from services.ap_routing_corroboration_authority_service import (
    summarize_train_corroboration_authority,
)
from services.ap_routing_learned_safety_service import (
    apply_learned_autonomy_safety,
    derive_universal_safety_blockers,
)


DNP = "DO NOT PAY"
DROP = "Dropship Not International/Drop Ship All Others"
DROP_INTL = "Dropship International"
DROP_CHILD = "Dropship International/114020"
WAREHOUSE = "Warehouse Not International"
WAREHOUSE_INTL = "Warehouse International"
BALL_ORDERS = "Warehouse Not International/Ball Orders"
FREIGHT = "Dropship Not International/Freight"


def contract():
    return {
        "version": "v117-corroboration-safety-test",
        "static_routes": [DNP, DROP, DROP_INTL, WAREHOUSE, WAREHOUSE_INTL, BALL_ORDERS, FREIGHT],
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
    file_name="114999_Current.pdf",
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
    file_name="114001_History.pdf",
    text="",
    source="accounting_temp",
    split="train",
    bc_context=None,
):
    return {
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
        "bc_context": bc_context or {},
    }


def autonomy(route, *, document=None, unresolved=None, refs=None, matched=None, anchor=None):
    return {
        "decision": "auto_route",
        "route_path": route,
        "ai_proposed_route": route,
        "autonomy_tier": "earned_auto",
        "anchor_authority": anchor or {},
        "prediction": {
            "proposed_route": route,
            "confidence": 1.0,
            "unresolved": list(unresolved or []),
            "bc_refs_used": list(refs or []),
            "matched_example_ids": list(matched or []),
        },
    }


def test_corroboration_earns_from_large_same_vendor_reference_majority():
    rows = [
        ex(DROP_INTL, fingerprint=f"p{i}", file_name=f"11410{i}_HWA.pdf")
        for i in range(6)
    ] + [ex(DROP_CHILD, fingerprint="child", file_name="114020_HWA.pdf")]
    result = summarize_train_corroboration_authority(
        document=doc(file_name="114022_HWA.pdf"),
        proposed_route=DROP_INTL,
        confidence=0.95,
        train_examples=rows,
        contract=contract(),
    )
    assert result["authority_ready"] is True
    assert result["earned_slice"] == "same_vendor_same_document_type_reference_family"
    assert result["support_count"] == 6
    assert result["purity"] >= 0.85


def test_corroboration_reference_majority_below_85_percent_stays_review():
    rows = [
        ex(DROP_INTL, fingerprint=f"p{i}", file_name=f"11410{i}_HWA.pdf")
        for i in range(5)
    ] + [ex(DROP_CHILD, fingerprint="child", file_name="114020_HWA.pdf")]
    result = summarize_train_corroboration_authority(
        document=doc(file_name="114022_HWA.pdf"),
        proposed_route=DROP_INTL,
        confidence=0.95,
        train_examples=rows,
        contract=contract(),
    )
    assert result["authority_ready"] is False


def test_corroboration_same_vendor_same_type_requires_large_high_purity_pattern():
    rows = [
        ex(WAREHOUSE, fingerprint=f"w{i}", file_name=f"doc-{i}.pdf")
        for i in range(9)
    ] + [ex(FREIGHT, fingerprint="other", file_name="other.pdf")]
    result = summarize_train_corroboration_authority(
        document=doc(file_name="plain-current.pdf"),
        proposed_route=WAREHOUSE,
        confidence=0.92,
        train_examples=rows,
        contract=contract(),
    )
    assert result["authority_ready"] is True
    assert result["earned_slice"] == "same_vendor_same_document_type"


def test_dynamic_child_requires_three_unanimous_supports_and_98_confidence():
    two = [
        ex(DROP_CHILD, fingerprint=f"d{i}", file_name=f"11402{i}_HWA.pdf")
        for i in range(2)
    ]
    low = summarize_train_corroboration_authority(
        document=doc(file_name="114020_HWA.pdf"),
        proposed_route=DROP_CHILD,
        confidence=0.99,
        train_examples=two,
        contract=contract(),
    )
    assert low["authority_ready"] is False
    three = two + [ex(DROP_CHILD, fingerprint="d2", file_name="114020_HWA2.pdf")]
    ready = summarize_train_corroboration_authority(
        document=doc(file_name="114020_HWA.pdf"),
        proposed_route=DROP_CHILD,
        confidence=0.98,
        train_examples=three,
        contract=contract(),
    )
    assert ready["authority_ready"] is True


def test_corroboration_cannot_grant_dnp_without_explicit_current_stop_pay():
    rows = [ex(DNP, fingerprint=f"d{i}") for i in range(8)]
    result = summarize_train_corroboration_authority(
        document=doc(text="ordinary credit memo"),
        proposed_route=DNP,
        confidence=1.0,
        train_examples=rows,
        contract=contract(),
    )
    assert result["authority_ready"] is False
    assert any("without explicit current stop-pay" in x for x in result["hard_blockers"])


def test_corroboration_cannot_bypass_reversal_exception_boundary():
    rows = [ex(DNP, fingerprint=f"d{i}", text="reversing credit memo") for i in range(8)]
    result = summarize_train_corroboration_authority(
        document=doc(text="reversing this credit memo; do not pay"),
        proposed_route=DNP,
        confidence=1.0,
        train_examples=rows,
        contract=contract(),
    )
    assert result["authority_ready"] is False
    assert any("reversal/void" in x for x in result["hard_blockers"])


def test_corroboration_excludes_holdout_and_unreviewed_ai_evidence():
    rows = [ex(WAREHOUSE, fingerprint=f"good{i}", file_name=f"doc-{i}.pdf") for i in range(5)]
    holdout = ex(FREIGHT, fingerprint="holdout", split="holdout")
    ai_row = ex(FREIGHT, fingerprint="ai", source="ai_prediction")
    ai_row["ai_generated"] = True
    result = summarize_train_corroboration_authority(
        document=doc(file_name="plain-current.pdf"),
        proposed_route=WAREHOUSE,
        confidence=0.95,
        train_examples=rows + [holdout, ai_row],
        contract=contract(),
    )
    assert result["eligible_train_example_count"] == 5
    assert result["authority_ready"] is True


def test_numeric_bc_reference_no_longer_vetoes_correct_warehouse_route():
    blockers = derive_universal_safety_blockers(
        document=doc(file_name="_Tumalo_invoice.pdf"),
        autonomy_decision=autonomy(WAREHOUSE_INTL),
        contract=contract(),
        bc_context={"verified_order_numbers": ["115357"]},
        support_examples=[],
    )
    assert not any("standard_order" in blocker for blocker in blockers)


def test_explicit_w_reference_still_vetoes_dropship_route():
    blockers = derive_universal_safety_blockers(
        document=doc(file_name="W118689_HWA.pdf"),
        autonomy_decision=autonomy(DROP_INTL),
        contract=contract(),
        bc_context={"verified_order_numbers": ["115357"]},
        support_examples=[],
    )
    assert any("reference family warehouse" in blocker for blocker in blockers)


def test_shipping_document_vendor_mismatch_is_not_treated_as_payable_vendor_conflict():
    blockers = derive_universal_safety_blockers(
        document=doc(vendor="Horseshoe Beverage", document_type="Shipping_Document"),
        autonomy_decision=autonomy(BALL_ORDERS),
        contract=contract(),
        bc_context={"status": "resolved", "bc_vendor_name": "Ball Metal Beverage Container", "verified_order_numbers": ["118434"]},
        support_examples=[],
    )
    assert not any("Business Central vendor conflicts" in blocker for blocker in blockers)


def test_ap_invoice_vendor_mismatch_still_fails_closed():
    blockers = derive_universal_safety_blockers(
        document=doc(vendor="Current Carrier", document_type="AP_Invoice"),
        autonomy_decision=autonomy(DROP),
        contract=contract(),
        bc_context={"status": "resolved", "bc_vendor_name": "Different Supplier", "verified_order_numbers": ["118434"]},
        support_examples=[],
    )
    assert any("Business Central vendor conflicts" in blocker for blocker in blockers)


def test_shipping_document_foreign_reference_is_not_a_supplier_identity_hazard():
    support = [
        ex(BALL_ORDERS, fingerprint="foreign", vendor="Ball Metal Beverage Container", document_type="Warehouse_Receipt", bc_context={"verified_order_numbers": ["W118434"]})
    ]
    decision = autonomy(BALL_ORDERS, refs=["W118434"], matched=["foreign"])
    blockers = derive_universal_safety_blockers(
        document=doc(vendor="Horseshoe Beverage", document_type="Shipping_Document", file_name="W118434_Horseshoe.pdf"),
        autonomy_decision=decision,
        contract=contract(),
        bc_context={"verified_order_numbers": ["W118434"]},
        support_examples=support,
    )
    assert not any("foreign-vendor exact-reference" in blocker for blocker in blockers)


def test_ap_invoice_foreign_reference_dependency_still_fails_closed():
    support = [
        ex(DROP, fingerprint="foreign", vendor="Other Carrier", bc_context={"verified_order_numbers": ["118434"]})
    ]
    decision = autonomy(DROP, refs=["118434"], matched=["foreign"])
    blockers = derive_universal_safety_blockers(
        document=doc(vendor="Current Carrier", document_type="AP_Invoice"),
        autonomy_decision=decision,
        contract=contract(),
        bc_context={"verified_order_numbers": ["118434"]},
        support_examples=support,
    )
    assert any("foreign-vendor exact-reference" in blocker for blocker in blockers)


def test_explicit_stop_pay_human_anchor_can_ignore_incidental_reference_and_nonfatal_unresolved():
    anchor = {"authority_ready": True, "earned_anchor": "explicit_stop_pay"}
    support = [
        ex(DNP, fingerprint="foreign", vendor="Other Vendor", text="DO NOT PAY", bc_context={"verified_order_numbers": ["118893"]})
    ]
    decision = autonomy(
        DNP,
        unresolved=["purchase order state could not be confirmed"],
        refs=["118893"],
        matched=["foreign"],
        anchor=anchor,
    )
    result = apply_learned_autonomy_safety(
        document=doc(vendor="Fast Track", text="DO NOT PAY; offset by credit", file_name="W118893 Fast Track.pdf"),
        autonomy_decision=decision,
        contract=contract(),
        bc_context={"verified_order_numbers": ["118893"]},
        support_examples=support,
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == DNP


def test_explicit_stop_pay_anchor_still_fails_closed_on_model_error():
    anchor = {"authority_ready": True, "earned_anchor": "explicit_stop_pay"}
    decision = autonomy(DNP, unresolved=["model_error:RateLimitError"], anchor=anchor)
    result = apply_learned_autonomy_safety(
        document=doc(text="DO NOT PAY"),
        autonomy_decision=decision,
        contract=contract(),
        bc_context={},
        support_examples=[],
    )
    assert result["decision"] == "needs_review"
    assert any("unresolved/model-error" in blocker for blocker in result["safety_blockers"])


def test_ai_prompt_contains_ownership_credit_dnp_wa_and_numeric_family_rules():
    seen = {}

    async def fake_send(prompt, model):
        seen["prompt"] = prompt
        return json.dumps({
            "proposed_route": WAREHOUSE,
            "confidence": 0.95,
            "evidence": ["human workflow"],
            "reasoning_summary": "uses learned workflow",
            "bc_refs_used": [],
            "unresolved": [],
            "matched_example_ids": [],
        })

    asyncio.run(propose_ap_route_ai_primary(
        document=doc(),
        bc_context={},
        contract=contract(),
        examples=[],
        learning_context={"eligible_train_example_count": 20},
        llm_send=fake_send,
    ))
    prompt = seen["prompt"]
    assert "Approval/processor child folders are GPI ownership assignments" in prompt
    assert "generic credit memo with no current stop-pay/invalidation evidence" in prompt
    assert "Storage/accessorial language by itself is not a stop-pay instruction" in prompt
    assert "WA-prefixed current reference is a warehouse-assembly structural family" in prompt
    assert "plain numeric BC/order reference is not a warehouse-versus-dropship discriminator" in prompt
