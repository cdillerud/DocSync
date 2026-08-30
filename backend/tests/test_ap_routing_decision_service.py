import json
from pathlib import Path

from services.ap_routing_decision_service import (
    DECISION_AUTO_ROUTE,
    DECISION_NEEDS_REVIEW,
    RoutePrediction,
    govern_route_prediction,
    parse_route_prediction,
    route_is_allowed,
)


CONTRACT_PATH = Path(__file__).resolve().parents[1] / "config" / "ap_routing_contract.v1.json"


def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def prediction(route, confidence=0.98, unresolved=None):
    return RoutePrediction(
        proposed_route=route,
        confidence=confidence,
        evidence=["invoice/payment semantics", "verified PO/order context"],
        reasoning_summary="route follows the labeled Accounting pattern and BC context",
        bc_refs_used=["113785"],
        unresolved=unresolved or [],
        matched_example_ids=["golden-1"],
        model="test-model",
    )


def test_top_level_freight_issues_is_forbidden_because_not_live_contract_path():
    c = contract()
    assert not route_is_allowed("Freight Issues", c, {"status": "resolved", "po_number": "113785"})
    decision = govern_route_prediction(
        prediction("Freight Issues"),
        contract=c,
        bc_context={"status": "resolved", "po_number": "113785"},
    )
    assert decision.decision == DECISION_NEEDS_REVIEW
    assert decision.route_path == ""
    assert any("not allowed" in b for b in decision.blockers)


def test_live_dropship_freight_route_is_allowed_with_bc_context():
    c = contract()
    decision = govern_route_prediction(
        prediction("Dropship Not International/Freight"),
        contract=c,
        bc_context={"status": "resolved", "po_number": "110784A", "bc_record_id": "po-id"},
    )
    assert decision.decision == DECISION_AUTO_ROUTE
    assert decision.route_path == "Dropship Not International/Freight"


def test_live_warehouse_route_is_allowed_with_bc_context():
    c = contract()
    decision = govern_route_prediction(
        prediction("Warehouse Not International"),
        contract=c,
        bc_context={"status": "resolved", "po_number": "113785", "bc_record_id": "po-id"},
    )
    assert decision.decision == DECISION_AUTO_ROUTE
    assert decision.route_path == "Warehouse Not International"


def test_same_vendor_can_legitimately_have_two_routes():
    c = contract()
    warehouse = govern_route_prediction(
        prediction("Warehouse Not International"),
        contract=c,
        bc_context={"status": "resolved", "po_number": "113785"},
    )
    dropship = govern_route_prediction(
        prediction("Dropship Not International/Freight"),
        contract=c,
        bc_context={"status": "resolved", "po_number": "110784A"},
    )
    assert warehouse.decision == DECISION_AUTO_ROUTE
    assert dropship.decision == DECISION_AUTO_ROUTE
    assert warehouse.route_path != dropship.route_path


def test_bc_context_required_routes_fail_closed_without_bc_resolution():
    c = contract()
    decision = govern_route_prediction(
        prediction("Warehouse Not International"),
        contract=c,
        bc_context={},
    )
    assert decision.decision == DECISION_NEEDS_REVIEW
    assert decision.route_path == ""
    assert any("Business Central" in b for b in decision.blockers)


def test_low_confidence_goes_to_temp_root_review_not_fabricated_folder():
    c = contract()
    decision = govern_route_prediction(
        prediction("Tooling Invoices", confidence=0.75),
        contract=c,
        bc_context={},
    )
    assert decision.decision == DECISION_NEEDS_REVIEW
    assert decision.route_path == ""
    assert decision.warnings


def test_unresolved_model_evidence_fails_closed_even_when_confident():
    c = contract()
    decision = govern_route_prediction(
        prediction(
            "Dropship Not International/Freight",
            confidence=0.99,
            unresolved=["two different Gamer PO candidates remain unresolved"],
        ),
        contract=c,
        bc_context={"status": "resolved", "po_number": "110784A"},
    )
    assert decision.decision == DECISION_NEEDS_REVIEW
    assert decision.route_path == ""


def test_dynamic_international_route_requires_exact_verified_bc_reference():
    c = contract()
    route = "Dropship International/113785"
    assert route_is_allowed(
        route,
        c,
        {"status": "resolved", "verified_order_numbers": ["113785"]},
    )
    assert not route_is_allowed(
        route,
        c,
        {"status": "resolved", "verified_order_numbers": ["999999"]},
    )


def test_parse_json_fenced_prediction():
    parsed = parse_route_prediction(
        """```json
        {
          "proposed_route": "Warehouse Not International",
          "confidence": 0.97,
          "evidence": ["PO context"],
          "reasoning_summary": "warehouse pattern",
          "bc_refs_used": ["113785"],
          "unresolved": [],
          "matched_example_ids": ["a"]
        }
        ```""",
        model="test",
    )
    assert parsed.proposed_route == "Warehouse Not International"
    assert parsed.confidence == 0.97
