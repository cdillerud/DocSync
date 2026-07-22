from services.human_review_queue_service import filter_dispositioned_items
from services.non_transactional_disposition_service import (
    build_disposition_update,
)


def test_graphics_disposition_update():
    update = build_disposition_update(
        {"suggested_job_type": "Sales_Order"},
        "graphics_artwork",
        "human_decision_queue",
    )

    assert update["document_type"] == "Graphics_Artwork"
    assert update["non_transactional"] is True
    assert update["excluded_from_processing"] is True
    assert update["excluded_from_bc"] is True
    assert update["excluded_from_routing"] is True
    assert update["status"] == "Archived"
    assert update["auto_cleared"] is True
    assert (
        update["classification_override"]["original_type"]
        == "Sales_Order"
    )


def test_decision_queue_filters_dispositioned_documents():
    items = [
        {"doc_id": "keep-me"},
        {"doc_id": "remove-me"},
    ]

    filtered = filter_dispositioned_items(
        items,
        {"remove-me"},
    )

    assert [item["doc_id"] for item in filtered] == ["keep-me"]
