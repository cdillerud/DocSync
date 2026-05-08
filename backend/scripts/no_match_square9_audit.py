"""
no_match_square9_audit.py
=========================
READ-ONLY audit of the Square9-side ``no_match`` rows in the latest
parity CSV. Classifies each into one of five buckets and projects the
new ``match_rate_pct`` under three remediation strategies (exclude-only,
improve-only, both).

Buckets (priority order — earlier predicates take precedence):

  1. non_ap_in_square9_corpus
       Square9 doc's folder/name signal indicates a non-AP artifact
       (treasury, positive pay, ACH, wire, monthly rec, do-not-pay,
       PST archive, template, instructions, etc.).
       Action: exclude_from_square9_scope

  2. pre_hub_corpus
       Square9 doc's modified date predates ``--hub-corpus-start``.
       Action: exclude_from_square9_scope

  3. matcher_miss_with_hub_candidate
       Square9 doc has a likely Hub counterpart by invoice-number
       digit substring or filename-token Jaccard.
       Action: improve_matcher

  4. vendor_not_in_hub_intake
       Square9 doc's vendor tokens (extracted from name/parent_path)
       do not overlap with the Hub corpus's vendor_canonical or
       email_sender domain set.
       Action: intake_channel_investigation
       (effectively exclude_from_square9_scope for projection)

  5. uncertain
       Not enough evidence to classify.
       Action: manual_review

This script writes nothing to Mongo. The Mongo touch is a single
read-only ``find`` against ``hub_documents`` to build an in-memory
index of vendor / invoice / sender tokens; tests inject a synthetic
index directly.
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

HUB_CORPUS_START_DEFAULT = "2024-01-01T00:00:00+00:00"

# Folder / filename keywords that indicate the Square9 doc is NOT an AP
# invoice. Conservative — these strings are unambiguous in Square9's
# corpus.
NON_AP_NEEDLES = tuple(s.lower() for s in (
    "treasury",
    "positive pay",
    "positive_pay",
    "ach.csv",
    "wire.csv",
    " ach ",
    " wire ",
    "monthly rec",
    "reconciliation",
    "do not pay",
    "do_not_pay",
    "donotpay",
    "template",
    "templates",
    "instructions",
    "instruction.",
    "pst",
    ".pst",
    "wire transfer",
    "ach transfer",
    "bank statement",
    "bank_statement",
    "month end",
    "month-end",
    "stop pay",
    "stop_pay",
    "wire log",
))

# Strong identity threshold for "Hub probably has this".
INVOICE_DIGIT_MIN_LEN = 4
FILENAME_JACCARD_STRONG = 0.34

# Stop tokens for filename / vendor tokenization.
STOP_TOKENS = {
    "the", "and", "of", "for", "to", "by", "in", "on",
    "invoice", "inv", "doc", "docs", "ap", "pdf", "tif", "tiff",
    "png", "jpg", "jpeg", "scan", "scans", "scanned", "copy",
    "final", "draft", "page", "p", "pp",
}

EXIT_GO = 0
EXIT_MIXED = 1
EXIT_NO_GO = 2

GO_THRESHOLD = 0.85
MIXED_THRESHOLD = 0.70

ACTION_IMPROVE_MATCHER = "improve_matcher"
ACTION_EXCLUDE = "exclude_from_square9_scope"
ACTION_INTAKE_INVESTIGATION = "intake_channel_investigation"
ACTION_MANUAL_REVIEW = "manual_review"

BUCKET_TO_ACTION = {
    "non_ap_in_square9_corpus": ACTION_EXCLUDE,
    "pre_hub_corpus": ACTION_EXCLUDE,
    "matcher_miss_with_hub_candidate": ACTION_IMPROVE_MATCHER,
    "vendor_not_in_hub_intake": ACTION_INTAKE_INVESTIGATION,
    "uncertain": ACTION_MANUAL_REVIEW,
}

# Stable bucket ordering for output tables.
BUCKET_ORDER = (
    "non_ap_in_square9_corpus",
    "pre_hub_corpus",
    "matcher_miss_with_hub_candidate",
    "vendor_not_in_hub_intake",
    "uncertain",
)


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def find_latest_parity_csv(base_dir: str = "prod_reports") -> Optional[str]:
    candidates = sorted(
        glob.glob(os.path.join(
            base_dir, "cutover_proof_*", "square9_hub_ap_parity*.csv")),
        reverse=True,
    )
    if candidates:
        return candidates[0]
    fallback = os.path.join(base_dir, "square9_hub_ap_parity.csv")
    return fallback if os.path.exists(fallback) else None


def read_parity_rows(csv_path: str) -> List[Dict[str, str]]:
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Tokenization (pure)
# ---------------------------------------------------------------------------

_DIGIT_RE = re.compile(r"\D+")


def digits_only(s: str) -> str:
    if not s:
        return ""
    s = _DIGIT_RE.sub("", s)
    stripped = s.lstrip("0")
    return stripped or s


def tokenize(s: str) -> List[str]:
    if not s:
        return []
    norm = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return [t for t in norm.split() if t and t not in STOP_TOKENS]


def extract_invoice_token_candidates(text: str) -> List[str]:
    """Return all digit runs of length >= ``INVOICE_DIGIT_MIN_LEN`` from
    the text. These are the candidate invoice numbers for matching
    against the Hub invoice-number set."""
    if not text:
        return []
    runs = re.findall(r"\d+", text)
    return [r for r in runs if len(r) >= INVOICE_DIGIT_MIN_LEN]


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


def jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# ---------------------------------------------------------------------------
# Hub corpus index
# ---------------------------------------------------------------------------

class HubIndex:
    """Read-only index of hub_documents identity tokens.

    Built once per run from a single ``find`` projection — never
    queried again. Supplies membership / lookup helpers to the
    classifier."""

    __slots__ = ("vendor_tokens", "sender_domain_roots",
                 "invoice_digits", "filename_tokens",
                 "doc_count", "by_invoice_digits",
                 "by_filename_token")

    def __init__(self,
                 vendor_tokens: Set[str],
                 sender_domain_roots: Set[str],
                 invoice_digits: Set[str],
                 filename_tokens: Set[str],
                 doc_count: int,
                 by_invoice_digits: Optional[Dict[str, Dict[str, str]]] = None,
                 by_filename_token: Optional[Dict[str, List[Dict[str, str]]]] = None,
                 ):
        self.vendor_tokens = vendor_tokens
        self.sender_domain_roots = sender_domain_roots
        self.invoice_digits = invoice_digits
        self.filename_tokens = filename_tokens
        self.doc_count = doc_count
        self.by_invoice_digits = by_invoice_digits or {}
        self.by_filename_token = by_filename_token or {}


def build_hub_index_from_docs(hub_docs: Iterable[Dict[str, Any]]) -> HubIndex:
    vendor_tokens: Set[str] = set()
    sender_domain_roots: Set[str] = set()
    invoice_digits: Set[str] = set()
    filename_tokens: Set[str] = set()
    by_invoice_digits: Dict[str, Dict[str, str]] = {}
    by_filename_token: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    count = 0

    for d in hub_docs:
        count += 1
        for t in tokenize(d.get("vendor_canonical", "") or ""):
            vendor_tokens.add(t)
        sender = (d.get("email_sender", "") or "").lower()
        if "@" in sender:
            domain = sender.split("@", 1)[1].split(".")[0]
            if domain:
                sender_domain_roots.add(domain)
        inv = digits_only(d.get("invoice_number_clean", "") or "")
        if inv and len(inv) >= INVOICE_DIGIT_MIN_LEN:
            invoice_digits.add(inv)
            by_invoice_digits.setdefault(inv, {
                "hub_doc_id": d.get("id", "") or d.get("hub_doc_id", ""),
                "hub_file_name": d.get("file_name", ""),
                "hub_mailbox_category": d.get("mailbox_category", ""),
                "hub_doc_type": d.get("doc_type", ""),
                "hub_suggested_job_type": d.get("suggested_job_type", ""),
                "hub_created_utc": (d.get("created_utc", "") or
                                    d.get("created_at", "")),
            })
        for t in tokenize(d.get("file_name", "") or ""):
            filename_tokens.add(t)
            if len(by_filename_token[t]) < 10:
                by_filename_token[t].append({
                    "hub_doc_id": d.get("id", "") or d.get("hub_doc_id", ""),
                    "hub_file_name": d.get("file_name", ""),
                    "hub_mailbox_category": d.get("mailbox_category", ""),
                    "hub_doc_type": d.get("doc_type", ""),
                    "hub_suggested_job_type": d.get("suggested_job_type", ""),
                    "hub_created_utc": (d.get("created_utc", "") or
                                        d.get("created_at", "")),
                })
    return HubIndex(
        vendor_tokens=vendor_tokens,
        sender_domain_roots=sender_domain_roots,
        invoice_digits=invoice_digits,
        filename_tokens=filename_tokens,
        doc_count=count,
        by_invoice_digits=by_invoice_digits,
        by_filename_token=dict(by_filename_token),
    )


def build_hub_index_from_mongo(collection) -> HubIndex:
    """Single read-only ``find`` against ``hub_documents`` with a tight
    projection. No writes, no downstream Mongo touch."""
    cursor = collection.find(
        {},
        {
            "_id": 0,
            "id": 1,
            "vendor_canonical": 1,
            "email_sender": 1,
            "invoice_number_clean": 1,
            "file_name": 1,
            "mailbox_category": 1,
            "doc_type": 1,
            "suggested_job_type": 1,
            "created_utc": 1,
            "created_at": 1,
        },
    )
    return build_hub_index_from_docs(cursor)


# ---------------------------------------------------------------------------
# Classification (pure)
# ---------------------------------------------------------------------------

def _haystack_for(row: Dict[str, str]) -> str:
    return " ".join((
        row.get("square9_name") or "",
        row.get("square9_parent_path") or "",
        row.get("square9_web_url") or "",
    ))


def is_non_ap_signal(row: Dict[str, str]) -> bool:
    haystack = _haystack_for(row).lower()
    if not haystack:
        return False
    return any(needle in haystack for needle in NON_AP_NEEDLES)


def is_pre_hub_corpus(row: Dict[str, str],
                      hub_corpus_start: dt.datetime) -> bool:
    modified = parse_iso_utc(row.get("square9_modified", ""))
    if modified is None:
        return False
    return modified < hub_corpus_start


def find_hub_invoice_match(row: Dict[str, str],
                           index: HubIndex
                           ) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    """Look at digit runs in Square9 name+parent_path. Return the first
    one that is a member of the Hub invoice-digit set + the Hub doc
    record from by_invoice_digits."""
    for tok in extract_invoice_token_candidates(_haystack_for(row)):
        digits = digits_only(tok)
        if digits and digits in index.invoice_digits:
            return digits, index.by_invoice_digits.get(digits)
    return None, None


def find_hub_filename_match(row: Dict[str, str],
                            index: HubIndex
                            ) -> Tuple[float, Optional[Dict[str, str]]]:
    """Pick the Hub doc whose filename has the strongest token-overlap
    with Square9's name. Returns (score, hub_doc_record)."""
    sq_tokens = tokenize(row.get("square9_name", ""))
    if not sq_tokens:
        return 0.0, None
    best_score = 0.0
    best_doc: Optional[Dict[str, str]] = None
    for tok in sq_tokens:
        for cand in index.by_filename_token.get(tok, ()):
            cand_tokens = tokenize(cand.get("hub_file_name", ""))
            score = jaccard(sq_tokens, cand_tokens)
            if score > best_score:
                best_score = score
                best_doc = cand
    return best_score, best_doc


