# GPI Document Hub — Product Requirements Document

## Original Problem Statement
Build a document intelligence platform (GPI Hub) to automate document-to-ERP completions, decouple legacy systems, and improve automated multi-source PO extraction. Key capabilities:
- "Intake Benchmark" workspace to compare GPI Hub extraction vs Square 9 side-by-side
- AI classification engine with true Feedback Loop
- Automated processing pipelines for Sales Orders (Drop-Ship vs Warehouse) and Freight G/L routing
- Decommission Square9 data paths
- PDF splitting and page deletion matching Square9 parity

## Architecture
- **Backend**: FastAPI (Python) on port 8001
- **Frontend**: React on port 3000
- **Database**: MongoDB
- **Integrations**: OpenAI GPT-4o / Gemini 3 Pro (Emergent LLM Key), Dynamics 365 BC, MS Graph (Email/SharePoint)
- **Key Pattern**: Derived state via workflow events — UI updates based on event timeline

## What's Implemented

### Core Features (Complete)
- Document ingestion pipeline (email, upload, SharePoint)
- Multi-field text search with MongoDB $text index
- AI extraction + deterministic classification pipeline
- Drop-Ship PO auto-creation in BC
- Intake Benchmark testing suite with auto-post readiness scoring
- SharePoint file preview with fallback logic
- Email polling (AP, Sales, dynamic UI-configured mailboxes)
- Event emission with direct DB fallback (hardened)
- Warehouse workflow with shipping doc auto-close

### Previous Session Work (March 23, 2026)
- **server.py Extraction Pass 3**: Reduced from 7879 to 6874 lines
- **Rep Assignment in SO Creation**: salesperson code from BC customer wired into SO payload
- **Salesperson Performance Dashboard**: New "Rep Performance" tab with KPI cards, charts, leaderboard
- **Auto-Post Readiness Improvements**: Active vendor resolution
- **PO Resolution Fix**: Dash-suffixed PO support (e.g., 106975-3)

### Current Session Fixes (March 23, 2026 - Fork)
- **500 Error Fix on Document Detail**: Wrapped `derive_state`, `evaluate_readiness`, and AP validation reconciliation in try/except. Fixed `b.lower()` crash when `blocking_issues` contained dicts. Documents with any type (including Unknown) now load without 500.
- **URL Encoding for Document Navigation**: Added `encodeURIComponent()` to all document navigation calls across 8 pages and all `api.js` functions. Prevents `#` or special characters in IDs from breaking routes.
- **Frontend Error Differentiation**: Toast now shows actual HTTP status (500 vs 404) instead of generic "Document not found" for all errors.
- **Auto-Classification Pipeline Hardening**: Wrapped all classification, normalization, vendor lookup, duplicate check, BC validation, and automation decision steps in try/except in `_internal_intake_document`. Documents now always get saved even if individual pipeline steps fail.
- **AI Classifier Prompt Fix**: Added BILL_OF_LADING, SALES_ORDER, PACKING_SLIP to AI classification prompt. Previously the AI was forced to return OTHER for shipping documents.
- **Type Normalization**: Added `normalize_doc_type()` mapping: BILL_OF_LADING → Shipping_Document, PACKING_SLIP → Packing_Slip, SALES_ORDER → Sales_Order.
- **Shipping Heuristic Expansion**: Added major shipping carrier names (Evergreen, Maersk, MSC, CMA-CGM, OOCL, etc.) and container number patterns to BOL filename heuristic.
- **Category Mapper Update**: Updated `get_category_for_doc_type` to handle Sales_Order, Shipping_Document, Packing_Slip, Warehouse_Document types.

## Key API Endpoints
- `GET /api/documents/search` — Multi-field text search
- `GET /api/documents/{doc_id}` — Document detail (hardened against 500s)
- `POST /api/documents/{doc_id}/reprocess` — Document reprocessing
- `POST /api/documents/{doc_id}/classify` — Manual classification trigger
- `GET /api/intake-benchmark/runs/{run_id}/auto-post-readiness` — Readiness scoring
- `GET /api/salesperson-dashboard/overview` — Rep performance metrics

## Known Limitations
- BC Sandbox and SharePoint Graph API calls fail in preview (DEMO_MODE=true)
- 19 pre-existing integration tests fail (env var mocking, low priority)
- 205 `no_bc_match` batch failures need investigation

## Backlog
- P2: Vendor Inventory Dashboard and Sales module
- P2: Product/BOM (Bill of Materials) module
- P2: Production-ready email service and Entra ID SSO
- P3: Continue server.py extraction (5 remaining `from server import` calls)
- P3: Investigate 205 `no_bc_match` batch failures
