"""
Import OneGamer folder tree classifications into MongoDB.
This provides rule-based classification lookup for the hybrid approach.
"""

import asyncio
import csv
import os
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

# Load environment
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

load_env()

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'gpi_hub')


async def import_folder_tree(csv_path: str):
    """Import the folder tree CSV into MongoDB."""
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    collection = db.folder_classifications
    
    # Clear existing data
    await collection.delete_many({})
    
    # Read CSV
    records = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Clean up windows line endings from values
            cleaned_row = {k: v.strip().replace('\r', '') for k, v in row.items()}
            
            # Skip folders (we only care about files)
            if cleaned_row.get('IsFolder', '').lower() == 'true':
                continue
            
            # Build the record
            record = {
                "file_ref": cleaned_row.get('FileRef', ''),
                "relative_path": cleaned_row.get('RelativePath', ''),
                "file_name": cleaned_row.get('FileName', ''),
                "folder_path": cleaned_row.get('FolderPath', ''),
                "level1": cleaned_row.get('Level1', '') or None,
                "level2": cleaned_row.get('Level2', '') or None,
                "level3": cleaned_row.get('Level3', '') or None,
                "level4": cleaned_row.get('Level4', '') or None,
                "level5": cleaned_row.get('Level5', '') or None,
                "level6": cleaned_row.get('Level6', '') or None,
                "imported_utc": datetime.now(timezone.utc).isoformat()
            }
            records.append(record)
    
    # Batch insert
    if records:
        # Insert in batches of 1000
        batch_size = 1000
        total_inserted = 0
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            await collection.insert_many(batch)
            total_inserted += len(batch)
            print(f"Inserted {total_inserted}/{len(records)} records...")
    
    # Create indexes
    await collection.create_index("file_name")
    await collection.create_index("folder_path")
    await collection.create_index("relative_path")
    await collection.create_index("level1")
    await collection.create_index("level2")
    
    print(f"\nImport complete: {len(records)} file records imported")
    
    # Print summary
    level1_counts = {}
    for r in records:
        l1 = r.get('level1') or 'Unknown'
        level1_counts[l1] = level1_counts.get(l1, 0) + 1
    
    print("\nLevel1 (Department) distribution:")
    for l1, count in sorted(level1_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  {l1}: {count}")
    
    client.close()
    return len(records)


if __name__ == "__main__":
    csv_path = os.path.join(os.path.dirname(__file__), 'data', 'folder_tree.csv')
    
    if not os.path.exists(csv_path):
        print(f"CSV not found at {csv_path}")
        exit(1)
    
    count = asyncio.run(import_folder_tree(csv_path))
    print(f"\nDone! Imported {count} records.")
