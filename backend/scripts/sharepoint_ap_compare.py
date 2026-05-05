"""
sharepoint_ap_compare.py — Fuzzy comparison of two SharePoint folder listings.

Purpose
-------
Prove whether prod AP Temp Folder and a test destination contain the same
documents, even when filenames are not byte-identical. The previous strict
filename comparison was returning 0 matches; that is almost certainly a
matcher problem, not a real-world overlap problem. This script replaces
the strict matcher with a multi-signal fuzzy scorer.

Inputs (two CSV listings of the two folders)
--------------------------------------------
Each CSV must have at minimum these columns (header row required):
    name, size, modified
Optional columns (passed through if present):
    web_url, id, parent_path

`size`     — file size in bytes (int).
`modified` — ISO-8601 timestamp; tolerant of `Z` and offset forms.
             Empty cells are treated as unknown (date proximity then
             contributes 0 to scoring).

Optional input
--------------
--prior-strict-csv : the output of an earlier strict-filename comparison
                     with at least columns `name, status` where status is
                     one of {match, no_match}. Used purely to flag
                     "previously_missed" rows for surface-up reporting.

Outputs
-------
1. --out-csv (default `sharepoint_ap_compare_out.csv`) — every prod row,
   one line per row, with the best test-side candidate (if any), the
   confidence bucket, and a score breakdown.

2. Stdout summary:
       counts by bucket: exact_match / likely_match / possible_match / no_match
       top N (--top, default 25) likely_match rows that were
       previously_missed by the strict matcher

Confidence buckets (ranked, highest first)
------------------------------------------
exact_match
    Normalized filename identical.

likely_match
    Same invoice/PO/reference token AND
        (size equal OR size within 5% OR modified-day-distance <= 1)
    OR vendor-token overlap >= 2 AND size equal
    OR normalized SequenceMatcher ratio >= 0.92
       (very strong fuzzy filename hit, e.g., "_DO NOT PAY" suffix added).

possible_match
    Same invoice/PO/reference token (alone)
    OR vendor-token overlap >= 1 AND modified-day-distance <= 7
    OR normalized SequenceMatcher ratio >= 0.85.

no_match
    Otherwise.

Operator usage (bare lines, run on prod VM, no triple backticks)
----------------------------------------------------------------
    docker compose exec -T backend python -m backend.scripts.sharepoint_ap_compare \
        --prod-csv prod_reports/sp_prod_ap_temp_listing.csv \
        --test-csv prod_reports/sp_test_ap_temp_listing.csv \
        --prior-strict-csv prod_reports/sp_strict_match_prev.csv \
        --out-csv prod_reports/sp_ap_compare_fuzzy.csv \
        --top 25

If --prior-strict-csv is omitted the "previously_missed" column is left
empty and the "previously missed" surfacing is skipped.

The script is read-only with respect to MongoDB and SharePoint. It only
reads the two input CSVs and writes one output CSV plus stdout.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_SUFFIX_NOISE = [
    "do not pay",
    "donotpay",
    "do_not_pay",
    "final final",
    "final",
    "copy",
    "scan",
    "scanned",
    "bol",
    "ocr",
    "rev",
    "revised",
    "v2",
    "v3",
]

_STOPWORDS = {
    "the", "and", "for", "from", "inc", "llc", "ltd", "co", "corp",
    "company", "invoice", "inv", "po", "purchase", "order", "bill",
    "statement", "credit", "memo", "draft", "final", "copy", "scan",
    "ocr", "do", "not", "pay", "rev", "revised",
}

_INVOICE_PO_PATTERNS = [
    # Keyword + reference where reference contains at least one digit and >=4 chars total.
    re.compile(r"\b(?:invoice|inv|order|ref|bol|po|so)\b[\s\-#:]*([a-z0-9](?=[a-z0-9\-]*\d)[a-z0-9\-]{3,})", re.I),
    re.compile(r"\b(\d{5,})\b"),                 # bare numeric refs >=5 digits
    re.compile(r"\b([a-z]{2,4}-?\d{4,})\b", re.I),  # vendor-prefixed alphanumeric
]


def _strip_diacritics(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )


def normalize_name(name: str) -> str:
    """Aggressive filename normalization for exact-equality bucketing."""
    if not name:
        return ""
    n = _strip_diacritics(name).lower()
    # drop extension
    if "." in n:
        n = n.rsplit(".", 1)[0]
    # drop common noise suffixes
    for noise in _SUFFIX_NOISE:
        n = n.replace(noise, " ")
    # collapse separators
    n = re.sub(r"[\(\)\[\]\{\}]", " ", n)
    n = re.sub(r"[_\-\.\,]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def extract_invoice_po_tokens(name: str) -> List[str]:
    if not name:
        return []
    found: List[str] = []
    base = name.rsplit(".", 1)[0] if "." in name else name
    # normalize separators so word boundaries fire correctly across "_" / "-" etc.
    base = re.sub(r"[_\-\.\,\(\)\[\]\{\}/]", " ", base)
    for pat in _INVOICE_PO_PATTERNS:
        for m in pat.findall(base):
            tok = m.strip().upper()
            # skip pure-keyword captures like "OICE" left over from broken matches
            if not tok or tok.lower() in {"oice", "voice", "rder", "bol", "inv", "po", "so"}:
                continue
            stripped = tok.lstrip("0") or tok
            if len(stripped) >= 4 and stripped not in found:
                found.append(stripped)
    return found


def extract_vendor_tokens(name: str) -> List[str]:
    if not name:
        return []
    base = _strip_diacritics(name).lower()
    base = base.rsplit(".", 1)[0] if "." in base else base
    base = re.sub(r"[_\-\.\,\(\)\[\]\{\}]", " ", base)
    tokens = [
        t for t in base.split()
        if t.isalpha() and len(t) >= 3 and t not in _STOPWORDS
    ]
    # de-dupe preserving order
    seen, out = set(), []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def parse_modified(value: str) -> Optional[datetime]:
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        # try common alt format
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
            try:
                return datetime.strptime(v, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Doc:
    raw: Dict[str, str]
    name: str
    size: Optional[int]
    modified: Optional[datetime]
    web_url: str
    norm_name: str = ""
    inv_po_tokens: List[str] = field(default_factory=list)
    vendor_tokens: List[str] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: Dict[str, str]) -> "Doc":
        name = (row.get("name") or "").strip()
        size_raw = (row.get("size") or "").strip()
        try:
            size = int(size_raw) if size_raw else None
        except ValueError:
            size = None
        modified = parse_modified(row.get("modified") or "")
        web_url = (row.get("web_url") or "").strip()
        d = cls(
            raw=row,
            name=name,
            size=size,
            modified=modified,
            web_url=web_url,
            norm_name=normalize_name(name),
            inv_po_tokens=extract_invoice_po_tokens(name),
            vendor_tokens=extract_vendor_tokens(name),
        )
        return d


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclass
class Score:
    bucket: str
    breakdown: Dict[str, Any] = field(default_factory=dict)


_BUCKET_ORDER = {"exact_match": 3, "likely_match": 2, "possible_match": 1, "no_match": 0}


def _size_signal(a: Optional[int], b: Optional[int]) -> str:
    if a is None or b is None or a <= 0 or b <= 0:
        return "unknown"
    if a == b:
        return "equal"
    diff = abs(a - b) / max(a, b)
    if diff <= 0.01:
        return "near_1pct"
    if diff <= 0.05:
        return "near_5pct"
    return "far"


def _date_distance_days(a: Optional[datetime], b: Optional[datetime]) -> Optional[int]:
    if a is None or b is None:
        return None
    return abs(int((a - b).total_seconds() // 86400))


def score_pair(p: Doc, t: Doc) -> Score:
    breakdown: Dict[str, Any] = {}
    # 1. exact normalized filename
    if p.norm_name and p.norm_name == t.norm_name:
        breakdown["norm_name"] = "equal"
        return Score("exact_match", breakdown)

    # 2. fuzzy ratio on normalized name
    ratio = 0.0
    if p.norm_name and t.norm_name:
        ratio = SequenceMatcher(None, p.norm_name, t.norm_name).ratio()
    breakdown["norm_ratio"] = round(ratio, 3)

    # 3. invoice/po token overlap
    p_inv = set(p.inv_po_tokens)
    t_inv = set(t.inv_po_tokens)
    inv_overlap = sorted(p_inv & t_inv)
    breakdown["inv_po_overlap"] = inv_overlap

    # 4. vendor token overlap
    p_v = set(p.vendor_tokens)
    t_v = set(t.vendor_tokens)
    v_overlap = sorted(p_v & t_v)
    breakdown["vendor_overlap"] = v_overlap

    # 5. size
    sz = _size_signal(p.size, t.size)
    breakdown["size"] = sz

    # 6. modified-date distance
    dd = _date_distance_days(p.modified, t.modified)
    breakdown["modified_day_distance"] = dd

    # ----- bucket logic -----

    if ratio >= 0.92:
        return Score("likely_match", breakdown)

    if inv_overlap:
        if sz in ("equal", "near_1pct", "near_5pct") or (dd is not None and dd <= 1):
            return Score("likely_match", breakdown)
        return Score("possible_match", breakdown)

    if len(v_overlap) >= 2 and sz == "equal":
        return Score("likely_match", breakdown)

    if len(v_overlap) >= 1 and dd is not None and dd <= 7:
        return Score("possible_match", breakdown)

    if ratio >= 0.85:
        return Score("possible_match", breakdown)

    return Score("no_match", breakdown)


def best_match(p: Doc, candidates: List[Doc]) -> Tuple[Optional[Doc], Score]:
    best: Tuple[Optional[Doc], Score] = (None, Score("no_match", {}))
    for t in candidates:
        s = score_pair(p, t)
        if _BUCKET_ORDER[s.bucket] > _BUCKET_ORDER[best[1].bucket]:
            best = (t, s)
        elif s.bucket == best[1].bucket and s.bucket != "no_match":
            # tie-break: higher norm_ratio wins
            if s.breakdown.get("norm_ratio", 0) > best[1].breakdown.get("norm_ratio", 0):
                best = (t, s)
        if best[1].bucket == "exact_match":
            break
    return best


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------

def load_listing(path: str) -> List[Doc]:
    out: List[Doc] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "name" not in reader.fieldnames:
            raise SystemExit(f"{path}: missing required `name` column")
        for row in reader:
            out.append(Doc.from_row(row))
    return out


def load_prior_strict(path: str) -> Dict[str, str]:
    """Returns {normalized_prod_name: status} from prior strict-match output."""
    prior: Dict[str, str] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "name" not in reader.fieldnames:
            raise SystemExit(f"{path}: missing required `name` column")
        status_col = "status" if "status" in reader.fieldnames else None
        if status_col is None:
            raise SystemExit(f"{path}: missing required `status` column")
        for row in reader:
            prior[normalize_name(row.get("name") or "")] = (row.get(status_col) or "").strip().lower()
    return prior


def write_output(out_path: str, rows: List[Dict[str, Any]]) -> None:
    cols = [
        "prod_name", "prod_size", "prod_modified", "prod_web_url",
        "test_name", "test_size", "test_modified", "test_web_url",
        "confidence", "norm_ratio", "inv_po_overlap", "vendor_overlap",
        "size_signal", "modified_day_distance", "previously_missed",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(prod_csv: str, test_csv: str, out_csv: str,
        prior_strict_csv: Optional[str], top_n: int) -> int:
    prod = load_listing(prod_csv)
    test = load_listing(test_csv)
    prior = load_prior_strict(prior_strict_csv) if prior_strict_csv else {}

    print(f"Loaded {len(prod)} prod docs, {len(test)} test docs.", file=sys.stderr)
    if prior:
        print(f"Loaded {len(prior)} prior-strict rows for previously-missed flagging.", file=sys.stderr)

    rows: List[Dict[str, Any]] = []
    counts = {"exact_match": 0, "likely_match": 0, "possible_match": 0, "no_match": 0}

    for p in prod:
        match, sc = best_match(p, test)
        bucket = sc.bucket
        counts[bucket] += 1

        prev = ""
        if prior:
            prior_status = prior.get(p.norm_name, "")
            if bucket in ("exact_match", "likely_match", "possible_match") and prior_status == "no_match":
                prev = "yes"
            elif bucket != "no_match" and prior_status == "" and p.norm_name not in prior:
                prev = "absent_in_prior"

        rows.append({
            "prod_name": p.name,
            "prod_size": p.size if p.size is not None else "",
            "prod_modified": p.modified.isoformat() if p.modified else "",
            "prod_web_url": p.web_url,
            "test_name": match.name if match else "",
            "test_size": match.size if match and match.size is not None else "",
            "test_modified": match.modified.isoformat() if match and match.modified else "",
            "test_web_url": match.web_url if match else "",
            "confidence": bucket,
            "norm_ratio": sc.breakdown.get("norm_ratio", ""),
            "inv_po_overlap": "|".join(sc.breakdown.get("inv_po_overlap", []) or []),
            "vendor_overlap": "|".join(sc.breakdown.get("vendor_overlap", []) or []),
            "size_signal": sc.breakdown.get("size", ""),
            "modified_day_distance": sc.breakdown.get("modified_day_distance", "") if sc.breakdown.get("modified_day_distance") is not None else "",
            "previously_missed": prev,
        })

    write_output(out_csv, rows)

    # ---- stdout summary ----
    print()
    print("=== sharepoint_ap_compare summary ===")
    print(f"  prod docs:       {len(prod)}")
    print(f"  test docs:       {len(test)}")
    print(f"  exact_match:     {counts['exact_match']}")
    print(f"  likely_match:    {counts['likely_match']}")
    print(f"  possible_match:  {counts['possible_match']}")
    print(f"  no_match:        {counts['no_match']}")
    print(f"  output csv:      {out_csv}")

    if prior:
        prev_likely = [
            r for r in rows
            if r["confidence"] == "likely_match" and r["previously_missed"] == "yes"
        ]
        prev_possible = [
            r for r in rows
            if r["confidence"] == "possible_match" and r["previously_missed"] == "yes"
        ]
        print()
        print("=== previously-missed by strict matcher ===")
        print(f"  likely_match  previously_missed: {len(prev_likely)}")
        print(f"  possible_match previously_missed: {len(prev_possible)}")
        print()
        print(f"--- top {min(top_n, len(prev_likely))} likely_match rows previously missed ---")
        for r in prev_likely[:top_n]:
            print(f"  prod: {r['prod_name']!r}")
            print(f"  test: {r['test_name']!r}")
            print(f"    norm_ratio={r['norm_ratio']} inv_po={r['inv_po_overlap']!r} "
                  f"vendor={r['vendor_overlap']!r} size={r['size_signal']} "
                  f"modified_day_distance={r['modified_day_distance']}")
            print()

    # exit non-zero only if zero matches at all (the operationally meaningful red flag)
    if counts["exact_match"] + counts["likely_match"] + counts["possible_match"] == 0:
        print("RESULT: zero exact / likely / possible matches across both folders.", file=sys.stderr)
        print("This is the genuine red flag the operator was warned about.", file=sys.stderr)
        return 2
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Fuzzy SharePoint AP folder comparison.")
    ap.add_argument("--prod-csv", required=True, help="CSV listing of prod AP Temp Folder.")
    ap.add_argument("--test-csv", required=True, help="CSV listing of test destination.")
    ap.add_argument("--out-csv", default="sharepoint_ap_compare_out.csv", help="Output CSV path.")
    ap.add_argument("--prior-strict-csv", default=None, help="Optional prior strict-match CSV.")
    ap.add_argument("--top", type=int, default=25, help="Top-N previously-missed rows to print.")
    args = ap.parse_args(argv)
    return run(args.prod_csv, args.test_csv, args.out_csv, args.prior_strict_csv, args.top)


if __name__ == "__main__":
    raise SystemExit(main())
