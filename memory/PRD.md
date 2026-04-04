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
- Auto-confirm on success, Auto-seed scheduler

### Post-LLM Refinement Pipeline (Complete - Feb 2026)
- Vendor Name Normalization, Doc Type Refinement, PO Number Validation
- Confidence Calibration, Feedback Loop Amplification

### Feedback Loop Fix (Complete - Feb 2026)
- All event handlers mark events as `applied=True`
- Approval reinforcement, Replay endpoint, 100% application rate

### LLM Learning Pipeline Gap Fixes (Complete - Apr 2026)
- Classification corrections feed into unified feedback loop
- VEP profiles seeded from BC cache (13 -> 469 profiles)

### Comparison Delta Scoring (Complete - Feb 2026)
### Intelligent Multi-Page Document Splitting (Complete)
### Bulk Reprocess & Comparison (Complete)
### Manual PO Override (Complete - Feb 2026)
### Derived State Vendor/PO Fix (Complete - Apr 2026)

### BC Posting Pattern Analyzer (Complete - Apr 2026)
- Vendor-specific posting templates with confidence levels
- Consistency scoring, full item distribution, charge line tracking

### Expanded BC Data Ingestion (Complete - Apr 2026)
- ALL invoice statuses ingested, dual-source, deduplication

### Invoice Trace Comparison (Enhanced - Apr 2026)
- Side-by-side human vs AI comparison at `/invoice-trace`

### BC Auto-Post Phase 2: Template-Driven Draft Creation (Complete - Apr 2026)
- Auto-Post Settings, Ready Queue, Draft PI Preview, Create Draft PI
- Confidence-Gated Auto-Draft, Posting Template Override
- Template Item/Description Matching, BC Item Sync
- Draft vs Production Comparison, Batch Auto-Draft Queue

### AI Learning Dashboard (Complete - Apr 2026)
- **Page**: `/ai-learning` — Proof of what the system has learned
- **Endpoint**: `GET /api/posting-patterns/learning-dashboard`
- **Sections**: Learning Events, Vendor Templates, Corrections, Label Corrections, Auto-Drafted PIs, Template Confidence, Vendor Activity, Recent Events

### Draft Review Queue (Complete - Apr 2026)
- **Page**: `/review-queue` — Review, approve, or correct auto-drafted PIs
- **Endpoints**: GET/POST review-queue, approve, correct
- **Features**: Summary cards, expandable items, Correction Dialog, approve/correct actions

### Feedback Loop — BC Draft Sync & Template Adjustment (Complete - Apr 2026)
- **Original Draft Line Storage**: When a Draft PI is created, the original lines are stored on the document (`original_draft_lines`) for future comparison
- **BC Sync**: `POST /api/posting-patterns/review-queue/{doc_id}/sync-from-bc` fetches current state of a draft PI from BC, compares with stored originals, detects human edits
- **Batch Sync**: `POST /api/posting-patterns/review-queue/sync-all` scans all pending auto-drafted PIs
- **Feedback Details**: `GET /api/posting-patterns/review-queue/{doc_id}/feedback` returns full diff with original vs current lines
- **Line Diff Engine**: `_compute_line_diff()` detects item changes, description changes, amount changes, quantity changes, tax changes, line additions/deletions
- **Template Adjustment**: `_adjust_template_from_feedback()` boosts corrected item weights (+3), records penalties on original items, adjusts line counts, updates tax codes
- **Learning Events**: Each sync that detects changes records `draft_bc_feedback` events in `posting_learning_events` and individual `classification_corrections`
- **Frontend**: "Sync All from BC" batch button, per-item "Sync BC" button, `FeedbackDiffPanel` component showing color-coded changes by type (item, description, amount, etc.)
- **Service**: `/app/backend/services/draft_feedback_service.py` — standalone service with `sync_draft_from_bc`, `process_feedback_batch`, diff engine, template adjustment

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
