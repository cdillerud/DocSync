"""Link sales-lane documents to their BC sales order and customer.

Sales documents (Sales_Order, Order_Confirmation, Sales_Quote) never get
a customer resolved: no customer_canonical, empty customer_candidates.
BC sales orders, shipments and sales invoices carry the customer's PO
number (external document no), so a document whose extracted PO matches
exactly one BC order is that order: its BC customer number and order
number are stored (customer_canonical, bc_sales_order_no,
customer_link_source="bc_po_match").

Customer names are then learned the same way as vendors: an extracted
customer name that maps to one BC customer in >=90% of 3+ PO-matched
documents links the documents carrying that name but no matching PO
(customer_link_source="bc_name_learned").

Dry run unless --apply. Usage (inside gpi-backend):
    PYTHONPATH=/app python scripts/link_sales_docs_to_bc.py [--since 2026-08-01] [--apply]
"""
import argparse, asyncio, os, re, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, ".")
SALES_TYPES = ["Sales_Order", "Order_Confirmation", "Sales_Quote"]


def norm(x):
    return re.sub(r"[^A-Z0-9]", "", str(x or "").upper()).lstrip("0")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-08-01")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    from motor.motor_asyncio import AsyncIOMotorClient
    from services.vendor_name_helpers import normalize_vendor_name
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

    by_po = defaultdict(dict)  # norm PO -> {customer_no: bc row}
    for t in ("sales_order", "posted_sales_shipment", "posted_sales_invoice"):
        async for d in db.bc_reference_cache.find({"bc_entity_type": t, "bc_external_document_no": {"$nin": [None, ""]}},
                                                  {"_id": 0, "bc_external_document_no": 1, "bc_customer_no": 1, "bc_customer_name": 1,
                                                   "bc_document_no": 1, "bc_order_number": 1, "bc_entity_type": 1}):
            k = norm(d["bc_external_document_no"])
            if len(k) >= 4 and d.get("bc_customer_no"):
                by_po[k].setdefault(d["bc_customer_no"], d)

    now = datetime.now(timezone.utc).isoformat()
    docs, linked, names = [], 0, defaultdict(Counter)
    async for h in db.hub_documents.find({"created_utc": {"$gte": args.since}, "document_type": {"$in": SALES_TYPES}, "is_duplicate": {"$ne": True}},
                                         {"_id": 1, "po_number_clean": 1, "extracted_fields": 1, "customer_canonical": 1, "file_name": 1}):
        ef = h.get("extracted_fields") or {}
        po = norm(h.get("po_number_clean") or ef.get("po_number"))
        cname = normalize_vendor_name(str(ef.get("customer") or ""))
        hits = by_po.get(po) if po else None
        if hits and len(hits) == 1:
            cust, row = next(iter(hits.items()))
            order = row.get("bc_order_number") or (row.get("bc_document_no") if row.get("bc_entity_type") == "sales_order" else "")
            linked += 1
            if cname and "gamer" not in cname:
                names[cname][cust] += 1
            if args.apply:
                await db.hub_documents.update_one({"_id": h["_id"]}, {"$set": {
                    "customer_canonical": cust, "customer_name_bc": row.get("bc_customer_name"),
                    "bc_sales_order_no": order, "customer_link_source": "bc_po_match", "customer_linked_at": now}})
        else:
            docs.append((h, cname))
    learned = {k: c.most_common(1)[0][0] for k, c in names.items()
               if sum(c.values()) >= 3 and c.most_common(1)[0][1] / sum(c.values()) >= 0.9}
    by_name = 0
    for h, cname in docs:
        cust = learned.get(cname)
        if cust and not h.get("customer_canonical"):
            by_name += 1
            if args.apply:
                await db.hub_documents.update_one({"_id": h["_id"]}, {"$set": {
                    "customer_canonical": cust, "customer_link_source": "bc_name_learned", "customer_linked_at": now}})
    print(("APPLIED" if args.apply else "DRY RUN") + f": linked by PO {linked}, customer names learned {len(learned)}, "
          f"linked by learned name {by_name}, still unlinked {len(docs) - by_name}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
