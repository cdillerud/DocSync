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

## Three-Layer Architecture (Production Ready)
1. **Durability Layer**: SharePoint-first storage (document preserved even if BC fails)
2. **Policy Layer**: Job Type configuration, validation rules, automation levels
3. **Intelligence Layer**: Alias learning, metrics, compounding efficiency

## What's Been Implemented (Feb 18, 2026)

### Phase 1 - Core Platform ✅
- [x] Full backend API (35+ endpoints)
- [x] LIVE SharePoint + Business Central integration
- [x] BC document attachments via documentAttachments API
- [x] Dashboard, Upload, Queue, Document Detail, Settings pages

### Phase 2 - Email Parser Agent ✅
- [x] AI document classification (Gemini 2.5-flash)
- [x] Configurable Job Types with automation levels
- [x] Graph Webhook support for real-time email monitoring
- [x] Email Parser UI

### Phase 2.1 - Production Hardening ✅
- [x] SharePoint-first upload (always preserve documents)
- [x] Field normalization (amounts → float, dates → ISO)
- [x] Multi-strategy vendor matching (exact, normalized, alias, fuzzy)
- [x] PO validation modes (PO_REQUIRED, PO_IF_PRESENT, PO_NOT_REQUIRED)
- [x] Resolve and Link endpoint

### Phase 2.2 - Audit Dashboard ✅
- [x] Automation metrics (status distribution, confidence, job type breakdown)
- [x] Vendor friction index with ROI signals
- [x] Resolution time tracking
- [x] Daily trend charts

### Phase 3 - Alias Impact Integration ✅
- [x] **Match Method Tracking** on every document
- [x] **Metrics Enhancement** with match_method_breakdown, alias_auto_linked
- [x] **Vendor Friction ROI Signal** with roi_hint
- [x] **Safe Reprocess Endpoint** with idempotency guards

### Phase 4 - CREATE_DRAFT_HEADER (Sandbox) ✅
- [x] **Feature Flag**: `ENABLE_CREATE_DRAFT_HEADER` (default: false)
- [x] **Purchase Invoice Draft Creation** for AP_Invoice only:
  - Creates HEADER ONLY (no lines, no posting)
  - Header fields: Vendor No, External Doc No, Document Date, Due Date, Posting Date
  - Adds comment: "Created by GPI Hub Automation"
- [x] **Safety Preconditions** (ALL must be true):
  - Feature flag enabled
  - Job type = AP_Invoice
  - match_method ∈ {exact_no, exact_name, normalized, alias} (NO fuzzy)
  - match_score ≥ 0.92
  - AI confidence ≥ 0.92
  - duplicate_check passed
  - vendor_match passed
  - PO validation passed (if required)
  - Document status ≠ LinkedToBC
  - bc_record_id not already set
- [x] **Duplicate Check**: Vendor + External Doc No before creation
- [x] **Idempotency**: 
  - Reprocess NEVER creates drafts (only links)
  - bc_record_id guard prevents duplicate drafts
- [x] **Transaction Tracking**: `transaction_action` field tracks NONE/LINKED_ONLY/DRAFT_CREATED
- [x] **Metrics Integration**: draft_created_count, draft_creation_rate, draft_feature_enabled

### Phase 5 - ELT ROI Dashboard ✅ NEW
- [x] **New "ROI Summary" Tab** - Default tab in Audit Dashboard
- [x] **Section 1: Automation Overview**
  - Total Documents, Fully Automated %, Needs Review %, Manual Resolved, Duplicates Blocked
  - Trend chart (AreaChart) showing auto-linked vs needs review over time
  - Visual indicators (arrows, warning icons) for quick status assessment
- [x] **Section 2: Alias Impact — Data Hygiene ROI**
  - Docs Via Alias, Automation From Alias %, Vendors w/ Alias, Alias Exception Rate
  - "Data Hygiene Improvement" explanation box showing ROI story
  - Proof that learned aliases compound automation over time
- [x] **Section 3: Vendor Friction Matrix**
  - Sortable table: Vendor | Docs | Automation % | Exception % | Avg Score | Alias Usage
  - Visual progress bars for automation rate
  - Badges for vendors with aliases
  - ROI conversation starter: "Here's where process breakdowns are happening"
- [x] **Section 4: Draft Creation Confidence** (Conditional)
  - Shows when `draft_feature_enabled` is defined
  - Disabled state: Shows safety requirements (match score ≥ 92%, confidence ≥ 92%, etc.)
  - Enabled state: Eligible docs, Drafts created, Draft creation rate, Draft mode
