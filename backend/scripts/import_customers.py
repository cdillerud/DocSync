#!/usr/bin/env python3
"""
Import customer list from CSV into MongoDB for document classification.
"""

import csv
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone
import os
import re

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "gpi_document_hub")

async def import_customers(csv_path: str):
    """Import customers from CSV file."""
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    collection = db["customers"]
    
    # Clear existing customers
    await collection.delete_many({})
    
    customers = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get('Customer', '').strip()
            if not name:
                continue
            
            # Create searchable variations of the name
            name_lower = name.lower()
            # Remove common suffixes for matching
            name_normalized = re.sub(r'\s*(inc\.?|llc|corp\.?|co\.?|ltd\.?|company|brewing|brewery|beverage|brands?|\*\*.*\*\*)$', '', name_lower, flags=re.IGNORECASE).strip()
            
            customers.append({
                "name": name,
                "name_lower": name_lower,
                "name_normalized": name_normalized,
                "customer_number": row.get('Customer Number', '').strip(),
                "city": row.get('City', '').strip(),
                "state": row.get('State', '').strip(),
                "country": row.get('Country', '').strip(),
                "zip": row.get('Zip', '').strip(),
                "created_utc": datetime.now(timezone.utc).isoformat()
            })
    
    if customers:
        await collection.insert_many(customers)
        # Create indexes for fast searching
        await collection.create_index("name_lower")
        await collection.create_index("name_normalized")
        await collection.create_index("customer_number")
    
    print(f"Imported {len(customers)} customers")
    return len(customers)

if __name__ == "__main__":
    import sys
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "/app/data/Customers-Grid-view.csv"
    asyncio.run(import_customers(csv_path))
