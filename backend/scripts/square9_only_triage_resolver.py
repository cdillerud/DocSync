"""
square9_only_triage_resolver.py
================================
READ-ONLY diagnostic. Decomposes the `square9_only` set produced by
`square9_hub_ap_parity_report.py --triage-square9-only` into four
buckets by cross-checking each Square9-only doc against the entire
`hub_documents` collection (any mailbox_category, any time):

  Bucket A — Hub has the doc but classified/routed outside AP
             (classifier/routing issue).
  Bucket B — Hub has the doc as AP, but `created_utc` is outside the
             parity window (timing artifact).
  Bucket C — Hub does not have the doc anywhere (intake-channel gap).
  Bucket D — Hub has the doc as AP within the window, but the parity
             matcher missed it (matcher precision gap).

Read-only with respect to MongoDB and SharePoint. Writes one CSV plus
one JSON summary to operator-supplied paths. Does NOT modify routing,
classification, or any data.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set, Tuple

# sys.path shim so this works as `python -m scripts.<...>` AND
# `python /app/scripts/<...>.py` AND inside-tests imports.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_THIS_DIR)
for p in (_PARENT_DIR, _THIS_DIR):
    if p and p not in sys.path:
        sys.path.insert(0, p)

try:
    from scripts.sharepoint_ap_compare import (  # type: ignore
        normalize_name,
        extract_invoice_po_tokens,
        extract_vendor_tokens,
        parse_modified,
    )
    from scripts.square9_hub_ap_parity_report import (  # type: ignore
        extract_date_from_filename,
    )
except ModuleNotFoundError:
    from sharepoint_ap_compare import (  # type: ignore
        normalize_name,
        extract_invoice_po_tokens,
        extract_vendor_tokens,
        parse_modified,
    )
    from square9_hub_ap_parity_report import (  # type: ignore
        extract_date_from_filename,
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def _canon_inv(t: str) -> str:
    """Uppercase + strip leading zeros (preserve original if all-zeros)."""
    u = (t or "").upper()
    return u.lstrip("0") or u


@dataclass
class Square9Row:
    name: str
    parent_path: str
    modified_iso: str
    modified_dt: Optional[datetime] = None
    norm_name: str = ""
    inv_tokens: List[str] = field(default_factory=list)
    vendor_tokens: List[str] = field(default_factory=list)
    inferred_date: Optional[datetime] = None

    @classmethod
    def from_csv_row(cls, r: Dict[str, str]) -> "Square9Row":
        name = (r.get("square9_name") or "").strip()
        parent = (r.get("square9_parent_path") or "").strip()
        modified = (r.get("square9_modified") or "").strip()
        modified_dt = parse_modified(modified) if modified else None
        combined = f"{name} {parent}"
        return cls(
            name=name,
            parent_path=parent,
            modified_iso=modified,
            modified_dt=modified_dt,
            norm_name=normalize_name(name),
            inv_tokens=[_canon_inv(t) for t in extract_invoice_po_tokens(combined)],
            vendor_tokens=extract_vendor_tokens(combined),
            inferred_date=extract_date_from_filename(name) or modified_dt,
        )


@dataclass
class HubDocLite:
    doc_id: str
    file_name: str
    norm_name: str
    inv_tokens_set: Set[str]
    vendor_tokens_set: Set[str]
    invoice_number_clean: str
    vendor_canonical: str
    mailbox_category: str
    doc_type: str
    suggested_job_type: str
    sharepoint_folder_path: str
    routing_status: str
    created_utc: Optional[datetime]
    invoice_date: Optional[datetime]

    @classmethod
    def from_mongo(cls, d: Dict[str, Any]) -> "HubDocLite":
        name = (d.get("file_name") or "").strip()
        inc = (d.get("invoice_number_clean") or "").strip()
        vc = (d.get("vendor_canonical") or "").strip()
        inv_tokens = extract_invoice_po_tokens(name)
        if inc:
            inv_tokens.append(inc)
        inv_set = {_canon_inv(t) for t in inv_tokens if t}
        vendor_tokens = extract_vendor_tokens(name)
        vendor_tokens.extend(
            t.lower() for t in vc.split() if len(t) >= 3
        )
        # created_utc parse
        cu = d.get("created_utc")
        if isinstance(cu, str):
            cu_dt = parse_modified(cu)
        elif isinstance(cu, datetime):
            cu_dt = cu if cu.tzinfo else cu.replace(tzinfo=timezone.utc)
        else:
            cu_dt = None
        # invoice_date parse (extracted_fields preferred)
        inv_date_raw: Any = None
        ef = d.get("extracted_fields")
        if isinstance(ef, dict):
            inv_date_raw = ef.get("invoice_date") or ef.get("inv_date")
        if not inv_date_raw:
            inv_date_raw = d.get("invoice_date")
        if isinstance(inv_date_raw, datetime):
            inv_dt: Optional[datetime] = (
                inv_date_raw if inv_date_raw.tzinfo
                else inv_date_raw.replace(tzinfo=timezone.utc)
            )
        elif isinstance(inv_date_raw, str) and inv_date_raw.strip():
            inv_dt = parse_modified(inv_date_raw.strip())
        else:
            inv_dt = None
        return cls(
            doc_id=str(d.get("id") or "")[:64],
            file_name=name,
            norm_name=normalize_name(name),
            inv_tokens_set=inv_set,
            vendor_tokens_set=set(vendor_tokens),
            invoice_number_clean=inc,
            vendor_canonical=vc,
            mailbox_category=(d.get("mailbox_category") or "").strip(),
            doc_type=(d.get("doc_type") or "").strip(),
            suggested_job_type=(d.get("suggested_job_type") or "").strip(),
            sharepoint_folder_path=(d.get("sharepoint_folder_path") or "").strip(),
            routing_status=(d.get("routing_status") or "").strip(),
            created_utc=cu_dt,
            invoice_date=inv_dt,
        )


@dataclass
class MatchVerdict:
    hub: Optional[HubDocLite]
    score: float
    reason: str


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _date_close(a: Optional[datetime], b: Optional[datetime],
                tol_days: int = 30) -> bool:
    if a is None or b is None:
        return False
    return abs((a - b).total_seconds()) <= tol_days * 86400


def score_match(sq: Square9Row, hub: HubDocLite,
                date_tol: int = 30) -> Tuple[float, str]:
    if sq.norm_name and sq.norm_name == hub.norm_name:
        return 1.0, "filename_exact"

    sq_inv = set(sq.inv_tokens)
    sq_vendors = set(sq.vendor_tokens)
    vendor_overlap = sq_vendors & hub.vendor_tokens_set
    hub_inv_date = hub.invoice_date or hub.created_utc

    if hub.invoice_number_clean:
        canon = _canon_inv(hub.invoice_number_clean)
        if canon and canon in sq_inv:
            if vendor_overlap:
                return 0.95, "invoice_number_clean+vendor_token"
            if _date_close(sq.inferred_date, hub_inv_date, date_tol):
                return 0.92, "invoice_number_clean+date_proximity"
            return 0.88, "invoice_number_clean"

    inv_overlap = sq_inv & hub.inv_tokens_set
    if inv_overlap:
        if vendor_overlap:
            return 0.82, "invoice_token+vendor_token"
        if _date_close(sq.inferred_date, hub_inv_date, date_tol):
            return 0.75, "invoice_token+date_proximity"
        return 0.62, "invoice_token_only"

    ratio = 0.0
    if sq.norm_name and hub.norm_name:
        ratio = SequenceMatcher(None, sq.norm_name, hub.norm_name).ratio()
    if ratio >= 0.92:
        return ratio, "filename_fuzzy_high"

    if vendor_overlap and _date_close(sq.inferred_date, hub_inv_date, date_tol):
        return 0.55, "vendor_token+date_proximity"

    if ratio >= 0.85:
        return ratio, "filename_fuzzy_mid"

    if len(vendor_overlap) >= 2:
        return 0.42, "vendor_token_multi"

    return 0.0, "no_evidence"


def build_indexes(hubs: List[HubDocLite]
                  ) -> Tuple[Dict[str, List[HubDocLite]], Dict[str, List[HubDocLite]]]:
    inv_idx: Dict[str, List[HubDocLite]] = defaultdict(list)
    norm_idx: Dict[str, List[HubDocLite]] = defaultdict(list)
    for h in hubs:
        for t in h.inv_tokens_set:
            inv_idx[t].append(h)
        if h.norm_name:
            norm_idx[h.norm_name].append(h)
    return inv_idx, norm_idx


def find_best_match(sq: Square9Row, hubs: List[HubDocLite],
                    inv_idx: Dict[str, List[HubDocLite]],
                    norm_idx: Dict[str, List[HubDocLite]],
                    min_score: float = 0.40,
                    date_tol: int = 30) -> MatchVerdict:
    best = MatchVerdict(None, 0.0, "no_evidence")

    if sq.norm_name:
        exact = norm_idx.get(sq.norm_name)
        if exact:
            return MatchVerdict(exact[0], 1.0, "filename_exact")

    seen_ids: Set[str] = set()
    for tok in sq.inv_tokens:
        for h in inv_idx.get(tok, []):
            if h.doc_id in seen_ids:
                continue
            seen_ids.add(h.doc_id)
            s, r = score_match(sq, h, date_tol=date_tol)
            if s > best.score:
                best = MatchVerdict(h, s, r)

    if best.score >= 0.85:
        return best

    if sq.vendor_tokens:
        v_set = set(sq.vendor_tokens)
        for h in hubs:
            if h.doc_id in seen_ids:
                continue
            if not (v_set & h.vendor_tokens_set):
                continue
            s, r = score_match(sq, h, date_tol=date_tol)
            if s > best.score:
                best = MatchVerdict(h, s, r)

    if best.score < min_score:
        return MatchVerdict(None, 0.0, "no_evidence")
    return best


# ---------------------------------------------------------------------------
# Bucket classification
# ---------------------------------------------------------------------------

def classify(verdict: MatchVerdict,
             since_cutoff: datetime) -> Tuple[str, str]:
    if verdict.hub is None:
        return "C", "expand_intake_channel_or_exchange_rule"
    h = verdict.hub
    if h.mailbox_category != "AP":
        cat = h.mailbox_category or "unknown"
        return "A", f"reclassify_to_AP_from_{cat}"
    if h.created_utc and h.created_utc >= since_cutoff:
        return "D", "improve_parity_matcher_precision"
    return "B", "extend_parity_window_or_no_action"


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

OUTPUT_COLUMNS = [
    "bucket", "square9_name", "square9_parent_path", "square9_modified",
    "best_hub_doc_id", "best_hub_file_name", "best_hub_created_utc",
    "best_hub_mailbox_category", "best_hub_doc_type",
    "best_hub_suggested_job_type", "best_hub_sharepoint_folder_path",
    "best_hub_routing_status", "best_match_score", "best_match_reason",
    "recommended_action",
]


def build_row(sq: Square9Row, verdict: MatchVerdict,
              bucket: str, action: str) -> Dict[str, Any]:
    h = verdict.hub
    return {
        "bucket": bucket,
        "square9_name": sq.name,
        "square9_parent_path": sq.parent_path,
        "square9_modified": sq.modified_iso,
        "best_hub_doc_id": h.doc_id if h else "",
        "best_hub_file_name": h.file_name if h else "",
        "best_hub_created_utc": (
            h.created_utc.isoformat() if h and h.created_utc else ""
        ),
        "best_hub_mailbox_category": h.mailbox_category if h else "",
        "best_hub_doc_type": h.doc_type if h else "",
        "best_hub_suggested_job_type": h.suggested_job_type if h else "",
        "best_hub_sharepoint_folder_path": h.sharepoint_folder_path if h else "",
        "best_hub_routing_status": h.routing_status if h else "",
        "best_match_score": round(verdict.score, 3),
        "best_match_reason": verdict.reason,
        "recommended_action": action,
    }


def write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def load_triage_rows(path: str) -> List[Square9Row]:
    out: List[Square9Row] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(Square9Row.from_csv_row(row))
    return out


def load_hub_corpus() -> List[HubDocLite]:
    from pymongo import MongoClient  # local import keeps unit tests dep-free
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    cursor = db.hub_documents.find(
        {},
        {"_id": 0, "id": 1, "file_name": 1, "invoice_number_clean": 1,
         "vendor_canonical": 1, "mailbox_category": 1, "doc_type": 1,
         "suggested_job_type": 1, "sharepoint_folder_path": 1,
         "routing_status": 1, "created_utc": 1, "invoice_date": 1,
         "extracted_fields.invoice_date": 1,
         "extracted_fields.inv_date": 1},
    )
    return [HubDocLite.from_mongo(d) for d in cursor]


# ---------------------------------------------------------------------------
# Pure resolver (used by tests)
# ---------------------------------------------------------------------------

def resolve(square9_rows: List[Square9Row], hubs: List[HubDocLite],
            since_hours: int, date_tol: int = 30) -> Dict[str, Any]:
    inv_idx, norm_idx = build_indexes(hubs)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    rows: List[Dict[str, Any]] = []
    counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for sq in square9_rows:
        verdict = find_best_match(sq, hubs, inv_idx, norm_idx,
                                  date_tol=date_tol)
        bucket, action = classify(verdict, cutoff)
        counts[bucket] += 1
        rows.append(build_row(sq, verdict, bucket, action))
    return {"rows": rows, "counts": counts,
            "total": len(square9_rows),
            "since_hours": since_hours,
            "cutoff_iso": cutoff.isoformat()}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Square9-only triage resolver (read-only)."
    )
    ap.add_argument("--triage-csv",
                    default="prod_reports/square9_only_triage.csv")
    ap.add_argument("--since-hours", type=int, default=720)
    ap.add_argument("--date-tolerance-days", type=int, default=30)
    ap.add_argument("--out-csv",
                    default="prod_reports/square9_only_triage_resolved.csv")
    ap.add_argument("--json",
                    default="prod_reports/square9_only_triage_resolved.json")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    print(f"Loading triage CSV: {args.triage_csv}", file=sys.stderr)
    sq_rows = load_triage_rows(args.triage_csv)
    print(f"  loaded {len(sq_rows)} square9_only row(s)", file=sys.stderr)

    print("Loading hub_documents corpus (full collection, read-only)...",
          file=sys.stderr)
    hubs = load_hub_corpus()
    print(f"  loaded {len(hubs)} hub doc(s)", file=sys.stderr)

    result = resolve(sq_rows, hubs, args.since_hours,
                     date_tol=args.date_tolerance_days)
    write_csv(args.out_csv, result["rows"])

    counts = result["counts"]
    by_bucket: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in result["rows"]:
        by_bucket[r["bucket"]].append(r)

    folder_C = Counter(r["square9_parent_path"] for r in by_bucket["C"])
    folder_A = Counter(r["square9_parent_path"] for r in by_bucket["A"])
    folder_unmatched = Counter(
        r["square9_parent_path"] for r in result["rows"]
        if r["bucket"] in ("A", "C")
    )

    summary: Dict[str, Any] = {
        "total_square9_only": result["total"],
        "bucket_A_count": counts["A"],
        "bucket_B_count": counts["B"],
        "bucket_C_count": counts["C"],
        "bucket_D_count": counts["D"],
        "since_hours": args.since_hours,
        "date_tolerance_days": args.date_tolerance_days,
        "cutoff_iso": result["cutoff_iso"],
        "top_bucket_A_examples": [
            {k: r[k] for k in (
                "square9_name", "square9_parent_path", "best_hub_doc_id",
                "best_hub_mailbox_category", "best_hub_doc_type",
                "best_hub_suggested_job_type",
                "best_hub_sharepoint_folder_path",
                "best_match_score", "best_match_reason",
                "recommended_action",
            )} for r in by_bucket["A"][:args.top]
        ],
        "top_bucket_C_examples": [
            {k: r[k] for k in (
                "square9_name", "square9_parent_path", "square9_modified",
                "recommended_action",
            )} for r in by_bucket["C"][:args.top]
        ],
        "top_bucket_D_examples": [
            {k: r[k] for k in (
                "square9_name", "best_hub_doc_id", "best_hub_file_name",
                "best_match_reason", "best_match_score",
            )} for r in by_bucket["D"][:args.top]
        ],
        "top_bucket_C_folders": folder_C.most_common(args.top),
        "top_bucket_A_folders": folder_A.most_common(args.top),
        "top_unmatched_folders": folder_unmatched.most_common(args.top),
        "out_csv": args.out_csv,
        "recommended_next_actions": [
            (
                f"BUCKET A ({counts['A']}): "
                "reclassify these docs from their current "
                "mailbox_category into AP — classifier/routing fix."
                if counts["A"] else None
            ),
            (
                f"BUCKET B ({counts['B']}): "
                "extend the parity window or accept as out-of-window "
                "(no code change required)."
                if counts["B"] else None
            ),
            (
                f"BUCKET C ({counts['C']}): "
                "expand intake channels — these docs never reached Hub. "
                "Investigate Exchange transport rules / scanner / "
                "drag-drop / portal / Square9 Inbox forwarding."
                if counts["C"] else None
            ),
            (
                f"BUCKET D ({counts['D']}): "
                "tune parity matcher precision — Hub ingested as AP in "
                "window but matcher missed it."
                if counts["D"] else None
            ),
        ],
    }
    summary["recommended_next_actions"] = [
        a for a in summary["recommended_next_actions"] if a
    ]

    os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(summary, f, default=str, indent=2)

    # ---- stdout ----
    print()
    print("=== square9_only_triage_resolved ===")
    print(f"  total_square9_only:  {summary['total_square9_only']}")
    print(f"  bucket_A_count:      {counts['A']}  "
          "(Hub has it, classified non-AP)")
    print(f"  bucket_B_count:      {counts['B']}  "
          "(Hub has AP version, outside window)")
    print(f"  bucket_C_count:      {counts['C']}  "
          "(Hub never received it)")
    print(f"  bucket_D_count:      {counts['D']}  "
          "(Hub has AP in window, parity matcher missed)")
    print(f"  since_hours:         {args.since_hours}  "
          f"(cutoff={result['cutoff_iso']})")

    if by_bucket["A"]:
        print(f"\n  TOP {args.top} BUCKET A (Hub has it but classified non-AP)")
        for r in by_bucket["A"][:args.top]:
            print(
                f"    sq={r['square9_name']!r}  "
                f"hub_id={r['best_hub_doc_id']!r}  "
                f"hub_cat={r['best_hub_mailbox_category']!r}  "
                f"type={r['best_hub_doc_type']!r}  "
                f"job={r['best_hub_suggested_job_type']!r}  "
                f"folder={r['best_hub_sharepoint_folder_path']!r}  "
                f"reason={r['best_match_reason']!r}  "
                f"score={r['best_match_score']}"
            )

    if by_bucket["C"]:
        print(f"\n  TOP {args.top} BUCKET C (intake-channel gap)")
        for r in by_bucket["C"][:args.top]:
            print(
                f"    {r['square9_name']!r}  "
                f"parent={r['square9_parent_path']!r}  "
                f"modified={r['square9_modified']!r}"
            )
        print(f"\n  BUCKET C parent_path concentrations (top {args.top}):")
        for path, n in folder_C.most_common(args.top):
            print(f"    {n:4d}  {path!r}")

    if by_bucket["D"]:
        print(f"\n  TOP {args.top} BUCKET D (parity matcher missed)")
        for r in by_bucket["D"][:args.top]:
            print(
                f"    sq={r['square9_name']!r}  "
                f"hub_id={r['best_hub_doc_id']!r}  "
                f"reason={r['best_match_reason']!r}  "
                f"score={r['best_match_score']}"
            )

    if summary["recommended_next_actions"]:
        print("\n  RECOMMENDED NEXT ACTIONS:")
        for a in summary["recommended_next_actions"]:
            print(f"    - {a}")

    print(f"\n  out_csv: {args.out_csv}")
    print(f"  json:    {args.json}")

    if counts["A"] > 0 or counts["C"] > 0:
        return 2
    if counts["B"] > 0 or counts["D"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
