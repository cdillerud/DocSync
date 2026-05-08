"""Tests for no_match_square9_audit (read-only, fixture-driven)."""
from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts import no_match_square9_audit as nms


# ---------------------------------------------------------------------------
# Fixture factories matching square9_hub_ap_parity_report row shapes
# ---------------------------------------------------------------------------

def _no_match_row(**overrides) -> Dict[str, str]:
    base = {
        "match_bucket": "no_match",
        "match_score": "0.0",
        "match_reason": "no_hub_counterpart",
        "square9_name": "Acme 12345.pdf",
        "square9_parent_path": "AP/Vendors/Acme",
        "square9_modified": "2026-04-15T10:00:00+00:00",
        "square9_web_url": "https://example/acme/12345",
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


def _matched_row(**overrides) -> Dict[str, str]:
    base = _no_match_row(**overrides)
    base["match_bucket"] = "strong_evidence_match"
    return base


def _hub_doc(**overrides) -> Dict[str, Any]:
    base = {
        "id": "hub-1",
        "vendor_canonical": "Acme Corp",
        "email_sender": "billing@acme.com",
        "invoice_number_clean": "12345",
        "file_name": "ACME-12345-Invoice.pdf",
        "mailbox_category": "AP",
        "doc_type": "AP_INVOICE",
        "suggested_job_type": "AP_Invoice",
        "created_utc": "2026-04-15T10:00:00+00:00",
    }
    base.update(overrides)
    return base


def _hub_corpus_start() -> dt.datetime:
    return dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------------------
# Tokenization / index unit tests
# ---------------------------------------------------------------------------

def test_digits_only_strips_leading_zeros():
    assert nms.digits_only("INV-00012345") == "12345"


def test_extract_invoice_token_candidates_filters_short_runs():
    cands = nms.extract_invoice_token_candidates("Acme 12 34567 PO123456")
    assert "34567" in cands
    assert "123456" in cands
    assert "12" not in cands


def test_build_hub_index_collects_all_token_kinds():
    index = nms.build_hub_index_from_docs([
        _hub_doc(id="h1", vendor_canonical="Acme Corp",
                 email_sender="billing@acme.com",
                 invoice_number_clean="12345",
                 file_name="ACME-12345.pdf"),
        _hub_doc(id="h2", vendor_canonical="Beta Ltd",
                 email_sender="ap@beta.io",
                 invoice_number_clean="98765",
                 file_name="beta-99.pdf"),
    ])
    assert index.doc_count == 2
    assert "acme" in index.vendor_tokens
    assert "beta" in index.vendor_tokens
    assert "acme" in index.sender_domain_roots
    assert "beta" in index.sender_domain_roots
    assert "12345" in index.invoice_digits
    assert "98765" in index.invoice_digits
    assert "12345" in index.by_invoice_digits


# ---------------------------------------------------------------------------
# Classification — one test per bucket
# ---------------------------------------------------------------------------

def test_non_ap_in_square9_corpus_when_folder_signals_treasury():
    row = _no_match_row(
        square9_name="Treasury Wire 2026-03.pdf",
        square9_parent_path="Treasury/Positive Pay")
    index = nms.build_hub_index_from_docs([_hub_doc()])
    verdict = nms.classify_doc(row, hub_corpus_start=_hub_corpus_start(),
                               index=index)
    assert verdict["bucket"] == "non_ap_in_square9_corpus"


def test_pre_hub_corpus_when_modified_predates_corpus_start():
    row = _no_match_row(square9_modified="2023-06-01T00:00:00+00:00")
    index = nms.build_hub_index_from_docs([_hub_doc()])
    verdict = nms.classify_doc(row, hub_corpus_start=_hub_corpus_start(),
                               index=index)
    assert verdict["bucket"] == "pre_hub_corpus"


def test_matcher_miss_with_hub_candidate_when_invoice_digits_match():
    row = _no_match_row(square9_name="Acme 12345.pdf",
                        square9_parent_path="AP/Vendors/Acme")
    index = nms.build_hub_index_from_docs([
        _hub_doc(id="hub-acme", invoice_number_clean="12345"),
    ])
    verdict = nms.classify_doc(row, hub_corpus_start=_hub_corpus_start(),
                               index=index)
    assert verdict["bucket"] == "matcher_miss_with_hub_candidate"
    assert verdict["best_hub_doc"]["hub_doc_id"] == "hub-acme"
    assert verdict["best_match_score"] >= 0.85


def test_matcher_miss_via_filename_token_overlap():
    row = _no_match_row(square9_name="Acme Corp Statement Q1 2026.pdf")
    index = nms.build_hub_index_from_docs([
        _hub_doc(id="hub-acme",
                 file_name="acme corp statement q1.pdf",
                 invoice_number_clean="",
                 vendor_canonical="Acme Corp",
                 email_sender="billing@acme.com"),
    ])
    verdict = nms.classify_doc(row, hub_corpus_start=_hub_corpus_start(),
                               index=index)
    assert verdict["bucket"] == "matcher_miss_with_hub_candidate"
    assert verdict["best_hub_doc"]["hub_doc_id"] == "hub-acme"


def test_vendor_not_in_hub_intake_when_no_overlap():
    row = _no_match_row(square9_name="Zzzcorp 99999.pdf",
                        square9_parent_path="AP/Vendors/Zzzcorp",
                        square9_web_url="https://x/zzz/99999")
    index = nms.build_hub_index_from_docs([
        _hub_doc(id="hub-acme", vendor_canonical="Acme Corp",
                 email_sender="billing@acme.com",
                 invoice_number_clean="12345",
                 file_name="acme.pdf"),
    ])
    verdict = nms.classify_doc(row, hub_corpus_start=_hub_corpus_start(),
                               index=index)
    assert verdict["bucket"] == "vendor_not_in_hub_intake"


def test_uncertain_when_vendor_known_but_no_evidence():
    row = _no_match_row(
        square9_name="Acme misc page.pdf",
        square9_parent_path="AP/Acme/Misc",
        square9_web_url="https://x/acme/misc",
    )
    index = nms.build_hub_index_from_docs([
        _hub_doc(id="hub-acme", vendor_canonical="Acme Corp",
                 email_sender="billing@acme.com",
                 invoice_number_clean="00000777",
                 file_name="totally different filename.pdf"),
    ])
    verdict = nms.classify_doc(row, hub_corpus_start=_hub_corpus_start(),
                               index=index)
    assert verdict["bucket"] == "uncertain"


# ---------------------------------------------------------------------------
# Projection math
# ---------------------------------------------------------------------------

def test_project_match_rates_correct_arithmetic():
    # matched=115, square_count=253, recoverable=20, excludable=80.
    proj = nms.project_match_rates(matched=115, square_count=253,
                                   recoverable=20, excludable=80)
    assert proj["baseline"] == round(115 / 253 * 100, 2)
    assert proj["after_exclude_only"] == round(115 / (253 - 80) * 100, 2)
    assert proj["after_improve_only"] == round((115 + 20) / 253 * 100, 2)
    assert proj["after_both"] == round(
        (115 + 20) / (253 - 80) * 100, 2)


def test_project_match_rates_denominator_floor_at_one():
    proj = nms.project_match_rates(matched=10, square_count=10,
                                   recoverable=0, excludable=10)
    # square_count - excludable = 0 -> floored to 1
    assert proj["after_exclude_only"] == 10 / 1 * 100


def test_decide_exit_code_matrix():
    assert nms.decide_exit_code({"after_both": 90}) == nms.EXIT_GO
    assert nms.decide_exit_code({"after_both": 75}) == nms.EXIT_MIXED
    assert nms.decide_exit_code({"after_both": 50}) == nms.EXIT_NO_GO
    assert nms.decide_exit_code({"after_both": 85}) == nms.EXIT_GO
    assert nms.decide_exit_code({"after_both": 70}) == nms.EXIT_MIXED


# ---------------------------------------------------------------------------
# build_summary integration
# ---------------------------------------------------------------------------

def _build_population_with_known_buckets() -> List[Dict[str, str]]:
    """Synthetic parity rows: 2 matched + a controlled no_match mix."""
    rows: List[Dict[str, str]] = []
    rows.append(_matched_row(square9_name="m1.pdf"))
    rows.append(_matched_row(square9_name="m2.pdf"))
    # 1 non_ap (treasury)
    rows.append(_no_match_row(
        square9_name="Treasury wire log Q1.pdf",
        square9_parent_path="Treasury",
        square9_modified="2026-04-15T10:00:00+00:00",
    ))
    # 1 pre_hub_corpus
    rows.append(_no_match_row(
        square9_name="Old Acme 99.pdf",
        square9_modified="2023-01-01T00:00:00+00:00",
    ))
    # 1 matcher_miss
    rows.append(_no_match_row(square9_name="Acme 12345.pdf",
                              square9_parent_path="AP/Vendors/Acme"))
    # 1 vendor_not_in_hub_intake
    rows.append(_no_match_row(square9_name="Zzz 9999.pdf",
                              square9_parent_path="AP/Vendors/Zzz",
                              square9_web_url="https://x/zzz/9999"))
    return rows


def test_build_summary_counts_buckets_and_projects_rates():
    rows = _build_population_with_known_buckets()
    no_match_rows = [r for r in rows if r["match_bucket"] == "no_match"]
    index = nms.build_hub_index_from_docs([
        _hub_doc(id="hub-acme", invoice_number_clean="12345"),
    ])
    classified = nms.classify_all(
        no_match_rows, hub_corpus_start=_hub_corpus_start(), index=index)
    summary = nms.build_summary(
        parity_rows=rows,
        classified=classified,
        hub_corpus_start=_hub_corpus_start(),
        hub_doc_count=index.doc_count,
        source_csv="fake.csv",
    )
    assert summary["matched"] == 2
    assert summary["square_count"] == 6
    assert summary["no_match_count"] == 4
    bc = summary["bucket_counts"]
    assert bc["non_ap_in_square9_corpus"] == 1
    assert bc["pre_hub_corpus"] == 1
    assert bc["matcher_miss_with_hub_candidate"] == 1
    assert bc["vendor_not_in_hub_intake"] == 1
    # excludable = non_ap + pre_hub + vendor_not = 3.
    assert summary["excludable"] == 3
    assert summary["recoverable_matcher_miss_count"] == 1
    proj = summary["projected_match_rates"]
    assert proj["baseline"] == round(2 / 6 * 100, 2)
    # after_both = (2+1) / (6-3) = 100%
    assert proj["after_both"] == 100.0
    assert summary["exit_code"] == nms.EXIT_GO


def test_build_summary_exit_no_go_when_after_both_below_seventy():
    # 5 matched, 100 no_match, only 1 excludable, 0 recoverable.
    rows: List[Dict[str, str]] = (
        [_matched_row(square9_name=f"m{i}.pdf") for i in range(5)]
        + [_no_match_row(
            square9_name=f"unknown-{i}.pdf",
            square9_parent_path=f"AP/Foo{i}",
            square9_web_url=f"https://x/foo{i}",
            square9_modified="2026-04-15T10:00:00+00:00",
        ) for i in range(100)]
    )
    no_match_rows = [r for r in rows if r["match_bucket"] == "no_match"]
    # Empty Hub corpus -> all 100 hit vendor_not_in_hub_intake.
    index = nms.build_hub_index_from_docs([])
    classified = nms.classify_all(
        no_match_rows, hub_corpus_start=_hub_corpus_start(), index=index)
    summary = nms.build_summary(
        parity_rows=rows,
        classified=classified,
        hub_corpus_start=_hub_corpus_start(),
        hub_doc_count=0,
        source_csv="fake.csv",
    )
    # vendor_not_in_hub_intake counts as excludable; with all 100 in
    # that bucket, after_both = 5 / max(105-100, 1) = 100% which would
    # actually exit_go. Use a more realistic scenario: half excludable.
    # Re-build with half non_ap + half uncertain to exercise NO_GO.
    rows2: List[Dict[str, str]] = (
        [_matched_row(square9_name=f"m{i}.pdf") for i in range(5)]
        + [_no_match_row(
            square9_name=f"unknown-{i}.pdf",
            square9_parent_path=f"AP/Acme/{i}",
            square9_web_url=f"https://x/acme/{i}",
            square9_modified="2026-04-15T10:00:00+00:00",
        ) for i in range(100)]
    )
    nm2 = [r for r in rows2 if r["match_bucket"] == "no_match"]
    # Hub corpus knows about Acme -> uncertain bucket (vendor known but
    # no invoice/filename evidence).
    idx2 = nms.build_hub_index_from_docs([_hub_doc(
        id="hub-acme", vendor_canonical="Acme Corp",
        email_sender="billing@acme.com",
        invoice_number_clean="888888",
        file_name="totally-different.pdf",
    )])
    classified2 = nms.classify_all(
        nm2, hub_corpus_start=_hub_corpus_start(), index=idx2)
    summary2 = nms.build_summary(
        parity_rows=rows2, classified=classified2,
        hub_corpus_start=_hub_corpus_start(),
        hub_doc_count=idx2.doc_count, source_csv="fake.csv",
    )
    # 100 uncertain, 0 excludable, 0 recoverable -> after_both = 5/105
    assert summary2["bucket_counts"]["uncertain"] == 100
    assert summary2["projected_match_rates"]["after_both"] < 70
    assert summary2["exit_code"] == nms.EXIT_NO_GO


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def test_write_csv_emits_per_row_columns(tmp_path: Path):
    rows = _build_population_with_known_buckets()
    no_match_rows = [r for r in rows if r["match_bucket"] == "no_match"]
    index = nms.build_hub_index_from_docs([
        _hub_doc(id="hub-acme", invoice_number_clean="12345"),
    ])
    classified = nms.classify_all(
        no_match_rows, hub_corpus_start=_hub_corpus_start(), index=index)
    out = tmp_path / "audit.csv"
    nms.write_csv(str(out), classified)
    with open(out, newline="", encoding="utf-8") as f:
        rows_out = list(csv.DictReader(f))
    assert len(rows_out) == 4
    assert {"bucket", "recommended_action", "best_hub_doc_id",
            "best_match_score", "best_match_reason"}.issubset(
                rows_out[0].keys())


def test_write_json_emits_full_summary(tmp_path: Path):
    rows = _build_population_with_known_buckets()
    no_match_rows = [r for r in rows if r["match_bucket"] == "no_match"]
    index = nms.build_hub_index_from_docs([
        _hub_doc(id="hub-acme", invoice_number_clean="12345"),
    ])
    classified = nms.classify_all(
        no_match_rows, hub_corpus_start=_hub_corpus_start(), index=index)
    summary = nms.build_summary(
        parity_rows=rows, classified=classified,
        hub_corpus_start=_hub_corpus_start(),
        hub_doc_count=index.doc_count, source_csv="fake.csv",
    )
    out = tmp_path / "audit.json"
    nms.write_json(str(out), summary)
    payload = json.loads(out.read_text())
    for k in ("source_csv", "matched", "square_count", "no_match_count",
              "bucket_counts", "projected_match_rates",
              "top_examples_by_bucket", "exit_code", "blockers", "warnings",
              "top_square9_parent_paths", "recommended_action_counts",
              "total_no_match", "excludable",
              "recoverable_matcher_miss_count"):
        assert k in payload, k


def test_write_md_renders_tables_and_recommendations(tmp_path: Path):
    rows = _build_population_with_known_buckets()
    no_match_rows = [r for r in rows if r["match_bucket"] == "no_match"]
    index = nms.build_hub_index_from_docs([
        _hub_doc(id="hub-acme", invoice_number_clean="12345"),
    ])
    classified = nms.classify_all(
        no_match_rows, hub_corpus_start=_hub_corpus_start(), index=index)
    summary = nms.build_summary(
        parity_rows=rows, classified=classified,
        hub_corpus_start=_hub_corpus_start(),
        hub_doc_count=index.doc_count, source_csv="fake.csv",
    )
    out = tmp_path / "audit.md"
    nms.write_md(str(out), summary)
    text = out.read_text()
    assert "# Square9-side no_match audit" in text
    assert "## Bucket counts" in text
    assert "## Projected match rates" in text
    assert "## Recommended next actions" in text
    for b in nms.BUCKET_ORDER:
        assert b in text


# ---------------------------------------------------------------------------
# CLI smoke (uses mongomock for the index-build path)
# ---------------------------------------------------------------------------

def test_main_writes_three_artifacts_and_returns_exit_code(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import mongomock

    rows = _build_population_with_known_buckets()
    parity = tmp_path / "square9_hub_ap_parity.csv"
    fieldnames = list(_no_match_row().keys())
    with open(parity, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    coll = mongomock.MongoClient().db.hub_documents
    coll.insert_one(_hub_doc(id="hub-acme", invoice_number_clean="12345"))

    monkeypatch.setattr(
        "scripts.no_match_square9_audit.get_hub_documents_collection",
        lambda: coll,
    )

    csv_out = tmp_path / "out.csv"
    json_out = tmp_path / "out.json"
    md_out = tmp_path / "out.md"
    monkeypatch.setattr("sys.argv", [
        "no_match_square9_audit.py",
        "--parity-csv", str(parity),
        "--out-csv", str(csv_out),
        "--json", str(json_out),
        "--md", str(md_out),
    ])
    rc = nms.main()
    assert rc in (nms.EXIT_GO, nms.EXIT_MIXED, nms.EXIT_NO_GO)
    payload = json.loads(json_out.read_text())
    assert payload["matched"] == 2
    assert payload["no_match_count"] == 4
    assert csv_out.exists() and md_out.exists()



# ---------------------------------------------------------------------------
# square9_web_url propagation (downstream pipelines depend on it)
# ---------------------------------------------------------------------------

def test_classify_all_carries_square9_web_url_into_each_row():
    """Each row produced by classify_all must preserve the original
    ``square9_web_url`` so downstream pipelines (deep_triage, body
    reconciliation probe) can reach the SharePoint document."""
    url = "https://example.sharepoint.com/sites/x/Documents/acme-12345.pdf"
    rows = [_no_match_row(
        square9_name="Acme 12345.pdf",
        square9_parent_path="AP/Vendors/Acme",
        square9_web_url=url,
    )]
    index = nms.build_hub_index_from_docs([
        _hub_doc(id="hub-acme", invoice_number_clean="12345"),
    ])
    classified = nms.classify_all(
        rows, hub_corpus_start=_hub_corpus_start(), index=index)
    assert classified, "expected at least one classified row"
    assert all(c.get("square9_web_url") == url for c in classified)


def test_output_csv_columns_include_square9_web_url():
    assert "square9_web_url" in nms.OUTPUT_CSV_COLUMNS


def test_write_csv_preserves_square9_web_url_end_to_end(tmp_path: Path):
    url = "https://example.sharepoint.com/sites/x/Documents/acme-12345.pdf"
    rows = [_no_match_row(
        square9_name="Acme 12345.pdf",
        square9_web_url=url,
    )]
    index = nms.build_hub_index_from_docs([_hub_doc(id="hub-acme")])
    classified = nms.classify_all(
        rows, hub_corpus_start=_hub_corpus_start(), index=index)
    out = tmp_path / "audit.csv"
    nms.write_csv(str(out), classified)
    with open(out, encoding="utf-8") as f:
        out_rows = list(csv.DictReader(f))
    assert out_rows
    assert out_rows[0]["square9_web_url"] == url


def test_write_json_top_examples_preserve_square9_web_url(tmp_path: Path):
    url = "https://example.sharepoint.com/sites/x/Documents/acme-12345.pdf"
    rows = [_no_match_row(
        square9_name="Acme 12345.pdf",
        square9_web_url=url,
        square9_parent_path="AP/Vendors/Acme",
    )]
    index = nms.build_hub_index_from_docs([
        _hub_doc(id="hub-acme", invoice_number_clean="12345"),
    ])
    classified = nms.classify_all(
        rows, hub_corpus_start=_hub_corpus_start(), index=index)
    summary = nms.build_summary(
        parity_rows=rows + [_matched_row(square9_name="m1.pdf")],
        classified=classified,
        hub_corpus_start=_hub_corpus_start(),
        hub_doc_count=index.doc_count,
        source_csv="fake.csv",
    )
    out = tmp_path / "audit.json"
    nms.write_json(str(out), summary)
    payload = json.loads(out.read_text())
    found = []
    for bucket_examples in payload["top_examples_by_bucket"].values():
        for ex in bucket_examples:
            if ex.get("square9_web_url"):
                found.append(ex["square9_web_url"])
    assert url in found
