import asyncio
import json

from services.ap_routing_ai_primary_service import propose_ap_route_ai_primary
from services.ap_routing_learned_safety_service import derive_universal_safety_blockers


DNP = "DO NOT PAY"
WAREHOUSE = "Warehouse International"
DROPSHIP = "Dropship International"


def contract():
    return {
        "version": "v117-prompt-safety-test",
        "static_routes": [DNP, WAREHOUSE, DROPSHIP],
        "dynamic_routes": [],
        "manual_only_routes": [],
        "review_route": "",
    }


def current(file_name="100001_Vendor.pdf", text=""):
    return {
        "file_name": file_name,
        "vendor_name": "Current Vendor",
        "vendor_canonical": "Current Vendor",
        "document_type": "AP_Invoice",
        "raw_text": text,
        "extracted_fields": {"vendor": "Current Vendor", "document_type": "AP_Invoice"},
    }


def example(index, text="historical semantic evidence"):
    return {
        "fingerprint": f"ex-{index}",
        "vendor_name": f"Vendor {index}",
        "document_type": "AP_Invoice",
        "route_path": DNP,
        "label_source": "accounting_temp",
        "raw_text_excerpt": text,
        "extracted_fields": {"vendor": f"Vendor {index}", "document_type": "AP_Invoice"},
        "file_name": f"historical-{index}.pdf",
    }


def test_ai_prompt_contains_bounded_semantic_excerpt_from_human_example():
    seen = {}

    async def fake_send(prompt, model):
        seen["payload"] = json.loads(prompt.split("INPUT:\n", 1)[1])
        return json.dumps({
            "proposed_route": DNP,
            "confidence": 0.99,
            "evidence": ["learned semantic example"],
            "reasoning_summary": "learned from human example",
            "bc_refs_used": [],
            "unresolved": [],
            "matched_example_ids": [],
        })

    asyncio.run(propose_ap_route_ai_primary(
        document=current(text="DO NOT PAY"),
        bc_context={},
        contract=contract(),
        examples=[example(1, text="DO NOT PAY because invoice was replaced")],
        llm_send=fake_send,
    ))
    prompt_example = seen["payload"]["similar_labeled_examples"][0]
    assert "DO NOT PAY because invoice was replaced" in prompt_example["key_evidence"]["semantic_excerpt"]


def test_ai_primary_direct_call_hard_caps_prompt_to_eight_examples():
    seen = {}

    async def fake_send(prompt, model):
        seen["payload"] = json.loads(prompt.split("INPUT:\n", 1)[1])
        return json.dumps({
            "proposed_route": DNP,
            "confidence": 0.99,
            "evidence": [],
            "reasoning_summary": "bounded prompt",
            "bc_refs_used": [],
            "unresolved": [],
            "matched_example_ids": [],
        })

    result = asyncio.run(propose_ap_route_ai_primary(
        document=current(text="DO NOT PAY"),
        bc_context={},
        contract=contract(),
        examples=[example(i) for i in range(20)],
        llm_send=fake_send,
    ))
    assert len(seen["payload"]["similar_labeled_examples"]) == 8
    assert result["few_shot_count"] == 8


def test_explicit_w_filename_outranks_incidental_numeric_bc_reference_for_family_safety():
    blockers = derive_universal_safety_blockers(
        document=current(file_name="W118689_HWA_HSIA.pdf"),
        autonomy_decision={"ai_proposed_route": WAREHOUSE, "prediction": {}},
        contract=contract(),
        bc_context={"verified_order_numbers": ["115357"]},
        support_examples=[],
    )
    assert not any("reference family standard_order" in blocker for blocker in blockers)
    assert not any("conflicts with AI route family warehouse" in blocker for blocker in blockers)


def test_explicit_w_filename_still_vetoes_dropship_ai_route():
    blockers = derive_universal_safety_blockers(
        document=current(file_name="W118689_HWA_HSIA.pdf"),
        autonomy_decision={"ai_proposed_route": DROPSHIP, "prediction": {}},
        contract=contract(),
        bc_context={"verified_order_numbers": ["115357"]},
        support_examples=[],
    )
    assert any("reference family warehouse" in blocker for blocker in blockers)
    assert any("conflicts with AI route family dropship" in blocker for blocker in blockers)
