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

## Core Requirements
- Upload documents (PDF/images) and link to BC Sales Orders
- Store files in SharePoint folders organized by document type
- Create sharing links for one-click document access
- **Attach files directly to BC Sales Orders via documentAttachments API**
- **AI-powered email parsing with document classification**
- **Production-grade validation with configurable automation**
- Full audit trail of workflow runs with step-by-step detail

## What's Been Implemented (Feb 18, 2026)

### Phase 1 - Complete ✅
- [x] Full backend API (FastAPI) with 25+ endpoints
- [x] MongoDB persistence for HubDocument, HubWorkflowRun, HubJobTypes
- [x] LIVE SharePoint integration - file upload + sharing links
- [x] LIVE Business Central integration - document attachments
- [x] Dashboard, Upload, Queue, Document Detail, Settings pages
- [x] Dark/Light theme, Re-submit/Delete functionality

### Phase 2 - Email Parser Agent ✅
- [x] AI Document Classification using Gemini 2.5-flash
- [x] Configurable Job Types with automation levels
- [x] Graph Webhook support for real-time email monitoring
- [x] Email Parser UI with Overview, Job Types, Email Watcher tabs

### Phase 2.1 - Production Hardening ✅ (NEW)
- [x] **Always upload to SharePoint first** - documents preserved even if BC fails
- [x] **Field Normalization** - amounts to float, dates to ISO format
- [x] **Multi-strategy Vendor Matching**:
  - Exact match on Vendor No
  - Exact match on Vendor Name
  - Normalized match (strip Inc, LLC, punctuation)
  - Alias map lookup
  - Fuzzy match with candidates
- [x] **PO Validation Modes**:
  - `PO_REQUIRED` - PO must exist and match
  - `PO_IF_PRESENT` - Validate if extracted (default for AP_Invoice)
  - `PO_NOT_REQUIRED` - Skip PO validation
- [x] **Vendor/Customer Candidates** - top 5 matches with scores for review UI
- [x] **Resolve and Link Endpoint** - one-click resolution from review queue
- [x] **New Document Statuses**:
  - `StoredInSP` - Document in SharePoint, pending BC link

### Job Type Configuration (Production)
| Job Type | Automation | Link Threshold | Create Threshold | PO Mode | Vendor Threshold |
|----------|------------|---------------|-----------------|---------|-----------------|
| AP_Invoice | Auto Link | 85% | 95% | PO_IF_PRESENT | 80% |
| Sales_PO | Auto Link | 80% | 92% | PO_NOT_REQUIRED | 80% |
| AR_Invoice | Manual Only | 90% | 98% | PO_NOT_REQUIRED | 80% |
| Remittance | Auto Link | 75% | 95% | PO_NOT_REQUIRED | 75% |

### Document Status Flow
```
Received → StoredInSP → Classified → LinkedToBC
                    ↘ NeedsReview → [Resolve] → LinkedToBC
```

### Testing Results (Latest - Feb 18, 2026)
- Backend: 100% (32/32 tests passed)
- All API endpoints verified working
- SharePoint-first upload verified
- Field normalization verified
- Vendor candidate matching verified

## Key API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/documents/intake` | POST | Email intake with AI classification + SharePoint upload |
| `/api/documents/{id}/resolve` | POST | Resolve NeedsReview with vendor/customer selection |
| `/api/documents/{id}/classify` | POST | Re-run AI classification |
| `/api/settings/job-types` | GET/PUT | Job type automation configuration |
| `/api/settings/email-watcher` | GET/PUT | Email watcher configuration |

## Prioritized Backlog

### P0 (Blocking for Production) - COMPLETED ✅
- [x] BC document attachment via API
- [x] AI-powered email classification
- [x] Production-grade validation with candidates

### P1 (Important - Upcoming)
- [ ] Review UI improvements - vendor pick list from candidates
- [ ] Audit & Monitoring dashboard with error filtering
- [ ] BC draft purchase invoice creation (automation level 2)
- [ ] Entra SSO for UI authentication

### P2 (Future)
- [ ] Exchange Online email polling (backup to webhooks)
- [ ] Vendor alias configuration UI
- [ ] Bulk upload support
- [ ] Export audit logs to CSV

## Technical Stack
- **Backend**: FastAPI, Pydantic, Motor, httpx, python-dateutil
- **Frontend**: React 18, Tailwind CSS, Shadcn/UI
- **AI**: Gemini 2.5-flash via emergentintegrations library
- **Database**: MongoDB
