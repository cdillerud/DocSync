import asyncio
import base64
import os
import sys
sys.path.insert(0, '.')

from motor.motor_asyncio import AsyncIOMotorClient

TODAY_PREFIX = "2026-07-09"


async def main():
    from services.sharepoint_service import upload_to_sharepoint_with_routing

    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]

    cursor = db.hub_documents.find({
        "created_utc": {"$regex": f"^{TODAY_PREFIX}"},
        "status": {"$ne": "batch_parent"},
    })
    docs = await cursor.to_list(length=None)
    total = len(docs)
    print(f"Found {total} documents to release to the test site.")
    print()

    succeeded = 0
    failed = 0
    missing_content = 0

    for i, doc in enumerate(docs, 1):
        content_b64 = doc.get("file_content_b64")
        if not content_b64:
            missing_content += 1
            print(f"[{i}/{total}] SKIP (no file_content_b64): {doc.get('file_name')}")
            continue

        try:
            file_content = base64.b64decode(content_b64)
            result = await upload_to_sharepoint_with_routing(
                file_content,
                doc.get("file_name", f"{doc.get('id')}.pdf"),
                doc,
                freight_direction=doc.get("freight_direction"),
                is_international=doc.get("is_international", False),
            )
            succeeded += 1
            if i % 10 == 0 or i == total:
                print(f"[{i}/{total}] OK ({succeeded} succeeded, {failed} failed, {missing_content} missing so far)")
        except Exception as e:
            failed += 1
            print(f"[{i}/{total}] FAILED: {doc.get('file_name')} -> {e}")

    print()
    print("=== DONE ===")
    print(f"Total: {total}  Succeeded: {succeeded}  Failed: {failed}  Missing content: {missing_content}")


asyncio.run(main())

