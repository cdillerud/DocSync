# GPI Document Hub - Changelog

## [2026-04-17] Inventory XLS Inference Pipeline — Phases A+B+C+D

### Added — Phase A (Classifier)
- `services/inventory_xls_classifier.py` — `classify_xls(filename, headers, sender_email) → XlsClassification`. Rule-based detector for 6 inventory doc types with filename + header signals, confidence scoring, and filename+header agreement bonus.

### Added — Phase B (Column Mapper + Row Normalizer)
- `services/inventory_xls_parser.py`:
  - `build_column_map` — cascade: learned → heuristic → LLM (Claude Haiku via Emergent LLM Key).
  - `normalize_rows` — applies column_map, parses dates/numbers, skips zero-qty/missing-item rows.
  - `compute_header_hash` — stable sha256[:16] over sorted-normalized headers (shared across services).
  - `extract_effective_date_from_filename` — detects "As Of" dates in filenames.

### Added — Phase C (Staging + Approval)
- `services/inventory_xls_staging_service.py` — stage_import / update_staging / approve_staging / reject_staging / suggest_customer_workspace.
- `routers/inventory_xls.py` — 8 REST endpoints under `/api/inventory-xls/`:
  - `POST /ingest` (multipart file upload)
  - `POST /ingest-pilot-doc/{doc_id}` (retroactive for hub_documents)
  - `GET /staging[?status=&customer_id=&limit=&skip=]`
  - `GET /staging/{id}`
  - `POST /staging/{id}/update`
  - `POST /staging/{id}/approve?approved_by=`
  - `POST /staging/{id}/reject?rejected_by=&reason=`
  - `GET /learning-summary`
- New collections: `inv_import_staging`, `inv_xls_learned_mappings` (indexes ensured at startup).
- Forecast rows route to `inv_incoming_supply` (planned); everything else to `inv_movements`.
- `effective_date` additive field on movements (never overrides `created_at`).

### Added — Phase D (Learning Loop)
- On approval, persists `{sender_domain, header_hash, column_map, classification, approval_count}`.
- Future ingests with matching `(sender_domain, header_hash)` auto-resolve via `source: "learned"` with conf = 0.80 + 0.03·approvals.
- `get_learning_summary` returns aggregates for AI Learning dashboard.

### Added — Phase E (UI)
- `frontend/src/pages/InventoryImportsPage.js` — full review/approval dashboard at `/inventory/imports`:
  - Status filter chips (pending_review / applied / rejected / all)
  - Upload button (.xlsx / .xls / .csv)
  - Learning summary strip (top senders by approval count)
  - Staging list with classification + map source pills
  - Side-drawer: classification signals, column map preview, first 80 rows, customer selector, Approve / Reject actions

### Verified
- `testing_agent_v3_fork` iteration 207: **20/20 backend tests passed, 0 issues.**
- Live smoke test on preview env:
  - Ingest: 3-row OpenOrders XLS → classified at 0.95 conf, mapped at 0.82 heuristic
  - Approval: 3 movements in `inv_movements` with `effective_date` preserved
  - Learning: second file from same domain → `source: "learned"` at 0.83 confidence
  - UI: Renders correctly with learning strip, staging list, and detail drawer
- Deploy instructions + backfill script in `/app/DEPLOY_INVENTORY_XLS.md`.

### Deferred
- Auto-stage from pilot mailbox ingestion (currently requires explicit `POST /ingest-pilot-doc/{id}` per doc, or the bulk backfill loop).
- Teams Adaptive Card webhook (user input still pending).
- P1 Phase 3 (policy extraction from server.py).



## [2026-04-17] Match-Tier Distribution Donut Chart

### Added
- **`GET /api/inside-sales-pilot/match-tier-distribution`** — aggregation endpoint returning match-tier buckets (`exact`, `scoped`, `fuzzy`, `live`, `no_match`, `no_ref`) + `by_entity_type` breakdown + overall `match_rate_pct`.
- **`MatchTierDonut` component** (pure-SVG, no chart library) — rendered at top of Inside Sales Pilot dashboard showing donut + color-coded legend. Serves as canary metric: a drop in the exact slice while fuzzy rises is an early warning of extraction / BC cache drift BEFORE the overall match rate changes.
- Lint clean. Backend smoke-tested (empty preview env returns zero-state correctly).

