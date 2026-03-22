# GPI Document Hub - Product Requirements Document

## Original Problem Statement
Enterprise document intelligence platform for Gamer Packaging, Inc. (GPI) that automates document classification, routing, approval workflows, and integration with Business Central and SharePoint. The system should serve as a continuous feedback loop where every interaction makes the AI smarter.

## Core Principle
**Every interaction is training data. Every correction makes the system smarter.**

## Architecture
- **Backend**: FastAPI (Python) with MongoDB
- **Frontend**: React with Shadcn/UI components
- **AI**: Gemini via Emergent LLM Key + Azure OpenAI fallback
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
- Vendor Inference Service — 6 strategies:
  1. Filename vendor patterns (30+ known vendors)
  2. Invoice number range mapping (TUMALOC 030xxxx, CCF_ → SMC, INUS → Air Menzies)
  3. Document number patterns (R66xx/W117xxx → CITICARGO)
  4. Email sender patterns (copier@buske.com → BUSKE)
  5. BC reference cache cross-reference (BOL/shipment/PO numbers)
  6. Sibling batch inference
- "No Vendor Expected" classification (Letters of Auth, W9 forms, etc.)
- Noise file detection (PNGs, QR codes)
- Vendor name casing normalization

### Feedback Loop Architecture (Mar 22, 2026)
- Unified Feedback Loop Service (`feedback_loop_service.py`)
- Every user action captured: vendor corrections, reclassifications, amount/PO edits, approvals, folder moves
- Immediate learning signal application:
  - Vendor corrections → vendor_aliases collection
  - Classification corrections → classification_feedback (few-shot examples)
  - Folder corrections → routing_feedback
  - Approvals/rejections → vendor track record
- AI prompt enrichment via `build_feedback_context_for_prompt()`
- Wired into documents.py update flow and ap_review.py save flow

### Auto-Post Confidence (Mar 22, 2026)
- Stable vendor score now wired into auto-post eligibility
- `attempt_auto_post()` queries vendor_intelligence_profiles for stable data
- Confidence formula: stable_flag + score >= 0.85 → max(raw, stable_score)
- Benchmark readiness check also queries stable vendor profiles
- TUMALOC (0.985 stable score) → 53 invoices should now be auto-post eligible

## Production Benchmark Results (Test2 — 122 docs)
- Classification Accuracy: GPI 100%, S9 0%
- Vendor Accuracy: GPI 100%, S9 0%
- PO Accuracy: GPI 100%, S9 0%
- Folder Accuracy: GPI 100%, S9 96.7%
- No-Touch Rate: GPI 70.5%, S9 0%
- Stable vendors: TUMALOC (0.985), CARGOMO (0.904), ARK (0.877), GROUPWA (0.865), ROTONDO (0.865)

## P0/P1/P2 Backlog

### P0
- Verify auto-post readiness shows ~59/71 AP invoices ready (user to refresh)

### P1
- Wire rep assignment into SO creation flow (Step 2)
- Investigate remaining `no_bc_match` failures from batch run
- Continue server.py extraction (classification, email polling services)

### P2
- Vendor Inventory Dashboard & Sales module
- Product/BOM module
- Production email service & Entra ID SSO
- Feedback Loop Health dashboard (events, aliases learned, accuracy trends)

## Key API Endpoints
- `GET /api/intake-benchmark/runs`
- `POST /api/intake-benchmark/runs/{id}/auto-populate`
- `POST /api/intake-benchmark/runs/{id}/scan-sharepoint`
- `GET /api/intake-benchmark/runs/{id}/folder-alignment`
- `GET /api/intake-benchmark/runs/{id}/auto-post-readiness`
- `GET /api/gpi-integration/document-links/{entity}/{doc_no}`

## Key Collections
- `feedback_events` — every user interaction
- `vendor_aliases` — learned vendor name mappings
- `classification_feedback` — few-shot examples from corrections
- `routing_feedback` — folder routing corrections
- `vendor_intelligence_profiles` — stable vendor scores and flags
- `bakeoff_runs` / `bakeoff_documents` — benchmark data

## Known Issues
- Preview env: Graph API token fails (expected — use DEMO_MODE fallback)
- 19 pre-existing integration tests fail due to missing BASE_URL env var
