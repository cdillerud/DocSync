"""Tests for investigate_low_confidence_bucket_A."""
from __future__ import annotations

from typing import Dict, List

from scripts import investigate_low_confidence_bucket_A as ilc


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

def _bucket_a_row(**kwargs):
    base = {
        "root_cause": "low_confidence_match_ambiguous",
        "square9_name": "FedEx_042926_9-275-62775.pdf",
        "square9_parent_path": "Temp Folder/Misc Invoices",
        "best_hub_doc_id": "h-1",
        "best_hub_file_name": "fedex_invoice.pdf",
        "best_hub_mailbox_category": "SALES",
        "best_hub_doc_type": "SALES_INVOICE",
        "best_match_score": "0.42",
        "best_match_reason": "vendor_token_multi",
    }
    base.update({k: str(v) for k, v in kwargs.items()})
    return base


def _parity_row(**kwargs):
    base = {
        "match_bucket": "match",
        "square9_name": "FedEx_042926_9-275-62775.pdf",
        "square9_parent_path": "Temp Folder/Misc Invoices",
    }
    base.update({k: str(v) for k, v in kwargs.items()})
    return base


# ---------------------------------------------------------------------------
# build_parity_index
# ---------------------------------------------------------------------------

def test_build_parity_index_keys_by_name_and_parent():
    parity = [
        _parity_row(match_bucket="no_match"),
        _parity_row(square9_name="other.pdf",
                    square9_parent_path="Other",
                    match_bucket="match"),
    ]
    idx = ilc.build_parity_index(parity)
    assert idx[("FedEx_042926_9-275-62775.pdf",
                "Temp Folder/Misc Invoices")] == "no_match"
    assert idx[("other.pdf", "Other")] == "match"


# ---------------------------------------------------------------------------
# classify_low_confidence_row — five outcomes
# ---------------------------------------------------------------------------

def test_classify_real_ambiguous_match_with_token_evidence():
    row = _bucket_a_row(
        best_match_score="0.55",
        best_match_reason="vendor_token+date_proximity",
    )
    assert ilc.classify_low_confidence_row(row, parity_index={}) == \
        "real_ambiguous_match"


def test_classify_matcher_false_positive_when_parity_says_no_match():
    row = _bucket_a_row(best_match_score="0.42")
    parity_idx = {
        ("FedEx_042926_9-275-62775.pdf",
         "Temp Folder/Misc Invoices"): "no_match",
    }
    assert ilc.classify_low_confidence_row(row, parity_idx) == \
        "matcher_false_positive"


def test_classify_missing_metadata_artifact_when_square9_blank():
    row = _bucket_a_row(square9_name="", square9_parent_path="")
    assert ilc.classify_low_confidence_row(row, {}) == \
        "missing_metadata_artifact"


def test_classify_should_be_bucket_C_when_no_hub_doc_id():
    row = _bucket_a_row(best_hub_doc_id="", best_match_score="0.30")
    assert ilc.classify_low_confidence_row(row, {}) == "should_be_bucket_C"


def test_classify_remain_manual_review_for_unclassifiable_score():
    row = _bucket_a_row(
        best_match_score="0.10",
        best_match_reason="weak_evidence",
        root_cause="uncertain",
    )
    # Score < 0.55 + reason has none of the strong-token keywords +
    # root_cause is not low_confidence_match_ambiguous → manual_review.
    assert ilc.classify_low_confidence_row(row, {}) == "remain_manual_review"


# ---------------------------------------------------------------------------
# analyze() — counts + recommendation
# ---------------------------------------------------------------------------

def test_analyze_partitions_and_recommends_regeneration():
    rows: List[Dict[str, str]] = [
        # 2 above threshold → ignored
        _bucket_a_row(best_match_score="0.85", best_hub_doc_id="hi-1"),
        _bucket_a_row(best_match_score="0.92", best_hub_doc_id="hi-2"),
        # 3 real_ambiguous_match
        _bucket_a_row(best_match_score="0.55"),
        _bucket_a_row(best_match_score="0.55"),
        _bucket_a_row(best_match_score="0.55"),
        # 2 should_be_bucket_C
        _bucket_a_row(best_match_score="0.30", best_hub_doc_id=""),
        _bucket_a_row(best_match_score="0.20", best_hub_doc_id=""),
        # 1 missing_metadata_artifact
        _bucket_a_row(best_match_score="0.40",
                      square9_name="", square9_parent_path=""),
    ]
    parity = [_parity_row(match_bucket="match")]
    result = ilc.analyze(rows, parity, score_threshold=0.60)
    assert result["bucket_A_total"] == 8
    assert result["low_confidence_total"] == 6
    assert result["true_low_confidence_count"] == 3
    assert result["should_be_bucket_C_count"] == 2
    assert result["missing_metadata_artifact_count"] == 1
    assert result["should_regenerate_bucket_A_plan"] is True


def test_analyze_no_regeneration_when_all_legit():
    rows = [_bucket_a_row(best_match_score="0.55") for _ in range(5)]
    result = ilc.analyze(rows, parity_rows=[], score_threshold=0.60)
    assert result["true_low_confidence_count"] == 5
    assert result["matcher_false_positive_count"] == 0
    assert result["missing_metadata_artifact_count"] == 0
    assert result["should_be_bucket_C_count"] == 0
    assert result["should_regenerate_bucket_A_plan"] is False


def test_analyze_score_threshold_is_respected():
    rows = [_bucket_a_row(best_match_score="0.61")]
    result = ilc.analyze(rows, parity_rows=[], score_threshold=0.60)
    assert result["low_confidence_total"] == 0


def test_analyze_false_positive_path_via_parity_index():
    rows = [_bucket_a_row(best_match_score="0.45")]
    parity = [_parity_row(match_bucket="no_match")]
    result = ilc.analyze(rows, parity, score_threshold=0.60)
    assert result["matcher_false_positive_count"] == 1
    assert result["should_regenerate_bucket_A_plan"] is True


# ---------------------------------------------------------------------------
# Read-only guardrails
# ---------------------------------------------------------------------------

def test_module_does_not_import_pymongo_or_motor():
    import inspect
    src = inspect.getsource(ilc)
    assert "from pymongo" not in src
    assert "from motor" not in src


def test_module_makes_no_mutating_http_calls():
    import inspect
    src = inspect.getsource(ilc)
    forbidden = ("requests.post", "requests.put", "requests.delete",
                 "requests.patch", "httpx.post", "httpx.put",
                 "httpx.delete", "httpx.patch")
    for tok in forbidden:
        assert tok not in src
