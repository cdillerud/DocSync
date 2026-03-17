# GPI Document Hub - Product Requirements Document

## Original Problem Statement
Enterprise document intelligence platform for Gamer Packaging, Inc. (GPI) that automates document classification, routing, approval workflows, and integration with Business Central and SharePoint.

## Core Requirements
1. Document ingestion from email (Microsoft Graph API) and manual upload
2. AI-powered document classification using Gemini
3. Automated approval workflows
4. SharePoint folder routing based on document type, vendor, and order
5. Business Central integration for vendor matching, PI/SO creation
6. Dashboard and analytics for operational visibility

## Architecture
- **Backend**: FastAPI (Python) with MongoDB
- **Frontend**: React with Shadcn/UI components
- **AI**: Gemini via Emergent LLM Key
- **External APIs**: Microsoft Graph, Business Central (read+write), SharePoint

## What's Been Implemented

### Phase 1 - Core Platform (Complete)
- Document ingestion pipeline, AI classification, MongoDB storage
- Dashboard, Document detail pages, BC integration (read-only)
- Vendor intelligence and matching

### Phase 2 - Automation (Complete)
- Stable Vendor engine, Auto-approval, Junk cleanup

### Phase 3 - SharePoint Folder Routing (Complete - Feb 2026)
- 37 rules, 15 top-level folders, vendor mappings, processor assignments
- Document-level folder suggestion, SharePoint file move (demo mode)

### P0 Fixes (Mar 2026)
- **Multi-page PDF Classification**: Extract first page only
- **BC Purchase Invoice Document Link**: Created `create_gpi_document_link` function that POSTs to `gpi/documents/v1.0` API to populate the GPI Documents factbox
- **PI Retry-Lines Delete-Before-Add**: New `delete_purchase_invoice_lines` with per-line client isolation to handle BC connection reuse issues
- **Duplicate _sanitize_lines**: Removed

### File & Clear Feature (Mar 2026)
- **Backend**: `POST /api/documents/{doc_id}/file-and-clear` — one-click suggest folder → move to SharePoint → mark cleared
- **Backend**: `POST /api/documents/bulk-file-and-clear` — bulk version for queue page
- **AI Learning**: `filing_actions` MongoDB collection records doc_type + vendor + folder patterns. After 3+ filings of the same pattern, new documents auto-file without intervention
- **Auto-filing hook**: Added to `on_document_ingested` — checks `filing_actions` for learned patterns before setting NeedsReview
- **Frontend**: "File & Clear" button on Document Detail page (green, in SharePoint card)
- **Frontend**: Bulk "File & Clear" button on Queue page (green, in bulk actions bar)
- **Filing Stats**: `GET /api/documents/filing-actions/stats` — shows learned patterns and auto-file candidates

## Key API Endpoints
- `POST /api/documents/{doc_id}/file-and-clear` — File to SharePoint + mark cleared
- `POST /api/documents/bulk-file-and-clear` — Bulk file & clear
- `GET /api/documents/filing-actions/stats` — Filing pattern stats
- `POST /api/gpi-integration/purchase-invoices/from-document/{doc_id}` — Creates PI in BC with GPI Document Link
- `POST /api/gpi-integration/purchase-invoices/retry-lines/{doc_id}` — Deletes bad lines + adds correct ones
- SharePoint routing endpoints, folder routing rules CRUD

## Database Collections
- `hub_documents`, `document_intelligence_results`, `sharepoint_folder_rules`
- `sharepoint_vendor_mappings`, `sharepoint_processor_assignments`
- `filing_actions` — AI learning for auto-filing patterns

## Mocked Services
- Microsoft Graph API (email ingestion - partial)
- JWT Authentication (Entra ID)
- SharePoint file move (demo mode)

## P0/P1/P2 Backlog
### P1 - Upcoming
- Admin UI for managing item mapping rules

### P2 - Future
- Vendor Inventory Dashboard and Sales module
- Product/BOM module
- Refactor monolithic files (server.py, inventory_ledger.py, InventoryLedgerPage.js)
- Production email service and Entra ID SSO
- Decommission legacy Zetadocs system

## Credentials
- Web UI: admin / admin
