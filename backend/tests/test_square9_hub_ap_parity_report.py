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

from datetime import datetime, timezone
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
