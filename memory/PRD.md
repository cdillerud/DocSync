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

## Completed Work (Mar 18 2026)

### P0: Data Extraction Pipeline Fix
- UPLOAD_DIR/{doc_id} fallback for file resolution
- Heuristic+LLM merge (heuristics classify, LLM always extracts)
- Clear ERROR logging when no file found

### P0: Validation & Auto-Clear Hardening
- extraction_quality_gate: rejects 0 meaningful fields in BC validation
- Auto-clear excludes _detected_by metadata from field counting
- Readiness terminal shortcut no longer gives 100% to zero-data docs

### P0: 5-Stage Classification Pipeline Refactor
- classification_pipeline.py with explicit quality gates per stage
- Pipeline metadata (stages, timing, failure_stage) in intelligence results
- process_document() delegates to pipeline

### Reliability Fixes
- **_detected_by metadata hidden from UI**: Frontend filters heuristic metadata from Extracted Data display
- **Extraction quality metrics fixed**: Uses correct required/optional fields per document type, returns total_defined/total_extracted
- **Shipping_Document customer matching**: Consignee matched as BC customer, shipper matched as vendor
- **Sales Order not-found = hard failure**: When order number present but not found in BC, validation FAILS
- **500 error fixed**: Null-safe bc_record_info access in documents router

### Testing Summary
- Pipeline: 15/15 tests passed
- Extraction: 16/16 tests passed
- Validation: 13/13 tests passed
- Reliability: 8/8 tests passed (3 skipped)
- Frontend: Verified across all iterations

## Key Files
- `backend/services/classification_pipeline.py` — 5-stage pipeline
- `backend/services/document_intelligence_service.py` — Orchestrator
- `backend/services/document_intel_helpers.py` — Heuristics, LLM, extraction
- `backend/services/bc_validation_service.py` — BC validation + quality gates
- `backend/services/auto_clear_service.py` — Auto-clear with metadata filtering
- `backend/services/document_readiness_service.py` — Readiness engine
- `frontend/src/pages/DocumentDetailPage.js` — Document detail UI

## Mocked Services
- Microsoft Graph API (email ingestion - partial)
- JWT Authentication (Entra ID)
- BC API (demo/sandbox mode in preview)

## P1/P2 Backlog
### P1
- AP Validation card on document detail page
- Azure OpenAI integration alongside Gemini
- Admin UI for item mapping rules

### P2
- Vendor Inventory Dashboard & Sales module
- Product/BOM module
- Refactor monolithic files (server.py, inventory_ledger.py, InventoryLedgerPage.js)
- Redesign Extracted Data / Document Intelligence card layouts
- Production email service & Entra ID SSO
- Decommission legacy Zetadocs

## Credentials
- Web UI: admin / admin
