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
# Regex hardening (regression for production VM run on 2026-02:
# garbage captures like 'OICE' / 'DATE' / 'LINE' / 'INVOICE')
# ---------------------------------------------------------------------------

# -- Failure-mode: the broken patterns must no longer emit noise -----------

def test_invoice_regex_does_not_match_inv_inside_invoice():
    """The previous regex matched ``inv`` as a label inside the word
    ``INVOICE`` and captured the rest (``OICE``)."""
    sig = probe.extract_body_signals(
        "INVOICE\n123 Main St\nBill to: Acme Corp\n")
    assert sig["invoice_number"] != "OICE"
    assert sig["invoice_number"] is None


def test_invoice_regex_rejects_bare_label_words():
    sig = probe.extract_body_signals(
        "DATE: 2026-04-30\nLINE 12345\nINVOICE\n")
    assert sig["invoice_number"] not in ("DATE", "LINE", "INVOICE", "OICE")


def test_po_regex_does_not_capture_invoice_as_po():
    """Previous regex turned ``P.O. INVOICE NO 12345`` into
    po_number=``INVOICE``."""
    sig = probe.extract_body_signals("P.O. INVOICE NO 12345")
    assert sig["po_number"] != "INVOICE"
    assert sig["po_number"] != "LINE"


def test_po_regex_does_not_match_inside_words_like_policy():
    sig = probe.extract_body_signals("Our policy 9988 is strict")
    # 'policy' must NOT be captured as a PO label.
    assert sig["po_number"] is None


def test_reference_regex_drops_pure_label_words():
    sig = probe.extract_body_signals(
        "Reference Number: A27300\nCONFIRMATION\nNUMBER\nORDER NO 9988\n")
    refs = sig["reference_numbers"]
    for noise in ("CONFIRMATION", "NUMBER", "REFERENCE", "ORDER", "OICE"):
        assert noise not in refs


def test_oice_oices_never_extracted_as_invoice_or_po():
    """The literal 'OICE' / 'OICES' tokens were the dominant garbage
    in production. They must never come back."""
    text = "INVOICES are due\nINVOICE 110604\nOICE noise\n"
    sig = probe.extract_body_signals(text)
    assert sig["invoice_number"] not in ("OICE", "OICES")


def test_clean_capture_rejects_noise_tokens_directly():
    for noise in ("OICE", "OICES", "DATE", "LINE", "INVOICE",
                  "NUMBER", "REFERENCE", "CONFIRMATION", "TOTAL",
                  "BALANCE"):
        assert probe._clean_capture(noise) is None
    # Empty / whitespace.
    assert probe._clean_capture("") is None
    assert probe._clean_capture("   ") is None
    # No-digit garbage.
    assert probe._clean_capture("ALPHA") is None
    # Real invoice value survives.
    assert probe._clean_capture("INV-12345") == "INV-12345"
    assert probe._clean_capture("110604") == "110604"


# -- Positive: real values still extract --------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Invoice 110604\nDate: 04/15/2026", "110604"),
    ("Invoice No. 306665", "306665"),
    ("INVOICE NUMBER 110604", "110604"),
    ("Invoice #: INV-12345", "INV-12345"),
    ("Inv. No. 2923600", "2923600"),
    ("Invoice P0024316-32", "P0024316-32"),
    ("INVOICE\nNumber: 110604", "110604"),
])
def test_invoice_regex_extracts_real_values(text: str, expected: str):
    sig = probe.extract_body_signals(text)
    assert sig["invoice_number"] == expected


@pytest.mark.parametrize("text,expected", [
    ("P.O. 113881", "113881"),
    ("PO# 113881", "113881"),
    ("PO-113881", "113881"),
    ("Purchase Order: 113881", "113881"),
    ("PO Number 113881", "113881"),
    ("P.O. Number 2923600", "2923600"),
])
def test_po_regex_extracts_real_values(text: str, expected: str):
    sig = probe.extract_body_signals(text)
    assert sig["po_number"] == expected


def test_reference_regex_extracts_real_values():
    sig = probe.extract_body_signals(
        "Reference: A27300\nORDER NO 1234567\nBOL: BOL-99887\n"
        "Ref# 2923600")
    refs = sig["reference_numbers"]
    assert "A27300" in refs
    assert "1234567" in refs
    assert "BOL-99887" in refs
    assert "2923600" in refs
    # Pure label words stripped.
    for noise in ("REFERENCE", "ORDER", "BOL", "REF"):
        assert noise not in refs


