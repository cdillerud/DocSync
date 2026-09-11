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
