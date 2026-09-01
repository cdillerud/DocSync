import asyncio

import services.ap_routing_coverage_authority_service as coverage


BASE_CONTRACT = {
    "version": "test-v117-coverage-authority",
    "review_route": "",
    "auto_route_threshold": 0.92,
    "review_threshold": 0.70,
    "few_shot_limit": 8,
    "static_routes": [
        "DO NOT PAY",
        "Dropship International",
        "Dropship Not International",
        "Dropship Not International/Canpack",
        "Dropship Not International/Drop Ship All Others",
        "Dropship Not International/Freight",
        "Meg to Process",
        "Rhonda - Issues",
        "Vendor Credit Memos",
        "Warehouse International",
        "Warehouse Not International",
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


def _example(vendor, route, file_name, *, source_route_path="", po=""):
    return {
        "fingerprint": f"{vendor}|{route}|{file_name}",
        "vendor_name": vendor,
        "route_path": route,
        "source_route_path": source_route_path,
        "file_name": file_name,
        "extracted_fields": {"vendor": vendor},
        "bc_context": {
            "status": "resolved" if po else "not_found",
            "po_number": po,
            "verified_order_numbers": [po] if po else [],
        },
    }


def _review_result(*, runtime_veto=False, authority_veto=False):
    result = {
        "decision": "needs_review",
        "route_path": "",
        "confidence": 0.95,
        "blockers": [],
        "warnings": [],
        "authority_guard": {
            "action": "force_review" if authority_veto else "allow_existing_decision",
            "blockers": ["base safety veto"] if authority_veto else [],
        },
    }
    if runtime_veto:
        result["runtime_authority_overlay"] = {
            "action": "force_review",
            "blockers": ["runtime safety veto"],
        }
    return result


def _auto_result(route):
    return {
        "decision": "auto_route",
        "route_path": route,
        "confidence": 0.99,
        "blockers": [],
        "warnings": [],
        "authority_guard": {"action": "allow_existing_decision", "blockers": []},
    }


def _run(monkeypatch, *, base_result, document, examples=None, context=None):
    async def fake_runtime(*args, **kwargs):
        return dict(base_result)

    monkeypatch.setattr(
        coverage,
        "_runtime_decide_ap_route_with_authority_guard",
        fake_runtime,
    )
    return asyncio.run(
        coverage.decide_ap_route_with_authority_guard(
            None,
            document=document,
            bc_context=context or {},
            contract=dict(BASE_CONTRACT),
            examples=list(examples or []),
            support_examples=list(examples or []),
        )
    )


def test_explicit_do_not_pay_recovers_review(monkeypatch):
    result = _run(
        monkeypatch,
        base_result=_review_result(),
        document=_document(
            "R+L Carriers, Inc.",
            "109577_RLCarriers_NO.1949252536_DO NOT_PAY.pdf",
            "DO NOT PAY - invoice was reissued",
        ),
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == "DO NOT PAY"
    assert result["coverage_authority"]["action"] == "promote_explicit_do_not_pay"


def test_generic_hold_language_does_not_recover_review(monkeypatch):
    result = _run(
        monkeypatch,
        base_result=_review_result(),
        document=_document(
            "Pacific Southwest Container, LLC",
            "108784_PSC_HOLD-Checking About This Order.pdf",
            "HOLD while checking about this order",
        ),
    )
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert result["coverage_authority"]["action"] == "retain_review"


def test_repeated_exact_reference_accounting_consensus_recovers_review(monkeypatch):
    vendor = "Cargo Modules LLC"
    examples = [
        _example(
            vendor,
            "Meg to Process",
            "W115989 Cargo prior 1.pdf",
            source_route_path="Meg to Process/Xolution/XO Quality Claim and Replacement Entries/W115989",
        ),
        _example(
            vendor,
            "Meg to Process",
            "W115989 Cargo prior 2.pdf",
            source_route_path="Meg to Process/Xolution/XO Quality Claim and Replacement Entries/W115989",
        ),
    ]
    result = _run(
        monkeypatch,
        base_result=_review_result(),
        document=_document(vendor, "W115989 Cargo 250519 125134305-AR.pdf"),
        examples=examples,
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == "Meg to Process"
    consensus = result["coverage_authority"]["exact_reference_consensus"]
    assert consensus["reference"] == "W115989"
    assert consensus["label_count"] == 2


def test_single_exact_reference_label_is_not_enough(monkeypatch):
    vendor = "Cargo Modules LLC"
    result = _run(
        monkeypatch,
        base_result=_review_result(),
        document=_document(vendor, "W115989 Cargo current.pdf"),
        examples=[
            _example(
                vendor,
                "Meg to Process",
                "W115989 Cargo prior.pdf",
                source_route_path="Meg to Process/W115989",
            )
        ],
    )
    assert result["decision"] == "needs_review"
    assert result["coverage_authority"]["action"] == "retain_review"


def test_conflicting_exact_reference_routes_do_not_recover(monkeypatch):
    vendor = "Example Vendor"
    examples = [
        _example(vendor, "Meg to Process", "W116090 prior 1.pdf", source_route_path="Meg to Process/W116090"),
        _example(vendor, "Meg to Process", "W116090 prior 2.pdf", source_route_path="Meg to Process/W116090"),
        _example(vendor, "Warehouse International", "W116090 prior 3.pdf", source_route_path="Warehouse International/W116090"),
    ]
    result = _run(
        monkeypatch,
        base_result=_review_result(),
        document=_document(vendor, "W116090 current.pdf"),
        examples=examples,
    )
    assert result["decision"] == "needs_review"
    assert result["coverage_authority"]["action"] == "retain_review"


def test_runtime_safety_veto_is_final(monkeypatch):
    result = _run(
        monkeypatch,
        base_result=_review_result(runtime_veto=True),
        document=_document(
            "R+L Carriers, Inc.",
            "109577_RLCarriers_DO_NOT_PAY.pdf",
            "DO NOT PAY",
        ),
    )
    assert result["decision"] == "needs_review"
    assert result.get("coverage_authority") is None


def test_base_authority_safety_veto_is_final(monkeypatch):
    result = _run(
        monkeypatch,
        base_result=_review_result(authority_veto=True),
        document=_document(
            "R+L Carriers, Inc.",
            "109577_RLCarriers_DO_NOT_PAY.pdf",
            "DO NOT PAY",
        ),
    )
    assert result["decision"] == "needs_review"
    assert result.get("coverage_authority") is None


def test_existing_auto_route_passes_through_unchanged(monkeypatch):
    result = _run(
        monkeypatch,
        base_result=_auto_result("Dropship International"),
        document=_document("Known Vendor", "113787 invoice.pdf"),
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == "Dropship International"
    assert result.get("coverage_authority") is None
