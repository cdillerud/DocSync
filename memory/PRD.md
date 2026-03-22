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

## Completed Work

### P1-A: PO Candidate Extraction from description/filename
- Direct extraction from `description`, `invoice_description`, `line_description` with PO format pre-validation
- Added to regex scan loop for embedded PO references

### P1-B: Square9 stage-counts NameError fix
- Import fix + regression test

### P1-C: FastAPI dependency injection fix
- Removed global db/bc_service injection from ap_review.py and spiro.py

### P1-D: Auto-post AP invoices for stable vendors
- Wired check_auto_post_eligibility + stable vendor score gate + bc_link_status gate

### P1-E: Azure OpenAI fallback classifier
- Created azure_openai_classifier.py, falls back when Gemini confidence < 0.70

### P2-A: Freight GL routing extensions
- Added gl-storage-handling, gl-dropship-international GL accounts, do_not_pay routing

### P2-B: Square9 decommission
- Migration status + cutover endpoints

### P3-A: BC catalog sync for Sales Order line resolution
- Health endpoint, 24-hour background sync

### P3-B: Drop-Ship vs Warehouse SO Type Routing
- _resolve_so_type(), conditional BC field mapping, dropship auto-approve

### P3-C: Warehouse SO Booked Notifications
- send_warehouse_receiving_notice, send_so_confirmation_to_customer

### P4-A: BC Shipment Sync to Inventory Ledger
- outbound_shipment movements, 1-hour background scheduler

### STEP 1: BC Customer + Salesperson Cache Sync & Rep Assignment
- sync_entities(), rep_assignment_service.py

### BC Factbox Document Links (Zetadocs Replacement)
- GET/POST/DELETE document-links endpoints, AL extension spec, migrate-from-zetadocs

### Frontend Consolidation
- Reduced 38 pages to 8 core routing pages

### App Versioning
- v1.6.0 badge with changelog dialog

### Intake Benchmark: GPI Hub vs Square 9
- Run setup, document scoring, auto-population, results summary, Excel export
- 15 API endpoints under /api/intake-benchmark/*

### SharePoint Folder Scan for Intake Benchmark (Mar 22 2026)
- `POST /api/intake-benchmark/runs/{run_id}/scan-sharepoint` — walks S9 output folders on SharePoint
- Graceful Graph API failure handling (falls back to demo mode)
- Demo data generator for preview environment testing
- Frontend "Scan S9 Folders" button on Scoring tab
- Fixed international detection bug ("Not International" false positive)
- Answered Fevisa routing question: GPI routes to `Dropship International Documents/ML179859`

## P0/P1/P2 Backlog

### Remaining
- P1: Wire rep assignment into SO creation flow (Step 2)
- P1: Investigate remaining `no_bc_match` failures from 500-doc batch
- P1: Continue server.py extraction (classification, email polling)
- P2: Vendor Inventory Dashboard & Sales module
- P2: Product/BOM module
- P2: Production email service & Entra ID SSO
- P2: Decommission legacy Zetadocs

## Key API Endpoints
- `GET /api/intake-benchmark/runs`
- `POST /api/intake-benchmark/runs/{id}/auto-populate`
- `POST /api/intake-benchmark/runs/{id}/scan-sharepoint`
- `GET /api/gpi-integration/document-links/{entity}/{doc_no}`
- `POST /api/gpi-integration/document-links/{entity}/{doc_no}/upload`

## Test Coverage
- 200+ backend tests passing across all service modules
- Frontend consolidation tests passing
- Intake Benchmark: 14-document demo scan validated

## Known Issues
- Preview env: Graph API token fails (expected — use DEMO_MODE fallback)
- 19 pre-existing integration tests fail due to missing BASE_URL env var
