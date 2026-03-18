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

### Classification Learning Loop (Complete - Mar 2026)
- User corrections → few-shot examples in Gemini prompt
- Bootstrap sweep: 1,874+ production docs
- Positive confirmations from auto-clear, file-and-clear, BC posting
- Vendor-type patterns for classification hints

### AP Workflow Hardening (Complete - Mar 2026)
- Duplicate PI check via live BC API
- PO amount validation (10% tolerance)
- Freight direction detection (inbound/outbound)

### Dashboard Date Filtering (Complete - Mar 2026)
- ALL metrics filter by selected date (Central Time)
- Date picker with prev/next day and "All Time" button

### Shipping Document Auto-File (Complete - Mar 2026)
- Auto-routes Shipping_Document/Warehouse_Receipt via BC lookup
- Based on warehouse workflow rules (GR=Dropship, GB=Warehouse)

### P0 Data Extraction Fix (Complete - Mar 18 2026)
- **Root Cause**: `process_document()` couldn't find files — `local_file_path` was never stored, but files exist at `UPLOAD_DIR/doc_id`
- **Fix**: Added `UPLOAD_DIR/doc_id` fallback in `document_intelligence_service.py`
- **Fix**: Clear ERROR logging when no file found (eliminates silent failures)
- **Fix**: Refactored `classify_document_with_ai()` — heuristics provide classification, LLM always runs for full extraction (heuristic+LLM merge)
- **Result**: Documents previously with 0 fields now extract 14+ fields
- **Testing**: 16/16 backend tests passed

### Validation & Auto-Clear Hardening (Complete - Mar 18 2026)
- **BC Validation extraction_quality_gate**: Rejects documents with 0 meaningful extracted fields (excludes `_detected_by` metadata)
- **Auto-clear minimum extraction**: Filters out `_detected_by` metadata from field counting — only real data (vendor, bol_number, etc.) counts
- **Readiness terminal shortcut fix**: Completed docs with 0 meaningful fields no longer get 100% readiness — falls through to full evaluation showing BLOCKED status
- **Testing**: 13/13 unit tests passed + frontend verified

## Key API Endpoints
- `POST /api/document-intelligence/process/{doc_id}` — Full intelligence pipeline
- `POST /api/documents/{doc_id}/reprocess?reclassify=true` — Re-classify document
- `GET /api/dashboard/stats?date=YYYY-MM-DD` — Date-filtered dashboard stats
- `GET /api/dashboard/workflow-intelligence?date=YYYY-MM-DD` — Date-filtered intelligence
- `POST /api/documents/classification/bootstrap-from-history` — Bootstrap learning model

## Mocked Services
- Microsoft Graph API (email ingestion - partial)
- JWT Authentication (Entra ID)
- BC API (demo/sandbox mode in preview)

## P1/P2 Backlog
### P1 - Upcoming
- AP Validation card on document detail page
- Azure OpenAI integration alongside Gemini (user deferred)
- Admin UI for managing item mapping rules

### P2 - Future
- Vendor Inventory Dashboard and Sales module
- Product/BOM module
- Refactor monolithic files (server.py, inventory_ledger.py, InventoryLedgerPage.js)
- Redesign Extracted Data and Document Intelligence card layouts
- Production email service and Entra ID SSO
- Decommission legacy Zetadocs system

## Credentials
- Web UI: admin / admin
