import pytest

from services.ap_routing_learning_service import (
    LABEL_SOURCE_ACCOUNTING_TEMP,
    LABEL_SOURCE_REVIEWER_CORRECTION,
    UNLABELED_SOURCE_NAV_ARCHIVE,
    learning_readiness,
    normalize_route_path,
    normalize_vendor_name,
    prepare_routing_example,
    score_example_similarity,
)


def test_nav_archive_cannot_become_routing_label():
    with pytest.raises(ValueError, match="not routing authority"):
        prepare_routing_example(
            {
                "label_source": UNLABELED_SOURCE_NAV_ARCHIVE,
                "file_name": "old-tumalo.pdf",
                "route_path": "Purchase/Tumalo",
                "vendor_name": "Tumalo Creek Transportation",
            }
        )


def test_accounting_temp_is_valid_supervised_label():
    example = prepare_routing_example(
        {
            "label_source": LABEL_SOURCE_ACCOUNTING_TEMP,
            "source_item_id": "sp-item-1",
            "file_name": "110784A_TUMALO_0312676_08262026.pdf",
            "route_path": "Dropship Not International/Freight",
            "vendor_name": "Tumalo Creek Transportation, LLC",
            "document_type": "AP_Invoice",
        }
    )
    assert example["route_path"] == "Dropship Not International/Freight"
    assert example["normalized_vendor"] == "tumalo creek transportation"
    assert example["label_weight"] >= 0.9
    assert len(example["fingerprint"]) == 64


def test_reviewer_correction_outweighs_passive_placement():
    passive = prepare_routing_example(
        {
            "label_source": LABEL_SOURCE_ACCOUNTING_TEMP,
            "source_item_id": "p1",
            "route_path": "Warehouse Not International",
            "vendor_name": "Tumalo Creek Transportation",
            "document_type": "AP_Invoice",
        }
    )
    corrected = prepare_routing_example(
        {
            "label_source": LABEL_SOURCE_REVIEWER_CORRECTION,
            "source_item_id": "p2",
            "route_path": "Warehouse Not International",
            "vendor_name": "Tumalo Creek Transportation",
            "document_type": "AP_Invoice",
            "reviewer_corrected": True,
        }
    )
    assert score_example_similarity(
        corrected,
        vendor_name="Tumalo Creek Transportation",
        document_type="AP_Invoice",
    ) > score_example_similarity(
        passive,
        vendor_name="Tumalo Creek Transportation",
        document_type="AP_Invoice",
    )


def test_bc_order_family_increases_similarity_for_variable_vendor():
    warehouse = prepare_routing_example(
        {
            "label_source": LABEL_SOURCE_ACCOUNTING_TEMP,
            "source_item_id": "w",
            "route_path": "Warehouse Not International",
            "vendor_name": "Tumalo Creek Transportation",
            "document_type": "AP_Invoice",
            "bc_context": {"order_family": "warehouse"},
        }
    )
    dropship = prepare_routing_example(
        {
            "label_source": LABEL_SOURCE_ACCOUNTING_TEMP,
            "source_item_id": "d",
            "route_path": "Dropship Not International/Freight",
            "vendor_name": "Tumalo Creek Transportation",
            "document_type": "AP_Invoice",
            "bc_context": {"order_family": "dropship"},
        }
    )
    target = {"order_family": "warehouse"}
    assert score_example_similarity(
        warehouse,
        vendor_name="Tumalo Creek Transportation",
        document_type="AP_Invoice",
        bc_context=target,
    ) > score_example_similarity(
        dropship,
        vendor_name="Tumalo Creek Transportation",
        document_type="AP_Invoice",
        bc_context=target,
    )


def test_learning_readiness_requires_measured_holdout_accuracy():
    not_ready = learning_readiness(
        example_count=30,
        route_count=3,
        withheld_accuracy=None,
    )
    assert not not_ready["ready_for_auto_route"]
    assert "no withheld accuracy measurement" in not_ready["reasons"]

    ready = learning_readiness(
        example_count=30,
        route_count=3,
        withheld_accuracy=0.98,
    )
    assert ready["ready_for_auto_route"]


def test_route_normalization_is_temp_relative():
    assert normalize_route_path("/Warehouse Not International//Ball Orders/") == "Warehouse Not International/Ball Orders"
    assert normalize_vendor_name("Tumalo Creek Transportation, Inc.") == "tumalo creek transportation"
