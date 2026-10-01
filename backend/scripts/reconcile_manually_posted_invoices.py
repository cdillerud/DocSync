"""Mark queued invoices that staff already posted in Production BC as posted.

Owner-approved 2026-10-01. Nothing is written to BC. Each document keeps its
previous status in reconcile_previous so the change can be reversed.
Usage (inside gpi-backend): PYTHONPATH=/app python scripts/reconcile_manually_posted_invoices.py [--apply]
"""
import asyncio, os, sys, logging
from datetime import datetime, timezone
logging.disable(logging.CRITICAL)
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
import deps

APPLY = "--apply" in sys.argv
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
deps.set_db(db)
import services.gpi_integration_service as g


async def main():
    q = {"$or": [{"status": "ReadyForPost"}, {"workflow_status": "ready_for_post"}],
         "status": {"$ne": "batch_parent"}, "bc_purchase_invoice": {"$exists": False}}
    tok = await g._get_token()
    env = g.BC_READ_ENVIRONMENT
    cid = await g._resolve_company_id(env)
    url = f"{g.GPI_API_BASE}/{g.BC_TENANT_ID}/{env}/api/v2.0/companies({cid})/purchaseInvoices"
    h = {"Authorization": "Bearer " + tok}
    now = datetime.now(timezone.utc).isoformat()
    matched = updated = 0
    async with httpx.AsyncClient(timeout=60) as cl:
        async for d in db.hub_documents.find(q, {"_id": 0, "id": 1, "status": 1, "workflow_status": 1,
                                                 "bc_vendor_number": 1, "vendor_no": 1,
                                                 "extracted_fields.invoice_number": 1,
                                                 "normalized_fields.invoice_number": 1}):
            v = d.get("bc_vendor_number") or d.get("vendor_no")
            inv = (d.get("extracted_fields") or {}).get("invoice_number") or (d.get("normalized_fields") or {}).get("invoice_number")
            if not (v and inv):
                continue
            r = await cl.get(url, headers=h, params={
                "$filter": "vendorNumber eq '" + v.replace("'", "''") + "' and vendorInvoiceNumber eq '" + str(inv).replace("'", "''") + "'",
                "$select": "id,number,status,postingDate", "$top": "1"})
            hit = (r.json().get("value") or [None])[0] if r.status_code == 200 else None
            if not hit:
                continue
            matched += 1
            if not APPLY:
                continue
            res = await db.hub_documents.update_one(
                {"id": d["id"], "bc_purchase_invoice": {"$exists": False}},
                {"$set": {
                    "reconcile_previous": {"status": d.get("status"), "workflow_status": d.get("workflow_status")},
                    "status": "Posted",
                    "workflow_status": "posted",
                    "bc_posting_status": "posted_manually_in_bc",
                    "bc_record_no": hit["number"],
                    "bc_purchase_invoice_no": hit["number"],
                    "bc_purchase_invoice": {
                        "bc_record_no": hit["number"], "bc_system_id": hit["id"],
                        "status": hit["status"], "success": True,
                        "environment": env, "vendor_no": v, "vendor_invoice_no": inv,
                        "source": "matched_existing_bc_invoice",
                        "note": "posted manually in BC; matched by vendor + vendor invoice number",
                        "matched_at": now,
                    },
                    "updated_utc": now,
                },
                 "$push": {"workflow_history": {
                     "timestamp": now, "from_status": d.get("workflow_status"), "to_status": "posted",
                     "event": "reconciled_with_bc", "actor": "reconcile_posted_script",
                     "reason": f"Already posted manually in BC as PI {hit['number']} ({hit['status']})",
                 }}})
            updated += res.modified_count
    print(("APPLIED" if APPLY else "DRY RUN") + f": matched {matched}, updated {updated}")


asyncio.run(main())
