# GPI Document Hub - Product Requirements Document

## Original Problem Statement
Enterprise document intelligence platform for Gamer Packaging, Inc. (GPI) that automates document classification, routing, approval workflows, and integration with Business Central and SharePoint.

## Architecture
- **Backend**: FastAPI (Python) with MongoDB
- **Frontend**: React with Shadcn/UI components
- **AI**: Gemini via Emergent LLM Key
- **External APIs**: Microsoft Graph, Business Central (read+write), SharePoint

## Classification Pipeline (5-stage)
```
PARSE    → Extract text (pypdf), resolve file (UPLOAD_DIR/{doc_id} fallback)
CLASSIFY → Heuristic-first (6 patterns), then LLM. Heuristic wins type, LLM wins fields.
EXTRACT  → Merge LLM+existing fields. Gate: ≥1 meaningful field (excludes _detected_by)
VALIDATE → BC validation + extraction_quality_gate (0 real fields = FAIL)
ROUTE    → Auto-clear / review / block with readiness score
```

## Completed Work

### P0: Data Extraction Pipeline Fix (Mar 18 2026)
- UPLOAD_DIR/{doc_id} fallback for file resolution
- Heuristic+LLM merge (heuristics classify, LLM always extracts)
- Clear ERROR logging when no file found

### P0: Validation & Auto-Clear Hardening (Mar 18 2026)
- extraction_quality_gate: rejects 0 meaningful fields in BC validation
- Auto-clear excludes _detected_by metadata from field counting
- Readiness terminal shortcut no longer gives 100% to zero-data docs

### P0: 5-Stage Classification Pipeline Refactor (Mar 18 2026)
- classification_pipeline.py with explicit quality gates per stage
- Pipeline metadata (stages, timing, failure_stage) in intelligence results
- process_document() delegates to pipeline

### P0: Batch Reprocessing Script (Mar 18 2026)
- reprocess_all.py with --revalidate, --dry-run, --sparse-only modes
- Local-only re-validation without file downloads or LLM calls
- Handles terminal-state document preservation

### P1: Pipeline Visualization Component (Mar 18 2026)
- PipelineVisualization.js component showing 5-stage pipeline status
- Horizontal stage indicators with pass/fail/skipped/not_run states
- Expandable detail view with quality gates, timing, errors
- Integrated into DocumentDetailPage left column after Document Info
- Gracefully returns null when no pipeline data present

### P1: Item Mapping Admin UI (Mar 18 2026)
- Full CRUD page at Settings > Item Mappings tab
- Table showing keyword phrase, target, description, customer, priority, status
- Create/Edit form with keyword phrase, keywords, aliases, target type, target no, description, customer, priority, active toggle
- Search, customer filter, show inactive toggle
- Uses existing /api/gpi-integration/item-mappings CRUD endpoints

### Reliability Fixes (Mar 18 2026)
- _detected_by metadata hidden from UI
- Extraction quality metrics fixed
- Shipping_Document customer matching
- Sales Order not-found = hard failure
- 500 error fixed: null-safe bc_record_info access

### Testing Summary
- Pipeline: 15/15 tests passed
- Extraction: 16/16 tests passed
- Validation: 13/13 tests passed
- Reliability: 8/8 tests passed
- Item Mappings CRUD: 13/13 passed
- Frontend: Verified all features

## Key Files
- `backend/services/classification_pipeline.py` — 5-stage pipeline
- `backend/services/document_intelligence_service.py` — Orchestrator
- `backend/services/document_intel_helpers.py` — Heuristics, LLM, extraction
- `backend/services/bc_validation_service.py` — BC validation + quality gates
- `backend/services/auto_clear_service.py` — Auto-clear with metadata filtering
- `backend/services/document_readiness_service.py` — Readiness engine
- `backend/services/item_mapping_service.py` — Item mapping CRUD + matching
- `backend/routers/gpi_integration.py` — Item mappings API (lines 1881-1922)
- `frontend/src/components/PipelineVisualization.js` — Pipeline stage visualization
- `frontend/src/pages/ItemMappingsPage.js` — Item mapping admin CRUD
- `frontend/src/pages/SettingsHubPage.js` — Settings hub with 4 tabs
- `frontend/src/pages/DocumentDetailPage.js` — Document detail UI

## Mocked Services
- Microsoft Graph API (email ingestion - partial)
- JWT Authentication (Entra ID)
- BC API (demo/sandbox mode in preview)

## P1/P2 Backlog
### P1
- Azure OpenAI integration alongside Gemini for classification
- AP Validation card on document detail page

### P2
- Vendor Inventory Dashboard & Sales module
- Product/BOM module
- Refactor monolithic files (server.py, inventory_ledger.py, InventoryLedgerPage.js)
- Redesign Extracted Data / Document Intelligence card layouts
- Production email service & Entra ID SSO
- Decommission legacy Zetadocs

## Credentials
- Web UI: admin / admin
