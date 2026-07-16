"""
Cleans up duplicate (internet_message_id, attachment_hash) records in
mail_intake_log, blocking the uniq_msgid_hash index from building.

Confirmed via direct inspection: these are NOT evidence of broken
deduplication - within each duplicate group, exactly one record shows
status='Processed' with a real sharepoint_doc_id (the genuine, correct
processing), and the rest show status='SkippedDuplicate',
sharepoint_doc_id=None (log entries correctly documenting that later
poll cycles detected and skipped the same email/attachment). The
application-level dedup check has been working correctly; this index
was meant as an additional backstop specifically against race
conditions, which aren't occurring given sequential, locked polling.

Strategy: for each duplicate group, keep exactly one record - prefer
the one with status='Processed' (the real one) if present, otherwise
keep the oldest by _id. Delete the rest.

Defaults to dry run: reports what would be deleted, changes nothing.
Requires --confirm DELETE to actually remove records and rebuild the
index.
"""
import argparse
import asyncio
import os
import sys
sys.path.insert(0, '.')


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--confirm", default=None, help="Pass DELETE to actually clean up and rebuild the index")
    args = p.parse_args()

    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]

    pipeline = [
        {"$match": {"internet_message_id": {"$type": "string", "$gt": ""},
                     "attachment_hash": {"$type": "string", "$gt": ""}}},
        {"$group": {
            "_id": {"msg": "$internet_message_id", "hash": "$attachment_hash"},
            "count": {"$sum": 1},
            "docs": {"$push": {"id": "$_id", "status": "$status"}},
        }},
        {"$match": {"count": {"$gt": 1}}},
    ]
    groups = await db.mail_intake_log.aggregate(pipeline).to_list(length=None)
    print(f"Duplicate groups found: {len(groups)}")

    to_delete = []
    kept_processed = 0
    kept_oldest = 0

    for g in groups:
        docs = g["docs"]  # already in insertion order (oldest first) from $push
        processed = [d for d in docs if d.get("status") == "Processed"]
        if processed:
            keep_id = processed[0]["id"]
            kept_processed += 1
        else:
            keep_id = docs[0]["id"]
            kept_oldest += 1
        for d in docs:
            if d["id"] != keep_id:
                to_delete.append(d["id"])

    print(f"Groups keeping a real Processed record: {kept_processed}")
    print(f"Groups with no Processed record (kept oldest instead): {kept_oldest}")
    print(f"Total records that would be deleted: {len(to_delete)}")

    if args.confirm != "DELETE":
        print()
        print("DRY RUN ONLY - no changes made. Re-run with --confirm DELETE to actually clean up.")
        return

    result = await db.mail_intake_log.delete_many({"_id": {"$in": to_delete}})
    print(f"Deleted: {result.deleted_count}")

    print("Rebuilding uniq_msgid_hash index...")
    try:
        await db.mail_intake_log.create_index(
            [("internet_message_id", 1), ("attachment_hash", 1)],
            unique=True,
            partialFilterExpression={
                "internet_message_id": {"$type": "string", "$gt": ""},
                "attachment_hash": {"$type": "string", "$gt": ""},
            },
            name="uniq_msgid_hash",
        )
        print("Index built successfully.")
    except Exception as e:
        print(f"Index build still failing: {e}")


asyncio.run(main())