def vendor_overlaps_hub(row: Dict[str, str], index: HubIndex) -> bool:
    sq_tokens = set(tokenize(_haystack_for(row)))
    if not sq_tokens:
        return False
    if sq_tokens & index.vendor_tokens:
        return True
    if sq_tokens & index.sender_domain_roots:
        return True
    return False


def classify_doc(row: Dict[str, str],
                 *,
                 hub_corpus_start: dt.datetime,
                 index: HubIndex,
                 ) -> Dict[str, Any]:
    if is_non_ap_signal(row):
        return {
            "bucket": "non_ap_in_square9_corpus",
            "reason": "folder/name keyword indicates non-AP artifact",
            "best_match_score": 0.0,
        }

    if is_pre_hub_corpus(row, hub_corpus_start):
        return {
            "bucket": "pre_hub_corpus",
            "reason": (f"square9_modified={row.get('square9_modified')!r} "
                       f"predates hub_corpus_start "
                       f"{hub_corpus_start.isoformat()}"),
            "best_match_score": 0.0,
        }

    inv_digits, hub_inv_doc = find_hub_invoice_match(row, index)
    if inv_digits and hub_inv_doc:
        return {
            "bucket": "matcher_miss_with_hub_candidate",
            "reason": (f"invoice digits {inv_digits!r} present in Hub "
                       f"hub_doc_id={hub_inv_doc.get('hub_doc_id')!r}"),
            "best_match_score": 0.95,
            "best_hub_doc": hub_inv_doc,
            "match_signal": "invoice_digits",
        }

    fname_score, fname_doc = find_hub_filename_match(row, index)
    if fname_score >= FILENAME_JACCARD_STRONG and fname_doc:
        return {
            "bucket": "matcher_miss_with_hub_candidate",
            "reason": (f"filename token Jaccard={fname_score:.2f} >= "
                       f"{FILENAME_JACCARD_STRONG} against Hub "
                       f"hub_doc_id={fname_doc.get('hub_doc_id')!r}"),
            "best_match_score": round(fname_score, 3),
            "best_hub_doc": fname_doc,
            "match_signal": "filename_token_overlap",
        }

    if not vendor_overlaps_hub(row, index):
        return {
            "bucket": "vendor_not_in_hub_intake",
            "reason": ("Square9 vendor/sender tokens do not overlap any "
                       "Hub vendor_canonical or email_sender domain"),
            "best_match_score": 0.0,
        }

    return {
        "bucket": "uncertain",
        "reason": ("AP-shaped, after hub_corpus_start, vendor known to "
                   "Hub, but no invoice/filename evidence of a "
                   "counterpart"),
        "best_match_score": round(fname_score, 3) if fname_score else 0.0,
    }


