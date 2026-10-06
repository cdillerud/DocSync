"""Daily replay of the Hub's current intake logic against ground truth.

Once a day (from the hourly learning cycle) the Hub re-runs what it would
decide today for documents whose answer is now known, so the learning has
a trend line rather than one-off measurements:

* routing: staff Square9 filings from the last 72 hours (parity CSV),
  routed with the BC link removed (what the Hub knows at intake); top
  folder agreement, S&H waiting/approved counted as one (a stage, not a
  routing decision).
* vendor: invoices AP entered in BC in the last 14 days (exact
  number+amount link); intake vendor resolution (sender map, then
  aliases) scored against the BC vendor number.

Stored in learning_metrics (one row per day), shown on the readiness page.
"""
import csv
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)

PARITY_CSV = "/app/prod_reports/parity_hourly.csv"
CAUGHT = {"exact_match", "strong_evidence_match", "likely_match", "possible_match"}


def _root(p: str) -> str:
    r = (p or "").strip("/")
    if r.lower().startswith("temp folder/"):
        r = r[12:]
    r = r.split("/")[0].lower()
    return "s&h" if r.startswith("s&h") else r


async def _routing_replay(db) -> Dict[str, Any]:
    from services.folder_routing_service import route_with_feedback
    if not os.path.exists(PARITY_CSV):
        return {"n": 0}
    seen, n, agree = set(), 0, 0
    for r in csv.DictReader(open(PARITY_CSV)):
        ok = r.get("match_bucket") in CAUGHT or (
            r.get("match_bucket") == "recently_deleted_match" and float(r.get("match_score") or 0) >= 1
            and r.get("square9_parent_path"))
        if not ok or not r.get("hub_doc_id") or r["hub_doc_id"] in seen:
            continue
        seen.add(r["hub_doc_id"])
        d = await db.hub_documents.find_one({"id": r["hub_doc_id"]}, {"_id": 0, "file_content_b64": 0})
        if not d:
            continue
        d.pop("bc_link", None)
        d.pop("bc_credit_of", None)
        try:
            path, _, _ = await route_with_feedback(d, is_international=bool(d.get("is_international")))
        except Exception:
            continue
        n += 1
        agree += _root(path) == _root(r.get("square9_parent_path"))
    return {"n": n, "agree": agree, "pct": round(100 * agree / n, 1) if n else None}


async def _vendor_replay(db) -> Dict[str, Any]:
    import services.vendor_matching as vm
    from services.vendor_name_helpers import normalize_vendor_name
    since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    n = right = 0
    async for d in db.hub_documents.find(
            {"bc_link.match": "number+amount", "created_utc": {"$gte": since}},
            {"_id": 0, "email_sender": 1, "vendor_raw": 1, "extracted_fields.vendor": 1,
             "normalized_fields.vendor_normalized": 1, "bc_link.bc_vendor_no": 1}):
        raw = d.get("vendor_raw") or (d.get("extracted_fields") or {}).get("vendor") or ""
        res: Dict[str, Any] = {}
        try:
            if d.get("email_sender"):
                res = await vm.lookup_vendor_by_sender(d["email_sender"], extracted_vendor=raw, document_id=None)
            if not res.get("vendor_canonical"):
                res = await vm.lookup_vendor_alias((d.get("normalized_fields") or {}).get("vendor_normalized")
                                                   or normalize_vendor_name(raw))
        except Exception:
            res = {}
        n += 1
        right += res.get("vendor_canonical") == d["bc_link"]["bc_vendor_no"]
    return {"n": n, "right": right, "pct": round(100 * right / n, 1) if n else None}


async def record_daily(db, force: bool = False) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    if not force and await db.learning_metrics.find_one({"date": today}, {"_id": 1}):
        return {"skipped": "already measured today"}
    row = {"date": today, "measured_at": datetime.now(timezone.utc).isoformat(),
           "routing": await _routing_replay(db), "vendor": await _vendor_replay(db)}
    await db.learning_metrics.update_one({"date": today}, {"$set": row}, upsert=True)
    logger.info("[LearningMetrics] %s", row)
    return {k: v for k, v in row.items() if k != "measured_at"}