def test_extracted_values_always_contain_a_digit():
    sig = probe.extract_body_signals(
        "Invoice ALPHA\nP.O. BETA\nReference: GAMMA")
    assert sig["invoice_number"] is None
    assert sig["po_number"] is None
    assert sig["reference_numbers"] == []


# Production regression: the actual broken row from the VM run
# ('110604 Global Grinders 260210 ORD006852.pdf') had body text whose
# previous extraction emitted invoice='OICE', po='INVOICE'. Verify
# extraction is now sane on that file's likely structure.
def test_production_regression_global_grinders_style_invoice():
    body = (
        "INVOICE\n"
        "Date: 02/10/2026\n"
        "Invoice Number: 110604\n"
        "Order Reference: ORD006852\n"
        "Total: $2,250.40\n"
    )
    sig = probe.extract_body_signals(body)
    assert sig["invoice_number"] == "110604"
    assert sig["po_number"] is None
    assert "ORD006852" in sig["reference_numbers"]
    assert sig["amount"] == 2250.40
    assert sig["invoice_date"] == "2026-02-10"


# ---------------------------------------------------------------------------
# Regex tightening pass #2 (production VM 2026-02 follow-up):
# - dates must not be captured as invoice numbers
# - invoice values must not absorb the next word (ACCOUNT, NUMBER, ...)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Invoice 05/01/26",
    "Invoice Date: 05/01/26",
    "INVOICE\n4/30/26",
    "Invoice 2026-04-30",
    "Inv 04-15-2026",
])
def test_dates_are_never_extracted_as_invoice_numbers(text: str):
    sig = probe.extract_body_signals(text)
    inv = sig["invoice_number"] or ""
    # No slash should ever appear in an invoice capture.
    assert "/" not in inv
    # And no MM-DD-YY/YYYY-MM-DD shape.
    assert not probe._DATE_SHAPE_RE.match(inv)


def test_invoice_capture_does_not_absorb_trailing_word():
    """Production case: ``9-275-62775ACCOUNT`` was captured as one
    token because the previous regex allowed letters after digits."""
    sig = probe.extract_body_signals("Invoice 9-275-62775ACCOUNT 04/29/2026")
    assert sig["invoice_number"] == "9-275-62775"


def test_invoice_capture_does_not_absorb_trailing_account_word_v2():
    sig = probe.extract_body_signals("Invoice No 9-285-37538 ACCOUNT NUMBER")
    assert sig["invoice_number"] == "9-285-37538"


def test_invoice_capture_does_not_absorb_word_directly_glued():
    # Even with the word right next to the digit run, capture must
    # end in a digit, dropping the glued letters.
    sig = probe.extract_body_signals("Invoice 30018395INVOICE")
    assert sig["invoice_number"] == "30018395"


@pytest.mark.parametrize("text,expected", [
    # Hawkemedia-style production value.
    ("Invoice BILL-2026-04-84480", "BILL-2026-04-84480"),
    # First Choice / BlueTiger.
    ("Invoice MN-1259515", "MN-1259515"),
    ("Invoice MN-1283736", "MN-1283736"),
    # MRA.
    ("Invoice 30018395", "30018395"),
    # Vans.
    ("Invoice ST026692", "ST026692"),
    # FedEx-style.
    ("Invoice 9-275-62775", "9-275-62775"),
    ("Invoice 9-285-37538", "9-285-37538"),
])
def test_invoice_regex_pass2_preserves_real_values(
        text: str, expected: str):
    sig = probe.extract_body_signals(text)
    assert sig["invoice_number"] == expected


# ---------------------------------------------------------------------------
# Reference-number scoring (Part B)
# ---------------------------------------------------------------------------

def test_hub_record_builds_reference_haystack_from_extracted_fields():
    rec = probe._hub_doc_record({
        "id": "hub-1",
        "file_name": "vendor_INV-99.pdf",
        "extracted_fields": {"invoice_number": "REF-2923600"},
        "normalized_fields": {"po_number": "PO-77777"},
        "email_subject": "Order 10713221 confirmation",
    })
    hay = rec["hub_ref_haystack"]
    assert "REF-2923600" in hay
    assert "PO-77777" in hay
    assert "10713221" in hay
    assert "INV-99" in hay


