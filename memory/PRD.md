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
- [x] **Purchase Invoice Draft Creation** for AP_Invoice only
- [x] **Safety Preconditions** enforced (match_score ≥0.92, confidence ≥0.92)
- [x] **Duplicate Check**: Vendor + External Doc No before creation
- [x] **Idempotency**: Reprocess NEVER creates drafts, bc_record_id guard
- [x] **Transaction Tracking**: NONE/LINKED_ONLY/DRAFT_CREATED

### Phase 5 - ELT ROI Dashboard ✅
- [x] **ROI Summary Tab** (default tab) with 4 sections
- [x] Automation Overview with trend chart
- [x] Alias Impact — Data Hygiene ROI
- [x] Vendor Friction Matrix (sortable)
- [x] Draft Creation Confidence (conditional)
- [x] Executive Summary box

### Phase 6 - Shadow Mode Instrumentation ✅ NEW
- [x] **Match Score Distribution Endpoint**
  - `GET /api/metrics/match-score-distribution?from=&to=`
  - Histogram buckets: 0.95-1.00, 0.92-0.95, 0.88-0.92, <0.88
  - Summary with high_confidence_pct and interpretation
  - Method breakdown per bucket
- [x] **Enhanced Alias Exception Tracking**
  - `GET /api/metrics/alias-exceptions?days=14`
  - alias_totals (total, success, needs_review, exception_rate)
  - Daily trend (7 days)
  - Top 10 vendors by alias exceptions
  - Top 10 vendors by alias contribution (60%+)
- [x] **Vendor Stability Analysis**
  - `GET /api/metrics/vendor-stability?days=14`
  - Categories: low_automation, high_score_high_exception, consistently_high_confidence
  - Threshold override candidates for future vendor-specific thresholds
- [x] **Shadow Mode Status**
  - `GET /api/settings/shadow-mode`
  - Feature flag status (CREATE_DRAFT_HEADER, DEMO_MODE)
  - Shadow mode start date and days running
  - Health indicators (7-day rolling): high_confidence_pct, alias_exception_rate, top_friction_vendor
  - Readiness assessment with pass/fail criteria
  - `POST /api/settings/shadow-mode` to set start date and notes
- [x] **Shadow Mode Performance Report (ELT)**
  - `GET /api/reports/shadow-mode-performance?days=14`
  - Readiness score (0-100) based on 4 factors:
    - High Confidence Documents (30 pts)
    - Alias Exception Rate (25 pts)
    - Overall Automation Rate (25 pts)
    - Data Volume (20 pts)
  - Match score analysis with buckets and interpretation
  - Alias engine performance with daily trend
  - Vendor friction analysis
  - Next steps recommendations
- [x] **Frontend Updates**
  - Match Score Distribution chart with 4 colored buckets + bar chart
  - Shadow Mode Status card with feature flags, readiness, health indicators

### Testing Results (Latest - Feb 18, 2026)
- Phase 6: 40/40 backend tests passed, 100% frontend verified
- All previous phases: Fully tested and working

## Key API Endpoints

### Core Operations
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/documents/intake` | POST | Main document intake (email parser) |
| `/api/documents/{id}/resolve` | POST | Manual link for NeedsReview docs |
| `/api/documents/{id}/reprocess` | POST | Safe reprocess (no drafts) |

### Phase 6: Shadow Mode Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/metrics/match-score-distribution` | GET | Histogram buckets for threshold analysis |
| `/api/metrics/alias-exceptions` | GET | Alias exception tracking + daily trend |
| `/api/metrics/vendor-stability` | GET | Vendor categorization for threshold overrides |
| `/api/settings/shadow-mode` | GET | Feature flags + readiness assessment |
| `/api/settings/shadow-mode` | POST | Set start date and notes |
| `/api/reports/shadow-mode-performance` | GET | Comprehensive ELT report |

### Other Metrics
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/metrics/automation` | GET | Overall automation metrics |
| `/api/metrics/vendors` | GET | Vendor friction with ROI hints |
| `/api/metrics/alias-impact` | GET | Alias contribution metrics |
| `/api/settings/features/create-draft-header` | GET/POST | Draft creation toggle |

## Prioritized Backlog

### P0 (Complete) ✅
- [x] BC document attachment
- [x] AI classification
- [x] Production validation
- [x] Audit Dashboard
- [x] Alias impact tracking
- [x] CREATE_DRAFT_HEADER backend
- [x] ELT ROI Dashboard
- [x] Shadow Mode Instrumentation

### P1 (Next Phase) - Production Deployment
- [ ] **Set shadow_mode_started_at** via POST /api/settings/shadow-mode
- [ ] **Monitor 2-3 weeks** watching:
  - Match score distribution (want 80%+ above 0.92)
  - Alias exception rate (want <10%)
  - Vendor friction patterns
- [ ] **Vendor Threshold Override Architecture** (when data supports it)
- [ ] **Enable CREATE_DRAFT_HEADER** for controlled vendor subset

### P2 (Future)
- [ ] Vendor Alias Manager UI
- [ ] "Resolve and Link" UI Actions
- [ ] Transaction Level 3 (auto-create invoice lines)
- [ ] Real-time Email Watcher (Graph webhooks)
- [ ] Entra ID SSO

### P3 (Strategic)
- [ ] Zetadocs Decommission Plan

## Production Cutover Strategy
```
Step 1: Deploy with feature flags OFF ← READY
        ├── CREATE_DRAFT_HEADER: OFF
        ├── All metrics running
        ├── Shadow mode instrumentation active
        └── Set shadow_mode_started_at

Step 2: Observe 2-3 weeks
        ├── Match score distribution
        ├── Alias exception rate trend
        ├── Vendor friction stability
        └── Monitor readiness_score in reports

Step 3: Enable draft creation when
        ├── readiness_score >= 80
        ├── high_confidence_pct >= 60%
        ├── alias_exception_rate < 10%
        └── sufficient_data (50+ docs)
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

## Shadow Mode Notes Storage
Use POST /api/settings/shadow-mode to record:
- Production deploy date
- Vendor onboarding changes
- Alias import events
- Any known data changes

Example:
```json
{
  "shadow_mode_started_at": "2026-02-18T10:00:00Z",
  "shadow_mode_notes": "Production deploy. 3 vendor aliases pre-loaded."
}
```
