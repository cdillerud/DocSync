import inspect
import json

import pytest

from services import ap_routing_relevant_learning_service as relevant
from services.ap_routing_ai_primary_service import (
    _augment_prompt_with_train_context,
    _prompt_learning_example,
)
from services.ap_routing_business_context_service import business_context_features
from services.ap_routing_learned_autonomy_service import evaluate_learned_autonomy
from services.ap_routing_train_context_service import build_train_learning_context


def _train(
    item_id,
    route,
    *,
    vendor="Acme",
    file_name="10001_invoice.pdf",
    raw_text="",
    split="train",
    label_source="accounting_temp",
    bc_context=None,
):
    return {
        "source_item_id": item_id,
        "fingerprint": item_id,
        "label_source": label_source,
        "split": split,
        "active": True,
        "vendor_name": vendor,
        "document_type": "AP_Invoice",
        "suggested_job_type": "AP_Invoice",
        "file_name": file_name,
        "raw_text": raw_text,
        "raw_text_excerpt": raw_text,
        "extracted_fields": {
            "vendor": vendor,
            "document_type": "AP_Invoice",
            "po_number": (
                file_name.split("_", 1)[0]
                if file_name.split("_", 1)[0].isdigit()
                else ""
            ),
        },
        "bc_context": bc_context or {},
        "route_path": route,
    }


def _current(
    *,
    vendor="Acme",
    file_name="W118572_Current.pdf",
    raw_text="",
    bc_context=None,
):
    return {
        "vendor_name": vendor,
        "vendor_canonical": vendor,
        "document_type": "AP_Invoice",
        "suggested_job_type": "AP_Invoice",
        "file_name": file_name,
        "raw_text": raw_text,
        "extracted_fields": {"vendor": vendor, "document_type": "AP_Invoice"},
        "bc_context": bc_context or {},
    }


def test_rev9_prompt_core_reserves_two_structural_slots_after_same_vendor(monkeypatch):
    current = _current(file_name="W118572_Current.pdf")
    same_vendor = [
        _train(
            f"same-{i}",
            "Same Vendor Route",
            vendor="Acme",
            file_name=f"{12000 + i}_invoice.pdf",
        )
        for i in range(6)
    ]
    structural = [
        _train(
            f"struct-{i}",
            "Warehouse Structural Route",
            vendor=f"Other Vendor {i}",
            file_name=f"W{22000 + i}_freight.pdf",
        )
        for i in range(2)
    ]

    monkeypatch.setattr(
        relevant,
        "learned_relevance_score",
        lambda document, example: (
            100.0 if example.get("vendor_name") == "Acme" else 1.0
        ),
    )

    selected = relevant.build_relevant_learning_examples(
        current,
        same_vendor + structural,
        limit=8,
    )

    assert len(selected) == 8
    core = selected[:6]
    assert sum(row.get("vendor_name") == "Acme" for row in core) == 4
    assert {row.get("source_item_id") for row in core}.issuperset(
        {"struct-0", "struct-1"}
    )


def test_rev9_foreign_prompt_example_redacts_exact_reference_material():
    current = _current(vendor="Acme", file_name="W118572_Current.pdf")
    foreign = _train(
        "foreign-1",
        "Warehouse Not International",
        vendor="Other Vendor",
        file_name="W998877_PO123456_INV654321.pdf",
        raw_text="PO 123456 invoice 654321 warehouse inbound freight",
    )
    foreign["extracted_fields"].update(
        {
            "po_number": "123456",
            "invoice_number": "654321",
            "reference_number": "998877",
        }
    )

    prompt_row = _prompt_learning_example(foreign, current_document=current)

    assert prompt_row["cross_vendor_exact_reference_redacted"] is True
    assert "file_name" not in prompt_row
    assert "extracted_fields" not in prompt_row["key_evidence"]
    assert prompt_row["key_evidence"]["exact_reference_fields"] == "redacted_cross_vendor"
    assert prompt_row["key_evidence"]["reference_family"] == "w_reference"
    assert "warehouse inbound freight" in prompt_row["key_evidence"]["semantic_excerpt"]
    assert "[REDACTED_REF]" in prompt_row["key_evidence"]["semantic_excerpt"]
    assert prompt_row["route_path"] == "Warehouse Not International"
    serialized = json.dumps(prompt_row)
    assert "123456" not in serialized
    assert "654321" not in serialized
    assert "998877" not in serialized


def test_rev9_same_vendor_prompt_example_keeps_full_human_evidence():
    current = _current(vendor="Acme")
    example = _train(
        "same-1",
        "Warehouse Not International",
        vendor="Acme",
        file_name="W118500_PO778899.pdf",
        raw_text="warehouse receipt PO 778899",
    )
    example["extracted_fields"]["po_number"] = "778899"

    prompt_row = _prompt_learning_example(example, current_document=current)

    assert prompt_row["cross_vendor_exact_reference_redacted"] is False
    assert prompt_row["file_name"] == "W118500_PO778899.pdf"
    assert prompt_row["key_evidence"]["extracted_fields"]["po_number"] == "778899"


def test_rev9_train_context_business_feature_usage_is_human_train_only():
    current = _current(
        file_name="W118572_Current.pdf",
        bc_context={"location_code": "911"},
    )
    train_rows = [
        _train(
            "w-1",
            "Warehouse Not International",
            vendor="Vendor A",
            file_name="W118500_receipt.pdf",
            bc_context={"location_code": "911"},
        ),
        _train(
            "w-2",
            "Warehouse Not International",
            vendor="Vendor B",
            file_name="W118501_receipt.pdf",
            bc_context={"location_code": "911"},
        ),
        _train(
            "heldout-w",
            "Dropship Not International/Freight",
            vendor="Vendor C",
            file_name="W118502_receipt.pdf",
            bc_context={"location_code": "911"},
            split="holdout",
        ),
    ]

    context = build_train_learning_context(
        current,
        train_rows,
        contract={},
        neighborhood_limit=24,
        route_limit=12,
    )

    assert "order_family:w" in context["current_business_context_features"]
    assert (
        "context_pair:w_documented_warehouse_location"
        in context["current_business_context_features"]
    )

    usage = {
        row["feature"]: row
        for row in context["business_feature_route_usage"]
    }
    assert usage["order_family:w"]["human_train_support_count"] == 2
    counts = {
        row["route_path"]: row["count"]
        for row in usage["order_family:w"]["route_counts"]
    }
    assert counts == {"Warehouse Not International": 2}


def test_rev9_prompt_rules_explain_structural_usage_and_redaction():
    prompt = _augment_prompt_with_train_context(
        "SYSTEM\nINPUT:\n{}",
        {
            "eligible_train_example_count": 10,
            "current_vendor": "Acme",
            "business_feature_route_usage": [],
        },
    )

    assert "business_feature_route_usage" in prompt
    assert "cross_vendor_exact_reference_redacted=true" in prompt
    assert "WTR, WA, and W structural families" in prompt
    assert "Approval and processor leaves are ownership assignments" in prompt


def test_rev9_does_not_change_learned_autonomy_confidence_floor():
    signature = inspect.signature(evaluate_learned_autonomy)
    assert signature.parameters["minimum_model_confidence"].default == 0.90
