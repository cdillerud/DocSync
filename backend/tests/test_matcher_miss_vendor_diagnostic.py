"""Tests for matcher_miss_vendor_diagnostic (read-only, fixture-driven)."""
from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts import matcher_miss_vendor_diagnostic as mmd


# ---------------------------------------------------------------------------
# Row factories matching square9_hub_ap_parity_report row shapes
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
        "hub_file_name": "TUM-12345-Invoice.pdf",
        "hub_sharepoint_web_url": "",
        "hub_sharepoint_folder_path": "Freight Issues/Tumalocreek",
        "hub_routing_status": "auto_process",
        "hub_routing_reason": "",
        "hub_doc_type": "AP_INVOICE",
        "hub_suggested_job_type": "AP_Invoice",
        "hub_classification_method": "ai_classifier:gpt-4o",
        "hub_vendor_canonical": "Tumalocreek Freight",
        "hub_invoice_number_clean": "12345",
        "hub_amount_float": "1500.00",
        "hub_po_number_clean": "",
        "hub_email_sender": "billing@tumalocreek.us",
        "hub_email_subject": "Invoice 12345",
        "hub_created_utc": "2026-04-15T10:00:00+00:00",
    }
    base.update({k: ("" if v is None else str(v)) for k, v in overrides.items()})
    return base


def _square9_no_match_row(**overrides) -> Dict[str, str]:
    base = {
        "match_bucket": "no_match",
        "match_score": "0.0",
        "match_reason": "no_hub_counterpart",
        "square9_name": "Tumalo Creek 12345.pdf",
        "square9_parent_path": "AP/Vendors/TumaloCreek",
        "square9_modified": "2026-04-16T08:00:00+00:00",
        "square9_web_url": "https://example/tumalo/12345",
        "hub_doc_id": "",
        "hub_file_name": "",
        "hub_sharepoint_web_url": "",
        "hub_sharepoint_folder_path": "",
        "hub_routing_status": "",
        "hub_routing_reason": "",
        "hub_doc_type": "",
        "hub_suggested_job_type": "",
        "hub_classification_method": "",
        "hub_vendor_canonical": "",
        "hub_invoice_number_clean": "",
        "hub_amount_float": "",
        "hub_po_number_clean": "",
        "hub_email_sender": "",
        "hub_email_subject": "",
        "hub_created_utc": "",
    }
    base.update({k: ("" if v is None else str(v)) for k, v in overrides.items()})
    return base


# ---------------------------------------------------------------------------
# Normalizer / scoring unit tests
# ---------------------------------------------------------------------------

def test_digits_only_strips_non_digits_and_leading_zeros():
    assert mmd.digits_only("INV-00012345") == "12345"
    assert mmd.digits_only("ABC") == ""
    assert mmd.digits_only("") == ""


def test_normalize_filename_lowercases_and_strips_extension():
    assert mmd.normalize_filename("TUM_12345-Invoice.PDF") == "tum 12345 invoice"


def test_jaccard_handles_empty_inputs():
    assert mmd.jaccard([], ["a"]) == 0.0
    assert mmd.jaccard(["a"], ["a"]) == 1.0
    assert mmd.jaccard(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)


def test_vendor_root_from_sender_uses_domain_root():
    assert mmd.vendor_root_from_sender("billing@tumalocreek.us") == "tumalocreek"
    assert mmd.vendor_root_from_sender("a@b.co.uk") == "b"
    assert mmd.vendor_root_from_sender("invalid") == ""


def test_date_proximity_full_score_within_seven_days():
    near = mmd.date_proximity_score(
        "2026-04-15T10:00:00+00:00", "2026-04-17T10:00:00+00:00")
    assert near == 1.0
    far = mmd.date_proximity_score(
        "2026-04-15T10:00:00+00:00", "2027-04-15T10:00:00+00:00")
    assert far == 0.0


# ---------------------------------------------------------------------------
# score_pair / best_candidate
# ---------------------------------------------------------------------------

def test_score_pair_strong_when_invoice_and_filename_align():
    hub = _hub_only_row()
    sq = _square9_no_match_row()
    score, breakdown, signals = mmd.score_pair(hub, sq, "billing@tumalocreek.us")
    assert score >= 0.85
    assert breakdown["invoice_number_match"] == 1.0
    assert "invoice_number_match" in signals


def test_score_pair_zero_when_no_overlap():
    hub = _hub_only_row(
        hub_invoice_number_clean="999",
        hub_file_name="random.pdf",
        hub_vendor_canonical="Other Co",
        hub_created_utc="2024-01-01T00:00:00+00:00",
    )
    sq = _square9_no_match_row(
        square9_name="Acme 5555.pdf",
        square9_parent_path="AP/Vendors/Acme",
        square9_modified="2026-01-01T00:00:00+00:00",
    )
    score, breakdown, _ = mmd.score_pair(hub, sq, "billing@tumalocreek.us")
    assert score == 0.0
    assert all(v == 0 for v in breakdown.values())