### Added — Inventory XLS Proposal
- **`/app/INVENTORY_XLS_PROPOSAL.md`** — 4-phase architecture for routing inventory-related `.xlsx`/`.xls` emails into the `inv_movements` ledger with pilot-style human-in-the-loop safety (Phase A classifier → B column mapping with LLM fallback → C staging + approval → D learning loop). Awaiting user scope decision (A only, A+B, or all four).



## [2026-04-17] P1 Phase 2 + Batch Enhancements

### Added — Order Match fuzzy tier
- `_check_order` in `services/bc_prod_validator.py` gains a final **fuzzy_normalized_search** tier (runs when `bc_customer_no` is null and ref is ≥6 chars). Searches `normalized_document_no`, `normalized_external_ref`, and regex on raw `bc_external_document_no` across `sales_order + posted_sales_invoice + posted_sales_shipment`.
- Diagnostic endpoint reports new `hit_via_fuzzy_normalized` bucket.

### Added — UI BC Match column on Inside Sales Pilot dashboard
- New column in Recent Pilot Documents table with color-coded `bc_entity_type` badge:
  - 🟢 Open SO · 🟡 Posted Inv · 🔵 Shipment · ⚪ no match
- Tier suffix: `~` for fuzzy, `c` for customer-scoped (tooltips on hover).
- Gives reviewers instant visibility into whether a doc matched an open order vs an already-posted invoice — a key pilot-safety signal.

### Added — Low-volume vendor gate
- `document_readiness_service.evaluate_and_persist` now counts prior non-duplicate docs for the vendor. Fewer than 5 → readiness downgrades `ready_auto_*` → `needs_review` with `warning_reason: low_volume_vendor`.
- Prevents first-time / rare vendors from auto-filing before training data exists.

### Added — BOL / Tracking / Carrier extraction on pilot docs
- `_extract_sales_fields` now captures `bol_number`, `tracking_number`, and `carrier` from the main pipeline onto `sales_pilot_extraction`.
- Pilot remains ingest-only — fields are persisted/displayable, NOT written to BC.

### Changed — P1 Phase 2: callers migrated to unified facade
- 8 call sites now import from `services.unified_validation_service` instead of directly:
  - `server.py` — intake readiness, gap-closer, PO retry (3 sites)
  - `server.py :: _run_pilot_enrichment` (done in Phase 1)
  - `routers/readiness.py` — `/evaluate/{doc_id}` + PO retry endpoint
  - `routers/inside_sales_pilot.py` — `/validate/{doc_id}` + re-extract loop
  - `services/inside_sales_pilot_service.py` — polling loop
  - `services/gap_closer_service.py` — re-evaluation loop
- Delegators (`run_bc_prod_validation`, `run_readiness`) are one-liners — zero behavior change.

### Verified
- `testing_agent_v3_fork` iteration 206: **22/22 backend tests passed, 0 issues**.
- Facade imports work, policy registry returns 4 policies with archive fallback.
- All pilot endpoints respond correctly; diagnostic reports new `hit_via_fuzzy_normalized` bucket.
- Low-volume gate (threshold=5) and BOL/tracking code paths verified via introspection.
- Fuzzy normalized tier verified present in `_check_order` with 6-char minimum.

### Deferred with user input required
- **Teams Adaptive Card webhook** — needs Azure AD app + Teams webhook URL + user sign-off on whether "Approve" should bypass the ingest-only pilot constraint.
- **P1 Phase 3 (full server.py policy extraction)** — 1000+ lines of behavioral migration. Needs dedicated session with full regression testing.
- **Evergreen multi-PO container allocation** — needs sample spreadsheet + schema clarification.



## [2026-04-17] P1 Refactor Started — Unified Validation + Policy Modules

### Added
- **`services/unified_validation_service.py`** — single canonical entry point for document validation. Exposes:
  - `validate_document(doc_id, policy_hint=None)` → orchestrates bc_prod + readiness + pilot_readiness per `POLICY_STAGES` table
  - Thin delegators `run_bc_prod_validation`, `run_readiness`, `run_pilot_readiness`
  - `POLICY_STAGES` map declaring which validation stages apply per doc_type
  - `_infer_policy_hint(doc)` auto-detects the right pipeline based on `inside_sales_pilot` + `doc_type`
- **`policies/` package** — pluggable policy modules (architectural review §2.3):
  - `policies/base.py` — `PolicyModule` ABC + `PolicyResult` dataclass
  - `policies/registry.py` — `register_policy`, `get_policy`, `list_policies`; fallback to archive policy
  - `policies/archive.py` — 30-line policy for unknowns / no-op doc types
  - `policies/warehouse.py` — BOL / shipment policy (thin wrapper, readiness-driven)
  - `policies/ap_invoice.py` — AP routing by readiness state
  - `policies/sales_order.py` — Pilot pilot_review enforcement + non-pilot readiness routing
  - All 4 policies auto-register on package import

