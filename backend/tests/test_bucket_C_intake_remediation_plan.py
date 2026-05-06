"""Tests for bucket_C_intake_remediation_plan."""
from __future__ import annotations

import csv
import json
import os
from typing import Dict, List

from scripts import bucket_C_intake_remediation_plan as bc


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

def _row(**kwargs) -> Dict[str, str]:
    base = {
        "square9_name": "FedEx 042926 9-275-62775.pdf",
        "square9_parent_path": "Temp Folder/Misc Invoices",
        "square9_parent_root": "Temp Folder/Misc Invoices",
        "square9_modified": "2026-04-29",
        "filename_pattern": "FEDEX PDF",
        "likely_vendor": "FedEx",
        "date_token": "042926",
        "invoice_token": "9275",
        "doc_type_guess": "ap_invoice_candidate",
        "candidate_intake_channel": "fedex_billing_email",
        "recommended_action": "add_fedex_sender_to_AP_intake",
        "is_parity_exclusion": "False",
    }
    base.update({k: str(v) for k, v in kwargs.items()})
    return base


# ---------------------------------------------------------------------------
# Channel taxonomy
# ---------------------------------------------------------------------------

def test_recommend_for_known_email_channel_owner_it():
    rec, owner = bc.recommend_for_channel("fedex_billing_email")
    assert rec == "add_sender_to_AP_transport_rule"
    assert owner == "IT"


def test_recommend_for_portal_channel_owner_ap():
    rec, owner = bc.recommend_for_channel("cogent_billing_portal")
    assert rec == "enable_portal_download"
    assert owner == "AP"


def test_recommend_for_unknown_channel_falls_back_to_manual():
    rec, owner = bc.recommend_for_channel("unmapped_channel", "")
    assert rec == "manual_followup"
    assert owner == "AP"


def test_recommend_uses_fallback_action_to_infer_change():
    rec, owner = bc.recommend_for_channel(
        "totally_unknown", "add_someone_sender_to_AP_intake")
    assert rec == "add_sender_to_AP_transport_rule"
    assert owner == "IT"

    rec, owner = bc.recommend_for_channel(
        "another_unknown", "confirm_acme_sender_in_AP_flow")
    assert rec == "forward_billing_alias_to_hub_ap_intake"
    assert owner == "AP"


# ---------------------------------------------------------------------------
# Exclusion vs intake gap row classification
# ---------------------------------------------------------------------------

def test_is_exclusion_true_for_explicit_flag():
    assert bc._is_exclusion({"is_parity_exclusion": "True"}) is True
    assert bc._is_exclusion({"is_parity_exclusion": "TRUE"}) is True
    assert bc._is_exclusion({"is_parity_exclusion": "1"}) is True


def test_is_exclusion_false_for_intake_gap_row():
    assert bc._is_exclusion(_row()) is False


def test_is_exclusion_falls_back_to_channel_when_flag_blank():
    row = {"is_parity_exclusion": "",
           "candidate_intake_channel": "not_expected_in_hub"}
    assert bc._is_exclusion(row) is True


# ---------------------------------------------------------------------------
# Cohort building
# ---------------------------------------------------------------------------

def test_build_intake_cohort_carries_recommendation():
    members = [_row(square9_name=f"FedEx_{i}.pdf") for i in range(3)]
    ck = {
        "likely_vendor": "FedEx",
        "candidate_intake_channel": "fedex_billing_email",
    }
    c = bc.build_intake_cohort(members, ck)
    assert c["section"] == "intake_channel_changes"
    assert c["affected_doc_count"] == 3
    assert c["current_arrival_channel"] == "none"
    assert c["recommended_intake_change"] == "add_sender_to_AP_transport_rule"
    assert c["owner_hint"] == "IT"
    assert len(c["evidence_sample"]) == 3


def test_build_exclusion_cohort_carries_exclusion_action():
    members = [_row(
        square9_name="GP Check Template.xlsx",
        candidate_intake_channel="not_expected_in_hub",
        doc_type_guess="template_or_form",
        is_parity_exclusion="True",
    ) for _ in range(2)]
    ck = {"doc_type_guess": "template_or_form"}
    c = bc.build_exclusion_cohort(members, ck)
    assert c["section"] == "parity_exclusions"
    assert c["affected_doc_count"] == 2
    assert c["recommended_intake_change"] == "exclude_from_parity_denominator"
    assert c["exclusion_reason"] == "template_or_form"


# ---------------------------------------------------------------------------
# analyze() — partitions exclusions vs intake-channel-changes
# ---------------------------------------------------------------------------

def test_analyze_separates_exclusions_from_intake_gaps():
    rows: List[Dict[str, str]] = []
    # 3 FedEx intake-channel-change rows
    for i in range(3):
        rows.append(_row(
            square9_name=f"FedEx_{i}.pdf",
            likely_vendor="FedEx",
            candidate_intake_channel="fedex_billing_email",
            is_parity_exclusion="False",
        ))
    # 2 OIPkgSol intake gap rows
    for i in range(2):
        rows.append(_row(
            square9_name=f"OIPkgSol_{i}.pdf",
            likely_vendor="OIPkgSol",
            candidate_intake_channel="oi_packaging_solutions_email",
            recommended_action="add_oi_pkg_sender_to_AP_intake",
            is_parity_exclusion="False",
        ))
    # 4 PST exclusions
    for i in range(4):
        rows.append(_row(
            square9_name=f"OrderIssues_{i}.pst",
            likely_vendor="",
            candidate_intake_channel="not_expected_in_hub",
            doc_type_guess="outlook_export",
            recommended_action="exclude_from_parity_denominator",
            is_parity_exclusion="True",
        ))
    # 2 template exclusions
    for i in range(2):
        rows.append(_row(
            square9_name=f"Template_{i}.xlsx",
            likely_vendor="",
            candidate_intake_channel="not_expected_in_hub",
            doc_type_guess="template_or_form",
            recommended_action="exclude_from_parity_denominator",
            is_parity_exclusion="True",
        ))

    result = bc.analyze(rows)
    assert result["total_bucket_C_rows"] == 11
    assert result["parity_exclusion_row_count"] == 6
    assert result["real_intake_gap_row_count"] == 5
    assert result["intake_channel_change_cohort_count"] == 2
    assert result["parity_exclusion_cohort_count"] == 2

    # Sorted by affected_doc_count desc
    intakes = result["intake_channel_changes"]
    assert intakes[0]["affected_doc_count"] == 3
    assert intakes[0]["cohort_key"]["likely_vendor"] == "FedEx"
    exclusions = result["parity_exclusions"]
    assert exclusions[0]["affected_doc_count"] == 4
    assert exclusions[0]["exclusion_reason"] == "outlook_export"


