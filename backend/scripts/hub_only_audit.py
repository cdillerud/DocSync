"""
hub_only_audit.py
=================
READ-ONLY audit of the ``hub_only`` rows produced by
``square9_hub_ap_parity_report``. Investigates the population of
hub_documents that have NO matching Square9 counterpart and classifies
each of them into one of:

  - non_ap_in_ap_scope          : hub doc is not actually AP — should
                                  be filtered out of the AP parity scope
  - duplicate_or_backlog_artifact: very old (predates the parity window)
                                  or duplicate filename within the same
                                  sender; not a live Square9 candidate
  - square9_scope_gap           : real AP doc, but flowed through a Hub
                                  ingestion lane Square9 does not
                                  observe (manual upload, body-only,
                                  un-routed, etc.); will never match
  - matcher_miss                : real AP doc with strong identity
                                  signals (vendor + invoice_number +
                                  amount) — Square9 likely *does* have
                                  it; matcher needs to improve
  - true_hub_extra              : Hub legitimately holds an AP doc
                                  Square9 was never expected to ingest
                                  (e.g. dropship, hub-only workflow);
                                  no action required
  - uncertain                   : signals are mixed; manual review

For each classification bucket the script emits a recommended_action so
the operator can decide where to act.

Inputs
------
- ``--parity-csv``  Path to the parity CSV from a proof pack run
                    (``square9_hub_ap_parity.csv``). If not supplied
                    the script auto-discovers the most recent
                    ``prod_reports/cutover_proof_*/square9_hub_ap_parity*.csv``.
                    Each row carries the per-document fields written
                    by ``square9_hub_ap_parity_report._row_hub_only``.

Outputs
-------
- ``prod_reports/hub_only_audit.csv``   per-doc classification
- ``prod_reports/hub_only_audit.json``  cohort summary + counts
- ``prod_reports/hub_only_audit.md``    human-readable summary

Exit codes
----------
- 0  hub_only docs are mostly explainable (non_ap + scope_gap +
     backlog + true_hub_extra together cover the vast majority and
     matcher_miss / non_ap_in_ap_scope are each under their thresholds)
- 1  uncertain cohorts remain (>10% of hub_only)
- 2  significant matcher-miss or AP-scope contamination signal
     (matcher_miss >= 10%  OR  non_ap_in_ap_scope >= 10%)

This script writes nothing to Mongo and never calls a remote service.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import os
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants / heuristics
# ---------------------------------------------------------------------------

AP_DOC_TYPES = {"AP_INVOICE", "AP_CREDIT_MEMO"}
AP_SUGGESTED_JOB_TYPES = {"AP_Invoice", "AP_CreditMemo"}

# Folder-name fragments that indicate a Square9-observed AP lane.
# Anything outside this set is taken as evidence the doc was routed
# through a path Square9 does not see (scope gap, not matcher miss).
AP_FOLDER_HINT_PATTERNS = (
    re.compile(r"\bAP\b", re.I),
    re.compile(r"accounts.*payable", re.I),
    re.compile(r"\binvoice", re.I),
    re.compile(r"freight", re.I),
)

# ``hub_classification_method`` values that suggest a Hub lane Square9
# does not ingest at all (operator-initiated rather than email-derived).
HUB_ONLY_LANE_METHODS = (
    "manual_upload",
    "manual_classification",
    "operator",
    "drop_ship",
    "dropship",
    "hub_only",
)

EXIT_OK = 0
EXIT_UNCERTAIN = 1
EXIT_SIGNIFICANT_GAP = 2

# Thresholds for exit-code decision (fractions of hub_only count).
UNCERTAIN_THRESHOLD = 0.10
SIGNIFICANT_THRESHOLD = 0.10

# Recommended action tags emitted into outputs.
ACTION_EXCLUDE = "exclude_from_parity_denominator"
ACTION_IMPROVE_MATCHER = "improve_matcher"
ACTION_FIX_AP_SCOPE = "fix_ap_scope_filter"
ACTION_MANUAL_REVIEW = "manual_review"
ACTION_NO_ACTION = "no_action_hub_extra"

BUCKET_TO_ACTION: Dict[str, str] = {
    "non_ap_in_ap_scope": ACTION_FIX_AP_SCOPE,
    "duplicate_or_backlog_artifact": ACTION_EXCLUDE,
    "square9_scope_gap": ACTION_EXCLUDE,
    "matcher_miss": ACTION_IMPROVE_MATCHER,
    "true_hub_extra": ACTION_NO_ACTION,
    "uncertain": ACTION_MANUAL_REVIEW,
}

# Stable bucket order for reporting.
BUCKET_ORDER = (
    "non_ap_in_ap_scope",
    "matcher_miss",
    "square9_scope_gap",
    "duplicate_or_backlog_artifact",
    "true_hub_extra",
    "uncertain",
)


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def find_latest_parity_csv(
    base_dir: str = "prod_reports",
) -> Optional[str]:
    """Return the most recent parity CSV beneath a ``cutover_proof_*``
    proof-pack directory, or fall back to the static
    ``prod_reports/square9_hub_ap_parity.csv``. Returns None if neither
    exists."""
    candidates = sorted(
        glob.glob(os.path.join(
            base_dir, "cutover_proof_*", "square9_hub_ap_parity*.csv")),
        reverse=True,
    )
    if candidates:
        return candidates[0]
    fallback = os.path.join(base_dir, "square9_hub_ap_parity.csv")
    return fallback if os.path.exists(fallback) else None


def read_parity_rows(csv_path: str) -> List[Dict[str, str]]:
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def filter_hub_only(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    return [r for r in rows
            if (r.get("match_bucket") or "").strip() == "hub_only"]


# ---------------------------------------------------------------------------
# Classification (pure)
# ---------------------------------------------------------------------------

def _is_ap_scope(row: Dict[str, str]) -> bool:
    """A row is in AP scope when EITHER the doc_type or the
    suggested_job_type is one of the AP enumerations."""
    if (row.get("hub_doc_type") or "").strip().upper() in AP_DOC_TYPES:
        return True
    if (row.get("hub_suggested_job_type") or "").strip() in AP_SUGGESTED_JOB_TYPES:
        return True
    return False


def _has_strong_identity_signals(row: Dict[str, str]) -> bool:
    """Vendor + invoice number + amount together = the matcher should
    have been able to find a Square9 counterpart if one existed."""
    vendor = (row.get("hub_vendor_canonical") or "").strip()
    inv = (row.get("hub_invoice_number_clean") or "").strip()
    amt = (row.get("hub_amount_float") or "").strip()
    if not vendor or vendor.lower() in ("", "unknown", "none"):
        return False
    if not inv:
        return False
    try:
        if float(amt) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    return True


def _folder_path_in_ap_lane(row: Dict[str, str]) -> bool:
    path = (row.get("hub_sharepoint_folder_path") or "").strip()
    if not path:
        return False
    return any(p.search(path) for p in AP_FOLDER_HINT_PATTERNS)


def _classification_method_is_hub_only_lane(row: Dict[str, str]) -> bool:
    method = (row.get("hub_classification_method") or "").strip().lower()
    if not method:
        return False
    return any(tag in method for tag in HUB_ONLY_LANE_METHODS)


def _parse_iso_utc(s: str) -> Optional[dt.datetime]:
    if not s:
        return None
    try:
        v = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if v.tzinfo is None:
            v = v.replace(tzinfo=dt.timezone.utc)
        return v
    except (ValueError, AttributeError):
        return None


def _is_backlog(row: Dict[str, str],
                window_start: Optional[dt.datetime]) -> bool:
    if window_start is None:
        return False
    created = _parse_iso_utc(row.get("hub_created_utc") or "")
    return created is not None and created < window_start


def _is_duplicate_in_sender(row: Dict[str, str],
                            sender_filename_counts: Dict[Tuple[str, str], int]
                            ) -> bool:
    sender = (row.get("hub_email_sender") or "").strip().lower()
    fname = (row.get("hub_file_name") or "").strip().lower()
    if not sender or not fname:
        return False
    return sender_filename_counts.get((sender, fname), 0) > 1


def classify_doc(row: Dict[str, str],
                 *,
                 sender_filename_counts: Dict[Tuple[str, str], int],
                 window_start: Optional[dt.datetime],
                 ) -> Tuple[str, str]:
    """Classify a single hub_only row.

    Returns (bucket, reason). Predicate evaluation order matters —
    earlier predicates take precedence.
    """
    # 1. Not AP at all -> AP scope filter is wrong upstream.
    if not _is_ap_scope(row):
        return "non_ap_in_ap_scope", (
            f"hub_doc_type={row.get('hub_doc_type')!r} "
            f"suggested_job_type={row.get('hub_suggested_job_type')!r} "
            f"are not AP enumerations"
        )

    # 2. Predates the Square9 corpus window -> backlog/duplicate.
    if _is_backlog(row, window_start):
        return "duplicate_or_backlog_artifact", (
            f"hub_created_utc={row.get('hub_created_utc')!r} "
            f"predates parity window start "
            f"{window_start.isoformat() if window_start else 'n/a'}"
        )
    if _is_duplicate_in_sender(row, sender_filename_counts):
        sender = (row.get("hub_email_sender") or "").strip().lower()
        fname = (row.get("hub_file_name") or "").strip().lower()
        return "duplicate_or_backlog_artifact", (
            f"duplicate filename {fname!r} from sender {sender!r} "
            f"({sender_filename_counts[(sender, fname)]} occurrences)"
        )

    # 3. Strong identity signals -> matcher should have caught it.
    if _has_strong_identity_signals(row):
        return "matcher_miss", (
            f"vendor_canonical={row.get('hub_vendor_canonical')!r} + "
            f"invoice_number_clean={row.get('hub_invoice_number_clean')!r} "
            f"+ amount_float={row.get('hub_amount_float')!r} "
            f"present; matcher returned hub_only"
        )

    # 4. Routed via a Hub-only lane / non-AP folder -> scope gap or
    #    legitimate Hub-extra.
    in_ap_folder = _folder_path_in_ap_lane(row)
    via_hub_lane = _classification_method_is_hub_only_lane(row)
    if via_hub_lane:
        return "true_hub_extra", (
            f"hub_classification_method="
            f"{row.get('hub_classification_method')!r} indicates a "
            f"Hub-only ingestion lane"
        )
    if not in_ap_folder:
        return "square9_scope_gap", (
            f"hub_sharepoint_folder_path="
            f"{row.get('hub_sharepoint_folder_path')!r} is outside the "
            f"observable Square9 AP folder set"
        )

    # 5. AP scope, AP folder, no strong identity, no special lane.
    return "uncertain", (
        "AP scope and AP folder but identity signals missing "
        "(vendor/invoice/amount); manual review needed"
    )


def classify_all(rows: List[Dict[str, str]],
                 *,
                 window_start: Optional[dt.datetime] = None,
                 ) -> List[Dict[str, Any]]:
    counts: Counter = Counter(
        (((r.get("hub_email_sender") or "").strip().lower()),
         ((r.get("hub_file_name") or "").strip().lower()))
        for r in rows
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        bucket, reason = classify_doc(
            r,
            sender_filename_counts=counts,
            window_start=window_start,
        )
        out.append({
            **r,
            "audit_bucket": bucket,
            "audit_reason": reason,
            "recommended_action": BUCKET_TO_ACTION[bucket],
        })
    return out


# ---------------------------------------------------------------------------
# Cohort summary
# ---------------------------------------------------------------------------

def _ym_bucket(s: str) -> str:
    d = _parse_iso_utc(s)
    return d.strftime("%Y-%m") if d else "<unknown>"


def _norm(v: Optional[str], default: str = "<unknown>") -> str:
    s = (v or "").strip()
    return s if s else default


def _root_of(path: Optional[str]) -> str:
    s = (path or "").strip().strip("/")
    if not s:
        return "<unknown>"
    return s.split("/", 1)[0]


def cohort_summary(classified: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(classified)
    bucket_counts: Counter = Counter(c["audit_bucket"] for c in classified)
    action_counts: Counter = Counter(
        c["recommended_action"] for c in classified)

    by_sender: Counter = Counter(
        _norm(c.get("hub_email_sender")) for c in classified)
    by_folder_root: Counter = Counter(
        _root_of(c.get("hub_sharepoint_folder_path")) for c in classified)
    by_doc_type: Counter = Counter(
        _norm(c.get("hub_doc_type")) for c in classified)
    by_suggested: Counter = Counter(
        _norm(c.get("hub_suggested_job_type")) for c in classified)
    by_classification_method: Counter = Counter(
        _norm(c.get("hub_classification_method")) for c in classified)
    by_routing_status: Counter = Counter(
        _norm(c.get("hub_routing_status")) for c in classified)
    by_routing_reason: Counter = Counter(
        _norm(c.get("hub_routing_reason")) for c in classified)
    by_created_month: Counter = Counter(
        _ym_bucket(c.get("hub_created_utc") or "") for c in classified)

    presence = {
        "vendor_canonical": sum(
            1 for c in classified if (c.get("hub_vendor_canonical") or "").strip()),
        "invoice_number_clean": sum(
            1 for c in classified if (c.get("hub_invoice_number_clean") or "").strip()),
        "amount_float": sum(
            1 for c in classified
            if (c.get("hub_amount_float") or "").strip()
            and (c.get("hub_amount_float") or "").strip() not in ("0", "0.0", "")),
    }

    matcher_miss_top = sorted(
        (c for c in classified if c["audit_bucket"] == "matcher_miss"),
        key=lambda c: (
            _norm(c.get("hub_vendor_canonical")),
            _norm(c.get("hub_invoice_number_clean")),
        ),
    )
    non_ap_top = sorted(
        (c for c in classified if c["audit_bucket"] == "non_ap_in_ap_scope"),
        key=lambda c: _norm(c.get("hub_doc_type")),
    )

    bucket_to_senders: Dict[str, Counter] = defaultdict(Counter)
    for c in classified:
        bucket_to_senders[c["audit_bucket"]][_norm(c.get("hub_email_sender"))] += 1

    return {
        "total_hub_only": total,
        "bucket_counts": {b: bucket_counts.get(b, 0) for b in BUCKET_ORDER},
        "action_counts": dict(action_counts),
        "top_senders": by_sender.most_common(10),
        "top_folder_roots": by_folder_root.most_common(10),
        "doc_type_counts": dict(by_doc_type),
        "suggested_job_type_counts": dict(by_suggested),
        "classification_method_counts": dict(by_classification_method),
        "routing_status_counts": dict(by_routing_status),
        "routing_reason_counts": dict(by_routing_reason),
        "created_month_counts": dict(sorted(by_created_month.items())),
        "presence_counts": presence,
        "matcher_miss_top": matcher_miss_top[:10],
        "non_ap_top": non_ap_top[:10],
        "senders_per_bucket": {
            b: bucket_to_senders.get(b, Counter()).most_common(5)
            for b in BUCKET_ORDER
        },
    }


# ---------------------------------------------------------------------------
# Exit-code decision
# ---------------------------------------------------------------------------

def decide_exit_code(summary: Dict[str, Any]) -> int:
    total = summary["total_hub_only"] or 0
    if total == 0:
        return EXIT_OK
    bc = summary["bucket_counts"]
    matcher_miss = bc.get("matcher_miss", 0) / total
    non_ap = bc.get("non_ap_in_ap_scope", 0) / total
    uncertain = bc.get("uncertain", 0) / total
    if matcher_miss >= SIGNIFICANT_THRESHOLD or non_ap >= SIGNIFICANT_THRESHOLD:
        return EXIT_SIGNIFICANT_GAP
    if uncertain > UNCERTAIN_THRESHOLD:
        return EXIT_UNCERTAIN
    return EXIT_OK


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

OUTPUT_CSV_COLUMNS = [
    "hub_doc_id", "hub_file_name", "hub_email_sender", "hub_doc_type",
    "hub_suggested_job_type", "hub_classification_method",
    "hub_sharepoint_folder_path", "hub_routing_status", "hub_routing_reason",
    "hub_vendor_canonical", "hub_invoice_number_clean", "hub_amount_float",
    "hub_po_number_clean", "hub_created_utc",
    "audit_bucket", "audit_reason", "recommended_action",
]


def write_csv(path: str, classified: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_CSV_COLUMNS,
                           extrasaction="ignore")
        w.writeheader()
        for c in classified:
            w.writerow(c)


def write_json(path: str,
               summary: Dict[str, Any],
               source_csv: str,
               exit_code: int) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    # Trim large per-row lists in matcher_miss_top / non_ap_top so the
    # JSON stays operator-readable.
    def _trim(rows):
        out = []
        for r in rows:
            out.append({k: r.get(k) for k in (
                "hub_doc_id", "hub_file_name", "hub_email_sender",
                "hub_doc_type", "hub_suggested_job_type",
                "hub_vendor_canonical", "hub_invoice_number_clean",
                "hub_amount_float", "audit_reason",
            )})
        return out

    payload = {
        "source_csv": source_csv,
        "exit_code": exit_code,
        "total_hub_only": summary["total_hub_only"],
        "bucket_counts": summary["bucket_counts"],
        "action_counts": summary["action_counts"],
        "top_senders": summary["top_senders"],
        "top_folder_roots": summary["top_folder_roots"],
        "doc_type_counts": summary["doc_type_counts"],
        "suggested_job_type_counts": summary["suggested_job_type_counts"],
        "classification_method_counts": summary["classification_method_counts"],
        "routing_status_counts": summary["routing_status_counts"],
        "routing_reason_counts": summary["routing_reason_counts"],
        "created_month_counts": summary["created_month_counts"],
        "presence_counts": summary["presence_counts"],
        "senders_per_bucket": summary["senders_per_bucket"],
        "matcher_miss_top": _trim(summary["matcher_miss_top"]),
        "non_ap_top": _trim(summary["non_ap_top"]),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, default=str, indent=2)


def write_md(path: str,
             summary: Dict[str, Any],
             source_csv: str,
             exit_code: int) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    bc = summary["bucket_counts"]
    total = summary["total_hub_only"]
    pct = lambda n: (n / total * 100.0) if total else 0.0  # noqa: E731

    lines: List[str] = []
    lines.append(f"# Hub-only audit")
    lines.append("")
    lines.append(f"- source_csv: `{source_csv}`")
    lines.append(f"- exit_code: **{exit_code}**")
    lines.append(f"- total_hub_only: **{total}**")
    lines.append("")
    lines.append("## Classification breakdown")
    lines.append("")
    lines.append("| bucket | count | pct | recommended_action |")
    lines.append("| --- | ---: | ---: | --- |")
    for b in BUCKET_ORDER:
        n = bc.get(b, 0)
        lines.append(f"| {b} | {n} | {pct(n):.1f}% | {BUCKET_TO_ACTION[b]} |")
    lines.append("")
    lines.append("## Top senders (overall)")
    lines.append("")
    lines.append("| sender | count |")
    lines.append("| --- | ---: |")
    for s, n in summary["top_senders"]:
        lines.append(f"| {s} | {n} |")
    lines.append("")
    lines.append("## Top SharePoint folder roots")
    lines.append("")
    lines.append("| folder_root | count |")
    lines.append("| --- | ---: |")
    for s, n in summary["top_folder_roots"]:
        lines.append(f"| {s} | {n} |")
    lines.append("")
    lines.append("## Identity-signal presence")
    lines.append("")
    p = summary["presence_counts"]
    lines.append(f"- vendor_canonical present: {p['vendor_canonical']}")
    lines.append(f"- invoice_number_clean present: {p['invoice_number_clean']}")
    lines.append(f"- amount_float present (>0): {p['amount_float']}")
    lines.append("")
    if summary["matcher_miss_top"]:
        lines.append("## Top matcher-miss candidates")
        lines.append("")
        lines.append(
            "| hub_doc_id | sender | vendor | invoice | amount |")
        lines.append("| --- | --- | --- | --- | ---: |")
        for r in summary["matcher_miss_top"]:
            lines.append(
                f"| {_norm(r.get('hub_doc_id'))} | "
                f"{_norm(r.get('hub_email_sender'))} | "
                f"{_norm(r.get('hub_vendor_canonical'))} | "
                f"{_norm(r.get('hub_invoice_number_clean'))} | "
                f"{_norm(r.get('hub_amount_float'))} |"
            )
        lines.append("")
    if summary["non_ap_top"]:
        lines.append("## Top non-AP-in-AP-scope candidates")
        lines.append("")
        lines.append("| hub_doc_id | doc_type | suggested_job_type | sender |")
        lines.append("| --- | --- | --- | --- |")
        for r in summary["non_ap_top"]:
            lines.append(
                f"| {_norm(r.get('hub_doc_id'))} | "
                f"{_norm(r.get('hub_doc_type'))} | "
                f"{_norm(r.get('hub_suggested_job_type'))} | "
                f"{_norm(r.get('hub_email_sender'))} |"
            )
        lines.append("")
    lines.append("## Created-month distribution")
    lines.append("")
    lines.append("| month | count |")
    lines.append("| --- | ---: |")
    for m, n in summary["created_month_counts"].items():
        lines.append(f"| {m} | {n} |")
    lines.append("")
    lines.append(
        "_READ-ONLY audit. No production state was changed._")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Console renderer
# ---------------------------------------------------------------------------

def render_console(summary: Dict[str, Any],
                   exit_code: int,
                   source_csv: str,
                   csv_out: str,
                   json_out: str,
                   md_out: str) -> str:
    bc = summary["bucket_counts"]
    total = summary["total_hub_only"]
    out: List[str] = []
    out.append("=" * 72)
    out.append(f" hub_only_audit — exit_code={exit_code}")
    out.append("=" * 72)
    out.append(f"  source_csv      : {source_csv}")
    out.append(f"  total_hub_only  : {total}")
    out.append("")
    out.append("  bucket counts (recommended_action):")
    for b in BUCKET_ORDER:
        n = bc.get(b, 0)
        pct_v = (n / total * 100.0) if total else 0.0
        out.append(f"    {b:32s} {n:5d}  ({pct_v:5.1f}%)  "
                   f"-> {BUCKET_TO_ACTION[b]}")
    out.append("")
    out.append("  top senders:")
    for s, n in summary["top_senders"]:
        out.append(f"    {n:5d}  {s}")
    out.append("")
    out.append("  top folder roots:")
    for s, n in summary["top_folder_roots"]:
        out.append(f"    {n:5d}  {s}")
    out.append("")
    p = summary["presence_counts"]
    out.append(f"  vendor_canonical present     : {p['vendor_canonical']}")
    out.append(f"  invoice_number_clean present : {p['invoice_number_clean']}")
    out.append(f"  amount_float present (>0)    : {p['amount_float']}")
    out.append("")
    out.append(f"  csv_out  : {csv_out}")
    out.append(f"  json_out : {json_out}")
    out.append(f"  md_out   : {md_out}")
    out.append("")
    out.append("  READ-ONLY audit. No DB writes, no cutover, "
               "no Square9 archive.")
    out.append("=" * 72)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Read-only hub_only audit from latest parity CSV.")
    p.add_argument("--parity-csv", default=None,
                   help="Path to square9_hub_ap_parity*.csv. If omitted, "
                        "auto-discover the latest cutover_proof_*/ run.")
    p.add_argument("--csv-out",
                   default="prod_reports/hub_only_audit.csv")
    p.add_argument("--json-out",
                   default="prod_reports/hub_only_audit.json")
    p.add_argument("--md-out",
                   default="prod_reports/hub_only_audit.md")
    p.add_argument("--window-start",
                   default=None,
                   help=("ISO-8601 UTC. Hub docs created before this "
                         "are classified as backlog/duplicate. Default: "
                         "no backlog cutoff."))
    args = p.parse_args()

    csv_path = args.parity_csv or find_latest_parity_csv()
    if not csv_path or not os.path.exists(csv_path):
        print("hub_only_audit: no parity CSV found "
              f"(--parity-csv={args.parity_csv!r}, auto-discovery "
              "produced no candidates).")
        return EXIT_SIGNIFICANT_GAP

    parity_rows = read_parity_rows(csv_path)
    hub_only_rows = filter_hub_only(parity_rows)

    window_start = _parse_iso_utc(args.window_start) \
        if args.window_start else None

    classified = classify_all(hub_only_rows, window_start=window_start)
    summary = cohort_summary(classified)
    exit_code = decide_exit_code(summary)

    write_csv(args.csv_out, classified)
    write_json(args.json_out, summary, csv_path, exit_code)
    write_md(args.md_out, summary, csv_path, exit_code)

    print(render_console(summary, exit_code, csv_path,
                         args.csv_out, args.json_out, args.md_out))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
