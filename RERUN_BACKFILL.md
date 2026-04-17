# 🔁 Re-run Backfill After Classifier Fixes

I just shipped three fixes:

1. **Classifier now catches** — `Ryl Co Inventory`, `CP on Hand from the Portal`, `Coloplast On Hold Orders`, `GAM100 Consignment Invoicing` (10/15 previously-unclassified files now classify correctly).
2. **Smart header-row detection** — `parse_excel` now scans the first 10 rows and picks the most header-like row. Fixes Ball AfterHours reports (they have a title banner + blank row before the header).
3. **`not_inventory` skips are now idempotent** — RFQs, quote sheets, credit memos get marked `inventory_xls_backfilled: true` so the next run skips them instantly.

## ▶️ Deploy + re-run

```bash
cd /opt/gpi-hub && \
git pull && \
docker compose build --no-cache backend && \
docker compose up -d backend && \
sleep 12 && \
echo "=== Re-scan: what would be staged now? ===" && \
curl -s -X POST "http://localhost:8080/api/inventory-xls/backfill-pilot-docs?dry_run=true&limit=200" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"scanned={d['scanned']} inventory={d['classified_inventory']} skipped_not_inventory={d['skipped_not_inventory']} errors={d['errors']}\")
print(f\"by_classification: {d['by_classification']}\")
print()
print('Items needing staging:')
for item in d.get('items', []):
    if item.get('status') == 'would_stage':
        print(f\"  {item.get('classification',''):25} {item.get('confidence',0):.2f}  {item.get('file','')[:60]}\")" && \
echo "" && \
echo "=== If the list looks right, apply: ===" && \
echo "curl -s -X POST 'http://localhost:8080/api/inventory-xls/backfill-pilot-docs?dry_run=false&limit=200' | python3 -m json.tool | head -30"
```

## Expected

| File | Before | After |
|---|---|---|
| 4× Ball AfterHours Open Orders | errored (parse fail) | ✅ `inventory_open_orders` @ 0.90 |
| 4× Ryl Co / CP / Coloplast / GAM100 | unmarked | ✅ `inventory_snapshot` / `outbound` |
| 2× Ryl Co vs Needs (dupes) | unmarked | ✅ `inventory_snapshot` @ 0.88 |
| 3× RFQ / Quote / Credit Memo | unmarked | ✅ `not_inventory`, marked idempotent |
| 1× Vets Plus Defects Form | unmarked | ✅ `not_inventory`, marked |
| 1× Gamer PO_0.5 GAL | unmarked | `not_inventory` (it's a customer PO — main Sales pipeline handles it) |

You should go from **14 staged + 15 unmarked** → **~24 staged + 5 skipped**, near 100% coverage.

## Then: go approve them

Once the re-backfill lands, follow the approval flow in [WHAT_TO_DO_NEXT](/app/BACKFILL_RESULTS_NEXT_STEPS.md):
1. Create customer workspaces (ball, pretium, mrp, wingnein, lagersmith, coloplast, rylco, daesang)
2. Approve 3 of each (domain, header_hash) pattern → after that, same pattern auto-applies

After one week of this, your inventory pipeline runs on autopilot for the senders you see most.
