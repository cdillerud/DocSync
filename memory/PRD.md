# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning. Goal: maximize AI autonomy, shrink the Review Queue to near-zero.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI + Recharts
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph
- **Production**: Docker Compose on Azure VM at http://4.204.41.190:8080/

## What's Been Implemented

### Phases 1-16f — See previous sessions

### Phase 16g — PO Bypass + Vendor Bypass + Batch Alias (Apr 8, 2026)
- Direct vendor profile lookup for `po_expected` in readiness
- PATCH /api/vendor-intelligence/profiles/{vendor_no}/bypass
- POST /api/aliases/vendors/batch-resolve

### Phase 16h — Aggressive Auto-Processing Engine (Apr 8, 2026)
- Smart warning categorization (CRITICAL vs INFORMATIONAL)
- Lowered confidence thresholds
- Expanded auto-post (no AP-only restriction, cap 50, skip tracking)
- Posting template trust (medium/high → auto-upgrade)

### Phase 16i — Automation Rate Dashboard Widget (Apr 8, 2026)
- GET /api/readiness/automation-rate?days=N
- Circular gauge + Recharts BarChart + Top Manual Vendors

### Phase 16j — Missing Required Fields Fix (Apr 8, 2026)
- Broadened field lookup (5 vendor sources, normalized_fields, external_document_no)
- Downgraded missing_required_fields from BLOCKING to WARNING when vendor resolved
- BOL/shipping docs only require vendor (not invoice_number/amount)

### Phase 16k — Auto-Approval Engine: The Queue Shrinker (Apr 8, 2026)

**Problem**: Review Queue at 644 and growing. Investigation revealed the badge counts auto-drafted PIs pending human review (`auto_draft_created=True, draft_review_status NOT IN [approved, corrected]`). The system creates 544 drafts but 0 get approved automatically — they ALL sit in queue.

**Root cause**: No auto-approval logic exists. Every draft requires manual human review, even from vendors with proven posting templates (TUMALOC: 374 invoices analyzed, high confidence).

**Fix: POST /api/posting-patterns/review-queue/auto-approve**
- Batch auto-approves drafts from vendors with proven posting templates
- Checks: template confidence >= medium AND invoices_analyzed >= 5
- Dry-run mode (preview without approving)
- Per-vendor result tracking (top_approved_vendors, skip_reasons)
- Creates positive feedback events (posting_learning_events)
- Frontend: "Preview Auto-Approve" and "Auto-Approve Proven Drafts" buttons

**Also identified**: 412 docs blocked by `missing_required_fields` (mostly missing invoice_number). Even known vendors (TUMALOC, CARGOMO, ROTONDO) are affected. Vendor IS resolved, amount IS present, but invoice_number missing from extracted_fields.

**Blocking reason distribution (production):**
- missing_required_fields: 412
- vendor_unresolved: 101  
- duplicate_risk: 24

**Files changed:**
- `/app/backend/routers/posting_patterns.py` — New auto-approve endpoint
- `/app/frontend/src/pages/LearningDashboard.js` — Auto-approve UI buttons + results

## Production Deploy Steps
1. Save to Github → `git pull && docker compose up -d --build`
2. Click "Preview Auto-Approve" to see how many drafts qualify
3. Click "Auto-Approve Proven Drafts" to approve them — Review Queue badge drops
4. Click "Re-evaluate All Documents" — fixes blocked docs (Phase 16j field fixes)
5. Check Automation Rate widget

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
