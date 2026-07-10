import asyncio
import csv
import os
import sys
sys.path.insert(0, '.')

from motor.motor_asyncio import AsyncIOMotorClient

CONFIDENT_BUCKETS = {"exact_match", "strong_evidence_match"}
PARITY_CSV = "prod_reports/square9_hub_ap_parity.csv"


def top_level(path: str) -> str:
    if not path:
        return ""
    return path.strip("/").split("/")[0]


async def main():
    from services.folder_routing_service import route_with_feedback

    with open(PARITY_CSV) as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r.get("match_bucket") in CONFIDENT_BUCKETS and r.get("hub_doc_id") and r.get("square9_parent_path")]

    print(f"Comparing {len(rows)} confidently-matched documents (exact_match + strong_evidence_match).")
    print()

    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]

    agree = 0
    disagree = 0
    errors = 0
    mismatches = []

    for row in rows:
        doc_id = row["hub_doc_id"]
        real_category = top_level(row["square9_parent_path"])

        doc = await db.hub_documents.find_one({"id": doc_id})
        if not doc:
            errors += 1
            continue

        try:
            computed_path, reason, details = await route_with_feedback(
                doc,
                freight_direction=doc.get("freight_direction"),
                is_international=doc.get("is_international", False),
            )
            computed_category = top_level(computed_path)
        except Exception as e:
            errors += 1
            print(f"  ERROR routing {doc.get('file_name')}: {e}")
            continue

        if real_category.lower() == computed_category.lower():
            agree += 1
        else:
            disagree += 1
            mismatches.append({
                "file_name": doc.get("file_name"),
                "real_category": real_category,
                "computed_category": computed_category,
                "doc_id": doc_id,
            })

    print(f"=== SUMMARY ===")
    print(f"Agree:    {agree}")
    print(f"Disagree: {disagree}")
    print(f"Errors:   {errors}")
    print()

    if mismatches:
        from collections import Counter
        pair_counts = Counter((m["computed_category"], m["real_category"]) for m in mismatches)
        print("=== MISMATCH PATTERNS (computed -> real), most common first ===")
        for (computed, real), count in pair_counts.most_common(30):
            print(f"  {count:3d}x  computed={computed!r:35s} real={real!r}")


asyncio.run(main())
