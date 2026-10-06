"""Vendor lane profiles learned from staff Square9 filings.

Each staff filing in a lane folder (Dropship / Warehouse, International /
Not International), live or from the recycle bin (deletedFromLocation),
is recorded once in vendor_lane_filings keyed by the Square9 item. The
per-vendor profile in vendor_lane_profiles (n, intl_share,
warehouse_share) is what routing reads: a vendor filed one way 95%+ of the
time (5+ filings) overrides the extraction's international flag and the
order-prefix warehouse guess. On 2,077 staff filings (45 days, leave-one-
out) this raised top-folder agreement from 67.8% to 71.4%: extraction
flagged US carriers and US branches of foreign vendors as international
(Quarterback, Anchor, Swift, Massilly, Triumbar), and freight carriers on
W-orders are filed under Dropship/Freight.

Fed hourly by the learning cycle from the 72-hour parity CSV.
"""
import csv
from datetime import datetime, timezone
from typing import Any, Dict

LANES = {"dropship international", "dropship not international", "warehouse international", "warehouse not international"}
FULL_MATCH = {"exact_match", "strong_evidence_match", "likely_match", "possible_match"}


def _root(p: str) -> str:
    p = (p or "").strip("/")
    if p.lower().startswith("temp folder/"):
        p = p[12:]
    return p.split("/")[0].lower()


async def learn_from_csv(db, path: str) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    added = 0
    try:
        rows = list(csv.DictReader(open(path)))
    except FileNotFoundError:
        return {"error": f"missing {path}"}
    for r in rows:
        bucket = r.get("match_bucket")
        ok = bucket in FULL_MATCH or (bucket == "recently_deleted_match" and float(r.get("match_score") or 0) >= 1.0)
        lane = _root(r.get("square9_parent_path"))
        if lane.startswith("s&h"):
            lane = "s&h"  # waiting / approved are stages of one destination
        if not ok or (lane not in LANES and lane != "s&h") or not r.get("hub_doc_id"):
            continue
        hub = await db.hub_documents.find_one({"id": r["hub_doc_id"]}, {"_id": 0, "vendor_canonical": 1})
        vendor = str((hub or {}).get("vendor_canonical") or "").upper()
        if not vendor:
            continue
        key = f"{r.get('square9_parent_path', '')}/{r.get('square9_name', '')}"
        res = await db.vendor_lane_filings.update_one(
            {"_id": key},
            {"$set": {"vendor": vendor, "lane": lane, "hub_doc_id": r["hub_doc_id"], "updated_at": now},
             "$setOnInsert": {"created_at": now}},
            upsert=True)
        added += 1 if res.upserted_id is not None else 0
    profiles = await rebuild_profiles(db)
    return {"filings_added": added, "vendors_profiled": profiles}


async def rebuild_profiles(db) -> int:
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    async for g in db.vendor_lane_filings.aggregate([
            {"$group": {"_id": "$vendor", "n_all": {"$sum": 1},
                        "sh": {"$sum": {"$cond": [{"$eq": ["$lane", "s&h"]}, 1, 0]}},
                        "n": {"$sum": {"$cond": [{"$eq": ["$lane", "s&h"]}, 0, 1]}},
                        "intl": {"$sum": {"$cond": [{"$in": ["$lane", ["dropship international", "warehouse international"]]}, 1, 0]}},
                        "wh": {"$sum": {"$cond": [{"$in": ["$lane", ["warehouse international", "warehouse not international"]]}, 1, 0]}}}}]):
        await db.vendor_lane_profiles.update_one(
            {"vendor": g["_id"]},
            {"$set": {"vendor": g["_id"], "n": g["n"],
                      "intl_share": round(g["intl"] / g["n"], 4) if g["n"] else 0.5,
                      "warehouse_share": round(g["wh"] / g["n"], 4) if g["n"] else 0.5,
                      "n_all": g["n_all"], "sh_share": round(g["sh"] / g["n_all"], 4), "updated_at": now}},
            upsert=True)
        n += 1
    return n


async def rebuild_order_lanes(db) -> Dict[str, Any]:
    """order -> {hub doc id: lane} from documents whose BC invoice lines carry
    a location code (bc_link.bc_location_lane). Routing votes with the other
    documents of the same order (a freight bill follows its product invoice:
    staff agreed 253 of 270 freight and 321 of 327 product filings)."""
    from services.folder_routing_service import _order_numbers_of
    lanes: Dict[str, Dict[str, str]] = {}
    async for d in db.hub_documents.find(
            {"bc_link.bc_location_lane": {"$in": ["warehouse", "dropship"]}},
            {"_id": 0, "id": 1, "bc_link": 1, "po_number_clean": 1, "po_number_extracted": 1, "extracted_fields": 1}):
        for o in _order_numbers_of(d, {}, {}):
            lanes.setdefault(o, {})[d["id"]] = d["bc_link"]["bc_location_lane"]
    now = datetime.now(timezone.utc).isoformat()
    for o, docs in lanes.items():
        await db.order_lanes.update_one({"order": o}, {"$set": {"docs": docs, "updated_at": now}}, upsert=True)
    await db.order_lanes.create_index("order", unique=True)
    return {"orders": len(lanes)}


