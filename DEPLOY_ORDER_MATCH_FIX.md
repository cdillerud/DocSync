# 🚢 Deploy BC Order Match Fix + Re-validate

## What changed

`_check_order` now searches across **3 BC entity types** in priority order:
1. **`sales_order`** (open, preferred) — unchanged behavior for currently-matching docs
2. **`posted_sales_invoice`** (catches 6-digit posted order numbers like `109301`, `111092`)
3. **`posted_sales_shipment`** (catches shipment/BOL/warehouse refs)

Customer-scoped fallback also now searches all 3 entity types.

**No behavioral change for docs that already match** — this is strictly additive.

## Why was it reporting 0/222?

Your earlier `validate-all` call didn't use `force=true`, so stale `bc_prod_validation`
results (written before the recent `_check_order` improvements made it into the container)
were kept. The new diagnostic endpoint runs `_check_order` fresh and showed **42.1% hit
rate** on a 30-doc sample — confirming the code IS working.

We need to **re-validate with `force=true`** to apply the current logic to all 222 docs.

---

## ▶️ Run on your VM

```bash
cd /opt/gpi-hub && \
git pull && \
docker compose build --no-cache backend && \
docker compose up -d backend && \
sleep 12 && \
echo "=== Step 1: Diagnostic BEFORE re-validation ===" && \
curl -s "http://localhost:8080/api/inside-sales-pilot/diagnose-order-match?sample_size=30" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d['summary'], indent=2)); print('cache:', json.dumps(d['cache_health'], indent=2)); print('extraction:', json.dumps(d['extraction_health'], indent=2))" && \
echo "" && \
echo "=== Step 2: Force re-validate all 222 pilot docs ===" && \
curl -s -X POST "http://localhost:8080/api/inside-sales-pilot/validate-all?force=true" \
  | python3 -m json.tool && \
echo "" && \
echo "=== Step 3: Final order-match rate ===" && \
curl -s "http://localhost:8080/api/inside-sales-pilot/diagnose-order-match?sample_size=50" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d['summary'], indent=2))"
```

Expected outcome: Order Match rate should jump from **0%** → **45–60%** range.

Paste back:
1. The `summary` from Step 1 (pre-validation state)
2. The full output of Step 2 (validate-all response)
3. The `summary` from Step 3 (post-validation)
