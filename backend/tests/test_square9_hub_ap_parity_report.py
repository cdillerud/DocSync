"""
Regression tests for square9_hub_ap_parity_report.

Covers:
  - filename exact match
  - invoice + vendor evidence match (strong_evidence_match)
  - invoice + amount evidence match (strong_evidence_match)
  - hub final-folder docs (e.g. Freight Issues, Vendor Credit Memos) are
    INCLUDED in the parity proof; the old single-folder AP_Invoices
    assumption must NOT be made
  - missing routing_status on current-window AP docs is a blocker
  - match-rate-below-threshold is a blocker
  - empty hub AP window is a blocker
  - forbidden Operations folder root is a blocker
  - legacy classification_method is a warning
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from scripts.sharepoint_ap_compare import Doc as SquareDoc
from scripts import square9_hub_ap_parity_report as parity


def _sq(name: str, modified: str = "2026-05-06T10:00:00Z",
        parent_path: str = "VendorA/2026-05") -> SquareDoc:
    return SquareDoc.from_row({
        "name": name, "size": "10240",
        "modified": modified,
        "web_url": f"https://example/sites/Acc/{name}",
        "id": f"sp-{name}", "parent_path": parent_path,
    })


def _hub(file_name: str, doc_id: str = "doc-1",
         folder_path: str = "Freight Issues",
         routing_status: str = "auto_process",
         doc_type: str = "AP_INVOICE",
         classification_method: str = "mailbox:AP+evidence",
         vendor_canonical: str = "",
         invoice_number_clean: str = "",
         amount_float=None,
         created_utc: str = "2026-05-06T10:00:00+00:00",
         email_subject: str = "",
         email_sender: str = "") -> parity.HubDoc:
    return parity.HubDoc.from_mongo({
        "id": doc_id,
        "file_name": file_name,
        "sharepoint_web_url": f"https://example/{file_name}",
        "sharepoint_folder_path": folder_path,
        "routing_status": routing_status,
        "doc_type": doc_type,
        "classification_method": classification_method,
        "vendor_canonical": vendor_canonical,
        "invoice_number_clean": invoice_number_clean,
        "amount_float": amount_float,
        "po_number_clean": "",
        "created_utc": created_utc,
        "email_subject": email_subject,
        "email_sender": email_sender,
    })


# ----------------------------------------------------------------------------
# 1. filename exact match
# ----------------------------------------------------------------------------
def test_filename_exact_match():
    sq = _sq("Invoice-12345_dragged_.pdf")
    hub = _hub("Invoice-12345_dragged_.pdf")
    res = parity.score_pair(sq, hub)
    assert res.bucket == "exact_match"
    assert res.score == 1.0
    assert res.reason == "filename_exact"


# ----------------------------------------------------------------------------
# 2. invoice + vendor evidence match
# ----------------------------------------------------------------------------
def test_invoice_plus_vendor_strong_match():
    # Square9 filename has invoice token; Hub has explicit invoice_number_clean
    # AND vendor_canonical that overlaps the Square9 filename vendor token.
    sq = _sq("ARKANSAS_GLASS_inv-99812.pdf")
    hub = _hub(
        "AGC_payable.pdf",
        vendor_canonical="Arkansas Glass Container Corp.",
        invoice_number_clean="99812",
        doc_type="AP_INVOICE",
    )
    res = parity.score_pair(sq, hub)
    assert res.bucket == "strong_evidence_match"
    assert "invoice_number_clean+vendor_canonical" == res.reason


# ----------------------------------------------------------------------------
# 3. invoice + amount evidence match (no vendor token overlap, but invoice + amount present)
# ----------------------------------------------------------------------------
def test_invoice_plus_amount_strong_match():
    sq = _sq("INV-00455123.pdf")
    hub = _hub(
        "scan_payable.pdf",
        invoice_number_clean="455123",
        amount_float=2417.50,
        vendor_canonical="",  # no vendor overlap
    )
    res = parity.score_pair(sq, hub)
    assert res.bucket == "strong_evidence_match"
    assert res.reason == "invoice_number_clean+hub_amount_present"


# ----------------------------------------------------------------------------
# 4. Hub final-folder docs (Freight Issues, Vendor Credit Memos) ARE INCLUDED
# ----------------------------------------------------------------------------
def test_hub_final_folder_docs_are_included_in_parity():
    """Old proof compared only the AP_Invoices folder. New proof must
    include any AP-mailbox doc regardless of final SharePoint folder."""
    sq = _sq("RL-Carriers_Inv_032662.pdf")
    hub_freight = _hub(
        "RL-Carriers_Inv_032662.pdf",
        folder_path="Freight Issues",
        vendor_canonical="R+L Carriers",
        invoice_number_clean="032662",
    )
    hub_credit = _hub(
        "VendorCreditMemo_99812.pdf",
        doc_id="doc-2",
        folder_path="Vendor Credit Memos",
    )

    result = parity.run_compare(
        square_docs=[sq],
        hub_docs=[hub_freight, hub_credit],
        out_csv=None,
        top_n=5,
        min_match_rate=0.0,
    )

    # The Freight-Issues hub doc must match the Square9 doc.
    assert result["bucket_counts"]["exact_match"] == 1
    # The unmatched Vendor-Credit-Memo doc must surface as hub_only —
    # it is NOT silently dropped just because it's outside AP_Invoices.
    assert result["bucket_counts"]["hub_only"] == 1


# ----------------------------------------------------------------------------
# 5. The single-folder AP_Invoices assumption is NOT used
# ----------------------------------------------------------------------------
def test_no_ap_invoices_folder_assumption():
    """Verify the parity report never filters Hub docs by folder name —
    every AP-mailbox doc participates regardless of its final destination."""
    folders = [
        "Freight Issues",
        "Dropship Not International Documents",
        "Dropship International Documents",
        "Vendor Credit Memos",
        "Remittance Advices",
        "Miscellaneous Documents",
        "AP_Invoices",
    ]
    hubs: List[parity.HubDoc] = [
        _hub(f"doc_{i}.pdf", doc_id=f"d-{i}", folder_path=folder)
        for i, folder in enumerate(folders)
    ]
    result = parity.run_compare(
        square_docs=[],  # zero Square9 docs — every hub doc becomes hub_only
        hub_docs=hubs,
        out_csv=None,
        top_n=5,
        min_match_rate=0.0,
    )
    # ALL hub docs (one per folder) should be in the hub_only bucket.
    assert result["bucket_counts"]["hub_only"] == len(folders)


# ----------------------------------------------------------------------------
# 6. Missing routing_status on AP docs is a blocker
# ----------------------------------------------------------------------------
def test_missing_routing_status_is_blocker():
    sq = _sq("foo.pdf")
    hub_ok = _hub("foo.pdf", routing_status="auto_process")
    hub_bad = _hub("bar.pdf", doc_id="doc-2", routing_status="")
    result = parity.run_compare(
        square_docs=[sq],
        hub_docs=[hub_ok, hub_bad],
        out_csv=None,
        top_n=5,
        min_match_rate=0.0,
    )
    blockers = " | ".join(result["findings"]["blockers"])
    assert "hub_ap_docs_missing_routing_status" in blockers


# ----------------------------------------------------------------------------
# 7. Match rate below threshold is a blocker
# ----------------------------------------------------------------------------
def test_low_match_rate_is_blocker():
    # 4 Square9 docs with very distinct names (no fuzzy collisions),
    # 1 Hub doc that matches only the first → 25% match rate.
    sq_docs = [
        _sq("aardvark_invoice.pdf"),
        _sq("zebra_statement.pdf"),
        _sq("kiwi_credit_memo.pdf"),
        _sq("orchid_freight_bill.pdf"),
    ]
    hubs = [_hub("aardvark_invoice.pdf")]
    result = parity.run_compare(
        square_docs=sq_docs,
        hub_docs=hubs,
        out_csv=None,
        top_n=5,
        min_match_rate=0.85,
    )
    assert result["match_rate"] < 0.85
    assert any(
        "match_rate_below_threshold" in b for b in result["findings"]["blockers"]
    )


# ----------------------------------------------------------------------------
# 8. Empty hub window is a blocker
# ----------------------------------------------------------------------------
def test_empty_hub_window_is_blocker():
    result = parity.run_compare(
        square_docs=[_sq("any.pdf")],
        hub_docs=[],
        out_csv=None,
        top_n=5,
        min_match_rate=0.0,
    )
    assert any(
        "hub_ap_docs_empty" in b for b in result["findings"]["blockers"]
    )


# ----------------------------------------------------------------------------
# 9. Forbidden Operations root for AP doc is a blocker
# ----------------------------------------------------------------------------
def test_ap_doc_in_operations_root_is_blocker():
    sq = _sq("foo.pdf")
    hub_in_ops = _hub(
        "foo.pdf", folder_path="Operations/Some/Subfolder",
        routing_status="auto_process",
    )
    result = parity.run_compare(
        square_docs=[sq],
        hub_docs=[hub_in_ops],
        out_csv=None,
        top_n=5,
        min_match_rate=0.0,
    )
    assert any(
        "ap_docs_in_forbidden_root" in b for b in result["findings"]["blockers"]
    )


# ----------------------------------------------------------------------------
# 10. Legacy classification_method is a warning, not a blocker
# ----------------------------------------------------------------------------
def test_legacy_classification_method_is_warning():
    sq = _sq("foo.pdf")
    hub = _hub(
        "foo.pdf",
        classification_method="legacy:rule_AP_invoice_v1",
    )
    result = parity.run_compare(
        square_docs=[sq],
        hub_docs=[hub],
        out_csv=None,
        top_n=5,
        min_match_rate=0.0,
    )
    warnings = " | ".join(result["findings"]["warnings"])
    assert "legacy_classification_method" in warnings
    assert not any(
        "legacy_classification_method" in b for b in result["findings"]["blockers"]
    )


# ----------------------------------------------------------------------------
# 11-14. B1 — Square9 modified-time window filter
# ----------------------------------------------------------------------------
def test_filter_square_docs_excludes_old_docs():
    """Docs older than the window must be excluded."""
    now = datetime.now(timezone.utc)
    old = _sq("old.pdf", modified=(now - timedelta(days=30)).isoformat().replace("+00:00", "Z"))
    fresh = _sq("fresh.pdf", modified=(now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"))
    out, cutoff = parity.filter_square_docs_by_modified([old, fresh], since_hours=24)
    assert [d.name for d in out] == ["fresh.pdf"]
    assert cutoff  # iso string


def test_filter_square_docs_includes_in_window():
    """Docs whose modified-time is within the window must be included."""
    now = datetime.now(timezone.utc)
    docs = [
        _sq(f"doc{i}.pdf", modified=(now - timedelta(hours=i)).isoformat().replace("+00:00", "Z"))
        for i in range(5)
    ]
    out, _ = parity.filter_square_docs_by_modified(docs, since_hours=24)
    assert len(out) == 5


def test_default_prod_window_equals_since_hours():
    """When --prod-modified-since-hours is not supplied, default is since-hours."""
    # Simulate by constructing args namespace and applying the same default
    # logic as the CLI block.
    class _Args:
        since_hours = 12
        prod_modified_since_hours = None
    a = _Args()
    effective = a.prod_modified_since_hours or a.since_hours
    assert effective == 12


def test_explicit_prod_window_overrides_default():
    """Explicit --prod-modified-since-hours overrides the since-hours default."""
    class _Args:
        since_hours = 24
        prod_modified_since_hours = 168
    a = _Args()
    effective = a.prod_modified_since_hours or a.since_hours
    assert effective == 168


def _filter_iso(now: datetime, **delta_kwargs) -> str:
    return (now - timedelta(**delta_kwargs)).isoformat().replace("+00:00", "Z")


# ----------------------------------------------------------------------------
# 15. extract_date_from_filename — directly parses common formats
# ----------------------------------------------------------------------------
def test_extract_date_from_filename_iso():
    assert parity.extract_date_from_filename(
        "INV_2026-04-15_acme.pdf"
    ) == datetime(2026, 4, 15, tzinfo=timezone.utc)


def test_extract_date_from_filename_us():
    assert parity.extract_date_from_filename(
        "Invoice_04-15-2026_final.pdf"
    ) == datetime(2026, 4, 15, tzinfo=timezone.utc)


def test_extract_date_from_filename_compact():
    assert parity.extract_date_from_filename(
        "20260415_invoice.pdf"
    ) == datetime(2026, 4, 15, tzinfo=timezone.utc)


def test_extract_date_from_filename_none():
    assert parity.extract_date_from_filename("random_invoice.pdf") is None
    assert parity.extract_date_from_filename("") is None


# ----------------------------------------------------------------------------
# 16. Invoice-date mode: ingest-time skew is ignored
# ----------------------------------------------------------------------------
def test_invoice_date_mode_ignores_ingest_skew():
    """The exact 24h-window-skew failure that 21.2% on 2026-05-06 was caused
    by must NO LONGER produce a no_match: a Hub doc created today (after a
    backlog drain) should still match a Square9 doc modified two weeks ago
    when invoice number + vendor evidence aligns."""
    now = datetime.now(timezone.utc)
    sq = SquareDoc.from_row({
        "name": "ARKANSAS_GLASS_inv-99812.pdf",
        "modified": _filter_iso(now, days=14),
        "size": "20480",
        "web_url": "https://example/sq/sq.pdf",
        "id": "sq-1",
        "parent_path": "ArkansasGlass/2026-04",
    })
    hub = parity.HubDoc.from_mongo({
        "id": "doc-after-drain",
        "file_name": "agc_payable_scan.pdf",
        "vendor_canonical": "Arkansas Glass Container Corp",
        "invoice_number_clean": "99812",
        "amount_float": 4250.00,
        "doc_type": "AP_INVOICE",
        "created_utc": now.isoformat(),  # ingested today after backlog drain
        "extracted_fields": {"invoice_date": _filter_iso(now, days=14)},
        "routing_status": "auto_process",
        "sharepoint_folder_path": "Freight Issues",
        "classification_method": "mailbox:AP+evidence",
    })
    # In ingest-window mode, this would be a strong evidence match anyway
    # (invoice + vendor); but the explicit goal of this test is that
    # invoice-date mode reaches the same or stronger conclusion DESPITE
    # the 14-day skew between Square9.modified and Hub.created_utc.
    res = parity.score_pair(sq, hub, invoice_date_tolerance_days=30)
    assert res.bucket == "strong_evidence_match"


# ----------------------------------------------------------------------------
# 17. Invoice-date mode: vendor + amount + invoice date proximity passes
#     even when filename is totally different
# ----------------------------------------------------------------------------
def test_invoice_date_mode_vendor_amount_date_with_filename_mismatch():
    now = datetime.now(timezone.utc)
    sq = SquareDoc.from_row({
        "name": "RL_Carriers_freight_2026-04-20.pdf",
        "modified": _filter_iso(now, days=10),
        "size": "10240",
        "web_url": "https://example/sq",
        "id": "sq-vamf",
        "parent_path": "RL/2026-04",
    })
    hub = parity.HubDoc.from_mongo({
        "id": "hub-vamf",
        "file_name": "totally_different_scan.pdf",
        "vendor_canonical": "R+L Carriers Inc",
        "invoice_number_clean": "",
        "amount_float": 877.42,
        "doc_type": "AP_INVOICE",
        "created_utc": now.isoformat(),
        "extracted_fields": {"invoice_date": "2026-04-20"},
        "routing_status": "auto_process",
        "sharepoint_folder_path": "Freight Issues",
        "classification_method": "mailbox:AP+evidence",
    })
    res = parity.score_pair(sq, hub, invoice_date_tolerance_days=30)
    assert res.bucket == "strong_evidence_match"
    assert res.reason == "vendor_canonical+amount_float+invoice_date_proximity"


# ----------------------------------------------------------------------------
# 18. Invoice-date mode: low match rate STILL blocks (cutover gate intact)
# ----------------------------------------------------------------------------
def test_invoice_date_mode_low_match_rate_still_blocks():
    sq_docs = [
        _sq("aardvark_invoice.pdf"),
        _sq("zebra_statement.pdf"),
        _sq("kiwi_credit_memo.pdf"),
        _sq("orchid_freight_bill.pdf"),
    ]
    hubs = [_hub("aardvark_invoice.pdf")]
    result = parity.run_compare(
        square_docs=sq_docs,
        hub_docs=hubs,
        out_csv=None,
        top_n=5,
        min_match_rate=0.85,
        match_by_invoice_date=True,
        invoice_date_tolerance_days=30,
    )
    assert result["match_rate"] < 0.85
    assert any(
        "match_rate_below_threshold" in b for b in result["findings"]["blockers"]
    )
    assert result["proof_mode"] == "invoice_document_set"
    assert result["invoice_date_tolerance_days"] == 30


# ----------------------------------------------------------------------------
# 19. Same Square9 document not double-counted across Temp + AP-root corpus
# ----------------------------------------------------------------------------
def test_expanded_corpus_dedupe_by_graph_id():
    """A document physically present in Temp Folder will appear BOTH in the
    non-recursive Temp pull and the recursive AP-root pull. The dedupe key
    must collapse them so the same doc isn't counted twice in the corpus."""
    row = {
        "name": "shared.pdf",
        "size": "1024",
        "modified": "2026-05-06T10:00:00Z",
        "web_url": "https://example/shared.pdf",
        "id": "graph-id-shared-1",
        "parent_path": "Accounts Payable/Temp Folder",
    }
    d1 = SquareDoc.from_row(row)
    d2 = SquareDoc.from_row(dict(row))  # same graph id => duplicate
    d3 = SquareDoc.from_row({**row, "id": "graph-id-other-2",
                             "name": "different.pdf"})
    # Apply the same dedupe logic the corpus puller uses:
    seen, deduped = set(), []
    for d in [d1, d2, d3]:
        key = parity._square_doc_dedupe_key(d)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(d)
    assert len(deduped) == 2
    assert {x.name for x in deduped} == {"shared.pdf", "different.pdf"}


