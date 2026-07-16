"""
Reads the most recently generated prod_reports/cutover_proof_*/summary.json
and appends its key metrics to a square9_readiness_history collection, so
the frontend dashboard can show both the current state and the trend over
time.

Safe to run repeatedly - each run just appends a new snapshot. Read-only
against the summary.json; only writes to the new history collection.
"""
import argparse
import asyncio
import glob
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, '.')


def find_all_summaries():
    return sorted(
        glob.glob("prod_reports/cutover_proof_*/summary.json"),
        key=os.path.getmtime,
    )


def find_latest_summary():
    files = find_all_summaries()
    return files[-1] if files else None


def build_doc(path, summary):
    key_counts = summary.get("key_counts", {})
    parity = key_counts.get("parity", {})
    bucket_A = key_counts.get("bucket_A", {})
    bucket_C = key_counts.get("bucket_C", {})
    projection = key_counts.get("projection", {})
    return {
        "recorded_utc": datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat(),
        "source_summary_path": path,
        "match_rate_pct": summary.get("match_rate_pct"),
        "min_match_rate_pct": summary.get("min_match_rate_pct"),
        "decision": summary.get("decision"),
        "blockers": summary.get("blockers", []),
        "square_count": parity.get("square_count"),
        "hub_count": parity.get("hub_count"),
        "matched_count": parity.get("matched_count"),
        "bucket_counts": parity.get("bucket_counts"),
        "bucket_A_actionable_cohort_count": bucket_A.get("actionable_cohort_count"),
        "bucket_A_actionable_doc_count": bucket_A.get("actionable_doc_count"),
        "bucket_A_manual_review_cohort_count": bucket_A.get("manual_review_cohort_count"),
        "bucket_C_intake_channel_change_cohort_count": bucket_C.get("intake_channel_change_cohort_count"),
        "bucket_C_parity_exclusion_cohort_count": bucket_C.get("parity_exclusion_cohort_count"),
        "bucket_C_intake_cohort_detail": bucket_C.get("intake_cohort_detail", []),
        "projected_match_rate_pct": projection.get("post_bucket_A_apply_match_rate_pct"),
    }


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--backfill-all", action="store_true",
                    help="Record every existing summary.json found, not just the latest")
    args = p.parse_args()

    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]

    paths = find_all_summaries() if args.backfill_all else ([find_latest_summary()] if find_latest_summary() else [])
    if not paths:
        print("No cutover_proof summary.json found under prod_reports/ - nothing to record.")
        return

    recorded = 0
    for path in paths:
        with open(path) as f:
            summary = json.load(f)
        doc = build_doc(path, summary)
        # Avoid duplicate entries if this script gets run more than once
        # against the same summary file.
        existing = await db.square9_readiness_history.find_one({"source_summary_path": path})
        if existing:
            continue
        await db.square9_readiness_history.insert_one(doc)
        recorded += 1
        print(f"Recorded: {path} :: match_rate={doc['match_rate_pct']} decision={doc['decision']}")

    total = await db.square9_readiness_history.count_documents({})
    print(f"\nNewly recorded: {recorded}")
    print(f"Total snapshots in history: {total}")


asyncio.run(main())
