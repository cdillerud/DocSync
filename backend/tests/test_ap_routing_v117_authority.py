import asyncio

from services.ap_routing_authority_guard_service import decide_ap_route_with_authority_guard


CONTRACT = {
    "version": "test-v117",
    "review_route": "",
    "auto_route_threshold": 0.92,
    "review_threshold": 0.70,
    "few_shot_limit": 8,
    "static_routes": [
        "DO NOT PAY",
        "Dropship Not International/Canpack",
        "Dropship Not International/Drop Ship All Others",
        "Dropship Not International/Freight",
        "Warehouse International",
        "Warehouse Not International",
        "Warehouse Not International/Temp - Cost Variance for POs",
        "Tooling Invoices",
        "Miscellaneous/Misc Invoices - need approval",
    ],
    "dynamic_routes": [],
    "bc_context_required_prefixes": [
        "Dropship Not International",
        "Warehouse International",
        "Warehouse Not International",
    ],
    "manual_only_routes": [],
}


def _example(vendor, route, file_name, raw_text, *, po="", location="", document_type="AP_Invoice"):
    ctx = {"status": "resolved" if po or location else "not_found"}
    if po:
        ctx["po_number"] = po
        ctx["verified_order_numbers"] = [po]
    if location:
        ctx["location_code"] = location
    return {
        "fingerprint": f"{vendor}|{route}|{file_name}",
        "vendor_name": vendor,
        "route_path": route,
        "file_name": file_name,
        "raw_text_excerpt": raw_text,
        "document_type": document_type,
        "label_weight": 0.94,
        "extracted_fields": {"vendor": vendor},
        "bc_context": ctx,
    }


def _doc(vendor, file_name, raw_text, *, document_type="AP_Invoice"):
    return {
        "file_name": file_name,
        "vendor_canonical": vendor,
        "document_type": document_type,
        "suggested_job_type": document_type,
        "confidence": 0.99,
        "raw_text": raw_text,
        "extracted_fields": {"vendor": vendor},
    }


def _sender(route, *, confidence=0.98, unresolved=None, bc_refs=None, matched=None):
    async def send(prompt, model):
        return {
            "proposed_route": route,
            "confidence": confidence,
            "evidence": ["synthetic regression evidence"],
            "reasoning_summary": "synthetic regression decision",
            "bc_refs_used": list(bc_refs or []),
            "unresolved": list(unresolved or []),
            "matched_example_ids": list(matched or []),
        }
    return send


def test_stable_vendor_stop_pay_consensus_overrides_generic_cost_variance_model():
    vendor = "Graphic Packaging International"
    examples = [
        _example(vendor, "DO NOT PAY", "10701 Graphic cost is wrong.pdf", "incorrect cost do not pay"),
        _example(vendor, "DO NOT PAY", "10702 Graphic duplicate invoice.pdf", "duplicate invoice hold payment"),
        _example(vendor, "DO NOT PAY", "10704 Graphic price is wrong.pdf", "price is wrong do not process"),
    ]
    result = asyncio.run(
        decide_ap_route_with_authority_guard(
            None,
            document=_doc(vendor, "10703 Graphic 180227 292929 cost is wrong.pdf", "cost is wrong on this invoice"),
            bc_context={"status": "not_found"},
            contract=CONTRACT,
            examples=examples,
            support_examples=examples,
            llm_send=_sender("Warehouse Not International/Temp - Cost Variance for POs"),
        )
    )
    assert result["pre_authority_guard_decision"] == "needs_review"
    assert result["pre_authority_guard_route"] == ""
    assert result["decision"] == "auto_route"
    assert result["route_path"] == "DO NOT PAY"
    assert result["authority_guard"]["raw_model_route"] == "Warehouse Not International/Temp - Cost Variance for POs"
    assert result["authority_guard"]["stable_vendor_route"] == "DO NOT PAY"
    assert result["authority_guard"]["action"] == "promote_stable_vendor_semantic_consensus"


def test_variable_vendor_standard_order_cannot_auto_route_to_warehouse_by_majority():
    vendor = "Tumalo Creek Transportation"
    examples = [
        _example(vendor, "Warehouse Not International", "110770_TUMALO_0311991.pdf", "freight invoice"),
        _example(vendor, "Warehouse Not International", "110771_TUMALO_0311992.pdf", "freight invoice"),
        _example(vendor, "Warehouse Not International", "110772_TUMALO_0311993.pdf", "freight invoice"),
        _example(vendor, "Dropship Not International/Freight", "_TUMALO_0312700.pdf", "freight invoice", po="110781A"),
        _example(vendor, "Dropship Not International/Freight", "_TUMALO_0312701.pdf", "freight invoice", po="110782A"),
    ]
    context = {"status": "resolved", "po_number": "110784B", "verified_order_numbers": ["110784B"]}
    result = asyncio.run(
        decide_ap_route_with_authority_guard(
            None,
            document=_doc(vendor, "110784B_TUMALO_0312777_08282026.pdf", "freight invoice for order 110784B"),
            bc_context=context,
            contract=CONTRACT,
            examples=examples,
            support_examples=examples,
            llm_send=_sender("Warehouse Not International", bc_refs=["110784B"]),
        )
    )
    assert result["ensemble_reconciliation"]["action"] == "supervised_route_selected"
    assert result["ensemble_reconciliation"]["selected_route"] == "Warehouse Not International"
    assert result["pre_authority_guard_decision"] == "auto_route"
    assert result["pre_authority_guard_route"] == "Warehouse Not International"
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert result["authority_guard"]["action"] == "force_review"
    assert result["authority_guard"]["current_reference_family"] == "standard_order"
    assert any("reference family" in blocker for blocker in result["authority_guard"]["blockers"])


