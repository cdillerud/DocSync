# 📦 Inventory XLS Pipeline — Full Rollout

All four phases (A + B + C + D) shipped in one batch. **20/20 backend tests passed** (iter 207).

## What's new

### Phase A — Classifier (`services/inventory_xls_classifier.py`)
Detects inventory-relevant XLS files via filename + sheet headers:

| Signal | Classification | Movement intent |
|---|---|---|
| `open.?order` | `inventory_open_orders` | `order_commitment` |
| `forecast \| HRML` | `inventory_forecast` | `incoming_supply` |
| `dunnage` | `inventory_dunnage` | `receipt` (`gamer_reserved`) |
| `inventory.*(count\|snapshot\|balance)` | `inventory_snapshot` | `opening_balance` |
| `asn \| receipt \| shipment` | `inventory_receipt` | `receipt` |
| `bol \| bill.of.lading \| outbound` | `inventory_outbound` | `outbound_shipment` |

Returns filename + header agreement bonus when both fire on same classification (+0.05 conf).

### Phase B — Parser (`services/inventory_xls_parser.py`)
Column-mapping cascade: **learned → heuristic → LLM (Claude Haiku)**.

- 9 canonical fields: `item`, `item_description`, `qty`, `warehouse`, `ownership_type`, `uom`, `reference`, `effective_date`, `notes`.
- `compute_header_hash(headers)` — stable sha256[:16] on sorted-normalized headers (cross-service key).
- `extract_effective_date_from_filename()` — parses `YYYY-MM-DD`, `MM-DD-YYYY`, `MM-DD-YY` from filenames like "Open Orders As Of 2026-03-18.xlsx".
- LLM fallback only fires when heuristic coverage <80% (via Emergent LLM Key).

### Phase C — Staging + approval (`services/inventory_xls_staging_service.py`)
- **`inv_import_staging` collection** — every XLS lands here first, NEVER auto-writes to ledger.
- Endpoints:
  - `POST /api/inventory-xls/ingest` (multipart) — classify + parse + stage
  - `POST /api/inventory-xls/ingest-pilot-doc/{doc_id}` — retroactively process XLS already in hub_documents
  - `GET  /api/inventory-xls/staging[?status=&customer_id=]`
  - `GET  /api/inventory-xls/staging/{id}`
  - `POST /api/inventory-xls/staging/{id}/update` — fix column_map / assign customer
  - `POST /api/inventory-xls/staging/{id}/approve?approved_by=user` — apply to ledger
  - `POST /api/inventory-xls/staging/{id}/reject?rejected_by=user&reason=`
- Dedup by `file_hash + customer_id` — re-ingesting same file returns `already_staged=true`.
- Forecast classification routes to `inv_incoming_supply` (planned qty), everything else to `inv_movements`.
- Every applied movement carries `source_type="spreadsheet_import"`, `reference_type="xls_import"`, `reference_id=<staging_id>`, `effective_date` (additive — never overrides `created_at`).
- Dunnage ownership resolves via cascade: customer.default_dunnage_ownership → classification hint → row override → `customer_owned` fallback.

### Phase D — Learning (`inv_xls_learned_mappings` collection)
- On first approval, persists `{sender_domain, header_hash, column_map, classification, approval_count}`.
- Future ingests with same `(sender_domain, header_hash)` auto-resolve via `source: "learned"` with confidence = 0.80 + 0.03·approvals (capped at 0.99).
- `GET /api/inventory-xls/learning-summary` returns aggregates for AI Learning dashboard.

### Phase E — UI (`frontend/src/pages/InventoryImportsPage.js`)
Route: `/inventory/imports`. Full dashboard:
- Status filter chips (pending_review / applied / rejected / all)
- Upload button (accepts .xlsx / .xls / .csv)
- Learning summary strip showing top senders by approval count
- Staging list with classification + confidence + map source pills
- Side-drawer detail view with classification signals, column map preview, row preview (up to 80 rows scrollable), customer selector (auto-suggests from sender domain), Approve / Reject actions

