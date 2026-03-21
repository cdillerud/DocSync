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

### Remaining
- P0: server.py monolith refactor (partially done — services extracted but ~7 functions still imported from server.py)
- P1: Investigate remaining `no_bc_match` failures from 500-doc batch
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
- Total passing: 130+ tests