def test_variable_vendor_route_neutral_semantics_can_authorize_correct_canpack_workflow():
    vendor = "Tumalo Creek Transportation"
    examples = [
        _example(vendor, "Dropship Not International/Canpack", "115580_TUMALO_a.pdf", "canpack dunnage return pallet freight", po="115580"),
        _example(vendor, "Dropship Not International/Canpack", "115581_TUMALO_b.pdf", "canpack dunnage return pallet freight", po="115581"),
        _example(vendor, "Dropship Not International/Freight", "115700_TUMALO_c.pdf", "customer freight delivery accessorial", po="115700"),
        _example(vendor, "Warehouse Not International", "_TUMALO_d.pdf", "warehouse storage inbound freight", po="W118500"),
    ]
    context = {"status": "resolved", "po_number": "115588", "verified_order_numbers": ["115588"]}
    result = asyncio.run(
        decide_ap_route_with_authority_guard(
            None,
            document=_doc(vendor, "115588_TUMALO_0312495_08242026.pdf", "canpack dunnage return pallet freight"),
            bc_context=context,
            contract=CONTRACT,
            examples=examples,
            support_examples=examples,
            llm_send=_sender("Dropship Not International/Canpack", bc_refs=["115588"]),
        )
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == "Dropship Not International/Canpack"


def test_foreign_reference_collision_without_model_reliance_does_not_veto_correct_route():
    current_vendor = "Radius Packaging"
    foreign = _example(
        "Other Vendor",
        "Dropship Not International/Drop Ship All Others",
        "112270_other.pdf",
        "ordinary dropship packaging invoice",
        po="112270",
    )
    context = {"status": "resolved", "po_number": "112270", "verified_order_numbers": ["112270"]}
    result = asyncio.run(
        decide_ap_route_with_authority_guard(
            None,
            document=_doc(current_vendor, "112270_Radius__.pdf", "ordinary dropship packaging invoice"),
            bc_context=context,
            contract=CONTRACT,
            examples=[foreign],
            support_examples=[foreign],
            llm_send=_sender("Dropship Not International/Drop Ship All Others"),
        )
    )
    assert result["decision"] == "auto_route"
    assert result["route_path"] == "Dropship Not International/Drop Ship All Others"


def test_foreign_reference_collision_is_blocked_when_model_cites_foreign_reference():
    current_vendor = "Radius Packaging"
    foreign = _example(
        "Other Vendor",
        "Dropship Not International/Drop Ship All Others",
        "112270_other.pdf",
        "ordinary dropship packaging invoice",
        po="112270",
    )
    context = {"status": "resolved", "po_number": "112270", "verified_order_numbers": ["112270"]}
    result = asyncio.run(
        decide_ap_route_with_authority_guard(
            None,
            document=_doc(current_vendor, "112270_Radius__.pdf", "ordinary dropship packaging invoice"),
            bc_context=context,
            contract=CONTRACT,
            examples=[foreign],
            support_examples=[foreign],
            llm_send=_sender(
                "Dropship Not International/Drop Ship All Others",
                bc_refs=["112270"],
                matched=[foreign["fingerprint"]],
            ),
        )
    )
    assert result["decision"] == "needs_review"
    assert any("different vendor" in blocker for blocker in result["authority_guard"]["blockers"])


def test_sparse_warehouse_reference_with_independent_warehouse_semantics_blocks_generic_tooling_auto():
    examples = [
        _example(
            "Cargo Modules",
            "Warehouse International",
            "W118609_Cargo_invoice.pdf",
            "international warehouse shipment delayed tooling charge",
            po="W118609",
        ),
        _example(
            "Hwa Hsia Glass",
            "Warehouse International",
            "W118610_HWA_invoice.pdf",
            "international warehouse shipment delayed tooling charge",
            po="W118610",
        ),
        _example(
            "Strategic Supplier",
            "Warehouse International",
            "W118611_supplier_invoice.pdf",
            "international warehouse shipment delayed tooling charge",
            po="W118611",
        ),
    ]
    context = {"status": "resolved", "po_number": "W118614", "verified_order_numbers": ["W118614"]}
    result = asyncio.run(
        decide_ap_route_with_authority_guard(
            None,
            document=_doc(
                "Evergreen Resources",
                "W118614 Evergreen_PS-INV260828_06172026 - delayed to mid-September.pdf",
                "international warehouse shipment delayed tooling charge",
            ),
            bc_context=context,
            contract=CONTRACT,
            examples=examples,
            support_examples=examples,
            llm_send=_sender("Tooling Invoices", confidence=0.99),
        )
    )
    assert result["decision"] == "needs_review"
    assert result["route_path"] == ""
    assert any("full-corpus evidence" in blocker for blocker in result["authority_guard"]["blockers"])
