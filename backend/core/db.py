"""
Shared MongoDB connection.

Extracted verbatim from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md). No behavior change: same MONGO_URL/DB_NAME env vars,
same client construction. server.py and every routes/*.py module import
`db` from here instead of each holding its own reference.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
