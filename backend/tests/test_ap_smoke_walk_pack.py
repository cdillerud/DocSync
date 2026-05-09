"""Tests for ap_smoke_walk_pack (read-only, fixture-driven).

No network. No filesystem outside tmp_path. No Playwright.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts import ap_smoke_walk_pack as pack


def _smoke_row(**overrides: Any) -> Dict[str, str]:
    hub_doc_id = overrides.pop("hub_doc_id", "hub-1")
    base = {
        "test_doc_category": "clean_ap_invoice",
        "priority": "P1",
        "hub_doc_id": hub_doc_id,
        "hub_document_url": f"/documents/{hub_doc_id}",
        "file_name": "Default.pdf",
        "vendor_canonical": "Default Vendor",
        "invoice_number_clean": "INV-1",
        "invoice_date": "2026-04-15",
        "amount_float": "100.00",
        "po_number_clean": "PO-1",
        "mailbox_category": "AP",
        "doc_type": "AP_INVOICE",
        "suggested_job_type": "AP_Invoice",
        "routing_status": "routed",
        "routing_reason": "vendor matched",
        "sharepoint_folder_path": "AP/Vendors/Default",
        "why_this_doc_is_in_the_test_set":
            "All five core fields populated; no exception.",
        "what_tester_should_check":
            "Open the doc. Read each AP Review field.",
        "expected_result": "All fields correct; no exception.",
        "notes": "",
    }
    base.update({k: ("" if v is None else str(v))
                 for k, v in overrides.items()})
    return base


def _write_smoke_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    fieldnames = list(_smoke_row().keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# CSV reader
# ---------------------------------------------------------------------------

def test_read_smoke_csv_returns_rows(tmp_path: Path):
    p = tmp_path / "smoke.csv"
    _write_smoke_csv(p, [_smoke_row(hub_doc_id="hub-a"),
                         _smoke_row(hub_doc_id="hub-b")])
    rows = pack.read_smoke_csv(str(p))
    assert len(rows) == 2
    assert rows[0]["hub_doc_id"] == "hub-a"


def test_read_smoke_csv_missing_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        pack.read_smoke_csv(str(tmp_path / "nope.csv"))


# ---------------------------------------------------------------------------
# Priority parsing & filtering
# ---------------------------------------------------------------------------

def test_parse_priorities_returns_none_on_empty():
    assert pack.parse_priorities(None) is None
    assert pack.parse_priorities("") is None
    assert pack.parse_priorities("   ") is None


def test_parse_priorities_uppercases_and_strips():
    assert pack.parse_priorities("p0,P1, p2 ") == ["P0", "P1", "P2"]


def test_filter_rows_no_priorities_returns_all():
    rows = [_smoke_row(priority="P0"), _smoke_row(priority="P2")]
    assert pack.filter_rows(rows, None) == rows


def test_filter_rows_keeps_only_listed():
    rows = [_smoke_row(hub_doc_id="a", priority="P0"),
            _smoke_row(hub_doc_id="b", priority="P1"),
            _smoke_row(hub_doc_id="c", priority="P2")]
    out = pack.filter_rows(rows, ["P0", "P1"])
    assert [r["hub_doc_id"] for r in out] == ["a", "b"]


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

def test_group_by_priority_orders_p0_p1_p2_and_drops_empty():
    rows = [_smoke_row(priority="P2"),
            _smoke_row(priority="P0"),
            _smoke_row(priority="P1")]
    grouped = pack.group_by_priority(rows)
    assert list(grouped.keys()) == ["P0", "P1", "P2"]
    assert all(len(v) == 1 for v in grouped.values())


# ---------------------------------------------------------------------------
# Link resolution
# ---------------------------------------------------------------------------

def test_resolve_link_uses_absolute_url_unchanged():
    row = _smoke_row(hub_document_url="https://hub.example.com/documents/x")
    assert pack.resolve_link(row, "") == \
        "https://hub.example.com/documents/x"
    # Origin should NOT override an explicit absolute URL.
    assert pack.resolve_link(row, "https://override.example.com") == \
        "https://hub.example.com/documents/x"


def test_resolve_link_prepends_hub_origin_to_relative():
    row = _smoke_row(hub_document_url="/documents/hub-1")
    assert pack.resolve_link(row, "https://hub.example.com") == \
        "https://hub.example.com/documents/hub-1"


def test_resolve_link_returns_relative_when_no_hub_origin():
    row = _smoke_row(hub_document_url="/documents/hub-1")
    assert pack.resolve_link(row, "") == "/documents/hub-1"


def test_resolve_link_falls_back_to_doc_id_when_url_blank():
    row = _smoke_row(hub_document_url="", hub_doc_id="hub-xyz")
    assert pack.resolve_link(row, "https://hub.example.com") == \
        "https://hub.example.com/documents/hub-xyz"


def test_resolve_link_returns_empty_when_nothing_known():
    row = _smoke_row(hub_document_url="", hub_doc_id="")
    assert pack.resolve_link(row, "https://hub.example.com") == ""


# ---------------------------------------------------------------------------
# Findings prefilled row
# ---------------------------------------------------------------------------

def test_prefilled_findings_row_has_expected_columns():
    row = _smoke_row(hub_doc_id="hub-a", file_name="x.pdf",
                     test_doc_category="clean_ap_invoice", priority="P1")
    line = pack.prefilled_findings_row(row, "https://hub/x")
    parsed = list(csv.DictReader(io.StringIO(
        ",".join(pack.FINDINGS_COLUMNS) + "\n" + line)))
    assert parsed, "row parsed back as a CSV record"
    rec = parsed[0]
    assert rec["Priority"] == "P1"
    assert rec["Category"] == "clean_ap_invoice"
    assert rec["Hub Doc ID"] == "hub-a"
    assert rec["File Name"] == "x.pdf"
    assert rec["Hub URL"] == "https://hub/x"
    # Tester / Date / yes-no / notes / severity / owner left blank.
    assert rec["Tester"] == ""
    assert rec["Severity"] == ""


# ---------------------------------------------------------------------------
# HTML render
# ---------------------------------------------------------------------------

def test_render_html_contains_banner_and_per_doc_card():
    rows = [_smoke_row(hub_doc_id="hub-a", file_name="A.pdf",
                       priority="P0",
                       test_doc_category="metadata_cleanup_example")]
    grouped = pack.group_by_priority(rows)
    html = pack.render_html(grouped, "https://hub.example.com",
                            "P0,P1", "x.csv", total_rows=1)
    assert "INTERNAL — IT / Engineering only" in html
    assert "Do not send to AP" in html
    assert "hub-a" in html
    assert "A.pdf" in html
    assert "https://hub.example.com/documents/hub-a" in html
    # Findings prefilled textarea per card.
    assert "AP_SMOKE_WALK_FINDINGS.csv" in html
    # Checkboxes for the five core questions.
    assert html.count("type=\"checkbox\"") >= 6
    # Priority badge present.
    assert "p-P0" in html


def test_render_html_escapes_html_in_filename_to_avoid_injection():
    rows = [_smoke_row(file_name="<script>alert(1)</script>.pdf")]
    grouped = pack.group_by_priority(rows)
    html = pack.render_html(grouped, "https://hub", "ALL", "x.csv", 1)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_render_html_renders_relative_link_when_no_hub_origin():
    rows = [_smoke_row(hub_doc_id="hub-x",
                       hub_document_url="/documents/hub-x")]
    grouped = pack.group_by_priority(rows)
    html = pack.render_html(grouped, "", "ALL", "x.csv", 1)
    assert "/documents/hub-x" in html
    # Notes the tester needs to prepend the Hub origin.
    assert "(not set" in html or "relative" in html


# ---------------------------------------------------------------------------
# Markdown render
# ---------------------------------------------------------------------------

def test_render_md_groups_by_priority_with_links():
    rows = [_smoke_row(hub_doc_id="hub-a", priority="P0", file_name="A.pdf"),
            _smoke_row(hub_doc_id="hub-b", priority="P1", file_name="B.pdf")]
    grouped = pack.group_by_priority(rows)
    md = pack.render_md(grouped, "https://hub", "ALL", "x.csv", 2)
    assert "## P0 — 1 document(s)" in md
    assert "## P1 — 1 document(s)" in md
    assert "https://hub/documents/hub-a" in md
    assert "INTERNAL" in md


# ---------------------------------------------------------------------------
# Findings CSV writer
# ---------------------------------------------------------------------------

def test_write_findings_csv_writes_typed_header(tmp_path: Path):
    out = tmp_path / "findings.csv"
    pack.write_findings_csv(str(out))
    with open(out, encoding="utf-8") as f:
        text = f.read()
    assert "Tester,Date,Priority,Category,Hub Doc ID,File Name," in text
    # Empty body — only header.
    assert text.strip().count("\n") == 0


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_writes_html_md_and_findings_csv(tmp_path: Path,
                                              capsys: pytest.CaptureFixture[str]):
    src = tmp_path / "smoke.csv"
    _write_smoke_csv(src, [
        _smoke_row(hub_doc_id="hub-p0", priority="P0",
                   test_doc_category="metadata_cleanup_example",
                   file_name="P0.pdf"),
        _smoke_row(hub_doc_id="hub-p1", priority="P1",
                   file_name="P1.pdf"),
        _smoke_row(hub_doc_id="hub-p2", priority="P2",
                   file_name="P2.pdf"),
    ])
    out_html = tmp_path / "packet.html"
    out_md = tmp_path / "packet.md"
    out_findings = tmp_path / "findings.csv"

    rc = pack.main([
        "--input-csv", str(src),
        "--hub-origin", "https://hub.example.com",
        "--priorities", "P0,P1",
        "--out-html", str(out_html),
        "--out-md", str(out_md),
        "--out-findings-csv", str(out_findings),
    ])
    assert rc == 0
    assert out_html.exists()
    assert out_md.exists()
    assert out_findings.exists()
    html = out_html.read_text()
    assert "P0.pdf" in html
    assert "P1.pdf" in html
    # P2 was filtered out.
    assert "P2.pdf" not in html
    # Findings CSV has only header.
    rows = list(csv.DictReader(open(out_findings, encoding="utf-8")))
    assert rows == []


def test_main_returns_nonzero_when_csv_missing(tmp_path: Path,
                                               capsys: pytest.CaptureFixture[str]):
    rc = pack.main([
        "--input-csv", str(tmp_path / "nope.csv"),
        "--out-html", str(tmp_path / "p.html"),
        "--out-md", str(tmp_path / "p.md"),
        "--out-findings-csv", str(tmp_path / "f.csv"),
    ])
    assert rc != 0
    err = capsys.readouterr().err
    assert "not found" in err.lower()


def test_main_returns_nonzero_when_filter_matches_zero_rows(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    src = tmp_path / "smoke.csv"
    _write_smoke_csv(src, [_smoke_row(priority="P2")])
    rc = pack.main([
        "--input-csv", str(src),
        "--priorities", "P0",
        "--out-html", str(tmp_path / "p.html"),
        "--out-md", str(tmp_path / "p.md"),
        "--out-findings-csv", str(tmp_path / "f.csv"),
    ])
    assert rc != 0
    err = capsys.readouterr().err
    assert "0 rows" in err
