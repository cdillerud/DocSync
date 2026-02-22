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

*Last Updated: February 21, 2026*
