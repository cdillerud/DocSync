"""
investigate_low_confidence_bucket_A.py
======================================
READ-ONLY diagnostic. Examines Bucket A rows whose
``best_match_score < 0.60`` (currently classified by the root-cause
report as ``low_confidence_match_ambiguous``) and determines whether
each row is:

  - real_ambiguous_match           Hub does have a matching doc but the
                                   matcher's score legitimately falls
                                   below the 0.60 threshold (token
                                   overlap is real but weak).
  - matcher_false_positive         Hub has a doc with `best_hub_doc_id`
                                   set, but cross-checking against the
                                   parity CSV shows the same Square9
                                   row already has a hub_only / no_match
                                   verdict. The score is meaningful but
                                   the candidate is the wrong doc.
  - missing_metadata_artifact      ``square9_name`` / ``square9_parent_path``
                                   blank — same upstream artifact as the
                                   blank-metadata diagnostic.
  - should_be_bucket_C             ``best_hub_doc_id`` is empty — Hub
                                   never had the doc; the parity matcher
                                   produced zero evidence.
  - remain_manual_review           Anything that does not satisfy the
                                   above heuristics.

Inputs:
  --bucket-a-csv     prod_reports/bucket_A_root_cause.csv
  --resolved-csv     prod_reports/square9_only_triage_resolved.csv
  --parity-csv       prod_reports/square9_hub_ap_parity_invoice_set.csv

Outputs:
  prod_reports/low_confidence_bucket_A_diagnostic.csv
  prod_reports/low_confidence_bucket_A_diagnostic.json

Pure CSV-on-disk reads. No DB. No mutations.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List, Optional


def _is_blank(s: Optional[str]) -> bool:
    return not (s or "").strip()


def _read_csv(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _coerce_score(val: Any) -> float:
    try:
        return float(val or 0.0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Parity index (square9_name, square9_parent_path) -> match_bucket
# ---------------------------------------------------------------------------

def build_parity_index(parity_rows: List[Dict[str, str]]
                       ) -> Dict[tuple, str]:
    """Map (square9_name, square9_parent_path) -> match_bucket.

    Used to detect cases where the parity report itself classified a
    Square9 row as `no_match` (Hub never had it) but the resolver later
    attached a low-score Hub candidate via secondary tokens.
    """
    idx: Dict[tuple, str] = {}
    for r in parity_rows:
        key = (
            (r.get("square9_name") or "").strip(),
            (r.get("square9_parent_path") or "").strip(),
        )
        bucket = (r.get("match_bucket") or "").strip().lower()
        if not idx.get(key):
            idx[key] = bucket
    return idx


# ---------------------------------------------------------------------------
# Per-row classifier
# ---------------------------------------------------------------------------

def classify_low_confidence_row(
    row: Dict[str, str],
    parity_index: Optional[Dict[tuple, str]] = None,
) -> str:
    sq_name = (row.get("square9_name") or "").strip()
    sq_parent = (row.get("square9_parent_path") or "").strip()
    hub_doc_id = (row.get("best_hub_doc_id") or "").strip()
    score = _coerce_score(row.get("best_match_score"))
    reason = (row.get("best_match_reason") or "").strip().lower()
    root_cause = (row.get("root_cause") or "").strip()

    if _is_blank(sq_name) and _is_blank(sq_parent):
        return "missing_metadata_artifact"

    if _is_blank(hub_doc_id):
        return "should_be_bucket_C"

    if parity_index:
        key = (sq_name, sq_parent)
        parity_bucket = parity_index.get(key, "")
        if parity_bucket == "no_match":
            return "matcher_false_positive"

    if score >= 0.55 and ("token" in reason or "vendor" in reason
                          or "invoice" in reason or "date" in reason):
        return "real_ambiguous_match"

    if root_cause == "low_confidence_match_ambiguous" and score > 0:
        return "real_ambiguous_match"

    return "remain_manual_review"


# ---------------------------------------------------------------------------
# Pure analyzer
# ---------------------------------------------------------------------------

def analyze(bucket_a_rows: List[Dict[str, str]],
            parity_rows: Optional[List[Dict[str, str]]] = None,
            score_threshold: float = 0.60) -> Dict[str, Any]:
    parity_index = build_parity_index(parity_rows or [])

    low_conf: List[Dict[str, Any]] = []
    for idx, r in enumerate(bucket_a_rows):
        score = _coerce_score(r.get("best_match_score"))
        if score >= score_threshold:
            continue
        cls = classify_low_confidence_row(r, parity_index)
        low_conf.append({
            "row_index": idx,
            "square9_name": (r.get("square9_name") or "").strip(),
            "square9_parent_path": (r.get("square9_parent_path") or "").strip(),
            "best_hub_doc_id": (r.get("best_hub_doc_id") or "").strip(),
            "best_hub_file_name": (r.get("best_hub_file_name") or "").strip(),
            "best_hub_mailbox_category": (
                r.get("best_hub_mailbox_category") or ""
            ).strip(),
            "best_hub_doc_type": (r.get("best_hub_doc_type") or "").strip(),
            "best_match_score": score,
            "best_match_reason": (r.get("best_match_reason") or "").strip(),
            "root_cause": (r.get("root_cause") or "").strip(),
            "classification": cls,
        })

    cls_counts = dict(Counter(r["classification"] for r in low_conf))

    true_low_conf = cls_counts.get("real_ambiguous_match", 0)
    false_pos = cls_counts.get("matcher_false_positive", 0)
    artifact = cls_counts.get("missing_metadata_artifact", 0)
    move_to_c = cls_counts.get("should_be_bucket_C", 0)
    remain = cls_counts.get("remain_manual_review", 0)

    actionable_to_relabel = false_pos + artifact + move_to_c
    if actionable_to_relabel > 0:
        recommendation = (
            f"Regenerate the Bucket A plan after dropping/relabeling "
            f"{actionable_to_relabel} rows ({false_pos} false-positive, "
            f"{artifact} artifact, {move_to_c} should-be-C). The remaining "
            f"{true_low_conf + remain} rows are legitimate manual_review."
        )
        should_regenerate = True
    else:
        recommendation = (
            "All low-confidence rows are legitimately ambiguous; the "
            "Bucket A plan does not need to be regenerated on these "
            "grounds."
        )
        should_regenerate = False

    return {
        "score_threshold": score_threshold,
        "bucket_A_total": len(bucket_a_rows),
        "low_confidence_total": len(low_conf),
        "classification_counts": cls_counts,
        "true_low_confidence_count": true_low_conf,
        "matcher_false_positive_count": false_pos,
        "missing_metadata_artifact_count": artifact,
        "should_be_bucket_C_count": move_to_c,
        "remain_manual_review_count": remain,
        "rows": low_conf,
        "recommendation": recommendation,
        "should_regenerate_bucket_A_plan": should_regenerate,
    }


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "row_index", "classification", "best_match_score",
    "best_match_reason", "root_cause",
    "square9_name", "square9_parent_path",
    "best_hub_doc_id", "best_hub_file_name",
    "best_hub_mailbox_category", "best_hub_doc_type",
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
        description="Low-confidence Bucket A diagnostic (read-only)."
    )
    ap.add_argument(
        "--bucket-a-csv",
        default="prod_reports/bucket_A_root_cause.csv",
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
        "--out-csv",
        default="prod_reports/low_confidence_bucket_A_diagnostic.csv",
    )
    ap.add_argument(
        "--json",
        default="prod_reports/low_confidence_bucket_A_diagnostic.json",
    )
    ap.add_argument("--score-threshold", type=float, default=0.60)
    args = ap.parse_args()

    bucket_a = _read_csv(args.bucket_a_csv)
    print(f"Loaded {len(bucket_a)} Bucket A row(s) from {args.bucket_a_csv}",
          file=sys.stderr)

    parity: List[Dict[str, str]] = []
    if os.path.exists(args.parity_csv):
        parity = _read_csv(args.parity_csv)
        print(f"Loaded {len(parity)} parity row(s) from {args.parity_csv}",
              file=sys.stderr)
    else:
        print(f"  [skip] parity CSV not present: {args.parity_csv}",
              file=sys.stderr)

    result = analyze(bucket_a, parity, args.score_threshold)
    write_csv(args.out_csv, result["rows"])
    write_json(args.json, result)

    print()
    print("=== low_confidence_bucket_A_diagnostic ===")
    print(f"  bucket_A_total:                  {result['bucket_A_total']}")
    print(f"  low_confidence_total (<{result['score_threshold']:.2f}): "
          f"{result['low_confidence_total']}")
    print()
    print("  classification_counts:")
    for k, v in result["classification_counts"].items():
        print(f"    {v:4d}  {k}")
    print()
    print(f"  true_low_confidence_count:        {result['true_low_confidence_count']}")
    print(f"  matcher_false_positive_count:     {result['matcher_false_positive_count']}")
    print(f"  missing_metadata_artifact_count:  {result['missing_metadata_artifact_count']}")
    print(f"  should_be_bucket_C_count:         {result['should_be_bucket_C_count']}")
    print(f"  remain_manual_review_count:       {result['remain_manual_review_count']}")
    print()
    print(f"  RECOMMENDATION:           {result['recommendation']}")
    print(f"  REGENERATE PLAN:          {result['should_regenerate_bucket_A_plan']}")
    print()
    print(f"  out_csv:  {args.out_csv}")
    print(f"  json:     {args.json}")
    return 0 if not result["should_regenerate_bucket_A_plan"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
