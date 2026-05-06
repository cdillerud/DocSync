"""Tests for square9_only_triage_resolver."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts import square9_only_triage_resolver as resolver


def _sq(name: str = "x.pdf",
        parent: str = "VendorA/2026-04",
        modified: str = "2026-05-06T10:00:00+00:00") -> resolver.Square9Row:
    return resolver.Square9Row.from_csv_row({
        "square9_name": name,
        "square9_parent_path": parent,
        "square9_modified": modified,
    })


def _hub(doc_id: str = "hub-1",
         file_name: str = "any.pdf",
         invoice_number_clean: str = "",
         vendor_canonical: str = "",
         mailbox_category: str = "AP",
         doc_type: str = "AP_INVOICE",
         suggested_job_type: str = "AP_Invoice",
         sharepoint_folder_path: str = "Freight Issues",
         routing_status: str = "auto_process",
         created_utc: str = "2026-05-06T10:00:00+00:00",
         invoice_date: str = "") -> resolver.HubDocLite:
    raw = {
        "id": doc_id,
        "file_name": file_name,
        "invoice_number_clean": invoice_number_clean,
        "vendor_canonical": vendor_canonical,
        "mailbox_category": mailbox_category,
        "doc_type": doc_type,
        "suggested_job_type": suggested_job_type,
        "sharepoint_folder_path": sharepoint_folder_path,
        "routing_status": routing_status,
        "created_utc": created_utc,
    }
    if invoice_date:
        raw["extracted_fields"] = {"invoice_date": invoice_date}
    return resolver.HubDocLite.from_mongo(raw)


# ----------------------------------------------------------------------------
# 1. Token extraction from real-world Square9 filename
# ----------------------------------------------------------------------------
def test_token_extraction_from_square9_filename():
    sq = _sq(
        name="113397_TUMALO_0307086_05052026.pdf",
        parent="Temp Folder/Warehouse Not International",
    )
    assert sq.norm_name
    # "0307086" should canonicalize to "307086" and end up in inv tokens
    assert "307086" in sq.inv_tokens
    # vendor_tokens should include "tumalo"
    assert "tumalo" in sq.vendor_tokens
    # filename has a recognizable date 05052026 (US-style MMDDYYYY token)
    assert sq.inferred_date is not None
    assert sq.inferred_date.year == 2026


# ----------------------------------------------------------------------------
# 2. Bucket A — Hub has the doc but classified non-AP
# ----------------------------------------------------------------------------
def test_bucket_A_hub_match_non_AP():
    sq = _sq(name="113397_TUMALO_0307086_05052026.pdf")
    hubs = [_hub(
        file_name="0307086.pdf",
        invoice_number_clean="0307086",
        vendor_canonical="TUMALO",
        mailbox_category="OPS",
        doc_type="OPS_DOCUMENT",
        suggested_job_type="Operations",
        created_utc=datetime.now(timezone.utc).isoformat(),
    )]
    inv_idx, norm_idx = resolver.build_indexes(hubs)
    v = resolver.find_best_match(sq, hubs, inv_idx, norm_idx)
    assert v.hub is not None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=720)
    bucket, action = resolver.classify(v, cutoff)
    assert bucket == "A"
    assert "reclassify_to_AP" in action


# ----------------------------------------------------------------------------
# 3. Bucket B — Hub has AP version but outside window
# ----------------------------------------------------------------------------
def test_bucket_B_AP_match_outside_window():
    sq = _sq(name="113397_TUMALO_0307086_05052026.pdf")
    old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    hubs = [_hub(
        file_name="0307086.pdf",
        invoice_number_clean="0307086",
        vendor_canonical="TUMALO",
        mailbox_category="AP",
        created_utc=old_iso,
    )]
    inv_idx, norm_idx = resolver.build_indexes(hubs)
    v = resolver.find_best_match(sq, hubs, inv_idx, norm_idx)
    assert v.hub is not None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=720)  # 30d
    bucket, action = resolver.classify(v, cutoff)
    assert bucket == "B"
    assert "extend_parity_window" in action or "no_action" in action


# ----------------------------------------------------------------------------
# 4. Bucket C — Hub does not have the doc anywhere
# ----------------------------------------------------------------------------
def test_bucket_C_no_hub_match():
    sq = _sq(name="totally_orphan_invoice_99999.pdf",
             parent="Temp Folder/Vendor Credit Memos")
    hubs = [_hub(file_name="something_completely_else.pdf",
                 invoice_number_clean="11111",
                 vendor_canonical="OtherCorp")]
    inv_idx, norm_idx = resolver.build_indexes(hubs)
    v = resolver.find_best_match(sq, hubs, inv_idx, norm_idx)
    assert v.hub is None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=720)
    bucket, action = resolver.classify(v, cutoff)
    assert bucket == "C"
    assert "intake" in action or "exchange" in action or "expand" in action


# ----------------------------------------------------------------------------
# 5. Bucket D — Hub has AP in-window, but parity matcher missed it
# ----------------------------------------------------------------------------
def test_bucket_D_AP_in_window_matcher_missed():
    sq = _sq(name="113397_TUMALO_0307086_05052026.pdf")
    fresh_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    hubs = [_hub(
        file_name="0307086.pdf",
        invoice_number_clean="0307086",
        vendor_canonical="TUMALO",
        mailbox_category="AP",
        created_utc=fresh_iso,
    )]
    inv_idx, norm_idx = resolver.build_indexes(hubs)
    v = resolver.find_best_match(sq, hubs, inv_idx, norm_idx)
    assert v.hub is not None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=720)
    bucket, action = resolver.classify(v, cutoff)
    assert bucket == "D"
    assert "matcher_precision" in action or "improve_parity" in action


# ----------------------------------------------------------------------------
# 6. Output CSV writes expected columns + bucket value
# ----------------------------------------------------------------------------
def test_csv_output_columns(tmp_path):
    out = tmp_path / "resolved.csv"
    sq = _sq(name="orphan.pdf")
    rows = [resolver.build_row(
        sq, resolver.MatchVerdict(None, 0.0, "no_evidence"),
        "C", "expand_intake_channel_or_exchange_rule",
    )]
    resolver.write_csv(str(out), rows)
    import csv as _csv
    with open(out, encoding="utf-8") as f:
        reader = list(_csv.DictReader(f))
    assert set(reader[0].keys()) == set(resolver.OUTPUT_COLUMNS)
    assert reader[0]["bucket"] == "C"
    assert reader[0]["square9_name"] == "orphan.pdf"
    assert reader[0]["recommended_action"] == "expand_intake_channel_or_exchange_rule"


# ----------------------------------------------------------------------------
# 7. End-to-end resolve() pure function aggregates all 4 buckets correctly
# ----------------------------------------------------------------------------
def test_resolve_aggregates_all_buckets():
    fresh = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    sq_rows = [
        _sq(name="bucketA_TUMALO_0001111.pdf"),     # → A (non-AP hub match)
        _sq(name="bucketB_TUMALO_0002222.pdf"),     # → B (AP hub match, old)
        _sq(name="bucketC_orphan_X.pdf",
            parent="Temp Folder/Vendor Credit Memos"),  # → C
        _sq(name="bucketD_TUMALO_0004444.pdf"),     # → D (AP in window)
    ]
    hubs = [
        _hub(doc_id="A1", file_name="0001111.pdf",
             invoice_number_clean="1111", vendor_canonical="TUMALO",
             mailbox_category="OPS", created_utc=fresh),
        _hub(doc_id="B1", file_name="0002222.pdf",
             invoice_number_clean="2222", vendor_canonical="TUMALO",
             mailbox_category="AP", created_utc=old),
        _hub(doc_id="D1", file_name="0004444.pdf",
             invoice_number_clean="4444", vendor_canonical="TUMALO",
             mailbox_category="AP", created_utc=fresh),
    ]
    result = resolver.resolve(sq_rows, hubs, since_hours=720)
    assert result["counts"] == {"A": 1, "B": 1, "C": 1, "D": 1}
    assert result["total"] == 4

    by_bucket = {r["bucket"]: r for r in result["rows"]}
    assert by_bucket["A"]["best_hub_doc_id"] == "A1"
    assert by_bucket["B"]["best_hub_doc_id"] == "B1"
    assert by_bucket["C"]["best_hub_doc_id"] == ""
    assert by_bucket["D"]["best_hub_doc_id"] == "D1"


# ----------------------------------------------------------------------------
# 8. find_best_match returns None below min_score (no false positives)
# ----------------------------------------------------------------------------
def test_no_false_positive_below_min_score():
    sq = _sq(name="totally_unique_999999.pdf",
             parent="Temp Folder/Misc")
    hubs = [_hub(file_name="completely_different.pdf",
                 invoice_number_clean="11111",
                 vendor_canonical="UnrelatedCorp")]
    inv_idx, norm_idx = resolver.build_indexes(hubs)
    v = resolver.find_best_match(sq, hubs, inv_idx, norm_idx,
                                 min_score=0.40)
    assert v.hub is None
    assert v.score == 0.0


# ----------------------------------------------------------------------------
# 9. Filename-exact match wins over weaker invoice-token candidates
# ----------------------------------------------------------------------------
def test_filename_exact_beats_weaker_match():
    sq = _sq(name="0307086.pdf")
    hubs = [
        _hub(doc_id="weak", file_name="other.pdf",
             invoice_number_clean="0307086"),
        _hub(doc_id="exact", file_name="0307086.pdf",
             invoice_number_clean="0307086"),
    ]
    inv_idx, norm_idx = resolver.build_indexes(hubs)
    v = resolver.find_best_match(sq, hubs, inv_idx, norm_idx)
    assert v.hub is not None
    assert v.hub.doc_id == "exact"
    assert v.reason == "filename_exact"
