import asyncio

import services.ap_routing_coverage_recovery_service as recovery


BASE_CONTRACT = {
    "version": "test-v117-coverage-recovery",
    "review_route": "",
    "auto_route_threshold": 0.92,
    "review_threshold": 0.70,
    "few_shot_limit": 8,
    "static_routes": [
        "DO NOT PAY",
        "Dropship International",
        "Dropship Not International/Ball",
        "Dropship Not International/Freight",
        "Meg to Process",
        "Vendor Credit Memos",
        "Vendor Credit Memos/Ball Detention Credits",
        "Warehouse International",
        "Warehouse Not International/Ball Orders",
    ],
    "dynamic_routes": [],
    "bc_context_required_prefixes": [],
    "manual_only_routes": [],
}


def _document(vendor, file_name, raw_text="invoice"):
    return {
        "file_name": file_name,
        "vendor_canonical": vendor,
        "document_type": "AP_Invoice",
        "raw_text": raw_text,
        "extracted_fields": {"vendor": vendor},
    }


def _example(vendor, route, file_name, *, po="", source_route_path=""):
    context = {
        "status": "resolved" if po else "not_found",
        "po_number": po,
        "verified_order_numbers": [po] if po else [],
    }
    return {
        "fingerprint": f"{vendor}|{route}|{file_name}",
        "vendor_name": vendor,
        "route_path": route,
        "file_name": file_name,
        "source_route_path": source_route_path,
        "extracted_fields": {"vendor": vendor},
        "bc_context": context,
    }


def _review_result(
    *,
    raw_model_route,
    raw_model_confidence=0.98,
    full_support_top_route="",
    full_support_margin=0.0,
    blockers=None,
    runtime_veto=False,
):
    result = {
        "decision": "needs_review",
        "route_path": "",
        "confidence": raw_model_confidence,
        "blockers": list(blockers or []),
        "warnings": [],
        "authority_guard": {
            "action": "force_review" if blockers else "allow_existing_decision",
            "blockers": list(blockers or []),
            "raw_model_route": raw_model_route,
            "raw_model_confidence": raw_model_confidence,
            "full_support_top_route": full_support_top_route,
            "full_support_margin": full_support_margin,
        },
    }
    if runtime_veto:
        result["runtime_authority_overlay"] = {
            "action": "force_review",
            "blockers": ["runtime safety veto"],
        }
    return result


def _run(monkeypatch, *, base_result, document, examples=None, context=None):
    async def fake_base(*args, **kwargs):
        return dict(base_result)

    monkeypatch.setattr(recovery, "_base_coverage_decide", fake_base)
    return asyncio.run(
        recovery.decide_ap_route_with_authority_guard(
            None,
            document=document,
            bc_context=context or {},
            contract=dict(BASE_CONTRACT),
            examples=list(examples or []),
            support_examples=list(examples or []),
        )
    )


