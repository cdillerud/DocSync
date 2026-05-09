"""
build_ap_smoke_test_set.py
==========================
READ-ONLY curator that assembles an internal IT/Engineering AP
smoke-test document set for GPI Hub.

Goal
----
Before AP testers ever see the system, IT needs a controlled, hand-curated
list of documents that exercise the core Hub AP workflow (clean invoices,
field accuracy, exceptions, OCR, non-invoice attachments, permission
edges, duplicates, misclassifications). This script does not change
anything; it reads ``hub_documents`` and the most recent body-
reconciliation probe CSV, picks a small number of representative
examples per category, and writes:

- ``prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv``
- ``prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.md``

Strict guarantees
-----------------
- No Mongo writes.
- No routing / classifier / matcher changes.
- No Square9 / DocuSign / HTTPS / cutover work.
- Pinned set of categories; the script emits a "missing categories"
  list when no real document satisfies a category.
- Two rows are pinned by ``hub_doc_id`` for the metadata-cleanup
  category so the smoke set always carries the Hawkemedia + XPO
  examples discussed in
  ``prod_reports/INTERNAL_AP_REVIEW_METADATA_VALIDATION.md``.

CLI
---
- ``--probe-csv PATH`` Path to the probe CSV (default
  ``prod_reports/document_body_reconciliation_probe_limit100_final.csv``;
  falls back to ``prod_reports/document_body_reconciliation_probe.csv``
  if the limit100 file is absent). Optional — if neither file exists
  the OCR / non-invoice-attachment / permission-edge categories are
  marked "missing" rather than synthesized.
- ``--per-category N`` Cap per category (default 2).
- ``--out-csv`` / ``--out-md`` Override output paths.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import OrderedDict, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple


# Bootstrap path so this can be invoked as
# ``python scripts/build_ap_smoke_test_set.py`` OR
# ``python -m scripts.build_ap_smoke_test_set``.
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CATEGORIES = [
    "clean_ap_invoice",
    "ap_invoice_vendor_populated",
    "ap_invoice_invoice_number_populated",
    "ap_invoice_amount_populated",
    "ap_invoice_po_populated",
    "needs_review_or_exception",
    "non_invoice_attachment",
    "ocr_required",
    "metadata_cleanup_example",
    "sharepoint_permission_edge",
    "duplicate_or_possible_duplicate",
    "misclassified_or_corrected",
]

# Pinned by hub_doc_id (from
# prod_reports/INTERNAL_AP_REVIEW_METADATA_VALIDATION.md). These two
# always go into the metadata_cleanup_example category so the smoke
# set is reproducible across runs.
PINNED_METADATA_CLEANUP = [
    {
        "hub_doc_id": "674926c1-d4da-42aa-897b-59cd4867c15f",
        "vendor_label": "Hawkemedia",
        "invoice_label": "BILL-2026-04-84480",
        "expected_missing": "amount_float, vendor_canonical, po_number_clean",
    },
    {
        "hub_doc_id": "34a351ba-c1e2-4cd2-aac8-c6fa535fa352",
        "vendor_label": "XPO Logistics",
        "invoice_label": "104-570966",
        "expected_missing": "invoice_date",
    },
]

DEFAULT_PROBE_CSV_CANDIDATES = (
    "prod_reports/document_body_reconciliation_probe_limit100_final.csv",
    "prod_reports/document_body_reconciliation_probe.csv",
)

OUTPUT_COLUMNS = [
    "test_doc_category", "priority", "hub_doc_id", "hub_document_url",
    "file_name", "vendor_canonical", "invoice_number_clean",
    "invoice_date", "amount_float", "po_number_clean",
    "mailbox_category", "doc_type", "suggested_job_type",
    "routing_status", "routing_reason", "sharepoint_folder_path",
    "why_this_doc_is_in_the_test_set",
    "what_tester_should_check",
    "expected_result",
    "notes",
]

CATEGORY_PRIORITY = {
    "clean_ap_invoice": "P1",
    "ap_invoice_vendor_populated": "P1",
    "ap_invoice_invoice_number_populated": "P1",
    "ap_invoice_amount_populated": "P1",
    "ap_invoice_po_populated": "P2",
    "needs_review_or_exception": "P1",
    "non_invoice_attachment": "P2",
    "ocr_required": "P2",
    "metadata_cleanup_example": "P0",
    "sharepoint_permission_edge": "P2",
    "duplicate_or_possible_duplicate": "P1",
    "misclassified_or_corrected": "P1",
}

CATEGORY_GUIDANCE = {
    "clean_ap_invoice":
        ("Open the doc. Read each AP Review field. Confirm vendor, "
         "invoice number, invoice date, total amount, and PO match "
         "the document body without any edit needed.",
         "All five core fields populated and correct; no exception."),
    "ap_invoice_vendor_populated":
        ("Confirm vendor_canonical is populated and matches the BC "
         "vendor implied by the document body.",
         "Vendor field non-empty and correctly resolved."),
    "ap_invoice_invoice_number_populated":
        ("Confirm invoice_number_clean is populated and matches the "
         "invoice number printed on the document.",
         "Invoice number field non-empty and accurate."),
    "ap_invoice_amount_populated":
        ("Confirm amount_float is populated and matches the printed "
         "total / amount due.",
         "Amount field non-empty and accurate to the cent."),
    "ap_invoice_po_populated":
        ("Confirm po_number_clean is populated when the invoice "
         "carries a PO; otherwise the field should be blank.",
         "PO field correctly populated OR correctly blank."),
    "needs_review_or_exception":
        ("Open the doc. Read the workflow_status and any blocker / "
         "validation_errors. Confirm the reason is plausible.",
         "Reviewer can articulate why the doc is held up."),
    "non_invoice_attachment":
        ("Open the doc. Confirm it is NOT a real invoice (tracking "
         "sheet, statement, packing slip, etc.).",
         "Reviewer agrees this should be excluded from the AP cohort."),
    "ocr_required":
        ("Open the doc. Confirm the PDF is scanned / image-only and "
         "extracted_fields are empty or sparse.",
         "Reviewer agrees OCR is needed before auto-extraction can "
         "fire."),
    "metadata_cleanup_example":
        ("Open the doc. Note the missing Hub fields. Use the AP "
         "Review panel to fill them in. Save and reload.",
         "Edits persist; status may advance per workflow rules."),
    "sharepoint_permission_edge":
        ("Try to open the SharePoint preview / link. Confirm whether "
         "Hub UI degrades gracefully when access is denied or item "
         "is missing.",
         "UI handles permission failures without crashing the page."),
    "duplicate_or_possible_duplicate":
        ("Open the doc. Confirm the duplicate flag is plausible — "
         "is there really another document in the Hub that matches "
         "vendor + invoice number?",
         "Duplicate flag is correct (true positive) OR clearly a "
         "false positive worth logging."),
    "misclassified_or_corrected":
        ("Open the doc. Confirm the document_type is correct after "
         "any prior classification correction.",
         "Type is now correct AND the classification_override audit "
         "subdoc is present."),
}

CATEGORY_HEADLINES = {
    "clean_ap_invoice": "Reference: a clean, all-fields-populated AP invoice.",
    "ap_invoice_vendor_populated": "Field accuracy: vendor extracted correctly.",
    "ap_invoice_invoice_number_populated": "Field accuracy: invoice number extracted correctly.",
    "ap_invoice_amount_populated": "Field accuracy: amount extracted correctly.",
    "ap_invoice_po_populated": "Field accuracy: PO extracted correctly when present.",
    "needs_review_or_exception": "Workflow: an exception/review document the user must read.",
    "non_invoice_attachment": "Cohort hygiene: a non-invoice attachment we should exclude upstream.",
    "ocr_required": "Coverage gap: scanned PDF awaiting OCR pipeline.",
    "metadata_cleanup_example": "Remediation: pinned cleanup row from the internal validation memo.",
    "sharepoint_permission_edge": "Edge case: SharePoint access denied / missing.",
    "duplicate_or_possible_duplicate": "Risk: duplicate detection — true positive or false positive.",
    "misclassified_or_corrected": "Risk: classification correction history.",
}


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def _read_probe_csv(path: str) -> List[Dict[str, str]]:
    """Read a body-reconciliation probe CSV. Returns [] on missing file."""
    if not path or not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _resolve_probe_csv(arg_path: Optional[str]) -> Tuple[str, List[Dict[str, str]]]:
    """Pick the probe CSV to use. Try arg, then defaults. Return (path,
    rows). Path is empty string if nothing found."""
    if arg_path:
        return arg_path, _read_probe_csv(arg_path)
    for candidate in DEFAULT_PROBE_CSV_CANDIDATES:
        if os.path.exists(candidate):
            return candidate, _read_probe_csv(candidate)
    return "", []


def get_hub_documents_collection():
    from pymongo import MongoClient  # noqa: WPS433
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise RuntimeError("MONGO_URL / DB_NAME env vars are required.")
    return MongoClient(mongo_url)[db_name]["hub_documents"]


# ---------------------------------------------------------------------------
# Document projection
# ---------------------------------------------------------------------------

PROJECTION = {
    "_id": 0,
    "id": 1, "file_name": 1, "vendor_canonical": 1,
    "invoice_number_clean": 1, "po_number_clean": 1,
    "amount_float": 1, "invoice_date": 1, "due_date": 1,
    "mailbox_category": 1, "doc_type": 1, "suggested_job_type": 1,
    "document_type": 1, "workflow_status": 1, "routing_status": 1,
    "routing_reason": 1, "sharepoint_folder_path": 1,
    "sharepoint_web_url": 1, "sharepoint_url": 1,
    "is_duplicate": 1, "possible_duplicate": 1,
    "duplicate_of": 1, "validation_errors": 1,
    "classification_override": 1, "extracted_fields": 1,
    "normalized_fields": 1, "created_utc": 1, "updated_utc": 1,
    "vendor_id": 1,
}


def _doc_url(doc: Dict[str, Any], hub_base_url: str) -> str:
    base = (hub_base_url or "").rstrip("/")
    doc_id = doc.get("id") or ""
    if not doc_id:
        return ""
    if base:
        return f"{base}/documents/{doc_id}"
    # Fallback: relative path; operator can paste into their Hub URL.
    return f"/documents/{doc_id}"


def _shape_row(doc: Dict[str, Any], category: str,
               *, why: str, check: str, expected: str,
               notes: str, hub_base_url: str) -> Dict[str, str]:
    return {
        "test_doc_category": category,
        "priority": CATEGORY_PRIORITY.get(category, "P2"),
        "hub_doc_id": str(doc.get("id") or ""),
        "hub_document_url": _doc_url(doc, hub_base_url),
        "file_name": str(doc.get("file_name") or ""),
        "vendor_canonical": str(doc.get("vendor_canonical") or ""),
        "invoice_number_clean": str(doc.get("invoice_number_clean") or ""),
        "invoice_date": str(doc.get("invoice_date") or ""),
        "amount_float": "" if doc.get("amount_float") is None
                        else str(doc.get("amount_float")),
        "po_number_clean": str(doc.get("po_number_clean") or ""),
        "mailbox_category": str(doc.get("mailbox_category") or ""),
        "doc_type": str(doc.get("doc_type") or doc.get("document_type") or ""),
        "suggested_job_type": str(doc.get("suggested_job_type") or ""),
        "routing_status": str(doc.get("routing_status") or ""),
        "routing_reason": str(doc.get("routing_reason") or ""),
        "sharepoint_folder_path": str(doc.get("sharepoint_folder_path") or ""),
        "why_this_doc_is_in_the_test_set": why,
        "what_tester_should_check": check,
        "expected_result": expected,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Category curators
# ---------------------------------------------------------------------------

def _is_ap(doc: Dict[str, Any]) -> bool:
    return (
        (doc.get("mailbox_category") or "").upper() == "AP"
        or (doc.get("doc_type") or "").upper() == "AP_INVOICE"
        or (doc.get("document_type") or "") == "AP_Invoice"
        or (doc.get("suggested_job_type") or "") == "AP_Invoice"
    )


def _amount_present(doc: Dict[str, Any]) -> bool:
    a = doc.get("amount_float")
    try:
        return a is not None and float(a) > 0
    except (TypeError, ValueError):
        return False


def _is_clean(doc: Dict[str, Any]) -> bool:
    return (
        _is_ap(doc)
        and bool(doc.get("vendor_canonical"))
        and bool(doc.get("invoice_number_clean"))
        and _amount_present(doc)
        and bool(doc.get("invoice_date"))
        and not doc.get("validation_errors")
        and (doc.get("workflow_status") or "") not in (
            "vendor_pending", "data_correction_pending",
            "bc_validation_failed", "review_pending",
        )
    )


def _is_exception(doc: Dict[str, Any]) -> bool:
    if doc.get("validation_errors"):
        return True
    return (doc.get("workflow_status") or "") in (
        "vendor_pending", "data_correction_pending",
        "bc_validation_failed", "review_pending",
    )


def _is_duplicate_candidate(doc: Dict[str, Any]) -> bool:
    return bool(doc.get("is_duplicate") or doc.get("possible_duplicate")
                or doc.get("duplicate_of"))


def _is_misclassified_or_corrected(doc: Dict[str, Any]) -> bool:
    return bool(doc.get("classification_override"))


def _curate_clean(docs: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    return [d for d in docs if _is_clean(d)][:n]


def _curate_field_populated(docs: List[Dict[str, Any]],
                            field: str, n: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for d in docs:
        if not _is_ap(d):
            continue
        v = d.get(field)
        if field == "amount_float":
            if not _amount_present(d):
                continue
        elif not v:
            continue
        out.append(d)
        if len(out) >= n:
            break
    return out


def _curate_exception(docs: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    return [d for d in docs if _is_ap(d) and _is_exception(d)][:n]


def _curate_duplicate(docs: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    return [d for d in docs if _is_duplicate_candidate(d)][:n]


def _curate_misclassified(docs: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    return [d for d in docs if _is_misclassified_or_corrected(d)][:n]


def _hub_ids_from_probe(probe_rows: List[Dict[str, str]],
                       classification: str,
                       *, status_filter: Optional[Iterable[str]] = None,
                       failure_filter: Optional[Iterable[str]] = None,
                       n: int) -> List[str]:
    out: List[str] = []
    for r in probe_rows:
        if r.get("classification") != classification:
            continue
        if status_filter is not None:
            if (r.get("content_access_status") or "") not in status_filter:
                continue
        if failure_filter is not None:
            if (r.get("failure_reason_detail") or "") not in failure_filter:
                continue
        hid = (r.get("best_hub_doc_id") or "").strip()
        if hid:
            out.append(hid)
            if len(out) >= n:
                break
    return out


# ---------------------------------------------------------------------------
# Curator entry point
# ---------------------------------------------------------------------------

def curate(*, hub_docs: List[Dict[str, Any]],
           probe_rows: List[Dict[str, str]],
           per_category: int = 2,
           hub_base_url: str = "",
           ) -> Tuple[List[Dict[str, str]], List[str]]:
    """Build the smoke-test rows. Returns (rows, missing_categories)."""
    by_id: Dict[str, Dict[str, Any]] = {
        str(d.get("id") or ""): d for d in hub_docs if d.get("id")
    }

    rows: List[Dict[str, str]] = []
    seen_pairs: set = set()  # (category, hub_doc_id) — avoid dup rows in same cat
    missing: List[str] = []

    def _emit(category: str, doc: Dict[str, Any], why: str,
              check: str, expected: str, notes: str = "") -> None:
        key = (category, str(doc.get("id") or ""))
        if key in seen_pairs:
            return
        seen_pairs.add(key)
        rows.append(_shape_row(
            doc, category,
            why=why, check=check, expected=expected, notes=notes,
            hub_base_url=hub_base_url,
        ))

    # 1. Clean AP invoice
    for d in _curate_clean(hub_docs, per_category):
        _emit("clean_ap_invoice", d,
              "All five core fields populated; no exception.",
              CATEGORY_GUIDANCE["clean_ap_invoice"][0],
              CATEGORY_GUIDANCE["clean_ap_invoice"][1])
    if not any(r["test_doc_category"] == "clean_ap_invoice" for r in rows):
        missing.append("clean_ap_invoice")

    # 2-5. Field-populated examples (vendor / invoice# / amount / po)
    for cat, field in (
        ("ap_invoice_vendor_populated", "vendor_canonical"),
        ("ap_invoice_invoice_number_populated", "invoice_number_clean"),
        ("ap_invoice_amount_populated", "amount_float"),
        ("ap_invoice_po_populated", "po_number_clean"),
    ):
        picks = _curate_field_populated(hub_docs, field, per_category)
        for d in picks:
            _emit(cat, d,
                  f"AP invoice with `{field}` populated.",
                  CATEGORY_GUIDANCE[cat][0],
                  CATEGORY_GUIDANCE[cat][1])
        if not picks:
            missing.append(cat)

    # 6. Needs Review / exception
    for d in _curate_exception(hub_docs, per_category):
        why = "Doc carries validation_errors or sits in a review/correction status."
        _emit("needs_review_or_exception", d,
              why,
              CATEGORY_GUIDANCE["needs_review_or_exception"][0],
              CATEGORY_GUIDANCE["needs_review_or_exception"][1])
    if not any(r["test_doc_category"] == "needs_review_or_exception" for r in rows):
        missing.append("needs_review_or_exception")

    # 7. Non-invoice attachment (from probe)
    nia_ids = _hub_ids_from_probe(probe_rows, "non_invoice_attachment",
                                  n=per_category)
    for hid in nia_ids:
        d = by_id.get(hid)
        if d:
            _emit("non_invoice_attachment", d,
                  "Probe classified body as non_invoice_attachment "
                  "(xlsx/xls/docx/OOXML).",
                  CATEGORY_GUIDANCE["non_invoice_attachment"][0],
                  CATEGORY_GUIDANCE["non_invoice_attachment"][1],
                  notes="internal_only=Y")
    if not any(r["test_doc_category"] == "non_invoice_attachment" for r in rows):
        missing.append("non_invoice_attachment")

    # 8. OCR required (from probe)
    ocr_ids = _hub_ids_from_probe(probe_rows, "ocr_required", n=per_category)
    for hid in ocr_ids:
        d = by_id.get(hid)
        if d:
            _emit("ocr_required", d,
                  "Probe classified body as ocr_required (PDF without "
                  "extractable text).",
                  CATEGORY_GUIDANCE["ocr_required"][0],
                  CATEGORY_GUIDANCE["ocr_required"][1],
                  notes="internal_only=Y; OCR pipeline is a P1 backlog item")
    if not any(r["test_doc_category"] == "ocr_required" for r in rows):
        missing.append("ocr_required")

    # 9. Pinned metadata-cleanup examples (Hawkemedia, XPO)
    for pinned in PINNED_METADATA_CLEANUP:
        hid = pinned["hub_doc_id"]
        d = by_id.get(hid) or {"id": hid, "file_name": "",
                               "vendor_canonical": "",
                               "invoice_number_clean": pinned["invoice_label"]}
        notes = (f"pinned_example=Y; vendor_label={pinned['vendor_label']}; "
                 f"expected_missing=[{pinned['expected_missing']}]; "
                 f"see prod_reports/INTERNAL_AP_REVIEW_METADATA_VALIDATION.md")
        _emit("metadata_cleanup_example", d,
              "Pinned from the internal validation memo — invoice "
              "number agrees with a Hub doc on body match but "
              "Hub-side metadata is too thin to clear the matcher "
              "threshold. Use the AP Review panel to fill the "
              "missing fields.",
              CATEGORY_GUIDANCE["metadata_cleanup_example"][0],
              CATEGORY_GUIDANCE["metadata_cleanup_example"][1],
              notes=notes)
    # Always present (pinned), so no missing entry.

    # 10. SharePoint permission/access edge (from probe http_403/http_404)
    perm_ids = _hub_ids_from_probe(
        probe_rows, "insufficient_content_access",
        failure_filter={"http_403", "http_404", "graph_resolve_failed"},
        n=per_category,
    )
    for hid in perm_ids:
        d = by_id.get(hid)
        if d:
            _emit("sharepoint_permission_edge", d,
                  "Probe could not fetch the document body — Graph "
                  "returned 403/404 or URL did not resolve.",
                  CATEGORY_GUIDANCE["sharepoint_permission_edge"][0],
                  CATEGORY_GUIDANCE["sharepoint_permission_edge"][1],
                  notes="internal_only=Y; do not surface to AP yet")
    if not any(r["test_doc_category"] == "sharepoint_permission_edge" for r in rows):
        missing.append("sharepoint_permission_edge")

    # 11. Duplicate / possible duplicate
    for d in _curate_duplicate(hub_docs, per_category):
        _emit("duplicate_or_possible_duplicate", d,
              "Hub flagged this doc as duplicate or possible "
              "duplicate.",
              CATEGORY_GUIDANCE["duplicate_or_possible_duplicate"][0],
              CATEGORY_GUIDANCE["duplicate_or_possible_duplicate"][1])
    if not any(
            r["test_doc_category"] == "duplicate_or_possible_duplicate"
            for r in rows):
        missing.append("duplicate_or_possible_duplicate")

    # 12. Misclassified / historically corrected
    for d in _curate_misclassified(hub_docs, per_category):
        _emit("misclassified_or_corrected", d,
              "Doc carries a classification_override audit subdoc — "
              "type was previously corrected.",
              CATEGORY_GUIDANCE["misclassified_or_corrected"][0],
              CATEGORY_GUIDANCE["misclassified_or_corrected"][1])
    if not any(
            r["test_doc_category"] == "misclassified_or_corrected"
            for r in rows):
        missing.append("misclassified_or_corrected")

    return rows, missing


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_csv(path: str, rows: List[Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS,
                           extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _group_by_category(rows: List[Dict[str, str]]
                       ) -> "OrderedDict[str, List[Dict[str, str]]]":
    grouped: "OrderedDict[str, List[Dict[str, str]]]" = OrderedDict()
    for c in CATEGORIES:
        grouped[c] = []
    for r in rows:
        c = r.get("test_doc_category") or ""
        grouped.setdefault(c, []).append(r)
    return grouped


def write_md(path: str, rows: List[Dict[str, str]],
             missing: List[str], probe_csv_path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    grouped = _group_by_category(rows)
    counts: Dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r.get("test_doc_category", "")] += 1

    lines: List[str] = []
    lines.append("# AP Internal Smoke-Test Document Set")
    lines.append("")
    lines.append("> **INTERNAL — IT / Engineering only.** Accounting "
                 "has not been engaged. Do not send this to AP.")
    lines.append("")
    lines.append("## 1. Purpose")
    lines.append("")
    lines.append(
        "This is a curated, controlled list of GPI Hub documents "
        "that exercise the core AP workflow before any AP user is "
        "invited to test. Each row points at a real Hub document and "
        "names exactly what the IT/Eng tester should check on it. "
        "It is the smoke set, not the AP UAT list.")
    lines.append("")

    lines.append("## 2. How to use this list")
    lines.append("")
    lines.append("- One IT/Eng tester walks the rows in priority "
                 "order (P0 → P1 → P2).")
    lines.append("- Open each row's `hub_document_url` in the Hub.")
    lines.append("- Read `what_tester_should_check`. Compare to "
                 "`expected_result`. Note any deviation.")
    lines.append("- Do **not** post any of these documents to BC. "
                 "Do **not** mark anything ready for posting unless "
                 "you specifically intend to test the post pipeline "
                 "on this run.")
    lines.append("- Findings stay internal. Do not screenshot rows "
                 "marked `internal_only=Y` for any external audience.")
    lines.append("")
    lines.append(f"- Source probe CSV: `{probe_csv_path or '(not present — OCR/non-invoice/permission categories may be incomplete)'}`.")
    lines.append("- Total rows: **" + str(len(rows)) + "**.")
    lines.append("")

    lines.append("## 3. Test document table grouped by category")
    lines.append("")
    for cat in CATEGORIES:
        cat_rows = grouped.get(cat, [])
        lines.append(f"### {cat} — {CATEGORY_HEADLINES.get(cat, '')}")
        lines.append("")
        lines.append(f"_Priority: {CATEGORY_PRIORITY.get(cat, 'P2')} · "
                     f"Rows: {len(cat_rows)}_")
        lines.append("")
        if not cat_rows:
            lines.append("_No real document satisfied this category in the "
                         "current corpus. Listed under Missing categories "
                         "below — IT to backfill before the AP UAT list._")
            lines.append("")
            continue
        lines.append("| hub_doc_id | file_name | vendor | invoice# | amount | status | notes |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for r in cat_rows:
            lines.append(
                f"| `{r.get('hub_doc_id','')}` "
                f"| {r.get('file_name','')} "
                f"| {r.get('vendor_canonical','')} "
                f"| {r.get('invoice_number_clean','')} "
                f"| {r.get('amount_float','')} "
                f"| {r.get('routing_status') or r.get('doc_type','')} "
                f"| {r.get('notes','')} |"
            )
        lines.append("")
        for r in cat_rows:
            lines.append(f"- **{r.get('hub_doc_id','')}** — "
                         f"why: {r.get('why_this_doc_is_in_the_test_set','')}")
            lines.append(f"  - check: {r.get('what_tester_should_check','')}")
            lines.append(f"  - expected: {r.get('expected_result','')}")
            if r.get("hub_document_url"):
                lines.append(f"  - link: `{r.get('hub_document_url','')}`")
        lines.append("")

    lines.append("## 4. What IT should verify before AP sees the system")
    lines.append("")
    lines.append("- Every P0 row (`metadata_cleanup_example`) opens, "
                 "the AP Review panel renders, fields can be edited, "
                 "Save persists, and reload shows the corrected "
                 "value.")
    lines.append("- Every P1 row opens cleanly. The five core fields "
                 "(vendor / invoice# / date / amount / PO) match the "
                 "invoice body or are correctly blank.")
    lines.append("- The Needs-Review / exception row clearly tells "
                 "the tester *why* the doc is held up.")
    lines.append("- The duplicate row's flag is plausible (true "
                 "duplicate or clearly a false positive worth "
                 "logging).")
    lines.append("- The misclassified-history row's "
                 "`classification_override` audit subdoc is intact "
                 "and the doc now reads as the corrected type.")
    lines.append("- The SharePoint permission edge row's UI does not "
                 "crash when the body cannot be fetched; it degrades "
                 "to a clear error state.")
    lines.append("")

    lines.append("## 5. Known limitations")
    lines.append("")
    lines.append("- This list is generated read-only from the live "
                 "`hub_documents` collection plus the most recent "
                 "body-reconciliation probe CSV. If the probe has "
                 "not been run recently, the OCR / non-invoice / "
                 "permission-edge categories may be empty.")
    lines.append("- The `metadata_cleanup_example` rows are pinned by "
                 "`hub_doc_id` from the internal validation memo. "
                 "They will appear even if the live Hub no longer "
                 "has those documents, so IT can spot drift.")
    lines.append("- No document on this list has been touched. The "
                 "smoke test is read-only by design.")
    lines.append("")
    if missing:
        lines.append("### Missing categories in this run")
        lines.append("")
        for c in missing:
            lines.append(f"- `{c}`")
        lines.append("")
        lines.append(
            "_Action: rerun once the corpus has a real example, or "
            "manually add a row to the CSV before promoting to the "
            "AP UAT list._")
        lines.append("")

    lines.append("## 6. Do not send to AP yet")
    lines.append("")
    lines.append("- This is the IT smoke set. The AP UAT package "
                 "(`memory/GPI_HUB_AP_USER_ACCEPTANCE_TEST_PLAN_DRAFT.md` "
                 "+ feedback CSV + kickoff notes) is a separate, "
                 "still-internal draft.")
    lines.append("- Do not paste rows from this list into AP-facing "
                 "communications. Some rows carry `internal_only=Y` "
                 "in the notes column.")
    lines.append("- The two pinned `metadata_cleanup_example` rows "
                 "(Hawkemedia, XPO) reference real Hub docs whose "
                 "metadata has not yet been corrected. Do not "
                 "ask AP to fix them. IT is the only consumer of "
                 "those rows today.")
    lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def render_console(rows: List[Dict[str, str]],
                   missing: List[str],
                   csv_path: str, md_path: str,
                   probe_csv_path: str) -> str:
    counts: Dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r.get("test_doc_category", "")] += 1
    out: List[str] = []
    out.append("=" * 72)
    out.append(" build_ap_smoke_test_set")
    out.append("=" * 72)
    out.append(f"  source probe csv : {probe_csv_path or '(none)'}")
    out.append(f"  total rows       : {len(rows)}")
    out.append("")
    out.append("  rows by category:")
    for c in CATEGORIES:
        out.append(f"    {c:42s} {counts.get(c, 0):3d}  "
                   f"({CATEGORY_PRIORITY.get(c, 'P2')})")
    out.append("")
    if missing:
        out.append("  missing categories (no real example found):")
        for c in missing:
            out.append(f"    - {c}")
    else:
        out.append("  missing categories: (none)")
    out.append("")
    out.append(f"  csv_out : {csv_path}")
    out.append(f"  md_out  : {md_path}")
    out.append("")
    out.append("  READ-ONLY. No DB writes. No AP-facing send.")
    out.append("=" * 72)
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Read-only AP internal smoke-test document set generator.")
    p.add_argument("--probe-csv", default=None,
                   help=("Path to body-reconciliation probe CSV. "
                         "Defaults: prod_reports/document_body_"
                         "reconciliation_probe_limit100_final.csv "
                         "→ prod_reports/document_body_reconciliation_"
                         "probe.csv. Optional."))
    p.add_argument("--per-category", type=int, default=2,
                   help="Cap on documents per category (default 2).")
    p.add_argument("--out-csv",
                   default="prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv")
    p.add_argument("--out-md",
                   default="prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.md")
    p.add_argument("--hub-base-url", default="",
                   help=("Optional Hub URL prefix used to build the "
                         "hub_document_url column (e.g. "
                         "https://hub.example.com)."))
    args = p.parse_args()

    probe_csv_path, probe_rows = _resolve_probe_csv(args.probe_csv)

    coll = get_hub_documents_collection()
    cursor = coll.find({}, PROJECTION)
    hub_docs = list(cursor)

    rows, missing = curate(
        hub_docs=hub_docs,
        probe_rows=probe_rows,
        per_category=args.per_category,
        hub_base_url=args.hub_base_url,
    )

    write_csv(args.out_csv, rows)
    write_md(args.out_md, rows, missing, probe_csv_path)

    print(render_console(rows, missing,
                         args.out_csv, args.out_md, probe_csv_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
