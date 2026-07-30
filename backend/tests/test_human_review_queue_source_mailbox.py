from services.human_review_queue_service import (
    resolve_source_mailbox,
)


def test_explicit_source_mailbox_wins():
    result = resolve_source_mailbox(
        {
            "current_state": {
                "mailbox_category": "AP",
            },
            "context": {
                "root_cause": (
                    "operations_mailbox_captured_AP_invoice"
                ),
            },
        },
        {
            "source_mailbox": (
                "whdocuments@gamerpackaging.com"
            ),
            "mailbox_category": "AP",
        },
        {
            "AP": "billing@gamerpackaging.com",
            "Operations": (
                "whdocuments@gamerpackaging.com"
            ),
        },
    )

    assert result == "whdocuments@gamerpackaging.com"


def test_root_cause_preserves_operations_source():
    result = resolve_source_mailbox(
        {
            "current_state": {
                "mailbox_category": "AP",
            },
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
            "AP": "billing@gamerpackaging.com",
            "Operations": (
                "whdocuments@gamerpackaging.com"
            ),
        },
    )

    assert result == "whdocuments@gamerpackaging.com"


def test_ap_lane_uses_business_mailbox_alias():
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

    assert result == "billing@gamerpackaging.com"
