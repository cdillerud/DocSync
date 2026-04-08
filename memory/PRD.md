# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning. Goal: maximize AI autonomy, shrink the Review Queue to near-zero.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI + Recharts
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph
- **Production**: Docker Compose on Azure VM at http://4.204.41.190:8080/

## What's Been Implemented (This Session)

### Phase 16g — PO Bypass + Vendor Bypass + Batch Alias (Apr 8)
- Direct vendor profile lookup for po_expected in readiness
- PATCH /api/vendor-intelligence/profiles/{vendor_no}/bypass
- POST /api/aliases/vendors/batch-resolve

### Phase 16h — Aggressive Auto-Processing Engine (Apr 8)
- Smart warning categorization (CRITICAL vs INFORMATIONAL)
- Lowered confidence thresholds
- Expanded auto-post (no AP-only restriction, cap 50, skip tracking)
- Posting template trust (medium/high → auto-upgrade)

### Phase 16i — Automation Rate Dashboard Widget (Apr 8)
- GET /api/readiness/automation-rate?days=N
- Circular gauge + Recharts BarChart + Top Manual Vendors

### Phase 16j — Missing Required Fields Fix (Apr 8)
- Broadened field lookup (5 vendor sources, normalized_fields, external_document_no)
- Downgraded missing_required_fields from BLOCKING to WARNING when vendor resolved
- Result: Blocked 423→110 (75% reduction), Automation Rate 76→88%

### Phase 16k — Auto-Approval Engine (Apr 8)
- POST /api/posting-patterns/review-queue/auto-approve
- Batch approves drafts from medium/high confidence vendors
- Result: Review Queue badge 544→42 (92% reduction)

### Phase 16l — Status Sync: The Inbox Fixer (Apr 8)

**Problem**: Inbox showed 515 "Needs Review" documents even though readiness said many were "ready_auto_draft". The readiness.status and document status fields were disconnected — readiness updated but the inbox-visible status field stayed "NeedsReview".

**Root cause**: `evaluate_and_persist()` updated readiness but never synced the document `status`. Auto-approve set `draft_review_status: "approved"` but left `status: "NeedsReview"`. The inbox queries the `status` field, not `readiness.status`.

**Fix — 3 changes:**

1. **evaluate_and_persist status sync**: After updating readiness, if status is ready_auto_draft/ready_auto_link AND document status is stuck on NeedsReview/Captured → auto-sets status to "ReadyForPost"

2. **Auto-approve status update**: When auto-approving drafts, now also sets `status: "ReadyForPost"` and `automation_decision: "auto_process"`

3. **POST /api/readiness/sync-status**: Bulk sync endpoint — finds ALL docs where readiness is ready but status is stuck, and all approved drafts still showing NeedsReview. Updates them to ReadyForPost in one sweep.

4. **Frontend**: "Sync Inbox Status" button on AI Learning page

**Expected production impact**: After deploy + clicking "Sync Inbox Status", hundreds of docs should move from inbox to ReadyForPost, dramatically shrinking the 515 pending review count.

## Production Deploy Steps
1. Save to Github → `git pull && docker compose up -d --build`
2. Click "Re-evaluate All Documents" (updates readiness + auto-syncs status)
3. Click "Auto-Approve Proven Drafts" (clears remaining draft queue)
4. Click "Sync Inbox Status" (catches any remaining stuck docs)
5. Refresh inbox — should see significant reduction

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P1: PO pending auto-retry queue

## Future / Backlog
- P2: Low-volume vendor review routing
- P2: Correction replay engine activation
- P2: Email sender → vendor mapping
- P2: Expand stable vendor criteria
- P3: server.py refactor (7,500+ lines)

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
