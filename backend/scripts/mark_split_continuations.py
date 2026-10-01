"""Mark existing split continuation pieces (see batch_po_splitter.mark_split_continuations).

Dry run unless --apply. Usage (inside gpi-backend):
    PYTHONPATH=/app python scripts/mark_split_continuations.py services/batch_po_splitter.py [--apply]
"""
import asyncio, os, sys, importlib.util, logging, collections
logging.disable(logging.CRITICAL)
from motor.motor_asyncio import AsyncIOMotorClient

APPLY = "--apply" in sys.argv
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
spec = importlib.util.spec_from_file_location("bps", sys.argv[1])
bps = importlib.util.module_from_spec(spec)
sys.modules["bps"] = bps
spec.loader.exec_module(bps)


async def main():
    children = collections.defaultdict(list)
    async for d in db.hub_documents.find(
            {"batch_parent_id": {"$exists": True, "$ne": None}, "created_utc": {"$gte": "2026-06-01"}},
            {"_id": 0, "id": 1, "batch_parent_id": 1}):
        children[d["batch_parent_id"]].append(d["id"])
    total = parents_hit = 0
    for pid, ids in children.items():
        n = await bps.mark_split_continuations(db, ids, apply=APPLY)
        if n:
            parents_hit += 1
            total += n
    print(("APPLIED" if APPLY else "DRY RUN") + f": batch files {len(children)}, with continuations {parents_hit}, pieces marked {total}")


asyncio.run(main())
