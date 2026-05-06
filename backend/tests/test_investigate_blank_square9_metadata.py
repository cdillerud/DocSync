"""Tests for investigate_blank_square9_metadata."""
from __future__ import annotations

from typing import Dict, List

from scripts import investigate_blank_square9_metadata as ibsm


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

def _parity_match_row(**kwargs):
    base = {
        "match_bucket": "match",
        "match_score": "0.95",
        "match_reason": "vendor+invoice",
        "square9_name": "FedEx_001.pdf",
        "square9_parent_path": "Temp Folder/Misc Invoices",
        "square9_modified": "2026-04-29",
        "hub_doc_id": "h-1",
        "hub_file_name": "fedex_001.pdf",
    }
    base.update({k: str(v) for k, v in kwargs.items()})
    return base


def _parity_hub_only_row(**kwargs):
    base = {
        "match_bucket": "hub_only",
        "match_score": "0.0",
        "match_reason": "no_square9_counterpart",
        "square9_name": "",
        "square9_parent_path": "",
        "square9_modified": "",
        "hub_doc_id": "h-only-1",
        "hub_file_name": "orphan_hub_doc.pdf",
    }
    base.update({k: str(v) for k, v in kwargs.items()})
    return base


def _resolved_row(**kwargs):
    base = {
        "bucket": "C",
        "square9_name": "",
        "square9_parent_path": "",
        "square9_modified": "",
        "best_hub_doc_id": "",
        "best_hub_file_name": "",
        "best_match_score": "0.0",
        "best_match_reason": "no_evidence",
        "recommended_action": "investigate_intake_for_this_vendor",
    }
    base.update({k: str(v) for k, v in kwargs.items()})
    return base


# ---------------------------------------------------------------------------
# count_blank
# ---------------------------------------------------------------------------

def test_count_blank_distinguishes_either_vs_both():
    rows: List[Dict[str, str]] = [
        {"square9_name": "a.pdf", "square9_parent_path": "p1"},
        {"square9_name": "", "square9_parent_path": "p2"},
        {"square9_name": "b.pdf", "square9_parent_path": ""},
        {"square9_name": "", "square9_parent_path": ""},
    ]
    c = ibsm.count_blank(rows)
    assert c["total_rows"] == 4
    assert c["blank_name"] == 2
    assert c["blank_parent_path"] == 2
    assert c["blank_either"] == 3
    assert c["blank_both"] == 1


def test_count_blank_handles_whitespace_only():
    rows = [{"square9_name": "   ", "square9_parent_path": "\t"}]
    c = ibsm.count_blank(rows)
    assert c["blank_both"] == 1


# ---------------------------------------------------------------------------
# classify_blank
# ---------------------------------------------------------------------------

def test_classify_blank_recognizes_hub_only_artifact():
    row = _parity_hub_only_row()
    assert ibsm.classify_blank(row) == "hub_only_artifact_from_parity"


def test_classify_blank_infers_hub_only_when_doc_id_present():
    row = {
        "match_bucket": "",  # no match_bucket column in resolved CSV
        "best_hub_doc_id": "h-1",
        "best_hub_file_name": "x.pdf",
        "bucket": "",
    }
    assert ibsm.classify_blank(row) == "hub_only_inferred_from_doc_id"


def test_classify_blank_artifact_when_nothing_recoverable():
    row = {"match_bucket": "", "best_hub_doc_id": "", "best_hub_file_name": "",
           "bucket": "C"}
    assert ibsm.classify_blank(row) == "artifact_exclude_from_parity"


def test_classify_blank_bucket_C_misrouting():
    row = {"match_bucket": "", "best_hub_doc_id": "h-77",
           "best_hub_file_name": "", "bucket": "C"}
    # hub_doc_id present + bucket=C → routed as hub_only_inferred_from_doc_id
    # which is acceptable; either label captures the same root issue. We
    # only require that the artifact-exclude branch is NOT taken.
    assert ibsm.classify_blank(row) != "artifact_exclude_from_parity"


# ---------------------------------------------------------------------------
# recover_blank_rows
# ---------------------------------------------------------------------------

