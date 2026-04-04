# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph

## What's Been Implemented

### Phases 1-3 — Core Platform
- Document Ingestion & Classification, AP Module, Sales Module

### Phase 4-8 — Intelligence Foundation
- Continuous Learning (4 engines), Per-Document Intelligence (8 dimensions), Deep Learning (5 layers), Advanced Intelligence (7 engines), Vendor Intelligence Integration

### Phase 9 — Validation Gap Closers (7 active)
1. Confidence Miscalibration, 2. PO Validation, 3. Customer Match, 4. Sales Order Match, 5. Duplicate Intelligence, 6. Amount Anomaly, 7. Auto-Escalation

### Phase 10 — Enhanced LLM Prompt Intelligence
Amount intelligence + Field correlation predictions injected into AI prompts.

### Phase 11 — Executive Monitoring Dashboard
`/monitor` page with 5 KPIs, Automation Health Score, "Run Intelligence Backfill" button.

### Phase 12 — Production-Targeted Fixes (Apr 4, 2026)
1. **PO Matching Enhancement** — Reverse vendor PO lookup, substring matching, dash variants, suffix digits, bigram similarity
2. **Duplicate Auto-Clearing** — Background scheduler (2h), batch-clear false positives
3. **Vendor Maturity Fix** — Labels: autonomous/stable/developing/learning/novice. Thresholds lowered.
4. **Intelligence Backfill** — On-demand endpoint + UI button
5. **PO Gap Re-validation** — Batch re-runs PO matching on all gap documents using enhanced intelligence against BC. Wired into the same backfill button. Finds new PO matches, updates validation results, clears gaps.

## Background Schedulers
- BC Catalog Sync (24h), BC Shipment Sync (1h), Knowledge Seed (6h)
- Draft Feedback + Continuous Learning (2h)
- Deep Learning: Self-Correction + Vendor Maturity (4h)
- Intelligence Maintenance: Dup Clear + Escalation Backfill + Dup Backfill (2h)

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