---

## ▶️ Run on your VM

```bash
cd /opt/gpi-hub && \
git pull && \
docker compose build --no-cache && \
docker compose up -d && \
sleep 15 && \
echo "=== 1. Indexes created ===" && \
docker exec gpi-backend python3 -c "
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
async def run():
    c = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = c[os.environ['DB_NAME']]
    staging_idx = await db.inv_import_staging.index_information()
    learn_idx = await db.inv_xls_learned_mappings.index_information()
    print('staging indexes:', list(staging_idx.keys()))
    print('learning indexes:', list(learn_idx.keys()))
asyncio.run(run())
" && \
echo "" && \
echo "=== 2. Backfill pilot XLS docs (OPTIONAL) ===" && \
echo "# Find existing pilot XLS docs and run them through the classifier:" && \
docker exec gpi-backend python3 -c "
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
async def run():
    c = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = c[os.environ['DB_NAME']]
    q = {'inside_sales_pilot': True, 'file_name': {'\$regex': '\\\\.xlsx\$', '\$options': 'i'}}
    count = await db.hub_documents.count_documents(q)
    docs = await db.hub_documents.find(q, {'_id':0, 'id':1, 'file_name':1}).limit(100).to_list(100)
    print(f'{count} pilot XLS docs found:')
    for d in docs[:10]:
        print(' ', d['file_name'][:70])
asyncio.run(run())
" && \
echo "" && \
echo "=== 3. To backfill, run this loop ===" && \
cat <<'EOF'
IDS=$(docker exec gpi-backend python3 -c "
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
async def run():
    c = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = c[os.environ['DB_NAME']]
    q = {'inside_sales_pilot': True, 'file_name': {'\$regex': '\\\\.xlsx\$', '\$options': 'i'}}
    async for d in db.hub_documents.find(q, {'_id':0,'id':1}):
        print(d['id'])
asyncio.run(run())
")
for ID in \$IDS; do
  echo "Processing \$ID..."
  curl -s -X POST "http://localhost:8080/api/inventory-xls/ingest-pilot-doc/\$ID" | python3 -c "import sys,json; d=json.load(sys.stdin); s=d.get('staging') or {}; print(f\"  staged={d.get('staged',False)} cls={(s.get('classification') or {}).get('classification')} rows={s.get('row_count',0)}\")"
done
EOF
echo ""
echo "=== 4. Open /inventory/imports in the UI to review + approve ==="
```

## Where to see it in the UI

Navigate to: `https://<your-host>/inventory/imports`

You'll see:
- Any currently-staged pilot XLS docs
- Upload button for ad-hoc XLS imports
- Learning strip at the top showing which senders the system has already "learned" from
- Click any row → side-drawer with classification signals, column-map preview, row-level data, customer assignment, and Approve/Reject buttons

## Safety model (identical to Sales Pilot)

1. ✅ No XLS auto-writes to the ledger
2. ✅ Dedup by SHA-256 file hash per customer
3. ✅ Row-level idempotency (existing `create_movement` balance checks)
4. ✅ Every row traceable via `reference_id=<staging_id>`
5. ✅ Customer workspace isolation (Gamer rows can never touch Giovanni rows)
6. ✅ Full audit trail: approved_by + approved_at on every movement

---

## What's NOT in this batch

- **Auto-stage from pilot mailbox ingestion** — deferred. Currently pilot XLS attachments need `POST /api/inventory-xls/ingest-pilot-doc/{doc_id}` run explicitly (either via the bulk backfill script above, or wired into `_run_pilot_enrichment` once you've reviewed how aggressive you want auto-staging to be).
- **Teams webhook** — still awaiting your config (Azure AD app, webhook URL, constraint-break signoff).
- **P1 Phase 3** (policy extraction from server.py) — still deferred; needs dedicated session.
