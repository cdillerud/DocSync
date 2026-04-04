# GPI Document Hub — Product Requirements

## Core Philosophy
**Learn -> Apply -> Improve -> Learn.** Every document processed, every correction, every interaction makes the system smarter.

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

### Knowledge Intelligence (Complete)
- Phase 1: 962 vendor aliases, 122 domain mappings, 603 vendor profiles from BC/Spiro
- Phase 2: Context-rich LLM calls with real BC invoice examples + vendor profiles

### Post-LLM Refinement Pipeline (Complete - Feb 2026)
### Feedback Loop Fix (Complete - Feb 2026)
### LLM Learning Pipeline Gap Fixes (Complete - Apr 2026)
### Comparison Delta Scoring (Complete - Feb 2026)
### Intelligent Multi-Page Document Splitting (Complete)
### Bulk Reprocess & Comparison (Complete)
### Manual PO Override (Complete - Feb 2026)
### Derived State Vendor/PO Fix (Complete - Apr 2026)
### BC Posting Pattern Analyzer (Complete - Apr 2026)
### Expanded BC Data Ingestion (Complete - Apr 2026)
### Invoice Trace Comparison (Enhanced - Apr 2026)
### Posting Pattern Analyzer Tightening (Complete - Apr 2026)

### BC Auto-Post Phase 2: Template-Driven Draft Creation (Complete - Apr 2026)
- Auto-Post Settings, Ready Queue, Draft PI Preview, Create Draft PI
- Confidence-Gated Auto-Draft, Posting Template Override
- Template Item/Description Matching, BC Item Sync
- Draft vs Production Comparison, Batch Auto-Draft Queue

### AI Learning Dashboard (Complete - Apr 2026)
- **Page**: `/ai-learning` — Proof of what the system has learned
- **Endpoint**: `GET /api/posting-patterns/learning-dashboard`

### Draft Review Queue (Complete - Apr 2026)
- **Page**: `/review-queue` — Review, approve, or correct auto-drafted PIs
- **Endpoints**: review-queue (GET), approve, correct
- **Features**: Summary cards, expandable items, Correction Dialog

### Feedback Loop — BC Draft Sync & Template Adjustment (Complete - Apr 2026)
- **Original Draft Line Storage**: Lines stored on doc at creation for future comparison
- **BC Sync**: `POST /review-queue/{doc_id}/sync-from-bc` and `POST /review-queue/sync-all`
- **Feedback Details**: `GET /review-queue/{doc_id}/feedback`
- **Diff Engine**: Detects item, description, amount, quantity, tax, structural changes
- **Template Adjustment**: Boosts corrected items (+3), records penalties, adjusts line counts
- **Service**: `/app/backend/services/draft_feedback_service.py`
- **Frontend**: "Sync All from BC" button, per-item "Sync BC", FeedbackDiffPanel

### Auto BC Sync Scheduling & Review Badge (Complete - Apr 2026)
- **Background Scheduler**: `_draft_feedback_sync_scheduler` in `server.py` — runs `process_feedback_batch` every 2 hours, auto-detects human edits on drafts in BC
- **Badge Count Endpoint**: `GET /api/posting-patterns/review-queue/badge-count` — lightweight query for nav badge
- **Nav Badge**: Amber pill badge on "Review Queue" sidebar nav item, polls every 60s, only shows when count > 0
- **Scope**: Counts auto-drafted docs needing attention (pending + BC-edited, excludes approved/corrected/synced)

## Backlog
- P0: Deploy to production and run analyze-top + auto-draft-queue
- P1: Rep Overrides management UI — Admin screen to map customers to reps
- P1: Teams Adaptive Card integration — webhook handler for "Approve" -> BC Sales Order
- P1: FRACHT template tuning — verify TARIFF-DS surcharge fix achieves >=90% accuracy
- P2: Stable vendor threshold tuning (lower from 100% to 85%)
- P2: Auto-delete on max retries (Square9 alignment)
- P2: Vendor Inventory Dashboard
- P2: Product/BOM module
- P2: Production-ready email / Entra ID SSO
- P3: server.py extraction, auto_clear_service cleanup
- P3: Investigate 205 no_bc_match batch failures
