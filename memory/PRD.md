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

## Classification Pipeline Architecture (Mar 18 2026)
The classification system was refactored from a monolithic function into a 5-stage pipeline with explicit quality gates (`classification_pipeline.py`):

```
Stage 1: PARSE    → Extract text from PDF (pypdf), resolve file path (UPLOAD_DIR/{doc_id} fallback)
Stage 2: CLASSIFY → Heuristic-first (6 patterns), then LLM (Gemini). Heuristic wins type, LLM wins fields.
Stage 3: EXTRACT  → Merge LLM fields + existing fields. Gate: ≥1 meaningful field (excludes _detected_by metadata)
Stage 4: VALIDATE → BC validation with extraction_quality_gate (0 real fields = FAIL)
Stage 5: ROUTE    → Auto-clear / review / block decision + readiness score
```

Each stage returns: `{status, quality_gate_passed, error, duration_ms}`. Pipeline stops advancing on gate failure but records all stages for debugging.

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

### AP Workflow Hardening (Complete - Mar 2026)
- Duplicate PI check via live BC API
- PO amount validation (10% tolerance)

### Dashboard Date Filtering (Complete - Mar 2026)
- ALL metrics filter by selected date (Central Time)

### Shipping Document Auto-File (Complete - Mar 2026)
- Auto-routes Shipping_Document/Warehouse_Receipt via BC lookup

### 5-Stage Classification Pipeline Refactor (Complete - Mar 18 2026)
- **Created `classification_pipeline.py`** — 5 clear stages with quality gates
- **Replaced monolithic logic** in `process_document()` with pipeline delegation
- **PARSE stage**: Uses pypdf, resolves files via UPLOAD_DIR/{doc_id} fallback, tolerates scanned PDFs
- **CLASSIFY stage**: Heuristic+LLM merge — heuristics win classification, LLM always runs for extraction
- **EXTRACT stage**: Quality gate rejects 0 meaningful fields, excludes _detected_by metadata
- **VALIDATE stage**: extraction_quality_gate rejects zero-data documents before BC checks
- **ROUTE stage**: Automation decision + readiness, no silent fallthrough
- **Pipeline metadata** returned in intelligence results: stages, timing, failure_stage/reason
- **BC Validation hardened**: extraction_quality_gate added
- **Auto-clear hardened**: _detected_by metadata excluded from field counts
- **Readiness fixed**: Terminal shortcut no longer gives 100% to completed docs with 0 real data
- **500 bug fixed**: Null-safe chained `.get()` for `bc_record_info` in documents router
- **Testing**: 15/15 pipeline tests + 16/16 extraction tests + 13/13 validation tests passed

## Key API Endpoints
- `POST /api/document-intelligence/process/{doc_id}` — Full 5-stage pipeline (returns pipeline_stages, classification_method, meaningful_field_count)
- `POST /api/documents/{doc_id}/reprocess?reclassify=true` — Re-classify document (independent of pipeline)
- `GET /api/dashboard/stats?date=YYYY-MM-DD` — Date-filtered dashboard stats
- `GET /api/dashboard/workflow-intelligence?date=YYYY-MM-DD` — Date-filtered intelligence

## Key Files
- `backend/services/classification_pipeline.py` — 5-stage pipeline (NEW)
- `backend/services/document_intelligence_service.py` — Orchestrator, delegates to pipeline
- `backend/services/document_intel_helpers.py` — Heuristics, LLM prompts, extraction
- `backend/services/bc_validation_service.py` — BC validation + extraction_quality_gate
- `backend/services/auto_clear_service.py` — Auto-clear with metadata filtering
- `backend/services/document_readiness_service.py` — Readiness engine

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
