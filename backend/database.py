"""
MongoDB (Motor) client singleton and ``db`` handle.

Authoritative home for what ``server.py`` previously declared at
lines 176–178. Landed in Phase 3 Step 4d.2b (2026-04-23).

The :data:`client` Motor client is the single connection-pool owner for
the entire backend. ``server.py`` retains ``client`` and ``db`` as
re-exports (``from database import db, client``) so existing external
importers and in-module shutdown hooks continue to function.
"""
import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Defensive: ensure .env is loaded regardless of import order. Idempotent —
# repeat calls from server.py and elsewhere have no additional effect.
load_dotenv()

client = AsyncIOMotorClient(os.environ['MONGO_URL'])
db = client[os.environ['DB_NAME']]
