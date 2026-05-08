"""Tests for document_body_reconciliation_probe (read-only, fixture-driven).

No network. No Mongo. Body extraction is injected as a callable per
test, so the probe is exercised end-to-end without any external I/O.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from scripts import document_body_reconciliation_probe as probe


# ---------------------------------------------------------------------------
# Fixture factories
# ---------------------------------------------------------------------------

def _triage_row(**overrides) -> Dict[str, str]:
    base = {
        "triage_bucket": "manual_review_required",
        "confidence": "0.40",
        "recommended_action": "manual_review",
        "square9_name": "Acme misc 12345.pdf",
        "square9_parent_path": "AP/Vendors/Acme",
        "square9_modified": "2026-04-15T10:00:00+00:00",
        "square9_web_url": "https://example/acme/12345",
        "extracted_invoice_tokens": "",
        "extracted_po_tokens": "",
        "extracted_vendor_tokens": "acme",
        "best_hub_doc_id": "",
        "best_hub_file_name": "",
        "best_match_reason": "",
        "notes": "",
    }
    base.update({k: ("" if v is None else str(v))
                 for k, v in overrides.items()})
    return base


def _hub_doc(**overrides) -> Dict[str, Any]:
    base = {
        "id": "hub-1",
        "vendor_canonical": "Acme Corp",
        "email_sender": "billing@acme.com",
        "invoice_number_clean": "INV-12345",
        "po_number_clean": "",
        "amount_float": "1500.00",
        "invoice_date": "2026-04-15",
        "file_name": "acme-april.pdf",
        "email_subject": "Acme April invoice",
        "sharepoint_folder_path": "AP/Vendors/Acme",
        "mailbox_category": "AP", "doc_type": "AP_INVOICE",
        "suggested_job_type": "AP_Invoice",
        "created_utc": "2026-04-15T10:00:00+00:00",
    }
    base.update(overrides)
    return base


def _make_extractor(text_by_name: Dict[str, Tuple[str, str]]
                    ) -> probe.BodyExtractor:
    """Build an extractor that maps square9_name -> (text, status)."""
    def _ext(row: Dict[str, str]) -> Tuple[str, str]:
        name = row.get("square9_name", "")
        return text_by_name.get(name, ("", probe.CONTENT_NO_ACCESS))
    return _ext


# ---------------------------------------------------------------------------
# Body-signal extraction
# ---------------------------------------------------------------------------

def test_extract_body_signals_pulls_invoice_amount_and_date():
    text = (
        "Acme Corp\nInvoice #: INV-12345\nDate: 04/15/2026\n"
        "Total: $1,500.00\nPO: PO-9999\nRemit To: Acme Corp\n"
    )
    sig = probe.extract_body_signals(text)
    assert sig["invoice_number"] == "INV-12345"
    assert sig["po_number"] == "PO-9999"
    assert sig["amount"] == 1500.00
    assert sig["invoice_date"] == "2026-04-15"
    assert "Acme" in (sig["vendor_hint"] or "")


def test_extract_body_signals_handles_empty_text():
    sig = probe.extract_body_signals("")
    assert sig["invoice_number"] is None
    assert sig["amount"] is None


def test_extract_body_signals_normalizes_invoice_date_long_format():
    sig = probe.extract_body_signals("Invoice Date: April 15, 2026")
    assert sig["invoice_date"] == "2026-04-15"


# ---------------------------------------------------------------------------
# Hub index + scoring
# ---------------------------------------------------------------------------

def test_build_hub_index_indexes_invoice_and_po_and_amount():
    idx = probe.build_hub_index_from_docs([
        _hub_doc(id="hub-acme", invoice_number_clean="INV-12345",
                 po_number_clean="PO-9999", amount_float="1500.00",
                 vendor_canonical="Acme Corp",
                 email_sender="billing@acme.com",
                 invoice_date="2026-04-15"),
    ])
    assert "INV12345" in idx.by_invoice_norm
    assert "12345" in idx.by_invoice_digits
    assert "PO9999" in idx.by_po_norm
    assert idx.by_amount.get("1500.00")


def test_score_signals_strong_when_invoice_and_amount_align():
    idx = probe.build_hub_index_from_docs([
        _hub_doc(id="hub-acme",
                 invoice_number_clean="INV-12345",
                 amount_float="1500.00",
                 invoice_date="2026-04-15",
                 vendor_canonical="Acme Corp"),
    ])
    sig = probe.extract_body_signals(
        "Acme Corp\nInvoice: INV-12345\nDate: 04/15/2026\nTotal: $1,500.00")
    score, doc, breakdown, signals_won = probe.score_signals_against_hub(
        sig, idx)
    assert doc and doc["hub_doc_id"] == "hub-acme"
    assert score >= probe.CONTENT_MATCH_THRESHOLD
    assert breakdown["invoice_number"] == 1.0
    assert breakdown["amount"] == 1.0


def test_score_signals_zero_when_nothing_matches():
    idx = probe.build_hub_index_from_docs([_hub_doc()])
    sig = probe.extract_body_signals("totally unrelated content")
    score, doc, breakdown, _ = probe.score_signals_against_hub(sig, idx)
    assert score == 0.0
    assert doc is None
    assert breakdown == {}


# ---------------------------------------------------------------------------
# probe() end-to-end — one test per bucket
# ---------------------------------------------------------------------------

def test_content_match_found_when_body_carries_invoice_and_amount():
    triage = [_triage_row(square9_name="acme.pdf")]
    extractor = _make_extractor({
        "acme.pdf": (
            "Acme Corp\nInvoice #: INV-12345\nDate: 04/15/2026\n"
            "Total: $1,500.00", probe.CONTENT_OK,
        ),
    })
    idx = probe.build_hub_index_from_docs([_hub_doc(id="hub-acme")])
    out = probe.probe(triage, extractor=extractor, idx=idx, limit=1)
    assert out[0]["classification"] == "content_match_found"
    assert out[0]["best_hub_doc_id"] == "hub-acme"


def test_likely_same_invoice_different_attachment_granularity():
    triage = [_triage_row(square9_name="acme-remit.pdf")]
    extractor = _make_extractor({
        # Same vendor + amount + date as Hub doc, but DIFFERENT invoice
        # number -- looks like a remittance attached to the same invoice.
        "acme-remit.pdf": (
            "Acme Corp\nRemittance Advice\nInvoice #: REMIT-7777\n"
            "Date: 04/15/2026\nTotal: $1,500.00\n"
            "Remit To: Acme Corp",
            probe.CONTENT_OK,
        ),
    })
    idx = probe.build_hub_index_from_docs([_hub_doc(
        id="hub-acme",
        invoice_number_clean="INV-12345",
        amount_float="1500.00",
        invoice_date="2026-04-15",
        vendor_canonical="Acme Corp",
    )])
    out = probe.probe(triage, extractor=extractor, idx=idx, limit=1)
    assert out[0]["classification"] == \
        "likely_same_invoice_different_attachment_granularity"


def test_ocr_required_when_extractor_signals_no_text():
    triage = [_triage_row(square9_name="scan.pdf")]
    extractor = _make_extractor({
        "scan.pdf": ("", probe.CONTENT_OCR_REQUIRED),
    })
    idx = probe.build_hub_index_from_docs([_hub_doc()])
    out = probe.probe(triage, extractor=extractor, idx=idx, limit=1)
    assert out[0]["classification"] == "ocr_required"


def test_ocr_required_when_extractor_returns_ok_but_empty_body():
    triage = [_triage_row(square9_name="scan.pdf")]
    extractor = _make_extractor({
        "scan.pdf": ("   \n  ", probe.CONTENT_OK),
    })
    idx = probe.build_hub_index_from_docs([_hub_doc()])
    out = probe.probe(triage, extractor=extractor, idx=idx, limit=1)
    assert out[0]["classification"] == "ocr_required"


def test_insufficient_content_access_when_no_extractor_wired():
    triage = [_triage_row(square9_name="acme.pdf")]
    idx = probe.build_hub_index_from_docs([_hub_doc()])
    out = probe.probe(triage,
                      extractor=probe.default_body_extractor,
                      idx=idx, limit=1)
    assert out[0]["classification"] == "insufficient_content_access"


def test_square9_only_true_gap_when_vendor_known_no_body_match():
    triage = [_triage_row(
        square9_name="acme-misc.pdf",
        square9_parent_path="AP/Vendors/Acme",
        square9_web_url="https://x/acme/misc")]
    extractor = _make_extractor({
        "acme-misc.pdf": (
            "Some random body without invoice numbers or amounts",
            probe.CONTENT_OK,
        ),
    })
    idx = probe.build_hub_index_from_docs([_hub_doc(
        id="hub-other", invoice_number_clean="999999",
        amount_float="100.00",
        vendor_canonical="Acme Corp",
        email_sender="billing@acme.com",
    )])
    out = probe.probe(triage, extractor=extractor, idx=idx, limit=1)
    assert out[0]["classification"] == "square9_only_true_gap"


def test_manual_review_when_vendor_unknown_and_signals_weak():
    triage = [_triage_row(
        square9_name="zzz-unknown.pdf",
        square9_parent_path="AP/Other",
        square9_web_url="https://x/other")]
    extractor = _make_extractor({
        "zzz-unknown.pdf": (
            "no invoice signals here", probe.CONTENT_OK,
        ),
    })
    idx = probe.build_hub_index_from_docs([_hub_doc(
        id="hub-acme", vendor_canonical="Acme Corp",
        email_sender="billing@acme.com",
    )])
    out = probe.probe(triage, extractor=extractor, idx=idx, limit=1)
    assert out[0]["classification"] == "manual_review_still_required"


# ---------------------------------------------------------------------------
# Summary builder + writers
# ---------------------------------------------------------------------------

def _mixed_population_probed() -> List[Dict[str, Any]]:
    triage = [
        _triage_row(square9_name="acme.pdf"),
        _triage_row(square9_name="scan.pdf"),
        _triage_row(square9_name="no-access.pdf"),
        _triage_row(square9_name="acme-misc.pdf",
                    square9_parent_path="AP/Vendors/Acme",
                    square9_web_url="https://x/acme/misc"),
    ]
    extractor = _make_extractor({
        "acme.pdf": (
            "Acme Corp\nInvoice #: INV-12345\nDate: 04/15/2026\n"
            "Total: $1,500.00", probe.CONTENT_OK,
        ),
        "scan.pdf": ("", probe.CONTENT_OCR_REQUIRED),
        # no-access.pdf has no entry -> default_body_extractor logic
        "acme-misc.pdf": (
            "random body text", probe.CONTENT_OK,
        ),
    })
    idx = probe.build_hub_index_from_docs([_hub_doc(id="hub-acme")])
    return probe.probe(triage, extractor=extractor, idx=idx, limit=4)


def test_build_summary_counts_and_recommendations():
    probed = _mixed_population_probed()
    s = probe.build_summary(probed, hub_doc_count=1, source_csv="x.csv")
    assert s["total_attempted"] == 4
    bc = s["bucket_counts"]
    assert bc["content_match_found"] == 1
    assert bc["ocr_required"] == 1
    assert bc["insufficient_content_access"] == 1
    assert (bc["square9_only_true_gap"]
            + bc["manual_review_still_required"]) == 1
    # Recommendations include both failure-detail investigation and OCR.
    steps = " ".join(s["recommended_engineering_next_steps"])
    assert "failure_reason_detail" in steps
    assert "OCR" in steps


def test_write_csv_emits_full_columns(tmp_path: Path):
    probed = _mixed_population_probed()
    out = tmp_path / "probe.csv"
    probe.write_csv(str(out), probed)
    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 4
    expected = {"square9_name", "content_access_status",
                "extracted_invoice_number", "best_hub_doc_id",
                "classification", "recommended_next_action",
                "best_match_score"}
    assert expected.issubset(rows[0].keys())


def test_write_json_emits_summary(tmp_path: Path):
    probed = _mixed_population_probed()
    s = probe.build_summary(probed, hub_doc_count=1, source_csv="x.csv")
    out = tmp_path / "probe.json"
    probe.write_json(str(out), s)
    payload = json.loads(out.read_text())
    for k in ("total_attempted", "content_read_success", "ocr_required",
              "content_match_found",
              "same_invoice_different_attachment_granularity",
              "true_square9_only_gap", "insufficient_content_access",
              "manual_review_still_required", "bucket_counts",
              "top_vendors", "top_failure_reasons",
              "top_examples_by_bucket",
              "recommended_engineering_next_steps"):
        assert k in payload, k


def test_write_md_renders_tables(tmp_path: Path):
    probed = _mixed_population_probed()
    s = probe.build_summary(probed, hub_doc_count=1, source_csv="x.csv")
    out = tmp_path / "probe.md"
    probe.write_md(str(out), s)
    text = out.read_text()
    assert "# Document body reconciliation probe" in text
    assert "## Plain-English summary" in text
    assert "## Bucket counts" in text
    for b in probe.BUCKET_ORDER:
        assert b in text


# ---------------------------------------------------------------------------
# CLI smoke (uses mongomock + injected extractor)
# ---------------------------------------------------------------------------

def test_main_writes_three_artifacts_with_injected_extractor(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import mongomock

    triage_csv = tmp_path / "uncertain_square9_deep_triage.csv"
    rows = [
        _triage_row(square9_name="acme.pdf"),
        _triage_row(square9_name="scan.pdf"),
    ]
    fields = list(_triage_row().keys())
    with open(triage_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    coll = mongomock.MongoClient().db.hub_documents
    coll.insert_one(_hub_doc(id="hub-acme"))
    monkeypatch.setattr(
        "scripts.document_body_reconciliation_probe.get_hub_documents_collection",
        lambda: coll,
    )

    csv_out = tmp_path / "out.csv"
    json_out = tmp_path / "out.json"
    md_out = tmp_path / "out.md"
    monkeypatch.setattr("sys.argv", [
        "document_body_reconciliation_probe.py",
        "--triage-csv", str(triage_csv),
        "--out-csv", str(csv_out),
        "--json", str(json_out),
        "--md", str(md_out),
    ])
    extractor = _make_extractor({
        "acme.pdf": (
            "Acme Corp\nInvoice #: INV-12345\nDate: 04/15/2026\n"
            "Total: $1,500.00", probe.CONTENT_OK),
        "scan.pdf": ("", probe.CONTENT_OCR_REQUIRED),
    })
    rc = probe.main(extractor=extractor)
    assert rc == 0
    payload = json.loads(json_out.read_text())
    assert payload["total_attempted"] == 2
    assert payload["content_match_found"] == 1
    assert payload["ocr_required"] == 1
    assert csv_out.exists() and md_out.exists()



# ---------------------------------------------------------------------------
# Fail-loud behavior: production fetcher is required by default
# ---------------------------------------------------------------------------

def _write_minimal_triage(tmp_path: Path) -> Path:
    triage_csv = tmp_path / "uncertain_square9_deep_triage.csv"
    fields = list(_triage_row().keys())
    with open(triage_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow(_triage_row(square9_name="acme.pdf"))
    return triage_csv


def test_main_exits_nonzero_when_production_fetcher_import_fails(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]):
    """If the production fetcher cannot be built and --use-noop-fetcher
    is NOT passed, main() must refuse to silently fall back: print a
    clear stderr message and return a non-zero exit code."""
    import mongomock
    import sys as _sys

    triage_csv = _write_minimal_triage(tmp_path)
    coll = mongomock.MongoClient().db.hub_documents
    coll.insert_one(_hub_doc(id="hub-acme"))
    monkeypatch.setattr(
        "scripts.document_body_reconciliation_probe.get_hub_documents_collection",
        lambda: coll,
    )

    # Force the production-fetcher import path to blow up.
    fake_mod = type(_sys)("scripts.sharepoint_body_fetcher")

    def _boom(no_cache: bool = False):
        raise RuntimeError("simulated import/build failure")
    fake_mod.build_production_fetcher = _boom  # type: ignore[attr-defined]
    monkeypatch.setitem(_sys.modules, "scripts.sharepoint_body_fetcher",
                        fake_mod)

    monkeypatch.setattr("sys.argv", [
        "document_body_reconciliation_probe.py",
        "--triage-csv", str(triage_csv),
        "--out-csv", str(tmp_path / "out.csv"),
        "--json", str(tmp_path / "out.json"),
        "--md", str(tmp_path / "out.md"),
    ])

    rc = probe.main(extractor=None)
    assert rc != 0, "must not silently fall back to no-op extractor"
    err = capsys.readouterr().err
    assert "production" in err.lower()
    assert "--use-noop-fetcher" in err


def test_main_runs_with_noop_extractor_when_flag_is_explicit(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]):
    """--use-noop-fetcher is the only way to legitimately run the probe
    without reading bodies. Every row must classify as
    insufficient_content_access and stderr must warn loudly."""
    import mongomock
    import sys as _sys

    triage_csv = _write_minimal_triage(tmp_path)
    coll = mongomock.MongoClient().db.hub_documents
    coll.insert_one(_hub_doc(id="hub-acme"))
    monkeypatch.setattr(
        "scripts.document_body_reconciliation_probe.get_hub_documents_collection",
        lambda: coll,
    )
    # Even if the production fetcher were importable, --use-noop-fetcher
    # must not invoke it. Plant a tripwire to prove that.
    fake_mod = type(_sys)("scripts.sharepoint_body_fetcher")

    def _tripwire(no_cache: bool = False):
        raise AssertionError("production fetcher must not be built when "
                             "--use-noop-fetcher is set")
    fake_mod.build_production_fetcher = _tripwire  # type: ignore[attr-defined]
    monkeypatch.setitem(_sys.modules, "scripts.sharepoint_body_fetcher",
                        fake_mod)

    json_out = tmp_path / "out.json"
    monkeypatch.setattr("sys.argv", [
        "document_body_reconciliation_probe.py",
        "--triage-csv", str(triage_csv),
        "--use-noop-fetcher",
        "--out-csv", str(tmp_path / "out.csv"),
        "--json", str(json_out),
        "--md", str(tmp_path / "out.md"),
    ])

    rc = probe.main(extractor=None)
    assert rc == 0
    err = capsys.readouterr().err
    assert "--use-noop-fetcher" in err
    assert "no document bodies will be read" in err
    payload = json.loads(json_out.read_text())
    assert payload["total_attempted"] == 1
    assert payload["insufficient_content_access"] == 1


def test_main_uses_production_fetcher_by_default_when_importable(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When the production fetcher imports cleanly and no flag is
    passed, main() must use it (not the no-op default)."""
    import mongomock
    import sys as _sys

    triage_csv = _write_minimal_triage(tmp_path)
    coll = mongomock.MongoClient().db.hub_documents
    coll.insert_one(_hub_doc(id="hub-acme"))
    monkeypatch.setattr(
        "scripts.document_body_reconciliation_probe.get_hub_documents_collection",
        lambda: coll,
    )

    built = {"called": False, "no_cache": None}

    def _stub_extractor(_row):
        return (
            "Acme Corp\nInvoice #: INV-12345\nDate: 04/15/2026\n"
            "Total: $1,500.00",
            probe.CONTENT_OK,
        )

    fake_mod = type(_sys)("scripts.sharepoint_body_fetcher")

    def _build(no_cache: bool = False):
        built["called"] = True
        built["no_cache"] = no_cache
        return _stub_extractor
    fake_mod.build_production_fetcher = _build  # type: ignore[attr-defined]
    monkeypatch.setitem(_sys.modules, "scripts.sharepoint_body_fetcher",
                        fake_mod)

    json_out = tmp_path / "out.json"
    monkeypatch.setattr("sys.argv", [
        "document_body_reconciliation_probe.py",
        "--triage-csv", str(triage_csv),
        "--no-cache",
        "--out-csv", str(tmp_path / "out.csv"),
        "--json", str(json_out),
        "--md", str(tmp_path / "out.md"),
    ])

    rc = probe.main(extractor=None)
    assert rc == 0
    assert built["called"] is True
    assert built["no_cache"] is True
    payload = json.loads(json_out.read_text())
    assert payload["content_match_found"] == 1


