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

### Session Work (March 23, 2026)
- **server.py Extraction Pass 3**: Reduced from 7879 to 6874 lines
  - Email polling logic → `services/email_polling_service.py`
  - Classification pipeline → `services/classification_helpers.py`
- **Rep Assignment in SO Creation**: salesperson code from BC customer wired into SO payload
- **Salesperson Performance Dashboard**: New "Rep Performance" tab with KPI cards, charts, leaderboard
- **Auto-Post Readiness Improvements**:
  - Active vendor resolution (lookup_vendor_alias, alias direct, BC cache name match)
  - Expanded PO number sources (ai_extraction, normalized_fields, linked records)
- **PO Resolution Fix** (for doc 113798.pdf / "106975-3"):
  - Updated `_VALID_BC_PO_PATTERN` to accept dash-suffixed POs (e.g., 106975-3, W117397-1)
  - Added base-number candidate generation: `106975-3` → also tries `106975`
  - Added suffix-stripping fallback in `_search_bc_cache`: tries base number when exact match fails
  - Confidence now properly 0.900 for dash-suffixed POs (was 0.450 due to valid_format=False)

## Key API Endpoints
- `GET /api/documents/search` — Multi-field text search
- `POST /api/documents/{doc_id}/reprocess` — Document reprocessing
- `GET /api/intake-benchmark/runs/{run_id}/auto-post-readiness` — Readiness scoring
- `GET /api/salesperson-dashboard/overview` — Rep performance metrics
- `GET /api/salesperson-dashboard/trend` — SO creation trend over time
- `GET /api/salesperson-dashboard/detail/{code}` — Rep drill-down

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
