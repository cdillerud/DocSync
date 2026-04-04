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
### Knowledge Intelligence (Complete)
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
- `/ai-learning` — Proof of AI learning with stats, template confidence, label corrections, vendor activity, auto-drafts, recent events

### Draft Review Queue (Complete - Apr 2026)
- `/review-queue` — Review, approve, correct auto-drafted PIs with feedback loop

### Feedback Loop — BC Draft Sync & Template Adjustment (Complete - Apr 2026)
- Original draft line storage, BC sync, diff engine, template adjustment
- Auto-scheduled every 2h via background task
- Nav badge with 60s polling

### Readiness Signal Contradiction Fix (Complete - Apr 2026)
- **Bug 1**: `duplicate_risk` now checks BC validation `duplicate_check` first — stale `possible_duplicate` flags from ingestion are overridden when BC confirmed "No duplicate found"
- **Bug 2**: `po_resolved` for AP_Invoices now checks BC validation `po_check` — field-presence-only "resolved" overridden to False when BC says PO not found
- **Automation Intelligence**: `_duplicate_risk_score()` also respects BC validation
- **Self-Learning**: `evaluate_and_persist()` detects contradictions and records `readiness_contradiction_fix` learning events

### Batch Re-evaluate & Learn (Complete - Apr 2026)
- **Service**: `batch_reevaluate_all()` re-evaluates ALL non-duplicate documents using learning-aware `evaluate_and_persist()`
- **Endpoint**: `POST /api/readiness/reevaluate-all?limit=500`
- **Returns**: total_processed, total_corrections, status_transitions (from→to with confidence delta), vendor_corrections (per-vendor breakdown), by_status distribution, errors
- **Frontend**: "Batch Re-evaluate & Learn" section on AI Learning page with button and rich results visualization (stats grid, status transitions list, vendor corrections list with signal badges)
- **Learning**: Every signal correction automatically feeds into `posting_learning_events` and `classification_corrections` — these appear on the Learning Dashboard
- **Bug Fix**: Fixed NoneType `round()` error in `/learning-dashboard` endpoint when aggregation returns None values

## Backlog
- P0: Deploy to production — re-evaluate document 0305567 via POST /api/readiness/evaluate/{id}, then batch re-evaluate all docs
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
