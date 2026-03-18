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
PARSE    -> Extract text (pypdf), resolve file (UPLOAD_DIR/{doc_id} fallback)
CLASSIFY -> Heuristic-first (6 patterns), then LLM. Heuristic wins type, LLM wins fields.
EXTRACT  -> Merge LLM+existing fields. Gate: >=1 meaningful field (excludes _detected_by)
VALIDATE -> BC validation + extraction_quality_gate (0 real fields = FAIL)
ROUTE    -> Auto-clear / review / block with readiness score
```

## Completed Work

### P0: Data Extraction Pipeline Fix (Mar 18 2026)
- UPLOAD_DIR/{doc_id} fallback for file resolution
- Heuristic+LLM merge (heuristics classify, LLM always extracts)

### P0: Validation & Auto-Clear Hardening (Mar 18 2026)
- extraction_quality_gate: rejects 0 meaningful fields in BC validation
- Auto-clear excludes _detected_by metadata from field counting

### P0: 5-Stage Classification Pipeline Refactor (Mar 18 2026)
- classification_pipeline.py with explicit quality gates per stage
- Pipeline metadata (stages, timing, failure_stage) in intelligence results

### P0: Batch Reprocessing Script (Mar 18 2026)
- reprocess_all.py with --revalidate, --dry-run, --sparse-only modes
- Now includes validation_status computation during revalidation

### P1: Pipeline Visualization Component (Mar 18 2026)
- PipelineVisualization.js showing 5-stage pipeline on Document Detail page
- Stage indicators with pass/fail/skipped/not_run, timing, quality gates
- Expandable detail view

### P1: Item Mapping Admin UI (Mar 18 2026)
- Full CRUD page at Settings > Item Mappings tab
- Table with search, filters, create/edit/delete for mapping rules

### P1: BC Validation 3-State Status (Mar 18 2026)
- **Before**: Badge showed binary PASSED/FAILED based only on required check failures
- **After**: 3-state display: PASSED (green), WARNINGS (amber), FAILED (red)
- Backend: validate_bc_match now wraps inner function, computes validation_status (pass/warn/fail) from all check outcomes
- Frontend: Client-side computation from checks array ensures backward compatibility with ALL existing documents (no re-processing needed)
- Script: reprocess_all.py --revalidate now includes validation_status in stored results
- Logic: `fail` = required check failed, `warn` = only optional checks failed, `pass` = all passed

### Reliability Fixes (Mar 18 2026)
- _detected_by metadata hidden from UI
- Extraction quality metrics fixed
- Shipping_Document customer matching
- 500 error: null-safe bc_record_info access

## Key Files
- `backend/services/classification_pipeline.py` - 5-stage pipeline
- `backend/services/bc_validation_service.py` - BC validation + 3-state status
- `backend/services/document_intelligence_service.py` - Orchestrator
- `backend/scripts/reprocess_all.py` - Batch data maintenance
- `frontend/src/components/PipelineVisualization.js` - Pipeline visualization
- `frontend/src/pages/ItemMappingsPage.js` - Item mapping admin CRUD
- `frontend/src/pages/SettingsHubPage.js` - Settings hub with 4 tabs
- `frontend/src/pages/DocumentDetailPage.js` - Document detail UI

## Mocked Services
- Microsoft Graph API (email ingestion - partial)
- JWT Authentication (Entra ID)
- BC API (demo/sandbox mode in preview)

## P1/P2 Backlog
### P1
- Azure OpenAI integration alongside Gemini for classification
- Derived state recomputation for queue validation badges (currently queue uses old derived state for existing docs)

### P2
- Vendor Inventory Dashboard & Sales module
- Product/BOM module
- Refactor monolithic files (server.py, inventory_ledger.py, InventoryLedgerPage.js)
- Production email service & Entra ID SSO
- Decommission legacy Zetadocs

## Credentials
- Web UI: admin / admin
