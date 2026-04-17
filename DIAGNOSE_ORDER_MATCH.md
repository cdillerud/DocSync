# 🔍 Diagnose BC Order Match 0% Regression

A new **read-only** diagnostic endpoint has been added:

```
GET /api/inside-sales-pilot/diagnose-order-match?sample_size=30
```

It reports:
1. **`cache_health`** — how many `sales_order` records are in `bc_reference_cache`, and what % have `bc_external_document_no` populated (from BC's `externalDocumentNumber`).
2. **`extraction_health`** — how many pilot docs actually have a `po_number` or `order_number` extracted.
3. **`raw_cache_samples`** — 5 raw rows so we can eyeball what `bc_external_document_no` actually looks like in production.
4. **`sample_matches`** — for each sampled doc, the PO/order extracted, the refs tried (after prefix/zero stripping), direct cache hits, and the actual `_check_order` result.
5. **`summary`** — hit rate broken down by match method.

---

## ▶️ Run on your VM

```bash
cd /opt/gpi-hub && \
git pull && \
docker compose build --no-cache backend && \
docker compose up -d backend && \
sleep 10 && \
curl -s "http://localhost:8080/api/inside-sales-pilot/diagnose-order-match?sample_size=30" \
  | python3 -m json.tool > /tmp/order_match_diag.json && \
cat /tmp/order_match_diag.json
```

Then paste the output back here (or at minimum, paste the `cache_health`,
`extraction_health`, `raw_cache_samples`, and `summary` sections).

## What we're looking for

| Symptom in output | Likely root cause |
|---|---|
| `total_sales_order_records == 0` | Cache never synced — need to trigger resync |
| `external_ref_coverage_pct < 20%` | `externalDocumentNumber` not being captured during BC sync |
| `docs_with_po_number == 0` | PO extraction from emails is broken upstream |
| `docs_with_po_number > 0` but `hit_rate_pct == 0` and `sample_matches[].direct_ref_hits == []` | PO format mismatch — customer PO in BC is free-form (e.g. "ARTWORK-PILSNER 16"); needs fuzzy match |
| `direct_ref_hits` shows hits but `result.found == false` | Bug inside `_check_order` itself |
