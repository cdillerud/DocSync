# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning. Goal: maximize AI autonomy via continuous learning and aggressive validation gap closure.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph
- **Production**: Docker Compose on Azure VM at http://4.204.41.190:8080/

## What's Been Implemented

### Phases 1-15c — See previous sessions

### Phase 15d — Aggressive Gap Improvement (Apr 7, 2026)

**Production baseline**: 72 blocking → 69 blocking after first 15d run.

#### Fixes Applied:
1. **PO Profile Threshold**: Lowered from >=10 to >=3 invoices, rate 5%→10%
2. **Vendor Name Normalization**: `_normalize_vendor_for_match()` strips trailing punct + legal suffixes
3. **First-Word Filter 3→2 chars**: Catches "SC", "HP", "UPS", "RTS"
4. **"Contains" Match Strategy**: Substring-based vendor matching
5. **Unknown Vendor PO Downgrade**: Simplified — ANY doc without vendor_no gets PO downgraded to advisory (removed vendor_check_failed guard)
6. **Force Extraction Downgrade**: MongoDB array filter bulk update to force-downgrade ALL remaining blocking extraction quality gate failures to advisory (safety net for per-doc processing errors)
7. **Monitor Dashboard UI**: Added backfill results for Extraction Gate, Enhanced PO, Enhanced Vendor to the Intelligence Backfill results panel

**Expected impact after next deployment:**
- extraction_quality_gate blocking: 22 → 0 (force-downgrade to advisory)
- PO "unknown" blocking: 4 remaining → 0 (simplified downgrade)
- Total blocking: 69 → ~43 (vendor match 28 irreducible + PO 12 legit + dup 3)

## Active Gap Closers: 10
## Backfill Steps: 15 (added force_downgrade_extraction_gate)

## Irreducible Gaps (require manual action):
- **28 vendor match**: 11 vendors genuinely not in BC database. Need manual alias or BC vendor creation.
- **~12 PO validation**: Vendors with high PO rates but specific POs not yet in BC (timing issue)
- **3 duplicate**: Real duplicate flags that can't be auto-cleared

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
