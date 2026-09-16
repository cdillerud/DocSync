import asyncio

from services.ap_routing_model_bakeoff_service import (
    build_frozen_prompt,
    model_selection_sort_key,
    parse_model_specs,
    route_balanced_sample,
    summarize_model_rows,
)


def _row(item_id, route, *, vendor="Acme", file_name=None):
    return {
        "source_item_id": item_id,
        "fingerprint": item_id,
        "route_path": route,
        "vendor_name": vendor,
        "document_type": "AP_Invoice",
        "file_name": file_name or f"{item_id}.pdf",
        "raw_text_excerpt": "standard invoice",
        "extracted_fields": {"vendor": vendor, "document_type": "AP_Invoice"},
        "bc_context": {},
        "label_source": "accounting_temp",
        "active": True,
        "split": "train",
    }


def _contract():
    return {
        "version": "bakeoff-test",
        "static_routes": ["Route A", "Route B", "Route C", "DO NOT PAY"],
        "dynamic_routes": [],
        "manual_only_routes": [],
        "review_route": "",
    }


def test_default_model_specs_include_current_baseline_and_cross_provider_candidates():
    specs = parse_model_specs("")
    pairs = {(row["provider"], row["model"]) for row in specs}
    assert ("gemini", "gemini-2.5-pro") in pairs
    assert any(provider == "openai" for provider, _ in pairs)
    assert any(provider == "anthropic" for provider, _ in pairs)


def test_model_specs_can_be_overridden_without_duplicates():
    specs = parse_model_specs(
        '[{"provider":"openai","model":"x"},{"provider":"openai","model":"x"},'
        '{"provider":"gemini","model":"y","name":"Y"}]'
    )
    assert specs == [
        {"provider": "openai", "model": "x", "name": "x"},
        {"provider": "gemini", "model": "y", "name": "Y"},
    ]


def test_route_balanced_sample_spreads_sparse_routes_before_repeating_dense_route():
    rows = [
        *[_row(f"a{i}", "Route A") for i in range(8)],
        _row("b1", "Route B"),
        _row("c1", "Route C"),
    ]
    selected = route_balanced_sample(rows, limit=5)
    routes = [row["route_path"] for row in selected]
    assert set(routes[:3]) == {"Route A", "Route B", "Route C"}
    assert routes.count("Route A") == 3


def test_route_balanced_sample_excludes_requested_ids():
    rows = [_row("a1", "Route A"), _row("b1", "Route B")]
    selected = route_balanced_sample(rows, limit=5, excluded_ids={"a1"})
    assert [row["source_item_id"] for row in selected] == ["b1"]


def test_frozen_prompt_removes_target_from_its_own_evidence_pool():
    target = _row("target", "Route A")
    others = [_row("a2", "Route A"), _row("b1", "Route B")]
    frozen = build_frozen_prompt(target=target, train_pool=[target] + others, contract=_contract())
    assert all(row["source_item_id"] != "target" for row in frozen["train_pool"])
    assert "target" not in frozen["few_shot_ids"]
    assert frozen["learning_context_example_count"] == 2
    assert len(frozen["prompt_sha256"]) == 64


def test_frozen_prompt_does_not_expose_target_route_label_in_document_payload():
    target = _row("target", "Route C", vendor="Unique Vendor")
    frozen = build_frozen_prompt(
        target=target,
        train_pool=[target, _row("a1", "Route A"), _row("b1", "Route B")],
        contract=_contract(),
    )
    assert "route_path" not in frozen["document"]
    # Route C may appear in the contract, but the target route must not be present
    # as a labeled target/example because target is excluded from its own pool.
    assert "target" not in frozen["few_shot_ids"]


def test_prompt_hash_is_deterministic_for_same_target_and_pool():
    target = _row("target", "Route A")
    pool = [target, _row("a2", "Route A"), _row("b1", "Route B")]
    one = build_frozen_prompt(target=target, train_pool=pool, contract=_contract())
    two = build_frozen_prompt(target=target, train_pool=pool, contract=_contract())
    assert one["prompt_sha256"] == two["prompt_sha256"]
    assert one["prompt"] == two["prompt"]


def test_summary_tracks_proposal_and_safe_authority_separately():
    rows = [
        {
            "proposed_route": "Route A",
            "proposal_correct": True,
            "family_correct": True,
            "contract_route_allowed": True,
            "overconfident_wrong": False,
            "dnp_false_positive": False,
            "dynamic_child_unseen_in_train": False,
            "unresolved": [],
            "model_error": "",
            "safe_auto": True,
            "safe_auto_correct": True,
            "safe_wrong_auto": False,
            "latency_seconds": 1.0,
        },
        {
            "proposed_route": "Route B",
            "proposal_correct": False,
            "family_correct": False,
            "contract_route_allowed": True,
            "overconfident_wrong": True,
            "dnp_false_positive": False,
            "dynamic_child_unseen_in_train": False,
            "unresolved": ["ambiguous"],
            "model_error": "",
            "safe_auto": False,
            "safe_auto_correct": False,
            "safe_wrong_auto": False,
            "latency_seconds": 3.0,
        },
    ]
    summary = summarize_model_rows(rows)
    assert summary["proposal_accuracy"] == 0.5
    assert summary["overconfident_wrong_count"] == 1
    assert summary["safe_coverage"] == 0.5
    assert summary["safe_auto_accuracy"] == 1.0
    assert summary["safe_wrong_auto_count"] == 0


def test_model_selection_prefers_accuracy_before_latency():
    better = {
        "spec": {"name": "better"},
        "summary": {
            "proposal_accuracy": 0.8,
            "family_accuracy": 0.9,
            "overconfident_wrong_count": 2,
            "contract_invalid_count": 0,
            "model_error_count": 0,
            "mean_latency_seconds": 20,
        },
    }
    faster_but_worse = {
        "spec": {"name": "fast"},
        "summary": {
            "proposal_accuracy": 0.7,
            "family_accuracy": 0.9,
            "overconfident_wrong_count": 0,
            "contract_invalid_count": 0,
            "model_error_count": 0,
            "mean_latency_seconds": 1,
        },
    }
    assert model_selection_sort_key(better) < model_selection_sort_key(faster_but_worse)


def test_model_selection_penalizes_overconfident_wrong_when_accuracy_ties():
    clean = {
        "spec": {"name": "clean"},
        "summary": {
            "proposal_accuracy": 0.8,
            "family_accuracy": 0.9,
            "overconfident_wrong_count": 0,
            "contract_invalid_count": 0,
            "model_error_count": 0,
            "mean_latency_seconds": 5,
        },
    }
    risky = {
        "spec": {"name": "risky"},
        "summary": {
            "proposal_accuracy": 0.8,
            "family_accuracy": 0.9,
            "overconfident_wrong_count": 3,
            "contract_invalid_count": 0,
            "model_error_count": 0,
            "mean_latency_seconds": 1,
        },
    }
    assert model_selection_sort_key(clean) < model_selection_sort_key(risky)
