"""Tests for bucket_A_routing_rule_addition_dryrun (read-only, synthetic)."""
from __future__ import annotations

import csv
import json
from typing import Any, Dict

import pytest

from scripts import bucket_A_routing_rule_addition_dryrun as ba_rules


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

def _cohort(change_type: str = "routing_rule_addition",
            sender: str = "billing@valley.com",
            band: str = "high",
            avg: float = 0.94,
            count: int = 5,
            **ck_overrides) -> Dict[str, Any]:
    ck = {
        "email_sender": sender,
        "classification_method": "ai_classifier:gpt-4o",
        "current_mailbox_category": "Operations",
        "current_doc_type": "AP_INVOICE",
        "current_suggested_job_type": "AP_Invoice",
        "sharepoint_folder_root": "Operations",
    }
    ck.update(ck_overrides)
    return {
        "cohort_key": ck,
        "affected_doc_count": count,
        "avg_score": avg,
        "confidence_band": band,
        "dominant_root_cause": "high_confidence_AP_invoice_misrouted",
        "change_type": change_type,
    }


def _plan(*cohorts: Dict[str, Any]) -> Dict[str, Any]:
    return {"actionable_cohorts": list(cohorts)}


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def test_select_routing_rule_cohorts_filters_change_type():
    plan = _plan(
        _cohort("routing_rule_addition"),
        _cohort("one_shot_data_patch"),
        _cohort("classifier_signal_uplift"),
    )
    out = ba_rules.select_routing_rule_cohorts(plan)
    assert len(out) == 1
    assert out[0]["change_type"] == "routing_rule_addition"


# ---------------------------------------------------------------------------
# derive_priority closed taxonomy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("band,expected", [
    ("high", 10),
    ("medium", 20),
    ("low", 30),
    ("HIGH", 10),
])
def test_derive_priority_maps_known_bands(band, expected):
    assert ba_rules.derive_priority(band, 0.0) == expected


def test_derive_priority_falls_back_to_score_when_band_unknown():
    assert ba_rules.derive_priority("unknown", 0.95) == 10
    assert ba_rules.derive_priority("", 0.7) == 20
    assert ba_rules.derive_priority(None, 0.1) == 30


def test_derive_priority_treats_unparseable_score_as_low():
    assert ba_rules.derive_priority(None, "not-a-number") == 30


# ---------------------------------------------------------------------------
# build_rule shape
# ---------------------------------------------------------------------------

def test_build_rule_targets_AP_AP_INVOICE_AP_Invoice():
    rule = ba_rules.build_rule(0, _cohort())
    assert rule["target_mailbox_category"] == "AP"
    assert rule["target_doc_type"] == "AP_INVOICE"
    assert rule["target_suggested_job_type"] == "AP_Invoice"
    assert rule["sender_glob"] == "billing@valley.com"
    assert rule["skipped_reason"] == ""


def test_build_rule_skips_when_email_sender_missing():
    rule = ba_rules.build_rule(0, _cohort(sender=""))
    assert rule["sender_glob"] == ""
    assert rule["skipped_reason"] == "no_email_sender_in_cohort_key"


def test_build_rule_priority_reflects_band():
    rule_hi = ba_rules.build_rule(0, _cohort(band="high"))
    rule_md = ba_rules.build_rule(1, _cohort(band="medium"))
    rule_lo = ba_rules.build_rule(2, _cohort(band="low"))
    assert rule_hi["priority"] == 10
    assert rule_md["priority"] == 20
    assert rule_lo["priority"] == 30


def test_build_rule_carries_full_cohort_key_for_traceability():
    rule = ba_rules.build_rule(0, _cohort())
    assert rule["source_cohort_email_sender"] == "billing@valley.com"
    assert rule["source_cohort_classification_method"] == "ai_classifier:gpt-4o"
    assert rule["source_cohort_current_mailbox_category"] == "Operations"
    assert rule["source_cohort_current_doc_type"] == "AP_INVOICE"
    assert rule["source_cohort_current_suggested_job_type"] == "AP_Invoice"
    assert rule["source_cohort_sharepoint_folder_root"] == "Operations"


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

def test_analyze_sorts_by_affected_then_score():
    plan = _plan(
        _cohort(sender="a@x.com", count=2, avg=0.95),
        _cohort(sender="b@x.com", count=10, avg=0.62),
        _cohort(sender="c@x.com", count=5, avg=0.99),
    )
    result = ba_rules.analyze(plan)
    senders = [r["sender_glob"] for r in result["emitted_rules"]]
    assert senders == ["b@x.com", "c@x.com", "a@x.com"]


def test_analyze_separates_emitted_from_skipped():
    plan = _plan(
        _cohort(sender="ok@x.com"),
        _cohort(sender=""),
    )
    result = ba_rules.analyze(plan)
    assert result["rule_count_emitted"] == 1
    assert result["rule_count_skipped"] == 1
    assert result["emitted_rules"][0]["sender_glob"] == "ok@x.com"


def test_analyze_priority_counts_only_count_emitted_rules():
    plan = _plan(
        _cohort(sender="a@x.com", band="high"),
        _cohort(sender="b@x.com", band="medium"),
        _cohort(sender="", band="low"),  # skipped
    )
    result = ba_rules.analyze(plan)
    counts = dict(result["priority_counts"])
    assert counts.get(10) == 1
    assert counts.get(20) == 1
    assert counts.get(30, 0) == 0


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

def test_exit_code_zero_when_no_routing_rule_cohorts():
    result = ba_rules.analyze(_plan(_cohort("one_shot_data_patch")))
    assert ba_rules._exit_code(result) == 0


def test_exit_code_one_when_all_cohorts_skipped_for_missing_sender():
    result = ba_rules.analyze(_plan(_cohort(sender="")))
    assert ba_rules._exit_code(result) == 1


def test_exit_code_two_when_at_least_one_rule_emitted():
    result = ba_rules.analyze(_plan(_cohort()))
    assert ba_rules._exit_code(result) == 2


# ---------------------------------------------------------------------------
# Round-trip CSV / JSON IO (tmp_path)
# ---------------------------------------------------------------------------

def test_csv_and_json_round_trip(tmp_path):
    plan = _plan(
        _cohort(sender="a@x.com", count=4, band="high"),
        _cohort(sender="", count=2, band="low"),
    )
    result = ba_rules.analyze(plan)

    csv_path = tmp_path / "rules.csv"
    json_path = tmp_path / "rules.json"
    ba_rules.write_csv(str(csv_path), result)
    ba_rules.write_json(str(json_path), result)

    with csv_path.open(encoding="utf-8") as f:
        loaded = list(csv.DictReader(f))
    assert len(loaded) == 2
    assert all(r["target_mailbox_category"] == "AP" for r in loaded)
    assert all(r["target_doc_type"] == "AP_INVOICE" for r in loaded)
    sender_rows = {r["sender_glob"]: r for r in loaded}
    assert sender_rows["a@x.com"]["skipped_reason"] == ""
    assert sender_rows[""]["skipped_reason"] == "no_email_sender_in_cohort_key"

    reloaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert reloaded["rule_count_emitted"] == 1
    assert reloaded["rule_count_skipped"] == 1
