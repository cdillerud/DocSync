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
- Auto-confirm on success for positive reinforcement
- Auto-seed scheduler: startup + every 6h + post-BC-sync

### Post-LLM Refinement Pipeline (Complete - Feb 2026)
- Vendor Name Normalization, Doc Type Refinement, PO Number Validation
- Confidence Calibration, Feedback Loop Amplification
- Pipeline Integration at Stage 3c

### Feedback Loop Fix (Complete - Feb 2026)
- All event handlers mark events as `applied=True`
- Approval reinforcement, Replay endpoint
- Application rate: 0% -> 100%

### LLM Learning Pipeline Gap Fixes (Complete - Apr 2026)
- Classification corrections feed into unified feedback loop
- VEP profiles seeded from BC cache (13 -> 469 profiles)
- Same-type correction noise filtered, unlearnable events force-marked

### Comparison Delta Scoring (Complete - Feb 2026)
- BC-match fields excluded, normalization

### Intelligent Multi-Page Document Splitting (Complete)
- Boundary detection, smart grouping, Split Preview UI

### Bulk Reprocess & Comparison (Complete)
- Compare, Apply Improvements, Full Pipeline Reprocess

### Manual PO Override (Complete - Feb 2026)
- Override endpoint, UI button, auto-post skip

### Derived State Vendor/PO Fix (Complete - Apr 2026)
- 5 fixes for stale vendor blocks and contradictory states

### BC Posting Pattern Analyzer (Complete - Apr 2026)
- `posting_pattern_analyzer.py` queries BC for human posting behavior
- Vendor-specific posting templates with confidence levels
- Endpoints: `/status`, `/analyze/{vendor_no}`, `/analyze-top`, `/learning-proof/{vendor_no}`

### Expanded BC Data Ingestion (Complete - Apr 2026)
- ALL invoice statuses ingested, dual-source, deduplication, graceful errors

### Invoice Trace Comparison (Enhanced - Apr 2026)
- Side-by-side human vs AI comparison at `/invoice-trace`
- Weighted dimension scoring, line-by-line alignment, batch trace

### BC Auto-Post Phase 2: Template-Driven Draft Creation (Complete - Apr 2026)
- Auto-Post Settings, Ready Queue, Draft PI Preview, Create Draft PI
- Confidence-Gated Auto-Draft, Posting Template Override
- Template Item/Description Matching, BC Item Sync
- Draft vs Production Comparison, Batch Auto-Draft Queue
- Frontend: `PostingPatternsDashboard.js`

### Posting Pattern Analyzer Tightening (Complete - Apr 2026)
- Line sample: 20 -> 75, consistency scoring, full item distribution
- Line-level tax codes, richer reference patterns, charge line tracking

### AI Learning Dashboard (Complete - Apr 2026)
- **New page**: `/ai-learning` — Proof of what the system has learned
- **Endpoint**: `GET /api/posting-patterns/learning-dashboard`
- **Sections**: Learning Events summary, Vendor Templates, Corrections Learned, Label Corrections, Auto-Drafted PIs
- **Cards**: Posting Template Confidence breakdown, Learned Label Corrections (PO->SHIPMENT, BOL->PO), Vendor Learning Activity, Auto-Drafted PIs by Vendor, Recent Learning Events table, Recent Classification Corrections
- **Frontend**: `LearningDashboard.js` with StatCard components and refresh

### Draft Review Queue (Complete - Apr 2026)
- **New page**: `/review-queue` — Review, approve, or correct auto-drafted Purchase Invoices
- **Endpoints**: 
  - `GET /api/posting-patterns/review-queue` — List auto-drafted PIs with filter (pending/approved/corrected/all)
  - `POST /api/posting-patterns/review-queue/{doc_id}/approve` — Approve draft, creates positive feedback event
  - `POST /api/posting-patterns/review-queue/{doc_id}/correct` — Submit corrections with feedback loop
- **Features**: Summary cards (pending/approved/corrected/total), expandable item details, Correction Dialog with field selectors, approve/correct actions
- **Feedback Loop**: Approved drafts create `draft_approved` learning events. Corrections create `draft_corrected` events and `classification_corrections` entries for continuous learning
- **Frontend**: `ReviewQueuePage.js` with StatusBadge, ConfidenceBadge, CorrectionDialog, ReviewItem components

## Backlog
- P0: Deploy to production and run `POST /api/posting-patterns/analyze-top?top_n=20` to build profiles, then `POST /api/posting-patterns/auto-draft-queue` to auto-draft qualifying invoices
- P1: Build Feedback Loop — When human edits an auto-drafted PI in BC, correction feeds back into template
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
