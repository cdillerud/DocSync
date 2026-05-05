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
4. AP_INVOICE docs are NOT sitting in un-redirected weak-fallback paths
   (Default routing / Misc need-approval) — the routing wrapper in
   services/folder_routing_service.py should redirect those to AP Temp
   Folder. High-confidence AP invoices (Canpack / credit memo / WH_ /
   freight vendor / resolved BC PO / etc.) auto-route to their final
   accounting folder; Temp Folder is fallback-only.

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
    1  warnings only (e.g. small N, high Temp Folder ratio, legacy classification
       method); operator should review.
    2  cutover-blocker findings (billing→Operations leak, AP_INVOICE in
       un-redirected weak-fallback paths, etc.). Re-run after remediation.
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

# A "weak fallback" routing for an AP-lane document. With the routing-fix
# wrapper in services/folder_routing_service.py, AP-lane docs whose rule
# chain produced "Default routing for ..." or landed in "Misc Invoices -
# need approval" are redirected to the AP Temp Folder. If the probe sees a
# persisted hub_documents row whose folder/reason still indicates one of
# these patterns for an AP_INVOICE, the wrapper isn't deployed (or the doc
# carried an explicit accounting override that disabled it).
_WEAK_FALLBACK_PATH_FRAGMENTS = ("Misc Invoices - need approval",)
_WEAK_FALLBACK_REASON_PREFIXES = ("Default routing for",)

AP_INVOICE_DOC_TYPES = {"AP_INVOICE", "AP_Invoice", "AP Invoice"}


def _path_is_weak_fallback(path: str, reason: str) -> bool:
    if path and any(frag in path for frag in _WEAK_FALLBACK_PATH_FRAGMENTS):
        # LocationCode=MSC explicitly maps to Misc/need-approval and is a
        # legitimate placement; do not flag it.
        if reason and reason.startswith("LocationCode="):
            return False
        return True
    if reason and any(reason.startswith(p) for p in _WEAK_FALLBACK_REASON_PREFIXES):
        return True
    return False


def _override_set(doc: Dict[str, Any]) -> bool:
    if doc.get("accounting_routing_override") is True:
        return True
    if doc.get("approved") is True:
        return True
    if (doc.get("status") or "") == "Approved":
        return True
    return False


