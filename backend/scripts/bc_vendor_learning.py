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
    # canonicalize_names: documents whose vendor_canonical is a vendor NAME
    # rather than a BC vendor number ("CITICARGO & STORAGE" 942 documents,
    # "Ball Metal Beverage Container Corp." 2,538, "Valley Distributing and
    # Storage Company") split one vendor's history in two. Resolve each name
    # to one BC number: exact BC name, a BC name inside it ("Citi-Cargo",
    # "Brown Warehouse"), an alias row, or BC links (3+, 90%). Gamer's own
    # names are never mapped. The resolution is saved as an alias.
    def _nm(x): return re.sub(r"[^a-z0-9]", "", str(x or "").lower())
    _SUFFIX = re.compile(r"(incorporated|inc|llc|ltd|corporation|corp|company|co|lp|usa)+$")
    def _stem(x):
        n = _nm(x)
        prev = None
        while prev != n:
            prev, n = n, _SUFFIX.sub("", n)
        return n
    # Every BC vendor number is a valid identity (blocked vendors included);
    # only new resolutions are restricted to active vendors.
    all_bc_nums = set(await db.bc_catalog_vendors.distinct("vendor_no"))
    bc_nums, bc_byname, bc_bystem, bc_name_of = set(), collections.defaultdict(set), [], {}
    async for v in db.bc_catalog_vendors.find({"blocked": {"$ne": True}}, {"_id": 0, "vendor_no": 1, "name": 1}):
        bc_nums.add(v["vendor_no"]); bc_byname[_nm(v["name"])].add(v["vendor_no"]); bc_name_of[v["vendor_no"]] = v["name"]
        if len(_stem(v["name"])) >= 7:
            bc_bystem.append((_stem(v["name"]), v["vendor_no"]))
    alias_map, gt_alias = collections.defaultdict(set), collections.defaultdict(set)
    async for a in db.vendor_aliases.find({}, {"_id": 0, "alias_string": 1, "normalized_alias": 1, "vendor_no": 1, "canonical_vendor_id": 1, "source": 1}):
        vn = a.get("vendor_no") or a.get("canonical_vendor_id")
        if vn in bc_nums:
            alias_map[_nm(a.get("alias_string") or a.get("normalized_alias"))].add(vn)
            if a.get("source") == "bc_ground_truth":
                gt_alias[_nm(a.get("alias_string") or a.get("normalized_alias"))].add(vn)
    names = collections.Counter()
    async for d in db.hub_documents.find({"vendor_canonical": {"$nin": [None, ""]}}, {"_id": 0, "vendor_canonical": 1}):
        if d["vendor_canonical"] not in all_bc_nums:
            names[d["vendor_canonical"]] += 1
    # Documents with no vendor at all but an extracted raw name (Berry
    # subsidiaries "BPRex Closures, LLC", "Setco, LLC" via CertCapture: 142
    # AP documents since 2026-08-20) resolve by the same rules.
    raw_unresolved = collections.Counter()
    async for d in db.hub_documents.find({"vendor_canonical": {"$in": [None, ""]}, "vendor_raw": {"$nin": [None, ""]}},
                                         {"_id": 0, "vendor_raw": 1}):
        raw_unresolved[str(d["vendor_raw"]).strip()] += 1
    c_names = c_docs = 0
    work = [(nm_, n_, "vendor_canonical") for nm_, n_ in names.most_common()] +            [(nm_, n_, "vendor_raw") for nm_, n_ in raw_unresolved.most_common()]
    for name, n, field in work:
        lookup_name = re.sub(r"^(?:beneficiary|vendor|supplier|remit to|from)\s*:\s*", "", name, flags=re.I).strip()
        if "gamer" in name.lower() or "test vendor" in name.lower() or len(_nm(name)) < 4:
            continue
        to, how = None, None
        ev = collections.Counter()
        async for d in db.hub_documents.find({"$or": [{"vendor_canonical": name}, {"vendor_raw": name}],
                                              "bc_link.match": {"$in": ["number+amount", "filename+vendor"]}},
                                             {"_id": 0, "bc_link.bc_vendor_no": 1}):
            ev[d["bc_link"]["bc_vendor_no"]] += 1
        top, k = ev.most_common(1)[0] if ev else (None, 0)
        # Only a BC name contained in ours ("CITICARGO & STORAGE" has
        # "Citi-Cargo"); the reverse ("Berry Global" inside BC "Berry Global
        # (ZEL)") picked ZEL where BC books Berry Global as BERRY.
        stem_hits = {vn for st, vn in bc_bystem if _stem(name).startswith(st)}
        words = {w for w in re.findall(r"[a-z]{4,}", name.lower())} - {"company", "corp", "corporation", "inc", "llc", "services", "service", "international", "united", "states"}
        alias_hits = {vn for vn in alias_map.get(_nm(name), ())
                      if words & set(re.findall(r"[a-z]{4,}", str(bc_name_of.get(vn, "")).lower()))}
        if len(bc_byname.get(_nm(name), ())) == 1:
            to, how = next(iter(bc_byname[_nm(name)])), "bc_name"
        elif k >= 3 and k / sum(ev.values()) >= 0.9:
            to, how = top, "bc_evidence"
        elif len(gt_alias.get(_nm(name), ())) == 1:
            to, how = next(iter(gt_alias[_nm(name)])), "bc_ground_truth_alias"
        elif len(stem_hits) == 1:
            to, how = stem_hits.pop(), "bc_name_stem"
        elif len(alias_hits) == 1:
            to, how = alias_hits.pop(), "alias"
        if not to:
            continue
        c_names += 1; c_docs += n
        print(f"  CANON {'raw ' if field == 'vendor_raw' else ''}{name!r} -> {to} ({how}, {n} docs)")
        if APPLY:
            sel = {"vendor_canonical": name} if field == "vendor_canonical" else                 {"vendor_canonical": {"$in": [None, ""]}, "vendor_raw": name}
            async for d in db.hub_documents.find(sel, {"_id": 1}):
                await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {"vendor_canonical": to, "vendor_canonical_backfill": {
                    "at": now, "previous": name, "from": "bc_name_canonical", "how": how}}})
            ex_alias = await db.vendor_aliases.find_one({"alias_string": name}, {"_id": 0, "vendor_no": 1, "canonical_vendor_id": 1})
            if ex_alias and (ex_alias.get("vendor_no") or ex_alias.get("canonical_vendor_id")) in all_bc_nums - {to}:
                print(f"    alias {name!r} already points at {ex_alias.get('vendor_no') or ex_alias.get('canonical_vendor_id')}; left as is")
                continue
            await db.vendor_aliases.update_one({"alias_string": name}, {"$set": {
                "alias_string": name, "alias": name.upper(), "normalized_alias": normalize_vendor_name(name),
                "vendor_no": to, "canonical_vendor_id": to, "vendor_name": bc_name_of.get(to), "source": "bc_name_canonical",
                "learned_at": now}, "$setOnInsert": {"alias_id": str(uuid.uuid4()), "created_at": now}}, upsert=True)
    print(f"vendor names canonicalized to BC numbers: {c_names} names, {c_docs} documents")
    # repair_aliases: alias rows whose target is not a BC vendor number
    # ("R & L", "C&MFORW", or a PO number like "112522") resolve new
    # documents to non-vendors. Repoint to the one BC vendor whose name
    # matches (exact or BC name inside it); otherwise quarantine the row.
    rep = quar = 0
    async for a in db.vendor_aliases.find({}):
        tgt = a.get("vendor_no") or a.get("canonical_vendor_id")
        if tgt in all_bc_nums:
            continue
        nm_ = a.get("alias_string") or a.get("normalized_alias") or ""
        hits = set(bc_byname.get(_nm(nm_), ())) or {vn for st, vn in bc_bystem if _stem(nm_).startswith(st)}
        if "gamer" not in nm_.lower() and len(hits) == 1:
            to = hits.pop(); rep += 1
            print(f"  ALIAS REPOINT {nm_!r}: {tgt} -> {to}")
            if APPLY:
                await db.vendor_aliases_fix_backup.insert_one({k: v for k, v in a.items() if k != "_id"} | {"orig_id": a["_id"], "backed_up_at": now, "reason": "target_not_bc_vendor"})
                await db.vendor_aliases.update_one({"_id": a["_id"]}, {"$set": {"vendor_no": to, "canonical_vendor_id": to, "vendor_name": bc_name_of.get(to), "aligned_to_bc_at": now}})
        else:
            quar += 1
            print(f"  ALIAS QUARANTINE {nm_!r} -> {tgt} (no single BC vendor)")
            if APPLY:
                await db.vendor_aliases_quarantine.insert_one({k: v for k, v in a.items() if k != "_id"} | {"orig_id": a["_id"], "quarantined_at": now, "reason": "target_not_bc_vendor"})
                await db.vendor_aliases.delete_one({"_id": a["_id"]})
    print(f"aliases with a non-BC target: repointed {rep}, quarantined {quar}")
    # learn_senders: a sender with no mapping whose BC-linked invoices are
    # 90%+ one vendor (3+) gets that vendor (bc_ground_truth). Gamer's own
    # domain never maps (internal forwards).
    # Billing platforms send for many vendors: never learned as one vendor.
    PLATFORM = re.compile(r"bill[.]com|intuit|quickbooks|quotefactory|accountservicing|avalara|certcapture|docusign|paypal|stripe|coupa|ariba|tungsten|sap[.]com|billtrust|invoicecloud", re.I)
    mapped = {str(r.get("sender_email") or "").lower() async for r in db.sender_vendor_map.find({"sender_email": {"$exists": True}}, {"sender_email": 1})}
    new_senders = 0
    for snd, c in by_sender.items():
        if snd in mapped or not snd or "gamerpackaging" in snd or sum(c.values()) < 3 or PLATFORM.search(snd):
            continue
        top, k = c.most_common(1)[0]
        if k / sum(c.values()) < 0.9 or top not in all_bc_nums:
            continue
        new_senders += 1
        print(f"  NEW SENDER {snd} -> {top} ({k}/{sum(c.values())})")
        if APPLY:
            await db.sender_vendor_map.update_one({"sender_email": snd}, {"$set": {
                "sender_email": snd, "sender_domain": snd.split("@")[-1], "vendor_canonical": top, "vendor_no": top,
                "vendor_name": bc_name_of.get(top) or names.get(top), "source": "bc_ground_truth", "bc_evidence": dict(c),
                "confirmation_count": k, "created_at": now, "updated_at": now}}, upsert=True)
    print(f"sender mappings learned from BC: {new_senders}")
    # fill_from_sender: documents with no vendor or a label for a vendor
    # ("ACCOUNT NO.", "Signature", "Consignee):", "19 CFR 142.3 ...") take
    # their sender's mapped vendor; "Beneficiary: X" is resolved as X.
    JUNK = re.compile(r"^(?:account|signature|consignee|shipper|bill to|ship to|remit|invoice|page|date|total|\d|19 cfr|hbl|mbl)", re.I)
    smap = {}
    async for r in db.sender_vendor_map.find({"sender_email": {"$exists": True}, "vendor_canonical": {"$nin": [None, ""]},
                                              "generic_sender": {"$ne": True}},
                                             {"_id": 0, "sender_email": 1, "vendor_canonical": 1, "source": 1, "bc_evidence": 1, "aligned_to_bc_at": 1}):
        # Only BC-confirmed mappings fill a missing vendor (old unconfirmed
        # rows mapped buske.com -> CROWN C, a customer -> BALLCOR).
        ev = r.get("bc_evidence") or {}
        confirmed = r.get("source") == "bc_ground_truth" or r.get("aligned_to_bc_at") or (
            sum(ev.values()) >= 3 and ev.get(r["vendor_canonical"], 0) / max(sum(ev.values()), 1) >= 0.9)
        if r["vendor_canonical"] in all_bc_nums and confirmed:
            smap[str(r["sender_email"]).lower()] = r["vendor_canonical"]
    filled = collections.Counter()
    async for d in db.hub_documents.find({"email_sender": {"$nin": [None, ""]}, "$or": [
            {"vendor_canonical": {"$in": [None, ""]}}, {"vendor_canonical": {"$regex": JUNK.pattern, "$options": "i"}}]},
            {"_id": 1, "email_sender": 1, "vendor_canonical": 1}):
        if d.get("vendor_canonical") in all_bc_nums:
            continue
        to = smap.get(str(d["email_sender"]).lower())
        if not to:
            continue
        filled[(str(d["email_sender"]).lower()[:40], to)] += 1
        if APPLY:
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {"vendor_canonical": to, "vendor_canonical_backfill": {
                "at": now, "previous": d.get("vendor_canonical"), "from": "bc_sender_fill"}}})
    for k, v in filled.most_common(10):
        print(f"  FILL {k[0]} -> {k[1]}: {v}")
    print(f"documents given their sender's vendor: {sum(filled.values())}")
    print(("APPLIED" if APPLY else "DRY RUN") + f": learned {len(learned)}, aliases created/updated {alias_new}, documents corrected {docs_fixed}")
    for k, v in per.most_common(20): print("  ", v, k)
asyncio.run(m())
