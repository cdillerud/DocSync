"""Tests for the global hub_doc_id dedupe in build_ap_smoke_test_set.

A document that satisfies multiple non-pinned categories should only
emit a single CSV row (under its highest-priority category, which is
the first one emitted by `curate()`). Pinned categories
(`metadata_cleanup_example`) should still be allowed to re-emit a
hub_doc_id that appeared elsewhere.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

from scripts import build_ap_smoke_test_set as builder


def _make_doc(doc_id: str, *, file_name: str = "",
              vendor: str = "Acme Corp",
              invoice_number: str = "INV-001",
              amount: float = 100.00,
              po: str = "PO-1",
              ) -> Dict[str, Any]:
    return {
        "id": doc_id,
        "file_name": file_name or f"{doc_id}.pdf",
        "vendor_canonical": vendor,
        "invoice_number_clean": invoice_number,
        "amount_float": amount,
        "po_number_clean": po,
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
        "blocking_issues": [],
        "duplicate_status": "",
        "extracted_fields": {
            "vendor": vendor,
            "invoice_number": invoice_number,
            "amount": amount,
            "po_number": po,
        },
    }


def test_within_cluster_dedupe_keeps_first_category_only():
    """A doc that qualifies for both `clean_ap_invoice` AND
    `ap_invoice_invoice_number_populated` (both in the happy_path
    cluster) must only appear once. `curate()` emits clean first, so
    the row's category should be `clean_ap_invoice`."""
    docs: List[Dict[str, Any]] = [
        _make_doc(
            "doc-shared-1",
            file_name="CS 3000000223.PDF",
            vendor="MRP Solutions",
            invoice_number="3000000223",
            amount=1234.56,
            po="PO-001",
        ),
    ]

    rows, _missing = builder.curate(
        hub_docs=docs, probe_rows=[], per_category=2,
        hub_base_url="http://test",
    )

    matching = [r for r in rows if r["hub_doc_id"] == "doc-shared-1"
                and r["test_doc_category"] != "metadata_cleanup_example"]
    assert len(matching) == 1, (
        f"expected exactly 1 non-pinned row for doc-shared-1, got "
        f"{len(matching)}: {[r['test_doc_category'] for r in matching]}")
    assert matching[0]["test_doc_category"] == "clean_ap_invoice", (
        f"expected first emitted category 'clean_ap_invoice', got "
        f"{matching[0]['test_doc_category']}")


def test_pinned_category_still_emits_even_if_doc_seen_elsewhere():
    """If a pinned hub_doc_id also satisfies a regular category, the
    pinned row must still appear so the curatorial example survives."""
    pinned_id = builder.PINNED_METADATA_CLEANUP[0]["hub_doc_id"]
    docs: List[Dict[str, Any]] = [
        _make_doc(pinned_id, vendor="X", invoice_number="INV-1",
                  amount=10.0, po="PO-Z"),
    ]
    rows, _ = builder.curate(
        hub_docs=docs, probe_rows=[], per_category=2,
        hub_base_url="http://test",
    )
    pinned_rows = [r for r in rows
                   if r["hub_doc_id"] == pinned_id
                   and r["test_doc_category"] == "metadata_cleanup_example"]
    assert len(pinned_rows) >= 1, (
        "pinned metadata_cleanup_example row was suppressed by the "
        "dedupe — it must always emit.")


def test_distinct_docs_in_distinct_categories_unaffected():
    """The dedupe must not collapse rows that legitimately span
    different categories with different hub_doc_ids."""
    docs: List[Dict[str, Any]] = [
        _make_doc("doc-a", vendor="A", invoice_number="INV-A",
                  amount=10.0, po="PO-A"),
        _make_doc("doc-b", vendor="B", invoice_number="INV-B",
                  amount=20.0, po=""),  # missing po, won't qualify for po cat
    ]
    rows, _ = builder.curate(
        hub_docs=docs, probe_rows=[], per_category=2,
        hub_base_url="http://test",
    )
    ids = {(r["hub_doc_id"], r["test_doc_category"])
           for r in rows
           if r["test_doc_category"] != "metadata_cleanup_example"}
    # both docs must appear at least once.
    assert any(t[0] == "doc-a" for t in ids)
    assert any(t[0] == "doc-b" for t in ids)


def test_no_exact_duplicate_rows_in_output():
    """Walking a representative mix should never produce two rows
    with the same (hub_doc_id, test_doc_category) tuple — that was
    already guaranteed by `seen_pairs` and the new global dedupe
    must not regress this."""
    docs = [
        _make_doc(f"doc-{i}", vendor=f"V{i}",
                  invoice_number=f"INV-{i}", amount=float(i),
                  po=f"PO-{i}")
        for i in range(5)
    ]
    rows, _ = builder.curate(
        hub_docs=docs, probe_rows=[], per_category=2,
        hub_base_url="http://test",
    )
    pairs = [(r["hub_doc_id"], r["test_doc_category"]) for r in rows]
    assert len(pairs) == len(set(pairs)), (
        "exact-duplicate (hub_doc_id, category) row found: "
        f"{[p for p in pairs if pairs.count(p) > 1]}")
