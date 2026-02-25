# GPI Document Hub - Product Requirements Document

## Overview

A **Document Intelligence Platform** that replaces Zetadocs-style document linking in Microsoft Dynamics 365 Business Central (BC). The hub orchestrates document ingestion from multiple sources, AI-powered classification, and BC record linking.

---

## Problem Statement

Gamer Packaging, Inc. needs to:
1. Replace legacy Zetadocs document linking system
2. Automate AP invoice processing from email attachments
3. Track sales-related documents (POs, inventory reports, shipping docs)
4. Provide observability into AI classification accuracy before enabling automation
5. Support multiple document sources with unified processing

---

## Simplified Architecture (Refactored Feb 2026)

```
SOURCES                    HUB                      WORKFLOWS
─────────────────────────────────────────────────────────────
                          ┌─────────────┐
Email (Graph API) ───────►│             │──► AP Invoice Workflow
                          │   hub_      │
File Upload ─────────────►│  documents  │──► Sales Order Workflow  
                          │             │
Excel/CSV Import ────────►│  (single    │──► Purchase Order Workflow
                          │   source    │
Legacy Systems ──────────►│   of truth) │──► Other/Triage
                          │             │
                          └─────────────┘

Key Principles:
• ONE collection (hub_documents) for ALL documents
• ONE ingestion pipeline (all sources → classify → route)
• ONE unified queue UI (filter by doc_type/status)
```

---

## Architecture (Original)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EMAIL MAILBOXES                               │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │ AP Invoices      │  │ Sales Orders     │  │ (Add more...)    │  │
│  │ hub-ap-intake@   │  │ hub-sales-intake@│  │                  │  │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘  │
└───────────┼─────────────────────┼─────────────────────┼─────────────┘
            │                     │                     │
            ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    UNIFIED INGESTION PIPELINE                        │
│  • Poll mailboxes via Graph API (read-only, no read status change)  │
│  • Extract attachments                                               │
│  • Deduplicate by message ID + file hash                            │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      AI CLASSIFICATION (Gemini)                      │
│  • Document Type: AP_Invoice, Sales_Order, Inventory_Report, etc.   │
│  • Category: AP, Sales, Operations                                   │
│  • Extract fields: vendor, invoice_number, PO, amount, etc.         │
│  • Confidence score (0-1)                                            │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         SHAREPOINT STORAGE                           │
│  • Upload document to categorized folder                             │
│  • Generate sharing link                                             │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    UNIFIED DOCUMENT QUEUE                            │
│  hub_documents collection (MongoDB)                                  │
│  • Filter by: Status, Category (AP/Sales), Document Type            │
│  • View, review, approve, link to BC                                │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 BUSINESS CENTRAL INTEGRATION                         │
│  • Link documents to existing records (Level 1)                      │
│  • Create draft purchase invoices (Level 2)                         │
│  • Auto-populate line items (Level 3 - future)                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI (Python) |
| Frontend | React + Tailwind CSS + Shadcn/UI |
| Database | MongoDB |
| AI | Gemini 2.5 Flash (via Emergent LLM Key) |
| Email | Microsoft Graph API |
| Storage | SharePoint Online |
| ERP | Dynamics 365 Business Central |
| Deployment | Docker Compose on Azure VM |

---

## Document Types & Categories

### AP Category (Accounts Payable)
| Type | Description | Automation |
|------|-------------|------------|
| AP_Invoice | Vendor invoices we receive | Level 1-2 |
| AR_Invoice | Invoices we send (outgoing) | Level 0 |
| Remittance | Payment confirmations | Level 1 |
| Freight_Document | BOL, shipping docs | Level 1 |
| Warehouse_Document | Receipts, shipments | Level 1 |
| Sales_PO | Customer purchase orders | Level 1 |

### Sales Category
| Type | Description | Automation |
|------|-------------|------------|
| Sales_Order | Customer POs to us | Level 0 |
| Sales_Quote | Price quotes/proposals | Level 0 |
| Order_Confirmation | Order acknowledgments | Level 0 |
| Inventory_Report | Stock/inventory status | Level 0 |
| Shipping_Document | Shipping requests | Level 0 |
| Quality_Issue | Complaints, NCRs | Level 0 |
| Return_Request | RMAs, credit requests | Level 0 |

### Automation Levels
- **Level 0**: Manual only (store and classify)
- **Level 1**: Auto-link to existing BC records
- **Level 2**: Auto-create draft BC documents
- **Level 3**: Auto-populate line items (future)

---

## Current Implementation Status

### Completed Features

#### Core Platform
- [x] FastAPI backend with MongoDB
- [x] React frontend with Shadcn/UI components
- [x] JWT authentication (mock for POC)
- [x] Document upload and storage
- [x] SharePoint integration for file storage

