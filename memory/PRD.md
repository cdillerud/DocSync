# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph

## What's Been Implemented

### Phases 1-8 — Core Platform + Intelligence Foundation
- Document Ingestion, Classification, AP/Sales Modules, Continuous Learning (4 engines), Per-Document Intelligence (8 dims), Deep Learning (5 layers), Advanced Intelligence (7 engines), Vendor Intelligence Integration

### Phase 9 — Validation Gap Closers (7 active)
1. Confidence Miscalibration, 2. PO Validation, 3. Customer Match, 4. Sales Order Match, 5. Duplicate Intelligence, 6. Amount Anomaly, 7. Auto-Escalation

### Phase 10 — Enhanced LLM Prompt Intelligence
Amount intelligence + Field correlation predictions injected into AI prompts.

### Phase 11 — Executive Monitoring Dashboard
`/monitor` page with 5 KPIs, Automation Health Score, Escalation Detail, Validation Gap Breakdown, PO Gap by Vendor, Backfill button.

### Phase 12 — Production-Targeted Fixes
PO matching enhancement, duplicate auto-clearing, vendor maturity fix, intelligence backfill system, PO gap re-validation.

### Phase 13 — PO Format Learning Engine (Apr 4, 2026)
**Root cause**: The learning system tracked field reliability but never learned PO number FORMAT TRANSFORMATIONS per vendor. Tumaloc sends PO-778245-GPI, 3456, MAR26-FTL-3 — the system needs to learn which transformations turn these into matchable BC POs.

**Built**:
- `po_format_learning_service.py` — 15+ built-in transformations (strip_vendor_suffix, strip_prefix_po, numeric_only, middle_segment, prefix_W, etc.)
- **Learning loop**: Every PO validation attempt records (vendor, extracted_po, matched_bc_po, transformation_used) → builds per-vendor transformation priority
- **Smart candidates**: `get_smart_po_candidates()` applies learned transformations in priority order (most successful first) before BC validation
- **Format pattern detection**: Analyzes successful BC PO formats (common prefixes, avg length) and failed patterns (date-like references, short numbers)
- Wired into `bc_validation_service.py` — smart candidates injected into both PO_REQUIRED and PO_IF_PRESENT flows
- Wired into batch re-validation in backfill endpoint
- API: `GET /api/posting-patterns/po-format-intelligence`

**Learning dimensions**: Now 21 total (20 + PO format learning)

## Background Schedulers
- BC Catalog Sync (24h), BC Shipment Sync (1h), Knowledge Seed (6h)
- Draft Feedback + Continuous Learning (2h)
- Deep Learning: Self-Correction + Vendor Maturity (4h)
- Intelligence Maintenance: Dup Clear + Escalation/Dup Backfill (2h)

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration

## Future / Backlog
- P2: Auto-delete on max retries, Expand stable vendor criteria
- P2: Vendor Inventory Dashboard, BOM module
- P2: Production-ready email service, Entra ID SSO
- P3: server.py refactor (7500+ lines), no_bc_match investigation

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
