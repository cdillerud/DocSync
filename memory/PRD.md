# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning. Goal: maximize AI autonomy via continuous learning and aggressive validation gap closure.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph
- **Production**: Docker Compose on Azure VM at http://4.204.41.190:8080/

## What's Been Implemented

### Phases 1-14 — See previous sessions for full history

### Phase 15 — Validation Gap Annihilation Engine (Apr 6-7, 2026)

**Starting point**: 1,252 validation gaps across 5 categories.
**Ending point**: 73 blocking + 71 advisory = 144 total (94.2% blocking reduction).

#### Key Changes:
1. Three-pass PO revalidation (vendor profile → unknown vendor → cache/BC match)
2. Customer match revalidation (alias map, vendor→customer history, cache fuzzy)
3. Sales order match revalidation (7 strategies: exact, external, normalized, digits, prefix, sibling, flow)
4. Smart duplicate clearing (BC status check, amount comparison, PO cross-validation)
5. Blocking vs advisory split (required checks = red, non-required = amber)
6. Unmatched vendor UI on Monitor dashboard (1-click alias creation)
7. Auto-accept rule for vendor matching (>=90% fuzzy → auto-alias)

### Phase 15b — Learning Dashboard Gap Fix (Apr 7, 2026)
- Fixed stale validation gap hotspots on `/learning` page (was querying legacy `validation_gap_log`)
- Now queries `hub_documents` directly (source of truth) for both global and per-vendor gaps

### Phase 15c — Gap Closer Expansion: 7→10 Engines (Apr 7, 2026)

**New Gap Closers Added:**

**Gap 8: Extraction Quality Gate Closer**
- Filename parsing for vendor/PO/invoice hints
- Batch/parent document context inheritance
- Smart advisory downgrade for genuinely empty docs (cover pages, separators)
- File: `validation_backfill_service.py` → `batch_revalidate_extraction_gaps()`

**Gap 9: Enhanced Vendor Match**
- Cross-document vendor inference (batch siblings with same vendor)
- Enhanced email domain → vendor mapping (historical 2+ doc threshold)
- Aggressive first-word matching (50%+ threshold if company names share first word)
- Single candidate acceptance at 55%+
- Auto-creates aliases for future matches
- File: `validation_backfill_service.py` → `enhanced_vendor_match_backfill()`

**Gap 10: Enhanced PO Revalidation**
- Vendor PO rate relaxation (<30% PO rate in BC → PO not expected, skip)
- Broader reference field matching (all ref fields, not just po_number)
- Digit-only and partial/substring PO matching against BC cache
- Doc-type downgrade (freight/shipping docs → PO advisory)
- File: `validation_backfill_service.py` → `enhanced_po_revalidation()`

**Backend integration:**
- All 3 new gap closers added to `/api/posting-patterns/intelligence/backfill` (steps 11-13)
- Gap status endpoint returns all 10 gap closers
- `extraction_quality_gate` added to gap counting

**Frontend:**
- 3 new gap closer cards on Learning Dashboard (Gap 8, 9, 10)
- Icons: FileText (extraction), Users (vendor), Zap (PO)
- Gap closer description updated: "10 biggest validation gaps"

## Active Gap Closers: 10 (was 7)
## Backfill Steps: 14 (was 11)
## Learning Dimensions: 21

## Production Stats (Apr 7, 2026)
- 81% AI confidence accuracy, 67% auto-file rate
- 13/23 mature vendors (10 autonomous, 3 stable)
- 73 blocking validation gaps (before Phase 15c deployment)
- Expected further reduction from new gap closers:
  - extraction_quality_gate: 36 → ~0 (filename + advisory downgrade)
  - vendor_match: 28 → ~15 (batch inference + aggressive matching)
  - po_validation: 25 → ~10 (PO rate relaxation + broader matching)

## Upcoming Tasks
- P1: Rep Overrides management UI (Admin screen to map customers to reps)
- P1: Teams Adaptive Card integration (webhook handler for "Approve" → BC Sales Order)

## Future / Backlog
- P2: Auto-delete on max retries (Square9 alignment)
- P2: Expand stable vendor criteria (90% automation rate threshold)
- P2: Vendor Inventory Dashboard
- P2: Product/BOM module
- P2: Production-ready email service, Entra ID SSO
- P3: server.py refactor (7,500+ lines)
- P3: Investigate no_bc_match batch failures

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
