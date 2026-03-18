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

### P0 Fixes (Mar 2026)
- Multi-page PDF Classification, BC PI Document Link, PI Retry-Lines

### File & Clear Feature (Mar 2026)
- One-click suggest folder → move to SharePoint → mark cleared

### Classification Learning Loop (Mar 2026)
- User corrections stored and used as few-shot examples in Gemini prompt
- Bootstrap sweep: mined 1,874 production docs for learning data
- Positive confirmations from: auto-clear, file-and-clear, bulk-file, BC posting, auto-file
- Vendor-type patterns tracked for classification hints

### Auto PI Creation Pipeline (Mar 2026)
- Automatic Purchase Invoice creation in BC sandbox for AP_Invoice docs

### Packing List Classification Fix (Mar 2026)
- New heuristic: filename + text patterns catch packing lists → Shipping_Document
- AI prompt updated with explicit anti-pattern (packing list ≠ Sales_Order)

### Document Type Alignment (Mar 2026)
- Frontend dropdown updated to show all 15 AI classification types
- Queue page fixed: reads document_type (AI) not doc_type (legacy BC field)
- Warehouse_Receipt added to DEFAULT_JOB_TYPES

### Dashboard Date Filtering (Mar 2026)
- ALL dashboard metrics now filter by selected date (Central Time)
- Date picker in header with prev/next day and "All Time" button
- /stats and /workflow-intelligence endpoints accept ?date=YYYY-MM-DD

### Shipping Document Auto-File (Mar 2026)
- New service: shipping_auto_file_service.py
- Triggered on auto-clear for Shipping_Document, Warehouse_Receipt types
- BC lookup for locationCode (GR=Dropship, GB=Warehouse) + InternationalGds
- Auto-routes to correct SharePoint folder based on warehouse workflow rules
- Falls back to heuristics if BC lookup fails (vendor patterns, text indicators)
- Records filing pattern + classification confirmation for AI learning

## Key API Endpoints
- `POST /api/documents/classification/bootstrap-from-history` — Bootstrap learning model
- `GET /api/documents/classification/bootstrap-status` — Bootstrap progress
- `GET /api/dashboard/stats?date=YYYY-MM-DD` — Date-filtered dashboard stats
- `GET /api/dashboard/workflow-intelligence?date=YYYY-MM-DD` — Date-filtered intelligence

## SharePoint Folder Routing (Warehouse Workflow)
| locationCode | InternationalGds | SharePoint Folder |
|---|---|---|
| GR | True | Dropship International Documents |
| GR | False | Dropship Not International Documents |
| GB | True | Warehouse International Documents |
| GB | False | Warehouse Not International Documents |

## Mocked Services
- Microsoft Graph API (email ingestion - partial)
- JWT Authentication (Entra ID)
- SharePoint file move (demo mode in preview)

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
