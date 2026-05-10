"""Tests for build_ap_smoke_test_set (read-only, fixture-driven).

No network. No Mongo. Synthetic ``hub_docs`` and probe rows are passed
directly into ``curate()``.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

from scripts import build_ap_smoke_test_set as smk


def _hub_doc(**overrides) -> Dict[str, Any]:
    base = {
        "id": "hub-default",
        "file_name": "default.pdf",
        "vendor_canonical": "Default Vendor",
        "invoice_number_clean": "INV-1",
        "po_number_clean": "PO-1",
        "amount_float": 100.00,
        "invoice_date": "2026-04-15",
        "mailbox_category": "AP",
        "doc_type": "AP_INVOICE",
        "suggested_job_type": "AP_Invoice",
        "document_type": "AP_Invoice",
        "workflow_status": "ready_for_approval",
        "routing_status": "routed",
        "routing_reason": "vendor matched",
        "sharepoint_folder_path": "AP/Vendors/Default",
        "validation_errors": [],
    }
    base.update(overrides)
    return base


def _probe_row(**overrides) -> Dict[str, str]:
    base = {
        "square9_name": "x.pdf",
        "classification": "manual_review_still_required",
        "content_access_status": "ok",
        "failure_reason_detail": "ok",
        "best_hub_doc_id": "",
        "best_hub_file_name": "",
        "best_hub_vendor_canonical": "",
    }
    base.update({k: ("" if v is None else str(v))
                 for k, v in overrides.items()})
    return base


# ---------------------------------------------------------------------------
# Curator behaviour
# ---------------------------------------------------------------------------

def test_curator_emits_clean_invoice_row():
    docs = [_hub_doc(id="hub-clean")]
    rows, missing = smk.curate(hub_docs=docs, probe_rows=[], per_category=2)
    assert any(r["test_doc_category"] == "clean_ap_invoice"
               for r in rows)
    assert "clean_ap_invoice" not in missing


def test_curator_marks_missing_when_no_clean_invoice():
    # Doc has a validation_error -> not clean.
    docs = [_hub_doc(id="hub-dirty", validation_errors=["amount_missing"],
                     workflow_status="data_correction_pending")]
    rows, missing = smk.curate(hub_docs=docs, probe_rows=[], per_category=2)
    assert "clean_ap_invoice" in missing


def test_curator_emits_field_populated_rows_per_field():
    """Each field-populated category should be representable. After
    the within-cluster dedupe, distinct docs are needed because the
    happy_path cluster (clean + 4 field-populated) collapses
    same-doc duplicates."""
    docs = [
        _hub_doc(id="hub-vendor",
                 vendor_canonical="V", invoice_number_clean="",
                 amount_float=0, po_number_clean="",
                 validation_errors=["amount_missing"],
                 workflow_status="data_correction_pending"),
        _hub_doc(id="hub-inv",
                 vendor_canonical="", invoice_number_clean="INV-9",
                 amount_float=0, po_number_clean="",
                 validation_errors=["amount_missing"],
                 workflow_status="data_correction_pending"),
        _hub_doc(id="hub-amt",
                 vendor_canonical="", invoice_number_clean="",
                 amount_float=42.50, po_number_clean="",
                 validation_errors=["po_missing"],
                 workflow_status="data_correction_pending"),
        _hub_doc(id="hub-po",
                 vendor_canonical="", invoice_number_clean="",
                 amount_float=0, po_number_clean="PO-9",
                 validation_errors=["amount_missing"],
                 workflow_status="data_correction_pending"),
    ]
    rows, _ = smk.curate(hub_docs=docs, probe_rows=[], per_category=1)
    cats = {r["test_doc_category"] for r in rows}
    assert "ap_invoice_vendor_populated" in cats
    assert "ap_invoice_invoice_number_populated" in cats
    assert "ap_invoice_amount_populated" in cats
    assert "ap_invoice_po_populated" in cats


def test_curator_omits_amount_field_row_when_amount_zero():
    # amount=0 should not satisfy "amount populated"
    docs = [_hub_doc(id="hub-zero", amount_float=0)]
    rows, missing = smk.curate(hub_docs=docs, probe_rows=[], per_category=1)
    cats = [r["test_doc_category"] for r in rows]
    assert "ap_invoice_amount_populated" not in cats
    assert "ap_invoice_amount_populated" in missing


def test_curator_emits_exception_row_for_validation_errors():
    docs = [_hub_doc(id="hub-bad",
                     validation_errors=["po_missing"],
                     workflow_status="data_correction_pending")]
    rows, missing = smk.curate(hub_docs=docs, probe_rows=[], per_category=2)
    assert any(r["test_doc_category"] == "needs_review_or_exception"
               for r in rows)
    assert "needs_review_or_exception" not in missing


def test_curator_emits_duplicate_row_when_flagged():
    docs = [_hub_doc(id="hub-dup", is_duplicate=True)]
    rows, missing = smk.curate(hub_docs=docs, probe_rows=[], per_category=2)
    assert any(r["test_doc_category"] == "duplicate_or_possible_duplicate"
               for r in rows)


def test_curator_emits_misclassified_row_when_override_present():
    docs = [_hub_doc(id="hub-mis",
                     classification_override={
                         "original_type": "Misc",
                         "corrected_type": "AP_Invoice"})]
    rows, _ = smk.curate(hub_docs=docs, probe_rows=[], per_category=2)
    assert any(r["test_doc_category"] == "misclassified_or_corrected"
               for r in rows)


def test_curator_pulls_non_invoice_attachment_from_probe():
    docs = [_hub_doc(id="hub-xls",
                     file_name="tracking.xlsx",
                     vendor_canonical="",
                     amount_float=None,
                     mailbox_category="AP",
                     doc_type="AP_INVOICE")]
    probe = [_probe_row(classification="non_invoice_attachment",
                        best_hub_doc_id="hub-xls")]
    rows, missing = smk.curate(hub_docs=docs, probe_rows=probe,
                               per_category=2)
    assert any(r["test_doc_category"] == "non_invoice_attachment"
               and r["hub_doc_id"] == "hub-xls" for r in rows)
    assert "non_invoice_attachment" not in missing


def test_curator_pulls_ocr_required_from_probe():
    docs = [_hub_doc(id="hub-ocr")]
    probe = [_probe_row(classification="ocr_required",
                        best_hub_doc_id="hub-ocr")]
    rows, missing = smk.curate(hub_docs=docs, probe_rows=probe,
                               per_category=2)
    assert any(r["test_doc_category"] == "ocr_required"
               and r["hub_doc_id"] == "hub-ocr" for r in rows)
    assert "ocr_required" not in missing


def test_curator_pulls_permission_edge_from_probe_403_404():
    docs = [_hub_doc(id="hub-403")]
    probe = [_probe_row(classification="insufficient_content_access",
                        failure_reason_detail="http_403",
                        best_hub_doc_id="hub-403")]
    rows, missing = smk.curate(hub_docs=docs, probe_rows=probe,
                               per_category=2)
    assert any(r["test_doc_category"] == "sharepoint_permission_edge"
               and r["hub_doc_id"] == "hub-403" for r in rows)
    assert "sharepoint_permission_edge" not in missing


def test_curator_always_emits_pinned_metadata_cleanup_rows():
    """The Hawkemedia + XPO rows are pinned and must appear even when
    the live corpus does not contain those hub_doc_ids."""
    rows, missing = smk.curate(hub_docs=[], probe_rows=[],
                               per_category=2)
    cleanup = [r for r in rows
               if r["test_doc_category"] == "metadata_cleanup_example"]
    assert len(cleanup) == 2
    ids = {r["hub_doc_id"] for r in cleanup}
    assert "674926c1-d4da-42aa-897b-59cd4867c15f" in ids
    assert "34a351ba-c1e2-4cd2-aac8-c6fa535fa352" in ids
    assert "metadata_cleanup_example" not in missing
    # Pinned rows always carry the pinned_example marker.
    for r in cleanup:
        assert "pinned_example=Y" in r["notes"]


def test_curator_resolves_pinned_row_with_live_doc_when_available():
    """When the live corpus DOES contain the pinned hub_doc_id, the
    row must be enriched from the live doc (not just the stub)."""
    docs = [_hub_doc(id="674926c1-d4da-42aa-897b-59cd4867c15f",
                     file_name="Hawkemedia_BILL-2026-04-84480_05012026.pdf",
                     vendor_canonical="",
                     invoice_number_clean="BILL-2026-04-84480",
                     amount_float=None)]
    rows, _ = smk.curate(hub_docs=docs, probe_rows=[], per_category=2)
    cleanup = [r for r in rows
               if r["test_doc_category"] == "metadata_cleanup_example"]
    hawkemedia = next(r for r in cleanup
                      if r["hub_doc_id"] ==
                      "674926c1-d4da-42aa-897b-59cd4867c15f")
    assert hawkemedia["file_name"] == \
        "Hawkemedia_BILL-2026-04-84480_05012026.pdf"
    assert hawkemedia["invoice_number_clean"] == "BILL-2026-04-84480"
    assert hawkemedia["vendor_canonical"] == ""  # Still missing — surfaced as such.


def test_curator_caps_per_category():
    docs = [_hub_doc(id=f"hub-{i}") for i in range(5)]
    rows, _ = smk.curate(hub_docs=docs, probe_rows=[], per_category=2)
    clean = [r for r in rows if r["test_doc_category"] == "clean_ap_invoice"]
    assert len(clean) == 2


def test_curator_does_not_dup_doc_within_same_category():
    docs = [_hub_doc(id="hub-1"), _hub_doc(id="hub-1")]  # accidental dup input
    rows, _ = smk.curate(hub_docs=docs, probe_rows=[], per_category=5)
    clean = [r for r in rows if r["test_doc_category"] == "clean_ap_invoice"]
    ids = [r["hub_doc_id"] for r in clean]
    assert len(set(ids)) == len(ids)


def test_curator_hub_document_url_uses_base_url_when_provided():
    docs = [_hub_doc(id="hub-1")]
    rows, _ = smk.curate(hub_docs=docs, probe_rows=[], per_category=1,
                         hub_base_url="https://hub.example.com/")
    clean = next(r for r in rows
                 if r["test_doc_category"] == "clean_ap_invoice")
    assert clean["hub_document_url"] == \
        "https://hub.example.com/documents/hub-1"


def test_curator_hub_document_url_falls_back_to_relative_path():
    docs = [_hub_doc(id="hub-1")]
    rows, _ = smk.curate(hub_docs=docs, probe_rows=[], per_category=1)
    clean = next(r for r in rows
                 if r["test_doc_category"] == "clean_ap_invoice")
    assert clean["hub_document_url"] == "/documents/hub-1"


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def test_resolve_probe_csv_picks_arg_path_first(tmp_path: Path,
                                                monkeypatch):
    arg_csv = tmp_path / "probe.csv"
    with open(arg_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f,
                           fieldnames=["classification", "best_hub_doc_id"])
        w.writeheader()
        w.writerow({"classification": "ocr_required", "best_hub_doc_id": "x"})
    path, rows = smk._resolve_probe_csv(str(arg_csv))
    assert path == str(arg_csv)
    assert len(rows) == 1


def test_resolve_probe_csv_returns_empty_when_absent(monkeypatch,
                                                    tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    path, rows = smk._resolve_probe_csv(None)
    assert path == ""
    assert rows == []


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def test_write_csv_emits_full_columns(tmp_path: Path):
    docs = [_hub_doc(id="hub-1")]
    rows, _ = smk.curate(hub_docs=docs, probe_rows=[], per_category=1)
    out = tmp_path / "smoke.csv"
    smk.write_csv(str(out), rows)
    with open(out, encoding="utf-8") as f:
        actual = list(csv.DictReader(f))
    assert actual, "csv has at least one row"
    expected_cols = set(smk.OUTPUT_COLUMNS)
    assert expected_cols.issubset(set(actual[0].keys()))


def test_write_md_groups_by_category_and_lists_missing(tmp_path: Path):
    docs = [_hub_doc(id="hub-1")]
    rows, missing = smk.curate(hub_docs=docs, probe_rows=[], per_category=1)
    out = tmp_path / "smoke.md"
    smk.write_md(str(out), rows, missing, probe_csv_path="probe.csv")
    text = out.read_text()
    assert "AP Internal Smoke-Test Document Set" in text
    assert "INTERNAL — IT / Engineering only" in text
    assert "Do not send" in text
    for c in smk.CATEGORIES:
        assert c in text
    if missing:
        assert "Missing categories in this run" in text
    # Pinned rows always show up.
    assert "674926c1-d4da-42aa-897b-59cd4867c15f" in text


# ---------------------------------------------------------------------------
# CLI smoke (mongomock)
# ---------------------------------------------------------------------------

def test_main_writes_artifacts_with_mongomock(tmp_path: Path,
                                              monkeypatch):
    import mongomock

    coll = mongomock.MongoClient().db.hub_documents
    coll.insert_one(_hub_doc(id="hub-clean"))
    coll.insert_one(_hub_doc(id="hub-dup", is_duplicate=True))
    coll.insert_one(_hub_doc(
        id="hub-mis",
        classification_override={"original_type": "Misc",
                                  "corrected_type": "AP_Invoice"}))
    monkeypatch.setattr(
        "scripts.build_ap_smoke_test_set.get_hub_documents_collection",
        lambda: coll,
    )

    csv_out = tmp_path / "out.csv"
    md_out = tmp_path / "out.md"
    monkeypatch.setattr("sys.argv", [
        "build_ap_smoke_test_set.py",
        "--out-csv", str(csv_out),
        "--out-md", str(md_out),
        "--per-category", "2",
    ])
    rc = smk.main()
    assert rc == 0
    assert csv_out.exists()
    assert md_out.exists()
    with open(csv_out, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cats = {r["test_doc_category"] for r in rows}
    # Must always include the pinned cleanup category.
    assert "metadata_cleanup_example" in cats
    # Must include real categories present in the synthetic corpus.
    assert "clean_ap_invoice" in cats
    assert "duplicate_or_possible_duplicate" in cats
    assert "misclassified_or_corrected" in cats
