"""
ingest_bucket_A_corrections.py — feed high-confidence, verified Bucket A
misclassifications from the Square9 cutover readiness check into the
existing classification learning loop (classification_corrections),
so the next document from the same vendor gets classified correctly
the first time instead of needing another diagnostic session to catch.

Why this exists (2026-07-17): the readiness chain already root-causes
Bucket A rows (Square9-only docs Hub actually has, just classified
wrong) with real confidence scores. Separately, the classification
pipeline already reads classification_corrections on every document
and injects matching corrections as few-shot context into the Gemini
prompt (services/feedback_loop_service.py::build_feedback_context_for_
prompt) - confirmed live: 27,905 records, 10,117 of them real type
changes, most recent one hours old. That loop is real and working. But
it only ever sees corrections made through the normal document-review
UI - it has no idea the readiness chain's diagnostic work ever
happened. This script is the bridge: it turns verified Bucket A
findings into the same shape of record a human UI correction would
produce, so they feed the same loop.

Deliberately conservative about WHICH Bucket A rows qualify, because
this writes into a collection that directly shapes future AI behavior
for every document from a matching vendor:

  1. Only root causes where the document's TYPE itself was actually
     wrong (sales_mailbox_captured_AP_invoice, operations_mailbox_
     captured_AP_invoice, high_confidence_AP_invoice_misrouted) are
     considered at all. square9_ap_folder_contains_non_ap_document is
     the opposite signal - Square9's own filing put a non-AP document
     near AP folders, which says nothing reliable about whether Hub's
     classification was wrong, and low_confidence_match_ambiguous is
     explicitly uncertain. Neither should be taught to the classifier
     as a confident example.

  2. On top of that root-cause filter, best_hub_doc_type must not
     already be "AP_INVOICE". Some high_confidence_AP_invoice_
     misrouted rows have doc_type already correct - Hub correctly
     called it an AP invoice, the problem was purely which mailbox/
     folder it landed in, a routing problem (already handled by
     bucket_A_routing_rule_addition_dryrun.py), not a classification
     problem. Feeding original_type == corrected_type would be
     meaningless - the existing record_correction() function this
     mirrors already explicitly skips exactly that case.

  3. Score floor of 0.90, matching the same bar bucket_A_misrouting_
     remediation_plan.py already uses to call a Bucket A row
     "actionable" rather than "manual review."

  4. Idempotent: every inserted record is tagged corrected_by=
     "readiness_check_bucket_a" and keyed on doc_id, so re-running
     this after every future readiness check (the intended, standing
     usage) never double-teaches the same correction.

  5. Dry-run by default, matching every other data-modifying script
     touched tonight (cleanup_mail_intake_log_duplicates.py, the
     bucket_A_one_shot_data_patch_dryrun.py family) - this writes to
     a collection that shapes live AI classification behavior for
     every future document from a matching vendor, so it gets an
     explicit --confirm requirement rather than writing by default.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Root causes that represent a genuine "Hub's doc_type classification
# was wrong" signal. square9_ap_folder_contains_non_ap_document and
# low_confidence_match_ambiguous are deliberately excluded - see module
# docstring.
QUALIFYING_ROOT_CAUSES = {
    "sales_mailbox_captured_AP_invoice",
    "operations_mailbox_captured_AP_invoice",
    "high_confidence_AP_invoice_misrouted",
}

CORRECTED_BY_MARKER = "readiness_check_bucket_a"


def load_bucket_a_rows(csv_path: str) -> List[Dict[str, str]]:
    if not os.path.exists(csv_path):
        print(f"ERROR: {csv_path} not found. Run bucket_A_root_cause_report.py first.",
              file=sys.stderr)
        sys.exit(1)
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def filter_qualifying_rows(
    rows: List[Dict[str, str]], min_score: float,
) -> List[Dict[str, str]]:
    qualifying = []
    for r in rows:
        root_cause = (r.get("root_cause") or "").strip()
        if root_cause not in QUALIFYING_ROOT_CAUSES:
            continue
        doc_type = (r.get("best_hub_doc_type") or "").strip()
        if doc_type == "AP_INVOICE":
            # Doc_type was already correct - this is a routing problem,
            # not a classification problem. Not this script's job.
            continue
        try:
            score = float(r.get("best_match_score") or 0.0)
        except ValueError:
            continue
        if score < min_score:
            continue
        if not (r.get("best_hub_doc_id") or "").strip():
            continue
        qualifying.append(r)
    return qualifying


def enrich_from_mongo(db, doc_id: str) -> Dict[str, Any]:
    """Best-effort enrichment for vendor fields and a text snippet -
    the Bucket A CSV doesn't carry vendor info, only the classification
    learning loop's schema wants it. Returns {} on any lookup miss;
    callers must tolerate missing enrichment gracefully, since a
    missing vendor field just means a slightly less rich correction,
    not something worth failing over."""
    doc = db.hub_documents.find_one(
        {"id": doc_id},
        {"_id": 0, "vendor_canonical": 1, "extracted_fields.vendor": 1,
         "file_name": 1},
    )
    if not doc:
        return {}
    ef = doc.get("extracted_fields") or {}
    return {
        "vendor_canonical": (doc.get("vendor_canonical") or "").strip(),
        "vendor_raw": (ef.get("vendor") or "").strip(),
        "file_name": (doc.get("file_name") or "").strip(),
    }


def build_correction_record(
    row: Dict[str, str], enrichment: Dict[str, Any], run_label: str,
) -> Dict[str, Any]:
    doc_id = row["best_hub_doc_id"].strip()
    original_type = (row.get("best_hub_doc_type") or "").strip() or "UNKNOWN"
    file_name = enrichment.get("file_name") or row.get("best_hub_file_name", "")
    text_snippet = (
        f"Square9 filename: {row.get('square9_name', '')} | "
        f"Square9 folder: {row.get('square9_parent_path', '')} | "
        f"Email subject: {row.get('email_subject', '')} | "
        f"Sender: {row.get('email_sender', '')}"
    )[:500]
    return {
        "doc_id": doc_id,
        "original_type": original_type,
        "corrected_type": "AP_INVOICE",
        "corrected_by": CORRECTED_BY_MARKER,
        "corrected_at": datetime.now(timezone.utc).isoformat(),
        "file_name": file_name,
        "vendor_raw": enrichment.get("vendor_raw", ""),
        "vendor_canonical": enrichment.get("vendor_canonical", ""),
        "text_snippet": text_snippet,
        "classification_method": (row.get("classification_method") or "").strip(),
        "classification_confidence": float(row.get("best_match_score") or 0.0),
        # Provenance - distinguishes this from a human UI correction so
        # future reviewers of classification_corrections can tell the
        # two apart at a glance.
        "source": "square9_cutover_readiness_bucket_A",
        "source_root_cause": (row.get("root_cause") or "").strip(),
        "source_readiness_run": run_label,
    }


def run(
    csv_path: str, min_score: float, confirm: bool, run_label: str,
) -> Dict[str, Any]:
    from pymongo import MongoClient

    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    rows = load_bucket_a_rows(csv_path)
    qualifying = filter_qualifying_rows(rows, min_score)

    already_recorded = 0
    inserted = 0
    would_insert = 0
    records_preview: List[Dict[str, Any]] = []

    for row in qualifying:
        doc_id = row["best_hub_doc_id"].strip()
        existing = db.classification_corrections.find_one(
            {"doc_id": doc_id, "corrected_by": CORRECTED_BY_MARKER},
            {"_id": 1},
        )
        if existing:
            already_recorded += 1
            continue

        enrichment = enrich_from_mongo(db, doc_id)
        record = build_correction_record(row, enrichment, run_label)

        if confirm:
            db.classification_corrections.insert_one(record)
            inserted += 1
        else:
            would_insert += 1
            records_preview.append(record)

    return {
        "csv_path": csv_path,
        "min_score": min_score,
        "confirm": confirm,
        "total_bucket_A_rows": len(rows),
        "qualifying_rows": len(qualifying),
        "already_recorded": already_recorded,
        "inserted": inserted,
        "would_insert": would_insert,
        "records_preview": records_preview[:10],
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Feed verified Bucket A misclassifications from the "
                     "readiness check into the existing classification "
                     "learning loop (classification_corrections). "
                     "Dry-run by default."
    )
    ap.add_argument(
        "--bucket-a-csv", default="prod_reports/bucket_A_root_cause.csv",
    )
    ap.add_argument(
        "--min-score", type=float, default=0.90,
        help="Minimum best_match_score to qualify (default 0.90, matching "
             "bucket_A_misrouting_remediation_plan.py's actionable bar).",
    )
    ap.add_argument(
        "--confirm", action="store_true",
        help="Actually write to classification_corrections. Without this "
             "flag, prints what WOULD be written and makes no changes.",
    )
    ap.add_argument(
        "--run-label", default=None,
        help="Optional label recorded on each correction (e.g. the "
             "cutover_proof_* directory name) for provenance. Defaults "
             "to the current UTC timestamp.",
    )
    ap.add_argument(
        "--out-json", default="prod_reports/bucket_A_corrections_preview.json",
        help="Always written (dry-run or --confirm) so this step leaves "
             "a persistent artifact in prod_reports/ like every other "
             "step in the chain, not just stdout.",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    run_label = args.run_label or datetime.now(timezone.utc).strftime(
        "manual_%Y%m%dT%H%M%SZ"
    )

    result = run(args.bucket_a_csv, args.min_score, args.confirm, run_label)

    if args.out_json:
        os.makedirs(os.path.dirname(args.out_json) or ".", exist_ok=True)
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump(result, f, default=str, indent=2)

    if args.json:
        print(json.dumps(result, default=str, indent=2))
        return 0

    print("=== ingest_bucket_A_corrections ===")
    print(f"  bucket_a_csv:        {result['csv_path']}")
    print(f"  min_score:           {result['min_score']}")
    print(f"  mode:                {'CONFIRM (writing)' if result['confirm'] else 'DRY RUN (no writes)'}")
    print(f"  total_bucket_A_rows: {result['total_bucket_A_rows']}")
    print(f"  qualifying_rows:     {result['qualifying_rows']}")
    print(f"  already_recorded:    {result['already_recorded']}  (idempotent skip)")
    if result["confirm"]:
        print(f"  inserted:            {result['inserted']}")
    else:
        print(f"  would_insert:        {result['would_insert']}")
        if result["records_preview"]:
            print()
            print("  PREVIEW (first 10, no writes performed):")
            for rec in result["records_preview"]:
                print(
                    f"    doc_id={rec['doc_id']}  "
                    f"{rec['original_type']} -> {rec['corrected_type']}  "
                    f"vendor={rec['vendor_canonical'] or rec['vendor_raw'] or '<unknown>'!r}  "
                    f"confidence={rec['classification_confidence']}"
                )
        print()
        print("  Re-run with --confirm to actually write these corrections.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
