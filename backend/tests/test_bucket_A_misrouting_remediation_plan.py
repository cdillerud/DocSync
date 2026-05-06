"""Tests for bucket_A_misrouting_remediation_plan."""
from __future__ import annotations

import csv
import json
import os
from typing import Dict, List

import pytest

from scripts import bucket_A_misrouting_remediation_plan as ba


# ---------------------------------------------------------------------------
# Synthetic fixtures (no Mongo, no live VM)
# ---------------------------------------------------------------------------

def _row(**kwargs) -> Dict[str, str]:
    base = {
        "root_cause": "high_confidence_AP_invoice_misrouted",
        "square9_name": "_Valley_4_30_2026_013901.pdf",
        "square9_parent_path": "Temp Folder/S&H Invoices Approved",
        "square9_parent_root": "Temp Folder/S&H Invoices Approved",
        "filename_pattern": "VALLEY PDF",
        "best_hub_doc_id": "doc-1",
        "best_hub_file_name": "valley_invoice.pdf",
        "best_hub_mailbox_category": "Operations",
        "best_hub_doc_type": "AP_INVOICE",
        "best_hub_suggested_job_type": "AP_Invoice",
        "classification_method": "ai_classifier:gpt-4o",
        "best_hub_sharepoint_folder_path": "Operations/2026/04",
        "sharepoint_folder_root": "Operations",
        "routing_status": "routed",
        "routing_reason": "vendor_match",
        "email_sender": "billing@valley.com",
        "email_subject": "Invoice 013901",
        "best_match_score": "0.95",
        "best_match_reason": "vendor+invoice",
    }
    base.update({k: str(v) for k, v in kwargs.items()})
    return base


# ---------------------------------------------------------------------------
# decide_change_type — closed-taxonomy decision matrix
# ---------------------------------------------------------------------------

def test_high_conf_misrouted_with_consistent_sender_and_count_picks_routing_rule():
    ck = {
        "email_sender": "billing@valley.com",
        "classification_method": "ai_classifier:gpt-4o",
        "current_mailbox_category": "Operations",
        "current_doc_type": "AP_INVOICE",
        "current_suggested_job_type": "AP_Invoice",
        "sharepoint_folder_root": "Operations",
    }
    change_type, _ = ba.decide_change_type(
        ck, "high_confidence_AP_invoice_misrouted", 0.94, 5)
    assert change_type == "routing_rule_addition"


def test_high_conf_misrouted_with_thin_sender_picks_one_shot_data_patch():
    ck = {
        "email_sender": "",
        "classification_method": "ai_classifier:gpt-4o",
        "current_mailbox_category": "Operations",
        "current_doc_type": "AP_INVOICE",
        "current_suggested_job_type": "AP_Invoice",
        "sharepoint_folder_root": "Operations",
    }
    change_type, _ = ba.decide_change_type(
        ck, "high_confidence_AP_invoice_misrouted", 0.95, 7)
    assert change_type == "one_shot_data_patch"


def test_sales_capture_with_mailbox_classifier_picks_routing_rule():
    ck = {
        "email_sender": "ar@xyz.com",
        "classification_method": "mailbox:SALES",
        "current_mailbox_category": "SALES",
        "current_doc_type": "SALES_INVOICE",
        "current_suggested_job_type": "AR_Invoice",
        "sharepoint_folder_root": "Sales",
    }
    change_type, _ = ba.decide_change_type(
        ck, "sales_mailbox_captured_AP_invoice", 0.75, 5)
    assert change_type == "routing_rule_addition"


def test_sales_capture_with_ai_classifier_picks_signal_uplift():
    ck = {
        "email_sender": "ar@xyz.com",
        "classification_method": "ai_classifier:gpt-4o",
        "current_mailbox_category": "SALES",
        "current_doc_type": "SALES_INVOICE",
        "current_suggested_job_type": "AR_Invoice",
        "sharepoint_folder_root": "Sales",
    }
    change_type, _ = ba.decide_change_type(
        ck, "sales_mailbox_captured_AP_invoice", 0.75, 5)
    assert change_type == "classifier_signal_uplift"


def test_operations_capture_picks_signal_uplift():
    ck = {
        "email_sender": "ops@xyz.com",
        "classification_method": "ai_classifier:gpt-4o",
        "current_mailbox_category": "Operations",
        "current_doc_type": "Shipping_Document",
        "current_suggested_job_type": "Shipping_Document",
        "sharepoint_folder_root": "Operations",
    }
    change_type, _ = ba.decide_change_type(
        ck, "operations_mailbox_captured_AP_invoice", 0.65, 4)
    assert change_type == "classifier_signal_uplift"


