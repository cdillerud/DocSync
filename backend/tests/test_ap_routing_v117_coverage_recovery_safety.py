import asyncio

import services.ap_routing_coverage_recovery_safety_service as safety


BASE_CONTRACT = {
    "version": "test-v117-coverage-recovery-safety",
    "review_route": "",
    "auto_route_threshold": 0.92,
    "review_threshold": 0.70,
    "few_shot_limit": 8,
    "static_routes": [
        "DO NOT PAY",
        "Dropship Not International/Drop Ship All Others",
        "Vendor Credit Memos",
        "Vendor Credit Memos/Ball Detention Credits",
        "Warehouse Not International/Ball Orders",
    ],
    "dynamic_routes": [],
    "bc_context_required_prefixes": [],
    "manual_only_routes": [],
}


def _document(vendor, file_name, *, document_type="AP_Invoice", raw_text="invoice"):
    return {
        "file_name": file_name,
        "vendor_canonical": vendor,
        "document_type": document_type,
        "raw_text": raw_text,
        "extracted_fields": {"vendor": vendor},
    }


def _example(vendor, route, file_name):
    return {
        "fingerprint": f"{vendor}|{route}|{file_name}",
        "vendor_name": vendor,
        "route_path": route,
        "file_name": file_name,
        "extracted_fields": {"vendor": vendor},
        "bc_context": {"status": "not_found", "verified_order_numbers": []},
    }


def _auto(route, *, recovery=None, guard_action="allow_existing_decision"):
    result = {
        "decision": "auto_route",
        "route_path": route,
        "confidence": 0.98,
        "blockers": [],
        "warnings": [],
        "authority_guard": {"action": guard_action, "blockers": []},
    }
    if recovery:
        result["coverage_recovery"] = recovery
    return result


def _run(monkeypatch, *, base_result, document, examples=None):
    async def fake_base(*args, **kwargs):
        return dict(base_result)

    monkeypatch.setattr(safety, "_base_recovery_decide", fake_base)
    return asyncio.run(
        safety.decide_ap_route_with_authority_guard(
            None,
            document=document,
            bc_context={},
            contract=dict(BASE_CONTRACT),
            examples=list(examples or []),
            support_examples=list(examples or []),
        )
    )


def test_extended_numeric_exact_reference_recovery_is_demoted(monkeypatch):
    result = _run(
        monkeypatch,
        base_result=_auto(
            "DO NOT PAY",
            recovery={
                "action": "promote_extended_exact_reference_consensus",
                "granted_route": "DO NOT PAY",
                "exact_reference_consensus": {
                    "reference": "184180",
                    "route": "DO NOT PAY",
                    "label_count": 2,
                },
            },
        ),
        document=_document(
            "PREFORM Solutions, inc.",
            "114716_PreformSolutions_96702_52226.pdf",
        ),
    )
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert result["coverage_recovery_safety"]["action"] == "force_review_extended_numeric_reference_recovery"


