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
- Multi-page PDF Classification: Extract first page only
- BC Purchase Invoice Document Link
- PI Retry-Lines Delete-Before-Add
- Duplicate _sanitize_lines removed

### File & Clear Feature (Mar 2026)
- One-click suggest folder → move to SharePoint → mark cleared
- Bulk version for queue page
- AI learning from filing patterns (auto-file after 3+ same patterns)

### Bug Fix: Stable Vendors Count (Mar 2026)
- Unified threshold logic across all code paths
- Configuration-driven thresholds via stable_vendor_config collection

### Bug Fix: Readiness Contradiction (Mar 2026)
- Short-circuit in evaluate_readiness() for terminal docs
- Live re-evaluation on document detail endpoint

### Classification Learning Loop (Mar 2026)
- User corrections stored and used as few-shot examples in Gemini prompt
- Vendor-type patterns tracked for classification hints
- Accuracy metrics API with confusion matrix
- New document type: Warehouse_Receipt

### Auto PI Creation Pipeline (Mar 2026)
- Automatic Purchase Invoice creation in BC sandbox for AP_Invoice docs
- Context-aware line items (PO/BOL in description for freight)
- Configurable via BC_WRITE_ENABLED flag

### Classification Bootstrap Sweep (Mar 2026)
- POST /api/documents/classification/bootstrap-from-history — mines existing documents
- 3-tier confidence model: manual corrections > high AI confidence > completed docs
- Idempotent — safe to re-run without duplicates
- Background task with status tracking endpoint
- Result: 36 documents bootstrapped, 22 vendor patterns created, 41 total corrections

### Document Type Alignment (Mar 2026)
- Frontend dropdown updated to show all 15 AI classification types
- Types: AP Invoice, AR Invoice, Remittance, Freight Document, Sales Order, Sales PO, Sales Quote, Order Confirmation, Purchase Order, Warehouse Receipt, Inventory Report, Shipping Document, Quality Issue, Return Request, Unknown
- Warehouse_Receipt added to DEFAULT_JOB_TYPES backend config

## Key API Endpoints
- `POST /api/documents/{doc_id}/file-and-clear` — File to SharePoint + mark cleared
- `POST /api/documents/bulk-file-and-clear` — Bulk file & clear
- `GET /api/documents/filing-actions/stats` — Filing pattern stats
- `POST /api/gpi-integration/purchase-invoices/from-document/{doc_id}` — Creates PI in BC
- `GET /api/documents/classification-accuracy` — Classification metrics
- `POST /api/documents/classification/bootstrap-from-history` — Bootstrap learning model
- `GET /api/documents/classification/bootstrap-status` — Bootstrap progress

## Database Collections
- `hub_documents`, `document_intelligence_results`, `sharepoint_folder_rules`
- `sharepoint_vendor_mappings`, `sharepoint_processor_assignments`
- `filing_actions` — AI learning for auto-filing patterns
- `classification_corrections` — User corrections + bootstrap data for few-shot learning
- `vendor_type_patterns` — Vendor → document type associations

## Mocked Services
- Microsoft Graph API (email ingestion - partial)
- JWT Authentication (Entra ID)
- SharePoint file move (demo mode)

## P0/P1/P2 Backlog
### P1 - Upcoming
- Admin UI for managing item mapping rules
- Azure OpenAI integration (user deferred)

### P2 - Future
- Vendor Inventory Dashboard and Sales module
- Product/BOM module
- Refactor monolithic files (server.py, inventory_ledger.py, InventoryLedgerPage.js)
- Production email service and Entra ID SSO
- Decommission legacy Zetadocs system

## Credentials
- Web UI: admin / admin
