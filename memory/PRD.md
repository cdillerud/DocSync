# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning. Goal: maximize AI autonomy via continuous learning and aggressive validation gap closure.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI + Recharts
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph
- **Production**: Docker Compose on Azure VM at http://4.204.41.190:8080/

## What's Been Implemented

### Phases 1-16f — See previous sessions

### Phase 16g — Robust PO Bypass + Vendor Processing Bypass + Batch Alias Resolution (Apr 8, 2026)

- Enhanced `evaluate_and_persist()` with direct vendor profile lookup for `po_expected` and `auto_process_bypass`
- New `PATCH /api/vendor-intelligence/profiles/{vendor_no}/bypass` for NOFACH-style vendors
- New `POST /api/aliases/vendors/batch-resolve` for SC Warehouses-style batch alias creation

### Phase 16h — Aggressive Auto-Processing: Inbox Reduction Engine (Apr 8, 2026)

**Problem**: Review Queue had 339 items and growing. Re-evaluation of 1733 docs found 151 corrections but posted 0 to BC.

**5 Fixes:**
1. **Smart Warning Categorization** — CRITICAL (policy_hold, customer_unresolved, vendor_needs_review, amount_anomaly, auto_escalation) vs INFORMATIONAL (po_missing, no_line_items, low_line_item_confidence). Only critical count toward ambiguous threshold.
2. **Lowered Confidence Thresholds** — Informational-only warnings auto-draft regardless. Critical: 0.75 (was 0.80).
3. **Expanded Auto-Post** — Removed AP-only doc type restriction, cap 25→50, added skip reason tracking.
4. **Posting Template Trust** — Medium/high templates (5+ invoices) auto-upgrade needs_review → ready_auto_draft.
5. **Frontend Enhanced** — Re-evaluation shows auto-posted count + skip reasons.

### Phase 16i — Automation Rate Dashboard Widget (Apr 8, 2026)

**New feature**: Real-time Automation Rate widget on AI Learning page.

**Backend**: `GET /api/readiness/automation-rate?days=N`
- Current automation rate % (auto-processed / total)
- BC posting rate %
- Breakdown: auto-processed, manual review, blocked, BC posted
- Daily trend: auto vs manual vs blocked per day (bar chart data)
- Top 10 vendors requiring manual review with primary reason
- Selectable period (7d / 30d / 90d)

**Frontend**: `AutomationRateWidget` component
- Circular SVG gauge with color-coded rate (green >70%, amber >40%, red <40%)
- 4-box breakdown (Auto-Processed, Manual Review, Blocked, Posted to BC)
- Recharts BarChart with stacked daily auto/manual/blocked
- Top Manual Review Vendors list with primary reason badges
- Period selector buttons (7d / 30d / 90d)

**Files changed:**
- `/app/backend/routers/readiness.py` — New GET /automation-rate endpoint
- `/app/frontend/src/pages/LearningDashboard.js` — AutomationRateWidget + recharts import

## Active Gap Closers: 10
## Backfill Steps: 15
## Learning Dimensions: 21

## Pending Production Steps
1. Deploy: Save to Github → `git pull && docker compose up -d --build` on Azure VM
2. For NOFACH: `PATCH /api/vendor-intelligence/profiles/NOFACH/bypass?enabled=true`
3. For SC Warehouses: `POST /api/aliases/vendors/batch-resolve` with correct vendor_no
4. Re-evaluate: `POST /api/readiness/reevaluate-all`
5. Monitor Automation Rate widget — should show rate increasing

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P1: PO pending auto-retry queue

## Future / Backlog
- P2: Low-volume vendor review routing
- P2: Correction replay engine activation
- P2: Email sender → vendor mapping
- P2: Expand stable vendor criteria for Auto-Ready
- P3: server.py refactor (7,500+ lines)

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
