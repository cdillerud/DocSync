# ⚡ One-Click Backfill for Existing Pilot XLS Documents

## What I saw in your dashboard

4+ XLS files are sitting in pilot classified as `SALES_INVOICE` by the main pipeline — but they're **actually inventory content**:

| Pilot-classified as | Filename | Should be |
|---|---|---|
| SALES_INVOICE | `Ryl Co Inventory vs Ryl Co Needs 4.17.26.xlsx` | `inventory_snapshot` |
| SALES_INVOICE | `897938 Gamer new order 4-2.xlsx` | `inventory_open_orders` |
| SALES_INVOICE | `Gamer Inventory Summary - Water Barons.xlsx` | `inventory_snapshot` |
| SALES_INVOICE | `Ryl Co. Gamer Can Forecast 041626.xlsx` | `inventory_forecast` |

The new inventory XLS pipeline will catch these. I just added two buttons on `/inventory/imports`:

- **Scan Pilot XLS** (amber, dry-run) → classify every pilot XLS but DON'T stage anything. Use this first to see what the classifier finds.
- **Backfill Pilot XLS** (sky-blue) → classify + stage everything that looks like inventory. Staging still requires approval before the ledger is touched.

## New endpoint
```
POST /api/inventory-xls/backfill-pilot-docs?dry_run=true|false&limit=200
```
Returns:
```json
{
  "scanned": N,
  "classified_inventory": M,
  "staged": K,
  "already_staged": L,
  "skipped_not_inventory": P,
  "by_classification": { "inventory_open_orders": X, "inventory_forecast": Y, ... },
  "items": [ ... per-doc trace ... ]
}
```

Each source doc gets marked with `inventory_xls_backfilled: true` + `inventory_xls_classification` + `inventory_xls_staging_id` so re-runs are idempotent.

## ▶️ Run on your VM

```bash
cd /opt/gpi-hub && \
git pull && \
docker compose build --no-cache backend && \
docker compose up -d backend && \
sleep 12 && \
echo "=== DRY RUN — what would be staged? ===" && \
curl -s -X POST "http://localhost:8080/api/inventory-xls/backfill-pilot-docs?dry_run=true&limit=200" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'Scanned: {d[\"scanned\"]}, classified as inventory: {d[\"classified_inventory\"]}')
print(f'Breakdown: {d[\"by_classification\"]}')
print()
print('First 10 inventory hits:')
for item in d.get('items', [])[:10]:
    if item.get('classification') not in (None, 'not_inventory'):
        print(f\"  {item.get('classification','?'):30} {item.get('confidence',0):.2f}  {item.get('file','')[:50]}\")"
```

Review the output — if the classifications look right, run the real thing:

```bash
curl -s -X POST "http://localhost:8080/api/inventory-xls/backfill-pilot-docs?dry_run=false&limit=500" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'Scanned: {d[\"scanned\"]}')
print(f'Staged: {d[\"staged\"]}')
print(f'Already staged: {d[\"already_staged\"]}')
print(f'Skipped (not inventory): {d[\"skipped_not_inventory\"]}')
print(f'Errors: {d[\"errors\"]}')
print(f'Breakdown: {d[\"by_classification\"]}')"
```

Then go to `https://<your-host>/inventory/imports` — the staging list will be populated. Review + approve each one.

Or just use the **Scan Pilot XLS** / **Backfill Pilot XLS** buttons I added to the UI.

## Why fuzzy tier stayed at 0

Looking at your actual numbers (104 exact + 1 scoped + 0 fuzzy + 140 no-match), the fuzzy tier correctly fired zero times because:
- Exact cache multi-search already caught everything matchable (99.1% external-ref coverage in your cache)
- The 140 "No match" docs aren't cache-drift issues — they're docs with ref numbers that genuinely don't exist in the BC cache (quotes, posted invoices older than sync horizon, non-standard customer refs)

The fuzzy tier is working as designed: it's a **safety net**, not a routine hit-generator. If your exact-tier % ever drops while fuzzy rises, THAT's the alarm bell — which is exactly what the donut is built to surface.
