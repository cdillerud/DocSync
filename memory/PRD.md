# GPI Document Hub - Product Requirements Document

## Original Problem Statement
Enterprise document intelligence platform for Gamer Packaging, Inc. (GPI) that automates document classification, routing, approval workflows, and integration with Business Central and SharePoint.

## Architecture
- **Backend**: FastAPI (Python) with MongoDB
- **Frontend**: React with Shadcn/UI components
- **AI**: Gemini via Emergent LLM Key + Azure OpenAI fallback
- **External APIs**: Microsoft Graph, Business Central, SharePoint

## Branch Constraint
Only use branch: `conflict_150326_1947`

## Credentials
- Web UI: admin / admin

## Completed Work (This Session — Mar 21 2026)

### P1-A: PO Candidate Extraction from description/filename
- Direct extraction from `description` (0.72), `invoice_description` (0.65), `line_description` (0.65) with PO format pre-validation
- Added to regex scan loop for embedded PO references
- 3 new tests: direct extraction, invoice_description, non-PO text filtering

### P1-B: Square9 stage-counts NameError fix
- Import was already fixed in prior session; added regression test

### P1-C: FastAPI dependency injection fix
- Removed global db/bc_service injection from ap_review.py and spiro.py
- All endpoints now use deps.get_db() and get_bc_service()
- Cleaned up set_dependencies/set_spiro_routes_db stubs and calls from main.py and server.py

### P1-D: Auto-post AP invoices for stable vendors
- Wired check_auto_post_eligibility + stable vendor score (>= 0.85) + bc_link_status == "linked" gate
- Calls auto_create_pi_from_document on success
- Stores auto_posted/auto_post_failed/auto_post_result on document
- Logs activity via create_activity; never blocks pipeline
- 6 tests covering all gate conditions and failure modes

### P1-E: Azure OpenAI fallback classifier
- Created azure_openai_classifier.py with classify_document_with_azure_openai()
- Wired into classify_document_with_ai(): falls back when Gemini confidence < 0.70 or errors
- Config: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_DEPLOYMENT
- Gracefully skips if not configured
- 6 tests covering all fallback paths

### P2-A: Freight GL routing extensions
- Added gl-storage-handling (5260-00) and gl-dropship-international (6115-00) GL accounts
- Added do_not_pay routing flag (no GL posting, DO NOT PAY folder)
- Added freight_issues routing flag (needs_logistics_approval workflow status)
- Added dropship_international combined sub-type detection
- Added storage_handling sub-type detection
- Sub-type-only fallback in _match_gl_account
- 10 new tests

### P2-B: Square9 decommission
- GET /api/square9/migration-status endpoint
- POST /api/admin/square9-cutover endpoint (idempotent)
- Dashboard green banner when square9_active=false
- DEPLOYMENT.md section for mailbox redirection

### P3-A: BC catalog sync for Sales Order line resolution
- get_catalog_health() function for sync staleness reporting
- GET /api/gpi-integration/catalog/health endpoint
- catalog_sync_health in dashboard stats
- 24-hour scheduled background catalog sync
- 7 tests covering health, staleness, item search

### P3-B: Drop-Ship vs Warehouse SO Type Routing (COMPLETED Feb 2026)
- Updated _CLASSIFY_SYSTEM_PROMPT to extract so_type (dropship/warehouse/unknown)
- Added _resolve_so_type() to normalize variants (drop_ship, drop-ship, wh → canonical)
- Added _resolve_so_routing_fields() for conditional BC field mapping:
  - Dropship: ship_to_code, ship_to_name from document; no location_code
  - Warehouse: location_code from doc or BC_DEFAULT_WAREHOUSE_CODE (default "MAIN")
- Extended create_sales_order() service to accept ship_to_code, ship_to_name, location_code
- Preflight endpoint returns so_type in document_summary and so_routing in mapped_values
- create_sales_order_from_document stores so_type and so_routing in audit and bc_sales_order
- Dropship auto-approve: _auto_approve_dropship_so() advances workflow to approved
- 38 tests (27 unit + 11 integration) — all passing

