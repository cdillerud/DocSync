"""
document_body_reconciliation_probe.py
=====================================
READ-ONLY prototype: reconcile Square9 ``manual_review_required``
documents against Hub documents using **document-body signals**, not
filename / parent-path / sender headers. The header-only reconciliation
work hit its ceiling at ~57.7%; the remaining gap requires reading
what's actually inside the documents.

This script does not chase a cutover percentage. It is the first
working iteration of a body-level reconciliation primitive that GPI
Hub needs in order to keep getting smarter about what each document
actually is, regardless of where it came from.

Inputs
------
- ``--triage-csv``  Default ``prod_reports/uncertain_square9_deep_triage.csv``.
                    Source of the manual_review_required cohort.
- ``--limit``       Top-N rows to attempt body extraction on.
                    Default 25.
- ``body_extractor`` (Python-side, injected) — given a Square9 row,
                    return ``(text, status)`` where status is
                    ``ok`` / ``ocr_required`` / ``no_access``.
                    The default extractor returns ``no_access`` so the
                    probe never makes a network call without explicit
                    wiring.
- Read-only ``hub_documents`` projection (vendor_canonical,
  invoice_number_clean, po_number_clean, amount_float, file_name,
  email_subject, sharepoint_folder_path, mailbox_category, doc_type,
  suggested_job_type, created_utc, plus extracted_fields /
  normalized_fields / ai_extraction when present).

Per-document classification (priority order):
  1. ``insufficient_content_access`` (extractor returned no_access)
  2. ``ocr_required``                 (extractor returned ocr_required)
  3. ``content_match_found``          (score >= 0.85)
  4. ``likely_same_invoice_different_attachment_granularity``
       (same vendor + amount + date but invoice number disagrees,
        suggesting one side stores remittance/attachment and the
        other stores the primary invoice)
  5. ``square9_only_true_gap``       (vendor present in Hub but no
                                      invoice/amount/PO match)
  6. ``manual_review_still_required`` (everything else)

Outputs (three artifacts):
- prod_reports/document_body_reconciliation_probe.csv
- prod_reports/document_body_reconciliation_probe.json
- prod_reports/document_body_reconciliation_probe.md

Strict guarantees:
- No Mongo writes.
- Default extractor performs no network I/O.
- No routing / classifier changes.
- No Square9 changes.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple


# Bootstrap: when invoked as ``python scripts/document_body_reconciliation_probe.py``
# Python places ``scripts/`` on sys.path[0], not the project root, which
# breaks ``from scripts.sharepoint_body_fetcher import …``. Prepend the
# project root so package-style imports resolve regardless of how the
# script is launched.
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TRIAGE_CSV = "prod_reports/uncertain_square9_deep_triage.csv"
TARGET_BUCKET = "manual_review_required"
DEFAULT_LIMIT = 25

CONTENT_MATCH_THRESHOLD = 0.85
ATTACHMENT_GRANULARITY_THRESHOLD = 0.70

WEIGHTS = {
    "invoice_number": 0.55,
    "amount": 0.20,
    "po_number": 0.10,
    "invoice_date": 0.10,
    "vendor": 0.05,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

INVOICE_NUMBER_RE = re.compile(
    r"\b(?:invoice\s*(?:no\.?|#|number)?|inv\s*(?:no\.?|#)?)\s*[:\-]?\s*"
    r"([A-Z0-9][A-Z0-9\-]{3,})", re.I)
PO_NUMBER_RE = re.compile(
    r"\b(?:po|p\.o\.|po#|purchase\s+order)\s*[:\-#]?\s*"
    r"([A-Z0-9][A-Z0-9\-]{3,})", re.I)
AMOUNT_RE = re.compile(
    r"(?:total|amount\s+due|balance\s+due|invoice\s+total)\s*[:\$]?\s*"
    r"\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d+\.\d{2})", re.I)
DATE_RE = re.compile(
    r"\b(?:invoice\s+date|date)\s*[:\-]?\s*"
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|"
    r"\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}|"
    r"[A-Z][a-z]+\s+\d{1,2},?\s+\d{4})", re.I)
VENDOR_HINT_RE = re.compile(
    r"\b(?:remit\s+to|bill\s+from|from|vendor|payee)\s*[:\-]?\s*([^\n,]{3,80})",
    re.I)
GENERIC_REF_RE = re.compile(
    r"\b(?:bol|order|reference|ref|order\s+no)\s*[:\-#]?\s*"
    r"([A-Z0-9][A-Z0-9\-]{3,})", re.I)

STOP_TOKENS = {
    "the", "and", "of", "for", "to", "by", "in", "on",
    "invoice", "inv", "doc", "ap", "pdf",
}


CONTENT_OK = "ok"
CONTENT_OCR_REQUIRED = "ocr_required"
CONTENT_NO_ACCESS = "no_access"

BUCKET_ORDER = (
    "content_match_found",
    "likely_same_invoice_different_attachment_granularity",
    "square9_only_true_gap",
    "ocr_required",
    "insufficient_content_access",
    "manual_review_still_required",
)

ACTION_FOR_BUCKET = {
    "content_match_found":
        "wire_into_matcher_as_body_signal_match",
    "likely_same_invoice_different_attachment_granularity":
        "decide_aggregation_strategy_per_vendor",
    "square9_only_true_gap":
        "investigate_square9_intake_lane",
    "ocr_required":
        "add_ocr_pipeline",
    "insufficient_content_access":
        "wire_sharepoint_graph_fetcher",
    "manual_review_still_required":
        "manual_AP_review",
}


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def read_csv_rows(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def filter_manual_review(rows: Iterable[Dict[str, str]]
                         ) -> List[Dict[str, str]]:
    return [r for r in rows
            if (r.get("triage_bucket") or "").strip() == TARGET_BUCKET]


# ---------------------------------------------------------------------------
# Body signal extraction (pure)
# ---------------------------------------------------------------------------

def _first_match(pattern: re.Pattern, text: str) -> Optional[str]:
    m = pattern.search(text or "")
    return m.group(1).strip() if m else None


def _amount_to_float(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    try:
        return float(raw.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _date_to_iso(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip()
    candidates = [
        ("%m/%d/%Y", "%Y-%m-%d"), ("%m-%d-%Y", "%Y-%m-%d"),
        ("%m/%d/%y", "%Y-%m-%d"), ("%Y-%m-%d", "%Y-%m-%d"),
        ("%Y/%m/%d", "%Y-%m-%d"), ("%B %d, %Y", "%Y-%m-%d"),
        ("%B %d %Y", "%Y-%m-%d"),
    ]
    for fmt_in, fmt_out in candidates:
        try:
            return dt.datetime.strptime(raw, fmt_in).strftime(fmt_out)
        except ValueError:
            pass
    return None


def extract_body_signals(text: str) -> Dict[str, Any]:
    """Pull AP-relevant identity signals from raw document text."""
    text = text or ""
    return {
        "invoice_number":
            (_first_match(INVOICE_NUMBER_RE, text) or "").upper() or None,
        "po_number":
            (_first_match(PO_NUMBER_RE, text) or "").upper() or None,
        "amount":
            _amount_to_float(_first_match(AMOUNT_RE, text)),
        "invoice_date":
            _date_to_iso(_first_match(DATE_RE, text)),
        "vendor_hint": _first_match(VENDOR_HINT_RE, text),
        "reference_numbers": [
            r.upper() for r in GENERIC_REF_RE.findall(text)
        ],
    }


# ---------------------------------------------------------------------------
# Hub corpus index
# ---------------------------------------------------------------------------

def _digits_only(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\D+", "", s)
    return s.lstrip("0") or s


def _norm_invoice(s: str) -> str:
    return (s or "").strip().upper().replace("-", "")


def _norm_po(s: str) -> str:
    return (s or "").strip().upper().replace("-", "")


def tokenize(s: str) -> List[str]:
    if not s:
        return []
    return [t for t in re.sub(r"[^a-z0-9]+", " ", s.lower()).split()
            if t and t not in STOP_TOKENS]


class HubIndex:
    __slots__ = (
        "vendor_tokens", "sender_domain_roots",
        "by_invoice_norm", "by_invoice_digits",
        "by_po_norm", "by_amount", "doc_count", "all_docs",
    )

    def __init__(self):
        self.vendor_tokens: Set[str] = set()
        self.sender_domain_roots: Set[str] = set()
        self.by_invoice_norm: Dict[str, Dict[str, str]] = {}
        self.by_invoice_digits: Dict[str, Dict[str, str]] = {}
        self.by_po_norm: Dict[str, Dict[str, str]] = {}
        self.by_amount: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        self.all_docs: List[Dict[str, str]] = []
        self.doc_count = 0


def _hub_doc_record(d: Dict[str, Any]) -> Dict[str, str]:
    return {
        "hub_doc_id": str(d.get("id") or d.get("hub_doc_id") or ""),
        "hub_file_name": str(d.get("file_name") or ""),
        "hub_vendor_canonical": str(d.get("vendor_canonical") or ""),
        "hub_invoice_number_clean": str(d.get("invoice_number_clean") or ""),
        "hub_po_number_clean": str(d.get("po_number_clean") or ""),
        "hub_amount_float": str(d.get("amount_float") or ""),
        "hub_email_sender": str(d.get("email_sender") or ""),
        "hub_email_subject": str(d.get("email_subject") or ""),
        "hub_mailbox_category": str(d.get("mailbox_category") or ""),
        "hub_doc_type": str(d.get("doc_type") or ""),
        "hub_suggested_job_type": str(d.get("suggested_job_type") or ""),
        "hub_invoice_date":
            str(d.get("invoice_date")
                or (d.get("normalized_fields") or {}).get("invoice_date")
                or ""),
        "hub_created_utc":
            str(d.get("created_utc") or d.get("created_at") or ""),
    }


def build_hub_index_from_docs(docs: Iterable[Dict[str, Any]]) -> HubIndex:
    idx = HubIndex()
    for d in docs:
        idx.doc_count += 1
        rec = _hub_doc_record(d)
        idx.all_docs.append(rec)

        for t in tokenize(rec["hub_vendor_canonical"]):
            idx.vendor_tokens.add(t)
        sender = rec["hub_email_sender"].lower()
        if "@" in sender:
            domain = sender.split("@", 1)[1].split(".")[0]
            if domain:
                idx.sender_domain_roots.add(domain)

        inv_norm = _norm_invoice(rec["hub_invoice_number_clean"])
        if inv_norm and len(inv_norm) >= 4:
            idx.by_invoice_norm.setdefault(inv_norm, rec)
            digits = _digits_only(inv_norm)
            if digits and len(digits) >= 4:
                idx.by_invoice_digits.setdefault(digits, rec)

        po_norm = _norm_po(rec["hub_po_number_clean"])
        if po_norm and len(po_norm) >= 4:
            idx.by_po_norm.setdefault(po_norm, rec)

        amt = rec["hub_amount_float"].strip()
        if amt:
            try:
                v = float(amt)
                if v > 0:
                    idx.by_amount[f"{v:.2f}"].append(rec)
            except (TypeError, ValueError):
                pass
    return idx


def build_hub_index_from_mongo(collection) -> HubIndex:
    cursor = collection.find(
        {},
        {
            "_id": 0, "id": 1,
            "vendor_canonical": 1, "email_sender": 1,
            "invoice_number_clean": 1, "po_number_clean": 1,
            "amount_float": 1, "invoice_date": 1, "file_name": 1,
            "email_subject": 1, "sharepoint_folder_path": 1,
            "mailbox_category": 1, "doc_type": 1,
            "suggested_job_type": 1, "created_utc": 1, "created_at": 1,
            "normalized_fields": 1,
        },
    )
    return build_hub_index_from_docs(cursor)


# ---------------------------------------------------------------------------
# Body-signals -> Hub-doc scoring
# ---------------------------------------------------------------------------

def _amount_match(a: Optional[float], b_str: str) -> bool:
    if a is None or not b_str:
        return False
    try:
        return abs(a - float(b_str)) <= 0.01
    except (TypeError, ValueError):
        return False


def score_signals_against_hub(signals: Dict[str, Any],
                              idx: HubIndex
                              ) -> Tuple[float, Optional[Dict[str, str]],
                                         Dict[str, float], List[str]]:
    """Return (score, best_hub_doc, per-signal-breakdown, signals_won)."""
    if idx.doc_count == 0:
        return 0.0, None, {}, []

    candidates: Dict[str, Dict[str, str]] = {}

    inv = signals.get("invoice_number")
    if inv:
        inv_norm = _norm_invoice(inv)
        if inv_norm in idx.by_invoice_norm:
            doc = idx.by_invoice_norm[inv_norm]
            candidates.setdefault(doc["hub_doc_id"], doc)
        digits = _digits_only(inv_norm)
        if digits and digits in idx.by_invoice_digits:
            doc = idx.by_invoice_digits[digits]
            candidates.setdefault(doc["hub_doc_id"], doc)

    po = signals.get("po_number")
    if po:
        po_norm = _norm_po(po)
        if po_norm in idx.by_po_norm:
            doc = idx.by_po_norm[po_norm]
            candidates.setdefault(doc["hub_doc_id"], doc)

    amt = signals.get("amount")
    if amt is not None:
        for doc in idx.by_amount.get(f"{amt:.2f}", ()):
            candidates.setdefault(doc["hub_doc_id"], doc)

    if not candidates:
        return 0.0, None, {}, []

    best_score = 0.0
    best_doc: Optional[Dict[str, str]] = None
    best_breakdown: Dict[str, float] = {}
    best_signals_won: List[str] = []
    for doc in candidates.values():
        breakdown: Dict[str, float] = {}
        if inv and (
            _norm_invoice(inv) == _norm_invoice(doc["hub_invoice_number_clean"])
            or _digits_only(inv) ==
            _digits_only(doc["hub_invoice_number_clean"])
        ):
            breakdown["invoice_number"] = 1.0
        if po and _norm_po(po) == _norm_po(doc["hub_po_number_clean"]):
            breakdown["po_number"] = 1.0
        if _amount_match(amt, doc["hub_amount_float"]):
            breakdown["amount"] = 1.0
        if signals.get("invoice_date") and signals["invoice_date"] == \
                (doc.get("hub_invoice_date") or ""):
            breakdown["invoice_date"] = 1.0
        vendor_hint = (signals.get("vendor_hint") or "").lower()
        if vendor_hint and tokenize(vendor_hint) and (
            set(tokenize(vendor_hint))
            & set(tokenize(doc["hub_vendor_canonical"]))
        ):
            breakdown["vendor"] = 1.0

        score = sum(breakdown.get(k, 0.0) * w for k, w in WEIGHTS.items())
        if score > best_score:
            best_score = score
            best_doc = doc
            best_breakdown = breakdown
            best_signals_won = list(breakdown.keys())
    return best_score, best_doc, best_breakdown, best_signals_won


# ---------------------------------------------------------------------------
# Body extractor protocol + default
# ---------------------------------------------------------------------------

BodyExtractor = Callable[[Dict[str, str]], Tuple[str, str]]


def default_body_extractor(_row: Dict[str, str]) -> Tuple[str, str]:
    """Production stub: returns no_access. Wire a SharePoint/Graph
    fetcher in main() when the credentials are available; tests inject
    their own extractor directly."""
    return "", CONTENT_NO_ACCESS


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def vendor_in_hub(row: Dict[str, str], idx: HubIndex) -> bool:
    haystack = " ".join((
        row.get("square9_name") or "",
        row.get("square9_parent_path") or "",
        row.get("square9_web_url") or "",
    ))
    sq_tokens = set(tokenize(haystack))
    if not sq_tokens:
        return False
    return bool(sq_tokens & idx.vendor_tokens) or \
        bool(sq_tokens & idx.sender_domain_roots)


def classify(*, status: str,
             signals: Dict[str, Any],
             score: float,
             best_hub: Optional[Dict[str, str]],
             breakdown: Dict[str, float],
             vendor_known: bool,
             ) -> Tuple[str, str]:
    if status == CONTENT_NO_ACCESS:
        return ("insufficient_content_access",
                "could not retrieve document content")
    if status == CONTENT_OCR_REQUIRED:
        return ("ocr_required",
                "PDF body had no extractable text; OCR pass needed")

    if score >= CONTENT_MATCH_THRESHOLD and best_hub:
        return ("content_match_found",
                f"score {score:.2f} >= {CONTENT_MATCH_THRESHOLD} on "
                f"hub_doc_id={best_hub['hub_doc_id']!r}")

    # Same vendor + amount + date but invoice number disagrees -> very
    # likely the same economic event split into multiple files.
    if (best_hub
            and breakdown.get("amount", 0) == 1.0
            and breakdown.get("invoice_number", 0) == 0
            and (breakdown.get("invoice_date", 0) == 1.0
                 or breakdown.get("vendor", 0) == 1.0)
            and score >= ATTACHMENT_GRANULARITY_THRESHOLD * WEIGHTS["amount"]):
        return ("likely_same_invoice_different_attachment_granularity",
                f"vendor+amount agree with hub_doc_id="
                f"{best_hub['hub_doc_id']!r} but invoice_number does not")

    if vendor_known:
        return ("square9_only_true_gap",
                "vendor known to Hub but no body-signal match against "
                "any Hub document")

    return ("manual_review_still_required",
            "body signals incomplete and vendor not registered in Hub")


# ---------------------------------------------------------------------------
# Probe runner
# ---------------------------------------------------------------------------

def probe(rows: List[Dict[str, str]],
          *,
          extractor: BodyExtractor,
          idx: HubIndex,
          limit: int = DEFAULT_LIMIT,
          ) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows[:limit] if limit else rows:
        text, status = extractor(row)
        if status == CONTENT_OK and not text.strip():
            status = CONTENT_OCR_REQUIRED
        signals = (extract_body_signals(text)
                   if status == CONTENT_OK else
                   {"invoice_number": None, "po_number": None,
                    "amount": None, "invoice_date": None,
                    "vendor_hint": None, "reference_numbers": []})
        score, best_hub, breakdown, _signals_won = (
            score_signals_against_hub(signals, idx)
            if status == CONTENT_OK else (0.0, None, {}, []))
        bucket, reason = classify(
            status=status, signals=signals, score=score,
            best_hub=best_hub, breakdown=breakdown,
            vendor_known=vendor_in_hub(row, idx),
        )
        hub = best_hub or {}
        out.append({
            "square9_name": row.get("square9_name", ""),
            "square9_parent_path": row.get("square9_parent_path", ""),
            "square9_web_url": row.get("square9_web_url", ""),
            "content_access_status": status,
            "extracted_invoice_number": signals.get("invoice_number") or "",
            "extracted_vendor": signals.get("vendor_hint") or "",
            "extracted_amount":
                f"{signals['amount']:.2f}" if signals.get("amount") is not None
                else "",
            "extracted_invoice_date": signals.get("invoice_date") or "",
            "extracted_po_number": signals.get("po_number") or "",
            "extracted_reference_numbers":
                ",".join(signals.get("reference_numbers") or []),
            "best_hub_doc_id": hub.get("hub_doc_id", ""),
            "best_hub_file_name": hub.get("hub_file_name", ""),
            "best_hub_vendor_canonical":
                hub.get("hub_vendor_canonical", ""),
            "best_hub_invoice_number_clean":
                hub.get("hub_invoice_number_clean", ""),
            "best_hub_amount_float": hub.get("hub_amount_float", ""),
            "best_hub_po_number_clean":
                hub.get("hub_po_number_clean", ""),
            "best_match_score": round(score, 3),
            "best_match_reason": reason,
            "classification": bucket,
            "recommended_next_action": ACTION_FOR_BUCKET[bucket],
        })
    return out


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def build_summary(probed: List[Dict[str, Any]],
                  hub_doc_count: int,
                  source_csv: str,
                  top: int = 25) -> Dict[str, Any]:
    total = len(probed)
    bc: Counter = Counter(r["classification"] for r in probed)
    failure_reasons: Counter = Counter(r["best_match_reason"] for r in probed)
    top_vendors: Counter = Counter(
        (r["best_hub_vendor_canonical"] or r["extracted_vendor"] or "<unknown>")
        for r in probed
    )

    def _trim(rows: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
        keep = ("classification", "recommended_next_action",
                "square9_name", "extracted_invoice_number",
                "extracted_amount", "extracted_invoice_date",
                "best_hub_doc_id", "best_hub_file_name",
                "best_hub_vendor_canonical", "best_match_score",
                "best_match_reason", "content_access_status")
        return [{k: r.get(k) for k in keep} for r in rows[:n]]

    by_bucket: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in probed:
        by_bucket[r["classification"]].append(r)

    next_steps: List[str] = []
    if bc.get("insufficient_content_access", 0) > 0:
        next_steps.append(
            "Wire a SharePoint/Graph fetcher into "
            "default_body_extractor so the probe can read Square9 "
            "files directly.")
    if bc.get("ocr_required", 0) > 0:
        next_steps.append(
            "Add an OCR pass (pytesseract / Azure OCR / similar) "
            "for PDFs that have no embedded text.")
    if bc.get("content_match_found", 0) > 0:
        next_steps.append(
            "Promote body-signal matches into the parity matcher as a "
            "first-class signal alongside header signals.")
    if bc.get("likely_same_invoice_different_attachment_granularity", 0) > 0:
        next_steps.append(
            "Decide a per-vendor aggregation rule for documents that "
            "Square9 splits but Hub stores as a single record (or vice "
            "versa). This is policy, not just code.")
    if bc.get("square9_only_true_gap", 0) > 0:
        next_steps.append(
            "Investigate the Square9 intake lanes for vendors that have "
            "true gaps -- these are documents Hub never received.")

    return {
        "source_csv": source_csv,
        "hub_doc_count": hub_doc_count,
        "total_attempted": total,
        "content_read_success": sum(
            1 for r in probed
            if r["content_access_status"] == CONTENT_OK),
        "ocr_required": bc.get("ocr_required", 0),
        "content_match_found": bc.get("content_match_found", 0),
        "same_invoice_different_attachment_granularity":
            bc.get(
                "likely_same_invoice_different_attachment_granularity", 0),
        "true_square9_only_gap": bc.get("square9_only_true_gap", 0),
        "insufficient_content_access":
            bc.get("insufficient_content_access", 0),
        "manual_review_still_required":
            bc.get("manual_review_still_required", 0),
        "bucket_counts": {b: bc.get(b, 0) for b in BUCKET_ORDER},
        "top_vendors": top_vendors.most_common(top),
        "top_failure_reasons": failure_reasons.most_common(top),
        "top_examples_by_bucket": {
            b: _trim(by_bucket.get(b, []), top) for b in BUCKET_ORDER
        },
        "recommended_engineering_next_steps": next_steps,
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

OUTPUT_CSV_COLUMNS = [
    "square9_name", "square9_parent_path", "square9_web_url",
    "content_access_status",
    "extracted_invoice_number", "extracted_vendor", "extracted_amount",
    "extracted_invoice_date", "extracted_po_number",
    "extracted_reference_numbers",
    "best_hub_doc_id", "best_hub_file_name",
    "best_hub_vendor_canonical", "best_hub_invoice_number_clean",
    "best_hub_amount_float", "best_hub_po_number_clean",
    "best_match_score", "best_match_reason",
    "classification", "recommended_next_action",
]


def write_csv(path: str, probed: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_CSV_COLUMNS,
                           extrasaction="ignore")
        w.writeheader()
        for r in probed:
            w.writerow(r)


def write_json(path: str, summary: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, default=str, indent=2)


def write_md(path: str, summary: Dict[str, Any], top: int = 25) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    bc = summary["bucket_counts"]
    total = summary["total_attempted"]
    pct = lambda n: (n / total * 100.0) if total else 0.0  # noqa: E731

    lines: List[str] = []
    lines.append("# Document body reconciliation probe")
    lines.append("")
    lines.append("Read-only first iteration of body-level reconciliation. "
                 "Header-only audits have hit their ceiling; this probe "
                 "starts moving GPI Hub toward genuine document understanding.")
    lines.append("")
    lines.append(f"- source_csv: `{summary['source_csv']}`")
    lines.append(f"- hub_doc_count: **{summary['hub_doc_count']}**")
    lines.append(f"- total_attempted: **{total}**")
    lines.append(f"- content_read_success: "
                 f"**{summary['content_read_success']}**")
    lines.append(f"- ocr_required: **{summary['ocr_required']}**")
    lines.append(f"- insufficient_content_access: "
                 f"**{summary['insufficient_content_access']}**")
    lines.append("")
    lines.append("## Plain-English summary")
    lines.append("")
    if summary["content_read_success"] == 0:
        lines.append("- No document bodies were read in this run. "
                     "Wire a SharePoint/Graph fetcher into the default "
                     "extractor before running the probe again on real "
                     "data.")
    else:
        if summary["content_match_found"] > 0:
            lines.append(f"- Body-level matching solved "
                         f"**{summary['content_match_found']}** documents "
                         f"that header-only matching could not.")
        if summary["same_invoice_different_attachment_granularity"] > 0:
            lines.append(
                f"- Found **{summary['same_invoice_different_attachment_granularity']}** "
                f"documents that look like the same economic invoice "
                f"split differently between Hub and Square9.")
        if summary["ocr_required"] > 0:
            lines.append(f"- **{summary['ocr_required']}** documents "
                         f"have no extractable text; OCR is needed "
                         f"before body matching can apply.")
        if summary["true_square9_only_gap"] > 0:
            lines.append(f"- **{summary['true_square9_only_gap']}** "
                         f"documents appear to be true Square9-only "
                         f"intake gaps (vendor known to Hub, but the "
                         f"specific document content does not).")
        if summary["manual_review_still_required"] > 0:
            lines.append(f"- **{summary['manual_review_still_required']}** "
                         f"documents still require manual AP review even "
                         f"after body inspection.")
    lines.append("")
    lines.append("## Bucket counts")
    lines.append("")
    lines.append("| classification | count | pct | recommended_next_action |")
    lines.append("| --- | ---: | ---: | --- |")
    for b in BUCKET_ORDER:
        n = bc.get(b, 0)
        lines.append(f"| {b} | {n} | {pct(n):.1f}% | "
                     f"{ACTION_FOR_BUCKET[b]} |")
    lines.append("")

    def _table(title: str, rows: List[Dict[str, Any]]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        if not rows:
            lines.append("_no rows_")
            lines.append("")
            return
        lines.append("| square9_name | extracted_invoice | extracted_amount | "
                     "best_hub_doc_id | best_match_score | best_match_reason |")
        lines.append("| --- | --- | --- | --- | ---: | --- |")
        for r in rows:
            lines.append(
                f"| {r.get('square9_name','')} "
                f"| {r.get('extracted_invoice_number','')} "
                f"| {r.get('extracted_amount','')} "
                f"| {r.get('best_hub_doc_id','')} "
                f"| {r.get('best_match_score', 0)} "
                f"| {r.get('best_match_reason','')} |"
            )
        lines.append("")

    for b in BUCKET_ORDER:
        _table(f"Top {top} {b}",
               summary["top_examples_by_bucket"].get(b, []))

    lines.append("## Recommended engineering next steps")
    lines.append("")
    if summary["recommended_engineering_next_steps"]:
        for step in summary["recommended_engineering_next_steps"]:
            lines.append(f"- {step}")
    else:
        lines.append("- _no automatic recommendations from this probe run_")
    lines.append("")
    lines.append("_READ-ONLY probe. No DB writes, no routing changes._")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Console renderer
# ---------------------------------------------------------------------------

def render_console(summary: Dict[str, Any],
                   csv_out: str, json_out: str, md_out: str) -> str:
    bc = summary["bucket_counts"]
    total = summary["total_attempted"]
    out: List[str] = []
    out.append("=" * 72)
    out.append(" document_body_reconciliation_probe")
    out.append("=" * 72)
    out.append(f"  source_csv               : {summary['source_csv']}")
    out.append(f"  hub_doc_count            : {summary['hub_doc_count']}")
    out.append(f"  total_attempted          : {total}")
    out.append(f"  content_read_success     : "
               f"{summary['content_read_success']}")
    out.append(f"  ocr_required             : {summary['ocr_required']}")
    out.append(f"  insufficient_content_access: "
               f"{summary['insufficient_content_access']}")
    out.append("")
    out.append("  bucket counts:")
    for b in BUCKET_ORDER:
        n = bc.get(b, 0)
        pct_v = (n / total * 100.0) if total else 0.0
        out.append(f"    {b:55s} {n:5d}  ({pct_v:5.1f}%)")
    out.append("")
    if summary["recommended_engineering_next_steps"]:
        out.append("  recommended next steps:")
        for s in summary["recommended_engineering_next_steps"]:
            out.append(f"    - {s}")
        out.append("")
    out.append(f"  csv_out  : {csv_out}")
    out.append(f"  json_out : {json_out}")
    out.append(f"  md_out   : {md_out}")
    out.append("")
    out.append("  READ-ONLY probe. No DB writes, no routing changes.")
    out.append("=" * 72)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def get_hub_documents_collection():
    from pymongo import MongoClient  # noqa: WPS433
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise RuntimeError("MONGO_URL / DB_NAME env vars are required.")
    return MongoClient(mongo_url)[db_name]["hub_documents"]


def main(extractor: Optional[BodyExtractor] = None) -> int:
    p = argparse.ArgumentParser(
        description="Read-only document-body reconciliation probe.")
    p.add_argument("--triage-csv", default=DEFAULT_TRIAGE_CSV)
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--out-csv",
                   default="prod_reports/document_body_reconciliation_probe.csv")
    p.add_argument("--json",
                   default="prod_reports/document_body_reconciliation_probe.json")
    p.add_argument("--md",
                   default="prod_reports/document_body_reconciliation_probe.md")
    p.add_argument("--no-cache", action="store_true",
                   help="Bypass /tmp/body_probe_cache and force re-fetch.")
    p.add_argument(
        "--use-noop-fetcher", action="store_true",
        help=("Explicitly run with the no-op body extractor (no document "
              "bodies will be read; every row will classify as "
              "insufficient_content_access). Intended only for plumbing "
              "verification / test runs. Without this flag the probe "
              "REQUIRES the production SharePoint/Graph fetcher and will "
              "exit non-zero if it cannot be built."))
    args = p.parse_args()

    if not os.path.exists(args.triage_csv):
        print(f"probe: triage CSV not found at {args.triage_csv!r}.",
              file=sys.stderr)
        return 2

    rows = filter_manual_review(read_csv_rows(args.triage_csv))
    coll = get_hub_documents_collection()
    idx = build_hub_index_from_mongo(coll)

    if extractor is None:
        if args.use_noop_fetcher:
            print(
                "probe: --use-noop-fetcher set; no document bodies will be "
                "read. Every row will classify as "
                "insufficient_content_access. This mode is for plumbing "
                "verification only.",
                file=sys.stderr,
            )
            extractor = default_body_extractor
        else:
            try:
                from scripts.sharepoint_body_fetcher import (
                    build_production_fetcher,
                )
                extractor = build_production_fetcher(no_cache=args.no_cache)
            except Exception as e:  # noqa: BLE001
                print(
                    "probe: could not build production SharePoint/Graph "
                    f"fetcher: {e!r}. Refusing to silently fall back to "
                    "the no-op extractor. If you intentionally want to "
                    "run the probe without reading document bodies "
                    "(plumbing check only), re-run with "
                    "--use-noop-fetcher.",
                    file=sys.stderr,
                )
                return 3

    probed = probe(
        rows,
        extractor=extractor,
        idx=idx,
        limit=args.limit,
    )
    summary = build_summary(probed,
                            hub_doc_count=idx.doc_count,
                            source_csv=args.triage_csv,
                            top=args.top)

    write_csv(args.out_csv, probed)
    write_json(args.json, summary)
    write_md(args.md, summary, top=args.top)

    print(render_console(summary, args.out_csv, args.json, args.md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