import re as _re

_EXCEPTION_SUB = _re.compile(r"hold|issue|missing|not posted|previous month|return|quality", _re.I)


def _path_parts(p: str):
    x = [t.strip() for t in (p or "").strip("/").split("/") if t.strip()]
    if x and x[0].lower().startswith("temp folder"):
        x = x[1:]
    return x


def _clean_subpath(parts) -> str:
    """Levels 2-3 of a staff folder, stopping at workflow exceptions (holds,
    issues, quality, returns): those are states the Hub models separately."""
    out = []
    for t in parts[1:3]:
        if _EXCEPTION_SUB.search(t):
            break
        out.append(t)
    return "/".join(out)


async def learn_folders_from_csv(db, path: str) -> Dict[str, Any]:
    """Every staff filing's folder (any top folder), per vendor: where in the
    real Square9 tree staff put this vendor's documents."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        rows = list(csv.DictReader(open(path)))
    except FileNotFoundError:
        return {"error": f"missing {path}"}
    n = 0
    for r in rows:
        bucket = r.get("match_bucket")
        ok = bucket in FULL_MATCH or (bucket == "recently_deleted_match" and float(r.get("match_score") or 0) >= 1.0)
        parts = _path_parts(r.get("square9_parent_path"))
        if not ok or not parts or not r.get("hub_doc_id"):
            continue
        hub = await db.hub_documents.find_one({"id": r["hub_doc_id"]}, {"_id": 0, "vendor_canonical": 1, "created_utc": 1})
        key = f"{r.get('square9_parent_path', '')}/{r.get('square9_name', '')}"
        await db.folder_filings.update_one({"_id": key}, {"$set": {
            "filed_at": (hub or {}).get("created_utc"),
            "vendor": str((hub or {}).get("vendor_canonical") or "").upper(), "top": parts[0],
            "top_l": parts[0].lower(), "subpath": _clean_subpath(parts), "hub_doc_id": r["hub_doc_id"],
            "updated_at": now}, "$setOnInsert": {"created_at": now}}, upsert=True)
        n += 1
    return {"filings": n, **(await rebuild_folder_profiles(db))}


FOLDER_HALF_LIFE_DAYS = 10.0


async def rebuild_folder_profiles(db) -> Dict[str, Any]:
    """Recency-weighted: staff reorganize (O-I / Anchor moved from "Drop Ship
    All Others" to "Drop Ship Dunnage Vendors" in mid-September 2026), so a
    filing's weight halves every FOLDER_HALF_LIFE_DAYS. Leave-one-out (past
    filings only): 75.6% -> 77.0% top + second level. counts are weights;
    n is the plain number of filings."""
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    vend, tops = {}, {}
    async for f in db.folder_filings.find({}, {"_id": 0, "vendor": 1, "top": 1, "top_l": 1, "subpath": 1, "filed_at": 1}):
        try:
            age = max(0.0, (now_dt - datetime.fromisoformat(str(f.get("filed_at"))[:19]).replace(tzinfo=timezone.utc)).days)
        except Exception:
            age = 30.0
        w = 0.5 ** (age / FOLDER_HALF_LIFE_DAYS)
        tops.setdefault(f["top_l"], {"top": f["top"], "counts": {}, "n": 0})
        tc = tops[f["top_l"]]["counts"]
        tc[f["subpath"]] = tc.get(f["subpath"], 0) + w
        tops[f["top_l"]]["n"] += 1
        if f.get("vendor"):
            k = (f["vendor"], f["top_l"])
            vend.setdefault(k, {"top": f["top"], "counts": {}, "n": 0})
            vc = vend[k]["counts"]
            vc[f["subpath"]] = vc.get(f["subpath"], 0) + w
            vend[k]["n"] += 1
    for (v, tl), x in vend.items():
        await db.vendor_subfolder_profiles.update_one({"vendor": v, "top_l": tl}, {"$set": {
            "vendor": v, "top_l": tl, "top": x["top"], "counts": x["counts"], "n": x["n"], "updated_at": now}}, upsert=True)
    for tl, x in tops.items():
        await db.top_subfolder_defaults.update_one({"top_l": tl}, {"$set": {
            "top_l": tl, "top": x["top"], "counts": x["counts"], "updated_at": now}}, upsert=True)
    return {"vendor_profiles": len(vend), "top_folders": len(tops)}