def test_reference_family_recovery_is_not_disturbed(monkeypatch):
    route = "Warehouse Not International/Ball Orders"
    result = _run(
        monkeypatch,
        base_result=_auto(
            route,
            recovery={
                "action": "promote_reference_family_accounting_consensus",
                "granted_route": route,
            },
        ),
        document=_document(
            "BALL METAL BEVERAGE CONTAINER CORP",
            "W118073_BallMetalBeverageContainer_6396992.pdf",
        ),
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == route
    assert result["coverage_recovery_safety"]["action"] == "allow_existing_decision"


def test_semantic_child_recovery_is_demoted_until_second_discriminator_exists(monkeypatch):
    vendor = "BALL METAL BEVERAGE CONTAINER CORP"
    route = "Vendor Credit Memos/Ball Detention Credits"
    result = _run(
        monkeypatch,
        base_result=_auto(
            route,
            recovery={
                "action": "promote_semantic_child_accounting_consensus",
                "granted_route": route,
                "semantic_child_consensus": {
                    "route": route,
                    "label_count": 3,
                    "semantic_pattern": r"\bdetention\b",
                },
            },
        ),
        document=_document(
            vendor,
            "_BallMetalBeverageContainer_6363143_08082026.pdf",
            document_type="Credit_Memo",
            raw_text="detention credit memo",
        ),
    )
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert result["coverage_recovery_safety"]["action"] == "force_review_semantic_child_recovery_insufficient_authority"


def test_existing_auto_detention_child_not_created_by_recovery_is_preserved(monkeypatch):
    route = "Vendor Credit Memos/Ball Detention Credits"
    result = _run(
        monkeypatch,
        base_result=_auto(route),
        document=_document(
            "BALL METAL BEVERAGE CONTAINER CORP",
            "Ball detention already-authoritative.pdf",
            document_type="Credit_Memo",
            raw_text="detention credit memo",
        ),
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == route
    assert result["coverage_recovery_safety"]["action"] == "allow_existing_decision"


def test_generic_credit_memo_dnp_with_credit_workflow_history_is_demoted(monkeypatch):
    vendor = "BALL METAL BEVERAGE CONTAINER CORP"
    examples = [
        _example(vendor, "DO NOT PAY", "Ball prior DNP.pdf"),
        _example(vendor, "Vendor Credit Memos", "Ball ordinary credit prior.pdf"),
        _example(vendor, "Vendor Credit Memos/Ball Detention Credits", "Ball detention prior.pdf"),
    ]
    result = _run(
        monkeypatch,
        base_result=_auto("DO NOT PAY"),
        document=_document(
            vendor,
            "_BallMetalBeverageContainer_6393080 CREDIT_08292026 - Possible Duplicate.pdf",
            document_type="Credit_Memo",
            raw_text="ordinary vendor credit memo possible duplicate",
        ),
        examples=examples,
    )
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert result["coverage_recovery_safety"]["action"] == "force_review_generic_credit_memo_dnp_conflict"


def test_explicit_stop_pay_credit_memo_dnp_is_preserved(monkeypatch):
    vendor = "Example Vendor"
    examples = [
        _example(vendor, "Vendor Credit Memos", "prior credit.pdf"),
    ]
    result = _run(
        monkeypatch,
        base_result=_auto("DO NOT PAY"),
        document=_document(
            vendor,
            "credit memo DO NOT PAY.pdf",
            document_type="Credit_Memo",
            raw_text="DO NOT PAY this credit memo because it was replaced",
        ),
        examples=examples,
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == "DO NOT PAY"


def test_credit_memo_dnp_without_competing_credit_workflow_history_is_preserved(monkeypatch):
    vendor = "Graphic Packaging INTERNATIONAL, INC."
    examples = [_example(vendor, "DO NOT PAY", "prior graphic credit.pdf")]
    result = _run(
        monkeypatch,
        base_result=_auto("DO NOT PAY"),
        document=_document(
            vendor,
            "10252 Graphic 180517 294048.pdf",
            document_type="Credit_Memo",
            raw_text="vendor credit memo",
        ),
        examples=examples,
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == "DO NOT PAY"


def test_explicit_stop_pay_cannot_be_overridden_by_stable_vendor_consensus(monkeypatch):
    result = _run(
        monkeypatch,
        base_result=_auto(
            "Dropship Not International/Drop Ship All Others",
            guard_action="override_stable_vendor_semantic_consensus",
        ),
        document=_document(
            "O-I Packaging Solutions LLC",
            "36539 O-I Pkg Solutions 200611 9310086178 Do not pay, replaced by 9310086251.pdf",
            raw_text="DO NOT PAY. Replaced by invoice 9310086251.",
        ),
    )
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert result["coverage_recovery_safety"]["action"] == "force_review_explicit_stop_pay_route_conflict"


def test_stable_vendor_consensus_non_ap_operational_document_is_demoted(monkeypatch):
    result = _run(
        monkeypatch,
        base_result=_auto(
            "Dropship Not International/Drop Ship All Others",
            guard_action="override_stable_vendor_semantic_consensus",
        ),
        document=_document(
            "O-I Packaging Solutions LLC",
            "W119028_ROTONDO_082726_BOL.pdf",
            document_type="Shipping_Document",
            raw_text="bill of lading warehouse shipment",
        ),
    )
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert result["coverage_recovery_safety"]["action"] == "force_review_stable_vendor_override_non_ap_document"


def test_stable_vendor_consensus_normal_ap_invoice_without_stop_pay_is_preserved(monkeypatch):
    route = "Dropship Not International/Drop Ship All Others"
    result = _run(
        monkeypatch,
        base_result=_auto(route, guard_action="override_stable_vendor_semantic_consensus"),
        document=_document(
            "O-I Packaging Solutions LLC",
            "118275_OIPkgSol_51579677_09022026.pdf",
            document_type="AP_Invoice",
            raw_text="ordinary payable invoice",
        ),
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == route
    assert result["coverage_recovery_safety"]["action"] == "allow_existing_decision"
