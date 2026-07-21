from datetime import datetime
from zoneinfo import ZoneInfo

from routers.inbox_today import (
    _attach_source_counts,
    _folder_comparison_key,
    _folders_equivalent,
    _row,
    _summary,
    build_today_filter,
)


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



def test_conflicting_stored_vendor_uses_extracted_vendor_for_display():
    row = _row({
        "id": "oi-conflict",
        "file_name": "oi.pdf",
        "document_type": "AP_Invoice",
        "vendor_canonical": "Gamer Packaging, Inc.",
        "vendor_raw": "O-I PACKAGING SOLUTIONS LLC",
        "vendor_resolution": {
            "vendor_name": "Gamer Packaging, Inc.",
            "vendor_no": "VIT1",
        },
        "extracted_fields": {
            "vendor": "O-I PACKAGING SOLUTIONS LLC",
        },
    })

    assert row["vendor_or_customer"] == "O-I PACKAGING SOLUTIONS LLC"
    assert row["vendor_identity_conflict"] is True
    assert row["stored_vendor_label"] == "Gamer Packaging, Inc."
    assert row["stored_vendor_no"] == "VIT1"


def test_agreeing_ball_resolution_remains_preferred_for_display():
    row = _row({
        "id": "ball-valid",
        "file_name": "ball.pdf",
        "document_type": "AP_Invoice",
        "vendor_canonical": "Ball Corp",
        "vendor_raw": "BALL METAL BEVERAGE CONTAINER CORP",
        "extracted_fields": {
            "vendor": "BALL METAL BEVERAGE CONTAINER CORP",
        },
    })

    assert row["vendor_or_customer"] == "Ball Corp"
    assert row["vendor_identity_conflict"] is False


def test_opaque_bc_vendor_code_does_not_create_false_display_conflict():
    row = _row({
        "id": "oi-code",
        "file_name": "oi-code.pdf",
        "document_type": "AP_Invoice",
        "vendor_canonical": "OWENS",
        "vendor_raw": "O-I PACKAGING SOLUTIONS LLC",
        "extracted_fields": {
            "vendor": "O-I PACKAGING SOLUTIONS LLC",
        },
    })

    assert row["vendor_or_customer"] == "O-I PACKAGING SOLUTIONS LLC"
    assert row["vendor_identity_conflict"] is False


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


def test_sharepoint_temp_folder_prefix_is_ignored_for_comparison():
    assert _folders_equivalent(
        "Freight Issues",
        "Temp Folder/Freight Issues",
    ) is True
    assert _folders_equivalent(
        "/Warehouse Not International/Assembly",
        "/General/Accounting/Accounts Payable/Temp Folder/Warehouse Not International/Assembly",
    ) is True


def test_base_folder_only_does_not_match_a_routing_destination():
    assert _folder_comparison_key("Temp Folder") == ""
    assert _folders_equivalent(
        "Dropship Not International Documents/111823",
        "Temp Folder",
    ) is False


def test_base_folder_matches_base_folder():
    assert _folders_equivalent(
        "Temp Folder",
        "General/Accounting/Accounts Payable/Temp Folder",
    ) is True


def test_genuine_folder_difference_remains_a_mismatch():
    assert _folders_equivalent(
        "Dropship Not International",
        "Temp Folder/Warehouse Not International",
    ) is False


def test_empty_prefiling_snapshot_means_base_folder_and_does_not_mix_current_rule():
    row = _row({
        "id": "oi-1",
        "file_name": "oi.pdf",
        "document_type": "AP_Invoice",
        "status": "Completed",
        "sharepoint_item_id": "item-1",
        "sharepoint_folder_path": "Temp Folder",
        "routing_preupload_checked_at": "2026-07-20T19:00:00+00:00",
        "routing_suggestion_snapshot": {
            "folder_path": "",
            "reason": "Staged for AP review",
            "source": "folder_routing_service",
            "suggested_at": "2026-07-20T19:00:00+00:00",
            "capture_type": "pre_filing_routing",
        },
        "_display_suggestion": {
            "folder_path": "Dropship Not International Documents/111823",
            "reason": "Current rule",
            "source": "folder_routing_service",
            "capture_type": "computed_current_rule",
        },
    })

    assert row["suggested_folder"] == "Temp Folder"
    assert row["routing_reason"] == "Staged for AP review"
    assert row["suggestion_capture"] == "pre_filing_routing"
    assert row["suggestion_is_pre_filing"] is True
    assert row["suggestion_comparable"] is True
    assert row["suggestion_matches_final"] is True


def test_legacy_unverified_prefiling_label_is_not_counted_as_initial_mismatch():
    row = _row({
        "id": "legacy-gate",
        "file_name": "ball.pdf",
        "document_type": "AP_Invoice",
        "status": "Completed",
        "sharepoint_item_id": "item-1",
        "sharepoint_folder_path": "Temp Folder/Warehouse Not International",
        "routing_suggestion_snapshot": {
            "folder_path": "Dropship Not International",
            "reason": "Routing gate recomputation",
            "source": "folder_routing_service",
            "suggested_at": "2026-07-20T08:57:27+00:00",
            "capture_type": "pre_filing_routing",
        },
    })

    assert row["suggestion_capture"] == "routing_gate_snapshot"
    assert row["suggestion_is_pre_filing"] is False
    assert row["suggestion_comparable"] is False
    assert row["suggestion_matches_final"] is None

    summary = _summary([row])
    assert summary["routing_gate_snapshots"] == 1
    assert summary["suggestion_mismatches_final"] == 0
    assert summary["pre_filing_mismatches"] == 0


def test_verified_prefiling_difference_remains_a_real_mismatch():
    row = _row({
        "id": "real-mismatch",
        "file_name": "invoice.pdf",
        "document_type": "AP_Invoice",
        "status": "Completed",
        "sharepoint_item_id": "item-1",
        "sharepoint_folder_path": "Temp Folder/Warehouse Not International",
        "routing_preupload_checked_at": "2026-07-20T12:00:00+00:00",
        "routing_suggestion_snapshot": {
            "folder_path": "Dropship Not International",
            "reason": "Pre-upload route",
            "source": "folder_routing_service",
            "suggested_at": "2026-07-20T12:00:00+00:00",
            "capture_type": "pre_filing_routing",
        },
    })

    assert row["suggestion_capture"] == "pre_filing_routing"
    assert row["suggestion_comparable"] is True
    assert row["suggestion_matches_final"] is False

    summary = _summary([row])
    assert summary["pre_filing_snapshots"] == 1
    assert summary["pre_filing_mismatches"] == 1
    assert summary["suggestion_mismatches_final"] == 1


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
    assert all(
        row["source_file_name"] == "R483296_2026071920053947_1.pdf"
        for row in rows
    )


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
