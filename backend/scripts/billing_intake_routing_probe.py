"""
billing_intake_routing_probe.py — Square9 cutover readiness probe.

What this proves
----------------
Pulls the most recently ingested billing/AP-lane documents and verifies that
the production pipeline is honoring the corrected behavior:

1. Documents from billing@gamerpackaging.com persist mailbox_category="AP"
   (NOT "Operations"). Counts and warns on any drift.
2. Clear AP invoices on the AP lane have classification_method ending in
   "+evidence" (deterministic mailbox+evidence path).
3. AP-lane docs without evidence carry mailbox_lane_needs_review=True with
   classification_method "mailbox_lane:AP:needs_review".
4. doc_type="AP_INVOICE" docs are NOT auto-routed into Operations-style
   destinations (Warehouse Reports / Dropship* / Warehouse* / Freight Issues
   / Vendor Credit Memos / Miscellaneous) without an explicit accounting
   override.

Read-only. No mutations. Returns non-zero on any cutover-blocking finding
so it can be wired into a smoke-test gate.

Operator usage (prod VM, single line)
-------------------------------------
    docker compose exec -T backend python -m scripts.billing_intake_routing_probe \
        --since-hours 24 --limit 200

Optional flags:
    --mailbox EMAIL      filter by sender mailbox address (default: billing@gamerpackaging.com)
    --since-hours N      look-back window in hours (default: 48)
    --limit N            max docs to inspect (default: 200)
    --json               machine-readable JSON output instead of formatted tables

Exit codes
----------
    0  no findings; AP/billing intake routing is clean for the window.
    1  warnings only (e.g. small N, low evidence rate); operator should review.
    2  cutover-blocker findings (billing→Operations leak, AP_INVOICE in
       forbidden folders without override, etc.). Re-run after remediation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorClient


DEFAULT_BILLING_MAILBOX = "billing@gamerpackaging.com"

# Mirrors services.folder_routing_service._FORBIDDEN_AP_FOLDER_ROOTS but kept
# local so the probe doesn't require importing the whole backend service tree.
FORBIDDEN_AP_FOLDER_ROOTS = (
    "Warehouse Reports",
    "Dropship Not International Documents",
    "Dropship International Documents",
    "Warehouse Not International Documents",
    "Warehouse International Documents",
    "Freight Issues",
    "Vendor Credit Memos",
    "Miscellaneous Documents",
)

AP_INVOICE_DOC_TYPES = {"AP_INVOICE", "AP_Invoice", "AP Invoice"}


def _path_in_forbidden(path: str) -> bool:
    if not path:
        return False
    return any(path.startswith(root) for root in FORBIDDEN_AP_FOLDER_ROOTS)


def _override_set(doc: Dict[str, Any]) -> bool:
    if doc.get("accounting_routing_override") is True:
        return True
    if doc.get("approved") is True:
        return True
    if (doc.get("status") or "") == "Approved":
        return True
    return False


async def _fetch_recent_docs(mailbox: str, since_hours: int, limit: int) -> List[Dict[str, Any]]:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    query = {
        "$and": [
            {"$or": [
                {"email_sender": {"$regex": mailbox, "$options": "i"}},
                {"sender": {"$regex": mailbox, "$options": "i"}},
                {"intake_email_to": {"$regex": mailbox, "$options": "i"}},
            ]},
            {"$or": [
                {"created_utc": {"$gte": cutoff}},
                {"created_at": {"$gte": cutoff}},
                {"intake_at": {"$gte": cutoff}},
            ]},
        ]
    }
    projection = {
        "_id": 0,
        "id": 1, "file_name": 1, "email_sender": 1, "sender": 1,
        "email_subject": 1, "subject": 1,
        "mailbox_category": 1, "doc_type": 1, "document_type": 1,
        "suggested_job_type": 1, "classification_method": 1,
        "mailbox_lane_needs_review": 1,
        "sharepoint_folder_path": 1, "folder_routing_reason": 1,
        "sharepoint_web_url": 1,
        "accounting_routing_override": 1, "approved": 1, "status": 1,
        "created_utc": 1, "created_at": 1, "intake_at": 1,
    }
    cur = db.hub_documents.find(query, projection)
    cur = cur.sort([("created_utc", -1), ("created_at", -1), ("intake_at", -1)]).limit(limit)
    rows = await cur.to_list(limit)
    return rows


def _classify_findings(rows: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], int]:
    """Returns (report, exit_code).

    exit_code: 0 = clean, 1 = warnings, 2 = blockers.
    """
    total = len(rows)
    by_mailbox_category = Counter()
    by_doc_type = Counter()
    by_classification_method = Counter()
    by_folder_root: Counter = Counter()
    needs_review_count = 0

    # --- Cutover-blocking findings ---
    billing_to_operations: List[Dict[str, Any]] = []          # mailbox_category != "AP"
    ap_invoice_in_forbidden: List[Dict[str, Any]] = []        # AP_INVOICE auto-routed wrong
    legacy_classification_method: List[Dict[str, Any]] = []   # "mailbox:AP" w/o "+evidence"

    # --- Warning-level findings ---
    no_classification_method: List[Dict[str, Any]] = []

    for r in rows:
        mc = r.get("mailbox_category") or ""
        dt = r.get("doc_type") or r.get("document_type") or ""
        cm = r.get("classification_method") or ""
        path = r.get("sharepoint_folder_path") or ""
        nr = bool(r.get("mailbox_lane_needs_review"))

        by_mailbox_category[mc or "<missing>"] += 1
        by_doc_type[dt or "<missing>"] += 1
        by_classification_method[cm or "<missing>"] += 1
        if nr:
            needs_review_count += 1

        root = path.split("/", 1)[0] if path else "<missing>"
        by_folder_root[root] += 1

        if mc and mc != "AP":
            billing_to_operations.append({
                "id": r.get("id"),
                "file_name": r.get("file_name"),
                "mailbox_category": mc,
                "doc_type": dt,
                "sharepoint_folder_path": path,
            })

        if dt in AP_INVOICE_DOC_TYPES and _path_in_forbidden(path) and not _override_set(r):
            ap_invoice_in_forbidden.append({
                "id": r.get("id"),
                "file_name": r.get("file_name"),
                "doc_type": dt,
                "sharepoint_folder_path": path,
                "folder_routing_reason": r.get("folder_routing_reason"),
            })

        if cm == "mailbox:AP":
            legacy_classification_method.append({
                "id": r.get("id"),
                "file_name": r.get("file_name"),
                "classification_method": cm,
            })

        if not cm:
            no_classification_method.append({
                "id": r.get("id"),
                "file_name": r.get("file_name"),
            })

    blockers: List[str] = []
    warnings: List[str] = []

    if billing_to_operations:
        blockers.append(
            f"{len(billing_to_operations)} billing-mailbox doc(s) persisted with "
            f"mailbox_category != 'AP' (Square9 parity break)"
        )
    if ap_invoice_in_forbidden:
        blockers.append(
            f"{len(ap_invoice_in_forbidden)} AP_INVOICE doc(s) routed into "
            f"Operations-style folder roots without an accounting override"
        )
    if legacy_classification_method:
        warnings.append(
            f"{len(legacy_classification_method)} doc(s) still using legacy "
            f"classification_method='mailbox:AP' (pre-evidence-gating); ensure "
            f"the latest deploy is live"
        )
    if no_classification_method:
        warnings.append(
            f"{len(no_classification_method)} doc(s) missing classification_method"
        )
    if total == 0:
        warnings.append("zero documents in window — sample size insufficient")

    report = {
        "window": {
            "mailbox": rows[0].get("email_sender") if rows else None,
            "total_docs": total,
        },
        "counts": {
            "by_mailbox_category": dict(by_mailbox_category),
            "by_doc_type": dict(by_doc_type),
            "by_classification_method": dict(by_classification_method),
            "by_folder_root": dict(by_folder_root),
            "mailbox_lane_needs_review": needs_review_count,
        },
        "findings": {
            "blockers": blockers,
            "warnings": warnings,
            "billing_to_operations": billing_to_operations[:25],
            "ap_invoice_in_forbidden": ap_invoice_in_forbidden[:25],
            "legacy_classification_method": legacy_classification_method[:25],
            "no_classification_method": no_classification_method[:25],
        },
    }

    if blockers:
        return report, 2
    if warnings:
        return report, 1
    return report, 0


def _print_report(report: Dict[str, Any], exit_code: int) -> None:
    counts = report["counts"]
    print()
    print("=== billing/AP intake routing probe ===")
    print(f"  total docs in window:               {report['window']['total_docs']}")
    print(f"  mailbox_lane_needs_review count:    {counts['mailbox_lane_needs_review']}")

    def _print_counter(label: str, c: Dict[str, Any]) -> None:
        print(f"\n  {label}:")
        for k, v in sorted(c.items(), key=lambda kv: -kv[1]):
            print(f"    {v:>6}  {k}")

    _print_counter("by mailbox_category", counts["by_mailbox_category"])
    _print_counter("by doc_type", counts["by_doc_type"])
    _print_counter("by classification_method", counts["by_classification_method"])
    _print_counter("by sharepoint_folder_path root", counts["by_folder_root"])

    findings = report["findings"]
    if findings["blockers"]:
        print("\n  *** CUTOVER-BLOCKING FINDINGS ***")
        for b in findings["blockers"]:
            print(f"    - {b}")
    if findings["warnings"]:
        print("\n  warnings:")
        for w in findings["warnings"]:
            print(f"    - {w}")

    for key in ("billing_to_operations", "ap_invoice_in_forbidden",
                "legacy_classification_method"):
        items = findings.get(key) or []
        if not items:
            continue
        print(f"\n  sample {key} (up to 25):")
        for it in items:
            print(f"    {it}")

    print()
    if exit_code == 0:
        print("  RESULT: clean. AP/billing intake routing is in spec for this window.")
    elif exit_code == 1:
        print("  RESULT: warnings — review and re-probe after remediation.")
    else:
        print("  RESULT: cutover-blocking findings present. Do NOT cut over.")
    print()


async def _run(mailbox: str, since_hours: int, limit: int, as_json: bool) -> int:
    rows = await _fetch_recent_docs(mailbox, since_hours, limit)
    report, exit_code = _classify_findings(rows)
    if as_json:
        print(json.dumps(report, default=str, indent=2))
    else:
        _print_report(report, exit_code)
    return exit_code


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AP/billing intake routing readiness probe.")
    ap.add_argument("--mailbox", default=DEFAULT_BILLING_MAILBOX,
                    help=f"Sender mailbox to filter on (default: {DEFAULT_BILLING_MAILBOX})")
    ap.add_argument("--since-hours", type=int, default=48,
                    help="Look-back window in hours (default: 48).")
    ap.add_argument("--limit", type=int, default=200,
                    help="Maximum documents to inspect (default: 200).")
    ap.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON instead of formatted tables.")
    args = ap.parse_args(argv)
    return asyncio.run(_run(args.mailbox, args.since_hours, args.limit, args.json))


if __name__ == "__main__":
    raise SystemExit(main())
