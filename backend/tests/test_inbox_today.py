from datetime import datetime
from zoneinfo import ZoneInfo

from routers.inbox_today import _row, _summary, build_today_filter


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
        },
        "sharepoint_folder_path": "Dropship Not International/Canpack",
        "ai_confidence": 0.97,
    })
    assert row["lane"] == "AP"
    assert row["routing_status"] == "manual_override"
    assert row["suggested_folder"] == "Dropship Not International"
    assert row["final_folder"] == "Dropship Not International/Canpack"
    assert row["confidence_pct"] == 97.0


def test_summary_allows_filed_and_auto_routed_to_overlap():
    auto_filed = _row({
        "id": "doc-2",
        "file_name": "warehouse.pdf",
        "created_utc": "2026-07-20T14:00:00+00:00",
        "document_type": "Warehouse_Receipt",
        "status": "AutoFiled",
        "automation_decision": "auto",
        "sharepoint_folder_path": "Warehouse Not International/Ball",
        "sharepoint_item_id": "item-1",
    })
    summary = _summary([auto_filed])
    assert summary["warehouse"] == 1
    assert summary["auto_routed"] == 1
    assert summary["filed"] == 1
