"""
recycle_bin_deletion_check.py — quantifies how much of the parity
report's hub_only pile is explained by Square9 deleting documents as
AP processes them, rather than genuine gaps.

Why this exists (2026-07-17): Chad flagged that Square9's prod side
deletes documents as the accounting team processes them. Confirmed
directly: the site recycle bin (/sites/GamerAccounting) is full of AP
invoice PDFs with deletion timestamps inside the same window the
readiness check compares against - including vendor patterns
(_BallMetalBeverageContainer_*) that have shown up as hub_only in
nearly every run tonight.

This matters because match_rate = matched / square_count, and if a
document is processed and deleted from Square9 before our snapshot
runs, it never gets to count as either. Worse, the documents STILL
sitting in Square9 at snapshot time are disproportionately the ones
AP hasn't gotten to yet - probably the messier, harder cases - which
means the comparison pool itself may be biased toward hard documents,
not a representative sample. This script doesn't fix that bias (that
would mean redesigning the comparison method itself, a bigger
conversation), but it does quantify one visible symptom of it: how
many hub_only documents actually did exist in Square9 and were simply
deleted before the snapshot could credit them as a match.

Method: pull hub_only rows from the latest parity CSV, pull the
Square9 site recycle bin (paginated, filtered client-side to the same
window the parity run used), and check for invoice/vendor token
overlap between each hub_only document and each recently-deleted
Square9 item, using the exact same token-extraction functions the
deterministic matcher itself uses - not a new, separate heuristic.

This is read-only and diagnostic only - it does not change match_rate,
does not write anywhere, and does not feed the readiness decision. It
answers "how much of the gap is this" so that question doesn't have
to be answered by eyeballing filenames.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sharepoint_ap_compare import (  # type: ignore
    acquire_graph_token,
    extract_invoice_po_tokens,
    extract_vendor_tokens,
)

PROD_SITE_PATH = "/sites/GamerAccounting"


def load_hub_only_rows(csv_path: str) -> List[Dict[str, str]]:
    if not os.path.exists(csv_path):
        print(f"ERROR: {csv_path} not found. Run square9_hub_ap_parity_report.py first.",
              file=sys.stderr)
        sys.exit(1)
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r.get("match_bucket") == "hub_only"]


def pull_recycle_bin_items(
    token: str, host: str, site_path: str, since_hours: int,
) -> List[Dict[str, Any]]:
    """Paginated pull of recently-deleted items from the Square9 prod
    site's recycle bin, filtered client-side to the comparison window.

    Does NOT assume any sort order from the API and does NOT stop
    early on the first out-of-window item - verified directly against
    real data that results come back in no reliable date order at all
    (a raw, unfiltered pull showed April/June/July timestamps
    interleaved with no pattern), so an early-stop-on-first-old-item
    approach silently returns near-zero results even when the target
    window's items are present later in the same page. Instead this
    pages through up to the safety cap and keeps every item inside the
    window regardless of where in the result set it appears."""
    import httpx

    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    headers = {"Authorization": f"Bearer {token}"}
    items: List[Dict[str, Any]] = []
    pages_scanned = 0
    total_items_scanned = 0

    with httpx.Client(timeout=30.0) as c:
        site_resp = c.get(
            f"https://graph.microsoft.com/v1.0/sites/{host}:{site_path}",
            headers=headers,
        )
        site_resp.raise_for_status()
        site_id = site_resp.json()["id"]

        url = f"https://graph.microsoft.com/beta/sites/{site_id}/recycleBin/items"
        params = {"$top": 200}
        while url and pages_scanned < 25:  # hard safety cap - never loop forever
            pages_scanned += 1
            resp = c.get(url, headers=headers, params=params if pages_scanned == 1 else None)
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("value", [])
            total_items_scanned += len(batch)
            for it in batch:
                deleted_str = it.get("deletedDateTime")
                if not deleted_str:
                    continue
                try:
                    deleted_dt = datetime.fromisoformat(
                        deleted_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    continue
                if deleted_dt >= cutoff:
                    items.append(it)
            url = data.get("@odata.nextLink")
            params = None  # nextLink already carries params

    print(
        f"[recycle_bin] scanned {pages_scanned} page(s), "
        f"{total_items_scanned} item(s) total, "
        f"{len(items)} within the last {since_hours}h window.",
        file=sys.stderr,
    )
    return items


def tokens_for_hub_row(row: Dict[str, str]) -> Dict[str, Set[str]]:
    name = row.get("hub_file_name", "")
    inv_clean = (row.get("hub_invoice_number_clean") or "").strip()
    vendor = (row.get("hub_vendor_canonical") or "").strip()

    inv_tokens = set(extract_invoice_po_tokens(name))
    if inv_clean:
        inv_tokens.add(inv_clean.upper().lstrip("0"))

    vendor_tokens = set(extract_vendor_tokens(name))
    vendor_tokens |= {t.lower() for t in vendor.split() if len(t) >= 3}

    return {"invoice": inv_tokens, "vendor": vendor_tokens}


def tokens_for_deleted_item(name: str) -> Dict[str, Set[str]]:
    return {
        "invoice": set(extract_invoice_po_tokens(name)),
        "vendor": set(extract_vendor_tokens(name)),
    }


def find_recycle_bin_evidence(
    hub_only_rows: List[Dict[str, str]], deleted_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    deleted_tokenized = [
        (it, tokens_for_deleted_item(it.get("name", "")))
        for it in deleted_items
    ]

    explained: List[Dict[str, Any]] = []
    unexplained: List[Dict[str, str]] = []

    for row in hub_only_rows:
        row_tokens = tokens_for_hub_row(row)
        best_match: Optional[Dict[str, Any]] = None

        for item, item_tokens in deleted_tokenized:
            invoice_overlap = row_tokens["invoice"] & item_tokens["invoice"]
            if invoice_overlap:
                best_match = {
                    "deleted_item_name": item.get("name"),
                    "deleted_at": item.get("deletedDateTime"),
                    "match_reason": "invoice_token_overlap",
                    "shared_tokens": sorted(invoice_overlap),
                }
                break  # invoice token overlap is strong enough to stop here

        if best_match is None:
            # Fall back to vendor-token-only overlap - weaker evidence,
            # recorded distinctly so it's never confused with the
            # stronger invoice-token signal above.
            for item, item_tokens in deleted_tokenized:
                vendor_overlap = row_tokens["vendor"] & item_tokens["vendor"]
                if vendor_overlap and len(vendor_overlap) >= 1:
                    best_match = {
                        "deleted_item_name": item.get("name"),
                        "deleted_at": item.get("deletedDateTime"),
                        "match_reason": "vendor_token_overlap_only",
                        "shared_tokens": sorted(vendor_overlap),
                    }
                    break

        if best_match:
            explained.append({
                "hub_file_name": row.get("hub_file_name"),
                "hub_doc_id": row.get("hub_doc_id"),
                "hub_vendor_canonical": row.get("hub_vendor_canonical"),
                "hub_invoice_number_clean": row.get("hub_invoice_number_clean"),
                **best_match,
            })
        else:
            unexplained.append({
                "hub_file_name": row.get("hub_file_name"),
                "hub_doc_id": row.get("hub_doc_id"),
                "hub_vendor_canonical": row.get("hub_vendor_canonical"),
                "hub_invoice_number_clean": row.get("hub_invoice_number_clean"),
            })

    total = len(hub_only_rows)
    strong = [e for e in explained if e["match_reason"] == "invoice_token_overlap"]
    weak = [e for e in explained if e["match_reason"] == "vendor_token_overlap_only"]

    return {
        "total_hub_only": total,
        "explained_by_recent_deletion_strong": len(strong),
        "explained_by_recent_deletion_weak": len(weak),
        "explained_total": len(explained),
        "unexplained": len(unexplained),
        "explained_pct": round(100 * len(explained) / total, 1) if total else 0.0,
        "recycle_bin_items_checked": len(deleted_items),
        "strong_examples": strong[:15],
        "weak_examples": weak[:15],
        "unexplained_sample": unexplained[:20],
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Quantify how much of hub_only is explained by "
                     "Square9 deleting documents as they're processed."
    )
    ap.add_argument("--parity-csv", default="prod_reports/square9_hub_ap_parity.csv")
    ap.add_argument("--since-hours", type=int, default=168,
                     help="Should match the parity run's own --since-hours.")
    ap.add_argument("--prod-site-path", default=PROD_SITE_PATH)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    hub_only_rows = load_hub_only_rows(args.parity_csv)
    if not hub_only_rows:
        print("No hub_only rows found in the parity CSV - nothing to check.")
        return 0

    tenant = os.environ.get("TENANT_ID")
    cid = os.environ.get("GRAPH_CLIENT_ID")
    csec = os.environ.get("GRAPH_CLIENT_SECRET")
    token = acquire_graph_token(tenant, cid, csec)
    host = os.environ.get(
        "SHAREPOINT_HOST",
        f"{(os.environ.get('SHAREPOINT_TENANT_NAME') or 'gamerpackaging1')}.sharepoint.com",
    )

    deleted_items = pull_recycle_bin_items(
        token, host, args.prod_site_path, args.since_hours,
    )

    result = find_recycle_bin_evidence(hub_only_rows, deleted_items)

    if args.json:
        print(json.dumps(result, default=str, indent=2))
        return 0

    print("=== recycle_bin_deletion_check ===")
    print(f"  total_hub_only:                    {result['total_hub_only']}")
    print(f"  recycle_bin_items_checked:         {result['recycle_bin_items_checked']}  "
          f"(deleted within last {args.since_hours}h)")
    print(f"  explained_by_recent_deletion:")
    print(f"    strong (invoice token match):    {result['explained_by_recent_deletion_strong']}")
    print(f"    weak (vendor token only):        {result['explained_by_recent_deletion_weak']}")
    print(f"    total explained:                 {result['explained_total']}  "
          f"({result['explained_pct']}% of hub_only)")
    print(f"  unexplained (genuinely no Square9 trace found): {result['unexplained']}")
    print()
    if result["strong_examples"]:
        print("  STRONG EVIDENCE (invoice number match against a deleted item):")
        for e in result["strong_examples"]:
            print(f"    {e['hub_file_name']!r}  ↔  deleted {e['deleted_item_name']!r} "
                  f"at {e['deleted_at']}  (shared: {e['shared_tokens']})")
    if result["weak_examples"]:
        print()
        print("  WEAKER EVIDENCE (vendor name only - review before trusting):")
        for e in result["weak_examples"]:
            print(f"    {e['hub_file_name']!r}  ↔  deleted {e['deleted_item_name']!r} "
                  f"at {e['deleted_at']}  (shared: {e['shared_tokens']})")
    if result["unexplained_sample"]:
        print()
        print("  UNEXPLAINED SAMPLE (no recycle bin trace - genuinely worth investigating):")
        for u in result["unexplained_sample"]:
            print(f"    {u['hub_file_name']!r}  vendor={u['hub_vendor_canonical']!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