def test_non_ap_doc_picks_manual_review():
    ck = {
        "email_sender": "",
        "classification_method": "",
        "current_mailbox_category": "Other",
        "current_doc_type": "OTHER",
        "current_suggested_job_type": "Remittance",
        "sharepoint_folder_root": "Other",
    }
    change_type, _ = ba.decide_change_type(
        ck, "square9_ap_folder_contains_non_ap_document", 0.0, 1)
    assert change_type == "manual_review"


def test_low_confidence_picks_manual_review():
    ck = {
        "email_sender": "x@y.com",
        "classification_method": "ai_classifier:gpt-4o",
        "current_mailbox_category": "AP",
        "current_doc_type": "AP_INVOICE",
        "current_suggested_job_type": "AP_Invoice",
        "sharepoint_folder_root": "AP",
    }
    change_type, _ = ba.decide_change_type(
        ck, "low_confidence_match_ambiguous", 0.42, 3)
    assert change_type == "manual_review"


# ---------------------------------------------------------------------------
# Confidence band buckets
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("score,expected", [
    (0.95, "high"), (0.90, "high"), (0.89, "medium"),
    (0.60, "medium"), (0.59, "low"), (0.0, "low"),
])
def test_confidence_band_thresholds(score, expected):
    assert ba._confidence_band(score) == expected


# ---------------------------------------------------------------------------
# build_cohort produces complete shape
# ---------------------------------------------------------------------------

def test_build_cohort_shape_and_proposed_target():
    members = [
        _row(best_hub_doc_id="d1", best_match_score="0.95",
             root_cause="high_confidence_AP_invoice_misrouted",
             square9_parent_root="Temp Folder/S&H Invoices Approved"),
        _row(best_hub_doc_id="d2", best_match_score="0.90",
             root_cause="high_confidence_AP_invoice_misrouted",
             square9_parent_root="Temp Folder/S&H Invoices Approved"),
        _row(best_hub_doc_id="d3", best_match_score="0.92",
             root_cause="high_confidence_AP_invoice_misrouted",
             square9_parent_root="Temp Folder/S&H Invoices Approved"),
    ]
    ck = ba._row_to_cohort_key(members[0])
    c = ba.build_cohort(members, ck)
    assert c["affected_doc_count"] == 3
    assert c["confidence_band"] == "high"
    assert c["proposed_mailbox_category"] == "AP"
    assert c["proposed_doc_type"] == "AP_INVOICE"
    assert c["proposed_suggested_job_type"] == "AP_Invoice"
    assert c["change_type"] == "routing_rule_addition"
    assert c["dominant_root_cause"] == "high_confidence_AP_invoice_misrouted"
    assert len(c["evidence_sample"]) == 3
    assert {e["best_hub_doc_id"] for e in c["evidence_sample"]} == \
        {"d1", "d2", "d3"}


# ---------------------------------------------------------------------------
# analyze() — actionable vs manual_review separation
# ---------------------------------------------------------------------------

def test_analyze_partitions_actionable_and_manual_review():
    rows: List[Dict[str, str]] = []
    # Actionable: 4 rows, high-score, sender consistent
    for i in range(4):
        rows.append(_row(best_hub_doc_id=f"a{i}", best_match_score="0.92"))
    # Manual review: low-confidence cohort
    for i in range(3):
        rows.append(_row(
            best_hub_doc_id=f"m{i}",
            best_match_score="0.42",
            root_cause="low_confidence_match_ambiguous",
            email_sender="other@example.com",
        ))
    # Singleton (cohort below min_cohort=2)
    rows.append(_row(
        best_hub_doc_id="s1",
        best_match_score="0.97",
        email_sender="solo@solo.com",
        classification_method="ai_classifier:gpt-4o",
    ))

    result = ba.analyze(rows, min_cohort=2, min_score=0.60)
    assert result["total_bucket_A_rows"] == 8
    assert result["cohort_count_actionable"] == 1
    assert result["cohort_count_manual_review"] == 2
    assert result["actionable_doc_count"] == 4
    assert result["manual_review_doc_count"] == 4

    actionable = result["actionable_cohorts"][0]
    assert actionable["affected_doc_count"] == 4
    assert actionable["change_type"] in (
        "routing_rule_addition",
        "one_shot_data_patch",
    )


def test_analyze_empty_input_returns_empty_plan():
    result = ba.analyze([])
    assert result["total_bucket_A_rows"] == 0
    assert result["cohort_count_total"] == 0
    assert result["cohort_count_actionable"] == 0
    assert result["actionable_cohorts"] == []
    assert result["manual_review_cohorts"] == []


