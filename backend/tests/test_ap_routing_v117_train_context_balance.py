from services import ap_routing_train_context_service as train_context


def _row(name: str, route: str, score: float, **extra):
    row = {
        "document_id": name,
        "label_source": "accounting_temp",
        "route_path": route,
        "score": score,
        "vendor_name": "Example Vendor",
        "document_type": "invoice",
    }
    row.update(extra)
    return row


def _patch_route_neutral_scoring(monkeypatch):
    monkeypatch.setattr(
        train_context,
        "learned_relevance_score",
        lambda _document, row: float(row["score"]),
    )
    monkeypatch.setattr(
        train_context,
        "feature_similarity",
        lambda _document, _row: {"shared_semantic_features": []},
    )
    monkeypatch.setattr(train_context, "reference_family", lambda _row: "descriptor_or_none")
    monkeypatch.setattr(train_context, "semantic_features", lambda _row: set())


def test_route_balanced_context_prevents_dominant_route_crowd_out(monkeypatch):
    _patch_route_neutral_scoring(monkeypatch)
    rows = [
        _row("a-1", "Warehouse Not International", 100.0),
        _row("a-2", "Warehouse Not International", 99.0),
        _row("b-1", "Vendor Credit Memos", 60.0),
    ]

    result = train_context.build_train_learning_context(
        {"vendor_name": "Example Vendor", "document_type": "invoice"},
        rows,
        contract={"dynamic_routes": []},
        neighborhood_limit=2,
        route_limit=12,
    )

    observations = result["nearest_human_route_observations"]
    assert {row["route_path"] for row in observations} == {
        "Warehouse Not International",
        "Vendor Credit Memos",
    }
    assert all(row["support_count"] == 1 for row in observations)


def test_route_balanced_neighborhood_fills_after_route_diversity_in_relevance_order():
    ranked = [
        _row("a-1", "A", 100.0),
        _row("a-2", "A", 99.0),
        _row("a-3", "A", 98.0),
        _row("b-1", "B", 60.0),
    ]

    selected = train_context._route_balanced_neighborhood(ranked, limit=3)

    assert [row["document_id"] for row in selected] == ["a-1", "b-1", "a-2"]


def test_route_balanced_context_still_excludes_holdout(monkeypatch):
    _patch_route_neutral_scoring(monkeypatch)
    rows = [
        _row("train-a", "A", 100.0),
        _row("holdout-b", "B", 200.0, is_holdout=True),
    ]

    result = train_context.build_train_learning_context(
        {},
        rows,
        contract={"dynamic_routes": []},
        neighborhood_limit=2,
    )

    assert result["eligible_train_example_count"] == 1
    assert [row["route_path"] for row in result["nearest_human_route_observations"]] == ["A"]


def test_route_balanced_neighborhood_remains_hard_bounded():
    ranked = [_row(f"r-{i}", f"Route {i}", 100.0 - i) for i in range(10)]

    selected = train_context._route_balanced_neighborhood(ranked, limit=3)

    assert len(selected) == 3
    assert [row["document_id"] for row in selected] == ["r-0", "r-1", "r-2"]