def test_best_candidate_returns_highest_scoring_match():
    hub = _hub_only_row()
    weak_sq = _square9_no_match_row(
        square9_name="Other 99.pdf",
        square9_parent_path="AP/Other",
        square9_modified="2025-01-01T00:00:00+00:00",
    )
    strong_sq = _square9_no_match_row()
    sq, score, _, _ = mmd.best_candidate(
        hub, [weak_sq, strong_sq], "billing@tumalocreek.us")
    assert sq is strong_sq
    assert score >= 0.85


def test_best_candidate_handles_empty_corpus():
    hub = _hub_only_row()
    sq, score, breakdown, signals = mmd.best_candidate(
        hub, [], "billing@tumalocreek.us")
    assert sq is None
    assert score == 0.0
    assert breakdown == {}
    assert signals == []


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def test_filter_hub_for_sender_drops_other_senders_and_other_buckets():
    rows = [
        _hub_only_row(hub_email_sender="billing@tumalocreek.us"),
        _hub_only_row(hub_email_sender="other@x.com",
                      hub_doc_id="d2", hub_file_name="x.pdf"),
        _square9_no_match_row(),  # match_bucket=no_match
    ]
    out = mmd.filter_hub_for_sender(rows, "billing@tumalocreek.us")
    assert len(out) == 1
    assert out[0]["hub_email_sender"] == "billing@tumalocreek.us"


def test_filter_square9_by_fragments_matches_name_or_parent_path():
    rows = [
        _square9_no_match_row(square9_name="Tumalo Creek 1.pdf",
                              square9_parent_path="AP/Other"),
        _square9_no_match_row(square9_name="Random.pdf",
                              square9_parent_path="AP/TumaloCreek"),
        _square9_no_match_row(square9_name="Acme 5.pdf",
                              square9_parent_path="AP/Acme",
                              square9_web_url="https://x"),
        _hub_only_row(),  # match_bucket=hub_only -> should be dropped
    ]
    out = mmd.filter_square9_by_fragments(rows, ["tumalo"])
    names = sorted([r["square9_name"] for r in out])
    assert names == ["Random.pdf", "Tumalo Creek 1.pdf"]


def test_filter_square9_by_fragments_returns_empty_when_no_fragments():
    rows = [_square9_no_match_row()]
    assert mmd.filter_square9_by_fragments(rows, []) == []
    assert mmd.filter_square9_by_fragments(rows, [""]) == []


# ---------------------------------------------------------------------------
# run_diagnostic + exit-code matrix
# ---------------------------------------------------------------------------

def _build_population(strong: int, weak: int, irrelevant_hub: int = 0
                      ) -> List[Dict[str, str]]:
    """Build a synthetic parity_rows population: ``strong`` Hub docs that
    each have a matching Square9 candidate, ``weak`` Hub docs that have
    no Square9 candidate, plus ``irrelevant_hub`` other-sender Hub-only
    rows (should be filtered out)."""
    rows: List[Dict[str, str]] = []
    for i in range(strong):
        inv = f"{1000 + i}"
        rows.append(_hub_only_row(
            hub_doc_id=f"hub-strong-{i}",
            hub_file_name=f"TUM-{inv}-Invoice.pdf",
            hub_invoice_number_clean=inv,
            hub_created_utc="2026-04-15T10:00:00+00:00",
        ))
        rows.append(_square9_no_match_row(
            square9_name=f"Tumalo Creek {inv}.pdf",
            square9_parent_path="AP/Vendors/TumaloCreek",
            square9_modified="2026-04-16T08:00:00+00:00",
        ))
    for i in range(weak):
        rows.append(_hub_only_row(
            hub_doc_id=f"hub-weak-{i}",
            hub_file_name=f"weak-{i}.pdf",
            hub_invoice_number_clean=f"{99000 + i}",
            hub_created_utc="2026-04-15T10:00:00+00:00",
        ))
    for i in range(irrelevant_hub):
        rows.append(_hub_only_row(
            hub_doc_id=f"hub-other-{i}",
            hub_file_name=f"other-{i}.pdf",
            hub_email_sender="other@x.com",
            hub_invoice_number_clean=f"{77000 + i}",
        ))
    return rows


def test_run_diagnostic_exit_zero_when_all_strong():
    rows = _build_population(strong=5, weak=0, irrelevant_hub=2)
    result = mmd.run_diagnostic(
        rows, "billing@tumalocreek.us", ["tumalo"])
    assert result["hub_docs_considered"] == 5
    assert result["square9_candidates_considered"] == 5
    assert result["strong_candidate_count"] == 5
    assert result["strong_candidate_rate"] == 1.0
    assert result["exit_code"] == mmd.EXIT_LIKELY_MATCHER_FIX
    assert result["recommended_matcher_rule"]
    assert "matcher" in result["conclusion"].lower()


