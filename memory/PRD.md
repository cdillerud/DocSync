# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning. Goal: maximize AI autonomy, shrink the Review Queue to near-zero.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI + Recharts
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph
- **Production**: Docker Compose on Azure VM at http://4.204.41.190:8080/

## What's Been Implemented

### Phase 16g-16k (Apr 8)
- PO Bypass, Vendor Bypass, Batch Alias Resolution
- Aggressive Auto-Processing Engine, Automation Rate Widget
- Missing Required Fields Fix, Auto-Approval Engine

### Phase 16m — Inbox Cleanup + Exception Queue (Apr 9)
- **Inbox: 134 → 17 → ~8 → Exception Queue**
- Root cause fix: auto-post service was reverting non-AP docs back to NeedsReview
- 20-rule force cleanup engine covering all document patterns
- Expanded TERMINAL_STATUSES (Validated, ReadyForPost, AutoFiled, Exception)
- Exception Queue: retry-failed endpoint + dedicated UI tab + auto-escalation

### Phase 16n — Vendor Matching Gap Closer (Apr 9)
**Problem**: 23 vendor match gaps, 8 unmatched vendors. Auto-suggestions were terrible quality (SC Warehouses → Group Warehouses?!). No way to manually search or dismiss.

**Fixes:**
1. **Improved Unmatched Vendors Endpoint** (`GET /api/aliases/vendors/unmatched-gaps`):
   - Name normalization merges duplicates ("SC Warehouses, LLC" = "SC Warehouses, LLC.")
   - Better fuzzy scoring: Jaccard word overlap + first-word bonus + abbreviation handling
   - Shows variants and sample files
   - Minimum score threshold raised from 0.30 to 0.40

2. **Manual BC Vendor Search** (`GET /api/aliases/vendors/search-bc?q=...`):
   - Searches bc_reference_cache + vendor_invoice_profiles by name/number
   - Returns scored results for manual matching

3. **Dismiss Unmatched** (`POST /api/aliases/vendors/dismiss-unmatched`):
   - Marks dismissed vendor docs as Completed + auto_cleared
   - For vendors not in BC or not real vendors

4. **Accept Suggestion with Variants** (`POST /api/aliases/vendors/accept-suggestion`):
   - Now creates aliases for ALL name variants at once
   - Re-validates affected docs immediately

5. **Frontend — Monitor Page**:
   - Vendor cards show variants, dismiss button, manual search input
   - Search results appear as blue clickable buttons
   - Dismiss button to clear non-vendor gaps

## Key API Endpoints
- POST /api/readiness/sync-status — Force cleanup (20-rule engine)
- POST /api/readiness/retry-failed — Batch retry → Exception Queue
- GET /api/readiness/exception-queue — Exception queue listing
- GET /api/readiness/inbox-diagnostic — Preview cleanup impact
- POST /api/readiness/reevaluate-all — Re-evaluate all docs
- GET /api/aliases/vendors/unmatched-gaps — Unmatched vendors with improved matching
- GET /api/aliases/vendors/search-bc?q= — Manual BC vendor search
- POST /api/aliases/vendors/dismiss-unmatched — Dismiss unmatched vendor
- POST /api/aliases/vendors/accept-suggestion — Accept alias with variants

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P1: PO pending auto-retry queue

## Future / Backlog
- P2: Low-volume vendor review routing
- P2: Correction replay engine activation
- P2: Email sender → vendor mapping
- P3: server.py refactor (7,500+ lines)

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
