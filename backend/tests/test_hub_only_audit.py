"""Tests for hub_only_audit (read-only, fixture-driven)."""
from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts import hub_only_audit as hoa


# ---------------------------------------------------------------------------
# Row factory matching square9_hub_ap_parity._row_hub_only output shape
# ---------------------------------------------------------------------------

def _hub_only_row(**overrides) -> Dict[str, str]:
    base = {
        "match_bucket": "hub_only",
        "match_score": "0.0",
        "match_reason": "no_square9_counterpart",
        "square9_name": "",
        "square9_parent_path": "",
        "square9_modified": "",
        "square9_web_url": "",
        "hub_doc_id": "doc-1",
        "hub_file_name": "invoice-1.pdf",
        "hub_sharepoint_web_url": "",
        "hub_sharepoint_folder_path": "AP/Inbox/Vendor",
        "hub_routing_status": "auto_process",
        "hub_routing_reason": "",
        "hub_doc_type": "AP_INVOICE",
        "hub_suggested_job_type": "AP_Invoice",
        "hub_classification_method": "ai_classifier:gpt-4o",
        "hub_vendor_canonical": "Acme Corp",
        "hub_invoice_number_clean": "INV-12345",
        "hub_amount_float": "150.00",
        "hub_po_number_clean": "",
        "hub_email_sender": "billing@acme.com",
        "hub_email_subject": "Invoice INV-12345",
        "hub_created_utc": "2026-04-01T10:00:00+00:00",
    }
    base.update({k: ("" if v is None else str(v)) for k, v in overrides.items()})
    return base


# ---------------------------------------------------------------------------
# classify_doc — one test per bucket
# ---------------------------------------------------------------------------

def _classify(row, window_start=None):
    return hoa.classify_doc(
        row,
        sender_filename_counts={},
        window_start=window_start,
    )


def test_non_ap_in_ap_scope_when_doc_type_is_not_AP():
    row = _hub_only_row(hub_doc_type="SALES_ORDER",
                        hub_suggested_job_type="Sales_Order")
    bucket, _ = _classify(row)
    assert bucket == "non_ap_in_ap_scope"


def test_matcher_miss_when_strong_identity_signals_present():
    row = _hub_only_row(
        hub_vendor_canonical="Acme Corp",
        hub_invoice_number_clean="INV-99",
        hub_amount_float="42.50",
        hub_classification_method="ai_classifier:gpt-4o",
        hub_sharepoint_folder_path="AP/Inbox/Acme",
    )
    bucket, reason = _classify(row)
    assert bucket == "matcher_miss"
    assert "INV-99" in reason


def test_square9_scope_gap_when_outside_AP_folder_and_no_strong_signals():
    """Real AP doc in a non-AP folder with weak identity -> scope gap."""
    row = _hub_only_row(
        hub_vendor_canonical="",
        hub_invoice_number_clean="",
        hub_amount_float="",
        hub_sharepoint_folder_path="Operations/Inbox",
        hub_classification_method="email_subject_heuristic",
    )
    bucket, reason = _classify(row)
    assert bucket == "square9_scope_gap"
    assert "Operations/Inbox" in reason


def test_true_hub_extra_when_classification_method_is_hub_only_lane():
    row = _hub_only_row(
        hub_vendor_canonical="",
        hub_invoice_number_clean="",
        hub_amount_float="",
        hub_classification_method="manual_upload",
        hub_sharepoint_folder_path="Operations/Manual",
    )
    bucket, reason = _classify(row)
    assert bucket == "true_hub_extra"
    assert "manual_upload" in reason


def test_duplicate_or_backlog_when_created_predates_window_start():
    row = _hub_only_row(hub_created_utc="2025-01-01T00:00:00+00:00")
    bucket, reason = _classify(row, window_start=dt.datetime(
        2026, 1, 1, tzinfo=dt.timezone.utc))
    assert bucket == "duplicate_or_backlog_artifact"
    assert "predates parity window" in reason


def test_duplicate_artifact_when_same_sender_filename_seen_twice():
    rows = [
        _hub_only_row(hub_doc_id="d1",
                      hub_email_sender="x@y.com",
                      hub_file_name="dup.pdf",
                      hub_vendor_canonical="",
                      hub_invoice_number_clean="",
                      hub_amount_float=""),
        _hub_only_row(hub_doc_id="d2",
                      hub_email_sender="x@y.com",
                      hub_file_name="dup.pdf",
                      hub_vendor_canonical="",
                      hub_invoice_number_clean="",
                      hub_amount_float=""),
    ]
    classified = hoa.classify_all(rows, window_start=None)
    assert classified[0]["audit_bucket"] == "duplicate_or_backlog_artifact"
    assert classified[1]["audit_bucket"] == "duplicate_or_backlog_artifact"
    assert all("duplicate filename" in c["audit_reason"] for c in classified)


