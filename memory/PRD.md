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

### AI Learning Dashboard (Complete - Apr 2026)
- `/ai-learning` — Proof of AI learning with 7 data sections

### Draft Review Queue (Complete - Apr 2026)
- `/review-queue` — Review, approve, correct auto-drafted PIs with feedback loop

### Feedback Loop — BC Draft Sync & Template Adjustment (Complete - Apr 2026)
- Original draft line storage, BC sync, diff engine, template adjustment
- Service: `/app/backend/services/draft_feedback_service.py`

### Auto BC Sync Scheduling & Review Badge (Complete - Apr 2026)
- Background scheduler every 2h, nav badge with 60s polling

### Readiness Signal Contradiction Fix (Complete - Apr 2026)
- **Bug 1 Fixed**: `duplicate_risk` now checks BC validation `duplicate_check` first. If BC confirmed "No duplicate found", the stale `possible_duplicate` flag from ingestion is overridden. Only falls back to raw flags if no BC duplicate check was run.
- **Bug 2 Fixed**: `po_resolved` for AP_Invoices now checks BC validation `po_check`. If BC says PO was not found, overrides the field-presence-only "resolved" to False.
- **Automation Intelligence Fixed**: `_duplicate_risk_score()` also respects BC validation duplicate check, returning 0.0 when BC passed.
- **Self-Learning**: `evaluate_and_persist()` detects when re-evaluation corrects contradictions (e.g., duplicate_risk True→False, po_resolved True→False) and records `readiness_contradiction_fix` learning events in both `posting_learning_events` and `classification_corrections` collections.
- **Impact on user's document (0305567)**: Status changes from Blocked (46%) → Needs Review (52%), duplicate_risk removed from blocking, po_resolved correctly set to False with warning.
- **Files changed**: `document_readiness_service.py` (compute_signals + evaluate_and_persist), `automation_intelligence_service.py` (_duplicate_risk_score)

## Backlog
- P0: Deploy to production — re-evaluate document 0305567 via POST /api/readiness/evaluate/{id}
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
