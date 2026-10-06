"""Mark repeated copies of the same invoice as duplicates.

Copies of one invoice reach the Hub under different file names: a vendor
resends it, Fevisa sends a PDF and its CFDI XML, an original PDF is kept
alongside its single split piece. The filename-based duplicate scan
(triage_tools_service.duplicate_scan) misses all of these: 221 extra
copies of AP invoices since 2026-09-01 were counted as separate invoices.

Identity = vendor_canonical + invoice_number_clean + amount (within
0.02). The oldest copy is kept (a posted/BC-linked copy always wins);
the others get is_duplicate=True, duplicate_reason="invoice_identity",
duplicate_of_document_id. Different amounts are never merged (a statement
that cites an invoice number is not a copy of it).

Dry run unless --apply. Usage (inside gpi-backend):
    PYTHONPATH=/app python scripts/mark_invoice_duplicates.py [--since 2026-08-01] [--apply]
"""
import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, ".")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-08-01")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    groups = defaultdict(list)
    async for d in db.hub_documents.find(
            {"created_utc": {"$gte": args.since}, "is_duplicate": {"$ne": True}, "status": {"$ne": "batch_parent"},
             # an identity needs a real number: label words ("AND", "INVOICE")
             # merged distinct invoices of the same amount
             "invoice_number_clean": {"$nin": [None, ""], "$regex": "[0-9]"}, "vendor_canonical": {"$nin": [None, ""]},
             "amount_float": {"$ne": None},
             "document_type": {"$in": ["AP_Invoice", "Credit_Memo", "Freight_Invoice"]}},
            {"_id": 0, "id": 1, "vendor_canonical": 1, "invoice_number_clean": 1, "amount_float": 1, "created_utc": 1,
             "file_name": 1, "status": 1, "bc_purchase_invoice": 1}):
        groups[(str(d["vendor_canonical"]).upper(), str(d["invoice_number_clean"]).upper(),
                round(abs(float(d["amount_float"])), 2))].append(d)
    now = datetime.now(timezone.utc).isoformat()
    marked = 0
    for key, docs in groups.items():
        if len(docs) < 2:
            continue
        docs.sort(key=lambda d: (not (d.get("bc_purchase_invoice") or d.get("status") == "Posted"), d.get("created_utc") or ""))
        keeper = docs[0]
        for d in docs[1:]:
            if d.get("bc_purchase_invoice") or d.get("status") == "Posted":
                continue
            marked += 1
            if marked <= 12:
                print(f"  {key[0]:10} {key[1]:16} {key[2]:>11,.2f}  {d['file_name'][:34]:34} -> keep {keeper['file_name'][:34]}")
            if args.apply:
                await db.hub_documents.update_one({"id": d["id"]}, {"$set": {
                    "is_duplicate": True, "duplicate_reason": "invoice_identity",
                    "duplicate_of_document_id": keeper["id"], "updated_utc": now}})
    print(("APPLIED" if args.apply else "DRY RUN") + f": duplicate copies {'marked' if args.apply else 'to mark'}: {marked}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
