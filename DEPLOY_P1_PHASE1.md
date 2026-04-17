# 🚀 P1 Phase 1 — Unified Validation + Policy Scaffolding

## What changed (strictly additive, zero behavior change)

### New files
```
backend/services/unified_validation_service.py   ← single entry point facade
backend/policies/__init__.py
backend/policies/base.py                          ← PolicyModule ABC + PolicyResult
backend/policies/registry.py                      ← get_policy(doc_type)
backend/policies/archive.py
backend/policies/warehouse.py
backend/policies/ap_invoice.py
backend/policies/sales_order.py                   ← enforces pilot ingest-only
```

### Modified
- `backend/server.py :: _run_pilot_enrichment` — now calls the unified facade instead of importing `bc_prod_validator` + `pilot_readiness_review_service` directly. **Same stages run in same order.**

## Why this is safe

| Risk | Mitigation |
|---|---|
| Pipeline regression | No validator logic was touched. Only ONE call site (`_run_pilot_enrichment`) was migrated. The facade delegates line-for-line to the same old functions. |
| Order of execution changed | Verified: `pilot_sales` stage list = `["bc_prod", "pilot_readiness"]` — identical to the previous inline order. |
| Policies might accidentally fire | Policy modules exist but are NOT wired into the runtime yet. They're registered and loadable, but no code path calls `get_policy(...).evaluate(...)`. Zero runtime impact. |
| Doc_type fallback loses docs | `get_policy("unknown")` falls back to archive, which marks `not_applicable`. No silent drops. |

## ▶️ Run on your VM

```bash
cd /opt/gpi-hub && \
git pull && \
docker compose build --no-cache backend && \
docker compose up -d backend && \
sleep 12 && \
echo "=== Health: unified facade ===" && \
docker exec gpi-backend python3 -c "
import asyncio
from policies import list_policies, get_policy
from services.unified_validation_service import POLICY_STAGES, _infer_policy_hint

print('Registered policies:')
for p in list_policies():
    print(' ', p)

print()
print('Doc-type routing:')
for dt in ['sales_order','invoice','bol','certificate','garbage']:
    print(f'  {dt:18} -> {get_policy(dt).policy_name}')

print()
print('POLICY_STAGES:')
for k, v in POLICY_STAGES.items():
    print(f'  {k:15} -> {v}')
" && \
echo "" && \
echo "=== Regression: Order Match still holding ===" && \
curl -s "http://localhost:8080/api/inside-sales-pilot/diagnose-order-match?sample_size=50" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d['summary'], indent=2))" && \
echo "" && \
echo "=== Regression: pilot enrichment still runs on new docs ===" && \
echo "Trigger a pilot poll or wait for the scheduler; validation bundle will be written to hub_documents.bc_prod_validation + pilot_review_result as before."
```

## Expected output

1. **Policies block**: 4 registered policies, 14 doc_type mappings, garbage → archive fallback.
2. **Order match**: still ~58% hit rate (unchanged from P0 fix).
3. **Enrichment**: docs ingested after restart should still get `bc_prod_validation` + `pilot_review_result` populated (verify in Mongo after the next poll cycle).

---

## Next up (pending your approval after this lands clean)

**P1 Phase 2** — Migrate the remaining ~30 direct callers of `validate_document_against_bc` / `evaluate_and_persist` to the unified facade, then extract shared primitives out of the 5 readiness services into `unified_validation_service`.

**P1 Phase 3** — Flesh out `policies/*.py` with real logic extracted from `server.py` lines 2065-2438 + 3333-3634 (the doc_type branches), and wire the pipeline orchestrator to call them.
