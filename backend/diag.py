import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os, json

async def check():
    client = AsyncIOMotorClient(os.environ.get("MONGO_URL"))
    db = client[os.environ.get("DB_NAME")]

    doc = await db.hub_documents.find_one(
        {"bc_vendor_number": "TUMALOC", "status": "NeedsReview", "doc_type": {"$regex": "AP", "$options": "i"}},
        {"_id": 0, "id": 1, "status": 1, "readiness": 1, "auto_draft_created": 1, "draft_review_status": 1, "bc_purchase_invoice_no": 1, "automation_decision": 1, "extracted_fields.invoice_number": 1, "extracted_fields.amount": 1, "extracted_fields.vendor": 1, "doc_type": 1}
    )
    print("=== TUMALOC AP Invoice ===")
    print(json.dumps(doc, indent=2, default=str) if doc else "None")

    pipeline = [
        {"$match": {"is_duplicate": {"$ne": True}}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    statuses = await db.hub_documents.aggregate(pipeline).to_list(20)
    print("\n=== STATUS DISTRIBUTION ===")
    for s in statuses:
        print(f"  {s['_id']}: {s['count']}")

asyncio.run(check())