def test_analyze_min_score_excludes_low_avg_cohorts():
    rows = [
        _row(best_hub_doc_id=f"a{i}", best_match_score="0.65")
        for i in range(3)
    ]
    rows += [
        _row(best_hub_doc_id=f"b{i}", best_match_score="0.40",
             email_sender="ambig@x.com")
        for i in range(3)
    ]
    result = ba.analyze(rows, min_cohort=2, min_score=0.70)
    assert result["cohort_count_actionable"] == 0
    assert result["cohort_count_manual_review"] == 2


# ---------------------------------------------------------------------------
# Cohort grouping is deterministic & evidence-bounded
# ---------------------------------------------------------------------------

def test_cohort_grouping_uses_documented_keys():
    base = _row(best_match_score="0.92")
    rows = [base, dict(base, best_hub_doc_id="d2"),
            dict(base, best_hub_doc_id="d3")]
    result = ba.analyze(rows, min_cohort=2, min_score=0.60)
    # All 3 docs should land in a single cohort with count=3
    assert result["cohort_count_total"] == 1
    assert result["actionable_cohorts"][0]["affected_doc_count"] == 3


def test_evidence_sample_is_capped_at_three():
    rows = [
        _row(best_hub_doc_id=f"d{i}", best_match_score="0.92")
        for i in range(10)
    ]
    result = ba.analyze(rows, min_cohort=2, min_score=0.60)
    assert len(result["actionable_cohorts"][0]["evidence_sample"]) == 3


# ---------------------------------------------------------------------------
# IO round-trip & exit codes
# ---------------------------------------------------------------------------

def _write_input_csv(path: str, rows: List[Dict[str, str]]) -> None:
    keys = list(rows[0].keys()) if rows else [
        "root_cause", "best_hub_doc_id", "best_match_score",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_io_round_trip_actionable_path(tmp_path):
    rows = [
        _row(best_hub_doc_id=f"a{i}", best_match_score="0.92")
        for i in range(3)
    ]
    in_csv = tmp_path / "in.csv"
    _write_input_csv(str(in_csv), rows)
    loaded = ba.load_bucket_A_rows(str(in_csv))
    assert len(loaded) == 3
    result = ba.analyze(loaded)
    out_csv = tmp_path / "plan.csv"
    out_json = tmp_path / "plan.json"
    out_yaml = tmp_path / "plan.yaml"
    ba.write_csv(str(out_csv), result)
    ba.write_json(str(out_json), result)
    ba.write_yaml(str(out_yaml), result)
    assert os.path.exists(out_csv)
    assert os.path.exists(out_json)
    assert os.path.exists(out_yaml)

    # CSV: header + 1 actionable cohort row
    with open(out_csv, encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert len(reader) == 1
    assert reader[0]["section"] == "actionable"
    assert reader[0]["proposed_mailbox_category"] == "AP"
    assert int(reader[0]["affected_doc_count"]) == 3

    # JSON shape
    payload = json.loads(out_json.read_text())
    assert payload["cohort_count_actionable"] == 1
    assert ba._exit_code(result) == 2


def test_exit_code_zero_on_empty_input(tmp_path):
    in_csv = tmp_path / "empty.csv"
    in_csv.write_text("root_cause,best_hub_doc_id,best_match_score\n")
    rows = ba.load_bucket_A_rows(str(in_csv))
    assert rows == []
    result = ba.analyze(rows)
    assert ba._exit_code(result) == 0


def test_exit_code_one_when_rows_present_but_no_actionable(tmp_path):
    rows = [
        _row(best_hub_doc_id="d1", best_match_score="0.30",
             root_cause="low_confidence_match_ambiguous")
    ]
    result = ba.analyze(rows)
    assert ba._exit_code(result) == 1


# ---------------------------------------------------------------------------
# Read-only / no-mutation guardrail (source-inspection)
# ---------------------------------------------------------------------------

def test_module_does_not_import_pymongo_or_motor():
    import inspect
    src = inspect.getsource(ba)
    assert "from pymongo" not in src
    assert "import pymongo" not in src
    assert "from motor" not in src
    assert "MongoClient" not in src


def test_module_makes_no_mutating_http_calls():
    import inspect
    src = inspect.getsource(ba)
    forbidden = ("requests.post", "requests.put", "requests.delete",
                 "requests.patch", "httpx.post", "httpx.put",
                 "httpx.delete", "httpx.patch")
    for tok in forbidden:
        assert tok not in src
