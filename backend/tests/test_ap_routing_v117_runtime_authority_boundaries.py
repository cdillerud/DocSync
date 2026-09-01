import asyncio

import services.ap_routing_runtime_authority_service as runtime_authority
from services.ap_routing_runtime_authority_service import decide_ap_route_with_authority_guard


BASE_CONTRACT = {
    "version": "test-v117-runtime-authority",
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
        "Dropship Not International/Freight/Sales Order not posted",
        "Meg to Process",
        "Rhonda - Issues",
        "Vendor Credit Memos",
        "Vendor Credit Memos/Ball Detention Credits",
        "Warehouse International",
        "Warehouse Not International",
        "Tooling Invoices",
    ],
    "dynamic_routes": [],
    "bc_context_required_prefixes": [
        "Dropship International",
        "Dropship Not International",
        "Warehouse International",
        "Warehouse Not International",
    ],
    "manual_only_routes": [],
}


def _contract(*, dynamic=False):
    contract = dict(BASE_CONTRACT)
    contract["static_routes"] = list(BASE_CONTRACT["static_routes"])
    contract["bc_context_required_prefixes"] = list(BASE_CONTRACT["bc_context_required_prefixes"])
    contract["dynamic_routes"] = []
    if dynamic:
        contract["dynamic_routes"] = [
            {
                "prefix": "Dropship International",
                "requires_verified_bc_reference": True,
                "leaf_pattern": r"\d{5,7}[A-Z]?",
            }
        ]
    return contract


def _example(
    vendor,
    route,
    file_name,
    raw_text,
    *,
    po="",
    document_type="AP_Invoice",
    source_route_path="",
):
    context = {"status": "resolved" if po else "not_found"}
    if po:
        context["po_number"] = po
        context["verified_order_numbers"] = [po]
    row = {
        "fingerprint": f"{vendor}|{route}|{file_name}",
        "vendor_name": vendor,
        "route_path": route,
        "file_name": file_name,
        "raw_text_excerpt": raw_text,
        "document_type": document_type,
        "label_weight": 0.94,
        "extracted_fields": {"vendor": vendor},
        "bc_context": context,
    }
    if source_route_path:
        row["source_route_path"] = source_route_path
    return row


def _document(vendor, file_name, raw_text, *, document_type="AP_Invoice"):
    return {
        "file_name": file_name,
        "vendor_canonical": vendor,
        "document_type": document_type,
        "suggested_job_type": document_type,
        "confidence": 0.99,
        "raw_text": raw_text,
        "extracted_fields": {"vendor": vendor},
    }


def _sender(route, *, confidence=0.99, bc_refs=None):
    async def send(prompt, model):
        return {
            "proposed_route": route,
            "confidence": confidence,
            "evidence": ["synthetic runtime-authority regression"],
            "reasoning_summary": "synthetic runtime-authority decision",
            "bc_refs_used": list(bc_refs or []),
            "unresolved": [],
            "matched_example_ids": [],
        }

    return send


def _run(*, document, context, contract, examples, route, bc_refs=None):
    return asyncio.run(
        decide_ap_route_with_authority_guard(
            None,
            document=document,
            bc_context=context,
            contract=contract,
            examples=examples,
            support_examples=examples,
            llm_send=_sender(route, bc_refs=bc_refs),
        )
    )


def _run_overlay(*, document, context, contract, examples, route, confidence=0.99):
    async def fake_base(*args, **kwargs):
        return {
            "decision": "auto_route",
            "route_path": route,
            "confidence": confidence,
            "blockers": [],
            "warnings": [],
            "authority_guard": {
                "action": "allow_existing_decision",
                "blockers": [],
            },
        }

    original = runtime_authority._base_decide_ap_route_with_authority_guard
    runtime_authority._base_decide_ap_route_with_authority_guard = fake_base
    try:
        return asyncio.run(
            runtime_authority.decide_ap_route_with_runtime_authority(
                None,
                document=document,
                bc_context=context,
                contract=contract,
                examples=examples,
                support_examples=examples,
                llm_send=_sender(route),
            )
        )
    finally:
        runtime_authority._base_decide_ap_route_with_authority_guard = original


