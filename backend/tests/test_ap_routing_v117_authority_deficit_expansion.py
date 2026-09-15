from services import ap_routing_authority_deficit_expansion_service as deficit


def _row(item_id, route, *, vendor="Acme", doc_type="AP_Invoice", file_name=None, semantics=()):
    return {
        "source_item_id": item_id,
        "route_path": route,
        "vendor_name": vendor,
        "document_type": doc_type,
        "file_name": file_name or f"{item_id}.pdf",
        "learned_feature_schema": "v117-semantic-v1",
        "learned_semantic_features": list(semantics),
        "label_source": "accounting_temp",
    }


def test_build_deficit_uses_existing_support_threshold_without_lowering_it():
    train = [_row(f"a{i}", "Route A") for i in range(1, 5)]
    rows = deficit.build_train_authority_deficits(train, routing_contract={})
    same = [row for row in rows if row["kind"] == "same_vendor_document_type"]
    assert len(same) == 1
    assert same[0]["minimum_support"] == 5
    assert same[0]["minimum_purity"] == 0.90
    assert same[0]["additional_support_needed"] == 1


def test_ambiguous_train_slice_is_not_broken_by_expansion_sampling():
    train = [
        _row("a1", "Route A"),
        _row("a2", "Route A"),
        _row("b1", "Route B"),
        _row("b2", "Route B"),
    ]
    rows = deficit.build_train_authority_deficits(train, routing_contract={})
    assert not [row for row in rows if row["kind"] == "same_vendor_document_type"]


def test_hydrated_candidate_must_reduce_a_train_derived_deficit():
    train = [_row(f"a{i}", "Route A") for i in range(1, 5)]
    candidates = [
        _row("good", "Route A"),
        _row("wrong-route", "Route B"),
        _row("wrong-vendor", "Route A", vendor="Different Vendor"),
    ]
    result = deficit.select_hydrated_authority_deficit_examples(
        candidates,
        train,
        routing_contract={},
        initial_selected_route_counts={},
        max_additional=10,
        max_additional_per_route=30,
    )
    assert [row["source_item_id"] for row in result["selected_examples"]] == ["good"]


def test_route_absent_from_train_cannot_be_admitted():
    train = [_row(f"a{i}", "Route A") for i in range(1, 5)]
    candidates = [_row("new-route", "Brand New Route")]
    result = deficit.select_hydrated_authority_deficit_examples(
        candidates,
        train,
        routing_contract={},
        initial_selected_route_counts={},
        max_additional=10,
        max_additional_per_route=30,
    )
    assert result["selected_count"] == 0


def test_reference_family_deficit_prefers_matching_hydrated_candidate():
    train = [
        _row("a1", "Route A", file_name="W10001_Acme.pdf"),
        _row("a2", "Route A", file_name="W10002_Acme.pdf"),
        _row("a3", "Route A", file_name="W10003_Acme.pdf"),
        _row("a4", "Route A", file_name="W10004_Acme.pdf"),
    ]
    candidates = [
        _row("numeric", "Route A", file_name="12345_Acme.pdf"),
        _row("wref", "Route A", file_name="W10005_Acme.pdf"),
    ]
    result = deficit.select_hydrated_authority_deficit_examples(
        candidates,
        train,
        routing_contract={},
        initial_selected_route_counts={},
        max_additional=1,
        max_additional_per_route=30,
    )
    assert result["selected_examples"][0]["source_item_id"] == "wref"


def test_discriminating_semantic_deficit_is_train_derived_and_reduced():
    train = [
        _row("a1", "Route A", semantics=("storage_accessorial",)),
        _row("a2", "Route A", semantics=("storage_accessorial",)),
    ]
    candidates = [
        _row("generic", "Route A"),
        _row("storage", "Route A", semantics=("storage_accessorial",)),
    ]
    result = deficit.select_hydrated_authority_deficit_examples(
        candidates,
        train,
        routing_contract={},
        initial_selected_route_counts={},
        max_additional=1,
        max_additional_per_route=30,
    )
    assert result["selected_examples"][0]["source_item_id"] == "storage"
    assert result["selected_by_deficit_kind"]["same_vendor_document_type_semantics"] >= 1


def test_dnp_deficit_requires_explicit_stop_pay_candidate():
    train = [
        _row("d1", "DO NOT PAY", semantics=("explicit_stop_pay",)),
        _row("d2", "DO NOT PAY", semantics=("explicit_stop_pay",)),
        _row("d3", "DO NOT PAY", semantics=("explicit_stop_pay",)),
        _row("d4", "DO NOT PAY", semantics=("explicit_stop_pay",)),
    ]
    candidates = [
        _row("generic-dnp", "DO NOT PAY"),
        _row("explicit-dnp", "DO NOT PAY", semantics=("explicit_stop_pay",)),
    ]
    result = deficit.select_hydrated_authority_deficit_examples(
        candidates,
        train,
        routing_contract={},
        initial_selected_route_counts={},
        max_additional=1,
        max_additional_per_route=30,
    )
    assert result["selected_examples"][0]["source_item_id"] == "explicit-dnp"


def test_selection_respects_total_budget_and_existing_shared_route_cap():
    train = [
        _row("a1", "Route A", vendor="Vendor A"),
        _row("a2", "Route A", vendor="Vendor A"),
        _row("b1", "Route B", vendor="Vendor B"),
        _row("b2", "Route B", vendor="Vendor B"),
    ]
    candidates = [
        _row("a3", "Route A", vendor="Vendor A"),
        _row("a4", "Route A", vendor="Vendor A"),
        _row("b3", "Route B", vendor="Vendor B"),
        _row("b4", "Route B", vendor="Vendor B"),
    ]
    result = deficit.select_hydrated_authority_deficit_examples(
        candidates,
        train,
        routing_contract={},
        initial_selected_route_counts={"Route A": 2, "Route B": 1},
        max_additional=2,
        max_additional_per_route=2,
    )
    assert result["selected_count"] == 1
    assert result["selected_by_route"] == {"Route B": 1}
