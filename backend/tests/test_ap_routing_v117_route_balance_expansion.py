from services import ap_routing_route_balance_expansion_service as balance


def _label(item_id, route, modified="2026-09-15T12:00:00Z"):
    return {
        "item_id": item_id,
        "file_name": f"{item_id}.pdf",
        "route_path": route,
        "modified_at": modified,
    }


def _train(item_id, route):
    return {"source_item_id": item_id, "route_path": route}


def test_route_balance_selects_sparsest_train_routes_dynamically():
    train = [
        *[_train(f"a-{i}", "Route A") for i in range(6)],
        *[_train(f"b-{i}", "Route B") for i in range(2)],
        _train("c-0", "Route C"),
    ]
    labels = [
        _label("new-a", "Route A"),
        _label("new-b-1", "Route B"),
        _label("new-b-2", "Route B"),
        _label("new-c-1", "Route C"),
        _label("new-c-2", "Route C"),
    ]

    result = balance.select_underrepresented_train_route_labels(
        labels,
        train,
        excluded_source_item_ids=set(),
        already_selected_source_item_ids=set(),
        initial_selected_route_counts={},
        max_additional=3,
        max_additional_per_route=30,
    )

    assert [row["route_path"] for _, row in result["selected_pairs"]] == [
        "Route C",
        "Route C",
        "Route B",
    ]
    assert result["selected_by_route"] == {"Route B": 1, "Route C": 2}


def test_route_balance_never_admits_route_absent_from_train():
    train = [_train("a-1", "Route A")]
    labels = [
        _label("new-a", "Route A"),
        _label("holdout-only", "Route HOLDOUT ONLY"),
        _label("brand-new", "Brand New Route"),
    ]

    result = balance.select_underrepresented_train_route_labels(
        labels,
        train,
        excluded_source_item_ids=set(),
        already_selected_source_item_ids=set(),
        initial_selected_route_counts={},
        max_additional=10,
        max_additional_per_route=30,
    )

    assert [row["item_id"] for _, row in result["selected_pairs"]] == ["new-a"]
    assert set(result["candidate_route_counts"]) == {"Route A"}


def test_route_balance_excludes_frozen_base_and_prior_expansion_ids():
    train = [_train("base-a", "Route A"), _train("base-b", "Route B")]
    labels = [
        _label("base-a", "Route A"),
        _label("holdout-b", "Route B"),
        _label("vendor-selected", "Route B"),
        _label("eligible-b", "Route B"),
    ]

    result = balance.select_underrepresented_train_route_labels(
        labels,
        train,
        excluded_source_item_ids={"base-a", "base-b", "holdout-b"},
        already_selected_source_item_ids={"vendor-selected"},
        initial_selected_route_counts={"Route B": 1},
        max_additional=10,
        max_additional_per_route=30,
    )

    assert [row["item_id"] for _, row in result["selected_pairs"]] == ["eligible-b"]


def test_route_balance_respects_remaining_budget_and_shared_route_cap():
    train = [_train("a-0", "Route A"), _train("b-0", "Route B")]
    labels = [
        *[_label(f"new-a-{i}", "Route A") for i in range(5)],
        *[_label(f"new-b-{i}", "Route B") for i in range(5)],
    ]

    result = balance.select_underrepresented_train_route_labels(
        labels,
        train,
        excluded_source_item_ids=set(),
        already_selected_source_item_ids=set(),
        initial_selected_route_counts={"Route A": 2, "Route B": 1},
        max_additional=3,
        max_additional_per_route=2,
    )

    assert result["selected_count"] == 1
    assert result["selected_by_route"] == {"Route B": 1}
    assert result["initial_expansion_route_counts"] == {"Route A": 2, "Route B": 1}
