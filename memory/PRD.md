# GPI Document Hub — Product Requirements

## Core Philosophy
**Learn → Apply → Improve → Learn.** Every document processed, every correction, every interaction makes the system smarter. Use ALL available data.

## Architecture
- **Backend**: FastAPI (Python) on port 8001
- **Frontend**: React on port 3000
- **Database**: MongoDB (gpi_document_hub)
- **Integrations**: Gemini (Emergent LLM Key), Dynamics 365 BC, MS Graph (Email/SharePoint)

## What's Implemented

### Core Features (Complete)
- Document ingestion pipeline (email, upload, SharePoint)
- AI extraction + deterministic classification
- Drop-Ship PO auto-creation in BC
- Intake Benchmark, SharePoint preview, Email polling, Event emission

### AP Auto-Post Pipeline (Complete)
- Strict binary 4-condition check, wired into intake/reprocess/mark-ready

### Phase 1: Bulk Knowledge Seeding (Complete)
| Metric | Before | After |
|--------|--------|-------|
| Vendor Aliases | 7 | 962 |
| Sender-Domain Mappings | 14 | 122 |
| Vendor Invoice Profiles | 3 | 603 |

### Phase 2: Context-Rich LLM Calls (Complete)
- **Vendor Context Builder**: Real BC invoice examples + profile + classification signals injected into every LLM call
- **Auto-Confirm on Success**: Positive feedback loop from ReadyForPost/Posted outcomes
- **Feedback Bridge Fixed**: 117 corrections now reach the LLM

### Auto-Seed Scheduler (April 1, 2026 — Complete)
- **Startup seed**: Runs 30s after backend starts
- **Periodic seed**: Every 6 hours
- **Post-sync seed**: Auto-triggers after every BC cache refresh
- **Idempotent**: Safe to run repeatedly — uses upserts, skips existing entries
- **Non-blocking**: Failures logged but never crash the pipeline
- **UI**: Scheduler status visible in Knowledge Base admin page
- Files: `server.py` (scheduler task), `bc_reference_cache_service.py` (post-sync hook), `routers/knowledge_seed.py` (status endpoint with scheduler info), `pages/KnowledgeBasePage.js` (scheduler card)

### Derived State Fix (Complete)
- Fixed ReadyForPost documents showing "Failed" badge

## Key API Endpoints
- `GET /api/knowledge-seed/status` — KB health + scheduler status
- `POST /api/knowledge-seed/run-all` — Manual full seed (idempotent)
- `GET /api/documents/{doc_id}` — Document detail with derived state
- `POST /api/documents/{doc_id}/reprocess` — Reprocessing
- `POST /api/ap-review/documents/{doc_id}/mark-ready` — BC post

## Backlog
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P2: Vendor Inventory Dashboard
- P2: Product/BOM module
- P2: Production-ready email / Entra ID SSO
- P3: server.py extraction, auto_clear_service cleanup