def test_reference_match_alone_does_not_create_content_match():
    """Reference weight is 0.10. Threshold is 0.85. A reference-only
    hit must not classify as ``content_match_found``."""
    idx = probe.build_hub_index_from_docs([{
        "id": "hub-x",
        "file_name": "ignore.pdf",
        "vendor_canonical": "Ball Metal",
        "extracted_fields": {"invoice_number": "BMC-2923600"},
    }])
    signals = {
        "invoice_number": None, "po_number": None,
        "amount": None, "invoice_date": None,
        "vendor_hint": None,
        "reference_numbers": ["2923600"],
    }
    score, doc, breakdown, _ = probe.score_signals_against_hub(signals, idx)
    assert doc is not None
    assert doc["hub_doc_id"] == "hub-x"
    assert score == pytest.approx(0.10, abs=1e-6)
    assert score < probe.CONTENT_MATCH_THRESHOLD
    assert breakdown.get("reference_number") == 1.0


def test_reference_lifts_a_near_match_above_threshold():
    """Body has invoice + amount + date that nearly match a Hub doc;
    reference number provides the final +0.10 needed."""
    idx = probe.build_hub_index_from_docs([{
        "id": "hub-near",
        "vendor_canonical": "Ball Metal Beverage Container",
        "invoice_number_clean": "6214787",
        "amount_float": "1500.00",
        "invoice_date": "2026-04-30",
        "file_name": "BallMetal_2923600_inv.pdf",
        "po_number_clean": "",
    }])
    signals = {
        "invoice_number": "6214787",
        "po_number": None,
        "amount": 1500.00,
        "invoice_date": "2026-04-30",
        "vendor_hint": None,
        "reference_numbers": ["2923600"],
    }
    score, doc, breakdown, _ = probe.score_signals_against_hub(signals, idx)
    assert doc["hub_doc_id"] == "hub-near"
    # invoice 0.55 + amount 0.20 + date 0.10 + reference 0.10 = 0.95
    assert score == pytest.approx(0.95, abs=1e-6)
    assert score >= probe.CONTENT_MATCH_THRESHOLD
    assert breakdown["reference_number"] == 1.0
    assert "2923600" in breakdown["_reference_numbers_matched"]


def test_reference_match_uses_digits_only_form():
    idx = probe.build_hub_index_from_docs([{
        "id": "hub-digits",
        "vendor_canonical": "X",
        "extracted_fields": {"invoice_number": "2923600"},
    }])
    # Body extracted it as 'REF-2923600'; Hub stored it as bare digits.
    signals = {
        "invoice_number": None, "po_number": None,
        "amount": None, "invoice_date": None,
        "vendor_hint": None,
        "reference_numbers": ["REF-2923600"],
    }
    score, doc, breakdown, _ = probe.score_signals_against_hub(signals, idx)
    assert doc is not None
    assert breakdown.get("reference_number") == 1.0
    assert score == pytest.approx(0.10, abs=1e-6)


@pytest.mark.parametrize("ref", [
    "2923600", "2931273", "10713221", "SI-02-26-32395",
])
def test_specific_production_references_match_against_haystack(ref: str):
    idx = probe.build_hub_index_from_docs([{
        "id": "hub-prod",
        "vendor_canonical": "X",
        "file_name": f"misc_{ref}_doc.pdf",
    }])
    signals = {
        "invoice_number": None, "po_number": None,
        "amount": None, "invoice_date": None,
        "vendor_hint": None,
        "reference_numbers": [ref],
    }
    score, doc, breakdown, _ = probe.score_signals_against_hub(signals, idx)
    assert doc is not None
    assert breakdown.get("reference_number") == 1.0


def test_short_reference_tokens_are_not_substring_matched():
    """A 3-char reference like 'ABC' must not blow up the haystack
    via accidental substring hits in unrelated docs."""
    idx = probe.build_hub_index_from_docs([{
        "id": "hub-noise", "vendor_canonical": "X",
        "file_name": "lots_of_text_ABC_in_random_place.pdf",
    }])
    signals = {
        "invoice_number": None, "po_number": None,
        "amount": None, "invoice_date": None,
        "vendor_hint": None,
        "reference_numbers": ["AB"],   # too short
    }
    score, doc, _, _ = probe.score_signals_against_hub(signals, idx)
    assert doc is None
    assert score == 0.0