#### Email Ingestion
- [x] Microsoft Graph API integration
- [x] Dynamic mailbox source configuration (add/edit/delete via UI)
- [x] Email polling (configurable interval)
- [x] Attachment extraction and deduplication
- [x] Backfill endpoints for historical emails
- [x] Read-only polling (doesn't change email read status)

#### AI Classification
- [x] Gemini-based document classification
- [x] Support for AP and Sales document types
- [x] Field extraction (vendor, invoice_number, amount, PO, etc.)
- [x] Confidence scoring
- [x] Category assignment (AP/Sales/Unknown)

#### Document Queue
- [x] Unified document queue (all sources in one view)
- [x] Filter by status (Received, Classified, Linked, etc.)
- [x] Filter by category (AP, Sales, All)
- [x] Document detail view with extracted fields
- [x] Manual review and approval workflow

#### Observability & Metrics
- [x] Dashboard with document counts and status breakdown
- [x] Audit Dashboard with Phase 7 extraction quality metrics
- [x] Email polling statistics
- [x] Extraction miss tracking

#### Sales Module (Phase 0)
- [x] Sales-specific data models (customers, items, inventory, orders)
- [x] Sales dashboard with customer selector
- [x] Seed data endpoint for testing
- [x] Sales email ingestion to unified pipeline

#### AP Invoice Workflow Engine (NEW - Feb 22, 2026)
- [x] Pure state machine implementation in `/app/backend/services/workflow_engine.py`
- [x] Workflow statuses: captured, classified, extracted, vendor_pending, bc_validation_pending, bc_validation_failed, data_correction_pending, ready_for_approval, approval_in_progress, approved, rejected, exported, archived
- [x] Workflow history tracking on each document
- [x] Queue APIs for each exception status (`/api/workflows/ap_invoice/*`)
- [x] Mutation APIs for manual corrections (set-vendor, update-fields, override-bc-validation)
- [x] Approval/rejection APIs
- [x] Workflow metrics API
- [x] Frontend AP Workflow page (`/workflow`) with queue tabs and action dialogs
- [x] 43 automated tests (21 unit + 22 API)

#### Multi-Document Type Classification (NEW - Feb 22, 2026)
- [x] Document classification model with `doc_type`, `source_system`, `capture_channel` fields
- [x] 10 document types supported: AP_INVOICE, SALES_INVOICE, PURCHASE_ORDER, SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO, STATEMENT, REMINDER, FINANCE_CHARGE_MEMO, QUALITY_DOC, OTHER
- [x] Type-aware workflow engine with different state machines per doc_type
- [x] Zetadocs set code mapping (ZD00015 -> AP_INVOICE, ZD00007 -> SALES_INVOICE, etc.)
- [x] Square9 workflow name mapping
- [x] Generic queue API: GET /api/workflows/generic/queue?doc_type=X&status=Y
- [x] Status counts by type: GET /api/workflows/generic/status-counts-by-type
- [x] Metrics by type: GET /api/workflows/generic/metrics-by-type
- [x] 60 automated tests (22 workflow engine + 16 generic API + 22 AP queue)

#### Document Type Dashboard (NEW - Feb 22, 2026)
- [x] Backend API: GET /api/dashboard/document-types
- [x] Aggregated metrics per doc_type: total, status_counts, extraction rates, match_methods
- [x] Field extraction rates: vendor, invoice_number, amount, po_number, due_date
- [x] Match method distribution: exact, normalized, alias, fuzzy, manual, none
- [x] Filters for source_system and doc_type
- [x] Frontend dashboard page at `/doc-types` with summary cards and table
- [x] 12 API tests + frontend tests all passing

#### AI-Assisted Document Classification (NEW - Feb 22, 2026)
- [x] Deterministic-first classification pipeline: Zetadocs set codes → Square9 workflows → Mailbox category → Legacy AI extraction
- [x] AI fallback classifier using EMERGENT_LLM_KEY when deterministic rules return OTHER
- [x] Confidence threshold (0.8) for accepting AI classification
- [x] AI classification audit trail (`ai_classification` field) saved only when AI is invoked
- [x] Classification method tracking (`classification_method` field) for debugging/observability
- [x] AI classifier service in `/app/backend/services/ai_classifier.py`
- [x] 29 automated tests (16 unit tests for ai_classifier + 13 integration tests)

#### Multi-Document Type Workflow Engine (NEW - Feb 22, 2026)
- [x] Full state machines for all 10 doc_types in WORKFLOW_DEFINITIONS:
  - AP_INVOICE: Full workflow with vendor matching and BC validation (unchanged)
  - SALES_INVOICE: Standard approval workflow (captured → classified → extracted → ready_for_approval → approved → exported)
  - PURCHASE_ORDER: Workflow with PO validation step (validation_pending, validation_failed states)
  - SALES_CREDIT_MEMO: Invoice linkage workflow (linked_to_invoice state)
  - PURCHASE_CREDIT_MEMO: Invoice linkage workflow (same as SALES_CREDIT_MEMO)
  - STATEMENT: Fast-path review workflow (ready_for_review → reviewed → archived)
  - REMINDER: Simple review workflow
  - FINANCE_CHARGE_MEMO: Simple review workflow
  - QUALITY_DOC: Tagging and review workflow (tagged, review_in_progress states)
  - OTHER: Triage workflow (triage_pending, triage_completed states)
- [x] New workflow events: ON_PO_VALIDATION_STARTED, ON_PO_VALID, ON_PO_INVALID, ON_CREDIT_LINKED_TO_INVOICE, ON_QUALITY_TAGGED, ON_REVIEW_STARTED, ON_TRIAGE_NEEDED, ON_TRIAGE_COMPLETED, ON_MARK_READY_FOR_REVIEW, ON_REVIEWED
- [x] New workflow statuses: VALIDATION_PENDING, VALIDATION_FAILED, LINKED_TO_INVOICE, TAGGED, REVIEW_IN_PROGRESS, TRIAGE_PENDING, TRIAGE_COMPLETED, READY_FOR_REVIEW, REVIEWED
- [x] Generic mutation endpoints:
  - POST /api/workflows/{doc_id}/mark-ready-for-review
  - POST /api/workflows/{doc_id}/mark-reviewed
  - POST /api/workflows/{doc_id}/start-approval
  - POST /api/workflows/{doc_id}/approve (generic)
  - POST /api/workflows/{doc_id}/reject (generic)
  - POST /api/workflows/{doc_id}/complete-triage
  - POST /api/workflows/{doc_id}/link-credit-to-invoice
  - POST /api/workflows/{doc_id}/tag-quality
  - POST /api/workflows/{doc_id}/export
- [x] Dashboard metric: active_queue_count per doc_type
- [x] 45 automated tests (23 unit tests for multi-type workflows + 22 API tests)

#### Classification Dashboard Extension (NEW - Feb 22, 2026)
- [x] `classification_counts` field per doc_type: deterministic, ai, other counts
- [x] `ai_assisted_count` field: docs where AI successfully changed type from OTHER
- [x] `ai_suggested_but_rejected_count` field: docs where AI was invoked but result rejected
- [x] `classification` filter parameter on dashboard API (deterministic, ai, all)
- [x] `classification_totals` in response: sum of classification counts across all doc_types
- [x] CSV export includes classification columns
- [x] Frontend "Classification" column with Det/AI/Other badges
- [x] Frontend classification filter dropdown with counts
- [x] 34 backend tests (12 existing + 22 new classification tests)

#### Excel/CSV File Ingestion for Sales (NEW - Feb 23, 2026)
- [x] Backend file ingestion service (`/app/backend/services/file_ingestion_service.py`)
- [x] Support for Excel (.xlsx, .xls) and CSV (.csv) formats
- [x] Auto-detection of column mappings based on known aliases
- [x] Three ingestion types: sales_order, inventory_position, customer_item
- [x] File parsing with validation for required columns
- [x] Dry-run mode to preview import before committing
- [x] Order grouping: lines with same customer_po grouped into single order
- [x] Import history tracking in `file_ingestion_log` collection
- [x] Frontend page at `/file-import` with 3-step workflow (Upload, Preview, Result)
- [x] Column mapping guide showing required vs optional columns
- [x] Data preview table before import
- [x] 15 backend tests + frontend verification

#### Square9 Workflow Alignment (NEW - Feb 24, 2026)
- [x] Aligned reprocess logic with Square9 workflows
- [x] AP Workflow: validate → store to SharePoint → status "Validated" (no BC attachment)
- [x] Warehouse Workflow: validate → store to SharePoint → status "Validated"
- [x] Removed automatic BC attachment attempts from reprocess
- [x] Updated Shipping_Document job config with required extractions: bol_number, ship_date
- [x] Improved AI extraction for BOL documents (shipper, consignee, carrier, pro_number, etc.)
- [x] Fixed `link_document_to_bc` to accept `bc_entity` parameter for correct endpoint routing
- [x] Improved fuzzy vendor matching with server-side BC API filtering

#### AP Invoice Review Workspace (NEW - Feb 25, 2026)
- [x] Phase 1: AP Review Workspace (Core)
  - [x] PDF Preview panel with zoom controls and fullscreen mode
  - [x] AP Invoice Review panel with editable form fields
  - [x] Vendor search dropdown (BC API integration with mock fallback)
  - [x] PO search dropdown (BC API integration with mock fallback)
  - [x] Save Changes functionality persists edits to document
  - [x] Mark Ready for Post sets review_status to "ready_for_post"
  - [x] Line items management (add/edit/remove)
  - [x] Integration into existing Document Detail page for AP_Invoice documents
- [x] Phase 2: BC Posting Integration
  - [x] BusinessCentralService class (`/app/backend/services/business_central_service.py`)
    - [x] get_vendors() - search vendors with filter
    - [x] get_open_purchase_orders() - search POs by vendor
    - [x] create_purchase_invoice() - create PI in BC
    - [x] Mock mode with sample data for development
    - [x] Real BC API integration ready (OAuth, HTTP client)
  - [x] AP Review API routes (`/app/backend/routes/ap_review.py`)
    - [x] GET /api/ap-review/vendors - vendor search
    - [x] GET /api/ap-review/purchase-orders - PO search
    - [x] PUT /api/ap-review/documents/{id} - save AP review
    - [x] POST /api/ap-review/documents/{id}/mark-ready - mark ready for post
    - [x] POST /api/ap-review/documents/{id}/post-to-bc - post to BC
    - [x] GET /api/ap-review/documents/{id}/bc-status - get posting status
  - [x] Document model extensions: vendor_id, vendor_name_resolved, review_status, bc_posting_status, bc_document_id, bc_posting_error
  - [x] GET /api/documents/{id}/file endpoint for PDF preview

#### Architecture Refactor (IN PROGRESS - Feb 24, 2026)
**Goal:** Simplify over-engineered architecture into clean, maintainable system.

**Frontend Refactor (COMPLETED):**
- [x] Reduced navigation from 13 items to 6 items
- [x] Created `UnifiedQueuePage.js` - single queue for all document types
- [x] Removed redundant pages: APWorkflowsPage, SalesWorkflowsPage, OperationsWorkflowsPage, WorkflowQueuesPage, PilotDashboardPage, SimulationDashboardPage, DocTypeDashboardPage, AuditDashboardPage, SalesDashboardPage
- [x] Simplified navigation: Dashboard, Upload, Document Queue, File Import, Email Config, Settings

**Backend Refactor (PREPARED, NOT ACTIVATED):**
- [x] Created modular route files in `/app/backend/routes/`:
  - `documents.py` - Document CRUD operations
  - `ingestion.py` - Unified ingestion from all sources
  - `workflows.py` - Workflow transitions and queues
  - `dashboard.py` - Stats and metrics
  - `config.py` - Settings and mailbox sources
- [x] Created `server_new.py` - Simplified entry point (~200 lines vs 12K)
- [ ] Switch from server.py to server_new.py (requires testing)
- [ ] Remove sales_module.py (integrate into main)
- [ ] Database collection cleanup


### In Progress / Shadow Mode
- [x] AP automatic workflow trigger (VERIFIED WORKING)
- [ ] BC record linking (manual only currently)
- [ ] BC draft creation (disabled)

### Pending / Future
- [ ] Phase 8: Controlled vendor enablement (P2)
- [ ] "Stable Vendor" metric based on extraction consistency and volume (P2)
- [ ] Vendor threshold overrides per-vendor
- [ ] Entra ID SSO (replace mock auth)
- [ ] Transaction automation (Level 3)
- [ ] Zetadocs decommissioning plan

---

## Key API Endpoints

### Documents
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/documents | List documents (filter by status, category, type) |
| GET | /api/documents/{id} | Get document details |
| POST | /api/documents/upload | Manual document upload |
| POST | /api/documents/{id}/link | Link to BC record |
| DELETE | /api/documents/{id} | Delete document |

### Mailbox Sources
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/settings/mailbox-sources | List all mailboxes |
| POST | /api/settings/mailbox-sources | Add new mailbox |
| PUT | /api/settings/mailbox-sources/{id} | Update mailbox |
| DELETE | /api/settings/mailbox-sources/{id} | Delete mailbox |
| POST | /api/settings/mailbox-sources/{id}/test-connection | Test Graph API access |
| POST | /api/settings/mailbox-sources/{id}/poll-now | Manual poll trigger |

### Admin
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/admin/backfill-ap-mailbox | Backfill AP emails |
| POST | /api/admin/backfill-sales-mailbox | Backfill Sales emails |
| POST | /api/admin/migrate-sales-to-unified | Migrate sales_documents to hub_documents |

### Metrics
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/dashboard/stats | Dashboard statistics |
| GET | /api/metrics/extraction-quality | AI extraction quality metrics |
| GET | /api/metrics/extraction-misses | Documents with missing fields |

### File Import (NEW - Feb 23, 2026)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/sales/file-import/parse | Parse Excel/CSV file and return validation |
| POST | /api/sales/file-import/import-orders | Import sales orders (supports dry_run) |
| POST | /api/sales/file-import/import-inventory | Import inventory positions |
| GET | /api/sales/file-import/column-mappings | Get expected columns for ingestion type |
| GET | /api/sales/file-import/history | Get import history log |

### AP Invoice Workflow (NEW - Feb 22, 2026)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/workflows/ap_invoice/status-counts | Get counts by workflow status |
| GET | /api/workflows/ap_invoice/vendor-pending | Documents awaiting vendor match |
| GET | /api/workflows/ap_invoice/bc-validation-pending | Documents in BC validation |
| GET | /api/workflows/ap_invoice/bc-validation-failed | Documents that failed BC validation |
| GET | /api/workflows/ap_invoice/data-correction-pending | Documents needing data correction |
| GET | /api/workflows/ap_invoice/ready-for-approval | Documents ready for approval |
| GET | /api/workflows/ap_invoice/metrics | Workflow metrics (daily counts) |
| POST | /api/workflows/ap_invoice/{id}/set-vendor | Manually set vendor for document |
| POST | /api/workflows/ap_invoice/{id}/update-fields | Update extracted fields |
| POST | /api/workflows/ap_invoice/{id}/override-bc-validation | Override validation failure |
| POST | /api/workflows/ap_invoice/{id}/start-approval | Start approval process |
| POST | /api/workflows/ap_invoice/{id}/approve | Approve document |
| POST | /api/workflows/ap_invoice/{id}/reject | Reject document |

### Generic Multi-Type Workflow (NEW - Feb 22, 2026)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/workflows/generic/queue | Generic queue - requires doc_type param, optional status |
| GET | /api/workflows/generic/status-counts-by-type | Counts grouped by doc_type and workflow_status |
| GET | /api/workflows/generic/metrics-by-type | Metrics per doc_type (extraction rates, confidence) |

### Document Type Dashboard (NEW - Feb 22, 2026)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/dashboard/document-types | Aggregated metrics by doc_type (status, extraction, match methods) |
| GET | /api/dashboard/document-types?source_system=X | Filter by source_system |
| GET | /api/dashboard/document-types?doc_type=X | Filter by specific doc_type |
| GET | /api/dashboard/document-types/export | CSV export of dashboard data |
| GET | /api/dashboard/document-types/export?source_system=X&doc_type=Y | CSV export with filters |

---

## Document Classification Model

### Document Type (doc_type)
| Value | Description | Zetadocs Set | Square9 Workflow |
|-------|-------------|--------------|------------------|
| AP_INVOICE | Vendor invoices we receive | ZD00015 | AP_Invoice |
| SALES_INVOICE | Invoices we send | ZD00007 | Sales Invoice |
| PURCHASE_ORDER | Purchase orders | ZD00002 | Purchase Order |
| SALES_CREDIT_MEMO | Credit memos we issue | ZD00009 | Credit Memo |
| PURCHASE_CREDIT_MEMO | Credit memos we receive | - | - |
| STATEMENT | Account statements | - | Statement |
| REMINDER | Payment reminders | - | Reminder |
| FINANCE_CHARGE_MEMO | Finance charge documents | - | - |
| QUALITY_DOC | Quality documentation | - | - |
| OTHER | Unclassified documents | - | - |

### Source System (source_system)
- SQUARE9: Migrated from Square9
- ZETADOCS: Migrated from Zetadocs
- GPI_HUB_NATIVE: Created in GPI Hub
- MIGRATION: Data migration job

### Capture Channel (capture_channel)
- EMAIL: Email ingestion
- UPLOAD: Manual upload
- API: API integration
- MIGRATION_JOB: Migration process
- ORDER_CONFIRMATION: Order confirmation flow

---

## Database Collections

### Core Collections
| Collection | Description |
|------------|-------------|
| hub_documents | All ingested documents (unified) |
| hub_config | System configuration |
| mailbox_sources | Configured email mailboxes |
| mail_intake_log | Email processing log (deduplication) |
| mail_poll_runs | Polling run statistics |
| job_types | Document type configurations |
| vendor_aliases | Vendor name normalization |
| automation_metrics_daily | Daily automation metrics |

### Sales Module Collections
| Collection | Description |
|------------|-------------|
| sales_documents | Legacy (migrate to hub_documents) |
| sales_customers | Customer master data |
| sales_items | Item catalog |
| sales_inventory_positions | Inventory levels |
| sales_open_order_headers | Open sales orders |

---

## Deployment

### Production (User's VM)
- Location: `/opt/gpi-hub`
- Docker Compose with backend, frontend, MongoDB containers
- Environment variables in `/opt/gpi-hub/backend/.env`

### Key Environment Variables
```
MONGO_URL=mongodb://...
DB_NAME=gpi_hub
EMAIL_CLIENT_ID=...
EMAIL_CLIENT_SECRET=...
EMAIL_TENANT_ID=...
SHAREPOINT_SITE_ID=...
BC_BASE_URL=...
EMERGENT_LLM_KEY=...
```

### Deployment Commands
```bash
cd /opt/gpi-hub
git pull origin main
sudo docker compose build backend frontend
sudo docker compose up -d
```

---

## Current Operating Mode: Shadow Mode

The system is in **observation mode**:
- ✅ Ingesting documents automatically from configured mailboxes
- ✅ AI classifying all documents
- ✅ Storing in SharePoint
- ✅ Logging metrics for analysis
- ❌ NOT auto-linking to BC (manual only)
- ❌ NOT auto-creating BC records

**Purpose**: Validate AI classification accuracy before enabling automation.

---

## Configured Mailboxes

| Name | Email | Category | Status |
|------|-------|----------|--------|
| AP Invoices | hub-ap-intake@gamerpackaging.com | AP | Active |
| Sales Orders | hub-sales-intake@gamerpackaging.com | Sales | Active |

---

## Document Counts (As of Feb 21, 2026)

| Source | Count | Location |
|--------|-------|----------|
| AP Documents | ~83 | hub_documents |
| Sales Documents | ~129 | sales_documents (needs migration) |

**To migrate Sales to unified collection:**
```bash
sudo docker exec gpi-backend curl -s -X POST "http://localhost:8001/api/admin/migrate-sales-to-unified"
```

---

## Next Steps

### Immediate
1. Deploy latest code to VM
2. Run migration to unify sales documents
3. Verify all documents appear in Document Queue with correct categories

### Short-term
1. Monitor AI classification accuracy via Audit Dashboard
2. Identify "stable vendors" with consistent extraction
3. Review and fix any misclassifications

### Medium-term (Phase 8)
1. Enable Level 1 automation for stable AP vendors
2. Enable Level 2 (draft creation) for highest-confidence vendors
3. Implement vendor-specific threshold overrides

### Long-term
1. Entra ID SSO integration
2. Level 3 automation (line item population)
3. Zetadocs decommissioning

---

## File Structure

```
/app/
├── backend/
│   ├── server.py           # Main API (monolith - needs refactoring)
│   ├── sales_module.py     # Sales-specific logic
│   ├── services/
│   │   ├── workflow_engine.py
│   │   ├── ai_classifier.py
│   │   ├── bc_sandbox_service.py      # BC read-only integration
│   │   ├── bc_simulation_service.py   # BC write simulation
│   │   ├── simulation_metrics_service.py
│   │   ├── file_ingestion_service.py  # Excel/CSV file import
│   │   ├── email_service.py
│   │   └── pilot_summary.py
│   ├── requirements.txt
│   └── .env
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── DashboardPage.js
│   │   │   ├── QueuePage.js           # Unified document queue
│   │   │   ├── EmailParserPage.js     # Mailbox configuration
│   │   │   ├── AuditDashboardPage.js  # Metrics & observability
│   │   │   ├── SalesDashboardPage.js  # Sales inventory view
│   │   │   ├── FileImportPage.js      # Excel/CSV file import (NEW)
│   │   │   ├── SimulationDashboardPage.js
│   │   │   ├── PilotDashboardPage.js
│   │   │   └── ...
│   │   ├── components/ui/    # Shadcn components
│   │   └── lib/api.js        # API client
│   └── package.json
├── docker-compose.yml
└── memory/
    └── PRD.md               # This file
```

---

## Known Issues

1. **AP workflow trigger** - Automatic workflow may not be triggering on ingestion (needs verification)
2. **AI misclassification** - Some AP vs AR invoice confusion (prompt hardening needed)
3. **Re-submit button** - Document re-classification not working as expected

---

## Contact & Support

- **Platform**: Emergent Agent
- **User VM**: Azure VM at `/opt/gpi-hub`
- **Git**: Save to Github via Emergent chat

---

## Legacy Document Migration (Completed - February 22, 2026)

### Overview
A fully tested migration module for importing historical documents from Square9 and Zetadocs into GPI Hub.

### Features
- **Dry Run Mode**: Preview and validate migration without writing to database
- **Real Mode**: Actually migrate documents with duplicate detection
- **Document Classification**: Automatic classification using Zetadocs set codes, Square9 workflow names, or field inference
- **Workflow Initialization**: Sets appropriate workflow states based on legacy status flags (is_paid, is_posted, is_exported, etc.)

### API Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/migration/run | Execute migration (dry_run or real mode) |
| GET | /api/migration/preview | Preview documents before migration |
| GET | /api/migration/stats | Get statistics about migrated documents |
| GET | /api/migration/supported-types | List supported doc types and mappings |
| POST | /api/migration/generate-sample | Generate sample migration JSON file |

### Test Coverage
- **71 automated tests** covering:
  - Unit tests for sources, workflow initialization, transformation
  - Async integration tests for MigrationJob.run()
  - API integration tests for all migration endpoints
  - End-to-end workflow tests

### Current Migration Stats
- 10 sample documents migrated
- Source systems: SQUARE9 (6), ZETADOCS (4)
- Doc types: AP_INVOICE (3), PURCHASE_ORDER (2), QUALITY_DOC (2), STATEMENT (1), SALES_INVOICE (1), OTHER (1)
- Workflow states: exported (5), approved (2), reviewed (1), tagged (1), triage_pending (1)

---

## AP Workflows UI (Completed - February 22, 2026)

### Overview
A dedicated AP Invoice workflow management page at `/ap-workflows` providing AP users with a focused view of AP_INVOICE documents across all workflow stages.

### Features Implemented
- **Summary Cards**: Total AP Invoices, Active Queue Count, Vendor Extraction Rate, Export Rate
- **Filters**: Vendor search, Source system, Date range, Amount range
- **Queue Tabs**: 7 workflow status tabs (Vendor Pending, BC Validation, Failed, Ready, In Progress, Approved, Exported)
- **Document Table**: Shows vendor, invoice #, amount, date, source, age for each document
- **Detail Panel**: Side panel with document details, validation errors, workflow history timeline
- **Row Actions**: Context-specific actions (Set Vendor, Override Validation, Approve/Reject, Export)

### Reusable Components Created
| Component | Path | Purpose |
|-----------|------|---------|
| WorkflowQueue | `/components/WorkflowQueue.js` | Generic queue component for any doc type |
| DocumentDetailPanel | `/components/DocumentDetailPanel.js` | Document detail side panel |
| workflowConstants | `/lib/workflowConstants.js` | Centralized status and config constants |

### Architectural Pattern (Reusable for Other Doc Types)
The implementation follows a pattern that can be replicated for Sales, Quality, and other doc types:
1. Define status constants in `workflowConstants.js`
2. Create a page that passes `docType` to `<WorkflowQueue>`
3. Define `rowActions` based on status-specific business rules
4. Reuse `DocumentDetailPanel` for consistent UX

### Test Results
- **Testing Agent**: 100% pass rate (9/9 features verified)
- Test report: `/app/test_reports/iteration_18.json`

---

## 14-Day Shadow Pilot Implementation (Completed - February 22, 2026)

### Overview
A comprehensive shadow pilot infrastructure enabling read-only validation of document ingestion across all document types (AP, AR/Sales, Warehouse) without affecting external systems.

### Pilot Configuration
- **Phase**: `shadow_pilot_v1`
- **Duration**: Feb 22 - Mar 8, 2026 (14 days)
- **Feature Flag**: `PILOT_MODE_ENABLED=true`
- **Guards**: Exports blocked, BC validation blocked, external writes blocked

### Backend - New APIs
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/pilot/status | Pilot mode status and configuration |
| GET | /api/pilot/daily-metrics | Daily metrics (counts, classification method, stuck docs) |
| GET | /api/pilot/logs | Audit logs with pagination |
| GET | /api/pilot/accuracy | Accuracy report (corrections, time-in-status distribution) |
| GET | /api/pilot/trend | Daily trend data for charting |

### Backend - Pilot Metadata
All documents ingested during pilot automatically receive:
- `pilot_phase`: "shadow_pilot_v1"
- `pilot_date`: ISO timestamp of ingestion
- `capture_channel`: SHADOW_PILOT_* variants

### Frontend - New Pages
| Route | Page | Description |
|-------|------|-------------|
| /pilot-dashboard | PilotDashboardPage | Summary cards, trend chart, misclassifications, stalls |
| /sales-workflows | SalesWorkflowsPage | Sales invoice workflow observation |
| /operations-workflows | OperationsWorkflowsPage | PO + Quality doc workflow observation |

### Frontend - Reusable Components Updated
- **WorkflowQueue**: Added pilot badge on rows where `pilot_phase != null`
- **workflowConstants.js**: Added SALES, PO, QUALITY workflow statuses and queue configs
- **api.js**: Added 5 pilot API functions

### Test Results
- **Testing Agent**: 100% pass rate (11 features verified)
- **Backend Tests**: 15/15 passed
- **Frontend Tests**: 28/28 UI checks passed
- Test report: `/app/test_reports/iteration_19.json`

### Acceptance Criteria Status
1. ✅ All ingestion sources route documents with correct pilot metadata
2. ✅ Workflows progress through states without error
3. ✅ Pilot dashboard displays accurate counts and trends
4. ✅ AP Workflows UI works with pilot filters
5. ✅ Sales and Operations workflow pages load and show queues
6. ✅ No writes to BC or external systems (guards in place)
7. ✅ Full test coverage for new logic

---

## Daily Pilot Email Notification (Completed - February 22, 2026)

### Overview
An automated daily email notification system that sends pilot summary reports to stakeholders, with both scheduled and manual trigger capabilities.

### Backend Components
| Component | Path | Purpose |
|-----------|------|---------|
| email_service.py | `/backend/services/email_service.py` | Mock email service (stores emails in-memory) |
| pilot_summary.py | `/backend/services/pilot_summary.py` | Generates HTML email body with pilot metrics |
| APScheduler | server.py | Schedules daily job at 7:00 AM EST |

### API Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/pilot/send-daily-summary | Manually trigger daily summary email |
| GET | /api/pilot/email-logs | View history of sent emails |
| GET | /api/pilot/email-config | Get email notification configuration |

### Frontend Implementation
- **"Send Summary Email Now" button** on `/pilot-dashboard` page
- Conditionally rendered (only when pilot mode is active)
- Includes loading state and toast notifications
- Button has `data-testid="send-summary-email-btn"` for testing

### Features
- **Automated Scheduling**: APScheduler runs daily at 7:00 AM EST
- **Manual Trigger**: Admin can send summary on-demand via dashboard button
- **Mock Provider**: Stores emails in-memory list (replace with real provider for production)
- **Rich HTML Content**: Summary includes total docs, accuracy score, AI usage, stuck documents

### Test Results
- **Backend API**: Verified via curl - returns `{"sent": true, "recipients": [...], "subject": "..."}`
- **Frontend**: Screenshot verified - button visible, toast notification works
- Recipients: 3 mock recipients configured

### Future Work
- Replace mock email service with Microsoft Graph API or SendGrid
- Add recipient configuration UI
- Add email template customization

---

## BC Sandbox Service Integration (Completed - February 22, 2026)

### Overview
Read-only Business Central sandbox API integration for vendor, customer, PO, and invoice lookups with pilot-safe guards. All write operations are blocked.

### New Service Module
- **File:** `/app/backend/services/bc_sandbox_service.py`
- **Purpose:** Safe, read-only BC sandbox API access during pilot observation mode

### Configuration
| Variable | Value | Description |
|----------|-------|-------------|
| BC_SANDBOX_CLIENT_ID | 22c4e601-51e8-4305-bd63-d4aa7d19defd | App registration client ID |
| BC_SANDBOX_TENANT_ID | c7b2de14-71d9-4c49-a0b9-2bec103a6fdc | Azure AD tenant ID |
| BC_SANDBOX_ENVIRONMENT | Sandbox | BC environment name |
| DEMO_MODE | true | Using mock data (no BC secret configured) |

### Read-Only Functions
| Function | Description |
|----------|-------------|
| `get_vendor(vendor_number)` | Get vendor by number |
| `search_vendors_by_name(name_fragment)` | Search vendors by name |
| `validate_vendor_exists(vendor_number)` | Check if vendor exists |
| `get_customer(customer_number)` | Get customer by number |
| `get_purchase_order(po_number)` | Get PO by number |
| `get_purchase_invoice(invoice_number)` | Get purchase invoice |
| `get_sales_invoice(invoice_number)` | Get sales invoice |
| `validate_invoice_exists(invoice_number, type)` | Check if invoice exists |

### Validation Functions (Observation Mode)
| Function | Description |
|----------|-------------|
| `validate_ap_invoice_in_bc()` | Full AP invoice validation |
| `validate_sales_invoice_in_bc()` | Sales invoice validation |
| `validate_purchase_order_in_bc()` | PO validation |

### API Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/bc-sandbox/status | Service status and config |
| GET | /api/bc-sandbox/vendors/{number} | Get vendor |
| GET | /api/bc-sandbox/vendors/search/{fragment} | Search vendors |
| GET | /api/bc-sandbox/customers/{number} | Get customer |
| GET | /api/bc-sandbox/purchase-orders/{number} | Get PO |
| GET | /api/bc-sandbox/purchase-invoices/{number} | Get purchase invoice |
| GET | /api/bc-sandbox/sales-invoices/{number} | Get sales invoice |
| POST | /api/bc-sandbox/validate/vendor | Validate vendor exists |
| POST | /api/bc-sandbox/validate/invoice | Validate invoice exists |
| POST | /api/bc-sandbox/validate/ap-invoice | Full AP validation |
| POST | /api/bc-sandbox/validate/sales-invoice | Sales validation |
| POST | /api/bc-sandbox/validate/purchase-order | PO validation |
| POST | /api/bc-sandbox/document/{id}/validate | Validate document against BC |

### Blocked Operations (PilotModeWriteBlockedError)
- `create_vendor`, `update_vendor`, `delete_vendor`
- `create_purchase_invoice`, `post_purchase_invoice`, `update_purchase_invoice`
- `create_sales_invoice`, `post_sales_invoice`

### Workflow Integration
- New workflow events: `ON_BC_LOOKUP_SUCCESS`, `ON_BC_LOOKUP_FAILED`, `ON_BC_LOOKUP_NOT_FOUND`
- New workflow events: `ON_BC_VENDOR_VALIDATED`, `ON_BC_CUSTOMER_VALIDATED`, `ON_BC_PO_VALIDATED`, `ON_BC_INVOICE_VALIDATED`
- `BCValidationHistoryEntry` class for creating workflow history entries

### Test Coverage
- **36 tests** in `/app/backend/tests/test_bc_sandbox_service.py`
- Coverage: All 8 lookup functions, 5 pilot guards, 5 validation functions, workflow integration

### Notes
- Currently using **MOCK DATA** (DEMO_MODE=true, no BC_CLIENT_SECRET)
- To enable real BC API calls: Set `BC_SANDBOX_CLIENT_SECRET` in environment

---

## BC Simulation Service (Completed - February 22, 2026)

### Overview
Phase 2 of Shadow Pilot: Simulates all BC write operations internally without calling real BC APIs. All simulations are deterministic, logged to workflow history, and stored in MongoDB for analysis.

### New Service Module
- **File:** `/app/backend/services/bc_simulation_service.py`
- **Purpose:** Simulated BC write operations for pilot observation mode

### Simulation Functions
| Function | Description |
|----------|-------------|
| `simulate_export_ap_invoice(doc)` | Simulate AP invoice export |
| `simulate_create_purchase_invoice(doc)` | Simulate draft purchase invoice creation |
| `simulate_attach_pdf(doc)` | Simulate PDF attachment to BC record |
| `simulate_sales_invoice_export(doc)` | Simulate sales invoice export |
| `simulate_po_linkage(doc)` | Simulate PO linkage |
| `run_full_export_simulation(doc)` | Run all applicable simulations for a doc |

### New Workflow Events
- `ON_EXPORT_SIMULATED`
- `ON_BC_CREATE_INVOICE_SIMULATED`
- `ON_BC_ATTACHMENT_SIMULATED`
- `ON_BC_LINKAGE_SIMULATED`
- `ON_SIMULATION_SUCCESS`
- `ON_SIMULATION_WOULD_FAIL`

### API Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/pilot/simulation/status | Service status |
| POST | /api/pilot/simulation/document/{id}/run | Run full simulation |
| POST | /api/pilot/simulation/ap-invoice/{id} | Simulate AP export |
| POST | /api/pilot/simulation/sales-invoice/{id} | Simulate Sales export |
| POST | /api/pilot/simulation/po-linkage/{id} | Simulate PO linkage |
| POST | /api/pilot/simulation/attachment/{id} | Simulate PDF attachment |
| GET | /api/pilot/simulation-results | Get simulation results |
| GET | /api/pilot/simulation-summary | Get summary statistics |
| POST | /api/pilot/simulation/batch | Run batch simulation |

### Workflow Integration
- `SimulationHistoryEntry` class for creating workflow history entries
- Results stored in `pilot_simulation_results` MongoDB collection
- `would_succeed_in_production` flag for each simulation

### Test Coverage
- **30 tests** in `/app/backend/tests/test_bc_simulation_service.py`
- **66 total tests** (30 simulation + 36 sandbox)

### Features
- **Deterministic ID Generation:** Same input produces same output
- **Validation Checks:** Each simulation validates prerequisites
- **Failure Tracking:** `failure_reason` explains why simulation would fail
- **No Real BC Writes:** All operations are read-only simulations

---

## Simulation Dashboard (Completed - February 22, 2026)

### Overview
Visual dashboard for analyzing BC simulation results during Phase 2 shadow pilot. Groups documents by success/failure, failure reason, doc_type, and source_system.

### Backend Components

#### New Service Module
- **File:** `/app/backend/services/simulation_metrics_service.py`
- **Class:** `SimulationMetricsService`

#### Metrics Calculated
| Metric | Description |
|--------|-------------|
| total_simulated_docs | Unique documents simulated |
| total_simulations | Total simulation runs |
| success_count / failure_count | Would succeed/fail in production |
| success_rate | Percentage success rate |
| by_doc_type | Breakdown by document type |
| by_failure_reason | Normalized failure reason codes |
| by_source_system | Breakdown by source system |
| by_workflow_status | Breakdown by workflow status |

#### Failure Reason Codes
- VENDOR_NOT_FOUND, CUSTOMER_NOT_FOUND, PO_NOT_FOUND
- MISSING_VENDOR, MISSING_CUSTOMER, MISSING_INVOICE_NUMBER
- MISSING_AMOUNT, MISSING_PO_NUMBER, MISSING_FILE_URL
- MISSING_REQUIRED_FIELDS, VALIDATION_FAILED, OTHER

### New API Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/pilot/simulation/metrics | Global metrics summary |
| GET | /api/pilot/simulation/metrics/failures | Failed simulation details |
| GET | /api/pilot/simulation/metrics/successes | Success simulation details |
| GET | /api/pilot/simulation/metrics/trend | Trend data for charting |
| GET | /api/pilot/simulation/metrics/pending | Documents pending simulation |
| GET | /api/pilot/simulation/failure-reasons | List of failure reason codes |

### Frontend Page
- **File:** `/app/frontend/src/pages/SimulationDashboardPage.js`
- **Route:** `/simulation-dashboard`
- **Navigation:** Added to sidebar with FlaskConical icon

### UI Features
- Summary cards: Total, Success Rate, Would Succeed, Would Fail
- Breakdown cards: By Doc Type, By Failure Reason, By Source System
- Trend chart: Daily success/failure over time
- By Workflow Status breakdown
- Recent Failed Simulations list with retry button
- Documents Pending Simulation with batch run capability
- Filter by days (7/14/30)
- Filter by failure reason

### Testing
- Backend APIs tested via curl
- Frontend visually verified via screenshot

---

## Simulation Dashboard Drill-Down Views (Completed - February 22, 2026)

### Overview
Added clickable drill-down functionality to the Simulation Dashboard, allowing users to view detailed document lists filtered by doc_type, failure_reason, or success status.

### Features Added

#### Clickable Breakdown Cards
- **By Document Type:** Click success (✓) or failure (✗) counts to view filtered documents
- **By Failure Reason:** Click any reason row to see all documents with that failure
- **Recent Failed Simulations:** Click any row to open document detail panel

#### Drill-Down Sheet
- Opens as a side sheet with filtered document list
- Shows document metadata: doc_type, workflow_status, source_system
- For failures: displays failure_reason_code
- For successes: displays simulated_bc_number
- Click any document row to open DocumentDetailPanel

#### Document Detail Panel Integration
- Reuses existing `DocumentDetailPanel` component
- Opens as a secondary sheet for document inspection
- Full document details with workflow history

### Technical Implementation
- Uses Shadcn Sheet components for slide-out panels
- Leverages existing `/api/pilot/simulation/metrics/failures` and `/api/pilot/simulation/metrics/successes` endpoints
- Maintains state for drill-down type, filters, and selected document

### UI Flow
1. User views Simulation Dashboard
2. Clicks on a breakdown card (doc_type success/failure, failure reason)
3. Drill-down sheet opens with filtered document list
4. User clicks on a document row
5. DocumentDetailPanel opens with full document details

---

*Last Updated: February 22, 2026*

---

## Dynamic BC Connection Status Indicator (Completed - February 24, 2026)

### Overview
Replaced static "BC CONNECTED" indicator in the sidebar with a dynamic status that reflects the actual connection state to the Business Central sandbox.

### Implementation
- **File Modified:** `/app/frontend/src/components/Layout.js`
- **API Used:** `GET /api/bc-sandbox/status`

### Status States
| State | Color | Text | Condition |
|-------|-------|------|-----------|
| Loading | Gray | CHECKING... | Initial fetch |
| Live | Green | BC LIVE | demo_mode=false AND has_secret=true |
| Demo | Amber | DEMO MODE | demo_mode=true |
| Offline | Red | BC OFFLINE | API error or unreachable |

### Code Changes
1. Added `useEffect` hook to fetch BC status on component mount
2. Created `bcStatus` state object with `loading`, `connected`, `demoMode`, `environment` properties
3. Conditional rendering based on status state

---

## Backend Modular Router Structure (In Progress - February 24, 2026)

### Overview
Refactoring the monolithic `server.py` (~12,000 lines) into modular router files under `/app/backend/routes/`.

### Router Files Created
| File | Prefix | Purpose | Wired |
|------|--------|---------|-------|
| `auth.py` | /auth | Authentication endpoints | YES |
| `documents.py` | /documents | Document CRUD operations | Pending |
| `workflows.py` | /workflows | Workflow state transitions | Pending |
| `config.py` | /config | System settings, mailboxes | Pending |
| `dashboard.py` | /dashboard | Statistics and metrics | Pending |
| `ingestion.py` | /ingestion | File import endpoints | Pending |

### Migration Strategy
1. Create router file with endpoint definitions
2. Import router in server.py 
3. Keep original endpoints for backward compatibility during migration
4. Test new router endpoints
5. Remove original endpoints after verification

### Current Status
- Auth router created and imported (backward-compatible mode)
- Other routers exist but are not yet wired to main app
- Full migration planned in phases to minimize risk

---

*Last Updated: February 24, 2026*

---

## Square9 Workflow Alignment (Completed - February 24, 2026)

### Overview
Implemented Square9-compatible workflow features to closely mirror the legacy Square9 system while adding improvements.

### Features Implemented

#### 1. Retry Counter System
- **Max Retries**: 4 attempts (configurable, matches Square9)
- **Auto-Escalation**: After 4 retries, documents are escalated to Manual Review (improved over Square9's auto-delete)
- **Reset Capability**: Manual reset of retry counter after intervention

#### 2. Square9 Workflow Stages
17 stages mapped to Square9 workflow diagram:
- Import, Classification, Unclassified
- Validation, Missing PO, Missing Invoice, Missing Vendor, Missing Location, Missing Date
- BC Validation, BC Failed
- Valid (green checkmark), Error Recovery
- Ready for Export, Exported, Deleted, Manual Review

#### 3. New API Endpoints
- `GET /api/documents/{id}/square9-status` - Get Square9 workflow status
- `POST /api/documents/{id}/retry` - Retry document with counter increment
- `POST /api/documents/{id}/reset-retries` - Reset retry counter
- `GET /api/square9/config` - Get workflow configuration
- `GET /api/square9/stage-counts` - Document counts by stage

#### 4. Frontend Components
- **Square9WorkflowTracker**: Shows current stage, retry count, progress bar, retry history
- **Square9StageSummary**: Dashboard widget showing stage distribution

### Files Created/Modified
- `backend/services/square9_workflow.py` (NEW)
- `frontend/src/components/Square9WorkflowTracker.js` (NEW)
- `backend/server.py` (MODIFIED - added Square9 endpoints)
- `frontend/src/pages/DocumentDetailPage.js` (MODIFIED - added tracker)
- `frontend/src/pages/DashboardPage.js` (MODIFIED - added stage summary)

### Configuration
```python
DEFAULT_WORKFLOW_CONFIG = {
    "max_retry_attempts": 4,
    "auto_delete_on_max_retries": False,  # Safety improvement
    "auto_escalate_on_max_retries": True,
    "retry_delay_minutes": 5,
}
```

### Square9 Comparison Document
Created `/app/memory/SQUARE9_COMPARISON.md` documenting alignment status.

---

## Session Update: February 25, 2026

### Completed

#### 1. **BC Purchase Invoice Posting Fix (P0 - CRITICAL)**
- **Issue**: POST to BC purchaseInvoices API was returning 400 Bad Request
- **Root Cause**: Payload used incorrect field name `externalDocumentNumber`
- **Fix**: Changed to correct BC API field name `vendorInvoiceNumber` in `/app/backend/services/business_central_service.py`
- **Tested**: Successfully created Purchase Invoice #72518 in BC Sandbox via `POST /api/ap-review/documents/{id}/post-to-bc`

#### 2. **Document Queue Status Consistency Fix (P1)**
- **Issue**: Document Queue showed stale `workflow_status` (e.g., "Vendor Pending") while Detail Page showed correct status ("Validated")
- **Root Cause**: `reprocess_document` function updated `status` field but not `workflow_status` or `square9_stage`
- **Fix**: Added `workflow_status` and `square9_stage` updates to `reprocess_document` function in `/app/backend/server.py`
- **Tested**: Reprocessed documents now show consistent status across Queue and Detail pages

#### 3. **BC Credentials Configuration**
- Updated `/app/backend/.env` with correct Azure AD credentials:
  - Tenant ID: `c7b2de14-71d9-4c49-a0b9-2bec103a6fdc`
  - Client ID: `6ac62e44-8968-4ad9-b781-434507a5c83a`
- BC Sandbox is now fully functional for vendor search, PO lookup, and invoice posting

### Files Modified
- `/app/backend/services/business_central_service.py` - Fixed `vendorInvoiceNumber` field name
- `/app/backend/server.py` - Added `workflow_status` and `square9_stage` sync in `reprocess_document`
- `/app/backend/.env` - Updated BC/Graph credentials

### API Endpoints Status
| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /api/ap-review/documents/{id}/post-to-bc` | ✅ Working | Creates Purchase Invoice in BC |
| `GET /api/ap-review/vendors` | ✅ Working | Searches vendors in real BC |
| `GET /api/ap-review/purchase-orders` | ✅ Working | Searches open POs in real BC |
| `POST /api/documents/{id}/reprocess` | ✅ Working | Now syncs workflow_status |

---

## Remaining Tasks

### P1 - In Progress
- [ ] Continue backend refactoring (move endpoints from server.py to routers)
- [ ] Add missing schema fields to documents: `bcDocumentId`, `bcPostingStatus`, `bcPostingErrors`, `reviewStatus`

### P2 - Upcoming
- [ ] Outbound Document Delivery module (email posted sales invoices)
- [ ] "Stable Vendor" metric implementation
- [ ] Fuzzy matching improvements

### Future/Backlog
- [ ] Replace mock email service with real provider
- [ ] Multi-step approval routing
- [ ] Entra ID SSO integration
- [ ] Automated Purchase Invoice line items in BC

---

*Last Updated: February 25, 2026*

---

## Session Update 2: February 25, 2026 - SharePoint Fix

### Completed

#### SharePoint Upload Fix
- **Issue**: SharePoint upload failed with "Invalid hostname for this tenancy" (HTTP 400)
- **Root Cause**: 
  1. Wrong hostname: `gamerpackaging.sharepoint.com` → should be `gamerpackaging1.sharepoint.com`
  2. Wrong site path: `/sites/GPI-DocumentHub` → should be `/sites/GPI-DocumentHub-Test`
  3. Missing trailing colon in Graph API URL format
- **Fixes Applied**:
  1. Updated `/app/backend/.env` with correct SharePoint credentials:
     - `SHAREPOINT_SITE_HOSTNAME=gamerpackaging1.sharepoint.com`
     - `SHAREPOINT_SITE_PATH=/sites/GPI-DocumentHub-Test`
     - `SHAREPOINT_LIBRARY_NAME=Shared Documents`
     - New Graph app credentials (SharePointBackupApp)
  2. Fixed Graph API URL format to include trailing colon: `sites/{hostname}:{path}:`
  3. Added better error logging for Graph API failures
- **Test Results**:
  - Graph connection test: ✅ "Connected. Site: GPI-DocumentHub-Test"
  - Document upload: ✅ Successfully uploaded to `https://gamerpackaging1.sharepoint.com/sites/GPI-DocumentHub-Test/Shared%20Documents/AP_Invoices/`
  - Sharing link generated: ✅

### Files Modified
- `/app/backend/.env` - Updated SharePoint hostname, path, and credentials
- `/app/backend/server.py` - Fixed Graph API URL format (added trailing colon), improved error logging

---

## Session Update 3: February 25, 2026 - BC Link Writeback

### Completed

#### BC Link Writeback Feature
- **Requirement**: After posting AP invoice to BC, write SharePoint URL back to BC purchase invoice so users can click from BC to open the document
- **Implementation**: 
  1. Added `update_purchase_invoice_link()` method to `BusinessCentralService` that creates a Comment line on the BC purchase invoice containing the SharePoint URL
  2. Added feature flag `BC_WRITEBACK_LINK_ENABLED=true` in `.env`
  3. Updated `post_document_to_bc` endpoint to call writeback after successful posting
  4. Added non-blocking error handling - if writeback fails, BC posting still succeeds
  5. Updated UI to show writeback status (success/failed/skipped)

- **Technical Details**:
  - Method: Creates a "Comment" line type on the purchase invoice with SharePoint URL in description field
  - URL is truncated to 100 chars if needed (BC field limit)
  - Writeback is non-blocking - BC posting remains successful even if writeback fails
  
- **Test Results**:
  - ✅ Posted Invoice #72520 to BC
  - ✅ SharePoint link written to BC invoice as comment line
  - ✅ UI shows "Link written to BC invoice" status

### Files Modified
- `/app/backend/services/business_central_service.py` - Added `update_purchase_invoice_link()` method, `BC_WRITEBACK_LINK_ENABLED` flag
- `/app/backend/routes/ap_review.py` - Updated `post_document_to_bc` to call writeback, extended `PostToBCResponse` model
- `/app/backend/.env` - Added `BC_WRITEBACK_LINK_ENABLED=true`
- `/app/frontend/src/components/APReviewPanel.js` - Added BC link writeback status display in Posted section

### API Changes
| Endpoint | Change |
|----------|--------|
| `POST /api/ap-review/documents/{id}/post-to-bc` | Now includes `sharepoint_url`, `bc_link_writeback_status`, `bc_link_writeback_error` in response |

### Document Schema Additions
- `bc_link_writeback_status`: "success" | "failed" | "skipped"
- `bc_link_writeback_error`: Error message if writeback failed

---

*Last Updated: February 25, 2026*
