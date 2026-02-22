# GPI Document Hub - Product Requirements Document

## Overview

A **Document Intelligence Platform** that replaces Zetadocs-style document linking in Microsoft Dynamics 365 Business Central (BC). The hub orchestrates document ingestion from multiple email sources, AI-powered classification, SharePoint storage, and BC record linking.

---

## Problem Statement

Gamer Packaging, Inc. needs to:
1. Replace legacy Zetadocs document linking system
2. Automate AP invoice processing from email attachments
3. Track sales-related documents (POs, inventory reports, shipping docs)
4. Provide observability into AI classification accuracy before enabling automation
5. Support multiple document sources with unified processing

---

## Architecture

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

### In Progress / Shadow Mode
- [x] AP automatic workflow trigger (VERIFIED WORKING)
- [ ] BC record linking (manual only currently)
- [ ] BC draft creation (disabled)

### Pending / Future
- [ ] Phase 8: Controlled vendor enablement
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
│   ├── requirements.txt
│   └── .env
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── DashboardPage.js
│   │   │   ├── QueuePage.js          # Unified document queue
│   │   │   ├── EmailParserPage.js    # Mailbox configuration
│   │   │   ├── AuditDashboardPage.js # Metrics & observability
│   │   │   ├── SalesDashboardPage.js # Sales inventory view
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

*Last Updated: February 22, 2026*
