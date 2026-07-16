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

Strategy: only ever delete records explicitly marked status='SkippedDuplicate'
(or 'Skipped_Duplicate') - these are confirmed-safe, purely redundant log
entries. Everything else is kept, regardless of its specific status. Found
live while building this: a group can legitimately contain BOTH a
'Processed' AND a separate 'Ingested' record - two different real
statuses, not just one - so an earlier version of this script that only
special-cased 'Processed' would have incorrectly deleted genuine
'Ingested' records. If a group somehow has no real record at all (only
SkippedDuplicate entries), keeps the oldest one as a safety fallback
rather than deleting every record for that group.

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
    groups_with_only_skipped = 0

    for g in groups:
        docs = g["docs"]
        # Only ever delete records explicitly marked as redundant
        # duplicate-detection log entries. Found live: a group can
        # legitimately contain BOTH a 'Processed' AND a separate
        # 'Ingested' record - two different real statuses, not just one -
        # so keep everything except the specifically-redundant status,
        # rather than trying to guess which single "good" status to keep.
        skipped = [d for d in docs if d.get("status") in ("SkippedDuplicate", "Skipped_Duplicate")]
        real = [d for d in docs if d.get("status") not in ("SkippedDuplicate", "Skipped_Duplicate")]
        if not real:
            # No real record at all in this group - keep the oldest
            # skipped one as a safety fallback, delete the rest.
            groups_with_only_skipped += 1
            to_delete.extend(d["id"] for d in skipped[1:])
        else:
            to_delete.extend(d["id"] for d in skipped)

    print(f"Groups with no real (non-skipped) record at all: {groups_with_only_skipped}")
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
