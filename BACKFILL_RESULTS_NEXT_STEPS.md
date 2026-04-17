# 🔍 Investigate the 5 Backfill Errors

Run this on your VM to see exactly which 5 files errored and why:

```bash
docker exec gpi-backend python3 -c "
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
async def run():
    c = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = c[os.environ['DB_NAME']]
    # Re-run as dry-run on only the error ones by filtering hub_documents
    # whose inventory_xls_backfilled is NOT True after the backfill
    q = {
        'inside_sales_pilot': True,
        'file_name': {'\$regex': r'\\.(xlsx|xls|csv)$', '\$options': 'i'},
        'inventory_xls_backfilled': {'\$ne': True},
    }
    docs = await db.hub_documents.find(q, {'_id':0,'id':1,'file_name':1,'email_sender':1,'file_content_b64':1}).to_list(50)
    print(f'{len(docs)} XLS docs NOT marked as backfilled:')
    for d in docs:
        has_bytes = bool(d.get('file_content_b64'))
        print(f\"  {d['file_name'][:70]:70}  sender={d.get('email_sender','-')[:30]}  bytes={has_bytes}\")
asyncio.run(run())
"
```

Likely causes (in order of probability):

1. **`has_bytes=False`** — doc has no `file_content_b64` on disk (older ingest before we stored bytes, or storage layer issue). Fixable: re-ingest the mailbox so new bytes land.
2. **Parse failure** — sheet has merged cells / non-standard header row / password-protected / corrupted.
3. **Empty sheet** — no rows after headers.

Once we see the list I'll know if we need a re-ingest or a parser tweak.

---

# 🏢 The Bigger Win: Create Customer Workspaces for the 7 senders

Your staging list shows these sender domains with **NO customer assigned**:

| Sender Domain | Files | Likely customer workspace to create |
|---|---|---|
| `ball.com` | 1 | "Ball Corporation" (code: `ball`) |
| `gamerpackaging.com` | 3 | Already exists (`gamer`) |
| `pretiumpkg.com` | 4 | "Pretium Packaging" (code: `pretium`) |
| `mrpsolutions.com` | 4 | "MRP Solutions" (code: `mrp`) |
| `wnfoods.com` | 1 | "Wing Nein Foods" (code: `wingnein`) |
| `lagersmith.com` | 1 | "Lagersmith" (code: `lagersmith`) |

Without customer workspaces, you'd have to manually pick a customer for each of the 14 staging records before approving. Create the workspaces first (one curl per customer), then when you re-visit the staging records, the auto-suggest will populate the customer field automatically for the remaining 11 (3 already match Gamer).

```bash
# Create all 5 missing customer workspaces in one go
for entry in "Ball Corporation|ball" "Pretium Packaging|pretium" "MRP Solutions|mrp" "Wing Nein Foods|wingnein" "Lagersmith|lagersmith"; do
  NAME="${entry%|*}"
  CODE="${entry#*|}"
  echo "Creating $NAME ($CODE)..."
  curl -s -X POST "http://localhost:8080/api/inventory-ledger/customers" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$NAME\",\"code\":\"$CODE\"}" | python3 -c "import sys,json; d=json.load(sys.stdin); print('  id:', d.get('id','?'))"
done
```

After this, each staging record will still need a one-time click to confirm the auto-suggested customer, and the FIRST approval per `(domain, header_hash)` starts the learning loop. After 3 approvals per same pattern, future same-sender files **auto-apply**.

---

# ▶️ Suggested approval workflow

1. **Create the 5 missing customer workspaces** (curl block above).
2. **Open `/inventory/imports`**, click each `pending_review` row.
3. **Accept the suggested customer** (or correct it).
4. **Approve**. After 3 approvals per `(domain, header_hash)`, the next identical ingest auto-applies.
5. **Re-run the Backfill button** once — it's idempotent, so nothing re-stages, but it'll pick up the 5 previously-errored files if their underlying issue (e.g., missing bytes) gets fixed.

---

# 🧠 Why all 14 show `source: hybrid`

The heuristic pass got some fields (item, qty usually) but not ≥80% coverage, so the system fell back to **Claude Haiku via your Emergent LLM key** to fill in the gaps (warehouse, uom, effective_date on odd column names like "Del. Date", "PO #", "ShipTo Plant").

As you approve them, the learning loop kicks in — the NEXT file from `pretiumpkg.com` with the same headers will come in as `source: learned` (cheaper, faster, no LLM call). After 3 approvals it auto-applies.

**Your first few approvals are training sessions; the rest are observations.**
