import asyncio

from services import ap_routing_corpus_expansion_service as expansion


def test_expansion_excludes_holdout_identity_without_using_holdout_label_for_targeting(monkeypatch):
    train_examples = [
        {
            "source_item_id": "train-1",
            "vendor_name": "Tumalo Creek Transportation",
            "route_path": "Dropship Not International/Freight",
        },
        {
            "source_item_id": "train-2",
            "vendor_name": "Tumalo Creek Transportation",
            "route_path": "Warehouse International",
        },
    ]
    discovered_labels = [
        {
            "item_id": "holdout-1",
            "file_name": "Tumalo holdout invoice.pdf",
            "route_path": "Rhonda - Issues",
        },
        {
            "item_id": "candidate-1",
            "file_name": "Tumalo new invoice.pdf",
            "route_path": "Dropship Not International/Freight",
        },
    ]
    hydrated_item_ids = []

    async def fake_discover(*, max_files):
        assert max_files == 50000
        return {"files": list(discovered_labels)}

    def fake_canonicalize(files, routing_contract):
        assert files == discovered_labels
        assert routing_contract == {"version": "test"}
        return {"labels": list(files)}

    async def fake_hydrate(label, *, routing_contract):
        assert routing_contract == {"version": "test"}
        hydrated_item_ids.append(label["item_id"])
        return {
            "source_item_id": label["item_id"],
            "vendor_name": "Tumalo Creek Transportation",
            "route_path": label["route_path"],
        }

    monkeypatch.setattr(expansion, "discover_accounting_temp_labels", fake_discover)
    monkeypatch.setattr(expansion, "_canonicalize_discovered_labels", fake_canonicalize)
    monkeypatch.setattr(expansion, "hydrate_accounting_label", fake_hydrate)

    result = asyncio.run(
        expansion.expand_high_value_vendor_corpus(
            train_examples,
            routing_contract={"version": "test"},
            excluded_source_item_ids={"holdout-1"},
            max_vendors=1,
            desired_total_per_vendor=30,
            max_additional=5,
            concurrency=1,
            retry_count=1,
        )
    )

    assert result["excluded_source_item_id_count"] == 1
    assert result["target_vendors"] == [
        {
            "normalized_vendor": "tumalo creek transportation",
            "vendor_name": "Tumalo Creek Transportation",
            "existing_count": 2,
            "route_count": 2,
            "routes": [
                "Dropship Not International/Freight",
                "Warehouse International",
            ],
        }
    ]
    assert result["selected_count"] == 1
    assert result["hydrated_count"] == 1
    assert hydrated_item_ids == ["candidate-1"]
    assert [row["source_item_id"] for row in result["examples"]] == ["candidate-1"]


def test_semantic_workflow_selection_is_route_blind_and_identity_safe():
    labels_a = [
        {
            "item_id": "holdout-receive",
            "file_name": "BOL need to receive.pdf",
            "route_path": "Warehouse Not International",
            "modified_at": "2026-09-11T12:00:00Z",
        },
        {
            "item_id": "receive-1",
            "file_name": "purchase receipt notification 118001.pdf",
            "route_path": "Warehouse Not International",
            "modified_at": "2026-09-11T11:00:00Z",
        },
        {
            "item_id": "detention-1",
            "file_name": "detention invoice 118002.pdf",
            "route_path": "Dropship Not International/Freight",
            "modified_at": "2026-09-11T10:00:00Z",
        },
        {
            "item_id": "ordinary-1",
            "file_name": "ordinary invoice.pdf",
            "route_path": "DO NOT PAY",
            "modified_at": "2026-09-11T09:00:00Z",
        },
    ]
    labels_b = [dict(row) for row in labels_a]
    for row in labels_b:
        row["route_path"] = "completely different label"

    kwargs = {
        "excluded_source_item_ids": {"holdout-receive"},
        "already_selected_source_item_ids": set(),
        "max_additional": 10,
    }
    selected_a, counts_a = expansion._round_robin_semantic_workflows(labels_a, **kwargs)
    selected_b, counts_b = expansion._round_robin_semantic_workflows(labels_b, **kwargs)

    ids_a = [row["item_id"] for _, row in selected_a]
    ids_b = [row["item_id"] for _, row in selected_b]
    assert ids_a == ids_b == ["detention-1", "receive-1"]
    assert counts_a == counts_b == {"detention": 1, "inventory": 1}
    assert "holdout-receive" not in ids_a
    assert "ordinary-1" not in ids_a


def test_semantic_workflow_expansion_hydrates_non_vendor_receiving_evidence(monkeypatch):
    train_examples = [
        {
            "source_item_id": "train-1",
            "vendor_name": "Tumalo Creek Transportation",
            "route_path": "Dropship Not International/Freight",
        },
        {
            "source_item_id": "train-2",
            "vendor_name": "Tumalo Creek Transportation",
            "route_path": "Warehouse International",
        },
    ]
    discovered_labels = [
        {
            "item_id": "semantic-1",
            "file_name": "Receiving receipt notification 119999.pdf",
            "route_path": "Warehouse Not International",
            "modified_at": "2026-09-11T12:00:00Z",
        }
    ]
    hydrated_item_ids = []

    async def fake_discover(*, max_files):
        return {"files": list(discovered_labels)}

    def fake_canonicalize(files, routing_contract):
        return {"labels": list(files)}

    async def fake_hydrate(label, *, routing_contract):
        hydrated_item_ids.append(label["item_id"])
        return {
            "source_item_id": label["item_id"],
            "vendor_name": "Receiving Carrier",
            "route_path": label["route_path"],
        }

    monkeypatch.setattr(expansion, "discover_accounting_temp_labels", fake_discover)
    monkeypatch.setattr(expansion, "_canonicalize_discovered_labels", fake_canonicalize)
    monkeypatch.setattr(expansion, "hydrate_accounting_label", fake_hydrate)

    result = asyncio.run(
        expansion.expand_high_value_vendor_corpus(
            train_examples,
            routing_contract={"version": "test"},
            excluded_source_item_ids={"train-1", "train-2"},
            max_vendors=1,
            desired_total_per_vendor=30,
            max_additional=5,
            concurrency=1,
            retry_count=1,
        )
    )

    assert result["semantic_candidate_counts"] == {"inventory": 1}
    assert result["semantic_selected_count"] == 1
    assert result["selected_count"] == 1
    assert hydrated_item_ids == ["semantic-1"]
    assert result["examples"][0]["source_item_id"] == "semantic-1"
