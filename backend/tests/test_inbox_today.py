from datetime import datetime
from zoneinfo import ZoneInfo

from routers.inbox_today import _attach_source_counts, _row, _summary, build_today_filter


def test_today_filter_uses_chicago_midnight_and_excludes_batch_parents():
    now = datetime(2026, 7, 20, 10, 30, tzinfo=ZoneInfo("America/Chicago"))
    assert build_today_filter(now) == {
        "created_utc": {"$gte": "2026-07-20T05:00:00+00:00"},
        "status": {"$ne": "batch_parent"},
    }


def test_manual_routing_correction_is_visible():
    row = _row({
        "id": "doc-1",
        "file_name": "invoice.pdf",
        "created_utc": "2026-07-20T13:00:00+00:00",
        "document_type": "AP_Invoice",
        "status": "NeedsReview",
        "workflow_status": "needs_review",
        "human_routing_decision": {
            "decision_type": "folder_correction",
            "suggested_folder": "Dropship Not International",
            "selected_folder": "Dropship Not International/Canpack",
            "suggested_reason": "Vendor evidence",
            "source": "human_decision_queue_folder_browser",
            "created_at": "2026-07-20T13:05:00+00:00",
        },
        "sharepoint_folder_path": "Dropship Not International/Canpack",
        "ai_confidence": 0.97,
    })
    assert row["lane"] == "AP"
    assert row["routing_status"] == "manual_override"
    assert row["suggested_folder"] == "Dropship Not International"
    assert row["final_folder"] == "Dropship Not International/Canpack"
    assert row["suggestion_capture"] == "human_review"
    assert row["suggestion_is_historical"] is True
    assert row["confidence_pct"] == 97.0


def test_file_and_clear_suggestion_fields_are_treated_as_historical():
    row = _row({
        "id": "doc-filed",
        "file_name": "freight.pdf",
        "created_utc": "2026-07-20T13:00:00+00:00",
        "document_type": "AP_Invoice",
        "status": "Completed",
        "workflow_status": "completed",
        "sharepoint_folder_suggestion": "Freight Issues",
        "sharepoint_folder_reason": "Freight invoice from carrier",
        "sharepoint_folder_path": "/Freight Issues",
        "filed_at": "2026-07-20T13:01:00+00:00",
        "sharepoint_item_id": "item-1",
        "auto_cleared": True,
    })
    assert row["suggested_folder"] == "Freight Issues"
    assert row["routing_reason"] == "Freight invoice from carrier"
    assert row["suggestion_capture"] == "file_and_clear_decision"
    assert row["suggestion_is_historical"] is True
    assert row["suggestion_matches_final"] is True
    assert row["routing_status"] == "filed"


def test_split_children_count_as_one_source_file_and_multiple_documents():
    rows = [
        _row({
            "id": f"child-{number}",
            "file_name": f"R483296_2026071920053947_1_doc{number}.pdf",
            "batch_parent_id": "parent-1",
            "batch_source_filename": "R483296_2026071920053947_1.pdf",
            "batch_group_num": number,
            "document_type": "AP_Invoice",
            "created_utc": "2026-07-20T00:12:00+00:00",
        })
        for number in (1, 2, 3)
    ]
    _attach_source_counts(rows)
    summary = _summary(rows)

    assert summary["source_files"] == 1
    assert summary["produced_documents"] == 3
    assert summary["split_outputs"] == 3
    assert summary["multi_output_sources"] == 1
    assert all(row["source_output_count"] == 3 for row in rows)
    assert all(row["source_file_name"] == "R483296_2026071920053947_1.pdf" for row in rows)


def test_non_split_documents_each_count_as_their_own_source_attachment():
    rows = [
        _row({
            "id": "doc-a",
            "file_name": "a.pdf",
            "internet_message_id": "message-a",
            "attachment_id": "attachment-a",
            "document_type": "AP_Invoice",
        }),
        _row({
            "id": "doc-b",
            "file_name": "b.pdf",
            "internet_message_id": "message-b",
            "attachment_id": "attachment-b",
            "document_type": "Warehouse_Receipt",
        }),
    ]
    _attach_source_counts(rows)
    summary = _summary(rows)

    assert summary["source_files"] == 2
    assert summary["produced_documents"] == 2
    assert summary["split_outputs"] == 0


def test_summary_allows_filed_and_auto_routed_to_overlap():
    auto_filed = _row({
        "id": "doc-2",
        "file_name": "warehouse.pdf",
        "created_utc": "2026-07-20T14:00:00+00:00",
        "document_type": "Warehouse_Receipt",
        "status": "AutoFiled",
        "automation_decision": "auto",
        "sharepoint_folder_suggestion": "Warehouse Not International/Ball",
        "sharepoint_folder_path": "Warehouse Not International/Ball",
        "sharepoint_item_id": "item-1",
    })
    summary = _summary([auto_filed])
    assert summary["warehouse"] == 1
    assert summary["auto_routed"] == 1
    assert summary["filed"] == 1
    assert summary["suggestion_matches_final"] == 1
