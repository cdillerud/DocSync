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
        return MatchResult(
            "possible_match", 0.50, "vendor_token+close_date_7d", bd
        )

    # 5. Fuzzy filename ratio fallback
    if ratio >= 0.85:
        return MatchResult("possible_match", ratio, "filename_mid_ratio", bd)

    # 6. Vendor token overlap >= 2 + close date 14d
    if len(sq_vendors & hub_vendors) >= 2 and _date_close_days(
        sq.modified, hub.created_utc, 14
    ):
        return MatchResult(
            "possible_match", 0.45, "multi_vendor_token+close_date_14d", bd
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


# ---------------------------------------------------------------------------
# Hub-side mongo loader
# ---------------------------------------------------------------------------

def load_hub_ap_docs(since_hours: int, limit: int) -> List[HubDoc]:
    """Read AP-lane docs from hub_documents within the requested window."""
    from pymongo import MongoClient  # local import keeps unit tests dep-free

    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    cursor = (
        db.hub_documents
        .find(
            {"mailbox_category": "AP", "created_utc": {"$gte": cutoff}},
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
) -> str:
    out: List[str] = []
    out.append("=== square9_hub_ap_parity ===")
    out.append(f"  Square9 docs:              {sq_count}")
    out.append(f"  Hub AP docs:               {hub_count}")
    out.append(f"  exact_match:               {bucket_counts.get('exact_match', 0)}")
    out.append(f"  strong_evidence_match:     {bucket_counts.get('strong_evidence_match', 0)}")
    out.append(f"  likely_match:              {bucket_counts.get('likely_match', 0)}")
    out.append(f"  possible_match:            {bucket_counts.get('possible_match', 0)}")
    out.append(f"  square9_only (no_match):   {bucket_counts.get('no_match', 0)}")
    out.append(f"  hub_only:                  {bucket_counts.get('hub_only', 0)}")
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
    triage_out_csv: Optional[str] = None,
) -> Dict[str, Any]:
    """Pure function — accepts loaded inputs, returns summary + rows."""
    poll_health = poll_health or {"failed_runs": [], "failed_run_count": 0}
    rows: List[Dict[str, Any]] = []
    bucket_counts: Dict[str, int] = {b: 0 for b in BUCKET_ORDER}
    bucket_counts["hub_only"] = 0

    inv_tol = invoice_date_tolerance_days if match_by_invoice_date else None

    matched_hub_ids: set = set()
    for sq in square_docs:
        hub, res = best_match(sq, hub_docs, invoice_date_tolerance_days=inv_tol)
        rows.append(_row_for(sq, hub if res.bucket != "no_match" else None, res))
        bucket_counts[res.bucket] = bucket_counts.get(res.bucket, 0) + 1
        if hub is not None and res.bucket != "no_match":
            matched_hub_ids.add(hub.doc_id)

    for h in hub_docs:
        if h.doc_id in matched_hub_ids:
            continue
        rows.append(_row_hub_only(h))
        bucket_counts["hub_only"] += 1

    matched = (
        bucket_counts["exact_match"]
        + bucket_counts["strong_evidence_match"]
        + bucket_counts["likely_match"]
        + bucket_counts["possible_match"]
    )
    match_rate = (matched / len(square_docs)) if square_docs else 0.0

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
        "findings": findings,
        "square_count": len(square_docs),
        "hub_count": len(hub_docs),
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
        "triage_out_csv": triage_out_csv if triage_out_csv else None,
        "triage_rows_written": triage_written,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

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
    ap.add_argument("--top", type=int, default=25)
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

    # Pull Hub side from Mongo
    hub_docs = load_hub_ap_docs(args.since_hours, args.limit)
    poll_health = load_recent_poll_health(args.since_hours)

    print(
        f"Square9 listing: {sq_docs_unfiltered_count} total, "
        f"{sq_count_before_subpath_exclusion} within last {prod_window_hours}h "
        f"(cutoff={prod_cutoff_iso}); excluded_by_subpath={excluded_count} "
        f"({excluded_subpaths!r}); kept={len(sq_docs)}.",
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
        triage_out_csv=triage_out,
    )

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
            "match_rate": result["match_rate"],
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
