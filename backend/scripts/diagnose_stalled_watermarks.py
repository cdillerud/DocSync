"""
diagnose_stalled_watermarks.py
==============================
READ-ONLY diagnostic for the email-poll watermark records that have
stalled (i.e. `last_received_datetime` hasn't advanced in a long
window despite mail still flowing in those mailboxes).

Outputs (all in prod_reports/):
- STALLED_WATERMARKS_DIAG.md
- STALLED_WATERMARKS_DIAG.csv
- STALLED_WATERMARKS_DIAG.json

For each watermark, captures:
- mailbox
- last_received_datetime
- watermark age (hours) since last_received_datetime
- last_polled_at (if present) and its age
- consecutive_empty_polls (if tracked)
- last_error / last_error_at (if present)
- a likely cause bucket
- whether a safe auto-fix appears available
- recommended next step

Strict guarantees:
- No Mongo writes.
- No watermark advancement.
- No mail polling triggered.
- No AP-facing artifacts.

Usage:
    python /app/scripts/diagnose_stalled_watermarks.py

Tunable:
    --stale-hours N    Watermark is considered stalled when
                       last_received_datetime is older than N hours
                       (default 24).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo import MongoClient


OUT_DIR = "/app/prod_reports"
MD_OUT = os.path.join(OUT_DIR, "STALLED_WATERMARKS_DIAG.md")
CSV_OUT = os.path.join(OUT_DIR, "STALLED_WATERMARKS_DIAG.csv")
JSON_OUT = os.path.join(OUT_DIR, "STALLED_WATERMARKS_DIAG.json")


def _to_dt(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _age_hours(dt: Optional[datetime]) -> Optional[float]:
    if not dt:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def _cause_and_next_step(rec: Dict[str, Any], stale_hours: float
                         ) -> Tuple[str, str, str]:
    """Return (cause_bucket, next_step, safe_auto_fix_yn)."""
    last_err = rec.get("last_error") or ""
    last_err_at_age = _age_hours(_to_dt(rec.get("last_error_at")))
    consecutive_empty = rec.get("consecutive_empty_polls") or 0

    if last_err and last_err_at_age is not None and last_err_at_age < 6:
        return (
            "active_error",
            "Investigate the recent error string. Likely auth, "
            "throttling, or a malformed message. Manual review "
            "required before any fix.",
            "no",
        )
    if consecutive_empty and consecutive_empty > 10:
        return (
            "high_consecutive_empty_polls",
            "Mailbox may have legitimately stopped receiving mail or "
            "the Graph filter is excluding everything. Compare "
            "against Microsoft Graph directly with the existing "
            "`email_poll_watermark_probe.py` script.",
            "investigate",
        )
    if rec.get("last_polled_at"):
        last_polled_age = _age_hours(_to_dt(rec.get("last_polled_at")))
        if last_polled_age is not None and last_polled_age > 6:
            return (
                "polling_loop_inactive",
                "Polling task hasn't touched this watermark recently. "
                "Check the email-polling background task; the loop "
                "may be wedged or excluded this mailbox.",
                "investigate",
            )
    return (
        "watermark_legitimately_quiet",
        "Mailbox may simply be quiet. Cross-check against Graph; if "
        "real mail exists past the watermark, escalate.",
        "investigate",
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stale-hours", type=float, default=24.0,
                        help="Watermark considered stalled when "
                             "last_received_datetime is older than "
                             "this many hours (default 24).")
    args = parser.parse_args(argv)

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        sys.stderr.write("MONGO_URL / DB_NAME not set in env.\n")
        return 2

    client = MongoClient(mongo_url)
    db = client[db_name]

    # Watermarks live on `hub_settings` documents of type
    # `email_poll_watermark`, OR — depending on schema generation —
    # on a dedicated `mail_poll_runs` collection. Probe both
    # read-only.
    candidates: List[Dict[str, Any]] = []

    if "hub_settings" in db.list_collection_names():
        # Match both the global watermark and all per-mailbox watermarks
        # (`type: "mailbox_watermark:<address>"`).
        wm_query = {
            "$or": [
                {"type": "email_poll_watermark"},
                {"type": {"$regex": r"^mailbox_watermark:"}},
            ]
        }
        for rec in db["hub_settings"].find(wm_query, {"_id": 0}):
            wm_type = rec.get("type") or ""
            if wm_type.startswith("mailbox_watermark:") and not rec.get("mailbox"):
                # Synthesize mailbox from the type key for reporting.
                rec["mailbox"] = wm_type.split(":", 1)[1]
            candidates.append({**rec, "_source_collection": "hub_settings"})

    if "mail_poll_runs" in db.list_collection_names():
        # Pull most recent run per mailbox
        pipeline = [
            {"$sort": {"started_at": -1}},
            {"$group": {
                "_id": {"$ifNull": ["$mailbox", "$user"]},
                "doc": {"$first": "$$ROOT"},
            }},
        ]
        for grouped in db["mail_poll_runs"].aggregate(pipeline):
            doc = grouped.get("doc") or {}
            doc.pop("_id", None)
            candidates.append({**doc, "_source_collection": "mail_poll_runs"})

    rows: List[Dict[str, Any]] = []
    by_cause: Dict[str, int] = {}
    stalled_count = 0

    for rec in candidates:
        wm = _to_dt(rec.get("last_received_datetime")
                    or rec.get("watermark")
                    or rec.get("last_received"))
        wm_age = _age_hours(wm)
        is_stalled = wm_age is not None and wm_age > args.stale_hours

        if not is_stalled:
            continue

        stalled_count += 1
        cause, next_step, safe = _cause_and_next_step(rec, args.stale_hours)
        by_cause[cause] = by_cause.get(cause, 0) + 1

        rows.append({
            "source_collection": rec.get("_source_collection"),
            "mailbox": rec.get("mailbox") or rec.get("user") or "",
            "watermark": wm.isoformat() if wm else "",
            "watermark_age_h": f"{wm_age:.1f}" if wm_age else "",
            "last_polled_at_age_h": (
                f"{_age_hours(_to_dt(rec.get('last_polled_at'))):.1f}"
                if rec.get("last_polled_at") else ""),
            "consecutive_empty_polls": rec.get("consecutive_empty_polls", 0),
            "last_error": (rec.get("last_error") or "")[:200],
            "last_error_at_age_h": (
                f"{_age_hours(_to_dt(rec.get('last_error_at'))):.1f}"
                if rec.get("last_error_at") else ""),
            "cause": cause,
            "safe_auto_fix": safe,
            "next_step": next_step,
        })

    os.makedirs(OUT_DIR, exist_ok=True)

    # JSON
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stale_threshold_hours": args.stale_hours,
            "total_watermarks_probed": len(candidates),
            "stalled_count": stalled_count,
            "by_cause": by_cause,
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
        with open(CSV_OUT, "w", encoding="utf-8") as f:
            f.write("source_collection,mailbox,watermark,cause\n")

    # Markdown
    md: List[str] = []
    md.append("# Stalled Email-Poll Watermarks — Diagnostic Report")
    md.append("")
    md.append("> READ-ONLY diagnostic. No Mongo writes, no fixes applied, "
              "no email polling triggered.")
    md.append(
        f"> Generated: {datetime.now(timezone.utc).isoformat()}")
    md.append(f"> Stale threshold: {args.stale_hours}h since "
              "last_received_datetime")
    md.append("")
    md.append(f"- **Watermarks probed:** {len(candidates)}")
    md.append(f"- **Stalled (above threshold):** {stalled_count}")
    md.append("")
    md.append("## By cause bucket")
    md.append("")
    md.append("| Cause | Count |")
    md.append("| --- | --- |")
    for cause, ct in sorted(by_cause.items(), key=lambda kv: -kv[1]):
        md.append(f"| {cause} | {ct} |")
    md.append("")
    md.append("## Affected watermarks")
    md.append("")
    md.append("| Source | Mailbox | Watermark age (h) | Empty polls | Last error | Cause | Next step |")
    md.append("| --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        md.append(
            f"| {r['source_collection']} "
            f"| {r['mailbox']} "
            f"| {r['watermark_age_h']} "
            f"| {r['consecutive_empty_polls']} "
            f"| {r['last_error'][:60]} "
            f"| {r['cause']} "
            f"| {r['next_step']} |")
    md.append("")
    md.append("## Recommended next step")
    md.append("")
    md.append(
        "1. For watermarks in `active_error` — read the error text and "
        "treat each individually; do not bulk-clear.")
    md.append(
        "2. For `polling_loop_inactive` — check the email-polling "
        "background task; it may be wedged for an unrelated reason.")
    md.append(
        "3. For `high_consecutive_empty_polls` and "
        "`watermark_legitimately_quiet` — verify against Microsoft "
        "Graph using the existing read-only "
        "`email_poll_watermark_probe.py` (does not write).")
    md.append(
        "4. No automated remediation runs from this diagnostic. Any "
        "watermark advancement or polling reset is a separate, "
        "explicitly scoped task.")
    md.append("")

    with open(MD_OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print("=" * 70)
    print(" diagnose_stalled_watermarks — READ-ONLY")
    print("=" * 70)
    print(f"  watermarks probed : {len(candidates)}")
    print(f"  stalled count     : {stalled_count}")
    print(f"  by cause          : {by_cause}")
    print(f"  out_md            : {MD_OUT}")
    print(f"  out_csv           : {CSV_OUT}")
    print(f"  out_json          : {JSON_OUT}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
