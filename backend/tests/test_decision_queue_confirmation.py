import pytest

from services.decision_queue_confirmation_service import (
    build_confirmation_record,
    confirmation_matches_current_state,
    current_document_state,
)


def test_current_document_state_uses_live_fields():
    state = current_document_state(
        {
            "doc_type": "AP_Invoice",
            "mailbox_category": "AP",
        }
    )

    assert state == {
        "doc_type": "AP_Invoice",
        "mailbox_category": "AP",
    }


def test_confirmation_matches_same_snapshot():
    doc = {
        "doc_type": "AP_Invoice",
        "mailbox_category": "AP",
        "decision_queue_confirmation": {
            "document_type": "AP_Invoice",
            "mailbox_category": "AP",
        },
    }

    assert (
        confirmation_matches_current_state(doc)
        is True
    )


def test_confirmation_does_not_match_changed_lane():
    doc = {
        "doc_type": "AP_Invoice",
        "mailbox_category": "Operations",
        "decision_queue_confirmation": {
            "document_type": "AP_Invoice",
            "mailbox_category": "AP",
        },
    }

    assert (
        confirmation_matches_current_state(doc)
        is False
    )


def test_confirmation_does_not_match_changed_type():
    doc = {
        "doc_type": "Order_Confirmation",
        "mailbox_category": "Operations",
        "decision_queue_confirmation": {
            "document_type": "Sales_Order",
            "mailbox_category": "Operations",
        },
    }

    assert (
        confirmation_matches_current_state(doc)
        is False
    )


def test_build_confirmation_captures_type_and_lane():
    confirmation = build_confirmation_record(
        {
            "id": "doc-1",
            "doc_type": "Order_Confirmation",
            "mailbox_category": "Operations",
        },
        confirmed_by="human_decision_queue",
        issue_type="isolated_misroute",
    )

    assert (
        confirmation["document_type"]
        == "Order_Confirmation"
    )
    assert (
        confirmation["mailbox_category"]
        == "Operations"
    )
    assert (
        confirmation["source"]
        == "human_decision_queue"
    )


def test_unknown_type_cannot_be_confirmed():
    with pytest.raises(
        ValueError,
        match="Set a valid document type",
    ):
        build_confirmation_record(
            {
                "id": "doc-1",
                "doc_type": "Unknown_Document",
                "mailbox_category": "Operations",
            },
            confirmed_by="human_decision_queue",
        )


def test_confirmation_does_not_hide_different_issue():
    doc = {
        "doc_type": "AP_Invoice",
        "mailbox_category": "AP",
        "decision_queue_confirmation": {
            "document_type": "AP_Invoice",
            "mailbox_category": "AP",
            "issue_type": "isolated_misroute",
        },
    }

    assert confirmation_matches_current_state(
        doc,
        "ambiguous_classification",
    ) is False


def test_multiple_issue_confirmations_are_independent():
    doc = {
        "doc_type": "AP_Invoice",
        "mailbox_category": "AP",
        "decision_queue_confirmations": {
            "isolated_misroute": {
                "document_type": "AP_Invoice",
                "mailbox_category": "AP",
                "issue_type": "isolated_misroute",
            },
            "ambiguous_classification": {
                "document_type": "AP_Invoice",
                "mailbox_category": "AP",
                "issue_type": "ambiguous_classification",
            },
        },
    }

    assert confirmation_matches_current_state(
        doc,
        "isolated_misroute",
    ) is True

    assert confirmation_matches_current_state(
        doc,
        "ambiguous_classification",
    ) is True

    assert confirmation_matches_current_state(
        doc,
        "square9_side_issue",
    ) is False



def test_acknowledgement_is_not_state_bound():
    confirmation = build_confirmation_record(
        {
            "id": "doc-ack",
            "doc_type": "Shipping_Document",
            "mailbox_category": "Operations",
        },
        confirmed_by="human_decision_queue",
        issue_type="square9_side_issue",
        resolution="acknowledged",
    )

    assert confirmation["state_bound"] is False
    assert confirmation["resolution"] == "acknowledged"


def test_different_document_allows_unknown_type():
    confirmation = build_confirmation_record(
        {
            "id": "doc-match",
            "doc_type": "Unknown_Document",
            "mailbox_category": "Operations",
        },
        confirmed_by="human_decision_queue",
        issue_type="ambiguous_match",
        resolution="different_document",
    )

    assert confirmation["state_bound"] is False


def test_issue_resolution_remains_resolved_after_state_change():
    doc = {
        "doc_type": "AP_Invoice",
        "mailbox_category": "AP",
        "decision_queue_confirmations": {
            "ambiguous_match": {
                "document_type": "Shipping_Document",
                "mailbox_category": "Operations",
                "issue_type": "ambiguous_match",
                "resolution": "different_document",
            },
        },
    }

    assert confirmation_matches_current_state(
        doc,
        "ambiguous_match",
    ) is True


def test_corrected_state_reopens_after_later_change():
    doc = {
        "doc_type": "Shipping_Document",
        "mailbox_category": "Operations",
        "decision_queue_confirmations": {
            "isolated_misroute": {
                "document_type": "AP_Invoice",
                "mailbox_category": "AP",
                "issue_type": "isolated_misroute",
                "resolution": "corrected_state",
            },
        },
    }

    assert confirmation_matches_current_state(
        doc,
        "isolated_misroute",
    ) is False