- [x] **Executive Summary Box**
  - Automation Rate with exact %
  - Data Hygiene ROI (alias count and contribution)
  - Risk Mitigation (duplicates blocked)
  - Processing Time (median resolution)

### Document Status Flow
```
Received → StoredInSP → Classified → LinkedToBC (LINKED_ONLY or DRAFT_CREATED)
                    ↘ NeedsReview → [Reprocess] → LinkedToBC (LINKED_ONLY only)
                                  ↘ [Resolve] → LinkedToBC
```

### Transaction Actions
| Action | Description |
|--------|-------------|
| NONE | No BC action taken |
| LINKED_ONLY | Document attached to existing BC record |
| DRAFT_CREATED | Purchase Invoice draft header created in BC |

### Testing Results (Latest - Feb 18, 2026)
- Phase 4: 47/47 tests passed (26 Phase 4 + 21 Phase 3)
- Phase 5: 14/14 backend + 100% frontend UI verification
- All safety gates verified
- All ROI dashboard sections functional

## Key API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/documents/{id}/reprocess` | POST | Safe reprocess - re-validates, links only (no drafts) |
| `/api/metrics/automation` | GET | Match methods, alias metrics, draft metrics |
| `/api/metrics/vendors` | GET | Vendor friction with ROI hints |
| `/api/aliases/vendors` | GET/POST | Alias CRUD |
| `/api/settings/features/create-draft-header` | GET/POST | Draft creation feature toggle |
| `/api/settings/status` | GET | Now includes `features` section |

## Prioritized Backlog

### P0 (Complete) ✅
- [x] BC document attachment
- [x] AI classification
- [x] Production validation
- [x] Audit Dashboard
- [x] Alias impact tracking
- [x] CREATE_DRAFT_HEADER backend (Phase 4)
- [x] ELT ROI Dashboard (Phase 5)

### P1 (Next Phase) - Production Cutover
- [ ] **Deploy to Production (Shadow Mode)** - Feature flags OFF, metrics running
- [ ] **Monitor 2-3 weeks**: match_score distribution, alias exception rate, vendor patterns
- [ ] **Vendor Threshold Override Architecture** - Per-vendor match score thresholds
- [ ] **Enable CREATE_DRAFT_HEADER** for controlled vendor subset

### P2 (Future)
- [ ] **Vendor Alias Manager UI** - create/edit/delete aliases from friction list
- [ ] **"Resolve and Link" UI Actions** - select vendor from candidates
- [ ] Transaction Level 3 (auto-create invoice lines)
- [ ] Real-time Email Watcher (Graph webhooks)
- [ ] Entra ID SSO

### P3 (Strategic)
- [ ] **Zetadocs Decommission Plan**
  - Phase A: Parallel run
  - Phase B: AP Invoices redirected to Hub
  - Phase C: Full intake cutover
  - Phase D: License removal

## Production Cutover Strategy
```
Step 1: Deploy with feature flags OFF
        ├── Draft creation disabled
        ├── Full metrics running
        ├── Matching + scoring active
        ├── Alias engine active
        └── Dashboard collecting real-world stats

Step 2: Analyze 2-3 weeks of metrics
        ├── % match_score >= 0.92 (should be high and stable)
        ├── Alias exception rate (should be low)
        ├── Fuzzy matches near threshold (should be small cluster)
        ├── NeedsReview volume (should be declining)
        └── Vendor-level automation rate (should be predictable)

Step 3: Enable Draft Creation for
        ├── AP_Invoice only
        ├── Limited vendor subset
        └── PO_REQUIRED documents first
```

## Safety Configuration
```python
DRAFT_CREATION_CONFIG = {
    "eligible_match_methods": ["exact_no", "exact_name", "normalized", "alias"],
    "min_match_score_for_draft": 0.92,
    "min_confidence_for_draft": 0.92,
    "duplicate_lookback_days": 365,
}
```

## Strategic Positioning for ELT
This is not just document management. This is:
- **Middleware Governance** - Controlled document flow with audit trails
- **Measurable Automation** - ROI proof with exact metrics
- **Vendor Data Hygiene** - Alias learning improves over time
- **BC-Safe Draft Staging** - No auto-posting, header-only, reversible
- **AI-Ready Ingestion** - Classification layer for future enhancements

## Non-Goals (Current Phase)
- No line creation (header only)
- No production enablement yet (shadow mode first)
- No Zetadocs retirement (parallel run first)