### P3-C: Warehouse SO Booked Notifications (COMPLETED Feb 2026)
- Created `services/notification_service.py` with:
  - `send_warehouse_receiving_notice(doc, so_data, dry_run)` — Warehouse Receiving Notice to Logistics
  - `send_so_confirmation_to_customer(doc, so_data, customer_email, dry_run)` — SO Confirmation to Customer
  - `on_warehouse_so_booked(doc, so_data, dry_run)` — orchestrator that calls both
  - `get_notification_config()` / `save_notification_config()` — CRUD for hub_config
  - Content builders: HTML tables with SO number, customer, line items, delivery/ship dates, warehouse location
  - Customer email resolved from: explicit param > extracted_fields.customer_email > spiro_data.email
  - dry_run=True logs content without sending; non-dry-run sends via email_service (Mock provider in dev, MS Graph in prod)
  - Guards: skips when disabled, skips when no recipient configured
- Wired into `create_sales_order_from_document()` in gpi_integration.py: when so_type=warehouse and SO created successfully, calls on_warehouse_so_booked()
- Added `GET/PUT /api/settings/notification-config` endpoints to settings.py for admin config
- Config stored in hub_config collection with _key="notification_config"
- 32 tests — all passing (content builders, dry-run, mock send, config CRUD, API endpoints)

### P4-A: BC Shipment Sync → Inventory Ledger (COMPLETED Feb 2026)
- Added `outbound_shipment` movement type and `bc_shipment` source type to inventory_ledger_service.py
- Implemented `sync_bc_shipments(db, lookback_hours)` in inventory_so_integration.py:
  - Fetches BC Sales Shipment Lines via standard OData v2.0 API (last N hours)
  - For each line: resolves inventory workspace by customer number, creates outbound_shipment movement (negative qty)
  - Idempotency: tracks synced shipments in bc_shipment_sync collection via (documentNo + lineNo) key
  - Skips zero-qty lines, items without numbers, and unknown customers (with error logging)
  - Updates sync status in hub_config (_key="bc_shipment_sync_status")
- Added `POST /api/inventory-ledger/sync-bc-shipments` for manual trigger
- Added `GET /api/inventory-ledger/sync-status` returning last_sync_at, shipments_processed_today, last_error
- Added 1-hour background scheduler in server.py startup
- Gracefully handles BC credential failures (preview env)
- 17 tests — all passing (sync logic, idempotency, status tracking, endpoints)

### STEP 1: BC Customer + Salesperson Cache Sync & Rep Assignment (COMPLETED Feb 2026)
- Extended ENTITY_CONFIGS in bc_reference_cache_service.py with:
  - "customers": entity_type=customer, syncs id/number/displayName/salespersonCode/email/phoneNumber
  - "salespeople": entity_type=salesperson, syncs code/name/email
- Extended _build_cache_document to carry entity-specific extra fields (salesperson_code, code, name, email, etc.)
- Added sync_entities() method to BCReferenceCacheService for partial entity-type syncs
- Added salesperson_code and code indexes
- Created services/rep_assignment_service.py with:
  - get_rep_for_customer(db, customer_no): override → BC cache → salesperson lookup chain
  - sync_reps_from_bc(db): triggers cache sync for customers + salespeople only
  - list_rep_assignments(db): aggregates customer counts per salesperson
  - override_rep_for_customer(db, customer_no, rep_email, rep_name): stores manual overrides in customer_rep_overrides collection
- 20 tests — all passing

