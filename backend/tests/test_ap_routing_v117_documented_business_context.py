from services.ap_routing_business_context_service import (
    authority_business_signature,
    business_context_features,
    business_context_similarity,
)
from services.ap_routing_business_context_expansion_service import (
    build_train_business_context_deficits,
    select_hydrated_business_context_examples,
)
from services.ap_routing_corroboration_authority_service import (
    summarize_train_corroboration_authority,
)


def _doc(
    *,
    vendor="Acme",
    doc_type="AP_Invoice",
    file_name="invoice.pdf",
    raw_text="",
    po="",
    location="",
    invoice_number="",
    route=None,
):
    fields = {"vendor": vendor, "document_type": doc_type}
    if invoice_number:
        fields["invoice_number"] = invoice_number
    row = {
        "vendor_name": vendor,
        "vendor_canonical": vendor,
        "document_type": doc_type,
        "suggested_job_type": doc_type,
        "file_name": file_name,
        "raw_text": raw_text,
        "extracted_fields": fields,
        "bc_context": {key: value for key, value in {"po_number": po, "location_code": location}.items() if value},
    }
    if route is not None:
        row["route_path"] = route
    return row


def _train(
    item_id,
    route,
    *,
    vendor="Acme",
    doc_type="AP_Invoice",
    file_name="invoice.pdf",
    raw_text="",
    po="",
    location="",
):
    row = _doc(
        vendor=vendor,
        doc_type=doc_type,
        file_name=file_name,
        raw_text=raw_text,
        po=po,
        location=location,
        route=route,
    )
    row.update(
        {
            "source_item_id": item_id,
            "fingerprint": item_id,
            "label_source": "accounting_temp",
            "split": "train",
            "active": True,
        }
    )
    return row


def test_business_context_never_reads_route_label():
    left = _doc(po="81583", location="00", route="Route A")
    right = _doc(po="81583", location="00", route="Completely Different Route")
    assert business_context_features(left) == business_context_features(right)
    assert authority_business_signature(left) == authority_business_signature(right)


def test_documented_numeric_and_warehouse_order_location_facts_are_distinct():
    drop_like = _doc(po="81583", location="00")
    warehouse_like = _doc(po="W114166", location="051")
    d = business_context_features(drop_like)
    w = business_context_features(warehouse_like)
    assert "order_family:numeric" in d
    assert "location_code:00" in d
    assert "context_pair:numeric_location_00" in d
    assert "order_family:w" in w
    assert "location_code:051" in w
    assert "location_class:documented_warehouse" in w
    assert "context_pair:w_documented_warehouse_location" in w


def test_wtr_and_wa_numbering_create_transfer_and_assembly_context_only():
    transfer = business_context_features(_doc(file_name="WTR12345 transfer.pdf"))
    assembly = business_context_features(_doc(file_name="WA2073G invoice.pdf"))
    assert {"order_family:wtr", "workflow:transfer"}.issubset(transfer)
    assert {"order_family:wa", "workflow:assembly"}.issubset(assembly)


def test_documented_canpack_freight_and_invoice_markers_are_extracted():
    current = _doc(
        vendor="CanPack Olyphant CANPUSA",
        po="81182",
        location="00",
        invoice_number="1101319288A",
        raw_text="PPDADD FREIGHT-DS dunnage",
    )
    features = business_context_features(current)
    assert "vendor_fact:canpack_invoice_110" in features
    assert "shipment_method:ppdadd" in features
    assert "freight_line:freight_ds" in features
    assert "service:dunnage" in features


def test_business_similarity_rewards_same_context_and_penalizes_conflicting_freight_family():
    current = _doc(po="81583", location="00", raw_text="PPDADD FREIGHT-DS")
    same = _doc(po="81010", location="00", raw_text="PPDADD FREIGHT-DS")
    conflict = _doc(po="W114166", location="051", raw_text="PPD FREIGHT-WH")
    same_score = business_context_similarity(current, same)["score"]
    conflict_score = business_context_similarity(current, conflict)["score"]
    assert same_score > 8
    assert same_score > conflict_score
    assert any("business_mismatch:freight_line" == x for x in business_context_similarity(current, conflict)["signals"])


def test_same_vendor_business_context_can_earn_existing_strict_corroboration_without_five_generic_examples():
    train = [
        _train(f"a{i}", "Route A", po=str(81000 + i), location="00")
        for i in range(3)
    ]
    result = summarize_train_corroboration_authority(
        document=_doc(po="81583", location="00"),
        proposed_route="Route A",
        confidence=0.95,
        train_examples=train,
        contract={},
    )
    assert result["authority_ready"] is True
    assert result["earned_slice"] == "same_vendor_same_document_type_business_context"
    assert result["support_count"] == 3


def test_cross_vendor_business_context_requires_multiple_fact_families_and_five_supports():
    train = [
        _train(f"v{i}", "Route A", vendor=f"Vendor {i}", po=str(82000 + i), location="00")
        for i in range(5)
    ]
    result = summarize_train_corroboration_authority(
        document=_doc(vendor="Current Vendor", po="81583", location="00"),
        proposed_route="Route A",
        confidence=0.98,
        train_examples=train,
        contract={},
    )
    assert result["authority_ready"] is True
    assert result["earned_slice"] == "cross_vendor_document_type_business_context"
    assert result["support_count"] == 5


def test_ambiguous_business_context_slice_does_not_earn_authority():
    train = [
        _train("a1", "Route A", po="81001", location="00"),
        _train("a2", "Route A", po="81002", location="00"),
        _train("b1", "Route B", po="81003", location="00"),
        _train("b2", "Route B", po="81004", location="00"),
    ]
    result = summarize_train_corroboration_authority(
        document=_doc(po="81583", location="00"),
        proposed_route="Route A",
        confidence=1.0,
        train_examples=train,
        contract={},
    )
    assert result["authority_ready"] is False


def test_train_business_context_deficit_uses_existing_three_support_and_90_percent_purity_boundary():
    train = [
        _train("a1", "Route A", po="81001", location="00"),
        _train("a2", "Route A", po="81002", location="00"),
    ]
    deficits = build_train_business_context_deficits(train, routing_contract={})
    same = [row for row in deficits if row["kind"] == "same_vendor_document_type_business_context"]
    assert len(same) == 1
    assert same[0]["minimum_support"] == 3
    assert same[0]["minimum_purity"] == 0.90
    assert same[0]["additional_support_needed"] == 1


def test_business_context_expansion_admits_only_candidate_that_closes_train_derived_signature_deficit():
    train = [
        _train("a1", "Route A", po="81001", location="00"),
        _train("a2", "Route A", po="81002", location="00"),
    ]
    candidates = [
        _train("good", "Route A", po="81003", location="00"),
        _train("wrong-route", "Route B", po="81004", location="00"),
        _train("wrong-context", "Route A", po="W114166", location="051"),
    ]
    result = select_hydrated_business_context_examples(
        candidates,
        train,
        routing_contract={},
        initial_selected_route_counts={},
        max_additional=5,
        max_additional_per_route=30,
    )
    assert [row["source_item_id"] for row in result["selected_examples"]] == ["good"]
    assert result["selected_by_deficit_kind"]["same_vendor_document_type_business_context"] >= 1
