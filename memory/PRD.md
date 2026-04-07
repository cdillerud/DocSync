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

### Phase 16b — Vendor Profile Rebuild Bug Fix (Apr 7, 2026)

**Problem**: Clicking "Rebuild Profiles" in production crashed with "not able to rebuild..." error. Data partially consolidated (96→29 profiles) but endpoint returned 500 before completing JSON response.

**Root causes fixed:**
1. No try/except around individual vendor profile inserts — one bad profile (duplicate key, missing field) crashed entire rebuild
2. `sv_cfg` (stable vendor config) queried inside the loop for every profile — moved outside
3. `insert_one` with pre-existing unique `vendor_no` index — duplicate values caused DuplicateKeyError  
4. Fallback `vendor_no = display_name` for name-only groups — collision risk when multiple groups share same display name
5. No HTTP status checking in frontend `apiPost()` helper

**Fixes applied:**
- Wrapped each profile insert in try/except with error collection
- Moved stable vendor config query before the loop
- Added `seen_vendor_nos` dedup set to prevent duplicate key errors
- Drop + recreate unique index around the rebuild  
- Name-only groups use `norm_name` (unique by definition) as vendor_no key instead of display_name
- Frontend: `apiPost` now checks `r.ok` before parsing JSON
- Frontend: rebuild success toast shows profile/stable/error counts
- Document cursor iteration wrapped in try/except
- Added `.batch_size(200)` to cursor for large collections

**Files changed:**
- `/app/backend/routers/vendor_profile_rebuild.py` — Hardened `rebuild_run()` with error handling, dedup, and index management
- `/app/frontend/src/pages/VendorIntelligencePage.js` — Better error handling and success feedback

### Phase 16c — Behavioral Fields in Rebuild (Apr 7, 2026)

**Problem**: After rebuild, Domain column showed "?" and PO/BOL rates were 0% for all vendors because the rebuild didn't compute behavioral metrics.

**Fix**: Enhanced `_accum_doc()` and rebuild profile to track and store:
- `typical_reference_domain` (purchase/sales/shipping/unknown) from best match entity + doc type
- `po_reference_count` / `po_reference_frequency` from `po_number_clean`
- `bol_count` / `bol_presence_rate` from `bol_number`
- `shipment_reference_count` / `shipment_reference_frequency` from reference candidates
- `freight_invoice_count`, `shipping_document_count` from doc type
- `typical_bc_match_types`, `bc_match_type_counts`, `avg_match_score`
- `match_outcome_counts`, `domain_counts`

Also updated Pass 2 merge logic to combine all behavioral counters when merging name-groups into BC-groups.

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
