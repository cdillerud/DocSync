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
- [x] Full backend API (30+ endpoints)
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
- [x] Vendor/customer candidates for review UI
- [x] Resolve and Link endpoint

### Phase 2.2 - Audit Dashboard & Intelligence Layer ✅ (NEW)
- [x] **Automation Metrics Engine**
  - Status distribution (LinkedToBC, NeedsReview, etc.)
  - Confidence histogram (90-100%, 80-90%, 70-80%, <70%)
  - Job type breakdown with auto-rate
  - Duplicate prevention counter
- [x] **Vendor Friction Index**
  - Exception rate by vendor
  - Auto-match rate by vendor
  - Friction score (identifies alias opportunities)
- [x] **Alias Impact Metrics**
  - Match method distribution (exact, normalized, alias, fuzzy)
  - Alias contribution percentage
  - Top used aliases
- [x] **Resolution Time Tracking**
  - Median, P95, average resolution times
  - Breakdown by job type
- [x] **Daily Trend Charts**
  - Document volume over time
  - Auto-link rate trends
- [x] **Vendor Alias Engine**
  - CRUD for alias mappings
  - "Save as alias?" suggestion on manual resolution
  - Normalized alias storage for fuzzy matching
  - Usage tracking per alias

### Audit Dashboard Capabilities
| Metric | Purpose | ELT Value |
|--------|---------|-----------|
| Auto-Link Rate | % documents auto-linked | Automation adoption |
| Review Rate | % requiring human review | Labor reduction target |
| Duplicates Blocked | Invoices prevented from double-entry | Risk avoidance ($) |
| Median Resolution | Time from Received to Linked | Efficiency proof |
| Vendor Friction Index | Vendors causing most exceptions | Alias ROI targeting |
| Alias Contribution | % matches via learned aliases | Compounding intelligence |

### Testing Results (Latest - Feb 18, 2026)
- Backend: 100% (19/19 tests passed)
- Frontend: 100% (all 4 tabs verified)
- 1 bug fixed (MongoDB _id serialization in alias suggest)

## Key API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/metrics/automation` | GET | Status distribution, confidence, job type stats |
| `/api/metrics/vendors` | GET | Vendor friction index |
| `/api/metrics/alias-impact` | GET | Alias learning metrics |
| `/api/metrics/resolution-time` | GET | Processing time statistics |
| `/api/metrics/daily` | GET | Daily trend data |
| `/api/aliases/vendors` | GET/POST | Alias management |
| `/api/aliases/vendors/suggest` | GET | Suggest alias on resolution |

## Prioritized Backlog

### P0 (Complete) ✅
- [x] BC document attachment
- [x] AI classification
- [x] Production validation
- [x] Audit Dashboard

### P1 (Next Phase)
- [ ] **Vendor Alias Manager UI** - Create aliases from friction list
- [ ] **CREATE_DRAFT Safety Layers** for AP Invoices:
  - Vendor match gate (fuzzy >= 0.92 for draft)
  - Duplicate hard stop (same vendor + invoice# + 365 days)
  - Header-only first (no auto-lines)
- [ ] Entra SSO authentication

### P2 (Future)
- [ ] Exchange Online email polling
- [ ] Bulk upload support
- [ ] Export audit logs to CSV
- [ ] Sales PO full flip

## Strategic Status
- **Level 2: Intelligent Link Engine** ✅ COMPLETE
- **Level 3: Transaction Automation Engine** - NEXT (with safety layers)

## Business Case Proof Points (from Dashboard)
- Auto-Link Rate: % of documents auto-linked
- Duplicate Prevention: invoices blocked from double-entry
- Resolution Time: reduced from manual to automated
- Alias Learning: auto-match rate improvement over time
