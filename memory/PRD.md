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
- Aggressive Auto-Processing Engine
- Automation Rate Dashboard Widget
- Missing Required Fields Fix (blocked 423->110)
- Auto-Approval Engine (review queue 544->42)

### Phase 16m — Force Cleanup + Exception Queue (Apr 9)

**Inbox Shrinkage: 134 → 17 → ~8 (then to Exception Queue)**

1. **Root Cause Fix — Auto-Post Status Revert Bug**:
   - `attempt_ap_auto_post()` was reverting non-AP docs (shipping, inventory) back to NeedsReview
   - Fixed: non-AP docs get soft skip, only real AP failures revert
   - Auto-act now only targets AP-type documents

2. **Expanded TERMINAL_STATUSES**: Added Validated, ReadyForPost, AutoFiled, LinkedToBC, Exception
   - Immediate effect: Validated docs leave the inbox on deploy

3. **20-Rule Force Cleanup Engine** (`POST /api/readiness/sync-status`):
   - Rules 1-7: BC PI, draft approved, auto-draft, readiness ready, vendor resolved, ReadyForPost, catchall
   - Rules 8-9: Non-AP doc types (shipping, inventory, BOL) with/without vendor
   - Rules 10-11: Auto-post attempted + vendor, reverted non-AP docs
   - Rules 12-15: Junk files (.jpg/.xlsx), statements/SOA, self-vendor (Gamer Packaging), W9/tax forms
   - Rules 16-20: Captured/stale docs, XML duplicates, AR invoices, broad self-vendor, duplicate filenames

4. **Exception Queue System**:
   - `POST /api/readiness/retry-failed` — batch retry extraction-failed docs
     - Normal mode: increments retry_count (4 max)
     - Force mode (`force_escalate=true`): immediately moves all to Exception Queue
   - `GET /api/readiness/exception-queue` — paginated list of exception docs
   - Exception status = terminal → docs leave main Inbox
   - Frontend: "Exceptions" tab in Inbox, "Retry Failed → Exception Queue" button on AI Learning page
   - Config: `auto_escalate_on_max_retries: True` (was auto_delete)

## Production Deploy & Run Sequence
1. Save to Github → `git pull && docker compose up -d --build`
2. Refresh inbox → Validated docs gone immediately
3. AI Learning page: "Re-evaluate All Documents"
4. "Force Cleanup Inbox"
5. "Retry Failed → Exception Queue" (moves remaining stuck docs)
6. Check Inbox → Exceptions tab for human review items

## Key API Endpoints
- POST /api/readiness/sync-status — Force cleanup (20-rule engine)
- POST /api/readiness/retry-failed — Batch retry → Exception Queue
- GET /api/readiness/exception-queue — Exception queue listing
- GET /api/readiness/inbox-diagnostic — Preview cleanup impact
- POST /api/readiness/reevaluate-all — Re-evaluate all docs
- POST /api/posting-patterns/review-queue/auto-approve — Auto-approve drafts
- GET /api/readiness/automation-rate — Automation metrics

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