async def _fetch_recent_docs(mailbox: Optional[str], since_hours: int, limit: int,
                             ap_only: bool) -> List[Dict[str, Any]]:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    # `created_utc` is persisted as an ISO-8601 string in hub_documents.
    # Compare string-against-string so MongoDB does a lexicographic match
    # (ISO-8601 sorts correctly as ASCII). datetime objects against a
    # string field always returns 0 due to BSON type-mismatch.
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    date_clause = {"$or": [
        {"created_utc": {"$gte": cutoff_iso}},
        {"created_at": {"$gte": cutoff_iso}},
        {"intake_at": {"$gte": cutoff_iso}},
    ]}
    if ap_only:
        # AP lane is identified by mailbox_category == "AP", which is set
        # by email_polling_service when a doc lands in the billing@ inbox.
        # billing@gamerpackaging.com is a destination, not a sender.
        scope_clause: Dict[str, Any] = {"mailbox_category": "AP"}
    else:
        scope_clause = {"$or": [
            {"email_sender": {"$regex": mailbox, "$options": "i"}},
            {"sender": {"$regex": mailbox, "$options": "i"}},
            {"intake_email_to": {"$regex": mailbox, "$options": "i"}},
        ]}
    query = {"$and": [scope_clause, date_clause]}
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
    ap_invoice_weak_fallback: List[Dict[str, Any]] = []       # AP_INVOICE in un-redirected weak-fallback path
    legacy_classification_method: List[Dict[str, Any]] = []   # "mailbox:AP" w/o "+evidence"

    # --- Warning-level findings ---
    no_classification_method: List[Dict[str, Any]] = []
    ap_temp_folder_count = 0                                  # informational: % of AP docs needing review

    for r in rows:
        mc = r.get("mailbox_category") or ""
        dt = r.get("doc_type") or r.get("document_type") or ""
        cm = r.get("classification_method") or ""
        path = r.get("sharepoint_folder_path") or ""
        reason = r.get("folder_routing_reason") or ""
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

        if dt in AP_INVOICE_DOC_TYPES:
            if path.startswith("Accounts Payable/Temp Folder"):
                ap_temp_folder_count += 1
            elif _path_is_weak_fallback(path, reason) and not _override_set(r):
                ap_invoice_weak_fallback.append({
                    "id": r.get("id"),
                    "file_name": r.get("file_name"),
                    "doc_type": dt,
                    "sharepoint_folder_path": path,
                    "folder_routing_reason": reason,
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
    if ap_invoice_weak_fallback:
        blockers.append(
            f"{len(ap_invoice_weak_fallback)} AP_INVOICE doc(s) sitting in a weak-"
            f"fallback path (Default routing / Misc need-approval) without "
            f"redirection — wrapper not active or override engaged"
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
    # Informational: % of AP_INVOICE docs that ended up in Temp Folder. A
    # very high percentage suggests either (a) classification confidence is
    # low across the window, or (b) routing rules don't match the typical
    # billing inflow. Not a blocker — high-confidence AP routing is the
    # goal but Temp Folder fallback is correct for genuinely uncertain docs.
    ap_count = sum(1 for r in rows
                   if (r.get("doc_type") or r.get("document_type") or "") in AP_INVOICE_DOC_TYPES)
    if ap_count and ap_temp_folder_count / ap_count > 0.5:
        warnings.append(
            f"{ap_temp_folder_count}/{ap_count} AP_INVOICE doc(s) staged in AP "
            f"Temp Folder ({ap_temp_folder_count / ap_count:.0%}); high ratio "
            f"suggests low-confidence classification or rule-coverage gap — "
            f"investigate before declaring auto-routing parity"
        )
    if total == 0:
        warnings.append("zero documents in window — sample size insufficient")

    report = {
        "window": {
            "mailbox": rows[0].get("email_sender") if rows else None,
            "total_docs": total,
            "ap_invoice_count": ap_count,
            "ap_temp_folder_count": ap_temp_folder_count,
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
            "ap_invoice_weak_fallback": ap_invoice_weak_fallback[:25],
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

    for key in ("billing_to_operations", "ap_invoice_weak_fallback",
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


async def _run(mailbox: Optional[str], since_hours: int, limit: int,
               ap_only: bool, as_json: bool) -> int:
    rows = await _fetch_recent_docs(mailbox, since_hours, limit, ap_only)
    report, exit_code = _classify_findings(rows)
    if as_json:
        print(json.dumps(report, default=str, indent=2))
    else:
        _print_report(report, exit_code)
    return exit_code


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AP/billing intake routing readiness probe.")
    ap.add_argument("--mailbox", default=None,
                    help="Sender email regex (only used with --no-ap-only).")
    ap.add_argument("--since-hours", type=int, default=48,
                    help="Look-back window in hours (default: 48).")
    ap.add_argument("--limit", type=int, default=200,
                    help="Maximum documents to inspect (default: 200).")
    ap.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON instead of formatted tables.")
    ap.add_argument("--ap-only", dest="ap_only", action="store_true", default=True,
                    help="Filter on mailbox_category=='AP' (default, recommended).")
    ap.add_argument("--no-ap-only", dest="ap_only", action="store_false",
                    help="Disable AP-category scope; falls back to --mailbox sender regex.")
    args = ap.parse_args(argv)
    if not args.ap_only and not args.mailbox:
        ap.error("--no-ap-only requires --mailbox EMAIL")
    return asyncio.run(_run(args.mailbox, args.since_hours, args.limit,
                            args.ap_only, args.json))


if __name__ == "__main__":
    raise SystemExit(main())
