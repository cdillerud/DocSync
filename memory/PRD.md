# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning. Goal: maximize AI autonomy, shrink the Review Queue to near-zero.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI + Recharts
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph
- **Production**: Docker Compose on Azure VM

## Implemented This Session (Apr 9, 2026)

### Phase 16m — Inbox Cleanup + Exception Queue
- **Inbox: 134 → 17 → ~8** via 20-rule force cleanup engine
- Root cause fix: auto-post reverting non-AP docs to NeedsReview
- Exception Queue: retry-failed endpoint + UI tab + auto-escalation
- Expanded TERMINAL_STATUSES (Validated, ReadyForPost, AutoFiled, Exception)

### Phase 16n — Vendor Matching Gap Closer
- Improved fuzzy matching (Jaccard + first-word bonus + abbreviation handling)
- Name normalization merges duplicate vendor variants
- Manual BC vendor search endpoint
- Dismiss unmatched vendor functionality
- Accept suggestion with all variants at once

### Phase 16o — PO Auto-Retry Queue
- **Problem**: 12 PO validation gaps, mostly TUMALOC (7) invoices arriving before POs
- `POST /api/readiness/po-pending/park` — finds and parks PO-gap docs
- `POST /api/readiness/po-pending/retry` — full readiness re-evaluation
- `GET /api/readiness/po-pending` — view the queue
- **Background scheduler** runs every 4 hours automatically
- After 3 days (18 retries) → escalates to Exception Queue
- "PO Pending" tab in Inbox UI
- "Park PO Pending" button on AI Learning page
- `po_pending` workflow_status excluded from main inbox view

## Key API Endpoints
- POST /api/readiness/sync-status — Force cleanup (20-rule engine)
- POST /api/readiness/retry-failed — Batch retry → Exception Queue
- POST /api/readiness/po-pending/park — Park PO-gap docs
- POST /api/readiness/po-pending/retry — Re-evaluate PO-pending docs
- GET /api/readiness/po-pending — PO pending queue
- GET /api/readiness/exception-queue — Exception queue
- GET /api/readiness/inbox-diagnostic — Preview cleanup impact
- POST /api/readiness/reevaluate-all — Re-evaluate all docs
- GET /api/aliases/vendors/unmatched-gaps — Unmatched vendors
- GET /api/aliases/vendors/search-bc?q= — Manual BC vendor search
- POST /api/aliases/vendors/dismiss-unmatched — Dismiss vendor
- POST /api/aliases/vendors/accept-suggestion — Accept alias with variants

## Test Results This Session
- Iteration 197: 20/20 (readiness endpoints)
- Iteration 198: 21/21 (exception queue)
- Iteration 199: 30/30 (vendor matching)
- Iteration 200: 26/26 (PO auto-retry queue)
- **Total: 97/97 tests passed (100%)**

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration

## Future / Backlog
- P2: Low-volume vendor review routing
- P2: Correction replay engine activation
- P2: Email sender → vendor mapping
- P3: server.py refactor (7,500+ lines)

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
