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

### Phase 3 - Alias Impact Integration ✅ (NEW)
- [x] **Match Method Tracking** on every document:
  - `exact_no`, `exact_name`, `normalized`, `alias`, `fuzzy`, `manual`, `none`
  - Stored as `match_method` and `match_score` fields
- [x] **Metrics Enhancement**:
  - `match_method_breakdown`: Count of each match method
  - `alias_auto_linked`: Documents auto-linked via alias
  - `alias_exception_rate`: Exception rate for alias matches
- [x] **Vendor Friction ROI Signal**:
  - `has_alias`: Boolean per vendor
  - `alias_matches`: Count of alias-based matches
  - `roi_hint`: "Creating alias could reduce review rate from X% to Y%"
- [x] **Safe Reprocess Endpoint** (`POST /api/documents/{id}/reprocess`):
  - Re-runs validation + vendor match only
  - Does NOT duplicate SharePoint uploads
  - Does NOT create new BC records if already linked
  - Idempotent - safe to call multiple times
  - Logs reprocess event in audit trail

### Document Status Flow
```
Received → StoredInSP → Classified → LinkedToBC
                    ↘ NeedsReview → [Reprocess] → LinkedToBC (if alias matches)
                                  ↘ [Resolve] → LinkedToBC
```

### Match Method Distribution
| Method | Description |
|--------|-------------|
| exact_no | Exact match on Vendor/Customer No |
| exact_name | Exact match on display name |
| normalized | Normalized match (strip Inc, LLC, etc.) |
| alias | Match via vendor alias mapping |
| fuzzy | Fuzzy token-based match |
| manual | User manually selected from candidates |
| none | No match found |

### Testing Results (Latest - Feb 18, 2026)
- Backend: 100% (21/21 Phase 3 tests passed)
- Frontend: 100% (all 4 tabs verified)
- Reprocess idempotency verified
- No SP/BC duplication confirmed

## Key API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/documents/{id}/reprocess` | POST | Safe reprocess - re-validates without duplication |
| `/api/metrics/automation` | GET | Match method breakdown, alias metrics |
| `/api/metrics/vendors` | GET | Vendor friction with ROI hints |
| `/api/aliases/vendors` | GET/POST | Alias CRUD |

## Prioritized Backlog

### P0 (Complete) ✅
- [x] BC document attachment
- [x] AI classification
- [x] Production validation
- [x] Audit Dashboard
- [x] Alias impact tracking

### P1 (Next Phase)
- [ ] **CREATE_DRAFT Safety Layers** for AP Invoices:
  - Vendor match gate (fuzzy >= 0.92 for draft)
  - Duplicate hard stop (same vendor + invoice# + 365 days)
  - Header-only first (no auto-lines)
- [ ] Vendor Alias Manager UI - create from friction list
- [ ] Entra SSO authentication

### P2 (Future)
- [ ] Exchange Online email polling
- [ ] Bulk reprocess button for eligible documents
- [ ] Export audit logs to CSV
- [ ] Sales PO full flip

## Strategic Status
- **Level 2: Intelligent Link Engine** ✅ COMPLETE
- **Level 3: Transaction Automation Engine** - NEXT (with safety layers)

## Business Case Proof Points (from Dashboard)
```
Week 1: 16.7% auto-link
Week 3: 42% auto-link (after alias learning)
Week 6: 63% auto-link
Alias-driven improvement: +21%
```

## Non-Goals (This Phase)
- No CREATE_DRAFT yet
- No UI redesign
- No schema changes to Job Type config
- No SharePoint changes
