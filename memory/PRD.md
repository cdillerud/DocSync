# GPI Document Hub — Product Requirements

## Core Philosophy
**Learn → Apply → Improve → Learn.** Every document processed, every correction made, every interaction makes the system smarter. Use ALL available data on everything — every interaction, every calculation, every routing decision. The system must continuously self-improve through feedback loops at every layer. Document

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

### Strict Binary AP Auto-Post Pipeline (Complete)
- `ap_auto_post_service.py`: 4-condition check (classified + fields extracted + vendor matched + PO matched)
- Wired into intake (`server.py`), reprocess (`document_handlers.py`), mark-ready (`ap_review.py`)
- AP invoices bypass old auto_clear entirely
- Vendor profile learning from BC cache (`vendor_invoice_profile_service.py`)
- Vendor alias auto-learning from successful BC validation
- `bc_vendor_number` properly stored during intake/reprocess

### Derived State / Status Badge Fix (April 1, 2026 - COMPLETE)
- **Root cause**: `automation.decision.completed` events with both `auto_clear=True` AND `decision="ReadyForPost"` were handled by the `auto_clear` branch first in `derived_state_service.py`, which set `workflow_state="completed"` but never set `validation_state="pass"`. Earlier `bc.validation.completed` events left `validation_state="fail"` — the frontend read this and showed "Failed" badge.
- **Fix**: Restructured `_derive_from_events()` to check `decision` field FIRST (ReadyForPost/Posted/NeedsReview) before falling back to `auto_clear`/`auto_post` booleans.
  - ReadyForPost: validation_state=pass, workflow_state=ready, clears blocking_issues, needs_review=False
  - Posted: validation_state=pass, workflow_state=completed, clears blocking_issues
  - NeedsReview: workflow_state=reviewing, needs_review=True
  - auto_clear/auto_post without decision: backward-compatible completed state with validation_state=pass
- **Legacy fallback fix**: `_derive_from_legacy()` now handles `status="ReadyForPost"` before `auto_cleared=True` override.
- **Frontend**: Added "Ready to Post" label and green color for ReadyForPost/ready_for_post in `UnifiedQueuePage.js`
- **Testing**: 100% (8/8 backend, full frontend verification — iteration_160)
- **Files**: `services/derived_state_service.py`, `pages/UnifiedQueuePage.js`

### Previous Session Work (See CHANGELOG for full history)
- UX Simplification (3-item → 4-item sidebar)
- Inbox Stats Strip, Insights Page
- Processed Tab, Batches Tab
- Sales Module Phase 1 (My Queue, Triage, Auto-Assign, Pipeline Demo)
- Learned Dunnage Patterns, Energy Surcharge, Quantity Bounds
- AP Writes to BC Sandbox
- BC Custom API 404 Fix, MEXUS vendor fix
- Auto-Close Confidence Fix, File Persistence Fix
- Folder Routing 100% accuracy

## Key API Endpoints
- `GET /api/documents/search` — Multi-field text search
- `GET /api/documents/{doc_id}` — Document detail with derived state
- `POST /api/documents/{doc_id}/reprocess` — Document reprocessing
- `POST /api/ap-review/documents/{doc_id}/mark-ready` — Triggers direct BC post
- `POST /api/ap-review/documents/{doc_id}/post-to-bc` — Direct BC posting
- `GET /api/dashboard/inbox-stats` — Inbox metrics
- `GET /api/dashboard/insights-trends` — Insights aggregations

## Known Limitations
- BC Sandbox and SharePoint Graph API calls fail in preview (DEMO_MODE=false, but BC creds may not work in preview)
- Documents stuck at 0.00 confidence from before the fix can be reprocessed via `POST /api/documents/{doc_id}/reprocess?reclassify=true`

## Backlog
- P1: Rep Overrides management UI (Admin screen to map customers to reps without DB scripts)
- P1: Teams Adaptive Card integration (DM rep via Graph API with Approve/Flag/View buttons)
- P1: Webhook handler for Teams "Approve" action → BC SO creation
- P2: Vendor Inventory Dashboard
- P2: Product/BOM (Bill of Materials) module
- P2: Production-ready email service and Entra ID SSO
- P3: Continue server.py extraction (5 remaining `from server import` calls)
- P3: Investigate 205 `no_bc_match` batch failures
- P3: Clean up dead code in `auto_clear_service.py` (AP invoice paths no longer used)