def test_run_diagnostic_exit_two_when_no_strong():
    rows = _build_population(strong=0, weak=5)
    result = mmd.run_diagnostic(
        rows, "billing@tumalocreek.us", ["tumalo"])
    assert result["strong_candidate_count"] == 0
    assert result["exit_code"] == mmd.EXIT_LIKELY_SCOPE_GAP
    assert result["recommended_matcher_rule"] == ""
    assert "scope_gap" in result["conclusion"] or \
        "scope gap" in result["conclusion"]


def test_run_diagnostic_exit_one_when_partial():
    # 2 strong / 3 weak -> 40% strong rate, between 30% and 80%.
    rows = _build_population(strong=2, weak=3)
    result = mmd.run_diagnostic(
        rows, "billing@tumalocreek.us", ["tumalo"])
    assert result["strong_candidate_count"] == 2
    assert result["exit_code"] == mmd.EXIT_MIXED


def test_run_diagnostic_excludes_other_senders_and_other_fragments():
    """Non-tumalo Hub docs are filtered by --sender; non-tumalo Square9
    docs are filtered by --fragments."""
    rows = _build_population(strong=1, weak=0)
    # Add a Hub doc + Square9 doc that both look like Acme. Neither
    # should be considered.
    rows.append(_hub_only_row(
        hub_doc_id="acme-hub",
        hub_email_sender="billing@acme.com",
        hub_file_name="ACME-7777.pdf",
        hub_invoice_number_clean="7777",
        hub_vendor_canonical="Acme Corp",
    ))
    rows.append(_square9_no_match_row(
        square9_name="ACME 7777.pdf",
        square9_parent_path="AP/Vendors/Acme",
        square9_web_url="https://example/acme/7777",
    ))
    result = mmd.run_diagnostic(
        rows, "billing@tumalocreek.us", ["tumalo"])
    assert result["hub_docs_considered"] == 1  # acme dropped
    assert result["square9_candidates_considered"] == 1  # acme dropped


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def test_write_csv_emits_full_per_hub_columns(tmp_path: Path):
    rows = _build_population(strong=2, weak=0)
    result = mmd.run_diagnostic(rows, "billing@tumalocreek.us", ["tumalo"])
    out = tmp_path / "diag.csv"
    mmd.write_csv(str(out), result["per_hub"])
    with open(out, newline="", encoding="utf-8") as f:
        rows_out = list(csv.DictReader(f))
    assert len(rows_out) == 2
    expected_cols = {
        "hub_doc_id", "best_square9_name", "score", "score_breakdown",
        "candidate_match_reason", "suggested_matcher_rule",
    }
    assert expected_cols.issubset(rows_out[0].keys())


def test_write_json_includes_summary_and_excludes_per_hub(tmp_path: Path):
    rows = _build_population(strong=1, weak=0)
    result = mmd.run_diagnostic(rows, "billing@tumalocreek.us", ["tumalo"])
    out = tmp_path / "diag.json"
    mmd.write_json(str(out), result, "fake.csv")
    payload = json.loads(out.read_text())
    for k in ("sender", "fragments", "hub_docs_considered",
              "square9_candidates_considered", "strong_candidate_count",
              "strong_candidate_rate", "score_histogram",
              "top_mismatch_reasons", "recommended_matcher_rule",
              "conclusion", "exit_code", "source_csv"):
        assert k in payload, k
    assert "per_hub" not in payload  # large detail belongs in CSV


def test_write_md_renders_examples_and_summary(tmp_path: Path):
    rows = _build_population(strong=2, weak=1)
    result = mmd.run_diagnostic(rows, "billing@tumalocreek.us", ["tumalo"])
    out = tmp_path / "diag.md"
    mmd.write_md(str(out), result, "fake.csv")
    text = out.read_text()
    assert "# Matcher-miss vendor diagnostic" in text
    assert "## Conclusion" in text
    assert "## Score histogram" in text
    assert "## Side-by-side examples" in text
    # The strong candidates' invoice numbers appear in side-by-side rows.
    assert "1000" in text or "1001" in text


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

def test_main_writes_three_artifacts_and_returns_exit_code(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rows = _build_population(strong=4, weak=1, irrelevant_hub=1)
    parity = tmp_path / "square9_hub_ap_parity.csv"
    fieldnames = list(_hub_only_row().keys())
    with open(parity, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    csv_out = tmp_path / "diag.csv"
    json_out = tmp_path / "diag.json"
    md_out = tmp_path / "diag.md"
    monkeypatch.setattr("sys.argv", [
        "matcher_miss_vendor_diagnostic.py",
        "--parity-csv", str(parity),
        "--csv-out", str(csv_out),
        "--json-out", str(json_out),
        "--md-out", str(md_out),
    ])
    rc = mmd.main()
    # 4 strong / 5 considered = 80% strong rate -> exit 0.
    assert rc == mmd.EXIT_LIKELY_MATCHER_FIX
    payload = json.loads(json_out.read_text())
    assert payload["hub_docs_considered"] == 5
    assert payload["strong_candidate_count"] == 4
    assert csv_out.exists() and md_out.exists()
