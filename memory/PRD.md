# GPI Document Hub — PRD

## Original Problem Statement
Build a document intelligence platform for GPI (Gamer Packaging Inc.) that automates document processing, vendor matching, and AP/AR workflows with connections to Microsoft Dynamics 365 Business Central and SharePoint.

## Core Architecture
- **Backend**: FastAPI (Python 3.11) on port 8001
- **Frontend**: React with Shadcn/UI on port 3000
- **Database**: MongoDB
- **AI**: Gemini via Emergent LLM Key
- **External APIs**: Dynamics 365 Business Central (read-only live, writes mocked), Microsoft Graph (mocked), SharePoint

## Key Integrations
- **Dynamics 365 Business Central**: Live read access for vendors, customers, items, purchase orders, sales orders
- **Microsoft Graph API**: Mocked — email ingestion from mailboxes
- **SharePoint**: Document storage and linking
- **Gemini LLM**: Document classification and data extraction
- **rapidfuzz**: Fuzzy string matching for vendor resolution

## User Personas
- **AP Clerk**: Reviews and processes purchase invoices
- **AR Clerk**: Reviews and processes sales orders/invoices
- **Admin**: Configures system settings, manages item mappings, monitors health

## Authentication
- Mock JWT auth (admin/admin). Entra ID SSO planned for production.

## Document Processing Pipeline
1. Ingestion (email, upload, file import)
2. AI Classification & Extraction
3. Reference Intelligence (BC lookup)
4. Vendor Intelligence (resolution, aliases, fuzzy matching)
5. Freight G/L Routing
6. AP Validation
7. Document Routing (auto-clear gate)
8. Document Readiness Engine
9. AR Release Gate
10. Derived State Update
11. Queue Routing

## Key DB Collections
- `hub_documents` — Main document store with all processing results
- `vendor_aliases` — Learned vendor name variations
- `vendor_resolution_rejections` — Negative feedback for fuzzy matching
- `hub_config` — System configuration

## Completed Features
See CHANGELOG.md for full history.

### Latest (March 16, 2026)
- Fixed Vendor KPI `$or` key collision bug in dashboard (P0)
- Fixed documents stuck in "captured" workflow_status — intake pipeline now sets workflow_status properly
- Added `/api/workflow-fix/run` batch endpoint to fix existing stuck docs on production
- Fixed Document Queue: type filter, status filter, tab counts, dynamic dropdowns
- Vendor matching remediation complete (auto-resolve, fuzzy candidates, reprocessing)
- **Dashboard Readiness Summary Card** — Shows document readiness status distribution with counts, confidence scores, top blockers and warnings
- **Config Service Extraction** — Centralized config_service.py module, decoupling settings.py/vendor_matching.py/mailbox_sources.py from server.py
- **AR Release Gate (Prepay & Terms Approval)** — Evaluates sales documents for customer resolution, prepay holds, credit limits, payment terms, and ship-to validation. Includes manual override workflow.

## Tech Stack
- FastAPI, Motor (async MongoDB), Pydantic
- React 18, Shadcn/UI, Tailwind CSS, Lucide icons
- rapidfuzz, APScheduler, httpx
- emergentintegrations (Gemini LLM)

## Mocked Services
- Email ingestion (Microsoft Graph)
- BC write operations
- JWT Authentication (Entra ID)