### Bake-Off Feature (v1.6.0 — COMPLETED Mar 21 2026)
- New top-level nav item "Bake-Off" (temporary benchmarking workspace)
- **Run Setup**: Create/list/complete/archive/delete bake-off runs
- **Document Scoring**: Add docs manually or via CSV import, side-by-side Truth/GPI/S9 fields
  - GPI auto-populate from hub_documents collection
  - Auto-scoring with normalization (case-insensitive, PO prefix removal, amount tolerance)
  - Correctness toggles, Needs Review/Final Status dropdowns, Why Wrong tags
  - Manual override tracking (auto-linked vs manually-edited flags)
- **Results Summary**: KPI comparison table (Ingest Rate, Classification/Vendor/Amount/PO/Folder Accuracy, No-Touch Rate, Usable Output Rate), Why Wrong breakdowns, accuracy by doc type/vendor, Key Insights panel
- **Export**: Excel file with Documents + Summary sheets (openpyxl)
- Backend: `/api/bakeoff/*` endpoints (15 endpoints)
- Collections: `bakeoff_runs`, `bakeoff_documents`
- 25 backend tests passing, all frontend UI tests passing
- Reduced page files from 38 to 29 (deleted 9 dead/orphaned pages)
- Navigation consolidated to 7 items (removed standalone Vendors nav)
- UnifiedQueuePage: Added workflow category buttons (All/AP/Sales/Ops) and date range picker (from/to)
- SettingsHubPage: Added Vendor Intelligence and Stable Vendors tabs (absorbed from VendorsHubPage)
- DashboardPage: Added Document Types tab embedding DocTypeDashboardPage
- App.js: Cleaned routes, old /vendors → /config?tab=vendors redirect
- Deleted: APWorkflowsPage, AuditDashboardPage, OperationsWorkflowsPage, PilotDashboardPage, QueuePage, SalesWorkflowsPage, SimulationDashboardPage, WorkflowQueuesPage, VendorsHubPage
- 24 frontend tests — all passing

## P0/P1/P2 Backlog

### Completed
- ✅ PO extraction from subject/description/notes (v2.3)
- ✅ resolve_po signature unification
- ✅ FastAPI dependency injection fix
- ✅ Auto-post AP invoices
- ✅ Azure OpenAI fallback classifier
- ✅ Freight GL routing extensions
- ✅ Square9 decommission
- ✅ BC catalog sync scheduling + health
- ✅ Drop-Ship vs Warehouse SO type routing
- ✅ Warehouse SO booked notifications (receiving notice + SO confirmation)
- ✅ BC Shipment Sync → Inventory Ledger (outbound_shipment movements)
- ✅ BC Customer + Salesperson Cache Sync & Rep Assignment Service
- ✅ server.py extraction Pass 2 (upload/SharePoint/BC link handlers)
- ✅ **[P4-C] Frontend consolidation** — 38 pages → 8 primary pages (Mar 21 2026)
- ✅ App versioning system with changelog dialog (v1.5.0) (Mar 21 2026)
- ✅ **Bake-Off: GPI Hub vs Square 9 comparison workspace** (v1.6.0) (Mar 21 2026)

### Remaining
- P1: Wire rep assignment into SO creation flow (Step 2)
- P1: Investigate remaining `no_bc_match` failures from 500-doc batch
- P1: Continue server.py extraction (classification, email polling)
- P2: Vendor Inventory Dashboard & Sales module
- P2: Product/BOM module
- P2: Production email service & Entra ID SSO
- P2: Decommission legacy Zetadocs

## Test Coverage
- test_po_resolution.py: 42 tests
- test_po_resolution_api.py: 28 tests
- test_auto_post_wiring.py: 6 tests
- test_azure_fallback.py: 6 tests
- test_freight_gl_routing.py: 29 tests (10 new + 19 pre-existing)
- test_catalog_sync.py: 7 tests
- test_so_type_routing.py: 27 tests
- test_so_type_routing_api.py: 11 tests (created by testing agent)
- test_rep_assignment.py: 20 tests
- test_bc_shipment_sync.py: 17 tests
- test_warehouse_so_notifications.py: 32 tests
- Total passing: 200+ tests