def classify_all(rows: List[Dict[str, str]],
                 *,
                 hub_corpus_start: dt.datetime,
                 index: HubIndex,
                 ) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        verdict = classify_doc(r, hub_corpus_start=hub_corpus_start,
                               index=index)
        haystack = _haystack_for(r)
        invoice_tokens = extract_invoice_token_candidates(haystack)
        vendor_tokens = sorted(set(tokenize(haystack)) & index.vendor_tokens)
        hub_doc = verdict.get("best_hub_doc") or {}
        out.append({
            "bucket": verdict["bucket"],
            "recommended_action": BUCKET_TO_ACTION[verdict["bucket"]],
            "square9_name": r.get("square9_name", ""),
            "square9_parent_path": r.get("square9_parent_path", ""),
            "square9_modified": r.get("square9_modified", ""),
            "extracted_invoice_tokens": ",".join(invoice_tokens),
            "extracted_vendor_tokens": ",".join(vendor_tokens),
            "best_hub_doc_id": hub_doc.get("hub_doc_id", ""),
            "best_hub_file_name": hub_doc.get("hub_file_name", ""),
            "best_hub_mailbox_category": hub_doc.get(
                "hub_mailbox_category", ""),
            "best_hub_doc_type": hub_doc.get("hub_doc_type", ""),
            "best_hub_suggested_job_type": hub_doc.get(
                "hub_suggested_job_type", ""),
            "best_hub_created_utc": hub_doc.get("hub_created_utc", ""),
            "best_match_score": verdict.get("best_match_score", 0.0),
            "best_match_reason": verdict["reason"],
            "notes": verdict.get("match_signal", ""),
        })
    return out