### Changed
- **`server.py :: _run_pilot_enrichment`** now calls `validate_document(pid, policy_hint="pilot_sales")` instead of importing bc_prod_validator + pilot_readiness_review_service directly (first canary migration; behavior unchanged — same stages run in same order).

### Verified
- Lint clean across all new files.
- Registry correctly maps 14 doc_type strings → 4 policy modules.
- `get_policy("garbage")` falls back to archive (no silent drops).
- Policy `evaluate()` smoke test: pilot sales → `stage=pilot_review` with `hold_for_pilot_review` action (ingest-only constraint preserved).
- Backend starts cleanly with no new errors.

### Next migration steps (scheduled)
- Migrate remaining `validate_document_against_bc` / `evaluate_and_persist` direct callers (~30 sites across server.py, routers/readiness.py, routers/inside_sales_pilot.py) to the unified facade.
- Once call sites are consolidated, extract shared primitives (`field_completeness`, `entity_exists`, `po_match`, `amount_range`, `duplicate_risk`, `extraction_quality`) from the 5 readiness services into `unified_validation_service`.
- Extract doc_type branches from `server.py` (lines 2065-2438, 3333-3634) into policy modules fleshing out real logic (currently thin wrappers).



## [2026-04-17] BC Order Match Rate Restored (P0 Fix)

### Diagnosed
- **Root cause**: Reported 0/222 Order Match was stale data. Earlier `validate-all` runs skipped docs with existing `bc_prod_validation` and didn't use `force=true`, so pre-fix results persisted.
- **Confirmed**: `_check_order` query logic was functionally correct — diagnostic endpoint showed 42.1% live hit rate on the very first probe.

### Added
- `GET /api/inside-sales-pilot/diagnose-order-match` — read-only diagnostic endpoint reporting:
  - `cache_health` — total sales_order records + external-ref coverage
  - `extraction_health` — PO / order number coverage across pilot docs
  - `sample_matches` — per-doc trace of refs_tried, direct cache hits, `_check_order` result
  - `raw_cache_samples` — shape of `bc_external_document_no` values
  - `summary` — hit rate broken down by match method

### Changed
- `_check_order` (in `services/bc_prod_validator.py`) now cascades across 3 BC entity types:
  1. `sales_order` (open, preferred — unchanged behavior for already-matching docs)
  2. `posted_sales_invoice` (catches 6-digit posted order numbers like `109301`, `111092`)
  3. `posted_sales_shipment` (catches shipment / BOL / warehouse refs)
- Customer-scoped fallback extended to the same 3 entity types.
- `match_method` now includes entity-type suffix (e.g., `cache_multi_search:posted_sales_invoice`) for observability.

### Verified (prod VM)
- Post-fix: **58.8%** Order Match hit rate on 50-doc sample (20/34 docs with refs matched)
- 225 pilot docs re-validated with `force=true`, 0 errors, avg overall score = **34**
- Docs files: `/app/DIAGNOSE_ORDER_MATCH.md`, `/app/DEPLOY_ORDER_MATCH_FIX.md`



## [2026-03-25] Learned Dunnage Patterns Feature

### Added
- **Learned Dunnage Patterns** — AI service that learns dunnage/ancillary line associations from historical orders and auto-suggests them during Sales Order review
  - Backend: `order_line_patterns.py` pattern learning service with `get_suggested_lines()` and `learn_patterns_from_history()`
  - Backend: Preflight endpoint injects `suggested` lines with metadata (confidence, frequency, occurrences)
  - Frontend: `PatternSuggestions` component with "Add All" and per-line "Add" buttons
  - Frontend: Sparkle icon visual distinction for pattern-sourced lines in editable table
  - Demo: Batch PO Split seeds Giovanni glass jar dunnage patterns (pallets, tier sheets, top frames)
  - Fixed UOM-aware qty_ratio calculations for M (per 1000) quantities

### Changed
- `CreateBCSalesOrderPanel` wrapped with `forwardRef` for parent access to edited lines
- Pattern-sourced lines separated from PO lines at preflight load time (shown in Suggested Additions panel, not mixed into line table)

