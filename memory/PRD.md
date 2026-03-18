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
- extraction_quality_gate: rejects 0 meaningful fields
- Auto-clear excludes _detected_by metadata from field counting

### P0: 5-Stage Classification Pipeline Refactor (Mar 18 2026)
- classification_pipeline.py with explicit quality gates per stage

### P0: Batch Reprocessing Script (Mar 18 2026)
- reprocess_all.py with --revalidate, --dry-run, --sparse-only modes
- Now includes validation_status computation during revalidation

### P1: Pipeline Visualization Component (Mar 18 2026)
- 5-stage pipeline status on Document Detail page
- Expandable details with quality gates, timing, errors

### P1: Item Mapping Admin UI (Mar 18 2026)
- Full CRUD page at Settings > Item Mappings tab

### P1: BC Validation 3-State Status (Mar 18 2026)
- 3-state badge: PASSED (green), WARNINGS (amber), FAILED (red)
- Backend: validation_status field computed on every return path
- Frontend: Client-side computation from checks array for backward compatibility
- Derived state service: Updated event-driven + legacy paths to use validation_status

### P1: Recompute Derived States Tool (Mar 18 2026)
- POST /api/admin/recompute-derived-states endpoint (supports dry_run)
- GET /api/admin/recompute-status/{run_id} for progress tracking
- Background task processes all documents, updates validation/workflow/automation states
- Settings > General > Data Maintenance section with Dry Run + Run buttons
- Results panel shows total/processed/changed/errors with per-document change details
- Event emission (event_service.py) now includes validation_status in bc.validation.completed payloads

## Key Files
- `backend/services/classification_pipeline.py` - 5-stage pipeline
- `backend/services/bc_validation_service.py` - BC validation + 3-state status
- `backend/services/derived_state_service.py` - Derived state with 3-state validation support
- `backend/services/event_service.py` - Event emission with validation_status
- `backend/services/document_intelligence_service.py` - Orchestrator
- `backend/scripts/reprocess_all.py` - Batch data maintenance
- `backend/routers/admin.py` - Admin endpoints including recompute-derived-states
- `frontend/src/components/PipelineVisualization.js` - Pipeline visualization
- `frontend/src/pages/ItemMappingsPage.js` - Item mapping admin CRUD
- `frontend/src/pages/SettingsPage.js` - Settings with Data Maintenance section
- `frontend/src/pages/DocumentDetailPage.js` - Document detail UI

## Mocked Services
- Microsoft Graph API (email ingestion - partial)
- JWT Authentication (Entra ID)
- BC API (demo/sandbox mode in preview)

## P1/P2 Backlog
### P1
- Azure OpenAI integration alongside Gemini for classification

### P2
- Vendor Inventory Dashboard & Sales module
- Product/BOM module
- Refactor monolithic files (server.py, inventory_ledger.py, InventoryLedgerPage.js)
- Production email service & Entra ID SSO
- Decommission legacy Zetadocs

## Credentials
- Web UI: admin / admin
