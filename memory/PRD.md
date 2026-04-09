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

### Phase 16m — Force Cleanup Engine + Queue View Fix (Apr 9)

**Problem**: Inbox showed ~134 active docs, ~119 pending review. Two root causes:
1. "ReadyForPost" and "Validated" statuses were NOT in TERMINAL_STATUSES, so docs with these statuses stayed in the queue view
2. `$or` key collision bug in MongoDB queries meant cleanup rules weren't matching correctly

**Fixes:**

1. **Expanded TERMINAL_STATUSES** in queue view filter (`documents.py`) and frontend `isTerminal`:
   Added: Validated, ValidationPassed, ReadyForPost, AutoFiled, LinkedToBC
   Effect: ~15-20 "Validated" docs immediately disappear from inbox on deploy

2. **7-Rule Force Cleanup Engine** (`POST /api/readiness/sync-status`):
   - Rule 1: Has BC Purchase Invoice -> Completed
   - Rule 2: Draft approved -> Completed
   - Rule 3: Auto-draft created -> Completed
   - Rule 4: Readiness ready + no blockers -> Completed
   - Rule 5: Vendor resolved + fields complete -> Completed
   - Rule 6: ReadyForPost (legacy) -> Completed
   - Rule 7: Readiness ready catchall -> Completed
   - Uses `$and` query construction to avoid `$or` key collisions

3. **Inbox Diagnostic** (`GET /api/readiness/inbox-diagnostic`):
   Preview cleanup impact before running

4. **evaluate_and_persist**: Sets terminal `Completed` + `auto_cleared=True` instead of "ReadyForPost"

5. **Frontend**: "Force Cleanup Inbox" button with per-rule results display

## Production Deploy Steps
1. Save to Github -> `git pull && docker compose up -d --build`
2. Refresh inbox -> "Validated" docs should already be gone
3. Click "Re-evaluate All Documents" on AI Learning page
4. Click "Force Cleanup Inbox" -> moves ready docs to Completed
5. Refresh inbox -> should see dramatic reduction to only genuinely blocked docs

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
