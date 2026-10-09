"""Hourly: vendor aliases checked against the invoices AP entered in BC.

1. An alias row whose canonical_vendor_id disagrees with its own vendor_no
   (Comar: vendor_no COMAR, canonical OMEGAPA - lookups read the canonical)
   is made consistent when vendor_no is a BC vendor.
2. An alias learned automatically (not from BC) that BC contradicts - 2+
   BC-linked invoices carrying that vendor name all belong to one other BC
   vendor, none to the alias target ("Adroit North America" -> IPLNORA;
   AP entered ADROITN) - is pointed at that vendor. The old row is backed up.
BC-sourced aliases (bc_ground_truth, bc_name_canonical, bc_cache_seed) are
left to scripts/bc_vendor_learning.py.
3. A document the old gap closer resolved by fuzzy name ("Stephen Conroy" ->
   ARDAGHM because "Ardagh - ST" reduced to "st"; 97 documents 2026-04..10)
   is un-resolved when its own vendor name does not match any name of that
   vendor. Never touches a document linked to a BC invoice.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict

_BC_SOURCES = {"bc_ground_truth", "bc_name_canonical", "bc_cache_seed"}


async def check(db, apply: bool = True) -> Dict[str, Any]:
    from services.vendor_name_helpers import normalize_vendor_name
    now = datetime.now(timezone.utc).isoformat()
    bc_vendors = set(await db.bc_catalog_vendors.distinct("vendor_no", {"blocked": {"$ne": True}}))
    names = {v["vendor_no"]: v.get("name") async for v in db.bc_catalog_vendors.find({}, {"_id": 0, "vendor_no": 1, "name": 1})}
    out = {"made_consistent": [], "realigned": []}

    evidence = defaultdict(Counter)
    async for d in db.hub_documents.find({"bc_link.match": {"$in": ["number+amount", "number+vendor"]}, "bc_link.bc_vendor_no": {"$nin": [None, ""]}},
                                         {"_id": 0, "vendor_raw": 1, "extracted_fields.vendor": 1, "bc_link.bc_vendor_no": 1}):
        raw = d.get("vendor_raw") or (d.get("extracted_fields") or {}).get("vendor")
        if raw:
            evidence[normalize_vendor_name(raw)][d["bc_link"]["bc_vendor_no"]] += 1
    # 1. Self-contradicting rows: BC decides between the two (both may be real
    #    vendors: Berry Global ZEL vs BERRY, CanPack Olyphant vs CANPACK).
    async for a in db.vendor_aliases.find({"vendor_no": {"$in": list(bc_vendors)}}, {"_id": 1, "alias_string": 1, "normalized_alias": 1, "vendor_no": 1, "canonical_vendor_id": 1}):
        c, v = a.get("canonical_vendor_id"), a["vendor_no"]
        if not c or c == v:
            continue
        ev = evidence.get(a.get("normalized_alias") or normalize_vendor_name(a.get("alias_string") or "")) or Counter()
        win = v if ev.get(v, 0) >= 2 and not ev.get(c) else (c if ev.get(c, 0) >= 2 and not ev.get(v) and c in bc_vendors else None)
        if not win:
            continue
        out["made_consistent"].append((a.get("alias_string"), c, v, win))
        if apply:
            await db.vendor_aliases.update_one({"_id": a["_id"]}, {"$set": {"canonical_vendor_id": win, "vendor_no": win, "made_consistent_at": now}})

    async for a in db.vendor_aliases.find({"source": {"$nin": list(_BC_SOURCES)}}, {"_id": 0}):
        key = a.get("normalized_alias") or normalize_vendor_name(a.get("alias_string") or "")
        ev = evidence.get(key)
        target = a.get("canonical_vendor_id") or a.get("vendor_no")
        if not ev or ev.get(target):
            continue
        (to, n), = ev.most_common(1)
        if n >= 3 and len(ev) == 1 and to in bc_vendors and to != target:
            out["realigned"].append((a.get("alias_string"), target, to, n))
            if apply:
                await db.vendor_aliases_fix_backup.insert_one({**a, "backed_up_at": now, "reason": "bc_contradicts_learned_alias"})
                await db.vendor_aliases.update_many({"alias_string": a.get("alias_string"), "source": a.get("source")}, {"$set": {
                    "vendor_no": to, "canonical_vendor_id": to, "vendor_name": names.get(to), "aligned_to_bc_at": now,
                    "aligned_evidence": n}})
    undone = await undo_bad_gap_closer(db, apply=apply)
    return {"made_consistent": len(out["made_consistent"]), "realigned": len(out["realigned"]),
            "gap_closer_undone": len(undone),
            "examples": (out["made_consistent"][:5], out["realigned"][:8], undone[:8])}


_GENERIC = {"inc", "llc", "corp", "company", "group", "services", "service", "international", "packaging",
            "solutions", "the", "and", "global", "usa", "america", "logistics", "warehouse", "plastics", "from",
            "email", "based", "metal", "glass", "transportation", "trucking", "products", "limited", "shipping"}


def _words(name: str) -> set:
    s = str(name or "").lower().replace("o-i", "oi")
    return {w for w in re.findall(r"[a-z]{2,}", s) if w not in _GENERIC and (len(w) >= 4 or w == "oi")}


async def undo_bad_gap_closer(db, apply: bool = True, threshold: float = 0.72):
    from services.vendor_name_helpers import calculate_fuzzy_score
    names = defaultdict(set)
    async for p in db.vendor_invoice_profiles.find({"vendor_no": {"$nin": [None, ""]}},
                                                   {"_id": 0, "vendor_no": 1, "vendor_name": 1, "vendor_name_variants": 1, "vendor_card.displayName": 1}):
        for n in (p.get("vendor_name"), (p.get("vendor_card") or {}).get("displayName"), *(p.get("vendor_name_variants") or [])):
            if n:
                names[p["vendor_no"]].add(n)
    async for v in db.bc_catalog_vendors.find({}, {"_id": 0, "vendor_no": 1, "name": 1}):
        if v.get("name"):
            names[v["vendor_no"]].add(v["name"])
    async for a in db.vendor_aliases.find({"source": {"$in": list(_BC_SOURCES) + ["manual", "manual_resolution"]}},
                                          {"_id": 0, "vendor_no": 1, "alias_string": 1}):
        if a.get("vendor_no") and a.get("alias_string"):
            names[a["vendor_no"]].add(a["alias_string"])
    now = datetime.now(timezone.utc).isoformat()
    undone = []
    async for d in db.hub_documents.find({"vendor_resolution.source": "auto_gap_closer", "bc_link": {"$exists": False},
                                          "vendor_canonical": {"$nin": [None, ""]}},
                                         {"_id": 1, "id": 1, "vendor_raw": 1, "extracted_fields.vendor": 1, "vendor_canonical": 1,
                                          "vendor_no": 1, "bc_vendor_number": 1, "vendor_resolution": 1}):
        raw = d.get("vendor_raw") or (d.get("extracted_fields") or {}).get("vendor")
        v = d["vendor_canonical"]
        if not raw or not names.get(v):
            continue
        best = max(calculate_fuzzy_score(raw, n) for n in names[v])
        if best >= threshold:
            continue
        # A shared distinctive word, or the vendor code's start, keeps it
        # ("Ward Trucking, LLC" is WARDTR, BC name "Forward Brokerage";
        # "O-I (from warehouse.bog@o-i.com)" is OWENS, whose names say OI).
        own = _words(raw)
        if own & set().union(*(_words(n) for n in names[v])) or any(v.lower().startswith(w) for w in own if len(w) >= 4):
            continue
        undone.append((raw, v, round(best, 2)))
        if apply:
            await db.hub_documents.update_one({"_id": d["_id"]}, {
                "$set": {"vendor_gap_closer_undone": {"at": now, "vendor_canonical": v, "vendor_no": d.get("vendor_no"),
                                                      "bc_vendor_number": d.get("bc_vendor_number"),
                                                      "vendor_resolution": d.get("vendor_resolution"), "name_score": round(best, 2)},
                         "vendor_resolution.status": "unresolved"},
                "$unset": {"vendor_canonical": "", "vendor_no": "", "bc_vendor_number": ""}})
    return undone

