from services.ap_routing_evaluation_service import promotion_gate, summarize_evaluation


def test_promotion_requires_zero_wrong_auto_routes():
    rows = [
        {
            "normalized_vendor": "tumalo creek transportation",
            "expected_route": "Warehouse Not International",
            "predicted_route": "Dropship Not International/Freight",
            "auto_routed": True,
            "auto_route_correct": False,
        },
        {
            "normalized_vendor": "tumalo creek transportation",
            "expected_route": "Dropship Not International/Freight",
            "predicted_route": "Dropship Not International/Freight",
            "auto_routed": True,
            "auto_route_correct": True,
        },
    ]
    evaluation = summarize_evaluation(rows)
    gate = promotion_gate(evaluation, labeled_example_count=50, target_coverage=0.5)
    assert not gate["ready_for_runtime_authority"]
    assert gate["wrong_auto_routes"] == 1


def test_safe_but_manual_model_does_not_meet_labor_reduction_goal():
    rows = [
        {
            "normalized_vendor": "tumalo creek transportation",
            "expected_route": "Warehouse Not International",
            "predicted_route": "",
            "auto_routed": False,
            "auto_route_correct": False,
        }
        for _ in range(20)
    ]
    evaluation = summarize_evaluation(rows)
    gate = promotion_gate(evaluation, labeled_example_count=100)
    assert not gate["ready_for_runtime_authority"]
    assert evaluation["coverage"] == 0.0
    assert any("coverage" in reason for reason in gate["reasons"])


def test_mature_vendor_can_promote_at_full_accuracy_and_high_coverage():
    rows = []
    for i in range(18):
        route = "Warehouse Not International" if i % 2 == 0 else "Dropship Not International/Freight"
        rows.append(
            {
                "normalized_vendor": "tumalo creek transportation",
                "expected_route": route,
                "predicted_route": route,
                "auto_routed": True,
                "auto_route_correct": True,
            }
        )
    for _ in range(2):
        rows.append(
            {
                "normalized_vendor": "tumalo creek transportation",
                "expected_route": "Warehouse Not International",
                "predicted_route": "",
                "auto_routed": False,
                "auto_route_correct": False,
            }
        )
    evaluation = summarize_evaluation(rows)
    gate = promotion_gate(evaluation, labeled_example_count=100)
    assert evaluation["coverage"] == 0.9
    assert evaluation["auto_route_accuracy"] == 1.0
    assert gate["ready_for_runtime_authority"]
