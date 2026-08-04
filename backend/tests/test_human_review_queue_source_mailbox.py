from services.human_review_queue_service import resolve_source_mailbox


def test_explicit_source_mailbox_is_used():
    result = resolve_source_mailbox(
        {"context": {}},
        {"source_mailbox": "whdocuments@gamerpackaging.com"},
        {"Operations": "whdocuments@gamerpackaging.com"},
    )

    assert result == "whdocuments@gamerpackaging.com"


def test_ap_service_mailbox_uses_business_alias():
    result = resolve_source_mailbox(
        {"context": {}},
        {"source_mailbox": "hub-ap-intake@gamerpackaging.com"},
        {},
    )

    assert result == "billing@gamerpackaging.com"


def test_current_sales_lane_does_not_fabricate_sales_mailbox():
    result = resolve_source_mailbox(
        {
            "current_state": {
                "mailbox_category": "Sales",
            },
            "context": {},
        },
        {
            "mailbox_category": "Sales",
        },
        {
            "Sales": "hub-sales-intake@gamerpackaging.com",
        },
    )

    assert result == ""


def test_current_ap_lane_does_not_fabricate_ap_mailbox():
    result = resolve_source_mailbox(
        {
            "current_state": {
                "mailbox_category": "AP",
            },
            "context": {},
        },
        {
            "mailbox_category": "AP",
        },
        {
            "AP": "billing@gamerpackaging.com",
        },
    )

    assert result == ""


def test_historical_root_cause_can_resolve_original_mailbox():
    result = resolve_source_mailbox(
        {
            "context": {
                "root_cause": (
                    "operations_mailbox_captured_AP_invoice"
                ),
            },
        },
        {
            "mailbox_category": "AP",
        },
        {
            "Operations": "whdocuments@gamerpackaging.com",
        },
    )

    assert result == "whdocuments@gamerpackaging.com"
