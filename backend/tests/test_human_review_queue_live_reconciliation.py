from services.human_review_queue_service import (
    reconcile_item_with_live_state,
)


def _misroute_item(
    document_type,
    lane="Operations",
):
    return {
        "doc_id": "doc-1",
        "file_name": "document.pdf",
        "issue_type": "isolated_misroute",
        "question": (
            "Should this be routed to AP? "
            "(currently: Operations)"
        ),
        "current_state": {
            "doc_type": document_type,
            "mailbox_category": lane,
        },
        "context": {
            "root_cause": (
                "operations_mailbox_captured_AP_invoice"
            ),
        },
        "submit_via": "bulk-classify",
        "submit_hint": {
            "doc_ids": ["doc-1"],
            "doc_type": document_type,
            "mailbox_category": "AP",
        },
    }


def test_shipping_document_is_not_offered_ap_route():
    item = _misroute_item(
        "Shipping_Document"
    )

    result = reconcile_item_with_live_state(
        item,
        {
            "id": "doc-1",
            "doc_type": "Shipping_Document",
            "mailbox_category": "Operations",
        },
    )

    assert result["issue_type"] == (
        "square9_side_issue"
    )
    assert result["submit_via"] is None
    assert result["submit_hint"] is None
    assert "Shipping_Document" in result["question"]
    assert (
        result["context"]["original_issue_type"]
        == "isolated_misroute"
    )


def test_bill_of_lading_is_not_offered_ap_route():
    item = _misroute_item(
        "Bill_of_Lading"
    )

    result = reconcile_item_with_live_state(
        item,
        {
            "id": "doc-1",
            "doc_type": "Bill_of_Lading",
            "mailbox_category": "Operations",
        },
    )

    assert result["issue_type"] == (
        "square9_side_issue"
    )
    assert result["submit_via"] is None


def test_ap_invoice_remains_actionable():
    item = _misroute_item("AP_Invoice")

    result = reconcile_item_with_live_state(
        item,
        {
            "id": "doc-1",
            "doc_type": "AP_Invoice",
            "mailbox_category": "Operations",
        },
    )

    assert result["issue_type"] == (
        "isolated_misroute"
    )
    assert result["submit_via"] == "bulk-classify"
    assert (
        result["submit_hint"]["mailbox_category"]
        == "AP"
    )


def test_unknown_document_remains_for_review():
    item = _misroute_item(
        "Unknown_Document"
    )

    result = reconcile_item_with_live_state(
        item,
        {
            "id": "doc-1",
            "doc_type": "Unknown_Document",
            "mailbox_category": "Operations",
        },
    )

    assert result["issue_type"] == (
        "isolated_misroute"
    )
    assert result["submit_via"] == "bulk-classify"


def test_non_ap_type_already_in_ap_is_not_rewritten():
    item = _misroute_item(
        "Shipping_Document",
        lane="AP",
    )

    result = reconcile_item_with_live_state(
        item,
        {
            "id": "doc-1",
            "doc_type": "Shipping_Document",
            "mailbox_category": "AP",
        },
    )

    assert result["issue_type"] == (
        "isolated_misroute"
    )
