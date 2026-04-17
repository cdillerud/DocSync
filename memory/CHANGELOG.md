# GPI Document Hub - Changelog

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