def test_recover_blank_rows_returns_only_blank_both_rows():
    rows = [
        _resolved_row(square9_name="a.pdf", square9_parent_path="p"),
        _resolved_row(),  # blank both
        _resolved_row(square9_name="", square9_parent_path="p"),  # blank name only
    ]
    rec = ibsm.recover_blank_rows(rows)
    assert len(rec) == 1
    assert rec[0]["row_index"] == 1


def test_recover_blank_rows_carries_hub_doc_id():
    rows = [_resolved_row(best_hub_doc_id="h-9", best_hub_file_name="f.pdf")]
    rec = ibsm.recover_blank_rows(rows)
    assert rec[0]["hub_doc_id"] == "h-9"
    assert rec[0]["hub_file_name"] == "f.pdf"


# ---------------------------------------------------------------------------
# analyze() — full root-cause story
# ---------------------------------------------------------------------------

def test_analyze_detects_resolver_consumed_parity_csv_root_cause():
    # 3 hub_only rows in parity → 3 blank rows in resolved.
    parity = [_parity_match_row()] + [
        _parity_hub_only_row(hub_doc_id=f"h-{i}") for i in range(3)
    ]
    resolved = [
        _resolved_row(square9_name="FedEx_001.pdf",
                      square9_parent_path="Temp Folder/Misc Invoices"),
        _resolved_row(),  # 3 blanks corresponding to parity hub_only rows
        _resolved_row(),
        _resolved_row(),
    ]
    result = ibsm.analyze(parity, resolved)
    assert result["resolved_counts"]["blank_both"] == 3
    assert result["parity_counts"]["blank_both"] == 3
    assert result["parity_blank_match_bucket_breakdown"]["hub_only"] == 3
    assert result["root_cause"] == \
        "resolver_consumed_parity_csv_without_filtering_match_bucket"
    assert result["should_regenerate_bucket_C_plan"] is True


def test_analyze_with_no_blank_rows_recommends_no_regeneration():
    parity = [_parity_match_row()]
    resolved = [
        _resolved_row(square9_name="FedEx_001.pdf",
                      square9_parent_path="Temp Folder/Misc Invoices",
                      bucket="A", best_hub_doc_id="h-1"),
    ]
    result = ibsm.analyze(parity, resolved)
    assert result["resolved_counts"]["blank_both"] == 0
    assert result["should_regenerate_bucket_C_plan"] is False


def test_analyze_corrected_bucket_C_counts():
    # Bucket C: 2 real (with metadata) + 3 blank-both (1 recoverable, 2 not)
    parity: List[Dict[str, str]] = []
    resolved = [
        _resolved_row(square9_name="x.pdf", square9_parent_path="p", bucket="C"),
        _resolved_row(square9_name="y.pdf", square9_parent_path="p", bucket="C"),
        _resolved_row(bucket="C", best_hub_doc_id="h-only-1"),  # recoverable
        _resolved_row(bucket="C"),  # artifact
        _resolved_row(bucket="C"),  # artifact
    ]
    result = ibsm.analyze(parity, resolved)
    assert result["bucket_C_total"] == 5
    assert result["bucket_C_blank_metadata"] == 3
    assert result["bucket_C_recoverable_via_hub_doc_id"] == 1
    assert result["real_bucket_C_rows"] == 2
    assert result["artifact_bucket_C_rows"] == 2
    assert result["recovered_bucket_C_rows"] == 1


# ---------------------------------------------------------------------------
# Read-only guardrails
# ---------------------------------------------------------------------------

def test_module_does_not_import_pymongo_or_motor():
    import inspect
    src = inspect.getsource(ibsm)
    assert "from pymongo" not in src
    assert "from motor" not in src


def test_module_makes_no_mutating_http_calls():
    import inspect
    src = inspect.getsource(ibsm)
    forbidden = ("requests.post", "requests.put", "requests.delete",
                 "requests.patch", "httpx.post", "httpx.put",
                 "httpx.delete", "httpx.patch")
    for tok in forbidden:
        assert tok not in src
