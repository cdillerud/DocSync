"""Tests for uncertain_square9_deep_triage (read-only, fixture-driven)."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts import uncertain_square9_deep_triage as dt


# ---------------------------------------------------------------------------
# Fixture factories
# ---------------------------------------------------------------------------

def _audit_uncertain_row(**overrides) -> Dict[str, str]:
    base = {
        "bucket": "uncertain",
        "recommended_action": "manual_review",
        "square9_name": "Acme 12345.pdf",
        "square9_parent_path": "AP/Vendors/Acme",
        "square9_modified": "2026-04-15T10:00:00+00:00",
        "extracted_invoice_tokens": "12345",
        "extracted_vendor_tokens": "acme",
        "best_hub_doc_id": "",
        "best_hub_file_name": "",
        "best_hub_mailbox_category": "",
        "best_hub_doc_type": "",
        "best_hub_suggested_job_type": "",
        "best_hub_created_utc": "",
        "best_match_score": "0.0",
        "best_match_reason": "",
        "notes": "",
    }
    # Add square9_web_url for haystack tests.
    base["square9_web_url"] = ""
    base.update({k: ("" if v is None else str(v))
                 for k, v in overrides.items()})
    return base


def _hub_doc(**overrides) -> Dict[str, Any]:
    base = {
        "id": "hub-1", "vendor_canonical": "Acme Corp",
        "email_sender": "billing@acme.com",
        "invoice_number_clean": "", "po_number_clean": "",
        "amount_float": "", "file_name": "",
        "email_subject": "", "sharepoint_folder_path": "",
        "mailbox_category": "AP", "doc_type": "AP_INVOICE",
        "suggested_job_type": "AP_Invoice",
        "created_utc": "2026-04-15T10:00:00+00:00",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tokenization unit tests
# ---------------------------------------------------------------------------

def test_extract_invoice_tokens_returns_long_digit_runs():
    out = dt.extract_invoice_tokens("Acme 12 34567 inv-INV00099")
    assert "34567" in out
    assert "00099" in out
    assert "12" not in out


def test_extract_po_tokens_finds_PO_prefix_then_token():
    assert dt.extract_po_tokens("PO 4567A invoice 12345") == ["4567A"]
    assert dt.extract_po_tokens("p.o. 998877") == ["998877"]
    assert dt.extract_po_tokens("po#: ABC1234") == ["ABC1234"]
    assert dt.extract_po_tokens("no po here") == []


def test_extract_amount_tokens_handles_commas_and_decimals():
    out = dt.extract_amount_tokens("Total $1,234.56 paid 999.00")
    assert "1234.56" in out
    assert "999.00" in out


def test_jaccard_basic():
    assert dt.jaccard(["a", "b"], ["a", "c"]) == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# Hub index build
# ---------------------------------------------------------------------------

def test_build_hub_index_indexes_all_signal_kinds():
    idx = dt.build_hub_index_from_docs([
        _hub_doc(id="h1", vendor_canonical="Acme Corp",
                 email_sender="billing@acme.com",
                 invoice_number_clean="12345",
                 po_number_clean="PO99",
                 amount_float="500.00",
                 file_name="acme-12345.pdf",
                 email_subject="Acme invoice 12345",
                 sharepoint_folder_path="AP/Vendors/Acme"),
    ])
    assert idx.doc_count == 1
    assert "acme" in idx.vendor_tokens
    assert "acme" in idx.sender_domain_roots
    assert "12345" in idx.by_invoice_digits
    assert "PO99" in idx.by_po_token
    assert "500.00" in idx.by_amount


# ---------------------------------------------------------------------------
# Classification — one test per bucket
# ---------------------------------------------------------------------------

def test_recoverable_via_invoice_digits_match():
    row = _audit_uncertain_row(
        square9_name="Acme inv 12345.pdf",
        square9_parent_path="AP/Vendors/Acme")
    idx = dt.build_hub_index_from_docs([
        _hub_doc(id="hub-x", invoice_number_clean="12345"),
    ])
    v = dt.classify_doc(row, idx)
    assert v["bucket"] == "recoverable_matcher_miss"
    assert v["match_signal"] == "invoice_digits"
    assert v["best_hub"]["hub_doc_id"] == "hub-x"


def test_recoverable_via_po_match():
    row = _audit_uncertain_row(
        square9_name="Vendor doc PO 4567A.pdf",
        square9_parent_path="AP/Vendors/Acme",
        extracted_invoice_tokens="")
    idx = dt.build_hub_index_from_docs([
        _hub_doc(id="hub-po", vendor_canonical="Acme",
                 invoice_number_clean="",
                 po_number_clean="4567A"),
    ])
    v = dt.classify_doc(row, idx)
    assert v["bucket"] == "recoverable_matcher_miss"
    assert v["match_signal"] == "po_token"
    assert v["best_hub"]["hub_doc_id"] == "hub-po"


def test_recoverable_via_filename_jaccard():
    row = _audit_uncertain_row(
        square9_name="Acme statement Q1 close.pdf",
        square9_parent_path="AP/Acme",
        extracted_invoice_tokens="")
    idx = dt.build_hub_index_from_docs([
        _hub_doc(id="hub-fn", file_name="acme statement q1 close.pdf",
                 invoice_number_clean="",
                 vendor_canonical="Acme"),
    ])
    v = dt.classify_doc(row, idx)
    assert v["bucket"] == "recoverable_matcher_miss"
    assert v["match_signal"] == "filename_jaccard"
    assert v["best_hub"]["hub_doc_id"] == "hub-fn"


def test_square9_scope_exclusion_via_treasury_keyword():
    row = _audit_uncertain_row(
        square9_name="Treasury wire log Q1.pdf",
        square9_parent_path="Treasury/Wires")
    idx = dt.build_hub_index_from_docs([_hub_doc()])
    v = dt.classify_doc(row, idx)
    assert v["bucket"] == "square9_scope_exclusion"
    assert "treasury" in v["reason"]


def test_square9_scope_exclusion_via_template_keyword():
    row = _audit_uncertain_row(
        square9_name="AP invoice template.pdf",
        square9_parent_path="AP/Templates")
    idx = dt.build_hub_index_from_docs([_hub_doc()])
    v = dt.classify_doc(row, idx)
    assert v["bucket"] == "square9_scope_exclusion"


def test_true_intake_gap_when_vendor_absent_from_hub():
    row = _audit_uncertain_row(
        square9_name="Zzzcorp 99999.pdf",
        square9_parent_path="AP/Vendors/Zzzcorp",
        square9_web_url="https://x/zzz/99999")
    idx = dt.build_hub_index_from_docs([
        _hub_doc(id="hub-acme", vendor_canonical="Acme Corp",
                 email_sender="billing@acme.com",
                 invoice_number_clean="55555"),
    ])
    v = dt.classify_doc(row, idx)
    assert v["bucket"] == "true_intake_gap"
    assert v["match_signal"] == "no_vendor_overlap"


def test_manual_review_when_vendor_known_but_no_evidence():
    row = _audit_uncertain_row(
        square9_name="Acme misc page.pdf",
        square9_parent_path="AP/Acme/Misc",
        square9_web_url="https://x/acme/misc")
    idx = dt.build_hub_index_from_docs([
        _hub_doc(id="hub-acme", vendor_canonical="Acme Corp",
                 email_sender="billing@acme.com",
                 invoice_number_clean="00000777",
                 file_name="totally-different.pdf",
                 email_subject="random",
                 sharepoint_folder_path="AR/Other"),
    ])
    v = dt.classify_doc(row, idx)
    assert v["bucket"] == "manual_review_required"


# ---------------------------------------------------------------------------
# Projection math
# ---------------------------------------------------------------------------

def test_project_match_rates_combines_prior_and_new_correctly():
    proj = dt.project_match_rates(
        matched=115, square_count=253,
        prior_recoverable=19, prior_excludable=14,
        new_recoverable=50, new_excludable=30,
    )
    assert proj["current"] == round(115 / 253 * 100, 2)
    assert proj["after_recoverable_only"] == round(
        (115 + 19 + 50) / 253 * 100, 2)
    assert proj["after_exclusions_only"] == round(
        115 / (253 - 14 - 30) * 100, 2)
    assert proj["after_both"] == round(
        (115 + 19 + 50) / (253 - 14 - 30) * 100, 2)


def test_decide_exit_code_matrix():
    assert dt.decide_exit_code(90.0) == dt.EXIT_GO
    assert dt.decide_exit_code(85.0) == dt.EXIT_GO
    assert dt.decide_exit_code(75.0) == dt.EXIT_MIXED
    assert dt.decide_exit_code(70.0) == dt.EXIT_MIXED
    assert dt.decide_exit_code(50.0) == dt.EXIT_NO_GO


# ---------------------------------------------------------------------------
# build_summary integration
# ---------------------------------------------------------------------------

def _mixed_uncertain_population() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    # 1 recoverable via invoice digits
    rows.append(_audit_uncertain_row(
        square9_name="Acme 12345.pdf",
        square9_parent_path="AP/Vendors/Acme"))
    # 1 scope exclusion (treasury)
    rows.append(_audit_uncertain_row(
        square9_name="Treasury wire log.pdf",
        square9_parent_path="Treasury",
        extracted_invoice_tokens=""))
    # 1 true intake gap (no vendor overlap)
    rows.append(_audit_uncertain_row(
        square9_name="ZzzCorp 99999.pdf",
        square9_parent_path="AP/ZzzCorp",
        square9_web_url="https://x/zzz",
        extracted_invoice_tokens="99999"))
    # 1 manual review
    rows.append(_audit_uncertain_row(
        square9_name="Acme misc.pdf",
        square9_parent_path="AP/Acme/Misc",
        square9_web_url="https://x/acme/misc",
        extracted_invoice_tokens=""))
    return rows


def test_build_summary_counts_all_buckets_and_projects():
    rows = _mixed_uncertain_population()
    idx = dt.build_hub_index_from_docs([
        _hub_doc(id="hub-acme", vendor_canonical="Acme Corp",
                 email_sender="billing@acme.com",
                 invoice_number_clean="12345",
                 file_name="x.pdf"),
    ])
    classified = dt.classify_all(rows, idx)
    s = dt.build_summary(
        classified=classified,
        matched=115, square_count=253,
        prior_recoverable=19, prior_excludable=14,
        source_audit_csv="audit.csv", source_audit_json="audit.json",
        hub_doc_count=idx.doc_count,
    )
    assert s["total_uncertain"] == 4
    assert s["recoverable_matcher_miss_count"] == 1
    assert s["square9_scope_exclusion_count"] == 1
    assert s["true_intake_gap_count"] == 1
    assert s["manual_review_required_count"] == 1
    proj = s["projected_match_rates"]
    # exclusions = 14 prior + 1 scope_exclusion + 1 intake_gap = 16
    # recoverable = 19 + 1 = 20
    assert proj["after_both"] == round(
        (115 + 20) / (253 - 16) * 100, 2)


def test_build_summary_exit_go_when_after_both_above_threshold():
    # Construct a synthetic population: lots of exclusions to push
    # after_both above 85%.
    rows: List[Dict[str, str]] = []
    for i in range(95):
        rows.append(_audit_uncertain_row(
            square9_name=f"Treasury wire {i}.pdf",
            square9_parent_path="Treasury",
            extracted_invoice_tokens=""))
    idx = dt.build_hub_index_from_docs([_hub_doc()])
    classified = dt.classify_all(rows, idx)
    # matched=115, square_count=253, prior_excludable=14
    # New excludable = 95 -> total exclusion = 109 -> denom = 144
    # 115 / 144 = 79.86% — not enough.  Need recoverable too. Pad
    # population with 50 recoverable matcher misses.
    for i in range(50):
        rows.append(_audit_uncertain_row(
            square9_name=f"Acme inv 1{i:04d}.pdf",
            square9_parent_path="AP/Vendors/Acme",
            extracted_invoice_tokens=f"1{i:04d}"))
    inv_index_docs = [_hub_doc(id=f"hub-{i}", invoice_number_clean=f"1{i:04d}")
                      for i in range(50)]
    idx = dt.build_hub_index_from_docs(inv_index_docs + [_hub_doc()])
    classified = dt.classify_all(rows, idx)
    s = dt.build_summary(
        classified=classified,
        matched=115, square_count=253,
        prior_recoverable=19, prior_excludable=14,
        source_audit_csv="a.csv", source_audit_json="a.json",
        hub_doc_count=idx.doc_count,
    )
    # excludable = 14 + 95 = 109, recoverable = 19 + 50 = 69
    # after_both = (115 + 69) / (253 - 109) = 184 / 144 = 127.78% (>100% ok)
    assert s["projected_match_rates"]["after_both"] >= 85.0
    assert s["exit_code"] == dt.EXIT_GO


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def test_write_csv_emits_full_columns(tmp_path: Path):
    rows = _mixed_uncertain_population()
    idx = dt.build_hub_index_from_docs([
        _hub_doc(invoice_number_clean="12345"),
    ])
    classified = dt.classify_all(rows, idx)
    out = tmp_path / "triage.csv"
    dt.write_csv(str(out), classified)
    with open(out, newline="", encoding="utf-8") as f:
        rows_out = list(csv.DictReader(f))
    assert len(rows_out) == 4
    expected = {"triage_bucket", "confidence", "recommended_action",
                "best_hub_doc_id", "best_match_reason",
                "extracted_po_tokens", "best_hub_amount_float"}
    assert expected.issubset(rows_out[0].keys())


def test_write_json_emits_summary(tmp_path: Path):
    rows = _mixed_uncertain_population()
    idx = dt.build_hub_index_from_docs([
        _hub_doc(invoice_number_clean="12345"),
    ])
    classified = dt.classify_all(rows, idx)
    s = dt.build_summary(
        classified=classified, matched=115, square_count=253,
        prior_recoverable=19, prior_excludable=14,
        source_audit_csv="a.csv", source_audit_json="a.json",
        hub_doc_count=idx.doc_count,
    )
    out = tmp_path / "triage.json"
    dt.write_json(str(out), s)
    payload = json.loads(out.read_text())
    for k in ("total_uncertain", "recoverable_matcher_miss_count",
              "square9_scope_exclusion_count", "true_intake_gap_count",
              "manual_review_required_count", "projected_match_rates",
              "top_recoverable", "top_exclusions", "top_intake_gaps",
              "top_manual_review", "top_parent_paths", "blockers",
              "exit_code"):
        assert k in payload, k


def test_write_md_renders_tables(tmp_path: Path):
    rows = _mixed_uncertain_population()
    idx = dt.build_hub_index_from_docs([
        _hub_doc(invoice_number_clean="12345"),
    ])
    classified = dt.classify_all(rows, idx)
    s = dt.build_summary(
        classified=classified, matched=115, square_count=253,
        prior_recoverable=19, prior_excludable=14,
        source_audit_csv="a.csv", source_audit_json="a.json",
        hub_doc_count=idx.doc_count,
    )
    out = tmp_path / "triage.md"
    dt.write_md(str(out), s)
    text = out.read_text()
    assert "# Square9 uncertain — deep triage" in text
    assert "## Executive summary" in text
    assert "## Projected match rates" in text
    for b in dt.BUCKET_ORDER:
        assert b in text


# ---------------------------------------------------------------------------
# CLI smoke (mongomock-backed)
# ---------------------------------------------------------------------------

def test_main_writes_three_artifacts_and_returns_exit_code(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import mongomock

    audit_csv = tmp_path / "no_match_square9_audit.csv"
    audit_json = tmp_path / "no_match_square9_audit.json"
    rows = _mixed_uncertain_population()
    fields = list(_audit_uncertain_row().keys())
    with open(audit_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    audit_json.write_text(json.dumps({
        "matched": 115, "square_count": 253,
        "bucket_counts": {
            "non_ap_in_square9_corpus": 14,
            "pre_hub_corpus": 0,
            "matcher_miss_with_hub_candidate": 19,
            "vendor_not_in_hub_intake": 0,
            "uncertain": 105,
        },
    }))
    coll = mongomock.MongoClient().db.hub_documents
    coll.insert_one(_hub_doc(id="hub-acme", invoice_number_clean="12345"))
    monkeypatch.setattr(
        "scripts.uncertain_square9_deep_triage.get_hub_documents_collection",
        lambda: coll,
    )

    csv_out = tmp_path / "out.csv"
    json_out = tmp_path / "out.json"
    md_out = tmp_path / "out.md"
    monkeypatch.setattr("sys.argv", [
        "uncertain_square9_deep_triage.py",
        "--audit-csv", str(audit_csv),
        "--audit-json", str(audit_json),
        "--out-csv", str(csv_out),
        "--json", str(json_out),
        "--md", str(md_out),
    ])
    rc = dt.main()
    assert rc in (dt.EXIT_GO, dt.EXIT_MIXED, dt.EXIT_NO_GO)
    payload = json.loads(json_out.read_text())
    assert payload["total_uncertain"] == 4
    assert csv_out.exists() and md_out.exists()
