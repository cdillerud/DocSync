import inspect
import json

import pytest

from services import ap_routing_relevant_learning_service as relevant
from services.ap_routing_ai_primary_service import _augment_prompt_with_train_context
from services.ap_routing_business_context_expansion_service import (
    _REV8_DISCRIMINATING_SEMANTICS,
    _REV8_MINIMUM_DISCRIMINATING_SEMANTIC_SUPPORT,
    build_train_business_context_deficits,
    select_hydrated_business_context_examples,
)
from services.ap_routing_learned_autonomy_service import (
    DISCRIMINATING_WORKFLOW_SEMANTICS,
    MINIMUM_DISCRIMINATING_SEMANTIC_SUPPORT,
    evaluate_learned_autonomy,
)


def _train(
    item_id,
    route,
    *,
    vendor="Acme",
    file_name="invoice.pdf",
    raw_text="",
    split="train",
    label_source="accounting_temp",
):
    return {
        "source_item_id": item_id,
        "fingerprint": item_id,
        "label_source": label_source,
        "split": split,
        "active": True,
        "vendor_name": vendor,
        "document_type": "AP_Invoice",
        "suggested_job_type": "AP_Invoice",
        "file_name": file_name,
        "raw_text": raw_text,
        "extracted_fields": {"vendor": vendor, "document_type": "AP_Invoice"},
        "bc_context": {},
        "route_path": route,
    }


def _current(*, vendor="Acme", file_name="current.pdf", raw_text=""):
    return {
        "vendor_name": vendor,
        "vendor_canonical": vendor,
        "document_type": "AP_Invoice",
        "suggested_job_type": "AP_Invoice",
        "file_name": file_name,
        "raw_text": raw_text,
        "extracted_fields": {"vendor": vendor, "document_type": "AP_Invoice"},
        "bc_context": {},
    }


def test_rev8_same_vendor_owns_prompt_core_before_higher_scored_foreign_vendor(monkeypatch):
    same_vendor = [
        _train(f"same-{i}", f"Same Route {i}", vendor="Acme")
        for i in range(6)
    ]
    foreign = [
        _train(f"foreign-{i}", f"Foreign Route {i}", vendor="Other Vendor")
        for i in range(4)
    ]

    def fake_score(document, example):
        return 1000.0 if example["vendor_name"] == "Other Vendor" else 1.0

    monkeypatch.setattr(relevant, "learned_relevance_score", fake_score)
    selected = relevant.build_relevant_learning_examples(
        _current(vendor="Acme"),
        foreign + same_vendor,
        limit=8,
    )

    assert len(selected) == 8
    assert [row["vendor_name"] for row in selected[:6]] == ["Acme"] * 6
    assert all(row["_learned_same_vendor"] for row in selected[:6])
    assert sum(row["vendor_name"] == "Other Vendor" for row in selected) == 2


def test_rev8_prompt_explicitly_rejects_foreign_vendor_exact_reference_as_authority():
    prompt = _augment_prompt_with_train_context(
        "SYSTEM\nINPUT:\n{}",
        {
            "eligible_train_example_count": 3,
            "current_vendor": "Acme",
            "same_vendor_example_count": 2,
        },
    )
    assert "same-vendor HUMAN TRAIN examples" in prompt
    assert "foreign-vendor exact-reference example" in prompt
    assert "lower confidence" in prompt
    payload = json.loads(prompt.split("INPUT:\n", 1)[1])
    assert payload["train_learning_context"]["current_vendor"] == "Acme"


def test_rev8_semantic_deficits_are_train_only_and_do_not_use_holdout_route():
    train = [
        _train("train-dunnage", "Warehouse Route", raw_text="dunnage reconciliation"),
        _train(
            "holdout-dunnage",
            "Secret Holdout Route",
            raw_text="dunnage reconciliation",
            split="holdout",
        ),
    ]
    deficits = build_train_business_context_deficits(train, routing_contract={})
    semantic = [
        row
        for row in deficits
        if row["kind"] == "discriminating_semantic_route_support"
        and row["required_semantics"] == ["dunnage"]
    ]

    assert len(semantic) == 1
    assert semantic[0]["route_path"] == "Warehouse Route"
    assert semantic[0]["support_count"] == 1
    assert semantic[0]["additional_support_needed"] == 1
    assert all(row["route_path"] != "Secret Holdout Route" for row in deficits)


def test_rev8_semantic_expansion_requires_exact_human_route_and_semantic_match():
    train = [
        _train("base", "Warehouse Route", raw_text="dunnage"),
    ]
    candidates = [
        _train("good", "Warehouse Route", raw_text="dunnage return"),
        _train("wrong-route", "Dropship Route", raw_text="dunnage return"),
        _train("wrong-semantic", "Warehouse Route", raw_text="ordinary invoice"),
    ]

    result = select_hydrated_business_context_examples(
        candidates,
        train,
        routing_contract={},
        initial_selected_route_counts={},
        max_additional=5,
        max_additional_per_route=30,
    )

    semantic_selected = [
        row["source_item_id"]
        for row in result["examples"]
        if row["source_item_id"] in {"good", "wrong-route", "wrong-semantic"}
    ]
    assert semantic_selected == ["good"]
    assert (
        result["selected_by_deficit_kind"]["discriminating_semantic_route_support"]
        >= 1
    )


def test_rev8_does_not_create_semantic_only_dnp_expansion_authority():
    deficits = build_train_business_context_deficits(
        [_train("dnp-storage", "DO NOT PAY", raw_text="yard storage charge")],
        routing_contract={},
    )
    assert not any(
        row["kind"] == "discriminating_semantic_route_support"
        and row["route_path"] == "DO NOT PAY"
        for row in deficits
    )


def test_rev8_semantic_targets_match_existing_authority_policy_without_threshold_change():
    assert _REV8_DISCRIMINATING_SEMANTICS == DISCRIMINATING_WORKFLOW_SEMANTICS
    assert (
        _REV8_MINIMUM_DISCRIMINATING_SEMANTIC_SUPPORT
        == MINIMUM_DISCRIMINATING_SEMANTIC_SUPPORT
        == 2
    )
    signature = inspect.signature(evaluate_learned_autonomy)
    assert signature.parameters["minimum_model_confidence"].default == 0.90
