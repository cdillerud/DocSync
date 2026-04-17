# 🚀 P1 Phase 2 + Enhancements — Full Rollout

## What's shipped in this batch

### 1. Order Match fuzzy tier (targets 58% → 70%+)
- `_check_order` gains a final "fuzzy_normalized_search" tier that runs when `bc_customer_no` is null and the ref is ≥6 chars.
- Searches `normalized_document_no`, `normalized_external_ref`, and regex on raw `bc_external_document_no` across `sales_order + posted_sales_invoice + posted_sales_shipment`.
- Diagnostic endpoint now reports a new `hit_via_fuzzy_normalized` bucket.

### 2. UI: BC Match column on Inside Sales Pilot dashboard
- New "BC Match" column in the Recent Pilot Documents table.
- Color-coded badge per `order_lookup.bc_entity_type`:
  - 🟢 **Open SO** (`sales_order`)
  - 🟡 **Posted Inv** (`posted_sales_invoice`)
  - 🔵 **Shipment** (`posted_sales_shipment`)
  - ⚪ **—** (no match)
- Tier suffix: `~` for fuzzy, `c` for customer-scoped (tooltips explain).
- Safety guard: reviewers can instantly spot docs matched against already-posted invoices vs open orders.

### 3. Low-volume vendor routing (<5 docs → manual review)
- In `document_readiness_service.evaluate_and_persist`, after the vendor-bypass check, a new gate counts prior docs for the vendor. If fewer than 5 non-duplicate docs exist, readiness downgrades from ready_auto_* → needs_review with reason `low_volume_vendor`.
- Prevents first-time / rare vendors from auto-filing with insufficient training data.

### 4. BOL / Tracking number extraction on pilot docs
- `_extract_sales_fields` now captures `bol_number`, `tracking_number`, and `carrier` from the main pipeline's extracted / normalized fields onto `sales_pilot_extraction`.
- **Pilot stays ingest-only** — these fields are persisted + displayable, NOT written to BC.

### 5. P1 Phase 2 — migrate remaining callers to unified facade
Migrated call sites (8 total):
- `server.py :: _run_pilot_enrichment` (already done in Phase 1)
- `server.py` — intake readiness (line ~3565), gap-closer (~8201), PO retry (~8431)
- `routers/readiness.py` — `/evaluate/{doc_id}` and PO retry endpoint
- `routers/inside_sales_pilot.py` — `/validate/{doc_id}` + re-extract loop
- `services/inside_sales_pilot_service.py` — polling loop
- `services/gap_closer_service.py` — re-evaluation loop

All now import from `services.unified_validation_service` (delegators `run_bc_prod_validation` / `run_readiness`). **Zero behavior change** — the delegators are one-liners calling the same underlying functions.

---

## ▶️ Run on your VM

```bash
cd /opt/gpi-hub && \
git pull && \
docker compose build --no-cache && \
docker compose up -d && \
sleep 15 && \
echo "=== 1. Backend health ===" && \
docker exec gpi-backend python3 -c "
from policies import list_policies, get_policy
from services.unified_validation_service import POLICY_STAGES
print('policies:', [p['name'] for p in list_policies()])
print('stages:', POLICY_STAGES)
" && \
echo "" && \
echo "=== 2. Re-validate ALL docs with force=true (picks up fuzzy tier + entity_type badge) ===" && \
curl -s -X POST "http://localhost:8080/api/inside-sales-pilot/validate-all?force=true" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"validated={d.get('validated')}, avg_score={d.get('avg_score')}, errors={d.get('errors')}\")" && \
echo "" && \
echo "=== 3. Post-validation hit rate ===" && \
curl -s "http://localhost:8080/api/inside-sales-pilot/diagnose-order-match?sample_size=60" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
s = d['summary']
print('hit_rate:', s['hit_rate_pct'], '%')
print('  cache_multi     ', s['hit_via_cache_multi'])
print('  direct_cache    ', s['hit_via_direct_cache'])
print('  customer_scoped ', s['hit_via_customer_scoped'])
print('  fuzzy_normalized', s['hit_via_fuzzy_normalized'])
print('  misses          ', s['misses'])
print('  no_ref          ', s['no_ref_extracted'])
" && \
echo "" && \
echo "=== 4. Sanity: frontend still serves ===" && \
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/
```

## Expected

| Metric | Before | After |
|---|---|---|
| Order Match hit rate | 58.8% | **~65–75%** (fuzzy tier catches free-form POs) |
| Low-volume vendor docs auto-filing | Yes | No (routed to review) |
| BOL/Tracking visible on pilot dashboard | No | Yes (extracted field) |
| UI Match Source badge | Missing | Present (Open SO / Posted Inv / Shipment) |

---

## What's NOT in this batch (intentionally)

- **Teams Adaptive Card webhook** — deferred. This needs:
  1. An Azure AD app registration with `ChannelMessage.Send` permission
  2. A Teams incoming webhook URL OR a bot framework bot ID
  3. Your decision on whether the "Approve" action should actually create the BC Sales Order (currently the pilot is ingest-only — approving would need explicit user sign-off to change that constraint).

  Tell me which of those 3 you already have and I'll scope + build the receiver endpoint.

- **P1 Phase 3 — full server.py policy extraction** — deferred. This is a 1000+ line behavioral migration (doc-type branches lines 2065-2438 + 3333-3634 of `server.py`). Risk of breaking the 97.2% auto-rate is real. I recommend a dedicated session with full regression testing via `testing_agent_v3_fork`.

- **Evergreen multi-PO container allocation spreadsheet** — needs a sample spreadsheet + schema clarification before I can build it.
