# GPI Document Hub - PRD

## Original Problem Statement
Build a "GPI Document Hub" test platform that replaces Zetadocs-style document linking in Microsoft Dynamics 365 Business Central by using SharePoint Online as the document repository and a middleware hub to orchestrate ingestion, metadata, approvals, and attachment linking back to BC.

## Architecture
- **Hub & Spoke**: Hub (FastAPI orchestrator) → Spokes (BC Sandbox, SharePoint Online, Exchange Online)
- **Backend**: FastAPI + MongoDB (Motor async driver)
- **Frontend**: React + Tailwind CSS + Shadcn/UI + Recharts
- **Auth**: JWT with hardcoded test user (SSO-ready structure)
- **Microsoft APIs**: LIVE integration with Graph API and Business Central API
- **AI Classification**: Gemini 2.5-flash via Emergent LLM Key

## Current Status: PHASE 7 - OBSERVATION MODE

**Shadow Mode Started:** February 18, 2026  
**Feature Freeze:** 14 days (until ~Mar 4, 2026)  
**No new features until observation window completes.**

---

## What's Been Implemented

### Phase 1 - Core Platform ✅
### Phase 2 - Email Parser Agent ✅
### Phase 2.1 - Production Hardening ✅
### Phase 2.2 - Audit Dashboard ✅
### Phase 3 - Alias Impact Integration ✅
### Phase 4 - CREATE_DRAFT_HEADER (Sandbox) ✅
### Phase 5 - ELT ROI Dashboard ✅
### Phase 6 - Shadow Mode Instrumentation ✅
### Phase 7 - Observation Mode 🔄 ACTIVE

---

## Locked Readiness Formula (Phase 7)

**DO NOT MODIFY** without business justification.

| Factor | Weight | Target | Gate Criteria |
|--------|--------|--------|---------------|
| High Confidence Docs (≥0.92) | 35 pts | ≥60% | `high_confidence_pct >= 60` |
| Alias Exception Rate | 20 pts | <5% | `alias_exception_rate < 5` |
| Stable Vendors | 25 pts | ≥3 | `stable_vendors >= 3` |
| Data Volume | 20 pts | ≥100 | `total_docs >= 100` |

**Total:** 100 pts  
**Enablement Threshold:** ≥80 pts AND all 4 gates passed

### Scoring Rules
- High Confidence: `min(35, (pct / 60) * 35)`
- Alias Exception: Full 20 if <5%, 15 if <10%, 10 if <20%, 0 otherwise
- Stable Vendors: Full 25 if ≥3, 18 if ≥2, 10 if ≥1, 0 otherwise
- Data Volume: Full 20 if ≥100, proportional if ≥50, slower ramp if <50

---

## Observation Checkpoints

- [ ] **Week 1:** Feb 25, 2026 - Check histogram stability
- [ ] **Week 2:** Mar 4, 2026 - Evaluate gates, decide Phase 8
- [ ] **Week 3:** Mar 11, 2026 (if needed)

---

## Phase 8 Trigger (When All Gates Pass)

1. Enable `CREATE_DRAFT_HEADER`
2. Restrict to **3 known stable vendors only**
3. Match methods: `exact_no`, `exact_name`, `normalized` (exclude alias initially)
4. Monitor draft modification rate (target: <10%)

---

## Enterprise Maturity Ladder

| Phase | Status | Description |
|-------|--------|-------------|
| 3 | ✅ | Deterministic matching |
| 4 | ✅ | Safe draft gating |
| 5 | ✅ | Executive ROI visibility |
| 6 | ✅ | Production instrumentation |
| 7 | 🔄 | **Observed stability** (CURRENT) |
| 8 | ⏳ | Controlled automation |
| 9 | ⏳ | Vendor-level tuning |
| 10 | ⏳ | Zetadocs retirement |

---

## Key Endpoints (Reference)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/reports/shadow-mode-performance` | Full readiness report |
| `GET /api/settings/shadow-mode` | Current shadow mode status |
| `GET /api/metrics/match-score-distribution` | Histogram analysis |
| `GET /api/metrics/alias-exceptions` | Alias health |
| `GET /api/metrics/vendor-stability` | Vendor categorization |

---

## Documents

- `/app/memory/PRD.md` - This file
- `/app/memory/SHADOW_MODE_MEMO.md` - Internal memo
- `/app/test_reports/iteration_10.json` - Latest test results
