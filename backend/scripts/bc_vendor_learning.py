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
        if (n >= 5 and cnt / n >= 0.9) or (n >= 3 and cnt == n):
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
    # align_conflicting: other alias rows with the same normalized name that
    # point at a different vendor lose to BC evidence (MRP Solutions: a
    # bc_ground_truth row said MOL from 19 exact pairs, an older
    # auto_confirm row said WEA, and lookups picked the older one).
    aligned = 0
    for key, vno in learned.items():
        async for other in db.vendor_aliases.find({"normalized_alias": key, "vendor_no": {"$ne": vno}, "source": {"$ne": "bc_ground_truth"}}):
            aligned += 1
            print(f"  ALIGN {other.get('alias_string')!r} ({other.get('source')}): {other.get('vendor_no')} -> {vno}")
            if APPLY:
                await db.vendor_aliases_fix_backup.insert_one({k: v for k, v in other.items() if k != "_id"} | {"orig_id": other["_id"], "backed_up_at": now, "reason": "bc_ground_truth_align"})
                await db.vendor_aliases.update_one({"_id": other["_id"]}, {"$set": {"vendor_no": vno, "canonical_vendor_id": vno, "vendor_name": names.get(vno), "aligned_to_bc_at": now}})
    print(f"conflicting alias rows aligned to BC: {aligned}")
    # align_sender: sender-email mappings checked against the BC vendor of the
    # invoices each sender sent. >=3 linked invoices and >=90% one vendor ->
    # that vendor (o-i.com had no vendor, BC: OWENS 118/118); >=3 vendors and
    # none above 60% -> a shared platform sender (QuickBooks notifications
    # mapped to LSIDIST, BC: Child, Bullanfair, ...) is disabled.
    by_sender = collections.defaultdict(collections.Counter)
    async for d in db.hub_documents.find({"bc_link.bc_vendor_no": {"$exists": True}, "email_sender": {"$nin": [None, ""]}},
                                         {"_id": 0, "email_sender": 1, "bc_link.bc_vendor_no": 1}):
        by_sender[str(d["email_sender"]).strip().lower()][d["bc_link"]["bc_vendor_no"]] += 1
    s_fixed = s_generic = 0
    async for row in db.sender_vendor_map.find({"sender_email": {"$exists": True}}):
        c = by_sender.get(str(row["sender_email"]).lower())
        if not c or sum(c.values()) < 3:
            continue
        top, n = c.most_common(1)[0]; tot = sum(c.values())
        if n / tot >= 0.9 and (row.get("vendor_canonical") != top or row.get("generic_sender")):
            s_fixed += 1
            print(f"  SENDER {row['sender_email']}: {row.get('vendor_canonical')} -> {top} ({n}/{tot})")
            if APPLY:
                await db.sender_vendor_map.update_one({"_id": row["_id"]}, {"$set": {
                    "vendor_canonical": top, "vendor_no": top, "vendor_name": names.get(top) or row.get("vendor_name"),
                    "vendor_canonical_before_bc": row.get("vendor_canonical"), "aligned_to_bc_at": now,
                    "bc_evidence": dict(c), "generic_sender": False}})
        elif len(c) >= 3 and n / tot < 0.6 and row.get("vendor_canonical"):
            s_generic += 1
            print(f"  GENERIC SENDER {row['sender_email']}: {row.get('vendor_canonical')} disabled, BC {dict(c.most_common(4))}")
            if APPLY:
                await db.sender_vendor_map.update_one({"_id": row["_id"]}, {"$set": {
                    "vendor_canonical": None, "vendor_canonical_before_bc": row.get("vendor_canonical"),
                    "generic_sender": True, "aligned_to_bc_at": now, "bc_evidence": dict(c)}})
                dom = str(row["sender_email"]).split("@")[-1]
                await db.sender_vendor_map.update_many({"sender_domain": dom, "sender_email": {"$exists": False}}, {"$set": {
                    "vendor_canonical": None, "generic_sender": True, "aligned_to_bc_at": now}})
    print(f"sender mappings aligned to BC: {s_fixed}, shared senders disabled: {s_generic}")
    print(("APPLIED" if APPLY else "DRY RUN") + f": learned {len(learned)}, aliases created/updated {alias_new}, documents corrected {docs_fixed}")
    for k, v in per.most_common(20): print("  ", v, k)
asyncio.run(m())
