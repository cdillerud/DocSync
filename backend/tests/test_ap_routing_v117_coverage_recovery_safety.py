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


def _auto(route, *, recovery=None):
    result = {
        "decision": "auto_route",
        "route_path": route,
        "confidence": 0.98,
        "blockers": [],
        "warnings": [],
        "authority_guard": {"action": "allow_existing_decision", "blockers": []},
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
