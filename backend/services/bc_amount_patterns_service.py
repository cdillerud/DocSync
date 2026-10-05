"""Vendor amount patterns from Business Central (ground truth).

amount_patterns feeds the extraction prompt ("typical amount for this
vendor") and per-document anomaly flags. It used to be built by appending
each Hub document's extracted amount every time learning ran on it, so
reprocessing repeated amounts (Arkansas Glass: the same 10 amounts ~20
times; Tumalo count 14,995) and every document type was mixed in. It is
now rebuilt from BC purchase invoices (draft/open/paid, not canceled):
per vendor the last 200 totals with count, average, standard deviation,
min and max. Runs in the hourly learning cycle.
"""
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict


async def refresh_amount_patterns_from_bc(db, days: int = 365) -> Dict[str, Any]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    rows = defaultdict(list)
    async for b in db.bc_reference_cache.find(
            {"bc_entity_type": {"$in": ["posted_purchase_invoice", "draft_purchase_invoice"]},
             "bc_posting_date": {"$gte": since}, "bc_status": {"$ne": "Canceled"}, "bc_amount": {"$gt": 0}},
            {"_id": 0, "bc_vendor_no": 1, "bc_amount": 1, "bc_posting_date": 1, "bc_external_document_no": 1}):
        if b.get("bc_vendor_no"):
            rows[b["bc_vendor_no"]].append(b)
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for vendor, items in rows.items():
        seen, amounts = set(), []
        for b in sorted(items, key=lambda x: x.get("bc_posting_date") or ""):
            key = (b.get("bc_external_document_no"), round(float(b["bc_amount"]), 2))
            if key in seen:
                continue
            seen.add(key)
            amounts.append(round(float(b["bc_amount"]), 2))
        amounts = amounts[-200:]
        if not amounts:
            continue
        n = len(amounts)
        avg = sum(amounts) / n
        sd = math.sqrt(sum((a - avg) ** 2 for a in amounts) / n) if n > 1 else 0.0
        await db.amount_patterns.update_one(
            {"vendor_no": vendor},
            {"$set": {"vendor_no": vendor, "amounts": amounts, "count": n, "sum": round(sum(amounts), 2),
                      "avg_amount": round(avg, 2), "stddev": round(sd, 2), "min_amount": min(amounts),
                      "max_amount": max(amounts), "source": "bc", "doc_type": "AP_Invoice", "updated_at": now}},
            upsert=True)
        written += 1
    return {"vendors": written}
