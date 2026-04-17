# GPI Document Hub - Changelog

## [2026-04-17] Round 5 — Filename-Aware Customer Suggestion

### Problem
Brokers (like Gamer Packaging) email inventory reports for their downstream customers. Files like `Gamer Inventory Summary - Water Barons.xlsx` were being auto-suggested as the **sender** (Gamer) instead of the **actual inventory owner** (Water Barons) named in the filename.

### Fixed — 3-tier suggestion cascade in `suggest_customer_workspace`
1. **Filename suffix pattern**: `... - <Customer>.xlsx` → extracts `<Customer>` → matches against registered workspaces (name or code, bidirectional prefix match).
2. **Filename prefix pattern**: `<Customer>. <Vendor> ...xlsx` or `<Customer> <Vendor> ...` where `<Vendor>` ∈ known broker tokens (gamer, pretium, mrp, ompi, ball, lagersmith). Extracts tokens BEFORE the vendor marker.
3. **Sender domain** (priority 3, previous default): used only when filename parsing yields no match.

### Added helpers
- `_resolve_customer_text(text, customers)` — normalized bidirectional match (strips punctuation, case-insensitive, ≥3 char minimum, prefers exact/prefix over substring).

### Added endpoint & UI
- `POST /api/inventory-xls/staging/re-suggest-customers?only_unassigned=false` — re-runs the new logic on existing `pending_review` staging rows. Returns `{updated, total_pending, changed: [{staging_id, filename, new_customer}]}`.
- New UI button **"Re-suggest Customers"** (violet, `Sparkles` icon) in `/inventory/imports` header. One click re-resolves all pending stagings to their correct customer via filename parsing.

### Verified
- Live E2E on 6 test patterns:
  - `Gamer Inventory Summary - Water Barons.xlsx` → **Water Barons** ✅
  - `Ryl Co Inventory vs Ryl Co Needs.xlsx` → **Ryl Co** ✅
  - `Ryl Co. Gamer Can Forecast.xlsx` (broker pattern) → **Ryl Co** (not Gamer) ✅
  - `Coloplast On Hold Orders.xlsx` → **Coloplast** ✅
  - `Gamer Can Forecast.xlsx` (no downstream) → **Gamer** (fallback to sender) ✅
  - `open_orders_report_17-APR-26.xlsx` → Pretium (via sender when no filename hint) ✅



## [2026-04-17] Round 4 — Description Fallback + Manual Mapping Editor

### Bug fix: "0 rows" on Ryl Co Inventory files
- **Root cause**: Spreadsheets like `Ryl Co Inventory vs Ryl Co Needs 4.17.26.xlsx` have a `Description` column but no dedicated SKU/Item column. Mapper tagged Description→item_description, then every row failed with "missing item".
- **Fix** (`inventory_xls_parser.py`):
  - If `item` is unmapped but `item_description` IS mapped, `normalize_rows` falls back to using description as the item identifier (legitimate for inventory summaries).
  - Heuristic mapper no longer reports `missing_required: item` when description is mapped.
  - Item string capped at 120 chars to keep ledger clean.

### Bug fix: `\binventory\b` missing underscored filenames
- Changed to `(^|[\s_\-.])inventory($|[\s_\-.])` so `Ryl_Co_Inventory.xlsx` matches.

### Added: Manual column-map editor in UI
- `pages/InventoryImportsPage.js` — side-drawer now has an **Edit** button next to the column map. Opens dropdowns for every canonical field with options from the staged headers.
- **Save Mapping** calls `POST /api/inventory-xls/staging/{id}/update` with the new mapping, THEN automatically calls `POST /api/inventory-xls/staging/{id}/re-normalize` to re-run row normalization against the new map — no re-upload needed.

### Added: `POST /api/inventory-xls/staging/{id}/re-normalize`
- Recovers original file bytes from `hub_documents` (via `source_doc_id` or file_hash match), re-parses, and re-runs `normalize_rows` with the current column_map. Returns parsed/error counts.

### Fixed: Approval UX for 0-row staging
- UI blocks Approve when `row_count == 0` with explanatory message pointing user to fix the column map.
- Backend approval errors now surface the first error's actual text instead of "undefined".

### Verified
- Live: `Ryl_Co_Inventory_test.xlsx` with only Description + Available columns → staged with 3/3 rows, item populated from description.
- Manual editor UI: dropdowns rendered, Save Mapping triggers re-normalize automatically.
- Classification fix: filename with underscores now matches correctly.



## [2026-04-17] Round 3 — Learning-Backed Automation + Drift Alarm

### Added — Auto-approve gate
- `services/inventory_xls_staging_service.py` — `_should_auto_approve(staging_doc)` checks: assigned_customer ≠ null + rows present + column_map.source=="learned" + confidence ≥ 0.95 + learned `approval_count ≥ 3`. When all true, `stage_import` immediately calls `approve_staging` with `approved_by="auto:learned-mapping"`.
- `services/inventory_xls_parser.py` — learned confidence formula updated to `min(0.99, 0.80 + 0.05 * approval_count)`. Thus 1→0.85, 2→0.90, 3→0.95 (auto threshold), 4→0.99.
- Response shape now includes `auto_applied: bool` on `/ingest`; staging record carries `auto_approved: true` flag.

### Added — Ingest-time XLS side-channel in pilot enrichment
- `server.py :: _maybe_stage_inventory_xls(doc_id)` is called from `_run_pilot_enrichment` after BC validation + Spiro + SO rules. For every pilot-ingested `.xlsx/.xls/.csv`, runs the classifier → if inventory, auto-stages via `stage_import` (which may auto-approve per the gate above). Marks source doc with `inventory_xls_backfilled=true` to prevent re-runs.

### Added — Bulk backfill endpoint
- `POST /api/inventory-xls/backfill-pilot-docs?dry_run=true|false&limit=N` — scans all pilot-ingested XLS/CSV docs in `hub_documents` and either reports (dry_run) or stages them. Idempotent via `inventory_xls_backfilled` marker. Returns per-doc trace + classification breakdown.

### Added — Cache Drift Alarm (frontend)
- `InsideSalesPilotPage.js :: MatchTierDonut` now renders an amber alarm banner when matched ≥ 10 AND (`exact/matched < 0.80` OR `fuzzy/matched > 0.10`). Turns the donut from a passive metric into an active safety signal for extraction or BC-cache drift.

### Added — Inventory Imports sidebar nav + backfill UI
- `components/Layout.js` — new "Inventory Imports" sidebar entry (FileSpreadsheet icon).
- `pages/InventoryImportsPage.js` — "Scan Pilot XLS" (dry run) + "Backfill Pilot XLS" buttons with a rich result card showing scanned / inventory / staged / already_staged / skipped / errors + by-classification breakdown.

### Fixed — Customer auto-suggest prefix match
- `suggest_customer_workspace` — bidirectional prefix match. Previous regex failed when the sender domain was LONGER than the customer code (e.g. `gamerpackaging` sender, `gamer` code). Now tests both `code.startsWith(hint)` AND `hint.startsWith(code)` with 3-char minimum code length to avoid false positives.

### Verified
- `testing_agent_v3_fork` iteration 208: **37/37 tests passed (17 new + 20 regression), 0 issues.**
- Live E2E: 3 human approvals of same `(domain, header_hash)` → 4th file from same domain **auto-applied in one shot** with `created_by: auto:learned-mapping`.
- Docs: `/app/BACKFILL_PILOT_XLS.md`, `/app/DEPLOY_INVENTORY_XLS.md`.



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
