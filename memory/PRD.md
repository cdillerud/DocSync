# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph

## What's Been Implemented

### Phases 1-12 — See previous PRD versions for full history

### Phase 13 — PO Format Learning Engine (Apr 4, 2026)
15+ PO transformations, records outcomes, applies learned vendor-specific transformations.

### Phase 14 — Vendor Profile PO Learning Integration (Apr 6, 2026)
Vendor profile PO learning wired into validation, PO format learning fallback, Multi-PO field parsing.

### Phase 15 — PO Gap Resolution Engine (Apr 7, 2026)
**Three-pass PO revalidation pipeline:**
1. **Pass 1 — Vendor Profile Learning**: Checks `po_expected` flag + PO format match rate. Auto-resolves gaps for vendors that don't use POs.
2. **Pass 2a — Unknown Vendor Resolution**: Attempts to match "unknown" vendor docs via vendor name aliases, email sender domains. Resolved vendors then get profile-checked.
3. **Pass 2b — Cache-first PO Lookup + BC API**: Searches `bc_reference_cache` for PO matches (19,000+ cached records). Learns vendor PO formats from cached POs and tries digit-substring matching. Falls back to BC live API.

**Vendor profile force-refresh**: `run_intelligence_backfill()` rebuilds vendor profiles from latest BC cache before running revalidation.

**Results**: PO validation gaps dropped from 658 → 364 in first two runs (294 resolved = 45% reduction). TUMALOC (124 gaps), CARGOMO (5), KOCHTRU (3), PEPPER (2) all auto-resolved via profile learning.

## Learning Dimensions: 21 total
## Active Gap Closers: 7
## LLM Prompt Injections: 6
## Background Schedulers: 7

## Production Stats (Latest — Apr 7, 2026)
- 81% AI confidence accuracy, 67% auto-file rate
- 13/23 mature vendors (10 autonomous, 3 stable)
- PO validation gaps: 364 (down from 658)
- Total validation gaps: 958 (down from 1252)

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration

## Future / Backlog
- P2: Auto-delete on max retries, Vendor Inventory Dashboard, BOM module
- P2: Production-ready email service, Entra ID SSO
- P3: server.py refactor (7,500+ lines), no_bc_match investigation

## Deployment
Docker Compose on Azure VM at http://4.204.41.190:8080/
"Save to Github" -> `git pull && docker compose up -d --build`