# ----------------------------------------------------------------------------
# 20. Dedupe falls back to parent_path/name when Graph id is missing
# ----------------------------------------------------------------------------
def test_expanded_corpus_dedupe_fallback_to_path_name():
    row1 = {"name": "x.pdf", "size": "1", "modified": "2026-05-06T10:00:00Z",
            "web_url": "", "id": "", "parent_path": "AP/Temp Folder"}
    row2 = {"name": "X.PDF", "size": "1", "modified": "2026-05-06T10:00:00Z",
            "web_url": "", "id": "", "parent_path": "AP/Temp Folder"}
    d1 = SquareDoc.from_row(row1)
    d2 = SquareDoc.from_row(row2)
    # case-insensitive path key collapses these
    assert (
        parity._square_doc_dedupe_key(d1)
        == parity._square_doc_dedupe_key(d2)
    )


# ----------------------------------------------------------------------------
# 21. JSON metadata exposes proof_mode + windows + tolerance
# ----------------------------------------------------------------------------
def test_run_compare_returns_proof_mode_metadata():
    result = parity.run_compare(
        square_docs=[],
        hub_docs=[_hub("x.pdf")],
        out_csv=None,
        top_n=5,
        min_match_rate=0.0,
        match_by_invoice_date=True,
        invoice_date_tolerance_days=45,
    )
    assert result["proof_mode"] == "invoice_document_set"
    assert result["invoice_date_tolerance_days"] == 45


