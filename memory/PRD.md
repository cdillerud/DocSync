# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning. Goal: maximize AI autonomy, shrink the Review Queue to near-zero.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI + Recharts
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph
- **Production**: Docker Compose on Azure VM at http://4.204.41.190:8080/

## What's Been Implemented

### Phase 16g-16k (Apr 8) — Previous Session
- PO Bypass, Vendor Bypass, Batch Alias Resolution
- Aggressive Auto-Processing Engine (smart warning categorization)
- Automation Rate Dashboard Widget
- Missing Required Fields Fix (blocked 423->110)
- Auto-Approval Engine (review queue 544->42)

### Phase 16m — Force Cleanup Engine + Status Revert Bug Fix (Apr 9)

**Problem 1 — Queue View**: "Validated", "ReadyForPost" etc. were NOT in TERMINAL_STATUSES, keeping them visible in inbox.
**Fix**: Expanded TERMINAL_STATUSES in both backend queue filter and frontend isTerminal.

**Problem 2 — Status Revert Bug (ROOT CAUSE of 982 skipped docs)**: `attempt_ap_auto_post()` was called on ALL non-sales docs (shipping, inventory, BOLs, etc.) during reevaluation. When these failed the AP check ("Not classified as AP_Invoice"), the function REVERTED their status back to `NeedsReview` + `auto_cleared: false` — undoing any progress made by the readiness engine.
**Fix**:
- `attempt_ap_auto_post`: Non-AP docs that fail the type check now get a soft skip (no status revert). Only genuine AP docs that fail validation get reverted to NeedsReview.
- `batch_reevaluate_all`: Auto-act now only targets AP-type documents (invoice, credit, purchase), skipping shipping/inventory/BOL/unknown docs entirely.

**Problem 3 — Force Cleanup**: 7-rule engine to move ready docs to terminal Completed status.

## Production Deploy Steps
1. Save to Github -> `git pull && docker compose up -d --build`
2. Refresh inbox -> "Validated" docs should already be gone (TERMINAL_STATUSES fix)
3. Click "Re-evaluate All Documents" -> no more mass revert to NeedsReview
4. Click "Force Cleanup Inbox" -> moves remaining ready docs to Completed
5. Refresh inbox -> should see dramatic reduction

## Key API Endpoints
- POST /api/readiness/sync-status - Force cleanup (7-rule engine)
- GET /api/readiness/inbox-diagnostic - Preview cleanup impact
- POST /api/readiness/reevaluate-all - Re-evaluate all docs
- POST /api/posting-patterns/review-queue/auto-approve - Auto-approve drafts
- GET /api/readiness/automation-rate - Automation metrics

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P1: PO pending auto-retry queue

## Future / Backlog
- P2: Low-volume vendor review routing
- P2: Correction replay engine activation
- P2: Email sender -> vendor mapping
- P3: server.py refactor (7,500+ lines)

## Deployment
Docker Compose on Azure VM. "Save to Github" -> `git pull && docker compose up -d --build`.
