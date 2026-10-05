"""
square9_hub_ap_parity_report.py
================================
P0 cutover proof: compare Square9's AP intake folder against actual GPI Hub
AP-lane documents (regardless of final destination folder).

The earlier `sharepoint_ap_compare.py --graph-pull` tool compares Square9's
`Accounts Payable/Temp Folder` against a single Hub folder
(`AP_Invoices`). That assumption is invalid now that the Hub is
evidence-routing AP docs into final destinations (Freight Issues,
Dropship Not International Documents, Vendor Credit Memos, etc.). This
report does NOT make that assumption — it reads the Hub side directly
from `hub_documents` where `mailbox_category == "AP"` and matches by
multiple evidence axes (filename, invoice number, vendor, amount,
date).

Read-only:
  - reads SharePoint via Graph (Sites.Read.All)
  - reads MongoDB hub_documents and mail_poll_runs
  - writes one CSV (operator-supplied --out-csv) and stdout

Operator example
----------------

    python -m scripts.square9_hub_ap_parity_report \\
        --since-hours 24 --limit 500 --top 25 \\
        --out-csv prod_reports/square9_hub_ap_parity.csv

JSON mode (machine-readable summary + findings on stdout) is also
available with `--json`. Exit code is non-zero when blockers fire.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

# 2026-09-28: bucket_C_intake_gap_report.py already has a live-tested,
# business-confirmed list of "this is a reference file/report/internal
# doc, not a real vendor invoice, and was never capturable by Hub's email
# intake" patterns (see that file's NOT_HUB_EXPECTED_PATTERNS). It has
# always been informational-only: bucket_C recommends
# "exclude_from_parity_denominator" for these documents, but nothing
# actually removed them from THIS script's own square_count/match_rate_pct
# -- the number the GO/NO-GO cutover decision is based on. They were
# silently counted as "no_match" (real gaps) instead. Importing the same
# pattern list here and excluding matches before scoring fixes that.
from bucket_C_intake_gap_report import NOT_HUB_EXPECTED_PATTERNS

# Reuse normalization / Graph-pull helpers from the sibling script. This is
# intentional — we want IDENTICAL filename normalization on both sides so
# bucket counts are directly comparable to the prior tool.
#
# Make the import work whether this script is invoked as
#   python -m scripts.square9_hub_ap_parity_report
# (sys.path includes the parent of `scripts/`) or as
#   python /app/scripts/square9_hub_ap_parity_report.py
# (sys.path only includes /app/scripts).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_THIS_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

try:
    from scripts.sharepoint_ap_compare import (  # type: ignore
        Doc as SquareDoc,
        acquire_graph_token,
        extract_invoice_po_tokens,
        extract_vendor_tokens,
        normalize_name,
        parse_modified,
        pull_listing_via_graph,
        PROD_DEFAULT_FOLDER_PATH,
        PROD_DEFAULT_LIBRARY,
        PROD_DEFAULT_SITE_PATH,
    )
except ModuleNotFoundError:  # invoked by absolute path; sibling import
    from sharepoint_ap_compare import (  # type: ignore
        Doc as SquareDoc,
        acquire_graph_token,
        extract_invoice_po_tokens,
        extract_vendor_tokens,
        normalize_name,
        parse_modified,
        pull_listing_via_graph,
        PROD_DEFAULT_FOLDER_PATH,
        PROD_DEFAULT_LIBRARY,
        PROD_DEFAULT_SITE_PATH,
    )


# ---------------------------------------------------------------------------
# Bucket model
# ---------------------------------------------------------------------------

# Strongest bucket wins on tie-break; higher value = stronger.
BUCKET_ORDER: Dict[str, int] = {
    "exact_match": 5,
    "strong_evidence_match": 4,
    "likely_match": 3,
    "possible_match": 2,
    "no_match": 1,
}

FORBIDDEN_HUB_FOLDER_ROOTS = {
    # Operations is the catch-all for non-AP. AP docs landing under one of
    # these is a routing bug. Match on the FIRST path segment.
    "operations",
    "general operations",
    "warehouse documents",
}

LEGACY_CLASSIFICATION_PREFIXES = (
    "legacy",
    "fallback",
    "rule:legacy",
)


# ---------------------------------------------------------------------------
# Filename invoice-date extraction (used in --match-by-invoice-date mode)
# ---------------------------------------------------------------------------

# Order matters: ISO YYYY-MM-DD checked first, then US MM-DD-YYYY, then 8-digit
# YYYYMMDD. Each capture group must yield a parseable (Y, M, D) triple.
_FILENAME_DATE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # 2026-04-15 / 2026_04_15 / 2026.04.15 / 2026/04/15
    (re.compile(r"(?<!\d)(20\d{2})[-_./](0[1-9]|1[0-2])[-_./](0[1-9]|[12]\d|3[01])(?!\d)"), "ymd"),
    # 04-15-2026 / 04/15/2026
    (re.compile(r"(?<!\d)(0[1-9]|1[0-2])[-_./](0[1-9]|[12]\d|3[01])[-_./](20\d{2})(?!\d)"), "mdy"),
    # 20260415 (compact, no separators)
    (re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)"), "ymd"),
]


def extract_date_from_filename(name: str) -> Optional[datetime]:
    """Parse an invoice/document date out of a filename.

    Returns None if no recognizable date is present. Best-effort, conservative —
    returns the first match, anchored to UTC midnight. Used as supporting
    evidence for invoice-document-set parity matching.
    """
    if not name:
        return None
    base = name.rsplit(".", 1)[0] if "." in name else name
    for pat, kind in _FILENAME_DATE_PATTERNS:
        m = pat.search(base)
        if not m:
            continue
        g = m.groups()
        try:
            if kind == "ymd":
                y, mo, d = int(g[0]), int(g[1]), int(g[2])
            else:  # mdy
                mo, d, y = int(g[0]), int(g[1]), int(g[2])
            if 2018 <= y <= 2035 and 1 <= mo <= 12 and 1 <= d <= 31:
                return datetime(y, mo, d, tzinfo=timezone.utc)
        except (ValueError, IndexError):
            continue
    return None


def square_invoice_date(sq: "SquareDoc") -> Optional[datetime]:
    """Inferred invoice date for a Square9 doc — filename token first, fallback
    to SharePoint modified time. Used only in --match-by-invoice-date mode."""
    return extract_date_from_filename(sq.name) or sq.modified


def _invoice_dates_close(a: Optional[datetime], b: Optional[datetime],
                         tol_days: int) -> bool:
    if a is None or b is None:
        return False
    return abs((a - b).total_seconds()) <= tol_days * 86400


# ---------------------------------------------------------------------------
# Hub-side document model
# ---------------------------------------------------------------------------



@dataclass
class HubDoc:
    raw: Dict[str, Any]
    doc_id: str
    file_name: str
    sharepoint_web_url: str
    sharepoint_folder_path: str
    routing_status: str
    routing_reason: str
    doc_type: str
    suggested_job_type: str
    classification_method: str
    vendor_canonical: str
    invoice_number_clean: str
    amount_float: Optional[float]
    po_number_clean: str
    created_utc: Optional[datetime]
    email_subject: str
    email_sender: str
    invoice_date: Optional[datetime] = None
    norm_name: str = ""
    inv_po_tokens: List[str] = field(default_factory=list)
    vendor_tokens: List[str] = field(default_factory=list)

    @classmethod
    def from_mongo(cls, d: Dict[str, Any]) -> "HubDoc":
        # Defensive: fields can be absent or null in legacy rows.
        amount = d.get("amount_float")
        try:
            amount = float(amount) if amount not in (None, "") else None
        except (TypeError, ValueError):
            amount = None

        created = d.get("created_utc")
        if isinstance(created, str):
            created_dt = parse_modified(created)
        elif isinstance(created, datetime):
            created_dt = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
        else:
            created_dt = None

        # Invoice date: prefer extracted_fields.invoice_date, fall back to
        # top-level invoice_date. Either may be ISO string, "YYYY-MM-DD", or
        # missing. Used only when --match-by-invoice-date is enabled.
        inv_date_raw: Any = None
        ef = d.get("extracted_fields")
        if isinstance(ef, dict):
            inv_date_raw = ef.get("invoice_date") or ef.get("inv_date")
        if not inv_date_raw:
            inv_date_raw = d.get("invoice_date")
        invoice_dt: Optional[datetime] = None
        if isinstance(inv_date_raw, datetime):
            invoice_dt = (
                inv_date_raw if inv_date_raw.tzinfo
                else inv_date_raw.replace(tzinfo=timezone.utc)
            )
        elif isinstance(inv_date_raw, str) and inv_date_raw.strip():
            invoice_dt = parse_modified(inv_date_raw.strip())

        name = (d.get("file_name") or "").strip()
        return cls(
            raw=d,
            doc_id=str(d.get("id") or d.get("doc_id") or "")[:64],
            file_name=name,
            sharepoint_web_url=(d.get("sharepoint_web_url") or "").strip(),
            sharepoint_folder_path=(d.get("sharepoint_folder_path") or "").strip(),
            routing_status=(d.get("routing_status") or "").strip(),
            routing_reason=(d.get("folder_routing_reason") or d.get("routing_reason") or "").strip(),
            doc_type=(d.get("doc_type") or "").strip(),
            suggested_job_type=(d.get("suggested_job_type") or "").strip(),
            classification_method=(d.get("classification_method") or "").strip(),
            vendor_canonical=(d.get("vendor_canonical") or "").strip(),
            invoice_number_clean=(d.get("invoice_number_clean") or "").strip(),
            amount_float=amount,
            po_number_clean=(d.get("po_number_clean") or "").strip(),
            created_utc=created_dt,
            email_subject=(d.get("email_subject") or "").strip(),
            email_sender=(d.get("email_sender") or "").strip(),
            invoice_date=invoice_dt,
            norm_name=normalize_name(name),
            inv_po_tokens=extract_invoice_po_tokens(name) + (
                [d["invoice_number_clean"].upper().lstrip("0")]
                if d.get("invoice_number_clean") else []
            ),
            vendor_tokens=extract_vendor_tokens(name) + (
                [t.lower() for t in (d.get("vendor_canonical") or "").split() if len(t) >= 3]
            ),
        )


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

@dataclass
class MatchResult:
    bucket: str
    score: float                    # 0.0 .. 1.0
    reason: str
    breakdown: Dict[str, Any] = field(default_factory=dict)


def _amount_close(a: Optional[float], b: Optional[float], tol: float = 0.02) -> bool:
    if a is None or b is None:
        return False
    if a == b:
        return True
    if max(abs(a), abs(b)) == 0:
        return False
    return abs(a - b) / max(abs(a), abs(b)) <= tol


def _date_close_days(a: Optional[datetime], b: Optional[datetime], days: int) -> bool:
    if a is None or b is None:
        return False
    return abs((a - b).total_seconds()) <= days * 86400


def score_pair(sq: SquareDoc, hub: HubDoc,
               invoice_date_tolerance_days: Optional[int] = None) -> MatchResult:
    """Layered evidence-based matching between a Square9 doc and a Hub doc.

    When `invoice_date_tolerance_days` is set (i.e. --match-by-invoice-date
    mode), the matcher ALSO accepts invoice-date proximity as supporting
    evidence — Hub uses `extracted_fields.invoice_date` (fallback
    `created_utc`), Square9 uses filename-extracted date (fallback
    SharePoint `modified`). Date proximity is supporting evidence only,
    never a sole match key.
    """
    bd: Dict[str, Any] = {}
    sq_norm = sq.norm_name
    hub_norm = hub.norm_name
    sq_inv = set(sq.inv_po_tokens)
    hub_inv = set(hub.inv_po_tokens)
    sq_vendors = set(sq.vendor_tokens)
    hub_vendors = set(hub.vendor_tokens)

    # Pre-compute date proximity once for the invoice-date mode.
    invoice_date_close = False
    if invoice_date_tolerance_days is not None:
        sq_inv_date = extract_date_from_filename(sq.name) or sq.modified
        hub_inv_date = hub.invoice_date or hub.created_utc
        invoice_date_close = _invoice_dates_close(
            sq_inv_date, hub_inv_date, invoice_date_tolerance_days
        )
        bd["invoice_date_close"] = invoice_date_close
        if sq_inv_date:
            bd["sq_invoice_date"] = sq_inv_date.isoformat()
        if hub_inv_date:
            bd["hub_invoice_date"] = hub_inv_date.isoformat()

    # 1. Exact normalized filename
    if sq_norm and sq_norm == hub_norm:
        return MatchResult(
            "exact_match", 1.0, "filename_exact",
            {**bd, "sq_norm_name": sq_norm}
        )

    # 2. Strong evidence: invoice number match + (vendor match OR amount match)
    inv_overlap = sq_inv & hub_inv
    bd["inv_overlap"] = sorted(inv_overlap)
    bd["vendor_overlap"] = sorted(sq_vendors & hub_vendors)

    if inv_overlap:
        if hub.invoice_number_clean and any(
            t.upper().lstrip("0") == hub.invoice_number_clean.upper().lstrip("0")
            for t in inv_overlap
        ):
            # Hub explicitly extracted this invoice number AND it's in the SP filename.
            if hub.vendor_canonical and (sq_vendors & hub_vendors):
                return MatchResult(
                    "strong_evidence_match", 0.95,
                    "invoice_number_clean+vendor_canonical",
                    bd,
                )
            if hub.amount_float is not None:
                # Treat any non-zero hub amount as strong corroboration of an
                # invoice-number-based match. We can't compare to SP without
                # hashing, but inv# equality is already very specific.
                return MatchResult(
                    "strong_evidence_match", 0.92,
                    "invoice_number_clean+hub_amount_present",
                    bd,
                )
            # Invoice-date-mode: invoice# + date proximity is strong evidence
            # even when vendor and amount are both absent.
            if invoice_date_tolerance_days is not None and invoice_date_close:
                return MatchResult(
                    "strong_evidence_match", 0.90,
                    "invoice_number_clean+invoice_date_proximity",
                    bd,
                )
            return MatchResult(
                "strong_evidence_match", 0.88,
                "invoice_number_clean_in_filename",
                bd,
            )
        # Token match without canonicalized invoice_number_clean — softer.
        if sq_vendors & hub_vendors:
            return MatchResult(
                "likely_match", 0.78,
                "inv_po_token+vendor_token",
                bd,
            )
        return MatchResult("possible_match", 0.55, "inv_po_token_only", bd)

    # 2b. Invoice-date-mode strong tier: vendor + amount + invoice date proximity
    # (priority slot 5 from the user's spec). Filename can be totally different.
    if (
        invoice_date_tolerance_days is not None
        and (sq_vendors & hub_vendors)
        and hub.amount_float is not None
        and invoice_date_close
    ):
        return MatchResult(
            "strong_evidence_match", 0.85,
            "vendor_canonical+amount_float+invoice_date_proximity",
            bd,
        )

    # 3. Fuzzy filename ratio
    ratio = 0.0
    if sq_norm and hub_norm:
        ratio = SequenceMatcher(None, sq_norm, hub_norm).ratio()
    bd["norm_ratio"] = round(ratio, 3)
    if ratio >= 0.92:
        return MatchResult("likely_match", ratio, "filename_high_ratio", bd)

    # 4. Vendor + amount + close date
    if (sq_vendors & hub_vendors) and _amount_close(None, hub.amount_float):
        # Square9 has no amount field via Graph; this branch is a placeholder
        # for future integration if we ever ingest Square9 amounts.
        pass

    # 4b. Invoice-date-mode: vendor + invoice date proximity → likely
    if (
        invoice_date_tolerance_days is not None
        and (sq_vendors & hub_vendors)
        and invoice_date_close
    ):
        return MatchResult(
            "likely_match", 0.72,
            "vendor_canonical+invoice_date_proximity",
            bd,
        )

    if (sq_vendors & hub_vendors) and _date_close_days(sq.modified, hub.created_utc, 7):
        # Same vendor in the same week is not evidence of the same document:
        # on 2026-10-05, 12 of 13 such pairings were wrong (a Rotondo receipt
        # vs an activity report, an inventory sheet vs a freight invoice).
        # Reported for diagnosis but not counted as caught.
        return MatchResult(
            "no_match", 0.50, "weak_candidate:vendor_token+close_date_7d", bd
        )

    # 5. Fuzzy filename ratio fallback
    if ratio >= 0.85:
        return MatchResult("possible_match", ratio, "filename_mid_ratio", bd)

    # 6. Vendor token overlap >= 2 + close date 14d
    if len(sq_vendors & hub_vendors) >= 2 and _date_close_days(
        sq.modified, hub.created_utc, 14
    ):
        return MatchResult(
            "no_match", 0.45, "weak_candidate:multi_vendor_token+close_date_14d", bd
        )

    return MatchResult("no_match", 0.0, "no_evidence", bd)


def best_match(sq: SquareDoc, hubs: List[HubDoc],
               invoice_date_tolerance_days: Optional[int] = None
               ) -> Tuple[Optional[HubDoc], MatchResult]:
    best_doc: Optional[HubDoc] = None
    best_res = MatchResult("no_match", 0.0, "no_evidence", {})
    for h in hubs:
        r = score_pair(sq, h, invoice_date_tolerance_days=invoice_date_tolerance_days)
        if BUCKET_ORDER[r.bucket] > BUCKET_ORDER[best_res.bucket]:
            best_doc, best_res = h, r
        elif r.bucket == best_res.bucket and r.bucket != "no_match" and r.score > best_res.score:
            best_doc, best_res = h, r
        if best_res.bucket == "exact_match":
            break
    return best_doc, best_res



def _assign_one_to_one(square_docs: List["SquareDoc"], hub_docs: List["HubDoc"],
                       invoice_date_tolerance_days: Optional[int] = None):
    """Match each Square9 doc to at most one Hub doc and vice versa.

    best_match() scored every Square9 doc against every Hub doc
    independently, so one Hub doc could "catch" several Square9 docs (found
    2026-10-05: a single "GAMER product listing" file claimed 7 Rotondo
    receipts on vendor + date alone; 14 of 127 catches were such repeat
    claims). Pairs are now assigned greedily, strongest bucket and score
    first; a Square9 doc whose best Hub doc is taken falls back to its next
    best free candidate, or no_match. Mirrors the one-to-one rule the LLM
    assist pass already applies.
    """
    pairs = []
    for i, sq in enumerate(square_docs):
        for h in hub_docs:
            r = score_pair(sq, h, invoice_date_tolerance_days=invoice_date_tolerance_days)
            if r.bucket != "no_match":
                pairs.append((BUCKET_ORDER[r.bucket], r.score, i, h, r))
    pairs.sort(key=lambda t: (t[0], t[1]), reverse=True)
    assigned: Dict[int, Tuple["HubDoc", MatchResult]] = {}
    claimed: set = set()
    for _, _, i, h, r in pairs:
        if i in assigned or h.doc_id in claimed:
            continue
        assigned[i] = (h, r)
        claimed.add(h.doc_id)
    out = []
    for i, sq in enumerate(square_docs):
        if i in assigned:
            out.append((sq,) + assigned[i])
        else:
            out.append((sq, None, MatchResult("no_match", 0.0, "no_evidence", {})))
    return out


# ---------------------------------------------------------------------------
# Hub-side mongo loader
# ---------------------------------------------------------------------------

def load_hub_ap_docs(since_hours: int, limit: int) -> List[HubDoc]:
    """Read AP-lane docs from hub_documents within the requested window."""
    from pymongo import MongoClient  # local import keeps unit tests dep-free

    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    # Safety-net backfills are copies of Square9's own files; counting them would
    # make the cutover match rate measure nothing. They are reported separately.
    # Split children of a backfilled batch file carry source=auto_split, so they
    # are excluded through batch_parent_id.
    backfill_ids = db.hub_documents.distinct("id", {"source": "square9_backfill"})
    query = {"mailbox_category": "AP", "created_utc": {"$gte": cutoff},
             "source": {"$ne": "square9_backfill"},
             "batch_parent_id": {"$nin": backfill_ids}}
    backfilled = db.hub_documents.count_documents(
        {"mailbox_category": "AP", "created_utc": {"$gte": cutoff},
         "$or": [{"source": "square9_backfill"}, {"batch_parent_id": {"$in": backfill_ids}}]})
    if backfilled:
        print(f"Safety net: {backfilled} Square9-backfilled doc(s) in window, excluded from parity.",
              file=sys.stderr)
    # The limit must never cut the window short: the Square9 side covers the
    # whole window, so dropping Hub's oldest docs made every Square9 doc from
    # those days look "missing from Hub". Found 2026-10-01 with 649 AP docs in
    # a 168h window and --limit 500 (everything before the last ~5 days of the
    # window was silently dropped, depressing the cutover match rate).
    in_window = db.hub_documents.count_documents(query)
    if in_window > limit:
        print(
            f"WARNING: --limit {limit} would truncate the comparison window "
            f"({in_window} Hub AP docs since {cutoff}); loading all {in_window}.",
            file=sys.stderr,
        )
        limit = in_window
    cursor = (
        db.hub_documents
        .find(
            query,
            {"_id": 0,
             "id": 1, "file_name": 1, "sharepoint_web_url": 1,
             "sharepoint_folder_path": 1, "routing_status": 1,
             "folder_routing_reason": 1, "routing_reason": 1, "doc_type": 1,
             "suggested_job_type": 1, "classification_method": 1,
             "vendor_canonical": 1, "invoice_number_clean": 1,
             "amount_float": 1, "po_number_clean": 1, "created_utc": 1,
             "email_subject": 1, "email_sender": 1,
             "invoice_date": 1, "extracted_fields.invoice_date": 1,
             "extracted_fields.inv_date": 1},
        )
        .sort("created_utc", -1)
        .limit(limit)
    )
    return [HubDoc.from_mongo(d) for d in cursor]


# ---------------------------------------------------------------------------
# Expanded Square9 AP corpus (Temp Folder non-recursive + AP root recursive)
# ---------------------------------------------------------------------------

PROD_AP_ROOT_PATH = "General/Accounting/Accounts Payable"
PROD_AP_TEMP_FOLDER_NAME = "Temp Folder"


def parse_exclude_subpaths(arg: Optional[str]) -> List[str]:
    """Parse --exclude-square9-subpaths CSV string into a normalized list.

    Empty / None / whitespace-only items are dropped. Each token is
    lowercased and trimmed. Used downstream as case-insensitive substring
    match against `parent_path`.
    """
    if not arg:
        return []
    tokens: List[str] = []
    for raw in arg.split(","):
        t = (raw or "").strip().lower()
        if t:
            tokens.append(t)
    return tokens


def filter_square_docs_by_subpath(
    docs: List["SquareDoc"], exclude_subpaths: List[str]
) -> Tuple[List["SquareDoc"], int, List["SquareDoc"]]:
    """Drop Square9 docs whose `parent_path` matches ANY excluded substring.

    Returns (kept_docs, excluded_count, excluded_docs). Case-insensitive,
    substring match — handles full prefixes like "Outgoing Wires" and
    nested paths like "Outgoing Wires/2026" identically. Returns the input
    unchanged when `exclude_subpaths` is empty.
    """
    if not exclude_subpaths:
        return list(docs), 0, []
    kept: List[SquareDoc] = []
    excluded: List[SquareDoc] = []
    for d in docs:
        parent_path = ""
        if isinstance(d.raw, dict):
            parent_path = (d.raw.get("parent_path") or "").lower()
        if any(token in parent_path for token in exclude_subpaths):
            excluded.append(d)
        else:
            kept.append(d)
    return kept, len(excluded), excluded


def filter_square_docs_by_non_transactional_pattern(
    docs: List["SquareDoc"],
) -> Tuple[List["SquareDoc"], int, List["SquareDoc"]]:
    """Drop Square9 docs that match a known non-transactional pattern
    (reference spreadsheets, internal reports, customs paperwork, manual
    accounting-exception queues, etc.) using the same, already
    business-confirmed patterns bucket_C_intake_gap_report.py uses to
    recommend "exclude_from_parity_denominator". These were never real
    vendor invoices and were never capturable by Hub's email intake, so
    counting them as "no_match" against the cutover match rate
    mischaracterizes a correct non-event as a gap.

    Returns (kept_docs, excluded_count, excluded_docs).
    """
    kept: List[SquareDoc] = []
    excluded: List[SquareDoc] = []
    for d in docs:
        parent_path = ""
        if isinstance(d.raw, dict):
            parent_path = d.raw.get("parent_path") or ""
        blob = f"{d.name} {parent_path}"
        if any(pat.search(blob) for pat, _label in NOT_HUB_EXPECTED_PATTERNS):
            excluded.append(d)
        else:
            kept.append(d)
    return kept, len(excluded), excluded


# ---------------------------------------------------------------------------
# Triage CSV — write square9_only (no_match) rows for operator review
# ---------------------------------------------------------------------------

TRIAGE_OUTPUT_COLUMNS = [
    "square9_name", "square9_parent_path", "square9_modified",
    "best_hub_candidate", "best_score", "best_reason",
]


def write_triage_csv(out_path: str, rows: List[Dict[str, Any]]) -> int:
    """Write the square9_only rows out for operator review. Returns count."""
    triage_rows = [r for r in rows if r.get("match_bucket") == "no_match"]
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRIAGE_OUTPUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in triage_rows:
            w.writerow({
                "square9_name": r.get("square9_name", ""),
                "square9_parent_path": r.get("square9_parent_path", ""),
                "square9_modified": r.get("square9_modified", ""),
                # `_row_for` writes hub_* fields only when bucket != no_match,
                # so for triage rows these come back empty — exposed for any
                # future scoring tweak that lets near-misses surface their
                # closest candidate.
                "best_hub_candidate": r.get("hub_file_name", ""),
                "best_score": r.get("match_score", 0.0),
                "best_reason": r.get("match_reason", "no_evidence"),
            })
    return len(triage_rows)


def _square_doc_dedupe_key(d: "SquareDoc") -> str:
    """Stable id for de-duplicating Square9 docs across multiple Graph pulls."""
    raw = d.raw if isinstance(d.raw, dict) else {}
    gid = (raw.get("id") or "").strip()
    if gid:
        return f"id::{gid}"
    parent = (raw.get("parent_path") or "").strip()
    return f"path::{parent}/{d.name}".lower()


def pull_expanded_ap_corpus(
    token: str, host: str, site_path: str, library: str,
    ap_root_folder_path: str = PROD_AP_ROOT_PATH,
    temp_folder_name: str = PROD_AP_TEMP_FOLDER_NAME,
    max_depth: int = 25,
) -> List["SquareDoc"]:
    """Pull a complete Square9 AP corpus:

      1) Temp Folder under AP root, NON-recursive (immediate children only).
      2) AP root recursively (which structurally also includes Temp Folder
         contents — those duplicates are removed via Graph item id).

    De-duplication is done by Graph item id when present, falling back to a
    case-insensitive `parent_path/name` key.
    """
    temp_path = f"{ap_root_folder_path.rstrip('/')}/{temp_folder_name}"
    temp_docs = pull_listing_via_graph(
        token=token, host=host, site_path=site_path, library=library,
        folder_path=temp_path, label="prod_ap_temp", recursive=False,
    )
    root_docs = pull_listing_via_graph(
        token=token, host=host, site_path=site_path, library=library,
        folder_path=ap_root_folder_path, label="prod_ap_root",
        recursive=True, max_depth=max_depth,
    )
    seen: set = set()
    out: List[SquareDoc] = []
    for d in (temp_docs + root_docs):
        key = _square_doc_dedupe_key(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    print(
        f"  expanded_ap_corpus: temp={len(temp_docs)} + ap_root_recursive={len(root_docs)} "
        f"=> deduped={len(out)} doc(s).",
        file=sys.stderr,
    )
    return out


def load_recent_poll_health(since_hours: int) -> Dict[str, Any]:
    """Read mail_poll_runs failures for the parity-companion diagnostic."""
    from pymongo import MongoClient

    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    failed_runs = list(
        db.mail_poll_runs.find(
            {"started_at": {"$gte": cutoff},
             "$or": [
                 {"status": {"$in": ["failed_graph", "failed_token", "failed_exception"]}},
                 {"errors": {"$exists": True, "$not": {"$size": 0}}},
                 {"attachments_failed": {"$gt": 0}},
                 {"stalled_watermark": {"$exists": True}},
             ]},
            {"_id": 0, "run_id": 1, "mailbox": 1, "status": 1,
             "errors": 1, "attachments_failed": 1, "messages_detected": 1,
             "started_at": 1, "completed_at": 1, "ended_at": 1,
             "watermark_in": 1, "watermark_out": 1, "stalled_watermark": 1},
        ).sort("started_at", -1).limit(50)
    )
    return {
        "failed_runs": failed_runs,
        "failed_run_count": len(failed_runs),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

OUTPUT_COLUMNS = [
    "match_bucket", "match_score", "match_reason",
    "square9_name", "square9_parent_path", "square9_modified", "square9_web_url",
    "hub_doc_id", "hub_file_name", "hub_sharepoint_web_url", "hub_sharepoint_folder_path",
    "hub_routing_status", "hub_routing_reason", "hub_doc_type",
    "hub_suggested_job_type", "hub_classification_method",
    "hub_vendor_canonical", "hub_invoice_number_clean", "hub_amount_float",
    "hub_po_number_clean", "hub_email_sender", "hub_email_subject", "hub_created_utc",
]


def _row_for(sq: SquareDoc, hub: Optional[HubDoc], r: MatchResult) -> Dict[str, Any]:
    return {
        "match_bucket": r.bucket,
        "match_score": round(r.score, 3),
        "match_reason": r.reason,
        "square9_name": sq.name,
        "square9_parent_path": sq.raw.get("parent_path", ""),
        "square9_modified": sq.modified.isoformat() if sq.modified else "",
        "square9_web_url": sq.web_url,
        "hub_doc_id": hub.doc_id if hub else "",
        "hub_file_name": hub.file_name if hub else "",
        "hub_sharepoint_web_url": hub.sharepoint_web_url if hub else "",
        "hub_sharepoint_folder_path": hub.sharepoint_folder_path if hub else "",
        "hub_routing_status": hub.routing_status if hub else "",
        "hub_routing_reason": hub.routing_reason if hub else "",
        "hub_doc_type": hub.doc_type if hub else "",
        "hub_suggested_job_type": hub.suggested_job_type if hub else "",
        "hub_classification_method": hub.classification_method if hub else "",
        "hub_vendor_canonical": hub.vendor_canonical if hub else "",
        "hub_invoice_number_clean": hub.invoice_number_clean if hub else "",
        "hub_amount_float": hub.amount_float if hub else "",
        "hub_po_number_clean": hub.po_number_clean if hub else "",
        "hub_email_sender": hub.email_sender if hub else "",
        "hub_email_subject": hub.email_subject if hub else "",
        "hub_created_utc": hub.created_utc.isoformat() if hub and hub.created_utc else "",
    }


def _row_hub_only(hub: HubDoc) -> Dict[str, Any]:
    return {
        "match_bucket": "hub_only",
        "match_score": 0.0,
        "match_reason": "no_square9_counterpart",
        "square9_name": "",
        "square9_parent_path": "",
        "square9_modified": "",
        "square9_web_url": "",
        "hub_doc_id": hub.doc_id,
        "hub_file_name": hub.file_name,
        "hub_sharepoint_web_url": hub.sharepoint_web_url,
        "hub_sharepoint_folder_path": hub.sharepoint_folder_path,
        "hub_routing_status": hub.routing_status,
        "hub_routing_reason": hub.routing_reason,
        "hub_doc_type": hub.doc_type,
        "hub_suggested_job_type": hub.suggested_job_type,
        "hub_classification_method": hub.classification_method,
        "hub_vendor_canonical": hub.vendor_canonical,
        "hub_invoice_number_clean": hub.invoice_number_clean,
        "hub_amount_float": hub.amount_float,
        "hub_po_number_clean": hub.po_number_clean,
        "hub_email_sender": hub.email_sender,
        "hub_email_subject": hub.email_subject,
        "hub_created_utc": hub.created_utc.isoformat() if hub.created_utc else "",
    }


def write_csv(out_path: str, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# Findings (blockers + warnings)
# ---------------------------------------------------------------------------

def _hub_folder_root(p: str) -> str:
    if not p:
        return ""
    parts = [seg for seg in p.replace("\\", "/").split("/") if seg]
    return parts[0].lower() if parts else ""


def evaluate_findings(
    hub_docs: List[HubDoc],
    bucket_counts: Dict[str, int],
    match_rate: float,
    min_match_rate: float,
    poll_health: Dict[str, Any],
) -> Dict[str, List[str]]:
    blockers: List[str] = []
    warnings: List[str] = []

    if not hub_docs:
        blockers.append("hub_ap_docs_empty: no AP docs in window — cannot prove parity.")
        return {"blockers": blockers, "warnings": warnings}

    missing_routing = sum(1 for d in hub_docs if not d.routing_status)
    if missing_routing:
        blockers.append(
            f"hub_ap_docs_missing_routing_status: {missing_routing} doc(s) "
            f"in window have no routing_status."
        )

    forbidden = [
        d for d in hub_docs
        if _hub_folder_root(d.sharepoint_folder_path) in FORBIDDEN_HUB_FOLDER_ROOTS
    ]
    if forbidden:
        blockers.append(
            f"ap_docs_in_forbidden_root: {len(forbidden)} AP doc(s) routed "
            f"under Operations/Warehouse — sample: "
            f"{[d.file_name for d in forbidden[:3]]}"
        )

    if match_rate < min_match_rate:
        blockers.append(
            f"match_rate_below_threshold: {match_rate:.1%} < {min_match_rate:.1%}"
        )

    legacy = sum(
        1 for d in hub_docs
        if d.classification_method.lower().startswith(LEGACY_CLASSIFICATION_PREFIXES)
    )
    if legacy:
        warnings.append(f"legacy_classification_method: {legacy} doc(s).")

    miss_inv = sum(1 for d in hub_docs if not d.invoice_number_clean)
    if miss_inv:
        warnings.append(f"missing_invoice_number_clean: {miss_inv} doc(s).")

    miss_vendor = sum(1 for d in hub_docs if not d.vendor_canonical)
    if miss_vendor:
        warnings.append(f"missing_vendor_canonical: {miss_vendor} doc(s).")

    miss_amount = sum(1 for d in hub_docs if d.amount_float is None)
    if miss_amount:
        warnings.append(f"missing_amount_float: {miss_amount} doc(s).")

    if poll_health.get("failed_run_count", 0):
        warnings.append(
            f"recent_poll_failures: {poll_health['failed_run_count']} run(s) "
            f"with errors / attachment failures / stalled watermarks."
        )

    return {"blockers": blockers, "warnings": warnings}


# ---------------------------------------------------------------------------
# Console formatting
# ---------------------------------------------------------------------------

def format_summary_text(
    sq_count: int,
    hub_count: int,
    bucket_counts: Dict[str, int],
    match_rate: float,
    findings: Dict[str, List[str]],
    rows_for_top: List[Dict[str, Any]],
    poll_health: Dict[str, Any],
    top_n: int,
    llm_assist_enabled: bool = False,
    recycle_bin_check_enabled: bool = False,
    recycle_bin_check_succeeded: bool = False,
    recycle_bin_check_error: Optional[str] = None,
    recycle_bin_bonus: int = 0,
    match_rate_before_recycle_bin_adjustment: Optional[float] = None,
) -> str:
    out: List[str] = []
    out.append("=== square9_hub_ap_parity ===")
    out.append(f"  Square9 docs:              {sq_count}")
    out.append(f"  Hub AP docs:               {hub_count}")
    out.append(f"  exact_match:               {bucket_counts.get('exact_match', 0)}")
    out.append(f"  strong_evidence_match:     {bucket_counts.get('strong_evidence_match', 0)}")
    out.append(f"  likely_match:              {bucket_counts.get('likely_match', 0)}")
    out.append(f"  possible_match:            {bucket_counts.get('possible_match', 0)}")
    if llm_assist_enabled:
        out.append(f"  llm_assisted_match:        {bucket_counts.get('llm_assisted_match', 0)}")
    out.append(f"  square9_only (no_match):   {bucket_counts.get('no_match', 0)}")
    out.append(f"  hub_only:                  {bucket_counts.get('hub_only', 0)}")
    if recycle_bin_check_enabled:
        out.append(f"  recently_deleted_match:    {bucket_counts.get('recently_deleted_match', 0)}  "
                    f"(Hub docs matched to a Square9 item deleted during the window)")
    out.append("")
    if recycle_bin_check_enabled and recycle_bin_check_succeeded:
        out.append(
            f"  match_rate (raw, before recycle-bin adjustment): "
            f"{(match_rate_before_recycle_bin_adjustment or 0.0):.1%}"
        )
        out.append(
            f"  match_rate (adjusted - {recycle_bin_bonus} Square9 docs recovered "
            f"from recycle bin, added to both sides of the ratio):"
        )
        out.append(f"  >>> {match_rate:.1%} <<<")
    elif recycle_bin_check_enabled and not recycle_bin_check_succeeded:
        out.append(f"  match_rate:                {match_rate:.1%}  "
                    f"(RAW - recycle-bin adjustment was attempted but FAILED: "
                    f"{recycle_bin_check_error})")
    else:
        out.append(f"  match_rate:                {match_rate:.1%}")

    matched = [
        r for r in rows_for_top
        if r["match_bucket"] in ("exact_match", "strong_evidence_match",
                                 "likely_match", "possible_match")
    ]
    matched.sort(key=lambda r: (-BUCKET_ORDER.get(r["match_bucket"], 0),
                                -float(r["match_score"] or 0)))
    out.append("")
    out.append(f"  TOP {top_n} STRONGEST MATCHES")
    for r in matched[:top_n]:
        out.append(
            f"    [{r['match_bucket']}/{r['match_score']}] "
            f"{r['square9_name']!r}  ↔  {r['hub_file_name']!r}  "
            f"({r['match_reason']})"
        )

    if llm_assist_enabled:
        # Always shown as its own section, never merged into the
        # deterministic matches above - these came from a model
        # judgment call, not a regex/token rule, and deserve separate
        # scrutiny. The reasoning string is the model's own, printed
        # verbatim so a human can sanity-check each one.
        llm_matches = [r for r in rows_for_top if r["match_bucket"] == "llm_assisted_match"]
        llm_matches.sort(key=lambda r: -float(r["match_score"] or 0))
        out.append("")
        out.append(f"  LLM-ASSISTED MATCHES ({len(llm_matches)}) — review before trusting")
        for r in llm_matches[:top_n]:
            out.append(
                f"    [confidence={r['match_score']}] "
                f"{r['square9_name']!r}  ↔  {r['hub_file_name']!r}"
            )
            out.append(f"        reasoning: {r['match_reason']}")

    if recycle_bin_check_enabled and recycle_bin_check_succeeded:
        deleted_matches = [r for r in rows_for_top if r["match_bucket"] == "recently_deleted_match"]
        if deleted_matches:
            counted = [r for r in deleted_matches if float(r["match_score"] or 0) >= 1.0]
            labeled_only = [r for r in deleted_matches if float(r["match_score"] or 0) < 1.0]
            out.append("")
            out.append(
                f"  RECOVERED FROM RECYCLE BIN ({len(counted)} counted toward the "
                f"adjusted rate, {len(labeled_only)} additional sub-doc matches "
                f"explained but not double-counted)"
            )
            for r in counted[:top_n]:
                out.append(f"    {r['hub_file_name']!r}  ↔  {r['match_reason']}")
            if labeled_only:
                out.append(f"    (+{len(labeled_only)} more Hub sub-documents matching "
                            f"the same already-counted Square9 items)")

    sq_only = [r for r in rows_for_top if r["match_bucket"] == "no_match"]
    out.append("")
    out.append(f"  TOP {top_n} SQUARE9-ONLY MISSES")
    for r in sq_only[:top_n]:
        out.append(f"    {r['square9_name']!r}   parent={r['square9_parent_path']!r}")

    hub_only = [r for r in rows_for_top if r["match_bucket"] == "hub_only"]
    out.append("")
    out.append(f"  TOP {top_n} HUB-ONLY DOCS (in Hub AP-lane, no Square9 counterpart)")
    for r in hub_only[:top_n]:
        out.append(
            f"    {r['hub_file_name']!r}  → {r['hub_sharepoint_folder_path']!r}  "
            f"vendor={r['hub_vendor_canonical']!r} inv#={r['hub_invoice_number_clean']!r}"
        )

    out.append("")
    out.append("  POLL HEALTH (last window):")
    out.append(f"    failed_run_count: {poll_health.get('failed_run_count', 0)}")
    for r in poll_health.get("failed_runs", [])[:10]:
        first_err = (r.get("errors") or [""])[0] if r.get("errors") else ""
        out.append(
            f"    run_id={r.get('run_id')!r} mailbox={r.get('mailbox')!r} "
            f"status={r.get('status')!r} attachments_failed={r.get('attachments_failed', 0)} "
            f"err={first_err[:140]!r}"
        )

    out.append("")
    if findings["blockers"]:
        out.append("  BLOCKERS:")
        for b in findings["blockers"]:
            out.append(f"    - {b}")
    if findings["warnings"]:
        out.append("  WARNINGS:")
        for w in findings["warnings"]:
            out.append(f"    - {w}")
    if not findings["blockers"] and not findings["warnings"]:
        out.append("  RESULT: clean. AP-lane parity proof passed.")
    elif findings["blockers"]:
        out.append("  RESULT: BLOCKED. See blockers above.")
    else:
        out.append("  RESULT: warnings only. Review and re-run.")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Pure-function entrypoint (used by tests)
# ---------------------------------------------------------------------------

def filter_square_docs_by_modified(
    docs: List[SquareDoc], since_hours: int
) -> Tuple[List[SquareDoc], str]:
    """Drop Square9 docs whose modified-time is older than `now - since_hours`.

    Returns the filtered list and the cutoff iso string for reporting.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    cutoff_iso = cutoff.isoformat()
    out: List[SquareDoc] = []
    for d in docs:
        if d.modified is None:
            # No modified-time means we can't tell; conservative: exclude.
            continue
        if d.modified >= cutoff:
            out.append(d)
    return out, cutoff_iso