def test_sparse_preform_child_route_fails_closed_when_parent_is_also_valid():
    result = _run(
        document=_document(
            "PREFORM Solutions, inc.",
            "115174_PreformSolutions_97028_82926.pdf",
            "invoice for third-party dropship address",
        ),
        context={
            "status": "resolved",
            "po_number": "115174",
            "verified_order_numbers": ["115174"],
        },
        contract=_contract(),
        examples=[],
        route="Dropship Not International/Drop Ship All Others",
        bc_refs=["115174"],
    )
    assert result["pre_runtime_authority_decision"] == "auto_route"
    assert result["pre_runtime_authority_route"] == "Dropship Not International/Drop Ship All Others"
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert result["runtime_authority_overlay"]["static_parent_route"] == "Dropship Not International"
    assert result["runtime_authority_overlay"]["same_vendor_exact_route_label_count"] == 0


def test_same_vendor_child_label_can_preserve_specific_static_route():
    vendor = "Known Dropship Supplier"
    examples = [
        _example(
            vendor,
            "Dropship Not International/Drop Ship All Others",
            "115170_KnownDropship.pdf",
            "ordinary dropship packaging invoice",
            po="115170",
        )
    ]
    result = _run(
        document=_document(vendor, "115171_KnownDropship.pdf", "ordinary dropship packaging invoice"),
        context={
            "status": "resolved",
            "po_number": "115171",
            "verified_order_numbers": ["115171"],
        },
        contract=_contract(),
        examples=examples,
        route="Dropship Not International/Drop Ship All Others",
        bc_refs=["115171"],
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == "Dropship Not International/Drop Ship All Others"


def test_craler_contract_valid_dynamic_child_without_accounting_authority_fails_closed():
    result = _run(
        document=_document(
            "Craler",
            "114480_CRALER_259746085_20260827.pdf",
            "international freight invoice for dropship purchase order",
        ),
        context={
            "status": "resolved",
            "po_number": "114480",
            "verified_order_numbers": ["114480"],
            "location_code": "",
        },
        contract=_contract(dynamic=True),
        examples=[],
        route="Dropship International/114480",
        bc_refs=["114480"],
    )
    assert result["pre_runtime_authority_decision"] == "auto_route"
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert result["runtime_authority_overlay"]["dynamic_route_prefix"] == "Dropship International"
    assert result["runtime_authority_overlay"]["same_vendor_exact_route_label_count"] == 0


def test_sgc_parent_history_does_not_authorize_new_dynamic_child():
    vendor = "SGC SOLUTIONS CO., LTD."
    examples = [
        _example(
            vendor,
            "Dropship International",
            "113787 SGC prior.pdf",
            "international dropship invoice",
            po="113787",
        )
    ]
    result = _run(
        document=_document(
            vendor,
            "113787 113788 SGC 260807 SGC-07-AUG-2026-1 & -2.pdf",
            "international dropship invoice",
        ),
        context={
            "status": "resolved",
            "po_number": "113788",
            "verified_order_numbers": ["113788"],
            "location_code": "",
        },
        contract=_contract(dynamic=True),
        examples=examples,
        route="Dropship International/113788",
        bc_refs=["113788"],
    )
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert result["runtime_authority_overlay"]["same_vendor_label_count"] == 1
    assert result["runtime_authority_overlay"]["same_vendor_exact_route_label_count"] == 0


def test_exact_same_vendor_dynamic_history_can_preserve_dynamic_route():
    vendor = "Known Dynamic Supplier"
    examples = [
        _example(
            vendor,
            "Dropship International/113788",
            "113788 Known Dynamic prior.pdf",
            "international dropship invoice",
            po="113788",
        )
    ]
    result = _run(
        document=_document(vendor, "113788 Known Dynamic current.pdf", "international dropship invoice"),
        context={
            "status": "resolved",
            "po_number": "113788",
            "verified_order_numbers": ["113788"],
        },
        contract=_contract(dynamic=True),
        examples=examples,
        route="Dropship International/113788",
        bc_refs=["113788"],
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == "Dropship International/113788"


def test_sparse_psc_hold_language_cannot_create_rhonda_issues_authority():
    result = _run(
        document=_document(
            "Pacific Southwest Container, LLC",
            "108784_PSC_1225483_71026 HOLD-PSC Checking About This Order.pdf",
            "invoice hold checking about this order",
        ),
        context={"status": "not_found", "verified_order_numbers": []},
        contract=_contract(),
        examples=[],
        route="Rhonda - Issues",
    )
    assert result["pre_runtime_authority_decision"] == "auto_route"
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert result["runtime_authority_overlay"]["same_vendor_exact_route_label_count"] == 0
    assert any(
        "Rhonda - Issues" in blocker
        for blocker in result["runtime_authority_overlay"]["blockers"]
    )


def test_generic_credit_memo_cannot_specialize_to_ball_detention_without_detention_semantics():
    vendor = "BALL METAL BEVERAGE CONTAINER CORP"
    examples = [
        _example(
            vendor,
            "Vendor Credit Memos/Ball Detention Credits",
            "Ball prior detention credit.pdf",
            "detention charge credit memo",
            document_type="Credit_Memo",
        )
    ]
    result = _run_overlay(
        document=_document(
            vendor,
            "_BallMetalBeverageContainer_6393080 CREDIT_08292026 - Possible Duplicate.pdf",
            "ordinary vendor credit memo possible duplicate",
            document_type="Credit_Memo",
        ),
        context={"status": "not_found"},
        contract=_contract(),
        examples=examples,
        route="Vendor Credit Memos/Ball Detention Credits",
    )
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert result["runtime_authority_overlay"]["specific_child_route"] == "Vendor Credit Memos/Ball Detention Credits"
    assert "semantic evidence" in result["reason"]


def test_detention_semantics_can_preserve_ball_detention_route():
    vendor = "BALL METAL BEVERAGE CONTAINER CORP"
    examples = [
        _example(
            vendor,
            "Vendor Credit Memos/Ball Detention Credits",
            "Ball prior detention credit.pdf",
            "detention charge credit memo",
            document_type="Credit_Memo",
        )
    ]
    result = _run_overlay(
        document=_document(
            vendor,
            "BallMetalBeverageContainer_5701110_04_10_2025.pdf",
            "credit memo for detention charges and detention fees",
            document_type="Credit_Memo",
        ),
        context={"status": "not_found"},
        contract=_contract(),
        examples=examples,
        route="Vendor Credit Memos/Ball Detention Credits",
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == "Vendor Credit Memos/Ball Detention Credits"


def test_exact_same_vendor_source_placement_reference_vetoes_vendor_majority_override():
    vendor = "Cargo Modules LLC"
    examples = [
        _example(
            vendor,
            "Rhonda - Issues",
            "W111694 Cargo prior.pdf",
            "cargo invoice exception",
            source_route_path="Rhonda - Issues/OIBJC Insurance Claim Documents/Ocean Freight",
        ),
        _example(
            vendor,
            "Meg to Process",
            "Cargo quality replacement prior.pdf",
            "cargo quality replacement invoice",
            source_route_path="Meg to Process/Xolution/XO Quality Claim and Replacement Entries/W115989",
        ),
    ]
    result = _run_overlay(
        document=_document(
            vendor,
            "W115989 Cargo 250519 125134305-AR.pdf",
            "cargo invoice quality claim replacement",
        ),
        context={"status": "not_found"},
        contract=_contract(),
        examples=examples,
        route="Rhonda - Issues",
    )
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert result["runtime_authority_overlay"]["same_vendor_exact_reference_routes"]["W115989"] == ["Meg to Process"]
    assert "exact current reference" in result["reason"]


def test_exact_same_vendor_source_placement_reference_allows_matching_route():
    vendor = "Cargo Modules LLC"
    examples = [
        _example(
            vendor,
            "Meg to Process",
            "Cargo quality replacement prior.pdf",
            "cargo quality replacement invoice",
            source_route_path="Meg to Process/Xolution/XO Quality Claim and Replacement Entries/W115989",
        )
    ]
    result = _run_overlay(
        document=_document(
            vendor,
            "W115989 Cargo 250519 125134305-AR.pdf",
            "cargo invoice quality claim replacement",
        ),
        context={"status": "not_found"},
        contract=_contract(),
        examples=examples,
        route="Meg to Process",
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == "Meg to Process"