def test_probe_csv_includes_reference_match_columns(tmp_path: Path):
    """Per-row CSV must surface ``reference_numbers_used`` and
    ``reference_match_score`` so operators can audit the new
    signal."""
    triage = [{
        "square9_name": "Ball_2923600.pdf",
        "square9_parent_path": "AP/Ball",
        "square9_web_url": "https://x/ball.pdf",
    }]

    class _Stub:
        last_diagnostic = {"failure_reason_detail": "ok",
                           "graph_url": "g", "http_status": 200,
                           "error_body_snippet": "", "exception_class": ""}

        def __call__(self, _row):
            return ("Reference: 2923600\nTotal: $1,500.00", probe.CONTENT_OK)

    idx = probe.build_hub_index_from_docs([{
        "id": "hub-prod",
        "vendor_canonical": "Ball",
        "file_name": "BallMetal_2923600.pdf",
        "amount_float": "1500.00",
    }])
    out = probe.probe(triage, extractor=_Stub(), idx=idx, limit=1)
    assert out[0]["reference_numbers_used"] == "2923600"
    assert out[0]["reference_match_score"] == "0.10"

    csv_path = tmp_path / "p.csv"
    probe.write_csv(str(csv_path), out)
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert "reference_numbers_used" in rows[0]
    assert "reference_match_score" in rows[0]
    assert rows[0]["reference_numbers_used"] == "2923600"


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



# ---------------------------------------------------------------------------
# Task A: content_match_invoice_only_below_threshold bucket
# Task B: non_invoice_attachment status flowing through classify()
# ---------------------------------------------------------------------------

def test_classify_routes_invoice_only_match_to_new_bucket():
    """Invoice agrees with a Hub doc, but other signals can't lift
    score across 0.85. Must route to
    ``content_match_invoice_only_below_threshold`` and recommend
    Hub-side metadata cleanup."""
    best_hub = {
        "hub_doc_id": "hub-hawkemedia",
        "hub_invoice_number_clean": "BILL-2026-04-84480",
        "hub_amount_float": "",            # blank — Hub-side gap
        "hub_vendor_canonical": "",        # blank — Hub-side gap
        "hub_invoice_date": "",
        "hub_po_number_clean": "",
    }
    bucket, reason = probe.classify(
        status=probe.CONTENT_OK,
        signals={"invoice_number": "BILL-2026-04-84480"},
        score=0.55,
        best_hub=best_hub,
        breakdown={"invoice_number": 1.0},
        vendor_known=True,
    )
    assert bucket == "content_match_invoice_only_below_threshold"
    assert "BILL-2026-04-84480" not in reason  # we surface hub_doc_id, not the raw value
    assert "hub-hawkemedia" in reason
    assert "hub_missing_fields" in reason
    assert "amount_float" in reason
    assert "vendor_canonical" in reason


def test_recommended_action_for_invoice_only_bucket_is_hub_metadata_cleanup():
    assert (probe.ACTION_FOR_BUCKET[
        "content_match_invoice_only_below_threshold"]
        == "improve_hub_metadata_for_this_doc")


def test_classify_keeps_content_match_found_above_threshold():
    """Invoice + amount + date + vendor sums above 0.85; the new
    bucket must NOT preempt content_match_found."""
    best_hub = {
        "hub_doc_id": "hub-strong",
        "hub_invoice_number_clean": "INV-12345",
        "hub_amount_float": "1500.00",
        "hub_vendor_canonical": "Acme Corp",
        "hub_invoice_date": "2026-04-15",
        "hub_po_number_clean": "PO-9999",
    }
    bucket, _ = probe.classify(
        status=probe.CONTENT_OK,
        signals={"invoice_number": "INV-12345"},
        score=0.95,
        best_hub=best_hub,
        breakdown={"invoice_number": 1.0, "amount": 1.0,
                   "invoice_date": 1.0, "vendor": 1.0},
        vendor_known=True,
    )
    assert bucket == "content_match_found"


def test_hub_missing_fields_lists_blank_keys_only():
    doc = {
        "hub_amount_float": "1500.00",
        "hub_vendor_canonical": "",
        "hub_invoice_date": "",
        "hub_po_number_clean": "PO-9999",
    }
    missing = probe.hub_missing_fields(doc)
    assert "vendor_canonical" in missing
    assert "invoice_date" in missing
    assert "amount_float" not in missing
    assert "po_number_clean" not in missing