def run_compare(
    square_docs: List[SquareDoc],
    hub_docs: List[HubDoc],
    out_csv: Optional[str],
    top_n: int,
    min_match_rate: float,
    poll_health: Optional[Dict[str, Any]] = None,
    match_by_invoice_date: bool = False,
    invoice_date_tolerance_days: int = 30,
    excluded_subpaths: Optional[List[str]] = None,
    excluded_count: int = 0,
    excluded_non_transactional_count: int = 0,
    triage_out_csv: Optional[str] = None,
    llm_assist: bool = False,
    check_recycle_bin: bool = True,
    recycle_bin_since_hours: int = 168,
    recycle_bin_site_path: Optional[str] = None,
    hub_window_start: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Pure function — accepts loaded inputs, returns summary + rows."""
    poll_health = poll_health or {"failed_runs": [], "failed_run_count": 0}
    # hub_docs may include a lookback before the comparison window so a
    # Square9 doc can pair with a Hub copy received earlier (Hub caught it
    # before staff filed it). Only in-window Hub docs count as Hub-side
    # volume: hub_only rows, hub_count and recycle-bin matching.
    def _in_window(h: "HubDoc") -> bool:
        return hub_window_start is None or (h.created_utc is not None and h.created_utc >= hub_window_start)
    rows: List[Dict[str, Any]] = []
    bucket_counts: Dict[str, int] = {b: 0 for b in BUCKET_ORDER}
    bucket_counts["hub_only"] = 0
    bucket_counts["llm_assisted_match"] = 0
    bucket_counts["recently_deleted_match"] = 0

    inv_tol = invoice_date_tolerance_days if match_by_invoice_date else None

    matched_hub_ids: set = set()
    # (square_doc, index into `rows`) for every row the deterministic
    # matcher left as no_match — candidates for the optional LLM pass.
    no_match_entries: List[Tuple[SquareDoc, int]] = []
    for sq, hub, res in _assign_one_to_one(square_docs, hub_docs, invoice_date_tolerance_days=inv_tol):
        rows.append(_row_for(sq, hub if res.bucket != "no_match" else None, res))
        bucket_counts[res.bucket] = bucket_counts.get(res.bucket, 0) + 1
        if hub is not None and res.bucket != "no_match":
            matched_hub_ids.add(hub.doc_id)
        elif res.bucket == "no_match":
            no_match_entries.append((sq, len(rows) - 1))

    llm_assist_count = 0
    if llm_assist and no_match_entries:
        # Local import: keeps the LLM/emergentintegrations dependency
        # out of the hot path for every run that doesn't opt in, and
        # keeps this script importable/testable even where that
        # package isn't installed.
        from llm_parity_assist import run_llm_assist, LLM_MATCH_CONFIDENCE_FLOOR

        hub_by_id = {h.doc_id: h for h in hub_docs}
        verdicts = run_llm_assist(
            [sq for sq, _ in no_match_entries], hub_docs, matched_hub_ids,
        )
        for sq, row_idx in no_match_entries:
            v = verdicts.get(sq.name)
            if not v:
                continue
            # Defense in depth: re-check the confidence floor here too,
            # rather than trusting run_llm_assist()'s internal filtering
            # alone. This feeds a real business metric - a single point
            # of enforcement isn't defensive enough. Caught by testing:
            # a mocked/misbehaving run_llm_assist that skips its own
            # filtering must still not be able to inflate match_rate.
            if float(v.get("confidence") or 0.0) < LLM_MATCH_CONFIDENCE_FLOOR:
                continue
            matched_hub = hub_by_id.get(v["matched_hub_doc_id"])
            if matched_hub is None or matched_hub.doc_id in matched_hub_ids:
                # Already claimed by another row. Shouldn't normally
                # happen since candidate generation excludes already-
                # matched ids, but stay safe rather than double-count a
                # single Hub doc against two Square9 rows.
                continue
            rows[row_idx] = _row_for(
                sq, matched_hub,
                MatchResult(
                    "llm_assisted_match", v["confidence"], v["reasoning"], {},
                ),
            )
            bucket_counts["no_match"] -= 1
            bucket_counts["llm_assisted_match"] += 1
            matched_hub_ids.add(matched_hub.doc_id)
            llm_assist_count += 1

    # Recycle-bin adjustment: for Hub docs that still have no Square9
    # counterpart, check whether the reason is that Square9 deleted
    # the document (AP processed and cleared it) rather than Hub never
    # having a real match. Confirmed live 2026-07-17 against real
    # production data: 244 of 412 hub_only docs (strong, invoice-
    # number-token evidence only) traced directly to something deleted
    # from Square9 inside the same comparison window - the raw
    # match_rate this script produced was silently penalizing Hub for
    # Square9's own document lifecycle, not measuring a real gap.
    # On by default (unlike llm_assist, which remains experimental) -
    # this corrects a proven, large, confirmed distortion, not an
    # unproven capability being trialed.
    recycle_bin_bonus = 0
    recycle_bin_checked = False
    recycle_bin_error: Optional[str] = None
    recycle_bin_items_scanned = 0
    if check_recycle_bin:
        try:
            from recycle_bin_deletion_check import (
                pull_recycle_bin_items, find_strong_matches_for_hub_docs,
                PROD_SITE_PATH,
            )
            from sharepoint_ap_compare import acquire_graph_token

            tenant = os.environ.get("TENANT_ID")
            cid = os.environ.get("GRAPH_CLIENT_ID")
            csec = os.environ.get("GRAPH_CLIENT_SECRET")
            token = acquire_graph_token(tenant, cid, csec)
            host = os.environ.get(
                "SHAREPOINT_HOST",
                f"{(os.environ.get('SHAREPOINT_TENANT_NAME') or 'gamerpackaging1')}.sharepoint.com",
            )
            site_path = recycle_bin_site_path or PROD_SITE_PATH

            remaining_unmatched = [h for h in hub_docs if h.doc_id not in matched_hub_ids and _in_window(h)]
            deleted_items = pull_recycle_bin_items(
                token, host, site_path, recycle_bin_since_hours,
            )
            recycle_bin_items_scanned = len(deleted_items)
            matches = find_strong_matches_for_hub_docs(remaining_unmatched, deleted_items)

            hub_by_id = {h.doc_id: h for h in hub_docs}
            for doc_id, info in matches.items():
                hub = hub_by_id[doc_id]
                rows.append({
                    **_row_hub_only(hub),
                    "match_bucket": "recently_deleted_match",
                    "match_score": 1.0 if info["counted_toward_rate"] else 0.5,
                    "match_reason": (
                        f"square9_item_deleted:{info['deleted_item_name']}"
                        f" (shared: {','.join(info['shared_tokens'])})"
                    ),
                    "square9_name": info["deleted_item_name"],
                    "square9_modified": info["deleted_at"] or "",
                })
                bucket_counts["recently_deleted_match"] += 1
                matched_hub_ids.add(doc_id)
                if info["counted_toward_rate"]:
                    recycle_bin_bonus += 1
            recycle_bin_checked = True
        except Exception as e:
            # Never let this take down the readiness check - fall back
            # to the unadjusted numbers and say clearly, in the output,
            # that the adjustment was attempted but failed, rather than
            # silently under-reporting with no explanation.
            recycle_bin_error = str(e)

    for h in hub_docs:
        if h.doc_id in matched_hub_ids or not _in_window(h):
            continue
        rows.append(_row_hub_only(h))
        bucket_counts["hub_only"] += 1

    matched_before_recycle_bin = (
        bucket_counts["exact_match"]
        + bucket_counts["strong_evidence_match"]
        + bucket_counts["likely_match"]
        + bucket_counts["possible_match"]
        + bucket_counts["llm_assisted_match"]
    )
    match_rate_before_recycle_bin = (
        (matched_before_recycle_bin / len(square_docs)) if square_docs else 0.0
    )

    # The honest, adjusted numbers: each recycle-bin-recovered match
    # adds one real Square9 document back into BOTH sides of the
    # ratio, since it genuinely existed and was genuinely matched
    # during the window - it just isn't sitting in Square9 any more by
    # snapshot time. Only counted_toward_rate=True matches move this;
    # duplicate sub-doc claims on the same deleted item are labeled in
    # the rows above but never inflate the denominator twice for one
    # underlying document.
    matched = matched_before_recycle_bin + recycle_bin_bonus
    square_count_adjusted = len(square_docs) + recycle_bin_bonus
    match_rate = (matched / square_count_adjusted) if square_count_adjusted else 0.0

    findings = evaluate_findings(
        hub_docs=hub_docs,
        bucket_counts=bucket_counts,
        match_rate=match_rate,
        min_match_rate=min_match_rate,
        poll_health=poll_health,
    )

    if out_csv:
        write_csv(out_csv, rows)

    triage_written = 0
    if triage_out_csv:
        triage_written = write_triage_csv(triage_out_csv, rows)

    return {
        "rows": rows,
        "bucket_counts": bucket_counts,
        "match_rate": match_rate,
        # Authoritative, fully-adjusted matched count (includes
        # llm_assisted_match and recently_deleted_match, not just the
        # four deterministic buckets). Added 2026-07-17 after finding
        # a downstream script (cutover_proof_summary.py) re-deriving
        # this by summing a hardcoded list of bucket_counts keys that
        # went stale the moment recently_deleted_match was introduced -
        # its own "Projected match rate after Bucket A apply" line was
        # silently using the pre-recycle-bin-adjustment numbers even
        # though the headline match_rate above was already correct.
        # Downstream consumers should read this field directly rather
        # than re-summing bucket_counts themselves.
        "matched_count": matched,
        "findings": findings,
        "square_count": len(square_docs),
        "hub_count": sum(1 for h in hub_docs if _in_window(h)),
        "poll_health": poll_health,
        "top_n": top_n,
        "proof_mode": (
            "invoice_document_set" if match_by_invoice_date else "ingest_window"
        ),
        "invoice_date_tolerance_days": (
            invoice_date_tolerance_days if match_by_invoice_date else None
        ),
        "excluded_subpaths": list(excluded_subpaths or []),
        "excluded_count": excluded_count,
        "excluded_non_transactional_count": excluded_non_transactional_count,
        "triage_out_csv": triage_out_csv if triage_out_csv else None,
        "triage_rows_written": triage_written,
        "llm_assist_enabled": llm_assist,
        "llm_assist_count": llm_assist_count,
        "recycle_bin_check_enabled": check_recycle_bin,
        "recycle_bin_check_succeeded": recycle_bin_checked,
        "recycle_bin_check_error": recycle_bin_error,
        "recycle_bin_items_scanned": recycle_bin_items_scanned,
        "recycle_bin_bonus": recycle_bin_bonus,
        "match_rate_before_recycle_bin_adjustment": match_rate_before_recycle_bin,
        "square_count_before_adjustment": len(square_docs),
        "square_count_adjusted": square_count_adjusted,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Daily efficacy (separate from the rolling cutover rate)
# ---------------------------------------------------------------------------
_CAUGHT_BUCKETS = {"exact_match", "strong_evidence_match", "likely_match",
                   "possible_match", "llm_assisted_match"}


def _business_day(iso_ts: str) -> Optional[str]:
    """Calendar date of a timestamp in US Central time (Gamer's business day)."""
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("America/Chicago")).date().isoformat()
    except Exception:
        return (dt - timedelta(hours=5)).date().isoformat()


def _bc_norm(x: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(x or "").upper()).lstrip("0")


def record_bc_entry_coverage(days_back: int = 14) -> Dict[str, Any]:
    """BC as ground truth: of the purchase invoices AP entered into BC (draft
    or posted, by posting date), how many did the Hub receive? Staff remove a
    Square9 item once it is entered in BC (2026-10-05: 72% of items deleted
    from the Temp Folder were BC drafts/posted invoices vs 7% of items still
    there), so this measures intake against what AP actually processed,
    independent of folder housekeeping.

    A BC invoice counts as received when a Hub document carries its vendor
    invoice number (extracted field, file name or email subject; a 1-2 letter
    suffix like 1101621742A also matches the base) and the vendor or amount
    agrees, or the number is 6+ characters. Written per posting day into
    square9_daily_efficacy (bc_* fields). Never raises.
    """
    try:
        from pymongo import MongoClient
        db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).date().isoformat()
        bc: Dict[Any, Dict[str, Any]] = {}
        for t in ("posted_purchase_invoice", "draft_purchase_invoice"):
            for d in db.bc_reference_cache.find(
                    {"bc_entity_type": t, "bc_posting_date": {"$gte": since}},
                    {"_id": 0, "bc_vendor_no": 1, "bc_vendor_name": 1, "bc_external_document_no": 1,
                     "bc_amount": 1, "bc_posting_date": 1}):
                key = (d.get("bc_vendor_no"), _bc_norm(d.get("bc_external_document_no")))
                if key[1]:
                    bc.setdefault(key, d)
        hub_since = (datetime.now(timezone.utc) - timedelta(days=days_back + 45)).isoformat()
        index: Dict[str, List[Dict[str, Any]]] = {}
        for h in db.hub_documents.find(
                {"created_utc": {"$gte": hub_since}, "source": {"$ne": "square9_backfill"}},
                {"_id": 0, "invoice_number_clean": 1, "extracted_fields.invoice_number": 1,
                 "vendor_canonical": 1, "amount_float": 1, "file_name": 1, "email_subject": 1}):
            keys = {_bc_norm(h.get("invoice_number_clean")),
                    _bc_norm((h.get("extracted_fields") or {}).get("invoice_number"))}
            for src in (h.get("file_name"), h.get("email_subject")):
                # Whole hyphenated tokens too: "PS-INV261136" (Evergreen).
                for tok in re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", str(src or "")):
                    if re.search(r"\d", tok):
                        keys.add(_bc_norm(tok))
            for k in list(keys):
                tail = re.sub(r"\D", "", k)
                if len(tail) >= 8:
                    keys.add("D:" + tail[-8:])
            for k in keys:
                if len(k) >= 4:
                    index.setdefault(k, []).append(h)

        per_day: Dict[str, Dict[str, Any]] = {}
        for (vno, inv), d in bc.items():
            day = str(d.get("bc_posting_date") or "")[:10]
            rec = per_day.setdefault(day, {"bc_entered": 0, "bc_caught": 0, "missing": {}})
            rec["bc_entered"] += 1
            amt = d.get("bc_amount")
            variants = {inv}
            m = re.fullmatch(r"(\d{5,})[A-Z]{1,2}", inv)
            if m:
                variants.add(m.group(1))
            # BC suffixes like "14333_DIGI" (Canworks): the leading number.
            m = re.match(r"(\d{4,})[_\-][A-Za-z]+$", str(d.get("bc_external_document_no") or "").strip())
            if m:
                variants.add(_bc_norm(m.group(1)))
            # OCR reads R+L's leading "I"/"D" as "1": same 8-digit tail.
            tail = re.sub(r"\D", "", inv)
            if len(tail) >= 8:
                variants.add("D:" + tail[-8:])
            found = False
            for v in (x for x in variants if len(x) >= 4):
                for h in index.get(v, []):
                    agree = (str(h.get("vendor_canonical") or "").upper() == str(vno or "").upper()
                             or (amt is not None and h.get("amount_float") is not None
                                 and abs(abs(h["amount_float"]) - abs(amt)) < 0.02))
                    if agree or len(v) >= 6:
                        found = True
                        break
                if found:
                    break
            if found:
                rec["bc_caught"] += 1
            else:
                name = d.get("bc_vendor_name") or vno or "?"
                rec["missing"][name] = rec["missing"].get(name, 0) + 1

        total = sum(r["bc_entered"] for r in per_day.values())
        caught = sum(r["bc_caught"] for r in per_day.values())
        for day, rec in per_day.items():
            top = sorted(rec["missing"].items(), key=lambda kv: -kv[1])[:5]
            db.square9_daily_efficacy.update_one(
                {"_id": day},
                {"$set": {"date": day, "bc_entered": rec["bc_entered"], "bc_caught": rec["bc_caught"],
                          "bc_rate_pct": round(100 * rec["bc_caught"] / rec["bc_entered"], 1),
                          "bc_missing_top": [{"vendor": k, "count": v} for k, v in top],
                          "bc_updated_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True)
        summary = {"since": since, "bc_entered": total, "hub_received": caught,
                   "rate_pct": round(100 * caught / total, 1) if total else None}
        print(f"BC-entered coverage since {since}: {caught}/{total} "
              f"({summary['rate_pct']}%) of AP invoices entered in BC were received by the Hub")
        return summary
    except Exception as e:  # never break the readiness run
        print(f"WARNING: BC-entered coverage failed: {e!r}", file=sys.stderr)
        return {}


def record_daily_efficacy(rows: List[Dict[str, Any]], since_hours: int) -> Dict[str, Any]:
    """Score each business day on its own and store it in square9_daily_efficacy.

    A day's cohort is the Square9 AP documents filed that day. Caught = the
    Hub matched them through its own intake; missed = no match; recycle-bin
    recovered is reported separately. Each run refreshes the days still in
    its window, so late matches are picked up. The oldest day (cut by the
    window) and today are marked partial. Never raises.
    """
    try:
        days: Dict[str, Dict[str, Any]] = {}

        def day(d):
            return days.setdefault(d, {"square9_docs": 0, "caught": 0, "missed": 0,
                                       "recycle_bin_recovered": 0, "hub_only": 0})

        for r in rows:
            bucket = r.get("match_bucket")
            if bucket == "hub_only":
                d = _business_day(r.get("hub_created_utc", ""))
                if d:
                    day(d)["hub_only"] += 1
                continue
            d = _business_day(r.get("square9_modified", ""))
            if not d:
                continue
            rec = day(d)
            if bucket in _CAUGHT_BUCKETS:
                rec["caught"] += 1
                rec["square9_docs"] += 1
            elif bucket == "no_match":
                rec["missed"] += 1
                rec["square9_docs"] += 1
            elif bucket == "recently_deleted_match" and float(r.get("match_score") or 0) >= 1.0:
                rec["recycle_bin_recovered"] += 1

        from pymongo import MongoClient
        db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        now = datetime.now(timezone.utc)
        today = _business_day(now.isoformat())
        oldest = _business_day((now - timedelta(hours=since_hours)).isoformat())

        backfills: Dict[str, Dict[str, int]] = {}
        for e in db.missed_document_intake_log.find(
                {"status": "ingested", "ingested_at": {"$gte": (now - timedelta(hours=since_hours + 24)).isoformat()}},
                {"_id": 0, "ingested_at": 1, "source": 1}):
            d = _business_day(e.get("ingested_at", ""))
            if d:
                b = backfills.setdefault(d, {})
                b[e.get("source", "?")] = b.get(e.get("source", "?"), 0) + 1

        for d, rec in days.items():
            judged = rec["caught"] + rec["missed"]
            rec["raw_rate_pct"] = round(100 * rec["caught"] / judged, 1) if judged else None
            adj = judged + rec["recycle_bin_recovered"]
            rec["adjusted_rate_pct"] = (round(100 * (rec["caught"] + rec["recycle_bin_recovered"]) / adj, 1)
                                        if adj else None)
            rec["safety_net"] = backfills.get(d, {})
            rec["partial"] = d in (today, oldest)
            db.square9_daily_efficacy.update_one(
                {"_id": d},
                {"$set": {**rec, "date": d, "computed_at": now.isoformat(), "window_hours": since_hours},
                 "$inc": {"runs": 1}},
                upsert=True)
        return {"days_recorded": len(days)}
    except Exception as e:
        print(f"WARNING: daily efficacy not recorded: {e!r}", file=sys.stderr)
        return {"error": repr(e)}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Square9 vs GPI Hub AP-lane parity proof (read-only)."
    )
    ap.add_argument("--since-hours", type=int, default=24)
    ap.add_argument(
        "--prod-modified-since-hours", type=int, default=None,
        help="Filter Square9 docs to those with modified-time within the last "
             "N hours. Defaults to --since-hours so prod and Hub windows align.",
    )
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--out-csv", default="prod_reports/square9_hub_ap_parity.csv")
    ap.add_argument("--hub-lookback-days", type=int, default=14,
                    help="Extra days of Hub docs considered when matching (Hub may receive a "
                         "document before staff file it in Square9). Hub-side counts stay in-window.")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--no-record-efficacy", action="store_true",
                    help="Analysis runs: do not write square9_daily_efficacy")
    ap.add_argument(
        "--min-match-rate", type=float, default=0.85,
        help="Match rate threshold (0..1). Below this is a blocker. Default 0.85.",
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--prod-site-path", default=PROD_DEFAULT_SITE_PATH)
    ap.add_argument("--prod-library", default=PROD_DEFAULT_LIBRARY)
    ap.add_argument("--prod-folder-path", default=PROD_DEFAULT_FOLDER_PATH)
    ap.add_argument("--max-depth", type=int, default=25)
    ap.add_argument("--no-recursive", action="store_true")
    ap.add_argument(
        "--expanded-ap-corpus", action="store_true",
        help="Pull a complete Square9 AP corpus: Temp Folder non-recursive + "
             "AP root recursive, deduped by Graph item id. Recommended with "
             "--prod-modified-since-hours 720 for invoice-document-set parity.",
    )
    ap.add_argument(
        "--prod-ap-root-path", default=PROD_AP_ROOT_PATH,
        help=f"AP root folder path under the document library (default: "
             f"{PROD_AP_ROOT_PATH!r}). Only used with --expanded-ap-corpus.",
    )
    ap.add_argument(
        "--prod-ap-temp-folder-name", default=PROD_AP_TEMP_FOLDER_NAME,
        help=f"AP Temp Folder name under the AP root (default: "
             f"{PROD_AP_TEMP_FOLDER_NAME!r}). Only used with "
             f"--expanded-ap-corpus.",
    )
    ap.add_argument(
        "--match-by-invoice-date", action="store_true",
        help="Enable invoice-document-set parity: matcher accepts invoice-date "
             "proximity as supporting evidence. Hub uses "
             "extracted_fields.invoice_date (fallback created_utc); Square9 "
             "uses filename date tokens (fallback SharePoint modified).",
    )
    ap.add_argument(
        "--invoice-date-tolerance-days", type=int, default=30,
        help="Date-proximity window for --match-by-invoice-date "
             "(default: 30 days).",
    )
    ap.add_argument(
        "--exclude-square9-subpaths", default="",
        help="Comma-separated list of substrings; any Square9 doc whose "
             "parent_path contains any of these tokens (case-insensitive) "
             "is dropped from the corpus before scoring. Example: "
             "\"Outgoing Wires,Wells Fargo Positive Pay Uploads\". "
             "Default: empty (no filtering).",
    )
    ap.add_argument(
        "--triage-square9-only", action="store_true",
        help="Write a CSV of all square9_only (no_match) docs for operator "
             "triage. Output path defaults to "
             "prod_reports/square9_only_triage.csv; override via "
             "--triage-out-csv.",
    )
    ap.add_argument(
        "--triage-out-csv", default="prod_reports/square9_only_triage.csv",
        help="Override the triage CSV output path. Only honored when "
             "--triage-square9-only is set.",
    )
    ap.add_argument(
        "--llm-assist", action="store_true",
        help="Opt-in second pass: for Square9 docs the regex/token matcher "
             "leaves as no_match, generate a small set of loose candidates "
             "and ask Gemini to judge whether any is genuinely the same "
             "document (different filename formatting, OCR variance, etc). "
             "Accepted matches are labeled llm_assisted_match, always "
             "distinct from deterministic matches in the output. Off by "
             "default - new capability, opt in until validated across "
             "several runs. Requires EMERGENT_LLM_KEY; degrades to "
             "regex-only results (no crash) if unset or on any failure.",
    )
    ap.add_argument(
        "--no-recycle-bin-check", action="store_true",
        help="Disable the recycle-bin match-rate adjustment (on by default). "
             "Square9's prod side deletes documents as AP processes them - "
             "confirmed live 2026-07-17 that a large share of hub_only docs "
             "(244 of 412 in one real run, invoice-number-token evidence "
             "only) trace directly to a Square9 item deleted during the "
             "comparison window, meaning the raw match_rate was penalizing "
             "Hub for Square9's own document lifecycle rather than "
             "measuring a real gap. On by default because this corrects a "
             "proven distortion, unlike --llm-assist which trials an "
             "unproven capability. Degrades to the raw match_rate (no "
             "crash) on any failure - checked via recycle_bin_check_"
             "succeeded in the JSON output.",
    )
    ap.add_argument(
        "--recycle-bin-site-path", default=None,
        help="Override the SharePoint site path checked for deletions "
             "(default: recycle_bin_deletion_check.PROD_SITE_PATH, "
             "currently /sites/GamerAccounting).",
    )
    args = ap.parse_args()

    # Pull Square9 side via Graph
    tenant = os.environ.get("TENANT_ID")
    cid = os.environ.get("GRAPH_CLIENT_ID")
    csec = os.environ.get("GRAPH_CLIENT_SECRET")
    token = acquire_graph_token(tenant, cid, csec)
    host = os.environ.get(
        "SHAREPOINT_HOST",
        f"{(os.environ.get('SHAREPOINT_TENANT_NAME') or 'gamerpackaging1')}.sharepoint.com",
    )
    print(f"Graph token acquired. Host: {host}", file=sys.stderr)

    if args.expanded_ap_corpus:
        sq_docs = pull_expanded_ap_corpus(
            token=token, host=host,
            site_path=args.prod_site_path, library=args.prod_library,
            ap_root_folder_path=args.prod_ap_root_path,
            temp_folder_name=args.prod_ap_temp_folder_name,
            max_depth=args.max_depth,
        )
    else:
        sq_docs = pull_listing_via_graph(
            token=token, host=host,
            site_path=args.prod_site_path, library=args.prod_library,
            folder_path=args.prod_folder_path,
            label="prod", recursive=(not args.no_recursive),
            max_depth=args.max_depth,
        )
    sq_docs_unfiltered_count = len(sq_docs)
    prod_window_hours = args.prod_modified_since_hours or args.since_hours
    sq_docs, prod_cutoff_iso = filter_square_docs_by_modified(sq_docs, prod_window_hours)
    sq_count_before_subpath_exclusion = len(sq_docs)
    excluded_subpaths = parse_exclude_subpaths(args.exclude_square9_subpaths)
    sq_docs, excluded_count, _excluded_docs = filter_square_docs_by_subpath(
        sq_docs, excluded_subpaths
    )
    sq_docs, excluded_non_transactional_count, _excluded_nt_docs = (
        filter_square_docs_by_non_transactional_pattern(sq_docs)
    )

    # Pull Hub side from Mongo
    hub_docs = load_hub_ap_docs(args.since_hours + args.hub_lookback_days * 24, args.limit)
    hub_window_start = datetime.now(timezone.utc) - timedelta(hours=args.since_hours)
    poll_health = load_recent_poll_health(args.since_hours)

    print(
        f"Square9 listing: {sq_docs_unfiltered_count} total, "
        f"{sq_count_before_subpath_exclusion} within last {prod_window_hours}h "
        f"(cutoff={prod_cutoff_iso}); excluded_by_subpath={excluded_count} "
        f"({excluded_subpaths!r}); excluded_non_transactional="
        f"{excluded_non_transactional_count}; kept={len(sq_docs)}.",
        file=sys.stderr,
    )
    print(
        f"Loaded {len(sq_docs)} Square9 docs, {len(hub_docs)} Hub AP docs "
        f"(window={args.since_hours}h, limit={args.limit}, "
        f"proof_mode={'invoice_document_set' if args.match_by_invoice_date else 'ingest_window'}).",
        file=sys.stderr,
    )

    triage_out = args.triage_out_csv if args.triage_square9_only else None

    result = run_compare(
        square_docs=sq_docs,
        hub_docs=hub_docs,
        out_csv=args.out_csv,
        top_n=args.top,
        min_match_rate=args.min_match_rate,
        poll_health=poll_health,
        match_by_invoice_date=args.match_by_invoice_date,
        invoice_date_tolerance_days=args.invoice_date_tolerance_days,
        excluded_subpaths=excluded_subpaths,
        excluded_count=excluded_count,
        excluded_non_transactional_count=excluded_non_transactional_count,
        triage_out_csv=triage_out,
        llm_assist=args.llm_assist,
        check_recycle_bin=not args.no_recycle_bin_check,
        recycle_bin_since_hours=prod_window_hours,
        recycle_bin_site_path=args.recycle_bin_site_path,
        hub_window_start=hub_window_start,
    )
    if not args.no_record_efficacy:
        record_daily_efficacy(result["rows"], prod_window_hours)
        result["bc_entry_coverage"] = record_bc_entry_coverage()

    if args.json:
        # Strip rows; CSV is the row store.
        payload = {
            "proof_mode": result["proof_mode"],
            "hub_window_hours": args.since_hours,
            "square9_modified_window_hours": prod_window_hours,
            "invoice_date_tolerance_days": result["invoice_date_tolerance_days"],
            "expanded_ap_corpus": args.expanded_ap_corpus,
            "excluded_subpaths": result["excluded_subpaths"],
            "excluded_count": result["excluded_count"],
            "square9_count_before_subpath_exclusion": sq_count_before_subpath_exclusion,
            "square9_docs_count": result["square_count"],
            "square_count_before_filter": sq_docs_unfiltered_count,
            "prod_modified_cutoff": prod_cutoff_iso,
            "hub_ap_docs_count": result["hub_count"],
            # Backward-compat aliases retained:
            "square_count": result["square_count"],
            "hub_count": result["hub_count"],
            "since_hours": args.since_hours,
            "prod_modified_since_hours": prod_window_hours,
            "limit": args.limit,
            "bucket_counts": result["bucket_counts"],
            "matched_count": result["matched_count"],
            "match_rate": result["match_rate"],
            "match_rate_before_recycle_bin_adjustment": result["match_rate_before_recycle_bin_adjustment"],
            "recycle_bin_check_enabled": result["recycle_bin_check_enabled"],
            "recycle_bin_check_succeeded": result["recycle_bin_check_succeeded"],
            "recycle_bin_check_error": result["recycle_bin_check_error"],
            "recycle_bin_items_scanned": result["recycle_bin_items_scanned"],
            "recycle_bin_bonus": result["recycle_bin_bonus"],
            "square_count_before_adjustment": result["square_count_before_adjustment"],
            "square_count_adjusted": result["square_count_adjusted"],
            "llm_assist_enabled": result["llm_assist_enabled"],
            "llm_assist_count": result["llm_assist_count"],
            "blockers": result["findings"]["blockers"],
            "warnings": result["findings"]["warnings"],
            "findings": result["findings"],
            "poll_health": {
                "failed_run_count": poll_health["failed_run_count"],
                "failed_runs": poll_health["failed_runs"][:50],
            },
            "out_csv": args.out_csv,
            "triage_out_csv": result["triage_out_csv"],
            "triage_rows_written": result["triage_rows_written"],
        }
        print(json.dumps(payload, default=str, indent=2))
    else:
        print(format_summary_text(
            sq_count=result["square_count"],
            hub_count=result["hub_count"],
            bucket_counts=result["bucket_counts"],
            match_rate=result["match_rate"],
            findings=result["findings"],
            rows_for_top=result["rows"],
            poll_health=poll_health,
            top_n=args.top,
            llm_assist_enabled=result["llm_assist_enabled"],
            recycle_bin_check_enabled=result["recycle_bin_check_enabled"],
            recycle_bin_check_succeeded=result["recycle_bin_check_succeeded"],
            recycle_bin_check_error=result["recycle_bin_check_error"],
            recycle_bin_bonus=result["recycle_bin_bonus"],
            match_rate_before_recycle_bin_adjustment=result["match_rate_before_recycle_bin_adjustment"],
        ))
        print(
            f"\n  proof_mode:                {result['proof_mode']}"
        )
        print(
            f"  hub_window_hours:          {args.since_hours}"
        )
        print(
            f"  square9_modified_window:   last {prod_window_hours}h "
            f"(cutoff={prod_cutoff_iso})"
        )
        print(
            f"  invoice_date_tolerance:    "
            f"{result['invoice_date_tolerance_days']!r} days"
        )
        print(
            f"  expanded_ap_corpus:        {args.expanded_ap_corpus}"
        )
        print(
            f"  excluded_subpaths:         {result['excluded_subpaths']!r}"
        )
        print(
            f"  excluded_count:            {result['excluded_count']}  "
            f"(square9 corpus before exclusion: {sq_count_before_subpath_exclusion})"
        )
        print(
            f"  prod_listing_before_filter: {sq_docs_unfiltered_count} doc(s)"
        )
        if result["triage_out_csv"]:
            print(
                f"  triage_csv_written:        {result['triage_out_csv']}  "
                f"({result['triage_rows_written']} square9_only row(s))"
            )

    return 1 if result["findings"]["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
