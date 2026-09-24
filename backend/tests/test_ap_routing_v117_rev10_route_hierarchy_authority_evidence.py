import inspect

from services.ap_routing_ai_primary_service import (
    _augment_prompt_with_train_context,
    _build_proposal_review_prompt,
    _proposal_review_needed,
)
from services.ap_routing_decision_service import RoutePrediction
from services.ap_routing_business_context_expansion_service import (
    _matches_deficit,
    build_train_business_context_deficits,
)
from services.ap_routing_learned_autonomy_service import evaluate_learned_autonomy
from services.ap_routing_train_context_service import (
    _route_balanced_neighborhood,
    build_train_learning_context,
)


def _train(
    item_id,
    route,
    *,
    vendor="Acme",
    file_name="W118500_invoice.pdf",
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
        "raw_text_excerpt": raw_text,
        "extracted_fields": {
            "vendor": vendor,
            "document_type": "AP_Invoice",
        },
        "bc_context": {},
        "route_path": route,
    }


def _current(*, vendor="Acme", file_name="W119900_current.pdf"):
    return {
        "vendor_name": vendor,
        "vendor_canonical": vendor,
        "document_type": "AP_Invoice",
        "suggested_job_type": "AP_Invoice",
        "file_name": file_name,
        "raw_text": "",
        "extracted_fields": {
            "vendor": vendor,
            "document_type": "AP_Invoice",
        },
        "bc_context": {},
    }


def _counts(rows, key):
    return {row[key]: row["count"] for row in rows}


def test_rev11_nearest_train_context_preserves_repeated_route_density_without_crowdout():
    ranked = [
        {"fingerprint": "a1", "route_path": "Route A"},
        {"fingerprint": "a2", "route_path": "Route A"},
        {"fingerprint": "a3", "route_path": "Route A"},
        {"fingerprint": "a4", "route_path": "Route A"},
        {"fingerprint": "b1", "route_path": "Route B"},
        {"fingerprint": "c1", "route_path": "Route C"},
        {"fingerprint": "d1", "route_path": "Route D"},
    ]

    selected = _route_balanced_neighborhood(
        ranked,
        limit=6,
        max_per_route=3,
    )
    routes = [row["route_path"] for row in selected]

    assert routes[:3] == ["Route A", "Route A", "Route A"]
    assert "Route B" in routes
    assert "Route C" in routes
    assert "Route D" in routes
    assert routes.count("Route A") == 3


def test_rev10_route_hierarchy_context_preserves_parent_and_child_counts_train_only():
    train = [
        _train("parent-1", "S&H Invoices Approved"),
        _train("parent-2", "S&H Invoices Approved"),
        _train("child-1", "S&H Invoices Approved/Amanda to process"),
        _train("child-2", "S&H Invoices Approved/Jess to process"),
        _train(
            "heldout-child",
            "S&H Invoices Approved/Amanda to process",
            split="holdout",
        ),
    ]

    context = build_train_learning_context(
        _current(),
        train,
        contract={},
        neighborhood_limit=24,
        route_limit=12,
    )

    hierarchy = context["route_hierarchy_same_vendor"]
    exact = _counts(hierarchy["exact_route_counts"], "route_path")
    assert exact["S&H Invoices Approved"] == 2
    assert exact["S&H Invoices Approved/Amanda to process"] == 1
    assert exact["S&H Invoices Approved/Jess to process"] == 1

    parent = next(
        row
        for row in hierarchy["parent_child_counts"]
        if row["parent_path"] == "S&H Invoices Approved"
    )
    assert parent["parent_exact_count"] == 2
    assert parent["child_count"] == 2


def test_rev10_prompt_requires_topology_before_workflow_and_parent_before_unsupported_child():
    prompt = _augment_prompt_with_train_context(
        "SYSTEM\nINPUT:\n{}",
        {
            "eligible_train_example_count": 10,
            "current_vendor": "Acme",
            "route_hierarchy_same_vendor": {},
            "route_hierarchy_same_reference_family": {},
            "route_hierarchy_nearest": {},
        },
    )

    assert "Decide routing topology before workflow detail" in prompt
    assert "Treat route depth as evidence-sensitive" in prompt
    assert "choose the supported parent" in prompt
    assert "Filename comments and historical notes" in prompt
    assert "verified PO, purchase receipt, or BC transaction" in prompt
    assert "Do not stop at a workflow parent merely because it is broader" in prompt
    assert "Distinguish sibling leaves by CURRENT evidence" in prompt
    assert "The exact phrase cost variance is discriminating workflow evidence" in prompt
    assert "short paid, underpaid, balance difference" in prompt
    assert "Inventory, warehouse receipt, packing-list, BOL, photo, and transfer semantics" in prompt
    assert "Special top-level queues such as Meg to Process, Rhonda - Issues, and Miscellaneous" in prompt