def test_hub_missing_fields_handles_none():
    assert probe.hub_missing_fields(None) == []


def test_classify_routes_non_invoice_attachment_status_to_new_bucket():
    bucket, reason = probe.classify(
        status=probe.CONTENT_NON_INVOICE_ATTACHMENT,
        signals={"invoice_number": None},
        score=0.0, best_hub=None, breakdown={},
        vendor_known=True,
    )
    assert bucket == "non_invoice_attachment"
    assert "Office" in reason or "xlsx" in reason


def test_action_for_non_invoice_attachment_is_exclude_from_cohort():
    assert (probe.ACTION_FOR_BUCKET["non_invoice_attachment"]
            == "exclude_from_ap_cohort")


def test_bucket_order_includes_both_new_buckets():
    assert "content_match_invoice_only_below_threshold" in probe.BUCKET_ORDER
    assert "non_invoice_attachment" in probe.BUCKET_ORDER
    # Ordering: invoice_only sits right after content_match_found.
    order = list(probe.BUCKET_ORDER)
    assert (order.index("content_match_invoice_only_below_threshold")
            == order.index("content_match_found") + 1)


def test_probe_csv_emits_hub_missing_fields_for_invoice_only_row(
        tmp_path: Path):
    triage = [{
        "square9_name": "Hawkemedia.pdf",
        "square9_parent_path": "AP/Hawkemedia",
        "square9_web_url": "https://x/hawk.pdf",
    }]

    class _Stub:
        last_diagnostic = {"failure_reason_detail": "ok",
                           "graph_url": "g", "http_status": 200,
                           "error_body_snippet": "", "exception_class": ""}

        def __call__(self, _row):
            return ("Invoice BILL-2026-04-84480", probe.CONTENT_OK)

    idx = probe.build_hub_index_from_docs([{
        "id": "hub-hawk",
        "invoice_number_clean": "BILL-2026-04-84480",
        # Hub doc is otherwise empty — this is the data-quality
        # situation we want to flag to AP.
    }])
    out = probe.probe(triage, extractor=_Stub(), idx=idx, limit=1)
    assert out[0]["classification"] == \
        "content_match_invoice_only_below_threshold"
    assert out[0]["recommended_next_action"] == \
        "improve_hub_metadata_for_this_doc"
    assert "amount_float" in out[0]["hub_missing_fields"]
    assert "vendor_canonical" in out[0]["hub_missing_fields"]

    csv_path = tmp_path / "p.csv"
    probe.write_csv(str(csv_path), out)
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert "hub_missing_fields" in rows[0]
    assert "amount_float" in rows[0]["hub_missing_fields"]


def test_probe_routes_non_invoice_attachment_status_into_csv():
    triage = [{
        "square9_name": "tracking.xlsx",
        "square9_parent_path": "AP/Misc",
        "square9_web_url": "https://x/t.xlsx",
    }]

    class _Stub:
        last_diagnostic = {
            "failure_reason_detail": "non_invoice_attachment",
            "graph_url": "g", "http_status": 200,
            "error_body_snippet": "", "exception_class": ""}

        def __call__(self, _row):
            return ("", probe.CONTENT_NON_INVOICE_ATTACHMENT)

    idx = probe.build_hub_index_from_docs([])
    out = probe.probe(triage, extractor=_Stub(), idx=idx, limit=1)
    assert out[0]["content_access_status"] == "non_invoice_attachment"
    assert out[0]["classification"] == "non_invoice_attachment"
    assert out[0]["recommended_next_action"] == "exclude_from_ap_cohort"


