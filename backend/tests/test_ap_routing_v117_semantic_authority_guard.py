import json

from services.ap_routing_ai_primary_service import _augment_prompt_with_train_context
from services.ap_routing_learned_autonomy_service import evaluate_learned_autonomy
from services.ap_routing_learned_features_service import semantic_features


PROPOSED = "Rhonda - Issues"
OTHER = "Dropship Not International/Freight"


def doc(text="detention invoice"):
    return {
        "file_name": "114745_TUMALO_0309048 CP_07012026 - DET waiting for corrected invoice.pdf",
        "vendor_name": "TUMALO CREEK TRANSPORTATION",
        "vendor_canonical": "TUMALO CREEK TRANSPORTATION",
        "document_type": "AP_Invoice",
        "raw_text": text,
        "extracted_fields": {
            "vendor": "TUMALO CREEK TRANSPORTATION",
            "document_type": "AP_Invoice",
        },
        "bc_context": {},
    }


def ex(route, fingerprint, *, text="standard freight invoice"):
    return {
        "fingerprint": fingerprint,
        "vendor_name": "TUMALO CREEK TRANSPORTATION",
        "normalized_vendor": "TUMALO CREEK TRANSPORTATION",
        "document_type": "AP_Invoice",
        "route_path": route,
        "label_source": "accounting_temp",
        "active": True,
        "split": "train",
        "file_name": f"{fingerprint}.pdf",
        "raw_text_excerpt": text,
        "extracted_fields": {
            "vendor": "TUMALO CREEK TRANSPORTATION",
            "document_type": "AP_Invoice",
        },
        "bc_context": {},
    }


def ai(route=PROPOSED, confidence=0.98):
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


def test_discriminating_workflow_blocks_broad_vendor_autonomy_with_only_one_semantic_support():
    rows = [
        ex(PROPOSED, "semantic-support-1", text="detention invoice awaiting correction"),
        *[ex(PROPOSED, f"broad-support-{i}") for i in range(6)],
        ex(OTHER, "contradiction"),
    ]

    decision = evaluate_learned_autonomy(
        document=doc(),
        ai_decision=ai(),
        train_examples=rows,
    )

    guard = decision["discriminating_semantic_authority"]
    assert guard["active"] is True
    assert "detention" in guard["features"]
    assert guard["support_count"] == 1
    assert guard["minimum_support"] == 2
    assert guard["authority_ready"] is False
    assert decision["decision"] == "needs_review"
    assert decision["route_path"] == ""
    assert decision["ai_proposed_route"] == PROPOSED


def test_discriminating_workflow_allows_broad_vendor_autonomy_after_two_semantic_supports():
    rows = [
        ex(PROPOSED, "semantic-support-1", text="detention invoice awaiting correction"),
        ex(PROPOSED, "semantic-support-2", text="detention freight invoice"),
        *[ex(PROPOSED, f"broad-support-{i}") for i in range(5)],
        ex(OTHER, "contradiction"),
    ]

    decision = evaluate_learned_autonomy(
        document=doc(),
        ai_decision=ai(),
        train_examples=rows,
    )

    guard = decision["discriminating_semantic_authority"]
    assert guard["active"] is True
    assert guard["support_count"] >= 2
    assert guard["authority_ready"] is True
    assert decision["decision"] == "auto_route"
    assert decision["route_path"] == PROPOSED
    assert decision["route_preserved"] is True


def test_receiving_language_is_inventory_semantic_and_one_matching_support_stays_review():
    receiving = doc(text="purchase receipt notification ready to receive into warehouse")
    assert "inventory" in semantic_features(receiving)
    assert "inventory" in semantic_features(
        {
            "file_name": "118911_REILE'S_090326_BOL - need to receive.pdf",
            "raw_text": "",
            "extracted_fields": {},
        }
    )

    rows = [
        ex(PROPOSED, "receiving-support-1", text="warehouse receipt ready to receive"),
        *[ex(PROPOSED, f"receiving-broad-{i}") for i in range(6)],
        ex(OTHER, "receiving-contradiction"),
    ]
    decision = evaluate_learned_autonomy(
        document=receiving,
        ai_decision=ai(),
        train_examples=rows,
    )

    guard = decision["discriminating_semantic_authority"]
    assert guard["active"] is True
    assert "inventory" in guard["features"]
    assert guard["support_count"] == 1
    assert guard["authority_ready"] is False
    assert decision["decision"] == "needs_review"
    assert decision["route_path"] == ""


def test_receiving_language_can_earn_only_after_two_route_matching_semantic_supports():
    receiving = doc(text="purchase receipt notification need to receive into warehouse")
    rows = [
        ex(PROPOSED, "receiving-support-1", text="warehouse receipt ready to receive"),
        ex(PROPOSED, "receiving-support-2", text="purchase receipt need to receive"),
        *[ex(PROPOSED, f"receiving-broad-{i}") for i in range(5)],
        ex(OTHER, "receiving-contradiction"),
    ]
    decision = evaluate_learned_autonomy(
        document=receiving,
        ai_decision=ai(),
        train_examples=rows,
    )

    guard = decision["discriminating_semantic_authority"]
    assert guard["active"] is True
    assert "inventory" in guard["features"]
    assert guard["support_count"] >= 2
    assert guard["authority_ready"] is True
    assert decision["decision"] == "auto_route"
    assert decision["route_path"] == PROPOSED
    assert decision["route_preserved"] is True


def _prompt_with_dynamic_context(dynamic_children):
    base_prompt = "BASE RULES\n\nINPUT:\n" + json.dumps({"document": {"file_name": "114022 HWA.pdf"}})
    context = {
        "eligible_train_example_count": 12,
        "dynamic_route_usage_same_vendor": [
            {
                "prefix": "Dropship International",
                "parent_count": 8,
                "dynamic_child_count": len(dynamic_children),
                "dynamic_children": dynamic_children,
            }
        ],
    }
    return _augment_prompt_with_train_context(base_prompt, context)


def test_dynamic_child_prompt_forbids_generalizing_one_historical_child_to_new_leaf():
    prompt = _prompt_with_dynamic_context(
        [{"route_path": "Dropship International/114020", "count": 1}]
    )
    assert "at least two distinct entries in dynamic_children" in prompt
    assert "A single historical dynamic child is not a reusable pattern" in prompt
    payload = json.loads(prompt.split("INPUT:\n", 1)[1])
    usage = payload["train_learning_context"]["dynamic_route_usage_same_vendor"][0]
    assert usage["parent_count"] == 8
    assert usage["dynamic_children"] == [
        {"route_path": "Dropship International/114020", "count": 1}
    ]


def test_dynamic_child_prompt_preserves_exact_observed_child_as_candidate():
    prompt = _prompt_with_dynamic_context(
        [{"route_path": "Dropship International/114020", "count": 1}]
    )
    assert "If the exact current child route itself appears in dynamic_children" in prompt
    assert "that exact observed child may still be considered" in prompt
