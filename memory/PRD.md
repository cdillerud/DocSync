# GPI Document Hub - Product Requirements Document

## Original Problem Statement
Enterprise document intelligence platform for Gamer Packaging, Inc. (GPI) that automates document classification, routing, approval workflows, and integration with Business Central and SharePoint. The system should serve as a continuous feedback loop where every interaction makes the AI smarter.

## Core Principle
**Every interaction is training data. Every correction makes the system smarter.**

## Architecture
- **Backend**: FastAPI (Python) with MongoDB
- **Frontend**: React with Shadcn/UI components
- **AI**: Gemini 3 Pro via Emergent LLM Key + Azure OpenAI fallback
- **External APIs**: Microsoft Graph, Business Central, SharePoint
- **Feedback Loop**: Unified feedback capture → learning signals → AI prompt enrichment

## Credentials
- Web UI: admin / admin

## Completed Work

### Core Platform
- PO Candidate Extraction, Square9 stage-counts fix, FastAPI dependency injection fix
- Auto-post AP invoices for stable vendors (with stable vendor confidence boost)
- Azure OpenAI fallback classifier (confidence < 0.70 triggers fallback)
- Freight GL routing extensions, Square9 decommission endpoints
- BC catalog sync, Drop-Ship vs Warehouse SO routing
- Warehouse SO Booked Notifications, BC Shipment Sync
- BC Customer + Salesperson Cache Sync & Rep Assignment (Step 1)
- BC Factbox Document Links (Zetadocs Replacement) + AL Extension
- Frontend Consolidation (38 → 8 pages), App Versioning (v1.6.0)

### Intake Benchmark (Mar 2026)
- Full benchmark workspace: run setup, scoring, auto-population, results, Excel export
- SharePoint folder scan (scan S9 output folders via Graph API)
- Folder Alignment Report (S9 vs GPI Hub folder comparison)
- Auto-Post Readiness Panel (criteria pass rates, blocker analysis)
- Truth auto-seeding from GPI extraction
- Hierarchical folder comparison (subfolder = bonus, not error)

### Vendor Intelligence (Mar 2026)
- Vendor Inference Service — 6 strategies
- "No Vendor Expected" classification (Letters of Auth, W9 forms, etc.)
- Noise file detection (PNGs, QR codes)
- Vendor name casing normalization

### Feedback Loop Architecture (Mar 22, 2026)
- Unified Feedback Loop Service (`feedback_loop_service.py`)
- Every user action captured: vendor corrections, reclassifications, amount/PO edits, approvals, folder moves
- Immediate learning signal application
- AI prompt enrichment via `build_feedback_context_for_prompt()`
- Wired into documents.py update flow and ap_review.py save flow

### LLM Optimization (Mar 22, 2026 — Session 2)
**Critical bugs fixed:**
1. Feedback context was never injected (vendor_id not passed) — FIXED
2. Vendor hints used filename instead of vendor name — FIXED
3. Secondary LLM path had no feedback injection — FIXED
4. Model upgraded: gemini-3-flash-preview → gemini-3-pro-preview
5. Chain-of-thought prompting: IDENTIFY → CLASSIFY → EXTRACT → ROUTE
6. General recent corrections always included in every LLM call

### Feedback Loop Health Dashboard (Mar 22, 2026 — Session 2)
- Settings > Feedback Loop tab (view-only)
- Backend: `GET /api/feedback-loop/health`
- Metrics: total events, applied rate, aliases, classification examples, routing corrections
- Daily activity chart, events by type, most corrected vendors, recent events

### Before/After Reprocess Comparison (Mar 22, 2026 — Session 2)
- Settings > Before/After tab
- Backend: `POST /api/reprocess-comparison/run`, `GET /api/reprocess-comparison/status`, `GET /api/reprocess-comparison/results/{run_id}`, `GET /api/reprocess-comparison/runs`
- Snapshots current classification results, re-runs LLM pipeline, compares field-by-field
- Does NOT overwrite production data — safe to run anytime
- Shows: summary cards, fields that changed, per-document before/after with verdict badges
- Background processing with live progress polling
- "Changes Only" filter for focused review

### Auto-Post Confidence (Mar 22, 2026)
- Stable vendor score wired into auto-post eligibility
- Confidence formula: stable_flag + score >= 0.85 → max(raw, stable_score)

## P0/P1/P2 Backlog

### P0
- Run Before/After comparison on production data to validate LLM improvements

### P1
- Wire rep assignment into SO creation flow (Step 2)
- Investigate remaining `no_bc_match` failures from batch run
- Continue server.py extraction pass 3 (classification, email polling)

### P2
- Vendor Inventory Dashboard & Sales module
- Product/BOM module
- Production email service & Entra ID SSO

## Key API Endpoints
- `GET /api/feedback-loop/health`
- `POST /api/reprocess-comparison/run`
- `GET /api/reprocess-comparison/status`
- `GET /api/reprocess-comparison/results/{run_id}`
- `GET /api/reprocess-comparison/runs`
- `GET /api/intake-benchmark/runs`
- `POST /api/intake-benchmark/runs/{id}/auto-populate`
- `POST /api/intake-benchmark/runs/{id}/scan-sharepoint`
- `GET /api/intake-benchmark/runs/{id}/folder-alignment`
- `GET /api/intake-benchmark/runs/{id}/auto-post-readiness`

## Key Collections
- `feedback_events` — every user interaction
- `vendor_aliases` — learned vendor name mappings
- `classification_feedback` — few-shot examples from corrections
- `routing_feedback` — folder routing corrections
- `vendor_intelligence_profiles` — stable vendor scores and flags
- `reprocess_comparison_runs` / `reprocess_comparison_results` — before/after comparison data
- `bakeoff_runs` / `bakeoff_documents` — benchmark data

## Known Issues
- Preview env: Graph API token fails (expected — use DEMO_MODE fallback)
- 19 pre-existing integration tests fail due to missing BASE_URL env var
- Before/After comparison on preview test docs shows "regression" because test files are plain text stubs with heuristic-assigned 1.0 confidence — real PDFs will show true improvement

### Bulk File Button (Mar 22, 2026 — Session 2)
- "File" button added to Documents Queue, right next to "Show auto-cleared"
- Select multiple documents via checkboxes → click "File (N)" → routes all selected to their destination SharePoint folders and marks as completed
- Uses existing `POST /api/documents/bulk-file-and-clear` endpoint
- Also records filing actions for AI learning and positive classification confirmation
