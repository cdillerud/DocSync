# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning. Goal: maximize AI autonomy via continuous learning and aggressive validation gap closure.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph
- **Production**: Docker Compose on Azure VM at http://4.204.41.190:8080/

## What's Been Implemented

### Phases 1-15d — See previous sessions

### Phase 16 — Vendor Profile Consolidation Engine (Apr 7, 2026)

**Problem**: Vendor Intelligence page showed 96 profiles with massive fragmentation:
- TUMALOC appeared as 4 profiles: "Tumalo Creek Transportation" (222), "TUMALO CREEK Transportation" (129), "TUMALOC" (43), "TUMALO CREEK TRANSPORTATION" (26)
- "Gamer Packaging Inc" vs "Gamer Packaging, Inc." — trailing period
- "Valley Distributing and Storage Company" vs "Valley Distributing & Storage Co." — abbreviation
- 0 Stable Vendors despite 420+ TUMALOC docs across variants

**Solution**: Three-pass vendor consolidation engine in `vendor_profile_rebuild.py`:

1. **Pass 1: BC Vendor Number Grouping** — Group documents by `bc_vendor_number` first (the canonical identity). Uses 5 lookup sources:
   - Direct `bc_vendor_number` field on document
   - `unified_vendor_match.bc_vendor_no`
   - `vendor_resolution.vendor_no`
   - Vendor alias DB lookup (1,004 aliases)
   - BC reference cache name-to-number mapping

2. **Pass 2: Normalized Name Grouping** — Remaining docs (no BC match) grouped by normalized name

3. **Pass 3: Alias-Based Merging** — Name-grouped profiles merged into BC-number groups when aliases or BC cache connect them

**Additional changes:**
- `VendorIntelligenceService.update_from_document()` now checks `bc_vendor_number`, `unified_vendor_match`, AND `vendor_resolution` for vendor_no
- Dry-run endpoint shows consolidation preview with merge report
- Rebuild endpoint returns consolidation report with merged variant counts
- Override preservation: looks up by vendor_no OR normalized name
- Frontend: "Preview Consolidation" button, consolidation report UI with variant badges, top vendors grid

**Files changed:**
- `/app/backend/routers/vendor_profile_rebuild.py` — Rewritten `_aggregate_vendor_data()` with 3-pass consolidation
- `/app/backend/services/vendor_intelligence_service.py` — Fixed `update_from_document()` vendor key resolution
- `/app/frontend/src/pages/VendorIntelligencePage.js` — Added consolidation preview UI

**Expected impact on production:**
- 96 profiles → ~30-40 consolidated profiles
- TUMALOC: 4 profiles (max 222 docs) → 1 profile (420 docs)
- Stable vendor count should increase as merged profiles exceed stability thresholds
- Resolution rate accuracy improves with consolidated learning data

## Active Gap Closers: 10
## Backfill Steps: 15
## Learning Dimensions: 21
## Validation Gap Status: 41 blocking (96.7% reduction from 1,252)

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P1: Confidence band tightening (85-95% → review)
- P1: PO pending auto-retry queue

## Future / Backlog
- P2: Low-volume vendor review routing
- P2: Correction replay engine activation
- P2: Auto-delete on max retries, Vendor Inventory Dashboard, BOM module
- P2: Production-ready email service, Entra ID SSO
- P3: server.py refactor (7,500+ lines)
- P3: Investigate no_bc_match batch failures

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
