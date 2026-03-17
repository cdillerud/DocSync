"""Bootstrap the classification learning model from existing documents.

Run directly:  python3 backend/scripts/bootstrap_learning.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "gpi_document_hub")


async def main():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    from services.classification_feedback_service import init_classification_feedback, bootstrap_from_history

    init_classification_feedback(db)

    print("Starting bootstrap sweep...")
    result = await bootstrap_from_history()
    print(f"\nDone: {result}")

    # Show summary
    total = await db.classification_corrections.count_documents({})
    patterns = await db.vendor_type_patterns.count_documents({})
    print(f"\nTotal corrections in DB: {total}")
    print(f"Vendor patterns: {patterns}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