def test_rev10_second_pass_review_is_bounded_to_uncertain_or_parent_proposals():
    high_conf_leaf = RoutePrediction(
        proposed_route="S&H Invoices waiting for approval/Andy to approve",
        confidence=0.96,
        evidence=[],
        reasoning_summary="supported leaf",
        bc_refs_used=[],
        unresolved=[],
        matched_example_ids=[],
        model="gpt-5.6-sol",
    )
    context = {
        "route_hierarchy_same_vendor": {
            "parent_child_counts": [
                {
                    "parent_path": "S&H Invoices waiting for approval",
                    "parent_exact_count": 1,
                    "child_count": 4,
                    "children": [
                        {
                            "route_path": "S&H Invoices waiting for approval/Andy to approve",
                            "count": 4,
                        }
                    ],
                }
            ]
        }
    }
    assert _proposal_review_needed(high_conf_leaf, context) is False

    low_conf_leaf = RoutePrediction(
        proposed_route=high_conf_leaf.proposed_route,
        confidence=0.72,
        evidence=[],
        reasoning_summary="uncertain leaf",
        bc_refs_used=[],
        unresolved=[],
        matched_example_ids=[],
        model="gpt-5.6-sol",
    )
    assert _proposal_review_needed(low_conf_leaf, context) is True

    parent = RoutePrediction(
        proposed_route="S&H Invoices waiting for approval",
        confidence=0.95,
        evidence=[],
        reasoning_summary="generic parent",
        bc_refs_used=[],
        unresolved=[],
        matched_example_ids=[],
        model="gpt-5.6-sol",
    )
    assert _proposal_review_needed(parent, context) is True


def test_rev10_second_pass_prompt_has_no_deterministic_route_recommendation():
    first = RoutePrediction(
        proposed_route="S&H Invoices waiting for approval",
        confidence=0.76,
        evidence=["first pass"],
        reasoning_summary="uncertain",
        bc_refs_used=[],
        unresolved=[],
        matched_example_ids=[],
        model="gpt-5.6-sol",
    )
    prompt = _build_proposal_review_prompt(
        "SYSTEM\nINPUT:\n{}",
        first,
        {"eligible_train_example_count": 10},
    )
    assert "SECOND-PASS PROPOSAL REVIEW" in prompt
    assert "selected by the AI from the supplied routing_contract" in prompt
    assert "do not collapse it to the parent" in prompt
    assert "Low confidence or ordinary caution alone is not unresolved" in prompt
    assert "FIRST_PASS_AI_PROPOSAL" in prompt


def test_rev10_same_vendor_route_support_deficit_is_train_only():
    train = [
        _train(
            "base",
            "S&H Invoices Approved",
            vendor="LSI",
            file_name="W119001_LSI.pdf",
        ),
        _train(
            "heldout",
            "S&H Invoices Approved",
            vendor="LSI",
            file_name="W119002_LSI.pdf",
            split="holdout",
        ),
    ]

    deficits = build_train_business_context_deficits(train, routing_contract={})
    matches = [
        row
        for row in deficits
        if row["kind"] == "same_vendor_document_type_route_support"
        and row["vendor"] == "lsi"
        and row["route_path"] == "S&H Invoices Approved"
    ]

    assert len(matches) == 1
    assert matches[0]["support_count"] == 1
    assert matches[0]["minimum_support"] == 3
    assert matches[0]["additional_support_needed"] == 2

    # A broader REV10 route-support deficit must never bypass REV8's more
    # specific discriminating-semantic expansion contract.
    semantic_train = [
        _train(
            "semantic-base",
            "Warehouse Route",
            vendor="Acme",
            file_name="invoice.pdf",
            raw_text="dunnage",
        ),
    ]
    semantic_deficits = build_train_business_context_deficits(
        semantic_train,
        routing_contract={},
    )
    assert any(
        row["kind"] == "discriminating_semantic_route_support"
        and row["route_path"] == "Warehouse Route"
        for row in semantic_deficits
    )
    assert not any(
        row["kind"] in {
            "same_vendor_document_type_route_support",
            "same_vendor_document_type_reference_family_route_support",
            "reference_family_route_support",
        }
        and row["route_path"] == "Warehouse Route"
        for row in semantic_deficits
    )


def test_rev10_reference_family_deficits_require_exact_human_route_and_reference_family():
    train = [
        _train(
            "base",
            "Warehouse International",
            vendor="Vendor A",
            file_name="W118500_invoice.pdf",
        ),
    ]
    deficits = build_train_business_context_deficits(train, routing_contract={})
    deficit = next(
        row
        for row in deficits
        if row["kind"] == "reference_family_route_support"
        and row["route_path"] == "Warehouse International"
        and row["required_reference_family"] == "w_reference"
    )

    good = _train(
        "good",
        "Warehouse International",
        vendor="Vendor B",
        file_name="W118501_invoice.pdf",
    )
    wrong_route = _train(
        "wrong-route",
        "Warehouse Not International",
        vendor="Vendor B",
        file_name="W118502_invoice.pdf",
    )
    wrong_reference = _train(
        "wrong-ref",
        "Warehouse International",
        vendor="Vendor B",
        file_name="118503_invoice.pdf",
    )

    assert _matches_deficit(good, deficit) is True
    assert _matches_deficit(wrong_route, deficit) is False
    assert _matches_deficit(wrong_reference, deficit) is False


def test_rev10_reference_family_expansion_excludes_descriptor_only_and_dnp():
    train = [
        _train(
            "descriptor",
            "Warehouse Not International",
            file_name="ordinary_invoice.pdf",
        ),
        _train(
            "dnp",
            "DO NOT PAY",
            file_name="W118700_do_not_pay.pdf",
            raw_text="DO NOT PAY",
        ),
    ]

    deficits = build_train_business_context_deficits(train, routing_contract={})
    assert not any(
        row["kind"] == "reference_family_route_support"
        and row["route_path"] == "Warehouse Not International"
        for row in deficits
    )
    assert not any(
        row["kind"] in {
            "same_vendor_document_type_route_support",
            "same_vendor_document_type_reference_family_route_support",
            "reference_family_route_support",
        }
        and row["route_path"] == "DO NOT PAY"
        for row in deficits
    )


def test_rev10_preserves_existing_learned_autonomy_confidence_floor():
    signature = inspect.signature(evaluate_learned_autonomy)
    assert signature.parameters["minimum_model_confidence"].default == 0.90
