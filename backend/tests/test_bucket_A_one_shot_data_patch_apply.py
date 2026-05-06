"""Tests for bucket_A_one_shot_data_patch_apply.

Uses ``mongomock`` instead of a live Mongo, so the apply path is
exercised end-to-end without touching production. The dry-run path is
already covered by tests/test_bucket_A_one_shot_data_patch_dryrun.py;
this file focuses on the apply-only behavior (idempotency, rollback
snapshots, refusal without --confirm, etc.)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import mongomock
import pytest

from scripts import bucket_A_one_shot_data_patch_apply as ba_apply


# ---------------------------------------------------------------------------
# Synthetic fixtures
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


def _seed_collection(docs: List[Dict[str, Any]]):
    coll = mongomock.MongoClient().db.hub_documents
    if docs:
        coll.insert_many(docs)
    return coll


# ---------------------------------------------------------------------------
# build_set_payload
# ---------------------------------------------------------------------------

def test_build_set_payload_sets_three_fields_plus_audit():
    ck = {"email_sender": "x@y.com",
          "classification_method": "ai_classifier:gpt-4o",
          "current_mailbox_category": "Operations",
          "current_doc_type": "AP_INVOICE",
          "current_suggested_job_type": "AP_Invoice",
          "sharepoint_folder_root": "Operations"}
    payload = ba_apply.build_set_payload(ck, "2026-05-06T20:00:00+00:00")
    assert payload["mailbox_category"] == "AP"
    assert payload["doc_type"] == "AP_INVOICE"
    assert payload["suggested_job_type"] == "AP_Invoice"
    audit = payload["remediation_audit"]
    assert audit["source"] == "bucket_A_one_shot_patch"
    assert audit["cohort_key"] == ck
    assert audit["applied_at"] == "2026-05-06T20:00:00+00:00"


# ---------------------------------------------------------------------------
# is_already_applied
# ---------------------------------------------------------------------------

def test_is_already_applied_true_for_matching_marker():
    doc = {"_id": "x",
           "remediation_audit": {"source": "bucket_A_one_shot_patch",
                                 "applied_at": "2026-05-06T20:00:00Z"}}
    assert ba_apply.is_already_applied(doc) is True


def test_is_already_applied_false_when_marker_missing():
    assert ba_apply.is_already_applied({"_id": "x"}) is False


def test_is_already_applied_false_when_other_source():
    doc = {"_id": "x",
           "remediation_audit": {"source": "manual_edit",
                                 "applied_at": "2026-05-06T20:00:00Z"}}
    assert ba_apply.is_already_applied(doc) is False


def test_is_already_applied_false_when_applied_at_empty():
    doc = {"_id": "x",
           "remediation_audit": {"source": "bucket_A_one_shot_patch",
                                 "applied_at": None}}
    assert ba_apply.is_already_applied(doc) is False


# ---------------------------------------------------------------------------
# snapshot_doc_for_rollback
# ---------------------------------------------------------------------------

def test_snapshot_captures_existing_fields():
    doc = {"_id": "objectid_xyz",
           "id": "doc-1",
           "mailbox_category": "Operations",
           "doc_type": "AP_INVOICE",
           "suggested_job_type": "AP_Invoice",
           "remediation_audit": {"source": "x"}}
    snap = ba_apply.snapshot_doc_for_rollback(doc)
    assert snap["id"] == "doc-1"
    assert snap["mailbox_category"] == "Operations"
    assert snap["doc_type"] == "AP_INVOICE"
    assert snap["suggested_job_type"] == "AP_Invoice"
    assert snap["remediation_audit"] == {"source": "x"}


def test_snapshot_marks_missing_fields():
    doc = {"id": "doc-1", "mailbox_category": "Sales"}
    snap = ba_apply.snapshot_doc_for_rollback(doc)
    assert snap["__missing_doc_type"] is True
    assert snap["__missing_suggested_job_type"] is True
    assert snap["__missing_remediation_audit"] is True


# ---------------------------------------------------------------------------
# apply_one_shot_patch — happy path (mongomock)
# ---------------------------------------------------------------------------

def test_apply_updates_matching_docs_and_writes_rollback(tmp_path: Path):
    coll = _seed_collection([
        {"id": "doc-1", "mailbox_category": "Operations",
         "doc_type": "AP_INVOICE", "suggested_job_type": "AP_Invoice"},
        {"id": "doc-2", "mailbox_category": "Operations",
         "doc_type": "AP_INVOICE", "suggested_job_type": "AP_Invoice"},
    ])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1"),
            _row(best_hub_doc_id="doc-2")]

    summary = ba_apply.apply_one_shot_patch(
        plan, rows, coll, str(tmp_path), applied_at="2026-05-06T20:00:00Z")

    assert summary["planned_count"] == 2
    assert summary["updated_count"] == 2
    assert summary["skipped_already_applied"] == 0
    assert summary["skipped_missing_in_db"] == 0

    # Documents updated correctly
    for doc_id in ("doc-1", "doc-2"):
        d = coll.find_one({"id": doc_id})
        assert d["mailbox_category"] == "AP"
        assert d["doc_type"] == "AP_INVOICE"
        assert d["suggested_job_type"] == "AP_Invoice"
        assert d["remediation_audit"]["source"] == "bucket_A_one_shot_patch"
        assert d["remediation_audit"]["applied_at"] == "2026-05-06T20:00:00Z"

    # Rollback file written FIRST and contains prior values
    rollback_path = tmp_path / "rollback.json"
    assert rollback_path.exists()
    rb = json.loads(rollback_path.read_text(encoding="utf-8"))
    assert rb["doc_count"] == 2
    assert rb["patch_source"] == "bucket_A_one_shot_patch"
    ids = sorted(r["id"] for r in rb["rollback_records"])
    assert ids == ["doc-1", "doc-2"]
    for r in rb["rollback_records"]:
        # Pre-patch values captured
        assert r["mailbox_category"] == "Operations"


def test_apply_is_idempotent_skips_already_applied(tmp_path: Path):
    coll = _seed_collection([
        {"id": "doc-1", "mailbox_category": "AP",
         "doc_type": "AP_INVOICE", "suggested_job_type": "AP_Invoice",
         "remediation_audit": {"source": "bucket_A_one_shot_patch",
                               "applied_at": "earlier-run"}},
    ])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1")]

    summary = ba_apply.apply_one_shot_patch(
        plan, rows, coll, str(tmp_path))

    assert summary["planned_count"] == 1
    assert summary["skipped_already_applied"] == 1
    assert summary["updated_count"] == 0
    rb = json.loads((tmp_path / "rollback.json").read_text(encoding="utf-8"))
    assert rb["doc_count"] == 0  # no rollback recorded for skipped doc


def test_apply_skips_planned_docs_missing_from_db(tmp_path: Path):
    coll = _seed_collection([])  # empty DB
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1"),
            _row(best_hub_doc_id="doc-2")]
    summary = ba_apply.apply_one_shot_patch(
        plan, rows, coll, str(tmp_path))
    assert summary["planned_count"] == 2
    assert summary["skipped_missing_in_db"] == 2
    assert summary["updated_count"] == 0


def test_apply_ignores_non_one_shot_change_types(tmp_path: Path):
    coll = _seed_collection([
        {"id": "doc-1", "mailbox_category": "Sales"},
    ])
    plan = _plan(_cohort("routing_rule_addition"),
                 _cohort("classifier_signal_uplift"),
                 _cohort("manual_review"))
    summary = ba_apply.apply_one_shot_patch(
        plan, [_row(best_hub_doc_id="doc-1")], coll, str(tmp_path))
    assert summary["planned_count"] == 0
    assert summary["updated_count"] == 0
    # And the doc was NOT touched.
    doc = coll.find_one({"id": "doc-1"})
    assert doc["mailbox_category"] == "Sales"


def test_apply_writes_rollback_before_updates(tmp_path: Path, monkeypatch):
    """If an update_one call raises, the rollback file should already
    be on disk (so the operator can recover any partial updates)."""
    coll = _seed_collection([
        {"id": "doc-1", "mailbox_category": "Operations"},
    ])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1")]
    rollback_path = tmp_path / "rollback.json"

    original_update_one = coll.update_one

    def boom(*a, **kw):
        # Rollback file must already exist when the first update fires.
        assert rollback_path.exists(), \
            "rollback.json must be written BEFORE update_one"
        return original_update_one(*a, **kw)

    monkeypatch.setattr(coll, "update_one", boom)
    summary = ba_apply.apply_one_shot_patch(
        plan, rows, coll, str(tmp_path))
    assert summary["updated_count"] == 1


def test_apply_two_cohorts_record_distinct_cohort_keys(tmp_path: Path):
    coll = _seed_collection([
        {"id": "doc-1"}, {"id": "doc-2"},
    ])
    plan = _plan(
        _cohort(email_sender="a@x.com"),
        _cohort(email_sender="b@x.com"),
    )
    rows = [_row(best_hub_doc_id="doc-1", email_sender="a@x.com"),
            _row(best_hub_doc_id="doc-2", email_sender="b@x.com")]
    summary = ba_apply.apply_one_shot_patch(
        plan, rows, coll, str(tmp_path), applied_at="t")
    assert summary["updated_count"] == 2
    audits = sorted(
        coll.find({}, {"_id": 0, "id": 1, "remediation_audit": 1}),
        key=lambda d: d["id"])
    assert (audits[0]["remediation_audit"]["cohort_key"]["email_sender"]
            == "a@x.com")
    assert (audits[1]["remediation_audit"]["cohort_key"]["email_sender"]
            == "b@x.com")


# ---------------------------------------------------------------------------
# CLI gating (refusal path)
# ---------------------------------------------------------------------------

def test_cli_refuses_apply_without_confirm(tmp_path: Path, monkeypatch,
                                           capsys):
    plan_path = tmp_path / "plan.json"
    csv_path = tmp_path / "rows.csv"
    plan_path.write_text(json.dumps(_plan(_cohort())), encoding="utf-8")
    # Minimal CSV
    csv_path.write_text(
        "best_hub_doc_id,best_hub_file_name,best_hub_mailbox_category,"
        "best_hub_doc_type,best_hub_suggested_job_type,classification_method,"
        "sharepoint_folder_root,email_sender,best_match_score,root_cause\n"
        "doc-1,a.pdf,Operations,AP_INVOICE,AP_Invoice,"
        "ai_classifier:gpt-4o,Operations,billing@valley.com,0.9,x\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["bucket_A_one_shot_data_patch_apply",
         "--plan-json", str(plan_path),
         "--root-cause-csv", str(csv_path),
         "--apply"],
    )
    rc = ba_apply.main()
    assert rc == 3
    err = capsys.readouterr().err
    assert "REFUSED" in err


def test_cli_dry_run_path_returns_two(tmp_path: Path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    csv_path = tmp_path / "rows.csv"
    out_csv = tmp_path / "preview.csv"
    plan_path.write_text(json.dumps(_plan(_cohort())), encoding="utf-8")
    csv_path.write_text(
        "best_hub_doc_id,best_hub_file_name,best_hub_mailbox_category,"
        "best_hub_doc_type,best_hub_suggested_job_type,classification_method,"
        "sharepoint_folder_root,email_sender,best_match_score,root_cause\n"
        "doc-1,a.pdf,Operations,AP_INVOICE,AP_Invoice,"
        "ai_classifier:gpt-4o,Operations,billing@valley.com,0.9,x\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["bucket_A_one_shot_data_patch_apply",
         "--plan-json", str(plan_path),
         "--root-cause-csv", str(csv_path),
         "--dry-run-csv", str(out_csv)],
    )
    rc = ba_apply.main()
    # Dry-run with rows present + matching cohort → rc=2 (rows emitted)
    assert rc == 2
    assert out_csv.exists()
