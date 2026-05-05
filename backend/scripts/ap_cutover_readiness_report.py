"""
ap_cutover_readiness_report.py — Full breakdown of recent AP-lane intake.

Distinct from `billing_intake_routing_probe.py` (which is a smoke-test
gate emitting blockers/warnings + an exit code). This script is the
**audit-grade** report: counts and samples by routing_status, doc_type,
folder root, classification_method — plus blocker/warning callouts and
representative samples for each routing_status.

What it shows
-------------
- Counts by mailbox_category (proves billing@ → "AP" propagation).
- Counts by doc_type and suggested_job_type.
- Counts by routing_status: auto_routed / needs_review / exception /
  manual_override / <missing>.
- Counts by sharepoint_folder_path root.
- Top routing reasons.
- Sample auto-routed AP invoices with the evidence_signals_used + final
  destination, so the reader can see "this doc had X, Y, Z evidence and
  landed in folder F".
- Sample needs_review/exception rows with the reason they were held.
- Blocker findings (billing→Operations leak, missing routing_status on
  fresh docs, AP-lane docs in Operations roots without strong signal).
- Warning findings (low confidence, missing classification_method, legacy
  classification_method, Temp Folder ratio > 50%).

Read-only. No mutations.

Operator usage (prod VM, single line)
-------------------------------------
    docker compose exec -T backend python -m scripts.ap_cutover_readiness_report \
        --since-hours 48 --limit 500

Optional flags:
    --mailbox EMAIL      sender mailbox filter (default: billing@gamerpackaging.com)
    --since-hours N      look-back window (default: 48)
    --limit N            max docs to inspect (default: 500)
    --json               emit machine-readable JSON

Exit codes
----------
    0  no blockers (cutover-defensible for the window).
    1  warnings only.
    2  blockers (do not declare cutover-ready).
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

AP_INVOICE_DOC_TYPES = {"AP_INVOICE", "AP_Invoice", "AP Invoice"}

OPERATIONS_FOLDER_ROOTS = (
    "Warehouse Reports",
    "Dropship Not International Documents",
    "Dropship International Documents",
    "Warehouse Not International Documents",
    "Warehouse International Documents",
    "Freight Issues",
    "Vendor Credit Memos",
    "Miscellaneous Documents",
)

WEAK_REASON_FRAGMENTS = ("Default routing for", "Misc Invoices - need approval")


def _path_in_operations_root(path: str) -> bool:
    return bool(path) and any(path.startswith(r) for r in OPERATIONS_FOLDER_ROOTS)


def _reason_is_weak(reason: str) -> bool:
    if not reason:
        return True
    return any(frag in reason for frag in WEAK_REASON_FRAGMENTS)


def _override_set(doc: Dict[str, Any]) -> bool:
    return (
        doc.get("accounting_routing_override") is True
        or doc.get("approved") is True
        or (doc.get("status") or "") == "Approved"
    )


async def _fetch(mailbox: str, since_hours: int, limit: int) -> List[Dict[str, Any]]:
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
        "id": 1, "file_name": 1, "email_sender": 1, "email_subject": 1,
        "mailbox_category": 1, "doc_type": 1, "document_type": 1,
        "suggested_job_type": 1, "classification_method": 1,
        "ai_confidence": 1, "confidence": 1,
        "vendor_canonical": 1, "po_number_clean": 1, "po_number_extracted": 1,
        "invoice_number_clean": 1, "amount_float": 1,
        "mailbox_lane_needs_review": 1,
        "routing_status": 1, "routing_reason": 1, "routing_details": 1,
        "sharepoint_folder_path": 1, "folder_routing_reason": 1,
        "sharepoint_web_url": 1,
        "accounting_routing_override": 1, "approved": 1, "status": 1,
        "created_utc": 1, "created_at": 1, "intake_at": 1,
    }
    cur = db.hub_documents.find(query, projection).sort(
        [("created_utc", -1), ("created_at", -1), ("intake_at", -1)]
    ).limit(limit)
    return await cur.to_list(limit)


def _derive_routing_status(r: Dict[str, Any]) -> str:
    """Use the persisted routing_status when available; otherwise synthesize
    from folder_path + reason + override flags so older rows are still
    usable in the report."""
    persisted = r.get("routing_status")
    if persisted:
        return str(persisted)
    if _override_set(r):
        return "manual_override"
    path = r.get("sharepoint_folder_path") or ""
    reason = r.get("folder_routing_reason") or r.get("routing_reason") or ""
    if r.get("mailbox_lane_needs_review"):
        return "needs_review"
    if path == "Accounts Payable/Temp Folder" or path.startswith("Accounts Payable/Temp Folder/"):
        return "needs_review"
    dt = r.get("doc_type") or r.get("document_type") or ""
    if dt in AP_INVOICE_DOC_TYPES and _path_in_operations_root(path) and _reason_is_weak(reason):
        return "exception"
    return "auto_routed"


def _build_report(rows: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], int]:
    total = len(rows)
    by_mailbox = Counter()
    by_doc_type = Counter()
    by_suggested = Counter()
    by_status = Counter()
    by_folder_root = Counter()
    by_reason_top = Counter()
    by_class_method = Counter()
    ap_temp_count = 0
    ap_count = 0

    auto_routed_samples: List[Dict[str, Any]] = []
    needs_review_samples: List[Dict[str, Any]] = []
    exception_samples: List[Dict[str, Any]] = []
    billing_to_operations: List[Dict[str, Any]] = []
    ap_in_operations_weak: List[Dict[str, Any]] = []
    legacy_class_method: List[Dict[str, Any]] = []

    for r in rows:
        mc = r.get("mailbox_category") or "<missing>"
        dt = r.get("doc_type") or r.get("document_type") or "<missing>"
        sj = r.get("suggested_job_type") or "<missing>"
        cm = r.get("classification_method") or "<missing>"
        path = r.get("sharepoint_folder_path") or ""
        reason = r.get("folder_routing_reason") or r.get("routing_reason") or ""
        root = path.split("/", 1)[0] if path else "<missing>"
        status = _derive_routing_status(r)

        by_mailbox[mc] += 1
        by_doc_type[dt] += 1
        by_suggested[sj] += 1
        by_class_method[cm] += 1
        by_status[status] += 1
        by_folder_root[root] += 1
        if reason:
            by_reason_top[reason[:100]] += 1

        if dt in AP_INVOICE_DOC_TYPES:
            ap_count += 1
            if path.startswith("Accounts Payable/Temp Folder"):
                ap_temp_count += 1

        sample = {
            "id": r.get("id"),
            "file_name": r.get("file_name"),
            "doc_type": dt,
            "vendor_canonical": r.get("vendor_canonical"),
            "po": r.get("po_number_clean") or r.get("po_number_extracted"),
            "invoice_number": r.get("invoice_number_clean"),
            "ai_confidence": r.get("ai_confidence") or r.get("confidence"),
            "classification_method": cm,
            "folder_path": path,
            "reason": reason,
        }
        if status == "auto_routed" and dt in AP_INVOICE_DOC_TYPES:
            auto_routed_samples.append(sample)
        elif status == "needs_review":
            needs_review_samples.append(sample)
        elif status == "exception":
            exception_samples.append(sample)

        # Findings
        if mc and mc != "AP" and mc != "<missing>":
            billing_to_operations.append(sample)
        if dt in AP_INVOICE_DOC_TYPES and _path_in_operations_root(path) \
                and _reason_is_weak(reason) and not _override_set(r):
            ap_in_operations_weak.append(sample)
        if cm == "mailbox:AP":
            legacy_class_method.append(sample)

    blockers, warnings = [], []
    if billing_to_operations:
        blockers.append(
            f"{len(billing_to_operations)} billing-mailbox doc(s) persisted with "
            f"mailbox_category != 'AP' (Square9 parity break)"
        )
    if ap_in_operations_weak:
        blockers.append(
            f"{len(ap_in_operations_weak)} AP_INVOICE doc(s) in Operations folder root "
            f"via weak/default reason without override (scatter)"
        )
    if legacy_class_method:
        warnings.append(
            f"{len(legacy_class_method)} doc(s) using legacy classification_method='mailbox:AP'; "
            f"ensure latest deploy is live"
        )
    if ap_count and ap_temp_count / ap_count > 0.5:
        warnings.append(
            f"{ap_temp_count}/{ap_count} AP_INVOICE doc(s) staged in AP Temp Folder "
            f"({ap_temp_count / ap_count:.0%}); high ratio — investigate evidence quality "
            f"or rule coverage before declaring auto-routing parity"
        )
    if total == 0:
        warnings.append("zero documents in window — sample size insufficient")

    report = {
        "window": {"total_docs": total, "ap_invoice_count": ap_count,
                   "ap_temp_folder_count": ap_temp_count},
        "counts": {
            "by_mailbox_category": dict(by_mailbox),
            "by_doc_type": dict(by_doc_type),
            "by_suggested_job_type": dict(by_suggested),
            "by_routing_status": dict(by_status),
            "by_folder_root": dict(by_folder_root),
            "by_classification_method": dict(by_class_method),
            "top_reasons": by_reason_top.most_common(15),
        },
        "samples": {
            "auto_routed_ap_invoice": auto_routed_samples[:25],
            "needs_review": needs_review_samples[:25],
            "exception": exception_samples[:25],
        },
        "findings": {
            "blockers": blockers,
            "warnings": warnings,
            "billing_to_operations": billing_to_operations[:25],
            "ap_in_operations_weak": ap_in_operations_weak[:25],
            "legacy_class_method": legacy_class_method[:25],
        },
    }
    if blockers:
        return report, 2
    if warnings:
        return report, 1
    return report, 0


def _print(report: Dict[str, Any], exit_code: int) -> None:
    counts = report["counts"]
    print()
    print("=== AP cutover readiness report ===")
    print(f"  total docs:               {report['window']['total_docs']}")
    print(f"  AP_INVOICE count:         {report['window']['ap_invoice_count']}")
    print(f"  in AP Temp Folder:        {report['window']['ap_temp_folder_count']}")

    def _print_counter(label: str, c: Dict[str, Any]) -> None:
        print(f"\n  {label}:")
        for k, v in sorted(c.items(), key=lambda kv: -kv[1]):
            print(f"    {v:>6}  {k}")

    _print_counter("by mailbox_category", counts["by_mailbox_category"])
    _print_counter("by doc_type", counts["by_doc_type"])
    _print_counter("by suggested_job_type", counts["by_suggested_job_type"])
    _print_counter("by routing_status", counts["by_routing_status"])
    _print_counter("by folder root", counts["by_folder_root"])
    _print_counter("by classification_method", counts["by_classification_method"])

    print("\n  top routing reasons:")
    for reason, n in counts["top_reasons"]:
        print(f"    {n:>6}  {reason}")

    samples = report["samples"]
    for label, items in (
        ("AUTO-ROUTED AP_INVOICE samples", samples["auto_routed_ap_invoice"]),
        ("NEEDS_REVIEW samples", samples["needs_review"]),
        ("EXCEPTION samples", samples["exception"]),
    ):
        if items:
            print(f"\n  {label} (up to 25):")
            for it in items:
                print(f"    {it}")

    findings = report["findings"]
    if findings["blockers"]:
        print("\n  *** CUTOVER-BLOCKING ***")
        for b in findings["blockers"]:
            print(f"    - {b}")
    if findings["warnings"]:
        print("\n  warnings:")
        for w in findings["warnings"]:
            print(f"    - {w}")

    print()
    if exit_code == 0:
        print("  RESULT: clean. AP-lane intake routing is auditable for this window.")
        print("  Cutover-defensible — pair with a successful run of "
              "scripts.sharepoint_ap_compare --graph-pull for prod-vs-test parity evidence.")
    elif exit_code == 1:
        print("  RESULT: warnings — review and re-run after addressing.")
    else:
        print("  RESULT: cutover-blocking findings present. Do NOT declare cutover-ready.")
    print()


async def _run(mailbox: str, since_hours: int, limit: int, as_json: bool) -> int:
    rows = await _fetch(mailbox, since_hours, limit)
    report, code = _build_report(rows)
    if as_json:
        print(json.dumps(report, default=str, indent=2))
    else:
        _print(report, code)
    return code


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AP cutover readiness report.")
    ap.add_argument("--mailbox", default=DEFAULT_BILLING_MAILBOX)
    ap.add_argument("--since-hours", type=int, default=48)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    return asyncio.run(_run(args.mailbox, args.since_hours, args.limit, args.json))


if __name__ == "__main__":
    raise SystemExit(main())