def test_repeated_warehouse_reference_family_recovers_ball_warehouse_route(monkeypatch):
    vendor = "BALL METAL BEVERAGE CONTAINER CORP"
    route = "Warehouse Not International/Ball Orders"
    examples = [
        _example(vendor, route, "W118010_Ball_prior.pdf"),
        _example(vendor, route, "W118020_Ball_prior.pdf"),
        _example(vendor, "Dropship Not International/Ball", "116278_Ball_prior.pdf"),
    ]
    result = _run(
        monkeypatch,
        base_result=_review_result(
            raw_model_route=route,
            full_support_top_route=route,
            full_support_margin=4.0,
            blockers=[
                "candidate route family warehouse conflicts with current reference family standard_order",
                "multi-route vendor lacks discriminating current-document or authoritative BC context evidence",
            ],
        ),
        document=_document(vendor, "W118073_BallMetalBeverageContainer_6396992.pdf"),
        examples=examples,
        context={"po_number": "116278", "verified_order_numbers": ["116278"]},
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == route
    assert result["coverage_recovery"]["action"] == "promote_reference_family_accounting_consensus"
    assert result["coverage_recovery"]["reference_family_consensus"]["reference_family"] == "warehouse"


def test_repeated_standard_order_family_recovers_hwa_dropship_route(monkeypatch):
    vendor = "HWA HSIA GLASS CO., LTD"
    route = "Dropship International"
    examples = [
        _example(vendor, route, "114000 HWA prior.pdf"),
        _example(vendor, route, "115000 HWA prior.pdf"),
        _example(vendor, "Warehouse International", "W118689 HWA warehouse.pdf"),
    ]
    result = _run(
        monkeypatch,
        base_result=_review_result(
            raw_model_route=route,
            full_support_top_route=route,
            full_support_margin=4.0,
            blockers=["multi-route vendor lacks discriminating current-document or authoritative BC context evidence"],
        ),
        document=_document(vendor, "115356 HWA HSIA 260825.pdf"),
        examples=examples,
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == route
    assert result["coverage_recovery"]["reference_family_consensus"]["reference_family"] == "standard_order"


def test_conflicting_reference_family_routes_do_not_recover(monkeypatch):
    vendor = "Variable Vendor"
    examples = [
        _example(vendor, "Warehouse International", "W118100 prior.pdf"),
        _example(vendor, "Warehouse Not International/Ball Orders", "W118101 prior.pdf"),
    ]
    result = _run(
        monkeypatch,
        base_result=_review_result(
            raw_model_route="Warehouse International",
            full_support_top_route="Warehouse International",
            full_support_margin=4.0,
            blockers=["multi-route vendor lacks discriminating current-document or authoritative BC context evidence"],
        ),
        document=_document(vendor, "W118102 current.pdf"),
        examples=examples,
    )
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert result["coverage_recovery"]["action"] == "retain_review"


def test_standard_numeric_exact_bc_reference_consensus_recovers_review(monkeypatch):
    vendor = "Valley Distibuting and Storage Company"
    examples = [
        _example(vendor, "DO NOT PAY", "Valley prior credit 1.pdf", po="55401"),
        _example(vendor, "DO NOT PAY", "Valley prior credit 2.pdf", po="55401"),
        _example(vendor, "Meg to Process", "Valley other workflow.pdf", po="55402"),
    ]
    result = _run(
        monkeypatch,
        base_result=_review_result(
            raw_model_route="Meg to Process",
            blockers=[],
        ),
        document=_document(vendor, "Valley 221127 7057 - received credit.pdf"),
        examples=examples,
        context={"po_number": "55401", "verified_order_numbers": ["55401"]},
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == "DO NOT PAY"
    assert result["coverage_recovery"]["action"] == "promote_extended_exact_reference_consensus"
    assert result["coverage_recovery"]["exact_reference_consensus"]["reference"] == "55401"


def test_detention_semantic_child_with_repeated_route_labels_recovers(monkeypatch):
    vendor = "BALL METAL BEVERAGE CONTAINER CORP"
    route = "Vendor Credit Memos/Ball Detention Credits"
    examples = [
        _example(vendor, route, "Ball prior detention 1.pdf"),
        _example(vendor, route, "Ball prior detention 2.pdf"),
        _example(vendor, "Vendor Credit Memos", "Ball ordinary credit.pdf"),
    ]
    result = _run(
        monkeypatch,
        base_result=_review_result(
            raw_model_route=route,
            raw_model_confidence=0.99,
            blockers=["multi-route vendor lacks discriminating current-document or authoritative BC context evidence"],
        ),
        document=_document(
            vendor,
            "BallMetalBeverageContainer_5701110_04_10_2025.pdf",
            "credit memo for detention charges and detention fees",
        ),
        examples=examples,
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == route
    assert result["coverage_recovery"]["action"] == "promote_semantic_child_accounting_consensus"
    assert result["coverage_recovery"]["semantic_child_consensus"]["label_count"] == 2


def test_generic_credit_memo_does_not_recover_to_detention_child(monkeypatch):
    vendor = "BALL METAL BEVERAGE CONTAINER CORP"
    route = "Vendor Credit Memos/Ball Detention Credits"
    examples = [
        _example(vendor, route, "Ball prior detention 1.pdf"),
        _example(vendor, route, "Ball prior detention 2.pdf"),
    ]
    result = _run(
        monkeypatch,
        base_result=_review_result(
            raw_model_route=route,
            raw_model_confidence=0.99,
            blockers=["multi-route vendor lacks discriminating current-document or authoritative BC context evidence"],
        ),
        document=_document(vendor, "Ball ordinary credit memo.pdf", "ordinary vendor credit memo"),
        examples=examples,
    )
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""


def test_cross_vendor_exact_reference_veto_remains_final(monkeypatch):
    vendor = "CRALER"
    route = "Dropship Not International/Freight"
    examples = [
        _example(vendor, route, "114480 Craler prior 1.pdf"),
        _example(vendor, route, "114480 Craler prior 2.pdf"),
    ]
    result = _run(
        monkeypatch,
        base_result=_review_result(
            raw_model_route=route,
            full_support_top_route=route,
            full_support_margin=5.0,
            blockers=["candidate route relies on an exact current reference seen only under a different vendor"],
        ),
        document=_document(vendor, "114480 Craler current.pdf"),
        examples=examples,
    )
    assert result["decision"] == "needs_review"
    assert result.get("coverage_recovery") is None


def test_runtime_authority_veto_remains_final(monkeypatch):
    vendor = "Known Vendor"
    route = "Dropship International"
    examples = [
        _example(vendor, route, "114000 prior.pdf"),
        _example(vendor, route, "115000 prior.pdf"),
    ]
    result = _run(
        monkeypatch,
        base_result=_review_result(
            raw_model_route=route,
            full_support_top_route=route,
            full_support_margin=5.0,
            blockers=["multi-route vendor lacks discriminating current-document or authoritative BC context evidence"],
            runtime_veto=True,
        ),
        document=_document(vendor, "116000 current.pdf"),
        examples=examples,
    )
    assert result["decision"] == "needs_review"
    assert result.get("coverage_recovery") is None
