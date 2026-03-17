# GPI Document Hub - Product Requirements Document

## Original Problem Statement
Enterprise document intelligence platform for Gamer Packaging, Inc. (GPI) that automates document classification, routing, approval workflows, and integration with Business Central and SharePoint.

## Core Requirements
1. Document ingestion from email (Microsoft Graph API) and manual upload
2. AI-powered document classification using Gemini
3. Automated approval workflows
4. SharePoint folder routing based on document type, vendor, and order
5. Business Central integration for vendor matching
6. Dashboard and analytics for operational visibility

## Architecture
- **Backend**: FastAPI (Python) with MongoDB
- **Frontend**: React with Shadcn/UI components
- **AI**: Gemini via Emergent LLM Key
- **External APIs**: Microsoft Graph (mocked), Business Central (read-only), SharePoint (move in demo mode)

## What's Been Implemented

### Phase 1 - Core Platform (Complete)
- Document ingestion pipeline
- AI classification with Gemini
- MongoDB storage (hub_documents, document_intelligence_results)
- Dashboard with stats and charts
- Document detail pages with full metadata
- Business Central integration (read-only)
- Vendor intelligence and matching

### Phase 2 - Automation (Complete)
- Stable Vendor engine with configurable thresholds
- Auto-approval of validated documents (cleared 1,244 backlog)
- Junk document cleanup (cleared 112 items)
- Daily ingestion dashboard card

### Phase 3 - SharePoint Folder Routing (Complete - Feb 2026)
- Folder Tree Management with 37 rules, 15 top-level folders
- Vendor Mappings: 31 vendor-to-folder mappings
- Processor Assignments: 6 processor assignments
- Test Routing Tool, AI Classification Enhancement
- Document-Level Folder Suggestion, SharePoint File Move (demo mode)
- Batch Operations

### P0 Fix - Multi-Page PDF Classification (Feb 2026)
- Fixed root cause: extract first page only for classification of multi-page PDFs

### P0 Fix - BC Purchase Invoice Document Link (Mar 2026)
- Root cause: `link_document_to_bc` was called for Sales Orders but never for Purchase Invoices
- Fix: Added Step 3 to `create_purchase_invoice_from_document` that calls `link_document_to_bc` with `bc_entity="purchaseInvoices"` after PI creation
- File content loaded from UPLOAD_DIR, attached to BC via documentAttachments API
- Link status recorded in `bc_purchase_invoice.document_linked` and `document_link_method`

### P0 Fix - PI Retry-Lines Delete-Before-Add (Mar 2026)
- Root cause: `retry-lines` endpoint added new lines without deleting existing bad lines, leading to duplicates
- Fix: New `delete_purchase_invoice_lines` function in `gpi_integration_service.py` fetches and deletes all existing PI lines via standard BC API
- `retry-lines` endpoint now: (1) Deletes existing bad lines, (2) Builds new correct lines, (3) Adds them
- Response includes `lines_deleted` count and `delete_errors`

### Duplicated _sanitize_lines Fix (Mar 2026)
- Fixed duplicated function body in `gpi_integration.py`

## Key Folder Routing Rules
1. All Canpack -> Dropship Not International / Canpack
2. Dunnage return freight -> Canpack / Dunnage return freight
3. Freight issues -> Freight Issues
4. Credit memos -> Vendor Credit Memos / by vendor
5. Tooling -> Tooling Invoices
6. S&H approved -> S&H Invoices Approved Documents / by processor
7. S&H waiting -> S&H Invoices waiting for approval Documents
8. International -> Dropship/Warehouse International Documents
9. Domestic -> Dropship/Warehouse Not International Documents
10. Unknown -> Miscellaneous Documents

## Database Collections
- `hub_documents` - Main document store
- `document_intelligence_results` - AI processing results
- `sharepoint_folder_rules` - Folder structure (auto-seeded)
- `sharepoint_vendor_mappings` - Vendor-to-folder mappings (auto-seeded)
- `sharepoint_processor_assignments` - Who processes what folders (auto-seeded)

## Key API Endpoints
- `POST /api/gpi-integration/purchase-invoices/from-document/{doc_id}` - Creates PI in BC with document linking
- `POST /api/gpi-integration/purchase-invoices/retry-lines/{doc_id}` - Deletes bad lines + adds correct ones
- `POST /api/gpi-integration/sales-orders/from-document/{doc_id}` - Creates SO in BC
- `GET, POST, PUT, DELETE /api/folder-routing-rules` - CRUD for SharePoint folder rules
- SharePoint routing endpoints (see Phase 3)

## Mocked Services
- Microsoft Graph API (email ingestion)
- Business Central write operations (partially - some custom APIs are live)
- JWT Authentication (Entra ID)
- SharePoint file move (demo mode)
- `link_document_to_bc` returns mock when DEMO_MODE=True

## P0/P1/P2 Backlog
### P1 - Upcoming
- Admin UI for managing item mapping rules

### P2 - Future
- Vendor Inventory Dashboard and Sales module
- Product/BOM (Bill of Materials) module
- Refactor monolithic files (server.py, inventory_ledger.py, InventoryLedgerPage.js)
- Production email service and Entra ID SSO
- Decommission legacy Zetadocs system

## Credentials
- Web UI: admin / admin
