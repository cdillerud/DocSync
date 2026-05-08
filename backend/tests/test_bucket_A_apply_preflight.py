"""Tests for bucket_A_apply_preflight (read-only, mongomock-backed)."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List

import mongomock

from scripts import bucket_A_apply_preflight as pf


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

def _row(**kw) -> Dict[str, str]:
    base = {
        "best_hub_doc_id": "doc-1",
        "best_hub_file_name": "valley.pdf",
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
        "affected_doc_count": 1,
        "avg_score": 0.95,
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
# evaluate_safety
# ---------------------------------------------------------------------------

def test_safety_passes_for_clean_candidate():
    live = {"_id": "doc-1", "doc_type": "AP_INVOICE",
            "suggested_job_type": "AP_Invoice",
            "mailbox_category": "Operations"}
    is_safe, reasons = pf.evaluate_safety(live)
    assert is_safe is True
    assert reasons == []


def test_safety_passes_when_suggested_job_type_blank():
    live = {"_id": "x", "doc_type": "AP_INVOICE",
            "suggested_job_type": "",
            "mailbox_category": "Sales"}
    is_safe, _ = pf.evaluate_safety(live)
    assert is_safe is True


def test_safety_fails_when_doc_not_found():
    is_safe, reasons = pf.evaluate_safety(None)
    assert is_safe is False
    assert any(r.startswith("S0") for r in reasons)


def test_safety_fails_when_doc_type_not_AP_INVOICE():
    live = {"_id": "x", "doc_type": "AR_INVOICE",
            "suggested_job_type": "AP_Invoice",
            "mailbox_category": "Sales"}
    is_safe, reasons = pf.evaluate_safety(live)
    assert is_safe is False
    assert any(r.startswith("S1") for r in reasons)


def test_safety_fails_when_suggested_job_type_incompatible():
    live = {"_id": "x", "doc_type": "AP_INVOICE",
            "suggested_job_type": "Sales_Invoice",
            "mailbox_category": "Sales"}
    is_safe, reasons = pf.evaluate_safety(live)
    assert is_safe is False
    assert any(r.startswith("S2") for r in reasons)


def test_safety_fails_when_mailbox_category_already_AP():
    live = {"_id": "x", "doc_type": "AP_INVOICE",
            "suggested_job_type": "AP_Invoice",
            "mailbox_category": "AP"}
    is_safe, reasons = pf.evaluate_safety(live)
    assert is_safe is False
    assert any(r.startswith("S3") for r in reasons)


def test_safety_fails_when_already_applied():
    live = {"_id": "x", "doc_type": "AP_INVOICE",
            "suggested_job_type": "AP_Invoice",
            "mailbox_category": "Sales",
            "remediation_audit": {"source": "bucket_A_one_shot_patch",
                                  "applied_at": "yesterday"}}
    is_safe, reasons = pf.evaluate_safety(live)
    assert is_safe is False
    assert any(r.startswith("S5") for r in reasons)


def test_safety_aggregates_multiple_failures():
    live = {"_id": "x", "doc_type": "OTHER",
            "suggested_job_type": "Something",
            "mailbox_category": "AP"}
    is_safe, reasons = pf.evaluate_safety(live)
    assert is_safe is False
    codes = sorted(r.split(":")[0] for r in reasons)
    assert codes == ["S1", "S2", "S3"]


# ---------------------------------------------------------------------------
# select_candidates
# ---------------------------------------------------------------------------

def test_select_candidates_filters_by_change_type_and_cohort():
    plan = _plan(_cohort("one_shot_data_patch"),
                 _cohort("routing_rule_addition"))
    rows = [_row(best_hub_doc_id="doc-1"),
            _row(best_hub_doc_id="doc-2", email_sender="other@x.com")]
    cands = pf.select_candidates(plan, rows)
    ids = [c[0] for c in cands]
    assert ids == ["doc-1"]


def test_select_candidates_skips_blank_doc_ids():
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id=""), _row(best_hub_doc_id="doc-2")]
    cands = pf.select_candidates(plan, rows)
    assert [c[0] for c in cands] == ["doc-2"]


# ---------------------------------------------------------------------------
# preflight (mongomock-backed)
# ---------------------------------------------------------------------------

def _parity(square_count: int = 100, matched: int = 36) -> Dict[str, Any]:
    return {"square_count": square_count,
            "bucket_counts": {
                "exact_match": 0,
                "strong_evidence_match": matched,
                "likely_match": 0,
                "possible_match": 0,
                "no_match": square_count - matched - 10,
                "hub_only": 10,
            }}


def test_preflight_happy_path_emits_safe_candidate(tmp_path: Path):
    coll = _seed_collection([
        {"id": "doc-1", "doc_type": "AP_INVOICE",
         "suggested_job_type": "AP_Invoice",
         "mailbox_category": "Operations",
         "file_name": "valley.pdf",
         "routing_status": "PENDING",
         "routing_reason": "no_rule",
         "sharepoint_folder_path": "/Operations/valley.pdf"},
    ])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1")]
    result = pf.preflight(plan, rows, coll,
                          parity_payload=_parity(square_count=100, matched=36),
                          now=dt.datetime(2026, 5, 6, 22, 0, 0,
                                          tzinfo=dt.timezone.utc))
    assert result["candidate_count"] == 1
    assert result["safe_count"] == 1
    assert result["unsafe_count"] == 0
    payloads = result["update_payloads"]
    assert len(payloads) == 1
    assert payloads[0]["filter"] == {"id": "doc-1"}
    set_body = payloads[0]["update"]["$set"]
    assert set_body["mailbox_category"] == "AP"
    assert set_body["doc_type"] == "AP_INVOICE"
    assert set_body["suggested_job_type"] == "AP_Invoice"
    assert set_body["remediation_audit"]["source"] == "bucket_A_one_shot_patch"
    assert "predicted_rollback_path" in result
    assert result["predicted_rollback_path"].startswith(
        "prod_reports/apply_bucket_A_2026-05-06T22-00-00Z/")
    table = result["before_after_table"][0]
    assert table["file_name"] == "valley.pdf"
    assert table["current_routing_status"] == "PENDING"
    assert table["current_routing_reason"] == "no_rule"
    assert table["sharepoint_folder_path"] == "/Operations/valley.pdf"
    # Projection: (36 + 1) / 100 = 37.0
    assert abs(result["projected_match_rate_pct"] - 37.0) < 1e-6
    assert pf._exit_code(result) == 0


def test_preflight_passes_when_doc_already_applied():
    """A doc whose live state EXACTLY matches the expected post-apply
    state is classified as already_applied (not unsafe). Preflight
    must exit 0 so the wrapper can skip the apply step and proceed to
    verification + proof pack."""
    coll = _seed_collection([
        {"id": "doc-1", "doc_type": "AP_INVOICE",
         "suggested_job_type": "AP_Invoice",
         "mailbox_category": "AP",
         "remediation_audit": {"source": "bucket_A_one_shot_patch",
                               "applied_at": "2026-05-06T22:00:00Z"}},
    ])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1")]
    result = pf.preflight(plan, rows, coll, parity_payload=_parity())
    assert result["safe_count"] == 0
    assert result["unsafe_count"] == 0
    assert result["already_applied_count"] == 1
    assert result["already_applied"][0]["doc_id"] == "doc-1"
    assert (result["already_applied"][0]["remediation_audit_source"]
            == "bucket_A_one_shot_patch")
    assert pf._exit_code(result) == 0
    # Idempotent state means no apply payloads should be queued.
    assert result["update_payloads"] == []


def test_preflight_passes_when_all_candidates_already_applied():
    """Every candidate already in expected post-apply state -> exit 0."""
    coll = _seed_collection([
        {"id": "doc-1", "doc_type": "AP_INVOICE",
         "suggested_job_type": "AP_Invoice",
         "mailbox_category": "AP",
         "remediation_audit": {"source": "bucket_A_one_shot_patch",
                               "applied_at": "2026-05-06T22:00:00Z"}},
        {"id": "doc-2", "doc_type": "AP_INVOICE",
         "suggested_job_type": "AP_Invoice",
         "mailbox_category": "AP",
         "remediation_audit": {"source": "bucket_A_one_shot_patch",
                               "applied_at": "2026-05-06T22:00:01Z"}},
    ])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1"),
            _row(best_hub_doc_id="doc-2", email_sender="billing@valley.com")]
    result = pf.preflight(plan, rows, coll, parity_payload=_parity())
    assert result["candidate_count"] == 2
    assert result["already_applied_count"] == 2
    assert result["safe_count"] == 0
    assert result["unsafe_count"] == 0
    assert pf._exit_code(result) == 0


def test_preflight_passes_when_mixed_safe_and_already_applied():
    """Mix of safe + already_applied (and zero unsafe) -> exit 0."""
    coll = _seed_collection([
        {"id": "doc-1", "doc_type": "AP_INVOICE",
         "suggested_job_type": "AP_Invoice",
         "mailbox_category": "Operations"},
        {"id": "doc-2", "doc_type": "AP_INVOICE",
         "suggested_job_type": "AP_Invoice",
         "mailbox_category": "AP",
         "remediation_audit": {"source": "bucket_A_one_shot_patch",
                               "applied_at": "2026-05-06T22:00:01Z"}},
    ])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1"),
            _row(best_hub_doc_id="doc-2")]
    result = pf.preflight(plan, rows, coll, parity_payload=_parity())
    assert result["candidate_count"] == 2
    assert result["safe_count"] == 1
    assert result["already_applied_count"] == 1
    assert result["unsafe_count"] == 0
    assert pf._exit_code(result) == 0


def test_preflight_fails_when_already_applied_mixed_with_truly_unsafe():
    """already_applied does not mask a truly unsafe candidate."""
    coll = _seed_collection([
        {"id": "doc-1", "doc_type": "AP_INVOICE",
         "suggested_job_type": "AP_Invoice",
         "mailbox_category": "AP",
         "remediation_audit": {"source": "bucket_A_one_shot_patch",
                               "applied_at": "2026-05-06T22:00:00Z"}},
        {"id": "doc-2", "doc_type": "OTHER",
         "suggested_job_type": "Sales_Invoice",
         "mailbox_category": "Operations"},
    ])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1"),
            _row(best_hub_doc_id="doc-2")]
    result = pf.preflight(plan, rows, coll, parity_payload=_parity())
    assert result["already_applied_count"] == 1
    assert result["unsafe_count"] == 1
    assert pf._exit_code(result) == 1


def test_preflight_partial_final_state_is_not_already_applied():
    """A doc with mailbox_category=AP but no remediation_audit must
    NOT be classified as already_applied — that is an inconsistent
    in-flight state and must remain unsafe (S3)."""
    coll = _seed_collection([
        {"id": "doc-1", "doc_type": "AP_INVOICE",
         "suggested_job_type": "AP_Invoice",
         "mailbox_category": "AP"},  # no remediation_audit
    ])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1")]
    result = pf.preflight(plan, rows, coll, parity_payload=_parity())
    assert result["already_applied_count"] == 0
    assert result["unsafe_count"] == 1
    assert pf._exit_code(result) == 1


def test_evaluate_already_applied_strict_predicate():
    """All four fields are required."""
    base = {"doc_type": "AP_INVOICE",
            "suggested_job_type": "AP_Invoice",
            "mailbox_category": "AP",
            "remediation_audit": {"source": "bucket_A_one_shot_patch",
                                  "applied_at": "x"}}
    assert pf.evaluate_already_applied(base) is True
    assert pf.evaluate_already_applied(None) is False
    assert pf.evaluate_already_applied(
        {**base, "mailbox_category": "Operations"}) is False
    assert pf.evaluate_already_applied(
        {**base, "doc_type": "OTHER"}) is False
    assert pf.evaluate_already_applied(
        {**base, "suggested_job_type": "Sales_Invoice"}) is False
    assert pf.evaluate_already_applied(
        {**base, "remediation_audit": None}) is False
    assert pf.evaluate_already_applied(
        {**base, "remediation_audit": {"source": "other", "applied_at": "x"}}
    ) is False
    # audit.source matches but applied_at missing -> not already applied.
    assert pf.evaluate_already_applied(
        {**base, "remediation_audit": {"source": "bucket_A_one_shot_patch"}}
    ) is False


def test_render_text_includes_already_applied_section_and_status_line():
    coll = _seed_collection([
        {"id": "doc-1", "doc_type": "AP_INVOICE",
         "suggested_job_type": "AP_Invoice",
         "mailbox_category": "AP",
         "remediation_audit": {"source": "bucket_A_one_shot_patch",
                               "applied_at": "2026-05-06T22:00:00Z"}},
    ])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1")]
    result = pf.preflight(plan, rows, coll, parity_payload=_parity())
    text = pf.render_text(result, pf._exit_code(result))
    assert "PASS" in text
    assert "already_applied_count" in text
    assert "ALREADY APPLIED DOC IDS" in text
    assert "doc-1" in text
    # Machine-friendly status line is present.
    assert "[preflight-status]" in text
    assert "safe_count=0" in text
    assert "already_applied_count=1" in text
    assert "unsafe_count=0" in text


def test_preflight_fails_when_doc_missing_from_db():
    coll = _seed_collection([])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1")]
    result = pf.preflight(plan, rows, coll, parity_payload=_parity())
    assert result["unsafe_count"] == 1
    assert any(r.startswith("S0")
               for r in result["unsafe"][0]["reasons"])
    assert pf._exit_code(result) == 1


def test_preflight_returns_two_when_no_candidates():
    coll = _seed_collection([])
    plan = _plan(_cohort("routing_rule_addition"))
    rows = [_row(best_hub_doc_id="doc-1")]
    result = pf.preflight(plan, rows, coll, parity_payload=_parity())
    assert result["candidate_count"] == 0
    assert pf._exit_code(result) == 2


def test_preflight_mixed_safe_and_unsafe_returns_one():
    coll = _seed_collection([
        {"id": "doc-1", "doc_type": "AP_INVOICE",
         "suggested_job_type": "AP_Invoice",
         "mailbox_category": "Operations"},
        {"id": "doc-2", "doc_type": "OTHER",
         "suggested_job_type": "AP_Invoice",
         "mailbox_category": "Operations"},
    ])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1"),
            _row(best_hub_doc_id="doc-2")]
    result = pf.preflight(plan, rows, coll, parity_payload=_parity())
    assert result["safe_count"] == 1
    assert result["unsafe_count"] == 1
    assert pf._exit_code(result) == 1


def test_projected_match_rate_unknown_when_parity_missing():
    coll = _seed_collection([
        {"id": "doc-1", "doc_type": "AP_INVOICE",
         "suggested_job_type": "AP_Invoice",
         "mailbox_category": "Operations"},
    ])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1")]
    result = pf.preflight(plan, rows, coll, parity_payload=None)
    assert result["projected_match_rate_pct"] is None


# ---------------------------------------------------------------------------
# render_text
# ---------------------------------------------------------------------------

def test_render_text_pass_includes_live_apply_command_and_rollback():
    coll = _seed_collection([
        {"id": "doc-1", "doc_type": "AP_INVOICE",
         "suggested_job_type": "AP_Invoice",
         "mailbox_category": "Operations"},
    ])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1")]
    result = pf.preflight(plan, rows, coll, parity_payload=_parity())
    text = pf.render_text(result, pf._exit_code(result))
    assert "PASS" in text
    assert pf.LIVE_APPLY_COMMAND in text
    assert "Rollback procedure" in text
    assert "doc-1" in text
    assert "READ-ONLY preflight" in text


def test_render_text_fail_includes_unsafe_reasons():
    coll = _seed_collection([
        {"id": "doc-1", "doc_type": "OTHER",
         "suggested_job_type": "Sales_Invoice",
         "mailbox_category": "AP"},
    ])
    plan = _plan(_cohort())
    rows = [_row(best_hub_doc_id="doc-1")]
    result = pf.preflight(plan, rows, coll, parity_payload=_parity())
    text = pf.render_text(result, pf._exit_code(result))
    assert "FAIL" in text
    assert "S1:" in text
    assert "S2:" in text
    assert "S3:" in text