def test_analyze_empty_input_returns_zero_counts():
    result = bc.analyze([])
    assert result["total_bucket_C_rows"] == 0
    assert result["intake_channel_change_cohort_count"] == 0
    assert result["parity_exclusion_cohort_count"] == 0


def test_analyze_grouping_is_deterministic():
    rows = [
        _row(likely_vendor="FedEx",
             candidate_intake_channel="fedex_billing_email"),
        _row(likely_vendor="FedEx",
             candidate_intake_channel="fedex_billing_email"),
    ]
    r1 = bc.analyze(rows)
    r2 = bc.analyze(list(rows))
    assert r1["intake_channel_change_cohort_count"] == \
        r2["intake_channel_change_cohort_count"]
    assert r1["intake_channel_changes"][0]["affected_doc_count"] == 2


# ---------------------------------------------------------------------------
# IO round-trip & exit codes
# ---------------------------------------------------------------------------

def _write_input_csv(path: str, rows: List[Dict[str, str]]) -> None:
    keys = list(rows[0].keys()) if rows else ["square9_name"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_io_round_trip_emits_two_sections(tmp_path):
    rows = [
        _row(square9_name=f"FedEx_{i}.pdf") for i in range(3)
    ] + [
        _row(square9_name=f"Template_{i}.xlsx",
             likely_vendor="",
             candidate_intake_channel="not_expected_in_hub",
             doc_type_guess="template_or_form",
             is_parity_exclusion="True") for i in range(2)
    ]
    in_csv = tmp_path / "in.csv"
    _write_input_csv(str(in_csv), rows)
    loaded = bc.load_bucket_C_rows(str(in_csv))
    assert len(loaded) == 5
    result = bc.analyze(loaded)
    out_csv = tmp_path / "plan.csv"
    out_json = tmp_path / "plan.json"
    out_yaml = tmp_path / "plan.yaml"
    bc.write_csv(str(out_csv), result)
    bc.write_json(str(out_json), result)
    bc.write_yaml(str(out_yaml), result)
    assert os.path.exists(out_csv)
    assert os.path.exists(out_json)
    assert os.path.exists(out_yaml)

    with open(out_csv, encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    sections = {r["section"] for r in reader}
    assert sections == {"intake_channel_changes", "parity_exclusions"}

    payload = json.loads(out_json.read_text())
    assert payload["intake_channel_change_cohort_count"] == 1
    assert payload["parity_exclusion_cohort_count"] == 1
    assert bc._exit_code(result) == 2


def test_exit_code_zero_on_empty_input(tmp_path):
    in_csv = tmp_path / "empty.csv"
    in_csv.write_text("square9_name,is_parity_exclusion\n")
    rows = bc.load_bucket_C_rows(str(in_csv))
    assert rows == []
    result = bc.analyze(rows)
    assert bc._exit_code(result) == 0


def test_exit_code_one_when_only_exclusions(tmp_path):
    rows = [
        _row(square9_name=f"OrderIssues_{i}.pst",
             likely_vendor="",
             candidate_intake_channel="not_expected_in_hub",
             doc_type_guess="outlook_export",
             is_parity_exclusion="True")
        for i in range(2)
    ]
    result = bc.analyze(rows)
    assert bc._exit_code(result) == 1
    assert result["intake_channel_change_cohort_count"] == 0
    assert result["parity_exclusion_cohort_count"] == 1


def test_csv_top_parent_root_is_populated_for_intake_cohort(tmp_path):
    rows = [_row(square9_parent_root="Temp Folder/Misc Invoices")
            for _ in range(2)]
    result = bc.analyze(rows)
    out_csv = tmp_path / "plan.csv"
    bc.write_csv(str(out_csv), result)
    with open(out_csv, encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    intake_row = [r for r in reader if r["section"] == "intake_channel_changes"][0]
    assert intake_row["top_parent_root"] == "Temp Folder/Misc Invoices"


# ---------------------------------------------------------------------------
# Read-only / no-mutation guardrail (source-inspection)
# ---------------------------------------------------------------------------

def test_module_does_not_import_pymongo_or_motor():
    import inspect
    src = inspect.getsource(bc)
    assert "from pymongo" not in src
    assert "import pymongo" not in src
    assert "from motor" not in src
    assert "MongoClient" not in src


def test_module_makes_no_mutating_http_calls():
    import inspect
    src = inspect.getsource(bc)
    forbidden = ("requests.post", "requests.put", "requests.delete",
                 "requests.patch", "httpx.post", "httpx.put",
                 "httpx.delete", "httpx.patch")
    for tok in forbidden:
        assert tok not in src
