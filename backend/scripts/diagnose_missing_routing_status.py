"""
diagnose_missing_routing_status.py
==================================
READ-ONLY diagnostic for hub documents that have no `routing_status`
set. Produces visibility only — no writes, no fixes.

Outputs (all in prod_reports/):
- MISSING_ROUTING_STATUS_DIAG.md
- MISSING_ROUTING_STATUS_DIAG.csv
- MISSING_ROUTING_STATUS_DIAG.json

For each affected document, the report captures:
- hub_doc_id
- file_name
- doc_type / classification
- created_at age (hours)
- last_modified age (hours, if present)
- source mailbox / channel (if present)
- whether the doc is in a "pre-routing" state by other signals
- a likely cause bucket
- a recommended next step
- whether a safe auto-fix appears available

Strict guarantees:
- No Mongo writes.
- No reclassification.
- No state changes.
- No AP-facing artifacts.

Usage:
    python /app/scripts/diagnose_missing_routing_status.py
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from pymongo import MongoClient


OUT_DIR = "/app/prod_reports"
MD_OUT = os.path.join(OUT_DIR, "MISSING_ROUTING_STATUS_DIAG.md")
CSV_OUT = os.path.join(OUT_DIR, "MISSING_ROUTING_STATUS_DIAG.csv")
JSON_OUT = os.path.join(OUT_DIR, "MISSING_ROUTING_STATUS_DIAG.json")


def _age_hours(ts: Any) -> str:
    if not ts:
        return ""
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts
        return f"{delta.total_seconds() / 3600:.1f}"
    return ""


def _cause_and_next_step(doc: Dict[str, Any]) -> Tuple[str, str, str]:
    """Return (cause_bucket, next_step, safe_auto_fix_yn)."""
    extracted = doc.get("extracted_fields") or {}
    classification_status = doc.get("classification_status") or ""
    has_extraction = bool(extracted)
    blocking_issues = doc.get("blocking_issues") or []

    # Newly arrived, classifier hasn't run yet.
    if not classification_status and not has_extraction:
        return (
            "pre_classification",
            "Verify document_intelligence pipeline ran for this doc; "
            "if not, queue it for processing (no auto-fix here).",
            "no",
        )
    # Classifier ran but routing didn't tag a status.
    if classification_status and not doc.get("routing_status"):
        return (
            "post_classification_pre_routing",
            "Re-run routing for this doc (read-only diagnostic only — "
            "do not write here). Most common cause: routing rule did "
            "not match this doc_type/source combo.",
            "investigate",
        )
    # Has extraction errors — routing skipped intentionally.
    if blocking_issues:
        return (
            "blocked_before_routing",
            "Doc has blocking issues; routing intentionally not "
            "assigned. Resolve blockers first (out of scope for this "
            "diagnostic).",
            "no",
        )
    return ("unknown", "Manual review needed.", "investigate")


def main() -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        sys.stderr.write("MONGO_URL / DB_NAME not set in env.\n")
        return 2

    client = MongoClient(mongo_url)
    db = client[db_name]
    coll = db["hub_documents"]

    # Find docs where routing_status is missing OR null OR empty
    query = {
        "$or": [
            {"routing_status": {"$exists": False}},
            {"routing_status": None},
            {"routing_status": ""},
        ]
    }
    projection = {
        "_id": 0,
        "id": 1,
        "file_name": 1,
        "doc_type": 1,
        "classification_status": 1,
        "routing_status": 1,
        "created_at": 1,
        "last_modified": 1,
        "source_mailbox": 1,
        "source_channel": 1,
        "extracted_fields": 1,
        "blocking_issues": 1,
        "validation_errors": 1,
    }

    docs = list(coll.find(query, projection))
    total = len(docs)

    rows: List[Dict[str, Any]] = []
    by_cause: Dict[str, int] = {}
    by_type: Dict[str, int] = {}
    by_mailbox: Dict[str, int] = {}

    for d in docs:
        cause, next_step, safe = _cause_and_next_step(d)
        by_cause[cause] = by_cause.get(cause, 0) + 1
        dtype = d.get("doc_type") or "unknown"
        by_type[dtype] = by_type.get(dtype, 0) + 1
        mb = d.get("source_mailbox") or d.get("source_channel") or ""
        if mb:
            by_mailbox[mb] = by_mailbox.get(mb, 0) + 1

        rows.append({
            "hub_doc_id": d.get("id") or "",
            "file_name": d.get("file_name") or "",
            "doc_type": dtype,
            "classification_status": d.get("classification_status") or "",
            "routing_status": d.get("routing_status") or "",
            "created_age_h": _age_hours(d.get("created_at")),
            "last_modified_age_h": _age_hours(d.get("last_modified")),
            "source_mailbox": mb,
            "blocking_issues_count": len(d.get("blocking_issues") or []),
            "validation_errors_count": len(d.get("validation_errors") or []),
            "cause": cause,
            "safe_auto_fix": safe,
            "next_step": next_step,
        })

    os.makedirs(OUT_DIR, exist_ok=True)

    # JSON
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total": total,
            "by_cause": by_cause,
            "by_doc_type": by_type,
            "by_source_mailbox": by_mailbox,
            "rows": rows,
        }, f, indent=2, default=str)

    # CSV
    if rows:
        with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow(r)
    else:
        # Empty CSV with header
        with open(CSV_OUT, "w", encoding="utf-8") as f:
            f.write("hub_doc_id,file_name,doc_type,cause\n")

    # Markdown
    md: List[str] = []
    md.append("# Missing Routing Status — Diagnostic Report")
    md.append("")
    md.append("> READ-ONLY diagnostic. No Mongo writes, no fixes applied.")
    md.append(
        f"> Generated: {datetime.now(timezone.utc).isoformat()}")
    md.append("")
    md.append(f"- **Total docs without routing_status:** {total}")
    md.append("")
    md.append("## By cause bucket")
    md.append("")
    md.append("| Cause | Count |")
    md.append("| --- | --- |")
    for cause, ct in sorted(by_cause.items(), key=lambda kv: -kv[1]):
        md.append(f"| {cause} | {ct} |")
    md.append("")
    md.append("## By doc_type")
    md.append("")
    md.append("| doc_type | Count |")
    md.append("| --- | --- |")
    for t, ct in sorted(by_type.items(), key=lambda kv: -kv[1]):
        md.append(f"| {t} | {ct} |")
    md.append("")
    if by_mailbox:
        md.append("## By source mailbox / channel")
        md.append("")
        md.append("| Source | Count |")
        md.append("| --- | --- |")
        for mb, ct in sorted(by_mailbox.items(), key=lambda kv: -kv[1]):
            md.append(f"| {mb} | {ct} |")
        md.append("")
    md.append("## Affected documents")
    md.append("")
    md.append("| hub_doc_id | file_name | doc_type | age (h) | cause | next step |")
    md.append("| --- | --- | --- | --- | --- | --- |")
    for r in rows:
        md.append(
            f"| `{r['hub_doc_id']}` | {r['file_name']} | {r['doc_type']} "
            f"| {r['created_age_h']} | {r['cause']} | {r['next_step']} |")
    md.append("")
    md.append("## Recommended next step")
    md.append("")
    md.append(
        "1. Review the cause bucket distribution above. If most docs "
        "fall into `post_classification_pre_routing`, the routing "
        "rules likely have a coverage gap for a specific doc_type or "
        "source channel.")
    md.append(
        "2. Confirm whether any of these docs are AP-relevant. If yes, "
        "they will surface in AP UAT as 'document not routed' — flag "
        "for follow-up but do not auto-fix during the pilot window.")
    md.append(
        "3. No action from this script. All fixes require an explicit "
        "follow-up scope.")
    md.append("")

    with open(MD_OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print("=" * 70)
    print(" diagnose_missing_routing_status — READ-ONLY")
    print("=" * 70)
    print(f"  total docs   : {total}")
    print(f"  by cause     : {by_cause}")
    print(f"  out_md       : {MD_OUT}")
    print(f"  out_csv      : {CSV_OUT}")
    print(f"  out_json     : {JSON_OUT}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