def test_summary_md_includes_both_new_buckets(tmp_path: Path):
    triage = [
        {"square9_name": "hawk.pdf", "square9_parent_path": "",
         "square9_web_url": "https://x/h.pdf"},
        {"square9_name": "tracking.xlsx", "square9_parent_path": "",
         "square9_web_url": "https://x/t.xlsx"},
    ]
    responses = {
        "hawk.pdf": ("Invoice BILL-2026-04-84480", probe.CONTENT_OK),
        "tracking.xlsx": ("", probe.CONTENT_NON_INVOICE_ATTACHMENT),
    }

    class _Stub:
        last_diagnostic = {"failure_reason_detail": "ok",
                           "graph_url": "g", "http_status": 200,
                           "error_body_snippet": "", "exception_class": ""}

        def __call__(self, row):
            return responses[row["square9_name"]]

    idx = probe.build_hub_index_from_docs([{
        "id": "hub-hawk",
        "invoice_number_clean": "BILL-2026-04-84480",
    }])
    out = probe.probe(triage, extractor=_Stub(), idx=idx, limit=2)
    s = probe.build_summary(out, hub_doc_count=1, source_csv="x.csv")
    md = tmp_path / "summary.md"
    probe.write_md(str(md), s)
    text = md.read_text()
    assert "content_match_invoice_only_below_threshold" in text
    assert "non_invoice_attachment" in text
    assert "improve_hub_metadata_for_this_doc" in text
    assert "exclude_from_ap_cohort" in text
    # Engineering next steps should mention the Hub-cleanup guidance.
    steps = " ".join(s["recommended_engineering_next_steps"])
    assert "hub_missing_fields" in steps


# ---------------------------------------------------------------------------
# AP feedback loop: --rerun-rows-csv targeted rerun mode
# ---------------------------------------------------------------------------

def _write_rerun_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    cols = list(probe.RERUN_CSV_REQUIRED_COLUMNS)
    extra: List[str] = []
    for r in rows:
        for k in r.keys():
            if k not in cols and k not in extra:
                extra.append(k)
    fieldnames = cols + extra
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_read_rerun_rows_csv_returns_name_to_hub_doc_id_map(tmp_path: Path):
    p = tmp_path / "rerun.csv"
    _write_rerun_csv(p, [
        {"square9_name": "hawk.pdf", "hub_doc_id": "674926c1-d4d"},
        {"square9_name": "xpo.pdf", "hub_doc_id": "34a351ba-c1e"},
    ])
    out = probe.read_rerun_rows_csv(str(p))
    assert out == {"hawk.pdf": "674926c1-d4d", "xpo.pdf": "34a351ba-c1e"}


def test_read_rerun_rows_csv_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        probe.read_rerun_rows_csv(str(tmp_path / "does_not_exist.csv"))


def test_read_rerun_rows_csv_missing_required_columns_raises(tmp_path: Path):
    p = tmp_path / "rerun.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["square9_name"])
        w.writeheader()
        w.writerow({"square9_name": "hawk.pdf"})
    with pytest.raises(ValueError) as exc:
        probe.read_rerun_rows_csv(str(p))
    assert "hub_doc_id" in str(exc.value)


def test_read_rerun_rows_csv_empty_raises(tmp_path: Path):
    p = tmp_path / "rerun.csv"
    _write_rerun_csv(p, [])
    with pytest.raises(ValueError) as exc:
        probe.read_rerun_rows_csv(str(p))
    assert "no usable rows" in str(exc.value)


def test_read_rerun_rows_csv_skips_blank_square9_name(tmp_path: Path):
    p = tmp_path / "rerun.csv"
    _write_rerun_csv(p, [
        {"square9_name": "", "hub_doc_id": "ignored"},
        {"square9_name": "hawk.pdf", "hub_doc_id": "674926c1-d4d"},
    ])
    out = probe.read_rerun_rows_csv(str(p))
    assert out == {"hawk.pdf": "674926c1-d4d"}


def test_filter_to_rerun_subset_keeps_only_listed_rows():
    rows = [
        _triage_row(square9_name="a.pdf"),
        _triage_row(square9_name="b.pdf"),
        _triage_row(square9_name="c.pdf"),
    ]
    rerun_map = {"a.pdf": "hub-a", "c.pdf": "hub-c"}
    out = probe.filter_to_rerun_subset(rows, rerun_map)
    assert [r["square9_name"] for r in out] == ["a.pdf", "c.pdf"]


