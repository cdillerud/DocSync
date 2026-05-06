"""Tests for bucket_C_intake_gap_report."""
from __future__ import annotations

from scripts import bucket_C_intake_gap_report as bc


# ----------------------------------------------------------------------------
# Exclusion-pattern coverage (parity denominator should drop these)
# ----------------------------------------------------------------------------

def test_pst_marked_as_parity_exclusion():
    ch, action, dt, vendor = bc.classify_intake(
        "OrderIssuesEmails - Autumn.pst",
        "Temp Folder/Meg to Process/Order Issues Emails",
    )
    assert ch == "not_expected_in_hub"
    assert action == "exclude_from_parity_denominator"
    assert dt == "outlook_export"


def test_template_marked_as_parity_exclusion():
    ch, _, dt, _ = bc.classify_intake(
        "GP Check Template.xlsx",
        "Temp Folder/Warehouse International",
    )
    assert ch == "not_expected_in_hub"
    assert dt == "template_or_form"


def test_allocation_sheet_marked_as_parity_exclusion():
    ch, _, dt, _ = bc.classify_intake(
        "_Valley_4_30_2026_013899 Allocation - EM.pdf",
        "Temp Folder/S&H Invoices Approved",
    )
    assert ch == "not_expected_in_hub"
    assert dt == "allocation_sheet"


def test_do_not_pay_marked_as_parity_exclusion():
    ch, _, dt, _ = bc.classify_intake(
        "105228_XPO_238-766570_092225 - DO NOT PAY.pdf",
        "Temp Folder/DO NOT PAY/2025",
    )
    assert ch == "not_expected_in_hub"
    assert dt == "do_not_pay_marker"


def test_monthly_rec_marked_as_parity_exclusion():
    ch, _, dt, _ = bc.classify_intake(
        "Monthly Rec - April.xlsx",
        "Temp Folder/S&H Invoices waiting for approval/Monthly Rec & Templates",
    )
    assert ch == "not_expected_in_hub"
    assert dt == "monthly_reconciliation"


# ----------------------------------------------------------------------------
# Real intake gaps — vendor-recognized, actionable
# ----------------------------------------------------------------------------

def test_fedex_actionable_intake_gap():
    ch, action, dt, vendor = bc.classify_intake(
        "FedEx 042926 9-275-62775.pdf",
        "Temp Folder/Miscellaneous/Misc Invoices - need approval",
    )
    assert ch == "fedex_billing_email"
    assert action == "add_fedex_sender_to_AP_intake"
    assert dt == "ap_invoice_candidate"
    assert "FedEx" in vendor


def test_oipkgsol_actionable_intake_gap():
    ch, action, dt, _ = bc.classify_intake(
        "113606_OIPkgSol_51536759_05052026.PDF",
        "Temp Folder/Dropship Not International/Drop Ship All Others",
    )
    assert ch == "oi_packaging_solutions_email"
    assert dt == "ap_invoice_candidate"
    assert action == "add_oi_pkg_sender_to_AP_intake"


def test_unrecognized_vendor_in_misc_invoices_marked_as_real_gap():
    ch, action, dt, vendor = bc.classify_intake(
        "Boyer_19094_04242026.pdf",
        "Temp Folder/Miscellaneous/Misc Invoices - need approval",
    )
    assert ch == "boyer_email"
    assert dt == "ap_invoice_candidate"


def test_unknown_vendor_in_ap_lane_still_actionable():
    ch, action, dt, vendor = bc.classify_intake(
        "ZZZ_Unknown_Vendor_invoice_12345.pdf",
        "Temp Folder/Warehouse Not International/Ball Orders",
    )
    assert ch == "monitored_ap_lane_unknown_sender"
    assert dt == "ap_invoice_candidate"
    assert action == "investigate_intake_for_this_vendor"


# ----------------------------------------------------------------------------
# Filename / vendor / date / invoice extraction
# ----------------------------------------------------------------------------

def test_filename_pattern_alpha_only():
    p = bc._filename_pattern("113606_OIPkgSol_51536759_05052026.PDF")
    # Extension is intentionally stripped before token extraction.
    assert "OIPKGSOL" in p
    assert "PDF" not in p


def test_extract_date_token_iso_us_compact():
    assert "05052026" in bc._extract_date_token("113397_TUMALO_0307086_05052026.pdf")
    assert "2026-04-15" in bc._extract_date_token("INV_2026-04-15_acme.pdf")


def test_extract_invoice_token_skips_year():
    assert bc._extract_invoice_token(
        "FedEx 042926 9-275-62775.pdf"
    ) in {"042926", "275", "62775"}


# ----------------------------------------------------------------------------
# Aggregate analyze() output
# ----------------------------------------------------------------------------

def test_analyze_separates_exclusions_from_real_gaps():
    rows = [
        {"bucket": "C",
         "square9_name": "OrderIssuesEmails.pst",
         "square9_parent_path": "Temp Folder/Meg to Process",
         "square9_modified": "2026-04-15T13:39:07+00:00"},
        {"bucket": "C",
         "square9_name": "FedEx 042926 9-275-62775.pdf",
         "square9_parent_path": "Temp Folder/Miscellaneous/Misc Invoices - need approval",
         "square9_modified": "2026-05-06T13:18:16+00:00"},
        {"bucket": "C",
         "square9_name": "_Valley_4_30_2026_013899 Allocation - EM.pdf",
         "square9_parent_path": "Temp Folder/S&H Invoices Approved",
         "square9_modified": "2026-05-01T10:00:00+00:00"},
        {"bucket": "C",
         "square9_name": "Boyer_19094_04242026.pdf",
         "square9_parent_path": "Temp Folder/Miscellaneous/Misc Invoices - need approval",
         "square9_modified": "2026-04-28T19:55:33+00:00"},
    ]
    result = bc.analyze(rows)
    assert result["total_bucket_C"] == 4
    assert result["parity_exclusion_count"] == 2  # PST + Allocation
    assert result["real_intake_gap_count"] == 2  # FedEx + Boyer
    # FedEx should be in real-gap rows, PST should NOT be
    real_names = {r["square9_name"] for r in result["real_intake_gap_rows"]}
    assert "FedEx 042926 9-275-62775.pdf" in real_names
    assert "OrderIssuesEmails.pst" not in real_names


def test_exit_code_actionable_when_real_gaps_present():
    result = {
        "total_bucket_C": 4,
        "parity_exclusion_count": 2,
        "real_intake_gap_count": 2,
    }
    assert bc._exit_code(result) == 2


def test_exit_code_only_exclusions():
    result = {
        "total_bucket_C": 3,
        "parity_exclusion_count": 3,
        "real_intake_gap_count": 0,
    }
    assert bc._exit_code(result) == 1


def test_exit_code_empty():
    result = {
        "total_bucket_C": 0,
        "parity_exclusion_count": 0,
        "real_intake_gap_count": 0,
    }
    assert bc._exit_code(result) == 0


def test_csv_columns():
    rows = [
        {"bucket": "C",
         "square9_name": "x.pdf",
         "square9_parent_path": "Temp Folder/Misc",
         "square9_modified": "2026-05-06T10:00:00+00:00"},
    ]
    result = bc.analyze(rows)
    assert all(
        col in result["rows"][0] for col in bc.OUTPUT_COLUMNS
    )
