"""
Learn vendor identity from Business Central (ground truth).

For Hub documents whose invoice number AND amount match a BC purchase
invoice (draft or posted, last 90 days), BC's vendor number is the truth
for the raw vendor name the Hub extracted. A raw name that maps to one BC
vendor in at least 90% of 5+ exact pairings becomes a vendor alias
(source bc_ground_truth) and Hub documents with that raw name get that
vendor_canonical (previous value kept in vendor_canonical_backfill).
Never learns Gamer's own name. First run 2026-10-05: 86 mappings, 2,737
documents corrected (CANPACK->CANPUSA 739, unresolved O-I->OWENS 379,
R & L->RLCARR 185, ...).

Dry run unless --apply. Usage (inside gpi-backend):
    PYTHONPATH=/app python scripts/bc_vendor_learning.py [--apply]
"""
import asyncio, os, re, sys, collections, uuid
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
from services.vendor_name_helpers import normalize_vendor_name
APPLY = "--apply" in sys.argv
LABEL_WORDS = re.compile(r"\b(invoice|facture|statement|remit|bill to|page)\b")
from datetime import timedelta
SINCE = (datetime.now(timezone.utc) - timedelta(days=90)).date().isoformat()
def norm(x): return re.sub(r"[^A-Z0-9]", "", str(x or "").upper()).lstrip("0")
async def m():
    bc = {}
    for t in ("posted_purchase_invoice", "draft_purchase_invoice"):
        async for d in db.bc_reference_cache.find({"bc_entity_type": t, "bc_posting_date": {"$gte": SINCE}}, {"_id": 0}):
            k = norm(d.get("bc_external_document_no"))
            if len(k) >= 5: bc.setdefault(k, d)
    maps = collections.defaultdict(collections.Counter); names = {}; raws = collections.defaultdict(set)
    async for h in db.hub_documents.find({"created_utc": {"$gte": SINCE}, "is_duplicate": {"$ne": True}},
                                         {"_id": 0, "invoice_number_clean": 1, "amount_float": 1, "vendor_raw": 1, "extracted_fields.vendor": 1}):
        b = bc.get(norm(h.get("invoice_number_clean")))
        if not b or h.get("amount_float") is None or b.get("bc_amount") is None: continue
        if abs(abs(h["amount_float"]) - abs(b["bc_amount"])) >= 0.02: continue
        raw = h.get("vendor_raw") or (h.get("extracted_fields") or {}).get("vendor")
        if not raw: continue
        key = normalize_vendor_name(str(raw))
        if "gamer" in key: continue  # our own name is never a vendor alias
        if LABEL_WORDS.search(key): continue  # "INVOICE - FACTURE" is a label, not a vendor
        maps[key][b["bc_vendor_no"]] += 1; names[b["bc_vendor_no"]] = b.get("bc_vendor_name"); raws[key].add(str(raw))
    learned = {}
    for key, c in maps.items():
        n = sum(c.values()); top, cnt = c.most_common(1)[0]
        if n >= 5 and cnt / n >= 0.9:
            learned[key] = top
    now = datetime.now(timezone.utc).isoformat()
    alias_new = docs_fixed = 0; per = collections.Counter()
    for key, vno in learned.items():
        ex = await db.vendor_aliases.find_one({"$or": [{"normalized_alias": key}, {"alias_string": {"$in": sorted(raws[key])}}]})
        if not ex or str(ex.get("vendor_no")).upper() != vno.upper():
            alias_new += 1
            if APPLY:
                if ex:
                    await db.vendor_aliases_fix_backup.insert_one({k: v for k, v in ex.items() if k != "_id"} | {"orig_id": ex["_id"], "backed_up_at": now, "reason": "bc_ground_truth"})
                await db.vendor_aliases.update_one({"_id": ex["_id"]} if ex else {"normalized_alias": key}, {"$set": {
                    **({} if ex else {"alias_string": sorted(raws[key])[0], "alias": sorted(raws[key])[0], "normalized_alias": key}),
                    "vendor_no": vno, "canonical_vendor_id": vno, "vendor_name": names.get(vno), "source": "bc_ground_truth",
                    "learned_at": now, "evidence_count": sum(maps[key].values())}, "$setOnInsert": {"alias_id": str(uuid.uuid4()), "created_at": now}}, upsert=True)
        async for d in db.hub_documents.find({"vendor_canonical": {"$ne": vno}, "$or": [{"vendor_raw": {"$in": sorted(raws[key])}}, {"extracted_fields.vendor": {"$in": sorted(raws[key])}}]}, {"_id": 1, "vendor_canonical": 1}):
            docs_fixed += 1; per[(d.get("vendor_canonical"), vno)] += 1
            if APPLY:
                await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {"vendor_canonical": vno, "vendor_canonical_backfill": {"at": now, "previous": d.get("vendor_canonical"), "from": "bc_ground_truth", "alias": key}}})
    print(("APPLIED" if APPLY else "DRY RUN") + f": learned {len(learned)}, aliases created/updated {alias_new}, documents corrected {docs_fixed}")
    for k, v in per.most_common(20): print("  ", v, k)
asyncio.run(m())
