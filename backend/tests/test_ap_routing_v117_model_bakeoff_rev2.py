from services.ap_routing_model_bakeoff_rev2_service import (
    _budget_exceeded,
    _response_success_rate,
    _validation_summary,
    reliability_aware_sort_key,
)


def _result(name, *, target=24, errors=0, correct=18, family=20, over=0, latency=1.0):
    rows = []
    for index in range(target):
        is_error = index < errors
        rows.append(
            {
                "proposal_correct": (not is_error and index < correct),
                "family_correct": (not is_error and index < family),
                "model_error": "SyntheticError:x" if is_error else "",
            }
        )
    return {
        "spec": {"name": name, "provider": "test", "model": name},
        "rows": rows,
        "summary": {
            "target_count": target,
            "model_error_count": errors,
            "overconfident_wrong_count": over,
            "contract_invalid_count": 0,
            "mean_latency_seconds": latency,
        },
    }


def test_response_success_rate_uses_all_targets_not_only_proposals():
    assert _response_success_rate(_result("ok", target=24, errors=0)) == 1.0
    assert _response_success_rate(_result("bad", target=24, errors=15)) == 0.375


def test_reliability_sort_blocks_high_accuracy_model_with_many_errors():
    complete = _result("complete", target=24, errors=0, correct=18, family=22)
    sparse = _result("sparse", target=24, errors=15, correct=9, family=9)
    assert reliability_aware_sort_key(complete) < reliability_aware_sort_key(sparse)


def test_reliability_sort_uses_target_accuracy_after_completion_tie():
    better = _result("better", target=24, errors=0, correct=19, family=21)
    worse = _result("worse", target=24, errors=0, correct=17, family=23)
    assert reliability_aware_sort_key(better) < reliability_aware_sort_key(worse)


def test_budget_exceeded_detects_emergent_global_budget_message():
    rows = [
        {"model_error": ""},
        {
            "model_error": (
                "ChatError:Failed to generate chat completion: litellm.RateLimitError: "
                "Budget has been exceeded! Current cost: 2043.1, Max budget: 2042.8"
            )
        },
    ]
    assert _budget_exceeded(rows) is True


def test_validation_summary_tracks_expected_vs_attempted_response_sufficiency():
    rows = [
        {"proposed_route": "A", "proposal_correct": True, "family_correct": True, "model_error": "", "safe_auto": False},
        {"proposed_route": "", "proposal_correct": False, "family_correct": False, "model_error": "ChatError:x", "safe_auto": False},
    ]
    result = _validation_summary(
        spec={"name": "x", "provider": "test", "model": "x"},
        rows=rows,
        expected_target_count=10,
        aborted_reason="provider_budget_exceeded",
    )
    summary = result["summary"]
    assert summary["attempted_target_count"] == 2
    assert summary["expected_target_count"] == 10
    assert summary["successful_response_count"] == 1
    assert summary["response_sufficiency"] == 0.1
    assert summary["validation_aborted_reason"] == "provider_budget_exceeded"