def test_uncertain_when_AP_in_AP_folder_but_identity_signals_missing():
    row = _hub_only_row(
        hub_vendor_canonical="",
        hub_invoice_number_clean="",
        hub_amount_float="",
        hub_sharepoint_folder_path="AP/Inbox/Acme",
        hub_classification_method="ai_classifier:gpt-4o",
    )
    bucket, reason = _classify(row)
    assert bucket == "uncertain"
    assert "manual review" in reason


# ---------------------------------------------------------------------------
# classify_all + cohort_summary + decide_exit_code
# ---------------------------------------------------------------------------

def _mixed_population() -> List[Dict[str, str]]:
    """Population dominated by non_ap_in_ap_scope (>=10%) so the
    significant-gap exit code triggers."""
    rows: List[Dict[str, str]] = []
    # 5 non_ap docs (50%)
    for i in range(5):
        rows.append(_hub_only_row(
            hub_doc_id=f"nonap-{i}",
            hub_file_name=f"nonap-{i}.pdf",
            hub_doc_type="SALES_ORDER",
            hub_suggested_job_type="Sales_Order",
            hub_email_sender="sales@x.com",
        ))
    # 3 true_hub_extra
    for i in range(3):
        rows.append(_hub_only_row(
            hub_doc_id=f"extra-{i}",
            hub_file_name=f"extra-{i}.pdf",
            hub_classification_method="manual_upload",
            hub_vendor_canonical="",
            hub_invoice_number_clean="",
            hub_amount_float="",
        ))
    # 2 matcher_miss
    for i in range(2):
        rows.append(_hub_only_row(
            hub_doc_id=f"miss-{i}",
            hub_file_name=f"miss-{i}.pdf",
            hub_invoice_number_clean=f"INV-{i}",
        ))
    return rows


def test_classify_all_assigns_recommended_action_for_each_bucket():
    classified = hoa.classify_all(_mixed_population())
    actions = {c["audit_bucket"]: c["recommended_action"]
               for c in classified}
    assert actions["non_ap_in_ap_scope"] == hoa.ACTION_FIX_AP_SCOPE
    assert actions["true_hub_extra"] == hoa.ACTION_NO_ACTION
    assert actions["matcher_miss"] == hoa.ACTION_IMPROVE_MATCHER


def test_cohort_summary_emits_top_senders_and_buckets():
    classified = hoa.classify_all(_mixed_population())
    summary = hoa.cohort_summary(classified)
    assert summary["total_hub_only"] == 10
    assert summary["bucket_counts"]["non_ap_in_ap_scope"] == 5
    assert summary["bucket_counts"]["true_hub_extra"] == 3
    assert summary["bucket_counts"]["matcher_miss"] == 2
    # Top sender should include sales@x.com (5 hits).
    senders = dict(summary["top_senders"])
    assert senders["sales@x.com"] == 5


def test_decide_exit_code_significant_gap_when_non_ap_over_threshold():
    classified = hoa.classify_all(_mixed_population())
    summary = hoa.cohort_summary(classified)
    assert hoa.decide_exit_code(summary) == hoa.EXIT_SIGNIFICANT_GAP


def test_decide_exit_code_ok_when_population_is_clean():
    rows = [_hub_only_row(
        hub_doc_id=f"extra-{i}",
        hub_file_name=f"extra-{i}.pdf",
        hub_classification_method="manual_upload",
        hub_vendor_canonical="",
        hub_invoice_number_clean="",
        hub_amount_float="",
    ) for i in range(20)]
    classified = hoa.classify_all(rows)
    summary = hoa.cohort_summary(classified)
    assert hoa.decide_exit_code(summary) == hoa.EXIT_OK


def test_decide_exit_code_uncertain_when_uncertain_over_threshold():
    rows: List[Dict[str, str]] = []
    # 19 explainable (true_hub_extra) + 3 uncertain. 3/22 ≈ 13.6% > 10%.
    for i in range(19):
        rows.append(_hub_only_row(
            hub_doc_id=f"extra-{i}",
            hub_file_name=f"extra-{i}.pdf",
            hub_classification_method="manual_upload",
            hub_vendor_canonical="",
            hub_invoice_number_clean="",
            hub_amount_float="",
        ))
    for i in range(3):
        rows.append(_hub_only_row(
            hub_doc_id=f"u-{i}",
            hub_file_name=f"u-{i}.pdf",
            hub_vendor_canonical="",
            hub_invoice_number_clean="",
            hub_amount_float="",
            hub_sharepoint_folder_path="AP/Inbox/Acme",
            hub_classification_method="ai_classifier:gpt-4o",
        ))
    classified = hoa.classify_all(rows)
    summary = hoa.cohort_summary(classified)
    assert hoa.decide_exit_code(summary) == hoa.EXIT_UNCERTAIN


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def test_filter_hub_only_drops_non_hub_only_rows():
    rows = [
        {"match_bucket": "hub_only", "hub_doc_id": "a"},
        {"match_bucket": "exact_match", "hub_doc_id": "b"},
        {"match_bucket": "no_match", "hub_doc_id": "c"},
    ]
    out = hoa.filter_hub_only(rows)
    assert [r["hub_doc_id"] for r in out] == ["a"]


