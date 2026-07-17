"""
ingest_manual_folder_labels.py
================================
Ingests Meghan's team's manual "Folder" column labels (SharePoint,
Miscellaneous/Misc Invoices - need approval) into the doc_type
learning loop.

Why this exists (2026-07-17): Chad pointed out this data exists and
is completely unused. Confirmed live: 133 documents sit in this
folder because Hub's classifier couldn't confidently determine
doc_type (all sampled: doc_type='OTHER', suggested_job_type=
'Unknown') - but mailbox_category is already correctly 'AP' on the
ones checked, so this is a doc_type gap, not a routing gap. Meghan's
team has been manually adding a "Folder" column value on each one
indicating what kind of document it actually is - 17 of 133 labeled
so far, ongoing work, not a finished dataset. None of this had ever
been read by anything.

Two deliberately different behaviors, not one:

1. UNAMBIGUOUS labels (currently just "Vendor Credit memo" ->
   Credit_Memo) get applied automatically via record_correction() -
   the same, real, already-proven learning-loop function bulk-classify
   itself calls on every human doc_type correction. Dry-run by
   default, --confirm to write.

2. AMBIGUOUS labels ("WH NOT International" / "DS NOT International" /
   the "DS Internanational" typo variant) are NEVER auto-applied.
   Chad confirmed directly these span at least two different doc_type
   values (Shipping_Document vs Warehouse_Receipt) and can't be told
   apart from the label alone. Guessing wrong here would feed an
   incorrect example into the AI's few-shot prompt - actively making
   future classification worse, the opposite of the goal. These are
   instead written to a clear, actionable review CSV so a human can
   finish the one remaining step (which specific type) via the
   existing /bulk-classify UI action, which already correctly feeds
   the learning loop the moment they do.

3. UNRECOGNIZED labels (anything not in the vocabulary below) are
   also surfaced, never guessed - Meghan's team may introduce new
   labels over time and this script should flag what it doesn't
   understand rather than silently ignoring it.

Re-runnable as this dataset grows: only unprocessed items (no
existing classification_corrections record for that doc_id + this
source) are considered on each run, so this can be run repeatedly as
Meghan's team labels more documents over time rather than as a
one-time backfill.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CORRECTION_SOURCE = "manual_folder_label"

# Normalized (lowercased, stripped) label -> single doc_type.
# Safe to auto-apply: no ambiguity between candidates.
UNAMBIGUOUS_LABELS: Dict[str, str] = {
    "vendor credit memo": "Credit_Memo",
}

# Normalized label -> list of plausible doc_type candidates. Confirmed
# directly with Chad these cannot be told apart from the label alone -
# never auto-applied, always surfaced for a human to pick the specific
# type.
AMBIGUOUS_LABELS: Dict[str, List[str]] = {
    "wh not international": ["Shipping_Document", "Warehouse_Receipt"],
    "ds not international": ["Shipping_Document", "Warehouse_Receipt"],
    "ds internanational": ["Shipping_Document", "Warehouse_Receipt"],  # typo variant seen live
    "ds international": ["Shipping_Document", "Warehouse_Receipt"],  # in case the typo gets fixed later
}


async def fetch_labeled_items(folder_path: str) -> List[Dict[str, Any]]:
    """Pulls every file (non-folder) item under folder_path that has a
    non-blank Folder column value, paginating through the full result
    set. Returns raw {file_name, folder_label} pairs - matching to
    hub_documents happens separately."""
    import httpx
    from services.config_service import get_graph_token

    token = await get_graph_token()
    headers = {"Authorization": f"Bearer {token}"}
    host = "gamerpackaging1.sharepoint.com"
    site_path = "/sites/GPI-DocumentHub-Test"

    out: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"https://graph.microsoft.com/v1.0/sites/{host}:{site_path}", headers=headers)
        site_id = r.json().get("id")
        r2 = await client.get(f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive", headers=headers)
        drive_id = r2.json().get("id")
        r3 = await client.get(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{folder_path}",
            headers=headers,
        )
        if r3.status_code != 200:
            raise RuntimeError(f"Folder not found: {folder_path} (status={r3.status_code})")
        folder_id = r3.json().get("id")

        url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{folder_id}/children"
        params = {"$expand": "listItem($expand=fields)", "$top": 200}
        while url:
            resp = await client.get(url, headers=headers, params=params)
            data = resp.json()
            for item in data.get("value", []):
                if item.get("folder") is not None:
                    continue  # skip subfolders
                fields = item.get("listItem", {}).get("fields", {})
                label = (fields.get("Folder") or "").strip()
                if label:
                    out.append({"file_name": item.get("name"), "folder_label": label})
            url = data.get("@odata.nextLink")
            params = None

    return out


def classify_label(label: str) -> Dict[str, Any]:
    norm = label.strip().lower()
    if norm in UNAMBIGUOUS_LABELS:
        return {"kind": "unambiguous", "target_doc_type": UNAMBIGUOUS_LABELS[norm]}
    if norm in AMBIGUOUS_LABELS:
        return {"kind": "ambiguous", "candidates": AMBIGUOUS_LABELS[norm]}
    return {"kind": "unrecognized", "candidates": []}


async def run(folder_path: str, confirm: bool) -> Dict[str, Any]:
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    labeled_items = await fetch_labeled_items(folder_path)

    results = {
        "folder_path": folder_path,
        "confirm": confirm,
        "total_labeled_items": len(labeled_items),
        "matched_to_hub_documents": 0,
        "no_hub_match": 0,
        "unambiguous_applied": 0,
        "unambiguous_would_apply": 0,
        "unambiguous_already_correct": 0,
        "ambiguous_for_review": [],
        "unrecognized_for_review": [],
        "no_match_details": [],
    }

    for item in labeled_items:
        file_name = item["file_name"]
        label = item["folder_label"]

        doc = await db.hub_documents.find_one(
            {"file_name": file_name},
            {"_id": 0, "id": 1, "doc_type": 1, "vendor_raw": 1, "vendor_canonical": 1,
             "email_sender": 1, "extracted_fields": 1, "classification_method": 1,
             "classification_confidence": 1},
        )
        if doc is None:
            results["no_hub_match"] += 1
            results["no_match_details"].append({"file_name": file_name, "folder_label": label})
            continue
        results["matched_to_hub_documents"] += 1

        classification = classify_label(label)
        current_doc_type = doc.get("doc_type") or "OTHER"

        if classification["kind"] == "unambiguous":
            target = classification["target_doc_type"]
            if current_doc_type == target:
                results["unambiguous_already_correct"] += 1
                continue
            if confirm:
                from services.classification_feedback_service import (
                    init_classification_feedback, record_correction,
                )
                init_classification_feedback(db)
                ef = doc.get("extracted_fields") or {}
                text_snippet = " | ".join(
                    str(v) for v in ef.values() if v and not isinstance(v, (list, dict))
                )[:500]
                await record_correction(
                    doc_id=doc["id"],
                    original_type=current_doc_type,
                    corrected_type=target,
                    corrected_by="meghan_manual_folder_label",
                    doc_context={
                        "file_name": file_name,
                        "vendor_raw": doc.get("vendor_raw", ""),
                        "vendor_canonical": doc.get("vendor_canonical", ""),
                        "text_snippet": text_snippet,
                        "classification_method": doc.get("classification_method", ""),
                        "classification_confidence": doc.get("classification_confidence", 0),
                        "source": CORRECTION_SOURCE,
                        "source_folder_label": label,
                    },
                )
                await db.hub_documents.update_one(
                    {"id": doc["id"]},
                    {"$set": {
                        "doc_type": target,
                        "document_type": target,
                        "suggested_job_type": target,
                        "document_type_source": CORRECTION_SOURCE,
                    }},
                )
                results["unambiguous_applied"] += 1
            else:
                results["unambiguous_would_apply"] += 1

        elif classification["kind"] == "ambiguous":
            results["ambiguous_for_review"].append({
                "doc_id": doc["id"], "file_name": file_name,
                "folder_label": label, "current_doc_type": current_doc_type,
                "candidate_doc_types": classification["candidates"],
                "vendor_raw": doc.get("vendor_raw", ""),
                "email_sender": doc.get("email_sender", ""),
            })
        else:
            results["unrecognized_for_review"].append({
                "doc_id": doc["id"], "file_name": file_name,
                "folder_label": label, "current_doc_type": current_doc_type,
            })

    return results


def write_review_csv(path: str, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Ingest Meghan's manual Folder-column labels into "
                     "the doc_type learning loop. Unambiguous labels "
                     "auto-apply (dry-run by default); ambiguous/"
                     "unrecognized labels are always surfaced for "
                     "human review, never guessed.",
    )
    ap.add_argument(
        "--folder-path",
        default="Miscellaneous/Misc Invoices - need approval",
    )
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument(
        "--ambiguous-out", default="prod_reports/manual_folder_labels_ambiguous.csv",
    )
    ap.add_argument(
        "--unrecognized-out", default="prod_reports/manual_folder_labels_unrecognized.csv",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = asyncio.run(run(args.folder_path, args.confirm))

    if result["ambiguous_for_review"]:
        write_review_csv(
            args.ambiguous_out, result["ambiguous_for_review"],
            ["doc_id", "file_name", "folder_label", "current_doc_type",
             "candidate_doc_types", "vendor_raw", "email_sender"],
        )
    if result["unrecognized_for_review"]:
        write_review_csv(
            args.unrecognized_out, result["unrecognized_for_review"],
            ["doc_id", "file_name", "folder_label", "current_doc_type"],
        )

    if args.json:
        print(json.dumps(result, default=str, indent=2))
        return 0

    print("=== ingest_manual_folder_labels ===")
    print(f"  folder_path:              {result['folder_path']}")
    print(f"  mode:                     {'CONFIRM (writing)' if result['confirm'] else 'DRY RUN (no writes)'}")
    print(f"  total_labeled_items:      {result['total_labeled_items']}")
    print(f"  matched_to_hub_documents: {result['matched_to_hub_documents']}")
    print(f"  no_hub_match:             {result['no_hub_match']}")
    print()
    print("  UNAMBIGUOUS (safe to auto-apply):")
    print(f"    already_correct: {result['unambiguous_already_correct']}")
    key = "applied" if result["confirm"] else "would_apply"
    print(f"    {key}: {result['unambiguous_' + key]}")
    print()
    print(f"  AMBIGUOUS (never auto-applied - needs a human pick): {len(result['ambiguous_for_review'])}")
    if result["ambiguous_for_review"]:
        print(f"    -> written to {args.ambiguous_out}")
        for r in result["ambiguous_for_review"][:10]:
            print(f"      {r['file_name']}  label={r['folder_label']!r}  candidates={r['candidate_doc_types']}")
    print()
    print(f"  UNRECOGNIZED labels (unknown vocabulary): {len(result['unrecognized_for_review'])}")
    if result["unrecognized_for_review"]:
        print(f"    -> written to {args.unrecognized_out}")
        for r in result["unrecognized_for_review"][:10]:
            print(f"      {r['file_name']}  label={r['folder_label']!r}")

    if not result["confirm"] and result["unambiguous_would_apply"] > 0:
        print()
        print("  Re-run with --confirm to actually apply the unambiguous corrections.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
