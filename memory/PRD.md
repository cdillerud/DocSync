# GPI Document Hub - PRD

## Original Problem Statement
Build a "GPI Document Hub" test platform that replaces Zetadocs-style document linking in Microsoft Dynamics 365 Business Central by using SharePoint Online as the document repository and a middleware hub to orchestrate ingestion, metadata, approvals, and attachment linking back to BC.

## Architecture
- **Hub & Spoke**: Hub (FastAPI orchestrator) → Spokes (BC Sandbox, SharePoint Online, Exchange Online future)
- **Backend**: FastAPI + MongoDB (Motor async driver)
- **Frontend**: React + Tailwind CSS + Shadcn UI + Recharts
- **Auth**: JWT with hardcoded test user (SSO-ready structure)
- **Microsoft APIs**: Mock/demo mode with real API integration ready

## User Personas
- Enterprise IT Administrators managing BC-SharePoint document flows
- ERP Consultants testing POC for document management
- Document Management Professionals evaluating replacement for Zetadocs

## Core Requirements
- Upload documents (PDF/images) and link to BC Sales Orders
- Store files in SharePoint folders organized by document type
- Create sharing links for one-click document access
- Full audit trail of workflow runs with step-by-step detail
- Dashboard with real-time stats and monitoring
- Document queue with status filtering and management

## What's Been Implemented (Feb 12, 2026)

### Phase 1 - Complete
- [x] Full backend API (FastAPI) with 15+ endpoints
- [x] MongoDB persistence for HubDocument and HubWorkflowRun entities
- [x] Workflow engine: upload_and_link, link_to_bc workflows
- [x] Mock Microsoft services (SharePoint, BC, Entra ID)
- [x] Real API integration code (ready when credentials provided)
- [x] JWT authentication (admin/admin)
- [x] Login page with SSO-ready structure
- [x] Dashboard with stats cards, bar chart, recent/failed workflows
- [x] Upload page with file dropzone, doc type selection, BC order search
- [x] Document Queue with status tabs, search, pagination
- [x] Document Detail with full metadata, SharePoint links, audit trail
- [x] Settings page with connection status for all services
- [x] Dark/Light theme toggle (Swiss Utility design)
- [x] docker-compose.yml for deployment
- [x] .env.example with all config variables
- [x] README.md with setup instructions
- [x] Test script (backend/test_script.py)

### Testing Results
- Backend: 100% (9/9 tests passed)
- Frontend: 100% (11/11 flows tested)

## Prioritized Backlog

### P0 (Blocking for Production)
- [ ] Configure real Entra ID credentials and test live APIs
- [ ] Entra SSO for UI authentication
- [ ] BC extension field for storing SharePoint link URL

### P1 (Important)
- [ ] Exchange Online email ingestion (Phase 2)
- [ ] AI document classification (OCR)
- [ ] File size validation and virus scanning
- [ ] Rate limiting and retry logic for Microsoft APIs

### P2 (Nice to Have)
- [ ] Spiro CRM integration
- [ ] Document sets mapping layer
- [ ] Bulk upload support
- [ ] Export audit logs to CSV
- [ ] WebSocket real-time workflow status updates

## Next Tasks
1. Provide Entra ID credentials to switch from demo to live mode
2. Test with real BC Sandbox and SharePoint site
3. Implement Entra SSO for production UI auth
4. Phase 2: Email ingestion endpoint