def test_score_signals_seeds_priority_hub_doc_into_candidates():
    """Without priority, an index-thin Hub doc is unreachable when the
    body's only matching signal is one that the index doesn't key
    on. With priority, the named doc is forced into the candidate set
    so the body signals can still score against it."""
    # Hub doc with vendor only — invoice/po/amount all blank, so
    # no normal index path can pull it as a candidate.
    idx = probe.build_hub_index_from_docs([
        _hub_doc(id="hub-priority",
                 invoice_number_clean="",
                 po_number_clean="",
                 amount_float="",
                 vendor_canonical="Hawkemedia",
                 invoice_date="2026-04-15"),
    ])
    # Body has an invoice + a date that align with hub-priority's
    # invoice_date and a vendor hint. Invoice number lookup misses (no
    # index entry), amount missing, PO missing, no refs.
    signals = {
        "invoice_number": "BILL-2026-04-84480",
        "po_number": None,
        "amount": None,
        "invoice_date": "2026-04-15",
        "vendor_hint": "Hawkemedia",
        "reference_numbers": [],
    }
    # Without priority: no candidate paths hit -> score 0, doc None.
    score_no, doc_no, _, _ = probe.score_signals_against_hub(signals, idx)
    assert doc_no is None
    assert score_no == 0.0
    # With priority: hub-priority is forced in. invoice_date + vendor
    # align -> non-zero score, doc returned.
    score_pri, doc_pri, breakdown_pri, _ = (
        probe.score_signals_against_hub(
            signals, idx, priority_hub_doc_id="hub-priority"))
    assert doc_pri is not None
    assert doc_pri["hub_doc_id"] == "hub-priority"
    assert score_pri > 0
    assert breakdown_pri.get("invoice_date") == 1.0
    assert breakdown_pri.get("vendor") == 1.0


def test_probe_threads_priority_hub_doc_id_per_row_into_scoring():
    """End-to-end: when probe() is called with a per-row priority map,
    each row scores against the named Hub doc."""
    triage = [_triage_row(square9_name="hawk.pdf")]

    class _Stub:
        last_diagnostic = {"failure_reason_detail": "ok",
                           "graph_url": "g", "http_status": 200,
                           "error_body_snippet": "", "exception_class": ""}

        def __call__(self, _row):
            # Body has invoice, amount, date — Hub-side has the same
            # but only because we seeded the right doc.
            return ("Hawkemedia\nInvoice BILL-2026-04-84480\n"
                    "Date: 04/15/2026\nTotal: $1,500.00",
                    probe.CONTENT_OK)

    idx = probe.build_hub_index_from_docs([
        _hub_doc(id="hub-priority",
                 invoice_number_clean="BILL-2026-04-84480",
                 amount_float="1500.00",
                 vendor_canonical="Hawkemedia",
                 invoice_date="2026-04-15"),
    ])
    out = probe.probe(triage, extractor=_Stub(), idx=idx, limit=1,
                      priority_hub_doc_id_by_row={"hawk.pdf": "hub-priority"})
    assert out[0]["best_hub_doc_id"] == "hub-priority"
    assert out[0]["classification"] == "content_match_found"