# ---------------------------------------------------------------------------
# Match-rate projections
# ---------------------------------------------------------------------------

def count_matched_in_parity(parity_rows: List[Dict[str, str]]) -> int:
    matched_buckets = {"exact_match", "strong_evidence_match",
                       "likely_match", "possible_match"}
    return sum(1 for r in parity_rows
               if (r.get("match_bucket") or "").strip() in matched_buckets)


def project_match_rates(matched: int,
                        square_count: int,
                        recoverable: int,
                        excludable: int) -> Dict[str, float]:
    def _safe(num: int, denom: int) -> float:
        denom = max(denom, 1)
        return (num / denom) * 100.0

    return {
        "baseline": round(_safe(matched, square_count), 2),
        "after_exclude_only": round(
            _safe(matched, square_count - excludable), 2),
        "after_improve_only": round(
            _safe(matched + recoverable, square_count), 2),
        "after_both": round(
            _safe(matched + recoverable, square_count - excludable), 2),
    }


def decide_exit_code(projections: Dict[str, float]) -> int:
    after_both = projections.get("after_both", 0.0)
    if after_both >= GO_THRESHOLD * 100:
        return EXIT_GO
    if after_both >= MIXED_THRESHOLD * 100:
        return EXIT_MIXED
    return EXIT_NO_GO


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def build_summary(parity_rows: List[Dict[str, str]],
                  classified: List[Dict[str, Any]],
                  hub_corpus_start: dt.datetime,
                  hub_doc_count: int,
                  source_csv: str,
                  top: int = 25,
                  ) -> Dict[str, Any]:
    matched = count_matched_in_parity(parity_rows)
    no_match_count = len(classified)
    square_count = matched + no_match_count

    bucket_counts: Counter = Counter(c["bucket"] for c in classified)
    action_counts: Counter = Counter(
        c["recommended_action"] for c in classified)

    excludable = (
        bucket_counts.get("non_ap_in_square9_corpus", 0)
        + bucket_counts.get("pre_hub_corpus", 0)
        + bucket_counts.get("vendor_not_in_hub_intake", 0)
    )
    recoverable = bucket_counts.get("matcher_miss_with_hub_candidate", 0)

    projections = project_match_rates(
        matched=matched,
        square_count=square_count,
        recoverable=recoverable,
        excludable=excludable,
    )
    exit_code = decide_exit_code(projections)

    blockers: List[str] = []
    warnings: List[str] = []
    if no_match_count == 0:
        warnings.append("zero no_match rows in parity CSV")
    if hub_doc_count == 0:
        warnings.append("hub_documents corpus empty; classification "
                        "may be conservative")
    if projections["after_both"] < GO_THRESHOLD * 100:
        blockers.append(
            f"projected after_both={projections['after_both']}% "
            f"< {GO_THRESHOLD * 100}% threshold")

    parent_paths: Counter = Counter(
        c["square9_parent_path"] or "<unknown>" for c in classified)

    top_examples: Dict[str, List[Dict[str, Any]]] = {}
    for b in BUCKET_ORDER:
        sample = [c for c in classified if c["bucket"] == b][:top]
        top_examples[b] = sample

    return {
        "source_csv": source_csv,
        "hub_corpus_start": hub_corpus_start.isoformat(),
        "hub_doc_count": hub_doc_count,
        "matched": matched,
        "square_count": square_count,
        "no_match_count": no_match_count,
        "excludable": excludable,
        "recoverable_matcher_miss_count": recoverable,
        "total_no_match": no_match_count,
        "bucket_counts": {b: bucket_counts.get(b, 0) for b in BUCKET_ORDER},
        "recommended_action_counts": dict(action_counts),
        "projected_match_rates": projections,
        "exit_code": exit_code,
        "top_examples_by_bucket": top_examples,
        "top_square9_parent_paths": parent_paths.most_common(top),
        "blockers": blockers,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

OUTPUT_CSV_COLUMNS = [
    "bucket", "recommended_action",
    "square9_name", "square9_parent_path", "square9_modified",
    "extracted_invoice_tokens", "extracted_vendor_tokens",
    "best_hub_doc_id", "best_hub_file_name",
    "best_hub_mailbox_category", "best_hub_doc_type",
    "best_hub_suggested_job_type", "best_hub_created_utc",
    "best_match_score", "best_match_reason", "notes",
]


def write_csv(path: str, classified: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_CSV_COLUMNS,
                           extrasaction="ignore")
        w.writeheader()
        for r in classified:
            w.writerow(r)


def _trim_examples(examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keep = ("bucket", "recommended_action", "square9_name",
            "square9_parent_path", "square9_modified",
            "extracted_invoice_tokens", "extracted_vendor_tokens",
            "best_hub_doc_id", "best_hub_file_name",
            "best_match_score", "best_match_reason")
    return [{k: e.get(k) for k in keep} for e in examples]


def write_json(path: str, summary: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = dict(summary)
    payload["top_examples_by_bucket"] = {
        b: _trim_examples(payload["top_examples_by_bucket"].get(b, []))
        for b in BUCKET_ORDER
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, default=str, indent=2)


def write_md(path: str, summary: Dict[str, Any], top: int = 25) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    bc = summary["bucket_counts"]
    proj = summary["projected_match_rates"]
    total = summary["total_no_match"]
    pct = lambda n: (n / total * 100.0) if total else 0.0  # noqa: E731

    lines: List[str] = []
    lines.append("# Square9-side no_match audit")
    lines.append("")
    lines.append(f"- source_csv: `{summary['source_csv']}`")
    lines.append(f"- hub_corpus_start: `{summary['hub_corpus_start']}`")
    lines.append(f"- hub_doc_count: **{summary['hub_doc_count']}**")
    lines.append(f"- matched: **{summary['matched']}**")
    lines.append(f"- square_count: **{summary['square_count']}**")
    lines.append(f"- no_match_count: **{summary['no_match_count']}**")
    lines.append(f"- excludable: **{summary['excludable']}**")
    lines.append(f"- recoverable_matcher_miss_count: "
                 f"**{summary['recoverable_matcher_miss_count']}**")
    lines.append(f"- exit_code: **{summary['exit_code']}**")
    lines.append("")
    lines.append("## Bucket counts")
    lines.append("")
    lines.append("| bucket | count | pct | recommended_action |")
    lines.append("| --- | ---: | ---: | --- |")
    for b in BUCKET_ORDER:
        n = bc.get(b, 0)
        lines.append(f"| {b} | {n} | {pct(n):.1f}% | {BUCKET_TO_ACTION[b]} |")
    lines.append("")
    lines.append("## Projected match rates")
    lines.append("")
    lines.append("| scenario | match_rate_pct |")
    lines.append("| --- | ---: |")
    for k in ("baseline", "after_exclude_only", "after_improve_only",
              "after_both"):
        lines.append(f"| {k} | {proj[k]:.2f}% |")
    lines.append("")

    def _table(title: str, rows: List[Dict[str, Any]]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        if not rows:
            lines.append("_no rows_")
            lines.append("")
            return
        lines.append("| square9_name | square9_parent_path | "
                     "best_hub_doc_id | best_hub_file_name | "
                     "best_match_score | best_match_reason |")
        lines.append("| --- | --- | --- | --- | ---: | --- |")
        for r in rows[:top]:
            lines.append(
                f"| {r.get('square9_name','')} "
                f"| {r.get('square9_parent_path','')} "
                f"| {r.get('best_hub_doc_id','')} "
                f"| {r.get('best_hub_file_name','')} "
                f"| {r.get('best_match_score', 0)} "
                f"| {r.get('best_match_reason','')} |"
            )
        lines.append("")

    _table(f"Top {top} matcher misses",
           summary["top_examples_by_bucket"]
           .get("matcher_miss_with_hub_candidate", []))
    _table(f"Top {top} scope exclusions (non-AP)",
           summary["top_examples_by_bucket"]
           .get("non_ap_in_square9_corpus", []))
    _table(f"Top {top} pre-hub-corpus rows",
           summary["top_examples_by_bucket"].get("pre_hub_corpus", []))
    _table(f"Top {top} vendor-not-in-hub-intake rows",
           summary["top_examples_by_bucket"]
           .get("vendor_not_in_hub_intake", []))
    _table(f"Top {top} uncertain rows",
           summary["top_examples_by_bucket"].get("uncertain", []))

    lines.append("## Recommended next actions")
    lines.append("")
    if summary["bucket_counts"].get("matcher_miss_with_hub_candidate", 0) > 0:
        lines.append("- Improve matcher to convert the "
                     "matcher_miss_with_hub_candidate rows.")
    if summary["bucket_counts"].get("non_ap_in_square9_corpus", 0) > 0:
        lines.append("- Add Square9-side scope filter to drop the "
                     "non_ap_in_square9_corpus rows.")
    if summary["bucket_counts"].get("pre_hub_corpus", 0) > 0:
        lines.append("- Bound parity by hub_corpus_start to drop the "
                     "pre_hub_corpus rows.")
    if summary["bucket_counts"].get("vendor_not_in_hub_intake", 0) > 0:
        lines.append("- Investigate intake channel for "
                     "vendor_not_in_hub_intake rows or exclude.")
    lines.append("")
    lines.append("_READ-ONLY audit. No DB writes, no cutover, "
                 "no Square9 archive._")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Console renderer
# ---------------------------------------------------------------------------

def render_console(summary: Dict[str, Any],
                   csv_out: str, json_out: str, md_out: str) -> str:
    bc = summary["bucket_counts"]
    proj = summary["projected_match_rates"]
    total = summary["total_no_match"]
    out: List[str] = []
    out.append("=" * 72)
    out.append(f" no_match_square9_audit — exit_code={summary['exit_code']}")
    out.append("=" * 72)
    out.append(f"  source_csv      : {summary['source_csv']}")
    out.append(f"  hub_corpus_start: {summary['hub_corpus_start']}")
    out.append(f"  hub_doc_count   : {summary['hub_doc_count']}")
    out.append(f"  matched         : {summary['matched']}")
    out.append(f"  square_count    : {summary['square_count']}")
    out.append(f"  no_match_count  : {summary['no_match_count']}")
    out.append(f"  excludable      : {summary['excludable']}")
    out.append(f"  recoverable     : {summary['recoverable_matcher_miss_count']}")
    out.append("")
    out.append("  bucket counts:")
    for b in BUCKET_ORDER:
        n = bc.get(b, 0)
        pct = (n / total * 100.0) if total else 0.0
        out.append(f"    {b:36s} {n:5d}  ({pct:5.1f}%)  -> "
                   f"{BUCKET_TO_ACTION[b]}")
    out.append("")
    out.append("  projected match rates:")
    for k in ("baseline", "after_exclude_only", "after_improve_only",
              "after_both"):
        out.append(f"    {k:24s} {proj[k]:7.2f}%")
    out.append("")
    if summary["blockers"]:
        out.append("  BLOCKERS:")
        for b in summary["blockers"]:
            out.append(f"    - {b}")
        out.append("")
    if summary["warnings"]:
        out.append("  warnings:")
        for w in summary["warnings"]:
            out.append(f"    - {w}")
        out.append("")
    out.append(f"  csv_out  : {csv_out}")
    out.append(f"  json_out : {json_out}")
    out.append(f"  md_out   : {md_out}")
    out.append("")
    out.append("  READ-ONLY audit. No DB writes, no cutover, "
               "no Square9 archive.")
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


def main() -> int:
    p = argparse.ArgumentParser(
        description="Read-only Square9-side no_match audit.")
    p.add_argument("--parity-csv", default=None)
    p.add_argument("--hub-corpus-start", default=HUB_CORPUS_START_DEFAULT)
    p.add_argument("--out-csv",
                   default="prod_reports/no_match_square9_audit.csv")
    p.add_argument("--json",
                   default="prod_reports/no_match_square9_audit.json")
    p.add_argument("--md",
                   default="prod_reports/no_match_square9_audit.md")
    p.add_argument("--top", type=int, default=25)
    args = p.parse_args()

    csv_path = args.parity_csv or find_latest_parity_csv()
    if not csv_path or not os.path.exists(csv_path):
        print("no_match_square9_audit: no parity CSV found.")
        return EXIT_NO_GO

    hub_corpus_start = parse_iso_utc(args.hub_corpus_start)
    if hub_corpus_start is None:
        raise SystemExit(
            f"--hub-corpus-start {args.hub_corpus_start!r} is not ISO-8601")

    parity_rows = read_parity_rows(csv_path)
    no_match_rows = [r for r in parity_rows
                     if (r.get("match_bucket") or "").strip() == "no_match"]

    coll = get_hub_documents_collection()
    index = build_hub_index_from_mongo(coll)

    classified = classify_all(no_match_rows,
                              hub_corpus_start=hub_corpus_start,
                              index=index)
    summary = build_summary(parity_rows=parity_rows,
                            classified=classified,
                            hub_corpus_start=hub_corpus_start,
                            hub_doc_count=index.doc_count,
                            source_csv=csv_path,
                            top=args.top)

    write_csv(args.out_csv, classified)
    write_json(args.json, summary)
    write_md(args.md, summary, top=args.top)

    print(render_console(summary, args.out_csv, args.json, args.md))
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
