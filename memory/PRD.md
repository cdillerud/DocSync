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
- **Folder Tree Management**: Full SharePoint folder structure from "Temp Folder Structure 9.15.25.docx" with 37 rules, 15 top-level folders
- **Vendor Mappings**: 31 vendor-to-folder mappings (Ball, Canpack, OI, Anchor, freight carriers)
- **Processor Assignments**: 6 processor assignments (Andy, Ellie, Meg, Rhonda, Aaron)
- **Test Routing Tool**: Interactive UI to test document routing with any combination of parameters
- **AI Classification Enhancement**: Updated prompt to extract routing fields (is_international, is_tooling, is_storage_handling, is_credit_memo, is_dunnage, freight_direction)
- **Document-Level Folder Suggestion**: Auto-computed on document processing, displayed in document detail
- **SharePoint File Move**: API endpoint to move/copy documents to SharePoint folders (demo mode)
- **Batch Operations**: Batch suggest and batch move endpoints

### P0 Fix - Multi-Page PDF Classification (Feb 2026)
- Fixed root cause: entire multi-page PDF was sent to Gemini, overwhelming the model with shipping content from later pages
- Solution: Extract first page only for classification of multi-page PDFs
- Uses pypdf to extract page 1 to temp file, sends only that to Gemini
- Adds page_count and classified_from_page to classification result

## Key Folder Routing Rules
1. All Canpack → Dropship Not International / Canpack
2. Dunnage return freight → Canpack / Dunnage return freight
3. Freight issues → Freight Issues
4. Credit memos → Vendor Credit Memos / by vendor (Anchor/Ball/OI Dunnage)
5. Tooling → Tooling Invoices
6. S&H approved → S&H Invoices Approved Documents / by processor
7. S&H waiting → S&H Invoices waiting for approval Documents
8. International → Dropship/Warehouse International Documents
9. Domestic → Dropship/Warehouse Not International Documents
10. Unknown → Miscellaneous Documents

## Database Collections
- `hub_documents` - Main document store
- `document_intelligence_results` - AI processing results
- `sharepoint_folder_rules` - Folder structure (auto-seeded)
- `sharepoint_vendor_mappings` - Vendor-to-folder mappings (auto-seeded)
- `sharepoint_processor_assignments` - Who processes what folders (auto-seeded)

## API Endpoints - SharePoint Routing
- `GET /api/sharepoint-routing/folder-tree` - Full folder tree
- `GET /api/sharepoint-routing/folder-rules` - All rules
- `POST /api/sharepoint-routing/folder-rules` - Create rule
- `PUT /api/sharepoint-routing/folder-rules/{key}` - Update rule
- `DELETE /api/sharepoint-routing/folder-rules/{key}` - Delete rule
- `GET /api/sharepoint-routing/vendor-mappings` - All vendor mappings
- `POST /api/sharepoint-routing/vendor-mappings` - Create mapping
- `DELETE /api/sharepoint-routing/vendor-mappings/{pattern}` - Delete mapping
- `GET /api/sharepoint-routing/processor-assignments` - All processor assignments
- `POST /api/sharepoint-routing/processor-assignments` - Create assignment
- `DELETE /api/sharepoint-routing/processor-assignments` - Delete assignment
- `POST /api/sharepoint-routing/suggest-folder` - Suggest folder for criteria
- `GET /api/sharepoint-routing/document/{id}/suggested-folder` - Get suggested folder for doc
- `POST /api/sharepoint-routing/document/{id}/assign-folder` - Manually assign folder
- `POST /api/sharepoint-routing/document/{id}/move-to-sharepoint` - Move doc to SP
- `POST /api/sharepoint-routing/batch-move` - Batch move
- `POST /api/sharepoint-routing/batch-suggest` - Batch suggest
- `POST /api/sharepoint-routing/seed-defaults` - Re-seed defaults

## Mocked Services
- Microsoft Graph API (email ingestion)
- Business Central write operations
- JWT Authentication (Entra ID)
- SharePoint file move (demo mode)

## P0/P1/P2 Backlog
### P1 - Upcoming
- Admin UI for managing item mapping rules

### P2 - Future
- Vendor Inventory Dashboard and Sales module
- Product/BOM (Bill of Materials) module
- Refactor monolithic files (server.py, inventory_ledger)
- Production email service and Entra ID SSO
- Decommission legacy Zetadocs system

## Credentials
- Web UI: admin / admin
