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

### Phase 4 — Continuous Learning
- Learning Dashboard, Review Queue, Feedback Loop, Batch Re-evaluation, 4 Continuous Learning Engines

### Phase 5-8 — Deep Intelligence
- Per-Document Intelligence (8 dimensions), Deep Learning (5 layers), Advanced Intelligence (7 engines), Vendor Intelligence Integration

### Phase 9 — Validation Gap Closers (7 active)
1. Confidence Miscalibration, 2. PO Validation, 3. Customer Match, 4. Sales Order Match, 5. Duplicate Intelligence, 6. Amount Anomaly, 7. Auto-Escalation

### Phase 10 — Enhanced LLM Prompt Intelligence
Amount intelligence + Field correlation predictions injected into AI prompts.

### Phase 11 — Executive Monitoring Dashboard (Apr 4, 2026)
Clean `/monitor` page with 5 KPIs, Automation Health Score, and "Run Intelligence Backfill" button.

### Phase 12 — Production-Targeted Fixes (Apr 4, 2026)
Based on real production data (1037 docs, 9 vendors, 51% health):

1. **PO Validation Enhancement** — Added reverse vendor PO lookup (historical match), substring/contains matching, dash variant handling, suffix digit matching, bigram similarity scoring. Targets the 452 PO validation gaps (55% of all gaps).

2. **Duplicate Intelligence Auto-Clearing** — Background scheduler runs every 2h: batch-clears false-positive duplicate flags, backfills duplicate outcomes from completed docs, backfills escalation outcomes. Targets the 84 docs stuck on duplicate flags.

3. **Vendor Maturity Threshold Fix** — Changed labels from mastered/proficient to autonomous/stable (matching dashboard expectations). Lowered thresholds: 85→80 (autonomous), 70→65 (stable), 50→45 (developing), 25→20 (learning). Vendors with 50+ docs and decent accuracy can now graduate to "stable."

4. **Intelligence Backfill System** — On-demand POST `/api/posting-patterns/intelligence/backfill` endpoint + UI button. Runs all 4 operations: escalation tracking, duplicate outcome tracking, vendor maturity recompute, duplicate batch-clear.

## Key Routes
- `/` — Inbox
- `/monitor` — Executive Monitoring Dashboard (5 KPIs + backfill)
- `/sales-inventory` — Sales
- `/posting-intelligence` — Posting AI
- `/invoice-trace` — Trace
- `/ai-learning` — AI Learning Dashboard (detailed 20 dimensions)
- `/review-queue` — Review Queue
- `/config` — Settings

## Background Schedulers
- BC Catalog Sync (24h)
- BC Shipment Sync (1h)
- Knowledge Seed (6h)
- Draft Feedback + Continuous Learning (2h)
- Deep Learning: Self-Correction + Vendor Maturity (4h)
- Intelligence Maintenance: Dup Clear + Escalation Backfill + Dup Backfill (2h)

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration

## Future / Backlog
- P2: Auto-delete on max retries, Expand stable vendor criteria (90% auto rate)
- P2: Vendor Inventory Dashboard, BOM module
- P2: Production-ready email service, Entra ID SSO
- P3: server.py refactor (7500+ lines), no_bc_match investigation

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
