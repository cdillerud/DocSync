# GPI Document Hub — Product Requirements

## Core Philosophy
**Learn → Apply → Improve → Learn.** Every document processed, every correction, every interaction makes the system smarter.

## Architecture
- **Backend**: FastAPI (Python) on port 8001
- **Frontend**: React on port 3000
- **Database**: MongoDB (gpi_document_hub)
- **Integrations**: Gemini (Emergent LLM Key), Dynamics 365 BC, MS Graph (Email/SharePoint)

## What's Implemented

### Core Features (Complete)
- Document ingestion, AI extraction, classification, vendor matching, auto-post
- Intake Benchmark, SharePoint preview, Email polling, Event emission

### AP Auto-Post Pipeline (Complete)
- Strict binary 4-condition check, wired into all flows

### Phase 1: Bulk Knowledge Seeding (Complete)
- 962 vendor aliases, 122 domain mappings, 603 vendor profiles from BC/Spiro

### Phase 2: Context-Rich LLM Calls (Complete)
- Vendor context builder with real BC invoice examples + profile intelligence
- Auto-confirm on success for positive reinforcement
- Classification + extraction prompts enriched with BC history

### Auto-Seed Scheduler (Complete)
- Startup + every 6h + post-BC-sync triggers

### Intelligent Multi-Page Document Splitting (April 1, 2026 — COMPLETE)
- **Problem**: Multi-page PDFs with multiple invoices/BOLs arrived as single documents, causing misclassification
- **Solution**: Intelligent boundary detection + auto-split
  - `document_boundary_service.py`: Page fingerprinting (vendor hints, invoice/PO/BOL numbers, letterhead detection)
  - Boundary scoring: vendor change (+3), ref number change (+3), letterhead transition (+2), doc type change (+2), threshold ≥ 2
  - Groups contiguous pages belonging to same logical document (e.g., 2-page invoice stays together)
  - `batch_po_splitter.py` expanded: SPLITTABLE_TYPES now includes AP_Invoice, BOL, Unknown, etc.
  - `split_and_ingest_batch()` accepts boundary groups for smart splitting, falls back to per-page
  - Auto-split wired into main intake pipeline (server.py)
  - API endpoints: GET `/{doc_id}/boundary-analysis`, POST `/{doc_id}/auto-split`
- **Test results**: 5-page PDF with 3 vendors → correctly split into 3 groups (pages 1-2, page 3, pages 4-5). Single-vendor 3-page invoice → correctly kept together.
- Testing: 100% (20/20 backend — iteration_163)

### Derived State Fix (Complete)
- ReadyForPost documents show "Validated" + "Ready" (not "Failed")

## Key API Endpoints
- `GET /api/knowledge-seed/status` — KB health + scheduler
- `POST /api/knowledge-seed/run-all` — Manual full seed
- `GET /api/documents/{doc_id}` — Document detail with derived state
- `GET /api/documents/{doc_id}/boundary-analysis` — Preview page boundary detection
- `POST /api/documents/{doc_id}/auto-split` — Trigger boundary-aware splitting
- `POST /api/documents/{doc_id}/reprocess` — Reprocessing

## Backlog
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P2: Vendor Inventory Dashboard
- P2: Product/BOM module
- P2: Production-ready email / Entra ID SSO
- P3: server.py extraction, auto_clear_service cleanup
