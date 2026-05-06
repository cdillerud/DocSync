"""Tests for bucket_A_one_shot_data_patch_dryrun (read-only, synthetic)."""
from __future__ import annotations

import csv
import json
from typing import Any, Dict

import pytest  # noqa: F401  (kept for fixture extension consistency)

from scripts import bucket_A_one_shot_data_patch_dryrun as ba_patch


# ---------------------------------------------------------------------------
# Synthetic fixtures (no Mongo, no live VM)
# ---------------------------------------------------------------------------

def _row(**kw) -> Dict[str, str]:
    base = {
        "best_hub_doc_id": "doc-1",
        "best_hub_file_name": "valley_invoice.pdf",
        "best_hub_mailbox_category": "Operations",
        "best_hub_doc_type": "AP_INVOICE",
        "best_hub_suggested_job_type": "AP_Invoice",
        "classification_method": "ai_classifier:gpt-4o",
        "sharepoint_folder_root": "Operations",
        "email_sender": "billing@valley.com",
        "best_match_score": "0.95",
        "root_cause": "high_confidence_AP_invoice_misrouted",
    }
    base.update({k: str(v) for k, v in kw.items()})
    return base


def _cohort(change_type: str = "one_shot_data_patch",
            **ck_overrides) -> Dict[str, Any]:
    ck = {
        "email_sender": "billing@valley.com",
        "classification_method": "ai_classifier:gpt-4o",
        "current_mailbox_category": "Operations",
        "current_doc_type": "AP_INVOICE",
        "current_suggested_job_type": "AP_Invoice",
        "sharepoint_folder_root": "Operations",
    }
    ck.update(ck_overrides)
    return {
        "cohort_key": ck,
        "affected_doc_count": 3,
        "avg_score": 0.94,
        "confidence_band": "high",
        "dominant_root_cause": "high_confidence_AP_invoice_misrouted",
        "change_type": change_type,
    }


def _plan(*cohorts: Dict[str, Any]) -> Dict[str, Any]:
    return {"actionable_cohorts": list(cohorts)}


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def test_select_one_shot_cohorts_filters_change_type():
    plan = _plan(
        _cohort("one_shot_data_patch"),
        _cohort("routing_rule_addition"),
        _cohort("classifier_signal_uplift"),
    )
    out = ba_patch.select_one_shot_cohorts(plan)
    assert len(out) == 1
    assert out[0]["change_type"] == "one_shot_data_patch"


def test_select_one_shot_cohorts_handles_missing_field():
    assert ba_patch.select_one_shot_cohorts({}) == []
    assert ba_patch.select_one_shot_cohorts({"actionable_cohorts": []}) == []


# ---------------------------------------------------------------------------
# Cohort-key matching
# ---------------------------------------------------------------------------

def test_row_matches_cohort_key_exact_match():
    ck = _cohort()["cohort_key"]
    assert ba_patch.row_matches_cohort_key(_row(), ck)


def test_row_matches_cohort_key_normalises_whitespace():
    ck = _cohort()["cohort_key"]
    assert ba_patch.row_matches_cohort_key(
        _row(email_sender="  billing@valley.com  "), ck)


def test_row_does_not_match_when_sender_differs():
    ck = _cohort()["cohort_key"]
    assert not ba_patch.row_matches_cohort_key(
        _row(email_sender="someone-else@valley.com"), ck)


def test_row_does_not_match_when_classification_method_differs():
    ck = _cohort()["cohort_key"]
    assert not ba_patch.row_matches_cohort_key(
        _row(classification_method="mailbox:Operations"), ck)


# ---------------------------------------------------------------------------
# update_one preview shape
# ---------------------------------------------------------------------------

def test_build_update_preview_sets_three_fields_plus_audit():
    ck = _cohort()["cohort_key"]
    preview = ba_patch.build_update_preview("doc-xyz", ck)
    assert preview["filter"] == {"_id": "doc-xyz"}
    set_fields = preview["update"]["$set"]
    assert set_fields["mailbox_category"] == "AP"
    assert set_fields["doc_type"] == "AP_INVOICE"
    assert set_fields["suggested_job_type"] == "AP_Invoice"
    audit = set_fields["remediation_audit"]
    assert audit["source"] == "bucket_A_one_shot_patch"
    assert audit["cohort_key"] == ck
    assert audit["applied_at"] is None


