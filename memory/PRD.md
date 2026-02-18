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

### Phase 4 - CREATE_DRAFT_HEADER (Sandbox) ✅ NEW
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
- [x] **Metrics Integration**:
  - `draft_created_count`: Number of drafts created
  - `draft_creation_rate`: % of LinkedToBC that are drafts
  - `draft_feature_enabled`: Current flag state
  - `header_only_flag`: Always true (no lines yet)

### Document Status Flow (Updated)
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

### Phase 4 API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/settings/features/create-draft-header` | GET | Get draft creation feature status |
| `/api/settings/features/create-draft-header` | POST | Toggle draft creation feature |
| `/api/settings/status` | GET | Now includes `features` section |
| `/api/metrics/automation` | GET | Now includes draft metrics |

### Testing Results (Latest - Feb 18, 2026)
- Backend: 100% (47/47 tests - 26 Phase 4 + 21 Phase 3)
- All safety gates verified
- Idempotency guards tested
- No duplicate draft creation
- Reprocess never creates drafts

## Key API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/documents/{id}/reprocess` | POST | Safe reprocess - re-validates, links only (no drafts) |
| `/api/metrics/automation` | GET | Match methods, alias metrics, draft metrics |
| `/api/metrics/vendors` | GET | Vendor friction with ROI hints |
| `/api/aliases/vendors` | GET/POST | Alias CRUD |
| `/api/settings/features/create-draft-header` | GET/POST | Draft creation feature toggle |

## Prioritized Backlog

### P0 (Complete) ✅
- [x] BC document attachment
- [x] AI classification
- [x] Production validation
- [x] Audit Dashboard
- [x] Alias impact tracking
- [x] CREATE_DRAFT_HEADER backend (Phase 4)

### P1 (Next Phase)
- [ ] **Enable CREATE_DRAFT_HEADER in Production** (after 7-day sandbox monitoring)
- [ ] **Vendor Alias Manager UI** - create/edit/delete aliases from friction list
- [ ] **"Resolve and Link" UI Actions** - select vendor from candidates
- [ ] Entra SSO authentication

### P2 (Future)
- [ ] Transaction Automation Level 3 (auto-create invoice lines)
- [ ] Real-time Email Watcher (Graph webhooks)
- [ ] Bulk reprocess button for eligible documents
- [ ] Export audit logs to CSV
- [ ] Sales PO full flip

## Strategic Status
- **Level 2: Intelligent Link Engine** ✅ COMPLETE
- **Level 3: Transaction Automation Engine** ✅ BACKEND COMPLETE (Sandbox)
- **Next**: Enable in production after monitoring

## Safety Configuration
```python
DRAFT_CREATION_CONFIG = {
    "eligible_match_methods": ["exact_no", "exact_name", "normalized", "alias"],
    "min_match_score_for_draft": 0.92,
    "min_confidence_for_draft": 0.92,
    "duplicate_lookback_days": 365,
}
```

## Non-Goals (This Phase)
- No line creation (header only)
- No UI redesign
- No production enablement (sandbox only)
- No job type schema changes
- No SharePoint logic changes
