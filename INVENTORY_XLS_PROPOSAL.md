# 📦 Inventory XLS Inference — Architecture Proposal

## Context — what we already have

| Piece | Location | State |
|---|---|---|
| Excel parser (pandas) | `services/file_ingestion_service.py :: parse_excel()` | ✅ Built — handles `.xlsx` + `.xls`, sheet selection |
| Inventory ledger (immutable) | `services/inventory_ledger_service.py` | ✅ Built — customers, movements, incoming supply |
| CSV import endpoint | `POST /api/inventory-ledger/import` | ✅ Built — SHA-256 dedup, opening_balance/manual_adjustment only |
| `spreadsheet_import` source type | `SOURCE_TYPES` | ✅ Registered |
| Pilot mailbox ingestion of .xlsx | `inside_sales_pilot_service.py` | ✅ Ingests — currently archived as "Report" |

## What's missing — and what pilot docs prove we need

From the last pilot diagnostic (real VM data), these XLS docs all hit pilot and got **no inventory treatment**:

| Filename | Should become |
|---|---|
| `3000000223(GAME)_OpenOrderList.xlsx` | `order_commitment` ledger rows |
| `Gamer Dunnage 04.13.26.xlsx` | `receipt` + ownership `gamer_reserved` |
| `open_orders_report_13-APR-26.xlsx` | `order_commitment` snapshot |
| `Gamer Packaging Open Orders (As of 2026-03-18).xlsx` | `order_commitment` snapshot |
| `Wing Nein HRML Forecast .xlsx` | planned `incoming_supply` |
| `American Popcorn Works- 32oz RFQ.xlsx` | (not inventory — skip) |

## Proposed architecture — 4 phases

### Phase A — XLS classifier + routing (small, low risk)
Add a detector that fires on every ingested `.xlsx`/`.xls` with sheet-header inference:

| Signal | Classification | Movement intent |
|---|---|---|
| Filename `open.?order` or sheet has `PO#`+`qty`+`ship date` | `inventory_open_orders` | `order_commitment` |
| Filename `forecast` or sheet has `week`+`qty` | `inventory_forecast` | planned `incoming_supply` |
| Filename `dunnage` or sheet has `returnable`+`qty` | `inventory_dunnage` | `receipt` (`gamer_reserved`) |
| Filename `inventory.?count|on.?hand|stock.?level` | `inventory_snapshot` | `opening_balance` |
| Filename `receipt|ASN|shipment` + has `qty_received` | `inventory_receipt` | `receipt` |
| Filename `BOL` + qty columns | `inventory_outbound` | `outbound_shipment` |
| No match | `Report` (current fallback) | none |

**File**: `services/inventory_xls_classifier.py` — 150 lines, pure regex + header heuristics.

### Phase B — Column-mapping inference (medium risk)
**File**: `services/inventory_xls_parser.py`

Given a classified sheet, infer column mappings using:
1. **Heuristic pass** — regex match on header names (`^item|sku|part`, `qty|quantity|balance`, etc.)
2. **LLM fallback pass** (via Emergent LLM key) — when heuristic coverage <80%, send headers + 3 sample rows to Claude Haiku with a strict JSON schema
3. **Learned pass** — check `inv_xls_learned_mappings` keyed by `(sender_domain, filename_pattern, sheet_hash)` for previously-approved mappings; auto-use if confidence ≥ 0.9

Output: canonical row list `[{item, qty, warehouse, ownership_type, uom, reference, notes}]`.

### Phase C — Staging + human-in-the-loop approval (safety)
**New collection**: `inv_import_staging`

1. Parsed rows land in staging, NOT in the ledger.
2. New UI at `/inventory/imports` shows:
   - Detected classification + confidence
   - Column mapping with per-column confidence
   - First 20 rows preview
   - Customer workspace selector (auto-suggested from sender/filename)
   - Approve / Reject / Edit-mapping buttons
3. On Approve → insert into `inv_movements` via `create_movement`, mark staging row as `applied`
4. On Reject → retain for audit; on Edit-mapping → user fixes, system learns
5. Staging is the ONLY write path for XLS — matches the pilot's "ingest-only, human-approved" safety model

### Phase D — Learning loop (capability)
**New collection**: `inv_xls_learned_mappings`
- Every approved mapping persists `{sender_domain, filename_pattern, sheet_header_hash, column_map, approved_by, approval_count}`.
- Future ingests from same sender/pattern → confidence ≥0.9 → auto-approve OR present to user with "Last time you mapped these columns like this. Approve?" (auto-approve threshold configurable per customer workspace)
- Stats available at `/api/inventory/xls-learning-summary` for the AI Learning Intelligence dashboard.

## Deliverables per phase

| Phase | Backend | Frontend | Risk |
|---|---|---|---|
| **A** | 1 classifier file, 1 router endpoint | Badge on Hub document row | Low |
| **B** | 1 parser file, LLM integration | Mapping preview component | Medium |
| **C** | Staging collection + 4 endpoints, approval flow | New `/inventory/imports` page | Medium-High |
| **D** | Learning collection + 2 endpoints | Stats card on AI Learning dashboard | Low |

## Safety guarantees (same model as the Sales pilot)

1. **No XLS ever auto-writes to the ledger** until Phase C staging approval — pilot-identical human-in-the-loop.
2. **Dedup via SHA-256** on the raw file bytes — same file imported twice returns 409.
3. **Row-level idempotency** — opening_balance for `(customer, item, warehouse, ownership)` can only exist once (already enforced).
4. **Customer workspace isolation** — Gamer rows never leak to Giovanni rows.
5. **Audit trail** — every movement carries `source_type="spreadsheet_import"`, `reference_type="xls_import"`, `reference_id=<staging_id>`.

## Estimated effort

| Phase | Effort | Value |
|---|---|---|
| A | Half-day | Unblocks classification — all pilot XLS start getting tagged |
| B | 1 day | LLM-assisted mapping — works on any reasonable spreadsheet |
| C | 1–2 days | The real safety moat + UX |
| D | Half-day | Turns one-shot imports into self-improving automation |

**Total**: ~3 days for a production-ready XLS → inventory ledger pipeline.

## Open questions for you

1. **Scope this session**: Phase A only (detect + tag + offer import link), or A + B (auto-parse and stage), or all four?
2. **Customer workspace assignment**: should the classifier auto-assign from sender domain (e.g., `@gamerpackaging.com` → Gamer) OR always require manual assignment at staging?
3. **Forecast handling**: should forecasts create `incoming_supply` records at ingest (planned quantities), or stay advisory until confirmed?
4. **Dunnage ownership inference**: filename contains "Dunnage" → `gamer_reserved`. Is that always correct, or do some customers own their own dunnage?
5. **Date anchoring**: when a "Gamer Packaging Open Orders (As of 2026-03-18)" is imported, should the 2026-03-18 date override `created_at` for the commitment movements, or should we treat it as a snapshot-as-of-now?
