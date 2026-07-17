"""
One-off backfill: sync doc_type from document_type for the specific 3
documents processed during tonight's reprocess_budget_error_documents.py
test run, before the doc_type write bug was fixed. Their document_type/
extracted_fields are already correct and already paid for (real LLM
calls already happened) - this just syncs the one field that was
missed, with no new LLM call needed.
"""
import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient

DOC_IDS = [
    "4f5d8aa9-4ae3-43ce-b4c4-39f124e1041c",
    "367d0a9d-9f2b-4166-84e1-26b7470fc213",
    "9c9ab0b7-eae0-4bb0-b18b-cc9ef7079367",
]


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    for doc_id in DOC_IDS:
        doc = await db.hub_documents.find_one(
            {"id": doc_id}, {"_id": 0, "document_type": 1, "file_name": 1, "doc_type": 1}
        )
        if not doc:
            print(doc_id, ":: not found")
            continue
        dtype = doc.get("document_type")
        if dtype and dtype != "Unknown":
            await db.hub_documents.update_one(
                {"id": doc_id}, {"$set": {"doc_type": dtype}}
            )
            print(f"{doc_id}  {doc.get('file_name')}  doc_type: {doc.get('doc_type')!r} -> {dtype!r}")
        else:
            print(doc_id, doc.get("file_name"), ":: no usable document_type, skipping")


if __name__ == "__main__":
    asyncio.run(main())
