# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning. Goal: maximize AI autonomy, shrink the Review Queue to near-zero.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI + Recharts
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph
- **Production**: Docker Compose on Azure VM at http://4.204.41.190:8080/

## What's Been Implemented

### Phase 16g — PO Bypass + Vendor Bypass + Batch Alias (Apr 8)
- Direct vendor profile lookup for po_expected in readiness
- PATCH /api/vendor-intelligence/profiles/{vendor_no}/bypass
- POST /api/aliases/vendors/batch-resolve

### Phase 16h — Aggressive Auto-Processing Engine (Apr 8)
- Smart warning categorization (CRITICAL vs INFORMATIONAL)
- Lowered confidence thresholds
- Expanded auto-post (no AP-only restriction, cap 50, skip tracking)
- Posting template trust (medium/high -> auto-upgrade)

### Phase 16i — Automation Rate Dashboard Widget (Apr 8)
- GET /api/readiness/automation-rate?days=N
- Circular gauge + Recharts BarChart + Top Manual Vendors

### Phase 16j — Missing Required Fields Fix (Apr 8)
- Broadened field lookup (5 vendor sources, normalized_fields, external_document_no)
- Downgraded missing_required_fields from BLOCKING to WARNING when vendor resolved
- Result: Blocked 423->110 (75% reduction), Automation Rate 76->88%

### Phase 16k — Auto-Approval Engine (Apr 8)
- POST /api/posting-patterns/review-queue/auto-approve
- Batch approves drafts from medium/high confidence vendors
- Result: Review Queue badge 544->42 (92% reduction)

### Phase 16l — Status Sync: The Inbox Fixer (Apr 8)
- evaluate_and_persist status sync for ready docs
- Auto-approve status update to ReadyForPost

### Phase 16m — Force Cleanup Engine (Apr 9) [LATEST]

**Problem**: Even after Phase 16l, Inbox still showed ~496 "Needs Review" documents. Root cause: "ReadyForPost" is NOT in TERMINAL_STATUSES, so docs moved to ReadyForPost still appeared in the queue view. Additionally, a Python dict `$or` key collision bug meant some MongoDB queries weren't filtering correctly.

**Fix — 3 changes:**

1. **7-Rule Force Cleanup Engine** (`POST /api/readiness/sync-status`):
   - Rule 1: Has BC Purchase Invoice -> Completed
   - Rule 2: Draft approved -> Completed
   - Rule 3: Auto-draft created -> Completed
   - Rule 4: Readiness ready + no blockers -> Completed
   - Rule 5: Vendor resolved + fields complete -> Completed
   - Rule 6: ReadyForPost (legacy) -> Completed
   - Rule 7: Readiness ready catchall -> Completed
   - Uses `$and` query construction to avoid `$or` key collisions

2. **Inbox Diagnostic** (`GET /api/readiness/inbox-diagnostic`):
   - Preview what force cleanup would do before running it
   - Shows breakdown by status, readiness, bc_pi, draft status

3. **evaluate_and_persist terminal sync**: Now sets status to "Completed" + `auto_cleared=True` instead of "ReadyForPost", ensuring docs leave the queue view immediately

**Frontend**: "Force Cleanup Inbox" button with detailed results display showing per-rule counts

## Production Deploy Steps
1. Save to Github -> `git pull && docker compose up -d --build`
2. Click "Re-evaluate All Documents" (updates readiness + auto-syncs status)
3. Click "Auto-Approve Proven Drafts" (clears remaining draft queue)
4. Click "Force Cleanup Inbox" (moves all clearable docs to Completed)
5. Refresh inbox -> should see dramatic reduction to only genuinely blocked docs

## Key API Endpoints
- POST /api/readiness/sync-status - Force cleanup (7-rule engine)
- GET /api/readiness/inbox-diagnostic - Preview cleanup impact
- POST /api/readiness/reevaluate-all - Re-evaluate all docs
- POST /api/posting-patterns/review-queue/auto-approve - Auto-approve drafts
- GET /api/readiness/automation-rate - Automation metrics
- GET /api/readiness/metrics - Readiness analytics

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P1: PO pending auto-retry queue

## Future / Backlog
- P2: Low-volume vendor review routing
- P2: Correction replay engine activation
- P2: Email sender -> vendor mapping
- P2: Expand stable vendor criteria
- P3: server.py refactor (7,500+ lines)

## Deployment
Docker Compose on Azure VM. "Save to Github" -> `git pull && docker compose up -d --build`.