def test_find_latest_parity_csv_prefers_proof_pack_dir(tmp_path: Path):
    older = tmp_path / "cutover_proof_2026-01-01T00-00-00Z"
    newer = tmp_path / "cutover_proof_2026-05-08T04-11-24Z"
    older.mkdir()
    newer.mkdir()
    (older / "square9_hub_ap_parity.csv").write_text("match_bucket\n")
    (newer / "square9_hub_ap_parity.csv").write_text("match_bucket\n")
    found = hoa.find_latest_parity_csv(base_dir=str(tmp_path))
    assert found is not None
    assert found.endswith("2026-05-08T04-11-24Z/square9_hub_ap_parity.csv")


def test_find_latest_parity_csv_falls_back_to_static(tmp_path: Path):
    fallback = tmp_path / "square9_hub_ap_parity.csv"
    fallback.write_text("match_bucket\n")
    found = hoa.find_latest_parity_csv(base_dir=str(tmp_path))
    assert found == str(fallback)


def test_find_latest_parity_csv_returns_none_when_missing(tmp_path: Path):
    assert hoa.find_latest_parity_csv(base_dir=str(tmp_path)) is None


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def test_write_csv_emits_classification_columns(tmp_path: Path):
    classified = hoa.classify_all(_mixed_population())
    out = tmp_path / "hub_only_audit.csv"
    hoa.write_csv(str(out), classified)
    with open(out, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 10
    assert "audit_bucket" in rows[0]
    assert "audit_reason" in rows[0]
    assert "recommended_action" in rows[0]


def test_write_json_emits_buckets_and_top_lists(tmp_path: Path):
    classified = hoa.classify_all(_mixed_population())
    summary = hoa.cohort_summary(classified)
    out = tmp_path / "hub_only_audit.json"
    hoa.write_json(str(out), summary, "fake.csv", exit_code=2)
    payload = json.loads(out.read_text())
    assert payload["exit_code"] == 2
    assert payload["source_csv"] == "fake.csv"
    assert payload["total_hub_only"] == 10
    assert "bucket_counts" in payload
    assert "top_senders" in payload
    assert "top_folder_roots" in payload
    assert "matcher_miss_top" in payload
    assert "non_ap_top" in payload


def test_write_md_renders_table_per_bucket(tmp_path: Path):
    classified = hoa.classify_all(_mixed_population())
    summary = hoa.cohort_summary(classified)
    out = tmp_path / "hub_only_audit.md"
    hoa.write_md(str(out), summary, "fake.csv", exit_code=2)
    text = out.read_text()
    assert "# Hub-only audit" in text
    assert "## Classification breakdown" in text
    for bucket in hoa.BUCKET_ORDER:
        assert bucket in text
    # Recommended actions appear in the breakdown table.
    assert hoa.ACTION_IMPROVE_MATCHER in text
    assert hoa.ACTION_FIX_AP_SCOPE in text
    assert hoa.ACTION_NO_ACTION in text


# ---------------------------------------------------------------------------
# CLI smoke (writes to tmp paths)
# ---------------------------------------------------------------------------

def test_main_emits_three_artifacts_and_returns_exit_code(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    parity = tmp_path / "square9_hub_ap_parity.csv"
    fieldnames = list(_hub_only_row().keys())
    rows = _mixed_population()
    with open(parity, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    csv_out = tmp_path / "out.csv"
    json_out = tmp_path / "out.json"
    md_out = tmp_path / "out.md"

    monkeypatch.setattr("sys.argv", [
        "hub_only_audit.py",
        "--parity-csv", str(parity),
        "--csv-out", str(csv_out),
        "--json-out", str(json_out),
        "--md-out", str(md_out),
    ])
    rc = hoa.main()
    assert rc == hoa.EXIT_SIGNIFICANT_GAP
    assert csv_out.exists()
    assert json_out.exists()
    assert md_out.exists()
    payload = json.loads(json_out.read_text())
    assert payload["exit_code"] == hoa.EXIT_SIGNIFICANT_GAP
    assert payload["total_hub_only"] == 10
