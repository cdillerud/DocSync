"""
uncertain_square9_deep_triage.py
================================
READ-ONLY follow-up triage of the rows that ``no_match_square9_audit``
classified as ``uncertain``. Uses richer identity signals (multiple
invoice / PO digit runs, vendor + amount, filename similarity,
email-subject similarity, SharePoint folder path overlap) plus a
broader Mongo enrichment of ``hub_documents`` across all categories
(not just AP) to convert each uncertain row into one of four
actionable buckets:

  - recoverable_matcher_miss     improve_matcher
  - square9_scope_exclusion      exclude_from_square9_scope
  - true_intake_gap              intake_channel_investigation
  - manual_review_required       manual_review

Predicate priority (earliest wins):
  1. square9_scope_exclusion  (extended non-AP keyword list)
  2. recoverable_matcher_miss (any of: invoice token in Hub /
     PO token in Hub / vendor token + amount overlap / strong
     filename or subject Jaccard / sharepoint folder hit)
  3. true_intake_gap          (no Hub doc has a matching vendor
     canonical OR sender domain root for any token in the Square9
     name + parent_path + web_url)
  4. manual_review_required   (otherwise)

Projection math (combines this triage with the prior audit so the
operator sees the full ceiling):

  current             = matched / square_count
  after_recoverable_only = (matched + prior_recoverable + R) / square_count
  after_exclusions_only  = matched / max(square_count - prior_excludable - E, 1)
  after_both           = (matched + prior_recoverable + R)
                         / max(square_count - prior_excludable - E, 1)

Where R, E come from this triage:
  R = recoverable_matcher_miss
  E = square9_scope_exclusion + true_intake_gap

Exit codes: 0 (after_both >= 85%), 1 (>=70%, <85%), 2 (<70%).

This script writes nothing to Mongo. The Mongo touch is one read-only
``find`` projection; tests inject the index synthetically.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import os
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PRIOR_AUDIT_JSON = "prod_reports/no_match_square9_audit.json"

# Extended non-AP keyword list (broader than the prior audit so this
# pass catches more excludable rows).
NON_AP_NEEDLES = tuple(s.lower() for s in (
    "treasury", "positive pay", "positive_pay",
    "ach.csv", "wire.csv", " ach ", " wire ",
    "wire transfer", "ach transfer", "wire log", "wire_log",
    "monthly rec", "reconciliation", "month end", "month-end",
    "do not pay", "do_not_pay", "donotpay",
    "stop pay", "stop_pay",
    "template", "templates", "instructions", "instruction.",
    "pst", ".pst",
    "bank statement", "bank_statement",
    "chargeback", "charge back",
    "credit card", "creditcard", "cc statement",
    "payroll", "1099",
    "tax form", "tax_form", "w-9", "w9",
    "void check", "voided check",
))

INVOICE_DIGIT_MIN_LEN = 4
PO_TOKEN_RE = re.compile(
    r"\b(?:po|p\.o\.|po#)\s*[-:]?\s*"
    r"([A-Za-z0-9-]*\d[A-Za-z0-9-]*)",
    re.I,
)
AMOUNT_RE = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+\.\d{2})")
DIGIT_RUN_RE = re.compile(r"\d+")

FILENAME_JACCARD_STRONG = 0.30
SUBJECT_JACCARD_STRONG = 0.45

STOP_TOKENS = {
    "the", "and", "of", "for", "to", "by", "in", "on",
    "invoice", "inv", "doc", "docs", "ap", "pdf", "tif", "tiff",
    "png", "jpg", "jpeg", "scan", "scans", "scanned", "copy",
    "final", "draft", "page", "p", "pp", "no", "number",
}

EXIT_GO = 0
EXIT_MIXED = 1
EXIT_NO_GO = 2

GO_THRESHOLD = 85.0
MIXED_THRESHOLD = 70.0

ACTION_IMPROVE_MATCHER = "improve_matcher"
ACTION_EXCLUDE = "exclude_from_square9_scope"
ACTION_INTAKE_INVESTIGATION = "intake_channel_investigation"
ACTION_MANUAL_REVIEW = "manual_review"

BUCKET_TO_ACTION = {
    "recoverable_matcher_miss": ACTION_IMPROVE_MATCHER,
    "square9_scope_exclusion": ACTION_EXCLUDE,
    "true_intake_gap": ACTION_INTAKE_INVESTIGATION,
    "manual_review_required": ACTION_MANUAL_REVIEW,
}

BUCKET_ORDER = (
    "recoverable_matcher_miss",
    "square9_scope_exclusion",
    "true_intake_gap",
    "manual_review_required",
)


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def find_latest(pattern: str, base_dir: str = "prod_reports") -> Optional[str]:
    candidates = sorted(
        glob.glob(os.path.join(base_dir, "cutover_proof_*", pattern)),
        reverse=True,
    )
    if candidates:
        return candidates[0]
    fallback = os.path.join(base_dir, pattern)
    return fallback if os.path.exists(fallback) else None


def read_csv_rows(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

def digits_only(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\D+", "", s)
    return s.lstrip("0") or s


def tokenize(s: str) -> List[str]:
    if not s:
        return []
    norm = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return [t for t in norm.split() if t and t not in STOP_TOKENS]


def jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def extract_invoice_tokens(text: str) -> List[str]:
    if not text:
        return []
    return [r for r in DIGIT_RUN_RE.findall(text)
            if len(r) >= INVOICE_DIGIT_MIN_LEN]


def extract_po_tokens(text: str) -> List[str]:
    if not text:
        return []
    matches = PO_TOKEN_RE.findall(text)
    return [m for m in matches if m and len(m) >= 4]


def extract_amount_tokens(text: str) -> List[str]:
    """Return the raw amount strings present in the text."""
    if not text:
        return []
    return [m.replace(",", "") for m in AMOUNT_RE.findall(text)]


def parse_iso_utc(s: str) -> Optional[dt.datetime]:
    if not s:
        return None
    try:
        v = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if v.tzinfo is None:
            v = v.replace(tzinfo=dt.timezone.utc)
        return v
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Hub corpus index
# ---------------------------------------------------------------------------

class HubIndex:
    """Token-level reverse index of hub_documents."""

    __slots__ = (
        "vendor_tokens", "sender_domain_roots",
        "by_invoice_digits", "by_po_token",
        "by_filename_token", "by_subject_token",
        "by_folder_path_token", "by_amount",
        "doc_count",
    )

    def __init__(self):
        self.vendor_tokens: Set[str] = set()
        self.sender_domain_roots: Set[str] = set()
        self.by_invoice_digits: Dict[str, Dict[str, str]] = {}
        self.by_po_token: Dict[str, Dict[str, str]] = {}
        self.by_filename_token: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        self.by_subject_token: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        self.by_folder_path_token: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        self.by_amount: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        self.doc_count = 0


def _doc_record(d: Dict[str, Any]) -> Dict[str, str]:
    return {
        "hub_doc_id": str(d.get("id", "") or d.get("hub_doc_id", "")),
        "hub_file_name": str(d.get("file_name", "") or ""),
        "hub_mailbox_category": str(d.get("mailbox_category", "") or ""),
        "hub_doc_type": str(d.get("doc_type", "") or ""),
        "hub_suggested_job_type": str(d.get("suggested_job_type", "") or ""),
        "hub_vendor_canonical": str(d.get("vendor_canonical", "") or ""),
        "hub_invoice_number_clean":
            str(d.get("invoice_number_clean", "") or ""),
        "hub_po_number_clean": str(d.get("po_number_clean", "") or ""),
        "hub_amount_float": str(d.get("amount_float", "") or ""),
        "hub_email_sender": str(d.get("email_sender", "") or ""),
        "hub_email_subject": str(d.get("email_subject", "") or ""),
        "hub_sharepoint_folder_path":
            str(d.get("sharepoint_folder_path", "") or ""),
        "hub_created_utc":
            str(d.get("created_utc", "") or d.get("created_at", "") or ""),
    }


def build_hub_index_from_docs(docs: Iterable[Dict[str, Any]]) -> HubIndex:
    idx = HubIndex()
    for d in docs:
        idx.doc_count += 1
        rec = _doc_record(d)

        for t in tokenize(rec["hub_vendor_canonical"]):
            idx.vendor_tokens.add(t)
        sender = rec["hub_email_sender"].lower()
        if "@" in sender:
            domain = sender.split("@", 1)[1].split(".")[0]
            if domain:
                idx.sender_domain_roots.add(domain)

        inv = digits_only(rec["hub_invoice_number_clean"])
        if inv and len(inv) >= INVOICE_DIGIT_MIN_LEN:
            idx.by_invoice_digits.setdefault(inv, rec)

        po = rec["hub_po_number_clean"].strip().upper()
        if po and len(po) >= 4:
            idx.by_po_token.setdefault(po, rec)

        for t in tokenize(rec["hub_file_name"]):
            if len(idx.by_filename_token[t]) < 8:
                idx.by_filename_token[t].append(rec)
        for t in tokenize(rec["hub_email_subject"]):
            if len(idx.by_subject_token[t]) < 8:
                idx.by_subject_token[t].append(rec)
        for t in tokenize(rec["hub_sharepoint_folder_path"]):
            if len(idx.by_folder_path_token[t]) < 8:
                idx.by_folder_path_token[t].append(rec)

        amt = rec["hub_amount_float"].strip()
        if amt:
            try:
                v = float(amt)
                if v > 0:
                    key = f"{v:.2f}"
                    if len(idx.by_amount[key]) < 12:
                        idx.by_amount[key].append(rec)
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
            "amount_float": 1, "file_name": 1,
            "email_subject": 1, "sharepoint_folder_path": 1,
            "mailbox_category": 1, "doc_type": 1,
            "suggested_job_type": 1, "created_utc": 1,
            "created_at": 1,
        },
    )
    return build_hub_index_from_docs(cursor)


# ---------------------------------------------------------------------------
# Classification (pure)
# ---------------------------------------------------------------------------

def _haystack(row: Dict[str, str]) -> str:
    return " ".join((
        row.get("square9_name") or "",
        row.get("square9_parent_path") or "",
        row.get("square9_web_url") or "",
    ))


def is_scope_exclusion(row: Dict[str, str]) -> Tuple[bool, str]:
    h = _haystack(row).lower()
    if not h:
        return False, ""
    for needle in NON_AP_NEEDLES:
        if needle in h:
            return True, f"non-AP keyword {needle!r} present in name/path"
    return False, ""


def find_invoice_match(text: str, idx: HubIndex
                       ) -> Optional[Tuple[str, Dict[str, str]]]:
    for tok in extract_invoice_tokens(text):
        digits = digits_only(tok)
        if digits and digits in idx.by_invoice_digits:
            return digits, idx.by_invoice_digits[digits]
    return None


def find_po_match(text: str, idx: HubIndex
                  ) -> Optional[Tuple[str, Dict[str, str]]]:
    for tok in extract_po_tokens(text):
        key = tok.strip().upper()
        if key in idx.by_po_token:
            return key, idx.by_po_token[key]
    return None


def find_amount_match(text: str, idx: HubIndex
                      ) -> Optional[Tuple[str, Dict[str, str]]]:
    for raw in extract_amount_tokens(text):
        try:
            v = float(raw)
        except ValueError:
            continue
        key = f"{v:.2f}"
        if key in idx.by_amount and idx.by_amount[key]:
            return key, idx.by_amount[key][0]
    return None


def find_filename_match(row: Dict[str, str], idx: HubIndex
                        ) -> Tuple[float, Optional[Dict[str, str]]]:
    sq_tokens = tokenize(row.get("square9_name", ""))
    if not sq_tokens:
        return 0.0, None
    best_score, best_doc = 0.0, None
    seen: Set[str] = set()
    for tok in sq_tokens:
        for cand in idx.by_filename_token.get(tok, ()):
            doc_id = cand["hub_doc_id"]
            if doc_id in seen:
                continue
            seen.add(doc_id)
            score = jaccard(sq_tokens, tokenize(cand["hub_file_name"]))
            if score > best_score:
                best_score, best_doc = score, cand
    return best_score, best_doc


def find_subject_match(row: Dict[str, str], idx: HubIndex
                       ) -> Tuple[float, Optional[Dict[str, str]]]:
    sq_tokens = tokenize(row.get("square9_name", ""))
    if not sq_tokens:
        return 0.0, None
    best_score, best_doc = 0.0, None
    seen: Set[str] = set()
    for tok in sq_tokens:
        for cand in idx.by_subject_token.get(tok, ()):
            doc_id = cand["hub_doc_id"]
            if doc_id in seen:
                continue
            seen.add(doc_id)
            score = jaccard(sq_tokens, tokenize(cand["hub_email_subject"]))
            if score > best_score:
                best_score, best_doc = score, cand
    return best_score, best_doc


def vendor_present_in_hub(row: Dict[str, str], idx: HubIndex) -> bool:
    """Stricter than the prior audit: require vendor token overlap on
    BOTH the Square9 doc tokens AND something Hub registered as a
    vendor canonical / sender root (not just a stray filename token)."""
    sq_tokens = set(tokenize(_haystack(row)))
    if not sq_tokens:
        return False
    if sq_tokens & idx.vendor_tokens:
        return True
    if sq_tokens & idx.sender_domain_roots:
        return True
    return False


def classify_doc(row: Dict[str, str], idx: HubIndex) -> Dict[str, Any]:
    excl, excl_reason = is_scope_exclusion(row)
    if excl:
        return {
            "bucket": "square9_scope_exclusion",
            "confidence": 0.95,
            "best_hub": {},
            "reason": excl_reason,
            "match_signal": "scope_keyword",
        }

    haystack = _haystack(row)

    inv_hit = find_invoice_match(haystack, idx)
    if inv_hit:
        digits, hub = inv_hit
        return {
            "bucket": "recoverable_matcher_miss",
            "confidence": 0.95,
            "best_hub": hub,
            "reason": (f"Square9 doc has invoice digits {digits!r} that "
                       f"match Hub invoice_number_clean on "
                       f"hub_doc_id={hub['hub_doc_id']!r}"),
            "match_signal": "invoice_digits",
        }

    po_hit = find_po_match(haystack, idx)
    if po_hit:
        key, hub = po_hit
        return {
            "bucket": "recoverable_matcher_miss",
            "confidence": 0.85,
            "best_hub": hub,
            "reason": (f"Square9 doc has PO token {key!r} matching Hub "
                       f"po_number_clean on hub_doc_id={hub['hub_doc_id']!r}"),
            "match_signal": "po_token",
        }

    fname_score, fname_doc = find_filename_match(row, idx)
    if fname_score >= FILENAME_JACCARD_STRONG and fname_doc:
        return {
            "bucket": "recoverable_matcher_miss",
            "confidence": round(fname_score, 3),
            "best_hub": fname_doc,
            "reason": (f"filename token Jaccard={fname_score:.2f} >= "
                       f"{FILENAME_JACCARD_STRONG} against Hub "
                       f"hub_doc_id={fname_doc['hub_doc_id']!r}"),
            "match_signal": "filename_jaccard",
        }

    subj_score, subj_doc = find_subject_match(row, idx)
    if subj_score >= SUBJECT_JACCARD_STRONG and subj_doc:
        return {
            "bucket": "recoverable_matcher_miss",
            "confidence": round(subj_score, 3),
            "best_hub": subj_doc,
            "reason": (f"email_subject Jaccard={subj_score:.2f} >= "
                       f"{SUBJECT_JACCARD_STRONG} against Hub "
                       f"hub_doc_id={subj_doc['hub_doc_id']!r}"),
            "match_signal": "subject_jaccard",
        }

    amt_hit = find_amount_match(haystack, idx)
    if amt_hit and vendor_present_in_hub(row, idx):
        key, hub = amt_hit
        return {
            "bucket": "recoverable_matcher_miss",
            "confidence": 0.70,
            "best_hub": hub,
            "reason": (f"amount {key} appears in Square9 name and Hub "
                       f"corpus, with vendor token overlap"),
            "match_signal": "amount_plus_vendor",
        }

    if not vendor_present_in_hub(row, idx):
        return {
            "bucket": "true_intake_gap",
            "confidence": 0.85,
            "best_hub": {},
            "reason": ("no vendor_canonical or sender_domain_root in Hub "
                       "matches any Square9 token"),
            "match_signal": "no_vendor_overlap",
        }

    return {
        "bucket": "manual_review_required",
        "confidence": 0.40,
        "best_hub": {},
        "reason": ("vendor known to Hub but no invoice/PO/filename/"
                   "subject/amount evidence linking to a specific Hub "
                   "document"),
        "match_signal": "no_evidence",
    }


def classify_all(rows: List[Dict[str, str]], idx: HubIndex
                 ) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        verdict = classify_doc(r, idx)
        haystack = _haystack(r)
        invoice_tokens = extract_invoice_tokens(haystack)
        po_tokens = extract_po_tokens(haystack)
        vendor_tokens = sorted(
            set(tokenize(haystack)) & idx.vendor_tokens)
        hub = verdict["best_hub"] or {}
        out.append({
            "triage_bucket": verdict["bucket"],
            "confidence": verdict["confidence"],
            "recommended_action": BUCKET_TO_ACTION[verdict["bucket"]],
            "square9_name": r.get("square9_name", ""),
            "square9_parent_path": r.get("square9_parent_path", ""),
            "square9_modified": r.get("square9_modified", ""),
            "square9_web_url": r.get("square9_web_url", ""),
            "extracted_invoice_tokens": ",".join(invoice_tokens),
            "extracted_po_tokens": ",".join(po_tokens),
            "extracted_vendor_tokens": ",".join(vendor_tokens),
            "best_hub_doc_id": hub.get("hub_doc_id", ""),
            "best_hub_file_name": hub.get("hub_file_name", ""),
            "best_hub_mailbox_category": hub.get("hub_mailbox_category", ""),
            "best_hub_doc_type": hub.get("hub_doc_type", ""),
            "best_hub_suggested_job_type":
                hub.get("hub_suggested_job_type", ""),
            "best_hub_vendor_canonical":
                hub.get("hub_vendor_canonical", ""),
            "best_hub_invoice_number_clean":
                hub.get("hub_invoice_number_clean", ""),
            "best_hub_po_number_clean":
                hub.get("hub_po_number_clean", ""),
            "best_hub_amount_float": hub.get("hub_amount_float", ""),
            "best_hub_email_sender": hub.get("hub_email_sender", ""),
            "best_hub_email_subject": hub.get("hub_email_subject", ""),
            "best_match_reason": verdict["reason"],
            "notes": verdict.get("match_signal", ""),
        })
    return out


# ---------------------------------------------------------------------------
# Projection math
# ---------------------------------------------------------------------------

def project_match_rates(matched: int, square_count: int,
                        prior_recoverable: int, prior_excludable: int,
                        new_recoverable: int, new_excludable: int
                        ) -> Dict[str, float]:
    def _safe(num: int, denom: int) -> float:
        return (num / max(denom, 1)) * 100.0
    total_recoverable = prior_recoverable + new_recoverable
    total_excludable = prior_excludable + new_excludable
    return {
        "current": round(_safe(matched, square_count), 2),
        "after_recoverable_only": round(
            _safe(matched + total_recoverable, square_count), 2),
        "after_exclusions_only": round(
            _safe(matched, square_count - total_excludable), 2),
        "after_both": round(
            _safe(matched + total_recoverable,
                  square_count - total_excludable), 2),
    }


def decide_exit_code(after_both: float) -> int:
    if after_both >= GO_THRESHOLD:
        return EXIT_GO
    if after_both >= MIXED_THRESHOLD:
        return EXIT_MIXED
    return EXIT_NO_GO


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def _trim_for_top(rows: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    keep = ("triage_bucket", "confidence", "recommended_action",
            "square9_name", "square9_parent_path",
            "square9_web_url",
            "extracted_invoice_tokens", "extracted_po_tokens",
            "best_hub_doc_id", "best_hub_file_name",
            "best_hub_vendor_canonical", "best_hub_invoice_number_clean",
            "best_match_reason")
    return [{k: r.get(k) for k in keep} for r in rows[:n]]


def build_summary(classified: List[Dict[str, Any]],
                  *,
                  matched: int, square_count: int,
                  prior_recoverable: int, prior_excludable: int,
                  source_audit_csv: str, source_audit_json: str,
                  hub_doc_count: int,
                  top: int = 25) -> Dict[str, Any]:
    bc: Counter = Counter(c["triage_bucket"] for c in classified)
    R = bc.get("recoverable_matcher_miss", 0)
    E = bc.get("square9_scope_exclusion", 0) + bc.get("true_intake_gap", 0)
    M = bc.get("manual_review_required", 0)

    proj = project_match_rates(
        matched=matched, square_count=square_count,
        prior_recoverable=prior_recoverable,
        prior_excludable=prior_excludable,
        new_recoverable=R, new_excludable=E,
    )
    rc = decide_exit_code(proj["after_both"])

    by_bucket: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in classified:
        by_bucket[c["triage_bucket"]].append(c)

    parent_paths: Counter = Counter(
        c["square9_parent_path"] or "<unknown>" for c in classified)

    return {
        "source_audit_csv": source_audit_csv,
        "source_audit_json": source_audit_json,
        "hub_doc_count": hub_doc_count,
        "matched": matched,
        "square_count": square_count,
        "prior_recoverable_matcher_miss": prior_recoverable,
        "prior_excludable": prior_excludable,
        "total_uncertain": len(classified),
        "recoverable_matcher_miss_count": R,
        "square9_scope_exclusion_count":
            bc.get("square9_scope_exclusion", 0),
        "true_intake_gap_count": bc.get("true_intake_gap", 0),
        "manual_review_required_count": M,
        "bucket_counts": {b: bc.get(b, 0) for b in BUCKET_ORDER},
        "projected_match_rates": proj,
        "exit_code": rc,
        "top_recoverable":
            _trim_for_top(by_bucket["recoverable_matcher_miss"], top),
        "top_exclusions":
            _trim_for_top(by_bucket["square9_scope_exclusion"], top),
        "top_intake_gaps":
            _trim_for_top(by_bucket["true_intake_gap"], top),
        "top_manual_review":
            _trim_for_top(by_bucket["manual_review_required"], top),
        "top_parent_paths": parent_paths.most_common(top),
        "blockers": (
            [f"projected after_both={proj['after_both']}% "
             f"< {GO_THRESHOLD}% threshold"]
            if proj["after_both"] < GO_THRESHOLD else []
        ),
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

OUTPUT_CSV_COLUMNS = [
    "triage_bucket", "confidence", "recommended_action",
    "square9_name", "square9_parent_path", "square9_modified",
    "square9_web_url",
    "extracted_invoice_tokens", "extracted_po_tokens",
    "extracted_vendor_tokens",
    "best_hub_doc_id", "best_hub_file_name",
    "best_hub_mailbox_category", "best_hub_doc_type",
    "best_hub_suggested_job_type", "best_hub_vendor_canonical",
    "best_hub_invoice_number_clean", "best_hub_po_number_clean",
    "best_hub_amount_float", "best_hub_email_sender",
    "best_hub_email_subject", "best_match_reason", "notes",
]


def write_csv(path: str, classified: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_CSV_COLUMNS,
                           extrasaction="ignore")
        w.writeheader()
        for r in classified:
            w.writerow(r)


def write_json(path: str, summary: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, default=str, indent=2)


def write_md(path: str, summary: Dict[str, Any], top: int = 25) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    bc = summary["bucket_counts"]
    proj = summary["projected_match_rates"]
    total = summary["total_uncertain"]
    pct = lambda n: (n / total * 100.0) if total else 0.0  # noqa: E731

    lines: List[str] = []
    lines.append("# Square9 uncertain — deep triage")
    lines.append("")
    lines.append("## Executive summary")
    lines.append("")
    lines.append(f"- total uncertain considered: **{total}**")
    lines.append(f"- recoverable matcher miss: "
                 f"**{summary['recoverable_matcher_miss_count']}**")
    lines.append(f"- square9 scope exclusion: "
                 f"**{summary['square9_scope_exclusion_count']}**")
    lines.append(f"- true intake gap: "
                 f"**{summary['true_intake_gap_count']}**")
    lines.append(f"- manual review required: "
                 f"**{summary['manual_review_required_count']}**")
    lines.append(f"- exit_code: **{summary['exit_code']}**")
    lines.append("")
    lines.append("## Projected match rates")
    lines.append("")
    lines.append("| scenario | rate |")
    lines.append("| --- | ---: |")
    for k in ("current", "after_recoverable_only",
              "after_exclusions_only", "after_both"):
        lines.append(f"| {k} | {proj[k]:.2f}% |")
    lines.append("")
    lines.append("## Bucket counts")
    lines.append("")
    lines.append("| bucket | count | pct | recommended_action |")
    lines.append("| --- | ---: | ---: | --- |")
    for b in BUCKET_ORDER:
        n = bc.get(b, 0)
        lines.append(f"| {b} | {n} | {pct(n):.1f}% | {BUCKET_TO_ACTION[b]} |")
    lines.append("")

    def _table(title: str, rows: List[Dict[str, Any]]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        if not rows:
            lines.append("_no rows_")
            lines.append("")
            return
        lines.append(
            "| square9_name | square9_parent_path | "
            "best_hub_doc_id | best_hub_file_name | "
            "best_hub_vendor_canonical | best_match_reason |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for r in rows:
            lines.append(
                f"| {r.get('square9_name','')} "
                f"| {r.get('square9_parent_path','')} "
                f"| {r.get('best_hub_doc_id','')} "
                f"| {r.get('best_hub_file_name','')} "
                f"| {r.get('best_hub_vendor_canonical','')} "
                f"| {r.get('best_match_reason','')} |"
            )
        lines.append("")

    _table(f"Top {top} recoverable matcher misses",
           summary["top_recoverable"])
    _table(f"Top {top} square9 scope exclusions",
           summary["top_exclusions"])
    _table(f"Top {top} true intake gaps", summary["top_intake_gaps"])
    _table(f"Top {top} manual review rows",
           summary["top_manual_review"])

    lines.append("## Recommended next action")
    lines.append("")
    if proj["after_both"] >= GO_THRESHOLD:
        lines.append("- Wire the recoverable cohort into the matcher and "
                     "the exclusion cohort into the parity scope filter. "
                     "Re-run the proof pack. Cutover gate is achievable.")
    elif proj["after_both"] >= MIXED_THRESHOLD:
        lines.append("- Apply both cohorts and revisit the slip-decision "
                     "memo with the post-fix projection. The 85% gate is "
                     "still out of reach, but the gap is narrower.")
    else:
        lines.append("- The 85% gate remains unreachable from this data "
                     "alone. Hold the slip-decision memo recommendation "
                     "(Option A or B) and treat manual_review_required as "
                     "the next investigation cohort if cutover slips.")
    lines.append("")
    lines.append("_READ-ONLY triage. No DB writes, no cutover._")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Console renderer
# ---------------------------------------------------------------------------

def render_console(summary: Dict[str, Any],
                   csv_out: str, json_out: str, md_out: str) -> str:
    bc = summary["bucket_counts"]
    proj = summary["projected_match_rates"]
    total = summary["total_uncertain"]
    out: List[str] = []
    out.append("=" * 72)
    out.append(f" uncertain_square9_deep_triage — exit_code="
               f"{summary['exit_code']}")
    out.append("=" * 72)
    out.append(f"  source_audit_csv : {summary['source_audit_csv']}")
    out.append(f"  hub_doc_count    : {summary['hub_doc_count']}")
    out.append(f"  matched          : {summary['matched']}")
    out.append(f"  square_count     : {summary['square_count']}")
    out.append(f"  total_uncertain  : {total}")
    out.append(f"  prior_recoverable: {summary['prior_recoverable_matcher_miss']}")
    out.append(f"  prior_excludable : {summary['prior_excludable']}")
    out.append("")
    out.append("  bucket counts:")
    for b in BUCKET_ORDER:
        n = bc.get(b, 0)
        pct_v = (n / total * 100.0) if total else 0.0
        out.append(f"    {b:30s} {n:5d}  ({pct_v:5.1f}%)  -> "
                   f"{BUCKET_TO_ACTION[b]}")
    out.append("")
    out.append("  projected match rates:")
    for k in ("current", "after_recoverable_only",
              "after_exclusions_only", "after_both"):
        out.append(f"    {k:24s} {proj[k]:7.2f}%")
    out.append("")
    if summary["blockers"]:
        out.append("  BLOCKERS:")
        for b in summary["blockers"]:
            out.append(f"    - {b}")
        out.append("")
    out.append(f"  csv_out  : {csv_out}")
    out.append(f"  json_out : {json_out}")
    out.append(f"  md_out   : {md_out}")
    out.append("")
    out.append("  READ-ONLY triage. No DB writes, no cutover, "
               "no Square9 archive.")
    out.append("=" * 72)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Helpers for prior-audit ingest
# ---------------------------------------------------------------------------

def filter_uncertain_rows(audit_csv_rows: List[Dict[str, str]]
                          ) -> List[Dict[str, str]]:
    return [r for r in audit_csv_rows
            if (r.get("bucket") or "").strip() == "uncertain"]


def prior_counts_from_audit_json(payload: Dict[str, Any]
                                 ) -> Tuple[int, int, int, int]:
    bc = payload.get("bucket_counts") or {}
    matched = int(payload.get("matched") or 0)
    square_count = int(payload.get("square_count") or 0)
    prior_recoverable = int(bc.get("matcher_miss_with_hub_candidate") or 0)
    prior_excludable = (
        int(bc.get("non_ap_in_square9_corpus") or 0)
        + int(bc.get("pre_hub_corpus") or 0)
        + int(bc.get("vendor_not_in_hub_intake") or 0)
    )
    return matched, square_count, prior_recoverable, prior_excludable


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


def main() -> int:
    p = argparse.ArgumentParser(
        description="Read-only deep triage of Square9 uncertain cohort.")
    p.add_argument("--audit-csv",
                   default="prod_reports/no_match_square9_audit.csv")
    p.add_argument("--audit-json", default=DEFAULT_PRIOR_AUDIT_JSON)
    p.add_argument("--bucket", default="uncertain")
    p.add_argument("--limit", type=int, default=0,
                   help="0 = process all matching rows.")
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--out-csv",
                   default="prod_reports/uncertain_square9_deep_triage.csv")
    p.add_argument("--json",
                   default="prod_reports/uncertain_square9_deep_triage.json")
    p.add_argument("--md",
                   default="prod_reports/uncertain_square9_deep_triage.md")
    args = p.parse_args()

    if not os.path.exists(args.audit_csv):
        print(f"deep_triage: audit CSV not found at {args.audit_csv!r}.")
        return EXIT_NO_GO
    if not os.path.exists(args.audit_json):
        print(f"deep_triage: audit JSON not found at {args.audit_json!r}.")
        return EXIT_NO_GO

    audit_rows = read_csv_rows(args.audit_csv)
    audit_payload = read_json(args.audit_json)

    rows = [r for r in audit_rows
            if (r.get("bucket") or "").strip() == args.bucket]
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    coll = get_hub_documents_collection()
    idx = build_hub_index_from_mongo(coll)

    classified = classify_all(rows, idx)

    matched, square_count, prior_recoverable, prior_excludable = \
        prior_counts_from_audit_json(audit_payload)

    summary = build_summary(
        classified=classified,
        matched=matched, square_count=square_count,
        prior_recoverable=prior_recoverable,
        prior_excludable=prior_excludable,
        source_audit_csv=args.audit_csv,
        source_audit_json=args.audit_json,
        hub_doc_count=idx.doc_count,
        top=args.top,
    )

    write_csv(args.out_csv, classified)
    write_json(args.json, summary)
    write_md(args.md, summary, top=args.top)

    print(render_console(summary, args.out_csv, args.json, args.md))
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
