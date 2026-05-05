"""
sharepoint_ap_compare.py — Fuzzy comparison of two SharePoint folder listings.

Purpose
-------
Prove whether prod AP Temp Folder and a test destination contain the same
documents, even when filenames are not byte-identical. The previous strict
filename comparison was returning 0 matches; that is almost certainly a
matcher problem, not a real-world overlap problem. This script replaces
the strict matcher with a multi-signal fuzzy scorer.

Two execution modes
-------------------
1. CSV mode (fallback): pass two pre-exported CSV listings.
2. --graph-pull mode (preferred): script pulls both folder listings live
   from SharePoint via Microsoft Graph using existing tenant credentials,
   removing the manual CSV-export step entirely.

Inputs (CSV mode)
-----------------
Each CSV must have at minimum these columns (header row required):
    name, size, modified
Optional columns (passed through if present):
    web_url, id, parent_path

`size`     — file size in bytes (int).
`modified` — ISO-8601 timestamp; tolerant of `Z` and offset forms.
             Empty cells are treated as unknown (date proximity then
             contributes 0 to scoring).

Inputs (--graph-pull mode)
--------------------------
Reuses the same env vars the backend already consumes for Graph API:
    TENANT_ID
    GRAPH_CLIENT_ID
    GRAPH_CLIENT_SECRET
    SHAREPOINT_SITE_HOSTNAME      (e.g. gamerpackaging.sharepoint.com)

Defaults are anchored on the locked production AP destination:
    site path:    /sites/GamerAccounting
    library:      Shared Documents
    folder path:  General/Accounting/Accounts Payable/Temp Folder

Test destination must be passed explicitly:
    --test-site-path        e.g. /sites/GPI-DocumentHub-Test
    --test-folder-path      e.g. Accounts Payable/Temp Folder
    --test-library          default: Shared Documents

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

Operator usage (preferred — single command, no manual export)
-------------------------------------------------------------
    docker compose exec -T backend python -m scripts.sharepoint_ap_compare \
        --graph-pull \
        --test-site-path "/sites/GPI-DocumentHub-Test" \
        --test-folder-path "Accounts Payable/Temp Folder" \
        --out-csv prod_reports/sp_ap_compare_fuzzy.csv \
        --top 25

Operator usage (CSV fallback — only when Graph creds are unavailable)
--------------------------------------------------------------------
    docker compose exec -T backend python -m scripts.sharepoint_ap_compare \
        --prod-csv prod_reports/sp_prod_ap_temp_listing.csv \
        --test-csv prod_reports/sp_test_ap_temp_listing.csv \
        --prior-strict-csv prod_reports/sp_strict_match_prev.csv \
        --out-csv prod_reports/sp_ap_compare_fuzzy.csv \
        --top 25

If --prior-strict-csv is omitted the "previously_missed" column is left
empty and the "previously missed" surfacing is skipped.

The script is read-only with respect to MongoDB and SharePoint. It only
reads from the two folder listings (CSV or Graph) and writes one output
CSV plus stdout. No production writes.
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
# Graph-pull mode (live SharePoint listings)
# ---------------------------------------------------------------------------

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Locked production AP destination (defaults for --graph-pull mode).
PROD_DEFAULT_SITE_PATH = "/sites/GamerAccounting"
PROD_DEFAULT_LIBRARY = "Shared Documents"
PROD_DEFAULT_FOLDER_PATH = "General/Accounting/Accounts Payable/Temp Folder"


def acquire_graph_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    """Client-credentials OAuth2 token for Microsoft Graph."""
    import httpx  # local import keeps CSV-only operators dep-free at import time
    if not (tenant_id and client_id and client_secret):
        raise SystemExit(
            "Graph creds missing. Set TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET "
            "in the environment (these are the same vars the backend already uses)."
        )
    with httpx.Client(timeout=30.0) as c:
        resp = c.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        data = resp.json()
        if "access_token" not in data:
            err = data.get("error_description", data.get("error", "unknown"))
            raise SystemExit(f"Graph token error: {err}")
        return data["access_token"]


def _graph_get(client: Any, url: str, token: str) -> Dict[str, Any]:
    resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code in (401, 403):
        raise SystemExit(
            f"Graph permission denied (HTTP {resp.status_code}). "
            f"App registration needs 'Sites.Read.All' (Application) with admin consent."
        )
    data = resp.json()
    if resp.status_code >= 400 or "error" in data:
        err = data.get("error", {})
        raise SystemExit(f"Graph error (HTTP {resp.status_code}): {err.get('message', err.get('code', data))}")
    return data


def pull_listing_via_graph(token: str, host: str, site_path: str,
                           library: str, folder_path: str,
                           label: str = "", recursive: bool = True,
                           max_depth: int = 25) -> List[Doc]:
    """List files under `library/folder_path` on `host:site_path` via Graph.

    Default is recursive (BFS) — the AP Temp Folder is nested in production
    by vendor / year / etc. Pass recursive=False for the legacy flat-only
    behavior. Returns a List[Doc] in the same shape CSV mode produces.

    `parent_path` (relative to the root folder being listed) is recorded on
    each Doc.raw for triage; it is not part of the comparison signals.
    """
    import httpx
    from urllib.parse import quote

    out: List[Doc] = []
    folders_visited = 0
    files_seen = 0

    with httpx.Client(timeout=60.0) as c:
        # 1. Resolve site
        site = _graph_get(c, f"{GRAPH_BASE}/sites/{host}:{site_path}:", token)
        if "id" not in site:
            raise SystemExit(f"Site not resolvable: {host}{site_path} ({label})")
        site_id = site["id"]

        # 2. Resolve drive (document library) by name
        drives = _graph_get(c, f"{GRAPH_BASE}/sites/{site_id}/drives", token).get("value", [])
        drive = next((d for d in drives if d.get("name") == library), None)
        if not drive:
            drive = next((d for d in drives if (d.get("name") or "").lower() == library.lower()), None)
        if not drive:
            alt = {"documents": "shared documents", "shared documents": "documents"}.get(library.lower())
            if alt:
                drive = next((d for d in drives if (d.get("name") or "").lower() == alt), None)
        if not drive:
            drive = next((d for d in drives if d.get("driveType") == "documentLibrary"), None)
        if not drive:
            raise SystemExit(
                f"Document library {library!r} not found ({label}). "
                f"Available: {[d.get('name') for d in drives]}"
            )
        drive_id = drive["id"]

        # 3. Resolve the root folder item by path so subsequent enumeration is by item id
        safe_path = quote(folder_path.strip("/"), safe="/")
        root_item = _graph_get(
            c,
            f"{GRAPH_BASE}/drives/{drive_id}/root:/{safe_path}?$select=id,name,folder",
            token,
        )
        if "id" not in root_item:
            raise SystemExit(f"Folder not resolvable: {folder_path!r} on {label}")
        if "folder" not in root_item:
            raise SystemExit(f"Path is not a folder: {folder_path!r} on {label}")
        root_item_id = root_item["id"]

        # 4. BFS enumeration. Each queued entry is (item_id, relative_path, depth).
        queue: List[Tuple[str, str, int]] = [(root_item_id, "", 0)]
        select_clause = "name,size,lastModifiedDateTime,webUrl,id,folder,file"

        while queue:
            folder_id, rel_path, depth = queue.pop(0)
            folders_visited += 1
            next_url: Optional[str] = (
                f"{GRAPH_BASE}/drives/{drive_id}/items/{folder_id}/children"
                f"?$top=999&$select={select_clause}"
            )
            while next_url:
                page = _graph_get(c, next_url, token)
                for item in page.get("value", []):
                    item_name = item.get("name") or ""
                    if "folder" in item:
                        if recursive and depth + 1 <= max_depth:
                            child_rel = (rel_path + "/" + item_name).strip("/") if rel_path else item_name
                            queue.append((item["id"], child_rel, depth + 1))
                        continue
                    files_seen += 1
                    row = {
                        "name": item_name,
                        "size": str(item.get("size") or ""),
                        "modified": item.get("lastModifiedDateTime") or "",
                        "web_url": item.get("webUrl") or "",
                        "id": item.get("id") or "",
                        "parent_path": rel_path,
                    }
                    out.append(Doc.from_row(row))
                next_url = page.get("@odata.nextLink")

    print(
        f"  graph-pull[{label}]: visited {folders_visited} folder(s), "
        f"{files_seen} file(s){' (flat)' if not recursive else ''}.",
        file=sys.stderr,
    )
    return out


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
        "prod_name", "prod_parent_path", "prod_size", "prod_modified", "prod_web_url",
        "test_name", "test_parent_path", "test_size", "test_modified", "test_web_url",
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

def run_with_docs(prod: List[Doc], test: List[Doc],
                  out_csv: str, prior: Dict[str, str], top_n: int,
                  source_label: str = "csv") -> int:
    print(f"Loaded {len(prod)} prod docs, {len(test)} test docs (source: {source_label}).", file=sys.stderr)
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
            "prod_parent_path": (p.raw.get("parent_path") or "").strip() if isinstance(p.raw, dict) else "",
            "prod_size": p.size if p.size is not None else "",
            "prod_modified": p.modified.isoformat() if p.modified else "",
            "prod_web_url": p.web_url,
            "test_name": match.name if match else "",
            "test_parent_path": (match.raw.get("parent_path") or "").strip() if (match and isinstance(match.raw, dict)) else "",
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
    print(f"  source:          {source_label}")
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


def run(prod_csv: str, test_csv: str, out_csv: str,
        prior_strict_csv: Optional[str], top_n: int) -> int:
    """CSV-mode entry point (kept for backward compat)."""
    prod = load_listing(prod_csv)
    test = load_listing(test_csv)
    prior = load_prior_strict(prior_strict_csv) if prior_strict_csv else {}
    return run_with_docs(prod, test, out_csv, prior, top_n,
                         source_label=f"csv ({prod_csv} | {test_csv})")


def run_graph(prod_site_path: str, prod_library: str, prod_folder_path: str,
              test_site_path: str, test_library: str, test_folder_path: str,
              out_csv: str, prior_strict_csv: Optional[str], top_n: int,
              recursive: bool, max_depth: int) -> int:
    """--graph-pull mode entry point (preferred)."""
    import os
    tenant = os.environ.get("TENANT_ID", "")
    client_id = os.environ.get("GRAPH_CLIENT_ID", "")
    client_secret = os.environ.get("GRAPH_CLIENT_SECRET", "")
    host = os.environ.get("SHAREPOINT_SITE_HOSTNAME", "gamerpackaging.sharepoint.com")

    if os.environ.get("DEMO_MODE", "true").lower() == "true":
        raise SystemExit(
            "DEMO_MODE=true detected. Graph-pull requires a real tenant. "
            "Run on the prod VM where DEMO_MODE=false."
        )

    token = acquire_graph_token(tenant, client_id, client_secret)
    print(f"Graph token acquired. Host: {host}", file=sys.stderr)
    print(
        f"Pulling prod (recursive={recursive}, max_depth={max_depth}): "
        f"{host}{prod_site_path} :: {prod_library} :: {prod_folder_path}",
        file=sys.stderr,
    )
    prod = pull_listing_via_graph(
        token, host, prod_site_path, prod_library, prod_folder_path,
        label="prod", recursive=recursive, max_depth=max_depth,
    )
    print(
        f"Pulling test (recursive={recursive}, max_depth={max_depth}): "
        f"{host}{test_site_path} :: {test_library} :: {test_folder_path}",
        file=sys.stderr,
    )
    test = pull_listing_via_graph(
        token, host, test_site_path, test_library, test_folder_path,
        label="test", recursive=recursive, max_depth=max_depth,
    )

    prior = load_prior_strict(prior_strict_csv) if prior_strict_csv else {}
    label = (f"graph-pull (prod={prod_site_path}/{prod_folder_path} | "
             f"test={test_site_path}/{test_folder_path} | recursive={recursive})")
    return run_with_docs(prod, test, out_csv, prior, top_n, source_label=label)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Fuzzy SharePoint AP folder comparison.")
    # Mode selector
    ap.add_argument("--graph-pull", action="store_true",
                    help="Pull both folder listings live via Microsoft Graph API "
                         "(preferred). Requires TENANT_ID, GRAPH_CLIENT_ID, "
                         "GRAPH_CLIENT_SECRET, SHAREPOINT_SITE_HOSTNAME env vars.")
    # CSV-mode args
    ap.add_argument("--prod-csv", default=None, help="CSV listing of prod AP Temp Folder (CSV mode).")
    ap.add_argument("--test-csv", default=None, help="CSV listing of test destination (CSV mode).")
    # Graph-pull-mode args
    ap.add_argument("--prod-site-path", default=PROD_DEFAULT_SITE_PATH,
                    help=f"Prod SharePoint site path (default: {PROD_DEFAULT_SITE_PATH}).")
    ap.add_argument("--prod-library", default=PROD_DEFAULT_LIBRARY,
                    help=f"Prod document library name (default: {PROD_DEFAULT_LIBRARY!r}).")
    ap.add_argument("--prod-folder-path", default=PROD_DEFAULT_FOLDER_PATH,
                    help=f"Prod folder path inside library (default: {PROD_DEFAULT_FOLDER_PATH!r}).")
    ap.add_argument("--test-site-path", default=None,
                    help="Test SharePoint site path. REQUIRED with --graph-pull.")
    ap.add_argument("--test-library", default=PROD_DEFAULT_LIBRARY,
                    help=f"Test document library name (default: {PROD_DEFAULT_LIBRARY!r}).")
    ap.add_argument("--test-folder-path", default=None,
                    help="Test folder path inside library. REQUIRED with --graph-pull.")
    # Common args
    ap.add_argument("--out-csv", default="sharepoint_ap_compare_out.csv", help="Output CSV path.")
    ap.add_argument("--prior-strict-csv", default=None, help="Optional prior strict-match CSV.")
    ap.add_argument("--top", type=int, default=25, help="Top-N previously-missed rows to print.")
    ap.add_argument("--no-recursive", action="store_true",
                    help="Graph-pull only: disable recursive folder walk (legacy flat behavior).")
    ap.add_argument("--max-depth", type=int, default=25,
                    help="Graph-pull only: max recursion depth (default: 25).")
    args = ap.parse_args(argv)

    if args.graph_pull:
        if args.prod_csv or args.test_csv:
            raise SystemExit("--graph-pull is incompatible with --prod-csv / --test-csv. Pick one mode.")
        if not args.test_site_path or not args.test_folder_path:
            raise SystemExit(
                "--graph-pull requires --test-site-path and --test-folder-path. "
                "Prod defaults to the locked AP destination "
                "(/sites/GamerAccounting :: Shared Documents :: "
                "General/Accounting/Accounts Payable/Temp Folder); override with "
                "--prod-site-path / --prod-library / --prod-folder-path if needed."
            )
        return run_graph(
            args.prod_site_path, args.prod_library, args.prod_folder_path,
            args.test_site_path, args.test_library, args.test_folder_path,
            args.out_csv, args.prior_strict_csv, args.top,
            recursive=(not args.no_recursive), max_depth=args.max_depth,
        )

    if not (args.prod_csv and args.test_csv):
        raise SystemExit(
            "CSV mode requires --prod-csv and --test-csv. "
            "Or pass --graph-pull (preferred) to skip the export step."
        )
    return run(args.prod_csv, args.test_csv, args.out_csv, args.prior_strict_csv, args.top)


if __name__ == "__main__":
    raise SystemExit(main())
