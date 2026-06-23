from scripts.seed_sales_order_test_data import build_documents


def test_seed_contains_expected_scenarios():
    documents = build_documents()
    by_id = {document["document_id"]: document for document in documents}

    assert len(documents) == 9
    assert by_id["so-approved-001"]["review_status"] == "approved"
    assert by_id["so-approve-001"]["review_status"] == "needs_review"
    assert by_id["so-unknown-customer"]["bc_customer_no"] is None
    assert (
        by_id["so-unmapped-item"]["extracted_fields"]["lines"][0][
            "bc_item_number"
        ]
        is None
    )
    assert (
        by_id["so-invalid-quantity-uom"]["extracted_fields"]["lines"][0][
            "uom"
        ]
        is None
    )
    assert by_id["so-low-confidence"]["ai_confidence"] < 0.90
    assert by_id["so-missing-sharepoint"]["sharepoint_web_url"] == ""
