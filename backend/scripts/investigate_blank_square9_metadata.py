"""
investigate_blank_square9_metadata.py
=====================================
READ-ONLY diagnostic. Determines the origin of rows with blank
``square9_name`` and/or ``square9_parent_path`` in the
``square9_only_triage_resolved.csv`` (and downstream reports).

Hypothesis under test:
  The user passed ``square9_hub_ap_parity_invoice_set.csv`` (the parity
  report's combined CSV containing rows with ``match_bucket`` ∈
  {match, no_match, hub_only}) directly to
  ``square9_only_triage_resolver.py``. The resolver does not filter by
  ``match_bucket``. The ``hub_only`` rows in that CSV write blank
  Square9 columns by design (see ``_row_hub_only`` in the parity
  report). Those blanks then propagate into the resolved CSV and
  cascade into the Bucket C remediation plan.

This script verifies that hypothesis by counting blank rows in each
upstream CSV, recovering whatever Hub-side metadata the parity report
wrote on those same rows, and emitting corrected counts.

No DB writes. No mutations of any input file. Pure read of CSVs.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_blank(s: Optional[str]) -> bool:
    return not (s or "").strip()


def _read_csv(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def classify_blank(row: Dict[str, str]) -> str:
    """Classify a row with blank Square9 metadata.

    Returns one of:
      - hub_only_artifact_from_parity   (parity row tagged hub_only)
      - hub_only_inferred_from_doc_id   (no match_bucket but has hub doc)
      - bucket_C_misrouting             (in resolved.csv with bucket=C
                                         and best_hub_doc_id present)
      - genuine_blank_square9_entry     (truly empty source row)
      - artifact_exclude_from_parity    (cannot recover anything)
    """
    bucket = (row.get("match_bucket") or "").strip().lower()
    hub_doc_id = (row.get("hub_doc_id") or row.get("best_hub_doc_id") or "").strip()
    hub_file = (row.get("hub_file_name") or row.get("best_hub_file_name") or "").strip()
    res_bucket = (row.get("bucket") or "").strip().upper()

    if bucket == "hub_only":
        return "hub_only_artifact_from_parity"
    if hub_doc_id and not bucket:
        return "hub_only_inferred_from_doc_id"
    if res_bucket == "C" and hub_doc_id:
        return "bucket_C_misrouting"
    if hub_file or hub_doc_id:
        return "hub_only_inferred_from_doc_id"
    return "artifact_exclude_from_parity"


# ---------------------------------------------------------------------------
# Pure analyzers (testable)
# ---------------------------------------------------------------------------

def count_blank(rows: List[Dict[str, str]]) -> Dict[str, int]:
    n_total = len(rows)
    n_blank_name = sum(1 for r in rows if _is_blank(r.get("square9_name")))
    n_blank_parent = sum(1 for r in rows if _is_blank(r.get("square9_parent_path")))
    n_blank_either = sum(
        1 for r in rows
        if _is_blank(r.get("square9_name"))
        or _is_blank(r.get("square9_parent_path"))
    )
    n_blank_both = sum(
        1 for r in rows
        if _is_blank(r.get("square9_name"))
        and _is_blank(r.get("square9_parent_path"))
    )
    return {
        "total_rows": n_total,
        "blank_name": n_blank_name,
        "blank_parent_path": n_blank_parent,
        "blank_either": n_blank_either,
        "blank_both": n_blank_both,
    }


def recover_blank_rows(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """For each blank row, attempt to recover ``hub_doc_id``,
    ``hub_file_name``, ``match_bucket`` and classify."""
    out: List[Dict[str, Any]] = []
    for idx, r in enumerate(rows):
        if not (
            _is_blank(r.get("square9_name"))
            and _is_blank(r.get("square9_parent_path"))
        ):
            continue
        out.append({
            "row_index": idx,
            "match_bucket": (r.get("match_bucket") or "").strip(),
            "resolved_bucket": (r.get("bucket") or "").strip(),
            "hub_doc_id": (
                r.get("hub_doc_id") or r.get("best_hub_doc_id") or ""
            ).strip(),
            "hub_file_name": (
                r.get("hub_file_name") or r.get("best_hub_file_name") or ""
            ).strip(),
            "match_reason": (
                r.get("match_reason") or r.get("best_match_reason") or ""
            ).strip(),
            "match_score": (
                r.get("match_score") or r.get("best_match_score") or ""
            ).strip(),
            "classification": classify_blank(r),
        })
    return out


def analyze(parity_rows: List[Dict[str, str]],
            resolved_rows: List[Dict[str, str]],
            triage_rows: Optional[List[Dict[str, str]]] = None
            ) -> Dict[str, Any]:
    parity_counts = count_blank(parity_rows) if parity_rows else {
        "total_rows": 0, "blank_name": 0, "blank_parent_path": 0,
        "blank_either": 0, "blank_both": 0,
    }
    resolved_counts = count_blank(resolved_rows)
    triage_counts = count_blank(triage_rows or []) if triage_rows else None

    # Trace blank-row origin in parity CSV (if available).
    parity_match_bucket_breakdown: Dict[str, int] = dict(Counter())
    if parity_rows:
        parity_match_bucket_breakdown = dict(
            Counter(
                (r.get("match_bucket") or "").strip()
                for r in parity_rows
                if _is_blank(r.get("square9_name"))
                and _is_blank(r.get("square9_parent_path"))
            )
        )

    resolved_blank_recovery = recover_blank_rows(resolved_rows)
    classification_counts = dict(
        Counter(r["classification"] for r in resolved_blank_recovery)
    )

    # Bucket C in resolved CSV broken down by blank/non-blank.
    bucket_c_rows = [
        r for r in resolved_rows
        if (r.get("bucket") or "").strip().upper() == "C"
    ]
    bucket_c_blank = [
        r for r in bucket_c_rows
        if _is_blank(r.get("square9_name"))
        and _is_blank(r.get("square9_parent_path"))
    ]
    bucket_c_recoverable = [
        r for r in bucket_c_blank
        if (r.get("best_hub_doc_id") or "").strip()
    ]

    # Determine root cause and remediation.
    parity_hub_only_count = parity_match_bucket_breakdown.get("hub_only", 0)
    if parity_rows and parity_hub_only_count >= max(
        1, int(0.5 * resolved_counts["blank_both"])
    ):
        root_cause = (
            "resolver_consumed_parity_csv_without_filtering_match_bucket"
        )
        recommendation = (
            "Re-run resolver with --triage-csv pointing at the parity "
            "report's --triage-out-csv (which emits only `no_match` rows). "
            "Bucket C plan should be regenerated from the cleaned input."
        )
    elif resolved_counts["blank_both"] > 0 and \
            classification_counts.get(
                "artifact_exclude_from_parity", 0
            ) == resolved_counts["blank_both"]:
        root_cause = "true_blank_rows_in_resolved_csv_unrecoverable"
        recommendation = (
            "Drop these rows from the cutover denominator as artifacts. "
            "Bucket C plan should be regenerated."
        )
    else:
        root_cause = "mixed_or_inconclusive_inspect_classification_counts"
        recommendation = (
            "Inspect classification breakdown manually before regenerating "
            "the Bucket C plan."
        )

    real_bucket_c = max(0, len(bucket_c_rows) - len(bucket_c_blank))
    artifact_bucket_c = len(bucket_c_blank) - len(bucket_c_recoverable)
    recovered_bucket_c = len(bucket_c_recoverable)

    return {
        "parity_counts": parity_counts,
        "resolved_counts": resolved_counts,
        "triage_counts": triage_counts,
        "parity_blank_match_bucket_breakdown": parity_match_bucket_breakdown,
        "resolved_blank_classification_counts": classification_counts,
        "bucket_C_total": len(bucket_c_rows),
        "bucket_C_blank_metadata": len(bucket_c_blank),
        "bucket_C_recoverable_via_hub_doc_id": len(bucket_c_recoverable),
        "real_bucket_C_rows": real_bucket_c,
        "artifact_bucket_C_rows": artifact_bucket_c,
        "recovered_bucket_C_rows": recovered_bucket_c,
        "blank_row_recovery": resolved_blank_recovery,
        "root_cause": root_cause,
        "recommendation": recommendation,
        "should_regenerate_bucket_C_plan": (
            len(bucket_c_blank) > 0
        ),
    }


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "row_index", "match_bucket", "resolved_bucket",
    "hub_doc_id", "hub_file_name", "match_reason", "match_score",
    "classification",
]


def write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, default=str, indent=2)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Blank Square9 metadata diagnostic (read-only)."
    )
    ap.add_argument(
        "--resolved-csv",
        default="prod_reports/square9_only_triage_resolved.csv",
    )
    ap.add_argument(
        "--parity-csv",
        default="prod_reports/square9_hub_ap_parity_invoice_set.csv",
    )
    ap.add_argument(
        "--triage-csv",
        default="prod_reports/square9_only_triage.csv",
    )
    ap.add_argument(
        "--out-csv",
        default="prod_reports/blank_square9_metadata_diagnostic.csv",
    )
    ap.add_argument(
        "--json",
        default="prod_reports/blank_square9_metadata_diagnostic.json",
    )
    args = ap.parse_args()

    resolved = _read_csv(args.resolved_csv)
    print(f"Loaded {len(resolved)} resolved row(s) from {args.resolved_csv}",
          file=sys.stderr)

    parity: List[Dict[str, str]] = []
    if os.path.exists(args.parity_csv):
        parity = _read_csv(args.parity_csv)
        print(f"Loaded {len(parity)} parity row(s) from {args.parity_csv}",
              file=sys.stderr)
    else:
        print(f"  [skip] parity CSV not present: {args.parity_csv}",
              file=sys.stderr)

    triage: Optional[List[Dict[str, str]]] = None
    if os.path.exists(args.triage_csv):
        triage = _read_csv(args.triage_csv)
        print(f"Loaded {len(triage)} triage row(s) from {args.triage_csv}",
              file=sys.stderr)
    else:
        print(f"  [skip] triage CSV not present: {args.triage_csv}",
              file=sys.stderr)

    result = analyze(parity, resolved, triage)
    write_csv(args.out_csv, result["blank_row_recovery"])
    write_json(args.json, result)

    print()
    print("=== blank_square9_metadata_diagnostic ===")
    print(f"  parity_csv counts:           {result['parity_counts']}")
    print(f"  resolved_csv counts:         {result['resolved_counts']}")
    if result["triage_counts"] is not None:
        print(f"  triage_csv counts:           {result['triage_counts']}")
    print()
    print("  parity_blank_match_bucket_breakdown:")
    for k, v in (result["parity_blank_match_bucket_breakdown"] or {}).items():
        print(f"    {v:5d}  match_bucket={k!r}")
    print()
    print("  resolved_blank_classification_counts:")
    for k, v in result["resolved_blank_classification_counts"].items():
        print(f"    {v:5d}  {k}")
    print()
    print(f"  Bucket C total:                       {result['bucket_C_total']}")
    print(f"  Bucket C with blank Square9 metadata: {result['bucket_C_blank_metadata']}")
    print(f"  Bucket C recoverable via hub_doc_id:  {result['bucket_C_recoverable_via_hub_doc_id']}")
    print(f"  real_bucket_C_rows:                   {result['real_bucket_C_rows']}")
    print(f"  artifact_bucket_C_rows:               {result['artifact_bucket_C_rows']}")
    print(f"  recovered_bucket_C_rows:              {result['recovered_bucket_C_rows']}")
    print()
    print(f"  ROOT CAUSE:        {result['root_cause']}")
    print(f"  RECOMMENDATION:    {result['recommendation']}")
    print(f"  REGENERATE PLAN:   {result['should_regenerate_bucket_C_plan']}")
    print()
    print(f"  out_csv:  {args.out_csv}")
    print(f"  json:     {args.json}")
    return 0 if not result["should_regenerate_bucket_C_plan"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
