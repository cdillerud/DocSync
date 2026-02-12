# GPI Document Hub - PRD

## Original Problem Statement
Build a "GPI Document Hub" test platform that replaces Zetadocs-style document linking in Microsoft Dynamics 365 Business Central by using SharePoint Online as the document repository and a middleware hub to orchestrate ingestion, metadata, approvals, and attachment linking back to BC.

## Architecture
- **Hub & Spoke**: Hub (FastAPI orchestrator) → Spokes (BC Sandbox, SharePoint Online, Exchange Online future)
- **Backend**: FastAPI + MongoDB (Motor async driver)
- **Frontend**: React + Tailwind CSS + Shadcn UI + Recharts
- **Auth**: JWT with hardcoded test user (SSO-ready structure)
- **Microsoft APIs**: LIVE integration with Graph API (SharePoint) and Business Central API

## User Personas
- Enterprise IT Administrators managing BC-SharePoint document flows
- ERP Consultants testing POC for document management
- Document Management Professionals evaluating replacement for Zetadocs

## Core Requirements
- Upload documents (PDF/images) and link to BC Sales Orders
- Store files in SharePoint folders organized by document type
- Create sharing links for one-click document access
- **Attach files directly to BC Sales Orders via documentAttachments API**
- Full audit trail of workflow runs with step-by-step detail
- Dashboard with real-time stats and monitoring
- Document queue with status filtering and management

## What's Been Implemented (Feb 12, 2026)

### Phase 1 - Complete ✅
- [x] Full backend API (FastAPI) with 15+ endpoints
- [x] MongoDB persistence for HubDocument and HubWorkflowRun entities
- [x] Workflow engine: upload_and_link, link_to_bc workflows
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

### Critical Integration Details
- **BC Environment**: `Sandbox_Autola_10232025`
- **BC Permissions Required**: `SUPER` + `D365 BUS FULL ACCESS` permission sets
- **SharePoint Site**: `gamerpackaging1.sharepoint.com/sites/GPI-DocumentHub-Test`
- **Document Attachment Method**: 
  1. POST to `/companies({id})/salesOrders({orderId})/documentAttachments` (creates metadata)
  2. PATCH to `/documentAttachments({attachmentId})/attachmentContent` (uploads file)

### Testing Results (Latest - Feb 12, 2026)
- Backend: 100% (28/28 tests passed)
- All API endpoints verified working in LIVE mode
- BC attachment workflow verified with real Sales Orders

## Prioritized Backlog

### P0 (Blocking for Production) - COMPLETED ✅
- [x] Configure real Entra ID credentials
- [x] Test live BC and SharePoint APIs  
- [x] Implement BC document attachment via documentAttachments API

### P1 (Important - Upcoming)
- [ ] Write SharePoint URL as a note/comment to BC Sales Order (secondary access method)
- [ ] Complete Document Queue UI - edit metadata and trigger linking
- [ ] Build Audit & Monitoring dashboard with stats and error logs
- [ ] Entra SSO for UI authentication

### P2 (Nice to Have - Future)
- [ ] Exchange Online email ingestion (Phase 2)
- [ ] AI document classification (OCR)
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
| `/api/documents/{id}/resubmit` | POST | Re-run workflow for failed document |
| `/api/documents/{id}/link` | POST | Link existing document to BC |
| `/api/bc/sales-orders` | GET | Query BC sales orders |
| `/api/settings/test-connection` | POST | Test SharePoint/BC connectivity |
| `/api/dashboard/stats` | GET | Dashboard statistics |

## Database Schema (MongoDB)
- **hub_documents**: Document metadata, SharePoint IDs, BC references, status
- **hub_workflow_runs**: Workflow execution logs with step-by-step audit trail
- **hub_config**: Saved credentials (masked secrets, loaded on startup)

## Next Tasks
1. Add SharePoint link as BC note/comment (P1)
2. Complete Document Queue edit functionality (P1)
3. Build Audit Dashboard UI (P1)
4. Implement Entra SSO (P1)