### Added — Energy Surcharge / Customer-Level Patterns
- **Customer-level patterns** (trigger_item="*") for items that appear across ALL orders for a customer (not tied to specific products)
- `learn_from_bc_posted_orders()` function: queries BC for posted sales invoices, identifies recurring line items above threshold (default 75% of last 10 orders)
- ENERGY surcharge auto-suggested for Giovanni: Qty 1 EA, Price $497.36 (editable), "seen in 80% of orders"
- Preflight endpoint auto-triggers BC history learning on first encounter
- Demo batch seed includes ENERGY pattern alongside existing dunnage patterns

### Added — Quantity Bounds Checking
- **Statistical bounds checking** (±2σ from historical mean) on PO line quantities
- `check_quantity_bounds()` function compares PO qty against historical stats per item per customer
- Preflight response includes `bounds_check` with `in_bounds` flag and violation details (item, expected range, deviation factor, severity)
- Out-of-bounds: document flagged with `bounds_alert: true`, `workflow_status: bounds_review`, `ready: false`
- Red "Quantity Out of Bounds — Review Required" banner with per-violation CRITICAL/WARNING badges
- "Approve & Submit to BC" button blocked ("Blocked — Qty Review Required")
- Queue shows "Bounds Review" red status and "QTY ALERT" badge
- Validation checklist includes "Quantity bounds check" item
- Demo seed: `qty_history` with mean, std_dev, min, max, sample_count per item


## [2026-03-16] SharePoint Folder Routing Feature

### Added
- **SharePoint Folder Routing Management Page** (`/sharepoint-routing`)
  - Folder tree visualization based on "Temp Folder Structure 9.15.25.docx"
  - Vendor-to-folder mapping CRUD (31 default mappings)
  - Processor assignment management (Andy, Ellie, Meg, Rhonda, Aaron)
  - Interactive test routing tool
  - Re-seed defaults functionality

- **Backend Router** (`/api/sharepoint-routing/*`)
  - Full CRUD for folder rules, vendor mappings, processor assignments
  - Document folder suggestion endpoint
  - Document folder assignment and move-to-SharePoint endpoints
  - Batch suggest and batch move operations
  - Auto-seeding of default configuration on first access

- **Folder Routing Service** (updated `folder_routing_service.py`)
  - Complete routing logic matching the accounting folder structure
  - Priority-based rules: Canpack override -> Credit Memos -> Tooling -> Freight -> S&H -> Standard
  - Vendor pattern matching for Ball, Canpack, Anchor, OI, freight carriers
  - International/domestic routing
  - Warehouse subfolder routing (Assembly, GT's, Ball Orders, UPS Orders, etc.)

- **AI Classification Enhancement**
  - Updated Gemini prompt with SharePoint routing context
  - Added extraction of routing fields: is_international, is_tooling, is_storage_handling, is_credit_memo, is_dunnage, freight_direction
  - Return_Request classification updated for credit memos

- **Document Pipeline Integration**
  - Auto-compute SharePoint folder suggestion after document classification
  - Store `sharepoint_folder_suggested` and `sharepoint_folder_reason` on hub_documents
  - Display folder suggestion in document detail page with breadcrumb path

- **Document Detail "Move to SharePoint" Button**
  - "Get Folder Suggestion" button when no folder suggestion exists
  - "Move to SharePoint" one-click button after folder is suggested
  - Shows folder path breadcrumbs, routing reason, and move timestamp
  - Both buttons integrated directly in the SharePoint card on document detail page

### Fixed
- **P0: Multi-Page PDF Misclassification** - Root cause: entire multi-page PDF was sent to Gemini, causing shipping content from later pages to overwhelm the classification. Fix: extract first page only using pypdf for classification of multi-page PDFs.
- **Regression: Purchase Invoice Line Items Missing in BC** - Root cause: `create_purchase_invoice_from_document` created the PI header but never called `add_purchase_invoice_lines` to add line items. Fix: added `add_purchase_invoice_lines` function to `gpi_integration_service.py` (mirrors `add_sales_order_lines` pattern) and integrated it into the PI creation flow. Lines are now extracted from `extracted_fields.line_items` and sent via `purchaseInvoices({id})/purchaseInvoiceLines` standard BC API. Frontend updated to show lines_added/lines_total/line_errors.

### Dependencies Added
- `pypdf` - For extracting first page of multi-page PDFs

### Test Results
- Backend: 20/20 tests passed (100%)
- Frontend: 12/12 UI tests passed (100%)
- Test report: `/app/test_reports/iteration_123.json`
