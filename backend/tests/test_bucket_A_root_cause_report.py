"""Tests for bucket_A_root_cause_report."""
from __future__ import annotations

from scripts import bucket_A_root_cause_report as ba


def test_classify_high_confidence_misrouted():
    row = {
        "best_match_score": "0.95",
        "best_hub_mailbox_category": "Operations",
        "best_hub_doc_type": "AP_INVOICE",
        "best_hub_suggested_job_type": "AP_Invoice",
        "square9_name": "_Valley_4_30_2026_013901.pdf",
        "square9_parent_path": "Temp Folder/S&H Invoices Approved",
    }
    assert ba.classify_root_cause(row) == "high_confidence_AP_invoice_misrouted"


def test_classify_sales_mailbox_capture():
    row = {
        "best_match_score": "0.75",
        "best_hub_mailbox_category": "SALES",
        "best_hub_doc_type": "SALES_INVOICE",
        "best_hub_suggested_job_type": "AR_Invoice",
        "square9_name": "107463 HWA HSIA 260417 HH-150417D.pdf",
        "square9_parent_path": "Temp Folder/Dropship International",
    }
    assert ba.classify_root_cause(row) == "sales_mailbox_captured_AP_invoice"


def test_classify_operations_mailbox_capture():
    row = {
        "best_match_score": "0.62",
        "best_hub_mailbox_category": "Operations",
        "best_hub_doc_type": "Shipping_Document",
        "best_hub_suggested_job_type": "Shipping_Document",
        "square9_name": "113922_Progressive_050126.pdf",
        "square9_parent_path": "Temp Folder/Warehouse Not International",
    }
    assert ba.classify_root_cause(row) == "operations_mailbox_captured_AP_invoice"


def test_classify_non_ap_document_in_ap_folder():
    row = {
        "best_match_score": "0.55",
        "best_hub_mailbox_category": "Other",
        "best_hub_doc_type": "OTHER",
        "best_hub_suggested_job_type": "Remittance",
        "square9_name": "Expected Vendor Credits.xlsx",
        "square9_parent_path": "Temp Folder/Vendor Credit Memos",
    }
    assert ba.classify_root_cause(row) == "square9_ap_folder_contains_non_ap_document"


def test_classify_low_confidence_ambiguous():
    row = {
        "best_match_score": "0.42",
        "best_hub_mailbox_category": "AP",
        "best_hub_doc_type": "AP_INVOICE",
        "best_hub_suggested_job_type": "AP_Invoice",
        "square9_name": "anything.pdf",
        "square9_parent_path": "Temp Folder/Misc",
    }
    assert ba.classify_root_cause(row) == "low_confidence_match_ambiguous"


def test_filename_pattern_clusters_vendor_naming():
    p1 = ba._filename_pattern("113397_TUMALO_0307086_05052026.pdf")
    p2 = ba._filename_pattern("110427_TUMALO_0306899_05052026.pdf")
    # Both have TUMALO + PDF in the surviving alpha tokens
    assert "TUMALO" in p1
    assert "TUMALO" in p2


def test_root_segment_temp_folder_uses_two_levels():
    assert ba._root_segment("Temp Folder/S&H Invoices Approved") == \
        "Temp Folder/S&H Invoices Approved"
    assert ba._root_segment("Temp Folder/Warehouse Not International/Ball Orders") == \
        "Temp Folder/Warehouse Not International"
    assert ba._root_segment("Freight Issues") == "Freight Issues"


def test_analyze_groups_into_cohorts():
    rows = [
        {  # high-confidence misroute
            "bucket": "A",
            "square9_name": "_Valley_4_30_2026_013901.pdf",
            "square9_parent_path": "Temp Folder/S&H Invoices Approved",
            "best_hub_doc_id": "h1",
            "best_hub_file_name": "013901.pdf",
            "best_hub_mailbox_category": "Operations",
            "best_hub_doc_type": "AP_INVOICE",
            "best_hub_suggested_job_type": "AP_Invoice",
            "best_hub_sharepoint_folder_path": "Dropship Not International Documents",
            "best_hub_routing_status": "auto_process",
            "best_match_score": "0.95",
            "best_match_reason": "invoice_number_clean+vendor_token",
        },
        {  # sales mailbox capture
            "bucket": "A",
            "square9_name": "107463 HWA HSIA 260417 HH-150417D.pdf",
            "square9_parent_path": "Temp Folder/Dropship International",
            "best_hub_doc_id": "h2",
            "best_hub_file_name": "hh.pdf",
            "best_hub_mailbox_category": "SALES",
            "best_hub_doc_type": "SALES_INVOICE",
            "best_hub_suggested_job_type": "AR_Invoice",
            "best_hub_sharepoint_folder_path": "Misc",
            "best_hub_routing_status": "auto_process",
            "best_match_score": "0.75",
            "best_match_reason": "invoice_token+date_proximity",
        },
    ]
    enrichment = {
        "h1": {"id": "h1", "email_sender": "billing@valley.com",
               "classification_method": "mailbox:Operations+evidence",
               "routing_reason": "operations_lane"},
        "h2": {"id": "h2", "email_sender": "sales-cc@gamerpackaging.com",
               "classification_method": "mailbox:SALES",
               "routing_reason": "sales_lane"},
    }
    result = ba.analyze(rows, enrichment)
    assert result["total_bucket_A"] == 2
    causes = result["root_cause_counts"]
    assert causes.get("high_confidence_AP_invoice_misrouted") == 1
    assert causes.get("sales_mailbox_captured_AP_invoice") == 1
    # Different cohorts (different sender + cat)
    assert len(result["cohorts"]) == 2
    # high-confidence misrouted list correctly populated
    assert len(result["high_confidence_misrouted"]) == 1
    assert result["high_confidence_misrouted"][0]["best_hub_doc_id"] == "h1"
    # ap_doc_in_non_ap_mailbox includes h1 (AP_INVOICE in Operations)
    assert any(r["best_hub_doc_id"] == "h1" for r in result["ap_doc_in_non_ap_mailbox"])
    # sales_classified_in_ap_folder includes h2
    assert any(r["best_hub_doc_id"] == "h2" for r in result["sales_classified_in_ap_folder"])


def test_exit_code_actionable_when_misrouting_present():
    result = {"total_bucket_A": 5,
              "root_cause_counts": {"high_confidence_AP_invoice_misrouted": 3,
                                    "low_confidence_match_ambiguous": 2}}
    assert ba._exit_code(result) == 2


def test_exit_code_ambiguous_only():
    result = {"total_bucket_A": 5,
              "root_cause_counts": {"low_confidence_match_ambiguous": 5}}
    assert ba._exit_code(result) == 1


def test_exit_code_empty():
    result = {"total_bucket_A": 0, "root_cause_counts": {}}
    assert ba._exit_code(result) == 0
