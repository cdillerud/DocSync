"""
diagnose_hub_documents_id_field.py
==================================
READ-ONLY one-shot diagnostic. Identifies which field on
``hub_documents`` carries the UUIDs that the parity / Bucket A
remediation pipeline calls ``best_hub_doc_id``.

Useful when the preflight reports ``S0: doc not found in
hub_documents`` for IDs that demonstrably came out of the parity report
— almost always a field-name mismatch between the parity output and
the live collection.

Performs only ``count_documents`` and a single ``find_one`` projection.
No writes. No iteration over the full collection.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

CANDIDATE_ID_FIELDS = [
    "_id",
    "id",
    "doc_id",
    "document_id",
    "hub_doc_id",
]

DEFAULT_PROBE_IDS = [
    "9391f78f-33c2-4186-9199-7df2da1124bb",
    "5fe1d5c2-275c-4bbd-a693-6073a0fe9567",
]


def get_collection():
    from pymongo import MongoClient  # noqa: WPS433
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise RuntimeError("MONGO_URL / DB_NAME env vars are required.")
    return MongoClient(mongo_url)[db_name]["hub_documents"]


def main() -> int:
    p = argparse.ArgumentParser(
        description="Locate which field on hub_documents carries a "
                    "given list of doc UUIDs (read-only).",
    )
    p.add_argument("--ids", nargs="+", default=DEFAULT_PROBE_IDS,
                   help="UUIDs to probe across each candidate field.")
    p.add_argument(
        "--from-csv", default=None,
        help="Optional: pull the IDs from this CSV's "
             "best_hub_doc_id column (first 5 rows).",
    )
    p.add_argument("--id-fields", nargs="+", default=CANDIDATE_ID_FIELDS)
    args = p.parse_args()

    ids: List[str] = list(args.ids)
    if args.from_csv:
        import csv
        with open(args.from_csv, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            ids = []
            for i, row in enumerate(reader):
                if i >= 5:
                    break
                v = (row.get("best_hub_doc_id") or "").strip()
                if v:
                    ids.append(v)
    if not ids:
        print("ERROR: no IDs to probe.", file=sys.stderr)
        return 1

    coll = get_collection()
    print()
    print("=== diagnose_hub_documents_id_field ===")
    print(f"  total_documents (estimated) : {coll.estimated_document_count()}")
    print(f"  probe_ids ({len(ids)}):")
    for v in ids:
        print(f"    {v}")
    print()
    print("  per-field hits:")
    hits_by_field: Dict[str, int] = {}
    for f in args.id_fields:
        try:
            n = coll.count_documents({f: {"$in": ids}})
        except Exception as e:  # noqa: BLE001
            print(f"    {f:18s} ERROR {type(e).__name__}: {e}")
            continue
        hits_by_field[f] = n
        print(f"    {f:18s} hits = {n}")

    sample = coll.find_one(
        {},
        {
            "_id": 1, "id": 1, "doc_id": 1, "document_id": 1,
            "hub_doc_id": 1, "mailbox_category": 1, "doc_type": 1,
            "suggested_job_type": 1, "routing_status": 1,
            "routing_reason": 1, "sharepoint_folder_path": 1,
            "email_sender": 1, "file_name": 1,
        },
    )
    print()
    print("  sample doc keys present:")
    if sample:
        for k in sorted(sample.keys()):
            v: Any = sample[k]
            preview = str(v)
            if len(preview) > 60:
                preview = preview[:57] + "..."
            print(f"    {k:24s} = {preview}")
    else:
        print("    (no docs in collection)")
    print()

    winners = [f for f, n in hits_by_field.items() if n > 0]
    if winners:
        print(f"  WINNER: {winners[0]!r} — fix preflight + apply to look up "
              f"by this field instead of '_id'.")
        rc = 0
    else:
        print("  NO FIELD HIT. Possibilities:")
        print("    - the IDs are stale (deleted from hub_documents)")
        print("    - the parity report sources `best_hub_doc_id` from a")
        print("      different collection altogether (e.g., aggregation)")
        print("    - the live hub_documents primary key is something other")
        print(f"      than the {len(args.id_fields)} fields probed; try")
        print("      passing --id-fields with the suspected name.")
        rc = 2

    print()
    print(json.dumps({"hits_by_field": hits_by_field,
                      "sample_keys_present": sorted((sample or {}).keys()),
                      "probe_ids": ids,
                      "winner": winners[0] if winners else None},
                     default=str, indent=2))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
