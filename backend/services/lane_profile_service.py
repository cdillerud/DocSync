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
