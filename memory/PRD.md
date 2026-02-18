# GPI Document Hub - PRD

## Original Problem Statement
Build a "GPI Document Hub" test platform that replaces Zetadocs-style document linking in Microsoft Dynamics 365 Business Central by using SharePoint Online as the document repository and a middleware hub to orchestrate ingestion, metadata, approvals, and attachment linking back to BC.

## Architecture
- **Hub & Spoke**: Hub (FastAPI orchestrator) → Spokes (BC Sandbox, SharePoint Online, Exchange Online)
- **Backend**: FastAPI + MongoDB (Motor async driver)
- **Frontend**: React + Tailwind CSS + Shadcn/UI + Recharts
- **Auth**: JWT with hardcoded test user (SSO-ready structure)
- **Microsoft APIs**: LIVE integration with Graph API (SharePoint, Email) and Business Central API
- **AI Classification**: Gemini 2.5-flash via Emergent LLM Key

## User Personas
- Enterprise IT Administrators managing BC-SharePoint document flows
- AP/AR Clerks processing invoices and purchase orders
- ERP Consultants testing POC for document management
- Document Management Professionals evaluating replacement for Zetadocs

## Core Requirements
- Upload documents (PDF/images) and link to BC Sales Orders
- Store files in SharePoint folders organized by document type
- Create sharing links for one-click document access
- **Attach files directly to BC Sales Orders via documentAttachments API**
- **AI-powered email parsing with document classification**
- **Configurable automation levels per job type**
- Full audit trail of workflow runs with step-by-step detail
- Dashboard with real-time stats and monitoring
- Document queue with status filtering and management

## What's Been Implemented (Feb 18, 2026)

### Phase 1 - Complete ✅
- [x] Full backend API (FastAPI) with 25+ endpoints
- [x] MongoDB persistence for HubDocument, HubWorkflowRun, HubJobTypes
- [x] Workflow engine: upload_and_link, link_to_bc, email_intake workflows
- [x] **LIVE SharePoint integration** - file upload + sharing links
- [x] **LIVE Business Central integration** - sales order queries + document attachments
- [x] BC document attachment via documentAttachments API (POST metadata + PATCH content)
- [x] JWT authentication (admin/admin)
- [x] Login page with SSO-ready structure
- [x] Dashboard with stats cards, bar chart, recent/failed workflows
- [x] Upload page with file dropzone, doc type selection, BC order search
- [x] Document Queue with status tabs, search, pagination
- [x] Document Detail with full metadata, SharePoint links, audit trail
- [x] Settings page with credential management + connection testing
- [x] Dark/Light theme toggle (Swiss Utility design)
- [x] Re-submit failed workflows with one click
- [x] Delete documents from queue

### Phase 2 - Email Parser Agent ✅ (NEW)
- [x] **AI Document Classification** using Gemini 2.5-flash
- [x] **Configurable Job Types** with automation levels:
  - Level 0: Manual Only (store + classify)
  - Level 1: Auto Link (link to existing BC records)
  - Level 2: Auto Create Draft (create draft BC documents)
  - Level 3: Advanced (future: auto-populate lines)
- [x] **Confidence Thresholds** per job type (auto-link, auto-create)
- [x] **BC Validation Engine**:
  - Vendor matching
  - Customer matching
  - PO validation
  - Duplicate invoice checking
- [x] **Decision Matrix** for automation:
  - All validations pass + confidence >= threshold → auto action
  - Validation fails → needs review
  - Confidence too low → needs review
- [x] **Graph Webhook Support** for real-time email notifications
- [x] **Email Watcher Configuration** (mailbox, folders)
- [x] **Email Parser UI** with:
  - Overview tab (stats, recent documents)
  - Job Types tab (configure automation)
  - Email Watcher tab (configure mailbox)

### Job Type Configurations
| Job Type | Automation Level | Auto-Link Threshold | Auto-Create Threshold | PO Validation |
|----------|-----------------|--------------------|-----------------------|---------------|
| AP_Invoice | Auto Link | 85% | 95% | Required |
| Sales_PO | Auto Link | 80% | 92% | No |
| AR_Invoice | Manual Only | 90% | 98% | No |
| Remittance | Auto Link | 75% | 95% | No |

### AI Classification Capabilities
- **Document Types**: AP Invoice, Sales PO, AR Invoice, Remittance
- **Extracted Fields**:
  - AP Invoice: vendor, invoice_number, amount, po_number, due_date
  - Sales PO: customer, po_number, order_date, amount, ship_to
  - AR Invoice: customer, invoice_number, amount, due_date
  - Remittance: vendor, payment_amount, payment_date, invoice_references
- **Model**: Gemini 2.5-flash via Emergent LLM Key

### Testing Results (Latest - Feb 18, 2026)
- Backend: 100% (47/47 tests passed)
- All API endpoints verified working in LIVE mode
- AI classification verified with real Gemini API

## Prioritized Backlog

### P0 (Blocking for Production) - COMPLETED ✅
- [x] Configure real Entra ID credentials
- [x] Test live BC and SharePoint APIs
- [x] Implement BC document attachment via documentAttachments API
- [x] Implement AI-powered email classification

### P1 (Important - Upcoming)
- [ ] Write SharePoint URL as a note/comment to BC Sales Order
- [ ] Complete Document Queue UI - edit metadata and trigger linking
- [ ] Build Audit & Monitoring dashboard with stats and error logs
- [ ] Entra SSO for UI authentication
- [ ] BC draft purchase invoice creation (automation level 2)

### P2 (Nice to Have - Future)
- [ ] Exchange Online email polling (alternative to webhook)
- [ ] File size validation and virus scanning
- [ ] Spiro CRM integration
- [ ] Document sets mapping layer
- [ ] Bulk upload support
- [ ] Export audit logs to CSV
- [ ] WebSocket real-time workflow status updates

## Key API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/documents/upload` | POST | Upload document, store in SharePoint, attach to BC |
| `/api/documents/intake` | POST | Email intake with AI classification |
| `/api/documents/{id}/classify` | POST | Re-run AI classification |
| `/api/documents/{id}/resubmit` | POST | Re-run workflow for failed document |
| `/api/bc/sales-orders` | GET | Query BC sales orders |
| `/api/settings/job-types` | GET/PUT | Job type automation configuration |
| `/api/settings/email-watcher` | GET/PUT | Email watcher configuration |
| `/api/graph/webhook` | POST | Graph notification endpoint |
| `/api/dashboard/email-stats` | GET | Email processing statistics |

## Database Schema (MongoDB)
- **hub_documents**: Document metadata, SharePoint IDs, BC references, AI classification, status
- **hub_workflow_runs**: Workflow execution logs with step-by-step audit trail
- **hub_config**: Saved credentials (masked secrets, loaded on startup)
- **hub_job_types**: Job type automation configurations

## Technical Stack
- **Backend**: FastAPI, Pydantic, Motor (async MongoDB), httpx
- **Frontend**: React 18, Tailwind CSS, Shadcn/UI, Recharts
- **AI**: Gemini 2.5-flash via emergentintegrations library
- **Database**: MongoDB
- **APIs**: Microsoft Graph API, Dynamics 365 BC API v2.0

## Next Tasks
1. Implement SharePoint link as BC note/comment
2. BC draft purchase invoice creation for high-confidence AP Invoices
3. Entra SSO for production authentication
4. Exchange Online email polling as backup to webhooks
