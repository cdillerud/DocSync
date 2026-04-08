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

### Phase 16b — Vendor Profile Rebuild Bug Fix (Apr 7, 2026)

**Problem**: Clicking "Rebuild Profiles" in production crashed with "not able to rebuild..." error.

**Root causes fixed:**
1. No try/except around individual vendor profile inserts
2. `sv_cfg` queried inside loop
3. `insert_one` with pre-existing unique index caused DuplicateKeyError
4. Fallback `vendor_no = display_name` collision risk
5. No HTTP status checking in frontend `apiPost()` helper

### Phase 16c — Behavioral Fields in Rebuild (Apr 7, 2026)

Enhanced rebuild to compute and store:
- `typical_reference_domain`, PO/BOL rates, shipment/freight counts, BC match types, domain counts

### Phase 16d — Confidence Calibration Fix: Effective Confidence (Apr 8, 2026)

Introduced `compute_effective_confidence(doc)` that penalizes classification confidence based on extraction completeness.

### Phase 16e — Re-process NoneType Crash Fix (Apr 8, 2026)

Fixed `match_vendor_unified()` returning `None` crash in bc_validation_service.py and server.py.

### Phase 16f — Auto-Act on Ready Docs + Extended Re-evaluation (Apr 8, 2026)

Added auto-act logic: when re-evaluation promotes a doc to "ready" AND no BC PI exists → auto-triggers `attempt_ap_auto_post()`. Increased batch limit 500→5000, prioritizes policy-held docs.

### Phase 16g — Robust PO Bypass + Vendor Processing Bypass + Batch Alias Resolution (Apr 8, 2026)

**Problem 1**: Documents from vendors with `po_expected=False` (e.g., TUMALOC) still getting stuck with `po_resolved=False` even after vendor profile was updated.

**Fix**: Enhanced `evaluate_and_persist()` to directly lookup vendor profile's `po_expected` flag from `vendor_invoice_profiles` collection. This covers cases where `validation_checks` weren't updated after the vendor profile learned `po_expected=False`. The flag is injected into the doc dict so `compute_signals()` detects it.

**Problem 2**: NOFACH vendor extraction fails 100% of the time, clogging the pipeline.

**Fix**: Added vendor processing bypass mechanism:
- `PATCH /api/vendor-intelligence/profiles/{vendor_no}/bypass` — Flags vendor for auto-processing bypass
- `GET /api/vendor-intelligence/bypassed-vendors` — Lists all bypassed vendors
- Readiness evaluator checks `auto_process_bypass` flag and routes to manual review

**Problem 3**: SC Warehouses, LLC has 17 stuck documents needing vendor alias mapping.

**Fix**: Added batch alias resolution endpoint:
- `POST /api/aliases/vendors/batch-resolve` — Takes vendor name→vendor_no mappings, creates aliases, and re-validates all affected documents in one call

**Files changed:**
- `/app/backend/services/document_readiness_service.py` — Direct vendor profile lookup in evaluate_and_persist for po_expected and auto_process_bypass
- `/app/backend/routers/vendor_intelligence.py` — PATCH bypass and GET bypassed-vendors endpoints
- `/app/backend/routers/aliases.py` — POST batch-resolve endpoint

## Active Gap Closers: 10
## Backfill Steps: 15
## Learning Dimensions: 21
## Validation Gap Status: 41 blocking (96.7% reduction from 1,252)

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P1: PO pending auto-retry queue

## Future / Backlog
- P2: Low-volume vendor review routing
- P2: Correction replay engine activation
- P2: Email sender → vendor mapping
- P2: Expand stable vendor criteria for Auto-Ready
- P3: server.py refactor (7,500+ lines)

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