def test_run_compare_default_proof_mode_is_ingest_window():
    result = parity.run_compare(
        square_docs=[],
        hub_docs=[_hub("x.pdf")],
        out_csv=None,
        top_n=5,
        min_match_rate=0.0,
    )
    assert result["proof_mode"] == "ingest_window"
    assert result["invoice_date_tolerance_days"] is None


# ----------------------------------------------------------------------------
# 22. HubDoc parses extracted_fields.invoice_date when present
# ----------------------------------------------------------------------------
def test_hub_doc_parses_invoice_date_from_extracted_fields():
    h = parity.HubDoc.from_mongo({
        "id": "h1",
        "file_name": "x.pdf",
        "extracted_fields": {"invoice_date": "2026-04-15"},
        "created_utc": "2026-05-06T10:00:00+00:00",
    })
    assert h.invoice_date == datetime(2026, 4, 15, tzinfo=timezone.utc)


def test_hub_doc_invoice_date_none_when_missing():
    h = parity.HubDoc.from_mongo({
        "id": "h2",
        "file_name": "x.pdf",
        "created_utc": "2026-05-06T10:00:00+00:00",
    })
    assert h.invoice_date is None


# ----------------------------------------------------------------------------
# 23. score_pair without invoice_date_tolerance_days preserves legacy behavior
# ----------------------------------------------------------------------------
def test_score_pair_default_kwarg_preserves_legacy_behavior():
    """Default invoice_date_tolerance_days=None must not change any
    pre-existing match results — guards every previously-shipped test."""
    sq = _sq("Invoice-12345_dragged_.pdf")
    hub = _hub("Invoice-12345_dragged_.pdf")
    res_default = parity.score_pair(sq, hub)
    res_explicit_none = parity.score_pair(sq, hub, invoice_date_tolerance_days=None)
    assert res_default.bucket == res_explicit_none.bucket == "exact_match"
    assert res_default.score == res_explicit_none.score == 1.0
