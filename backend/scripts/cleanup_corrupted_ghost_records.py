"""
Cleans up corrupted "ghost" duplicate records created by the auto-split
runaway-suffix bug (fixed 2026-07-14). These records are safely
identifiable: email_id matching the Hub-internal batch-split pattern
AND vendor_canonical is None (meaning extraction/classification never
even ran on them - they're pure duplicate junk, not real documents).

Defaults to dry run: reports what would be deleted, changes nothing.
Requires --confirm DELETE to actually remove records.
"""
import argparse
import asyncio
import os
import sys
sys.path.insert(0, '.')


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--confirm", default=None, help="Pass DELETE to actually remove records")
    args = p.parse_args()

    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]

    query = {"email_id": {"$regex": "^batch-.*-doc1$"}, "vendor_canonical": None}
    count = await db.hub_documents.count_documents(query)
    print(f"Corrupted ghost records found: {count}")
    print()

    sample = await db.hub_documents.find(query, {"_id": 0, "id": 1, "file_name": 1, "created_utc": 1}).limit(5).to_list(5)
    print("Sample (first 5):")
    for s in sample:
        fname = s.get("file_name", "")
        short_name = fname[:60] + ("..." if len(fname) > 60 else "")
        print(f"  id={s.get('id')} created={s.get('created_utc')} file_name_len={len(fname)} :: {short_name}")
    print()

    if args.confirm != "DELETE":
        print("DRY RUN ONLY - no changes made. Re-run with --confirm DELETE to actually remove these records.")
        return

    result = await db.hub_documents.delete_many(query)
    print(f"Deleted: {result.deleted_count}")


asyncio.run(main())
