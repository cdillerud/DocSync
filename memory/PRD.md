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

#### Key Changes:
1. Three-pass PO revalidation (vendor profile → unknown vendor → cache/BC match)
2. Customer match revalidation (alias map, vendor→customer history, cache fuzzy)
3. Sales order match revalidation (7 strategies)
4. Smart duplicate clearing (BC status check, amount comparison, PO cross-validation)
5. Blocking vs advisory split (required=True blocks, required=False advisory)
6. Unmatched vendor UI on Monitor dashboard (1-click alias creation)
7. Auto-accept rule for vendor matching (>=90% fuzzy → auto-alias)

### Phase 15b — Learning Dashboard Gap Fix (Apr 7, 2026)
- Fixed stale validation gap hotspots on `/learning` page
- Queries `hub_documents` directly (source of truth)

### Phase 15c — Gap Closer Expansion: 7→10 Engines (Apr 7, 2026)

**Gap 8: Extraction Quality Gate Closer**
- Filename parsing for vendor/PO/invoice hints
- Batch/parent document context inheritance
- Email sender domain → vendor mapping
- Email subject parsing for PO/invoice extraction
- Smart advisory downgrade for genuinely empty docs

**Gap 9: Enhanced Vendor Match**
- Cross-document vendor inference (batch siblings)
- Enhanced email domain mapping
- First-word matching (lowered to 2-char filter for "SC", "HP", etc.)
- "Contains" matching (substring detection)
- Single candidate acceptance at 55%+
- Auto-creates aliases for future matches

**Gap 10: Enhanced PO Revalidation**
- Vendor PO rate relaxation (<30% PO rate → skip)
- Broader reference field matching
- Digit-only and partial/substring PO matching
- No-vendor downgrade (if vendor_match also failed → PO becomes advisory)
- Doc-type downgrade (freight/shipping → PO advisory)

### Phase 15d — Aggressive Gap Improvement Round 2 (Apr 7, 2026)

**Based on production deployment results (95→72 blocking):**

1. **PO Profile Threshold Fix**: Lowered minimum invoice count from 10→3 and PO rate threshold from 5%→10%
   - Fixes FIFTHSTR (8 PIs, 0% PO rate was incorrectly showing "PO required")
   - Also catches vendors with 3-9 invoices that have zero POs

2. **Vendor Name Normalization**: Added `_normalize_vendor_for_match()` helper
   - Strips trailing punctuation (., ,, ;)
   - Removes common legal suffixes (Inc, LLC, Ltd, Corp, etc.)
   - Fixes "SC Warehouses, LLC" vs "SC Warehouses, LLC." dedup
   - Applied to both standard and enhanced vendor match backfills

3. **First-Word Filter Lowered**: 3-char → 2-char minimum
   - Catches 2-letter vendor names: "SC", "HP", "UPS", "RTS"
   - Applied in both standard deep fuzzy match AND enhanced backfill

4. **"Contains" Matching Strategy**: New vendor match approach
   - If vendor name is a substring of a BC vendor name (or vice versa), match it
   - E.g., "GARTNER" matching "Gartner Inc." in BC

5. **Unknown Vendor PO Downgrade**: When vendor_match AND po_validation both fail
   - PO validation downgraded to advisory (vendor must resolve first)
   - Fixes 7 "unknown" PO gaps that were counting as blocking

6. **Email Subject Extraction**: For extraction quality gate
   - Parses PO numbers from email subject lines
   - Parses invoice numbers from email subject lines

## Active Gap Closers: 10
## Backfill Steps: 14
## Learning Dimensions: 21

## Production Stats (Apr 7, 2026 — post Phase 15c deployment)
- 81% AI confidence accuracy, 67% auto-file rate
- 13/23 mature vendors (10 autonomous, 3 stable)
- 72 blocking validation gaps (down from 95, originally 1,252)
- 84 advisory validation gaps
- Expected further reduction from Phase 15d fixes:
  - FIFTHSTR PO: 1 gap → 0 (profile threshold fix)
  - "unknown" PO: 7 gaps → 0 blocking (vendor-deferred downgrade)
  - extraction quality: 22 → further reduced (email sender/subject)
  - vendor match: 28 → reduced (name normalization, 2-char filter, contains matching)

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration

## Future / Backlog
- P2: Auto-delete on max retries, Vendor Inventory Dashboard, BOM module
- P2: Production-ready email service, Entra ID SSO
- P3: server.py refactor (7,500+ lines)
- P3: Investigate no_bc_match batch failures

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