# ---------------------------------------------------------------------------
# Subprocess regression: import resolution for both invocation modes
# ---------------------------------------------------------------------------

def _backend_root() -> Path:
    # tests/test_document_body_reconciliation_probe.py -> /app/backend
    return Path(__file__).resolve().parent.parent


def test_subprocess_help_works_with_direct_script_invocation():
    """python scripts/document_body_reconciliation_probe.py --help
    must succeed. This is the exact invocation that produced the
    ModuleNotFoundError("No module named 'scripts'") on the VM."""
    import subprocess
    result = subprocess.run(
        ["python", "scripts/document_body_reconciliation_probe.py", "--help"],
        cwd=str(_backend_root()),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"direct invocation failed (rc={result.returncode}):\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    assert "--use-noop-fetcher" in result.stdout
    assert "--triage-csv" in result.stdout


def test_subprocess_help_works_with_module_invocation():
    """python -m scripts.document_body_reconciliation_probe --help must
    also work."""
    import subprocess
    result = subprocess.run(
        ["python", "-m", "scripts.document_body_reconciliation_probe",
         "--help"],
        cwd=str(_backend_root()),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"module invocation failed (rc={result.returncode}):\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    assert "--use-noop-fetcher" in result.stdout



# ---------------------------------------------------------------------------
# Diagnostic capture from extractors with last_diagnostic side-channel
# ---------------------------------------------------------------------------

class _DiagnosticExtractor:
    """Test double mimicking GraphBodyFetcher's diagnostic protocol."""

    def __init__(self, mapping):
        # mapping: square9_name -> (text, status, diagnostic dict)
        self._mapping = mapping
        self.last_diagnostic: Dict[str, Any] = {}

    def __call__(self, row):
        name = row.get("square9_name", "")
        text, status, diag = self._mapping.get(
            name, ("", probe.CONTENT_NO_ACCESS,
                   {"failure_reason_detail": "empty_url",
                    "graph_url": "", "http_status": None,
                    "error_body_snippet": "", "exception_class": ""}))
        self.last_diagnostic = dict(diag)
        return text, status


def test_probe_captures_failure_reason_detail_from_extractor():
    """When the extractor publishes ``last_diagnostic``, the probe
    must thread that detail into each output row."""
    triage = [
        _triage_row(square9_name="ok.pdf"),
        _triage_row(square9_name="forbidden.pdf"),
        _triage_row(square9_name="missing.pdf"),
        _triage_row(square9_name="timeout.pdf"),
    ]
    extractor = _DiagnosticExtractor({
        "ok.pdf": (
            "Acme Corp\nInvoice #: INV-12345\nDate: 04/15/2026\n"
            "Total: $1,500.00",
            probe.CONTENT_OK,
            {"failure_reason_detail": "ok",
             "graph_url": "https://graph.microsoft.com/v1.0/shares/u!ok",
             "http_status": 200,
             "error_body_snippet": "", "exception_class": ""},
        ),
        "forbidden.pdf": (
            "", probe.CONTENT_NO_ACCESS,
            {"failure_reason_detail": "http_403",
             "graph_url": "https://graph.microsoft.com/v1.0/shares/u!fb",
             "http_status": 403,
             "error_body_snippet": "{\"error\":\"forbidden\"}",
             "exception_class": ""},
        ),
        "missing.pdf": (
            "", probe.CONTENT_NO_ACCESS,
            {"failure_reason_detail": "http_404",
             "graph_url": "https://graph.microsoft.com/v1.0/shares/u!ms",
             "http_status": 404,
             "error_body_snippet": "{\"error\":\"itemNotFound\"}",
             "exception_class": ""},
        ),
        "timeout.pdf": (
            "", probe.CONTENT_NO_ACCESS,
            {"failure_reason_detail": "timeout",
             "graph_url": "https://graph.microsoft.com/v1.0/shares/u!tm",
             "http_status": None,
             "error_body_snippet": "",
             "exception_class": "ReadTimeout"},
        ),
    })
    idx = probe.build_hub_index_from_docs([_hub_doc(id="hub-acme")])
    out = probe.probe(triage, extractor=extractor, idx=idx, limit=4)
    by_name = {r["square9_name"]: r for r in out}
    assert by_name["ok.pdf"]["failure_reason_detail"] == "ok"
    assert by_name["forbidden.pdf"]["failure_reason_detail"] == "http_403"
    assert by_name["forbidden.pdf"]["http_status"] == "403"
    assert "forbidden" in by_name["forbidden.pdf"]["error_body_snippet"]
    assert by_name["missing.pdf"]["failure_reason_detail"] == "http_404"
    assert by_name["timeout.pdf"]["failure_reason_detail"] == "timeout"
    assert by_name["timeout.pdf"]["exception_class"] == "ReadTimeout"


def test_build_summary_aggregates_failure_reason_detail_counts():
    triage = [
        _triage_row(square9_name="a.pdf"),
        _triage_row(square9_name="b.pdf"),
        _triage_row(square9_name="c.pdf"),
    ]
    extractor = _DiagnosticExtractor({
        "a.pdf": ("", probe.CONTENT_NO_ACCESS,
                  {"failure_reason_detail": "http_404",
                   "graph_url": "g/a", "http_status": 404,
                   "error_body_snippet": "", "exception_class": ""}),
        "b.pdf": ("", probe.CONTENT_NO_ACCESS,
                  {"failure_reason_detail": "http_404",
                   "graph_url": "g/b", "http_status": 404,
                   "error_body_snippet": "", "exception_class": ""}),
        "c.pdf": ("", probe.CONTENT_NO_ACCESS,
                  {"failure_reason_detail": "graph_resolve_failed",
                   "graph_url": "g/c", "http_status": 400,
                   "error_body_snippet": "", "exception_class": ""}),
    })
    idx = probe.build_hub_index_from_docs([_hub_doc()])
    probed = probe.probe(triage, extractor=extractor, idx=idx, limit=3)
    s = probe.build_summary(probed, hub_doc_count=1, source_csv="x.csv")
    counts = s["failure_reason_detail_counts"]
    assert counts["http_404"] == 2
    assert counts["graph_resolve_failed"] == 1


def test_render_diag_sample_includes_url_status_and_body_snippet():
    triage = [_triage_row(square9_name="forbidden.pdf",
                          square9_parent_path="AP/Vendors/X")]
    extractor = _DiagnosticExtractor({
        "forbidden.pdf": (
            "", probe.CONTENT_NO_ACCESS,
            {"failure_reason_detail": "http_403",
             "graph_url": "https://graph.microsoft.com/v1.0/shares/u!xyz",
             "http_status": 403,
             "error_body_snippet": "{\"error\":{\"code\":\"accessDenied\"}}",
             "exception_class": ""},
        ),
    })
    idx = probe.build_hub_index_from_docs([_hub_doc()])
    out = probe.probe(triage, extractor=extractor, idx=idx, limit=1)
    banner = probe.render_diag_sample(out, n=1)
    assert "DIAGNOSTIC SAMPLE" in banner
    assert "forbidden.pdf" in banner
    assert "AP/Vendors/X" in banner
    assert "graph.microsoft.com" in banner
    assert "http_403" in banner
    assert "403" in banner
    assert "accessDenied" in banner


def test_render_diag_sample_returns_empty_when_n_is_zero():
    assert probe.render_diag_sample([{"square9_name": "x"}], n=0) == ""


def test_csv_output_includes_diagnostic_columns(tmp_path: Path):
    triage = [_triage_row(square9_name="forbidden.pdf")]
    extractor = _DiagnosticExtractor({
        "forbidden.pdf": (
            "", probe.CONTENT_NO_ACCESS,
            {"failure_reason_detail": "http_403",
             "graph_url": "https://g/x", "http_status": 403,
             "error_body_snippet": "denied", "exception_class": ""},
        ),
    })
    idx = probe.build_hub_index_from_docs([_hub_doc()])
    out = probe.probe(triage, extractor=extractor, idx=idx, limit=1)
    csv_path = tmp_path / "p.csv"
    probe.write_csv(str(csv_path), out)
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["failure_reason_detail"] == "http_403"
    assert rows[0]["http_status"] == "403"
    assert rows[0]["graph_url_attempted"] == "https://g/x"
    assert rows[0]["error_body_snippet"] == "denied"


def test_md_output_includes_failure_reason_detail_section(tmp_path: Path):
    triage = [_triage_row(square9_name="x.pdf")]
    extractor = _DiagnosticExtractor({
        "x.pdf": ("", probe.CONTENT_NO_ACCESS,
                  {"failure_reason_detail": "http_404",
                   "graph_url": "g", "http_status": 404,
                   "error_body_snippet": "", "exception_class": ""}),
    })
    idx = probe.build_hub_index_from_docs([_hub_doc()])
    out = probe.probe(triage, extractor=extractor, idx=idx, limit=1)
    s = probe.build_summary(out, hub_doc_count=1, source_csv="x.csv")
    md_path = tmp_path / "p.md"
    probe.write_md(str(md_path), s)
    text = md_path.read_text()
    assert "## failure_reason_detail counts" in text
    assert "http_404" in text


def test_main_emits_diag_sample_banner_when_flag_is_set(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]):
    import mongomock

    triage_csv = tmp_path / "t.csv"
    fields = list(_triage_row().keys())
    rows_in = [
        _triage_row(square9_name="ok.pdf"),
        _triage_row(square9_name="bad.pdf"),
    ]
    with open(triage_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows_in:
            w.writerow(r)

    coll = mongomock.MongoClient().db.hub_documents
    coll.insert_one(_hub_doc(id="hub-acme"))
    monkeypatch.setattr(
        "scripts.document_body_reconciliation_probe.get_hub_documents_collection",
        lambda: coll,
    )

    extractor = _DiagnosticExtractor({
        "ok.pdf": ("Acme\nInvoice #: INV-12345\nDate: 04/15/2026\n"
                   "Total: $1,500.00", probe.CONTENT_OK,
                   {"failure_reason_detail": "ok",
                    "graph_url": "https://g/ok", "http_status": 200,
                    "error_body_snippet": "", "exception_class": ""}),
        "bad.pdf": ("", probe.CONTENT_NO_ACCESS,
                    {"failure_reason_detail": "http_403",
                     "graph_url": "https://g/bad", "http_status": 403,
                     "error_body_snippet": "denied",
                     "exception_class": ""}),
    })

    monkeypatch.setattr("sys.argv", [
        "document_body_reconciliation_probe.py",
        "--triage-csv", str(triage_csv),
        "--diag-sample", "2",
        "--out-csv", str(tmp_path / "out.csv"),
        "--json", str(tmp_path / "out.json"),
        "--md", str(tmp_path / "out.md"),
    ])

    rc = probe.main(extractor=extractor)
    assert rc == 0
    captured = capsys.readouterr()
    out = captured.out
    assert "DIAGNOSTIC SAMPLE" in out
    assert "ok.pdf" in out
    assert "bad.pdf" in out
    assert "http_403" in out
    assert "denied" in out
    # And the failure_reason_detail counts show up in the regular summary too.
    assert "failure_reason_detail counts" in out