def _make_rerun_main_environ(tmp_path: Path,
                             monkeypatch: pytest.MonkeyPatch
                             ) -> Dict[str, Path]:
    """Set up a minimal triage CSV + mongomock collection + paths for
    main() invocation tests below."""
    import mongomock
    triage_csv = tmp_path / "uncertain_square9_deep_triage.csv"
    fields = list(_triage_row().keys())
    with open(triage_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow(_triage_row(square9_name="hawk.pdf"))
        w.writerow(_triage_row(square9_name="xpo.pdf"))
        w.writerow(_triage_row(square9_name="other.pdf"))

    coll = mongomock.MongoClient().db.hub_documents
    coll.insert_one(_hub_doc(id="hub-hawk",
                             invoice_number_clean="BILL-2026-04-84480",
                             amount_float="1500.00",
                             vendor_canonical="Hawkemedia",
                             invoice_date="2026-04-15"))
    coll.insert_one(_hub_doc(id="hub-xpo",
                             invoice_number_clean="104-570966",
                             amount_float="250.00",
                             vendor_canonical="XPO Logistics",
                             invoice_date="2026-04-10"))
    monkeypatch.setattr(
        "scripts.document_body_reconciliation_probe.get_hub_documents_collection",
        lambda: coll,
    )
    return {
        "triage_csv": triage_csv,
        "out_csv": tmp_path / "out.csv",
        "json_out": tmp_path / "out.json",
        "md_out": tmp_path / "out.md",
    }


def test_main_rerun_mode_filters_to_subset_and_uses_priority_hub_doc(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """End-to-end main() smoke: --rerun-rows-csv loads only the listed
    rows and re-scores against the named Hub docs."""
    paths = _make_rerun_main_environ(tmp_path, monkeypatch)
    rerun_csv = tmp_path / "rerun.csv"
    _write_rerun_csv(rerun_csv, [
        {"square9_name": "hawk.pdf", "hub_doc_id": "hub-hawk"},
        {"square9_name": "xpo.pdf", "hub_doc_id": "hub-xpo"},
    ])

    body_by_name = {
        "hawk.pdf": (
            "Hawkemedia\nInvoice BILL-2026-04-84480\n"
            "Date: 04/15/2026\nTotal: $1,500.00",
            probe.CONTENT_OK,
        ),
        "xpo.pdf": (
            "XPO Logistics\nInvoice 104-570966\n"
            "Date: 04/10/2026\nTotal: $250.00",
            probe.CONTENT_OK,
        ),
    }
    extractor = _make_extractor(body_by_name)

    monkeypatch.setattr("sys.argv", [
        "document_body_reconciliation_probe.py",
        "--triage-csv", str(paths["triage_csv"]),
        "--rerun-rows-csv", str(rerun_csv),
        "--out-csv", str(paths["out_csv"]),
        "--json", str(paths["json_out"]),
        "--md", str(paths["md_out"]),
    ])
    rc = probe.main(extractor=extractor)
    assert rc == 0
    payload = json.loads(paths["json_out"].read_text())
    # Only the 2 rerun rows were scored — 'other.pdf' must be absent.
    assert payload["total_attempted"] == 2
    assert payload["content_match_found"] == 2
    with open(paths["out_csv"], encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    names = sorted(r["square9_name"] for r in rows)
    assert names == ["hawk.pdf", "xpo.pdf"]
    by_name = {r["square9_name"]: r for r in rows}
    assert by_name["hawk.pdf"]["best_hub_doc_id"] == "hub-hawk"
    assert by_name["xpo.pdf"]["best_hub_doc_id"] == "hub-xpo"


def test_main_rerun_mode_missing_csv_returns_nonzero(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]):
    paths = _make_rerun_main_environ(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.argv", [
        "document_body_reconciliation_probe.py",
        "--triage-csv", str(paths["triage_csv"]),
        "--rerun-rows-csv", str(tmp_path / "missing.csv"),
        "--use-noop-fetcher",
        "--out-csv", str(paths["out_csv"]),
        "--json", str(paths["json_out"]),
        "--md", str(paths["md_out"]),
    ])
    rc = probe.main(extractor=None)
    assert rc != 0
    err = capsys.readouterr().err
    assert "rerun-rows-csv" in err
    assert "not found" in err.lower()


def test_main_rerun_mode_empty_csv_returns_nonzero(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]):
    paths = _make_rerun_main_environ(tmp_path, monkeypatch)
    rerun_csv = tmp_path / "rerun.csv"
    _write_rerun_csv(rerun_csv, [])
    monkeypatch.setattr("sys.argv", [
        "document_body_reconciliation_probe.py",
        "--triage-csv", str(paths["triage_csv"]),
        "--rerun-rows-csv", str(rerun_csv),
        "--use-noop-fetcher",
        "--out-csv", str(paths["out_csv"]),
        "--json", str(paths["json_out"]),
        "--md", str(paths["md_out"]),
    ])
    rc = probe.main(extractor=None)
    assert rc != 0
    err = capsys.readouterr().err
    assert "no usable rows" in err.lower() or "empty" in err.lower()


def test_main_rerun_mode_no_overlap_with_triage_returns_nonzero(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]):
    """If the rerun CSV lists square9_names that don't appear in the
    triage CSV, main() must refuse with a clear message rather than
    write empty outputs."""
    paths = _make_rerun_main_environ(tmp_path, monkeypatch)
    rerun_csv = tmp_path / "rerun.csv"
    _write_rerun_csv(rerun_csv, [
        {"square9_name": "ghost-row.pdf", "hub_doc_id": "nope"},
    ])
    monkeypatch.setattr("sys.argv", [
        "document_body_reconciliation_probe.py",
        "--triage-csv", str(paths["triage_csv"]),
        "--rerun-rows-csv", str(rerun_csv),
        "--use-noop-fetcher",
        "--out-csv", str(paths["out_csv"]),
        "--json", str(paths["json_out"]),
        "--md", str(paths["md_out"]),
    ])
    rc = probe.main(extractor=None)
    assert rc != 0
    err = capsys.readouterr().err
    assert "matched 0 rows" in err