def test_build_update_preview_does_not_mutate_cohort_key():
    ck = _cohort()["cohort_key"]
    snapshot = dict(ck)
    preview = ba_patch.build_update_preview("doc-xyz", ck)
    preview["update"]["$set"]["remediation_audit"]["cohort_key"]["mutated"] = True
    assert ck == snapshot, "cohort_key must not be mutated by preview build"


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

def test_analyze_emits_one_record_per_matching_row():
    plan = _plan(_cohort("one_shot_data_patch"))
    rows = [
        _row(best_hub_doc_id="doc-1"),
        _row(best_hub_doc_id="doc-2", best_match_score="0.97"),
        _row(best_hub_doc_id="doc-3", email_sender="other@x.com"),  # excluded
    ]
    result = ba_patch.analyze(plan, rows)
    assert result["cohort_count_one_shot_data_patch"] == 1
    assert result["doc_record_count"] == 2
    ids = sorted(d["doc_id"] for d in result["doc_records"])
    assert ids == ["doc-1", "doc-2"]


def test_analyze_skips_rows_with_no_doc_id():
    plan = _plan(_cohort("one_shot_data_patch"))
    rows = [_row(best_hub_doc_id="doc-1"), _row(best_hub_doc_id="")]
    result = ba_patch.analyze(plan, rows)
    assert result["doc_record_count"] == 1
    assert result["skipped_no_doc_id"] == 1


def test_analyze_ignores_non_one_shot_change_types():
    plan = _plan(
        _cohort("routing_rule_addition"),
        _cohort("classifier_signal_uplift"),
        _cohort("manual_review"),
    )
    result = ba_patch.analyze(plan, [_row()])
    assert result["cohort_count_one_shot_data_patch"] == 0
    assert result["doc_record_count"] == 0


def test_analyze_emits_update_many_preview_per_cohort():
    plan = _plan(_cohort("one_shot_data_patch"))
    result = ba_patch.analyze(plan, [_row()])
    cs = result["cohort_summaries"][0]
    assert "update_many_preview" in cs
    set_fields = cs["update_many_preview"]["update"]["$set"]
    assert set_fields["mailbox_category"] == "AP"
    assert set_fields["remediation_audit"]["source"] == "bucket_A_one_shot_patch"


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

def test_exit_code_zero_when_no_one_shot_cohorts():
    result = ba_patch.analyze(_plan(_cohort("routing_rule_addition")), [_row()])
    assert ba_patch._exit_code(result) == 0


def test_exit_code_one_when_cohorts_but_no_matching_rows():
    result = ba_patch.analyze(_plan(_cohort("one_shot_data_patch")), [])
    assert ba_patch._exit_code(result) == 1


def test_exit_code_two_when_rows_emitted():
    result = ba_patch.analyze(_plan(_cohort("one_shot_data_patch")), [_row()])
    assert ba_patch._exit_code(result) == 2


# ---------------------------------------------------------------------------
# Round-trip CSV / JSON IO (tmp_path)
# ---------------------------------------------------------------------------

def test_csv_and_json_round_trip(tmp_path):
    plan = _plan(_cohort("one_shot_data_patch"))
    rows = [_row(best_hub_doc_id="doc-A"),
            _row(best_hub_doc_id="doc-B", best_match_score="0.98")]
    result = ba_patch.analyze(plan, rows)

    csv_path = tmp_path / "preview.csv"
    json_path = tmp_path / "preview.json"
    ba_patch.write_csv(str(csv_path), result)
    ba_patch.write_json(str(json_path), result)

    with csv_path.open(encoding="utf-8") as f:
        loaded = list(csv.DictReader(f))
    assert {r["doc_id"] for r in loaded} == {"doc-A", "doc-B"}
    for r in loaded:
        assert r["proposed_mailbox_category"] == "AP"
        assert r["proposed_doc_type"] == "AP_INVOICE"
        assert r["patch_source"] == "bucket_A_one_shot_patch"

    reloaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert reloaded["doc_record_count"] == 2
    assert reloaded["proposed_fields"]["mailbox_category"] == "AP"
    sample = reloaded["doc_records"][0]["update_preview"]
    assert sample["filter"]["_id"] in {"doc-A", "doc-B"}
    assert sample["update"]["$set"]["remediation_audit"]["applied_at"] is None
