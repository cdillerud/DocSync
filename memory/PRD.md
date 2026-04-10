# GPI Document Hub — Product Requirements Document

## Original Problem Statement
Build and continuously refine the Sales/AP Modules and Document Inbox with AI autonomy and continuous learning. Goal: aggressively shrink the Inbox "Needs Review" queue by closing validation gaps (PO, Customer, Vendor, SO, Duplicate) so docs are auto-routed.

## Core Product Requirements
1. Per-Document Intelligence Engine
2. Advanced Intelligence Engines (Gap Closers) for POs, Customers, Vendors, SOs, Duplicates
3. Accurate validation gap reporting across monitoring dashboards
4. Auto-resolution of high-confidence vendor aliases
5. Executive Monitoring Dashboard (`/monitor`)
6. Vendor Profile Consolidation
7. Exception and Retry mechanisms
8. Inbox Metrics Panel — Detailed breakdown of docs IN the inbox by Status, Type, Age, Vendor, Blocker
9. Captured Doc Auto-Retry — Docs stuck in "captured" get 4 retries then escalate to Exception Queue

## Architecture
- **Frontend**: React (Vite) with Shadcn UI, dark theme
- **Backend**: FastAPI with MongoDB
- **Deployment**: Docker on Azure VM (git pull → docker compose up)
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph

## Key File References
- `/app/backend/routers/dashboard.py` — inbox-stats, inbox-metrics, insights endpoints
- `/app/backend/routers/readiness.py` — Force cleanup, Exception retry, PO park/retry, Captured retry
- `/app/backend/routers/documents.py` — Queue endpoints, TERMINAL_STATUSES, is_duplicate filter
- `/app/backend/routers/aliases.py` — Vendor matching & alias suggestions
- `/app/backend/routers/workflow_fix.py` — Batch-fix stuck "captured" docs
- `/app/backend/server.py` — Main server, background schedulers (PO retry, Captured retry), intake pipeline
- `/app/frontend/src/pages/UnifiedQueuePage.js` — Inbox with metrics panel, retry-stuck button, tabs
- `/app/frontend/src/pages/MonitoringDashboard.js` — Vendor mapping UI

## Critical Data Rule
- `is_duplicate: {"$ne": True}` must be included in ALL inbox-related queries (documents list, inbox-stats, inbox-metrics) to match the actual inbox view. The documents endpoint enforces this at line 180.

## Completed Features
- Expanded TERMINAL_STATUSES (Validated, ReadyForPost, etc.)
- 20-Rule Force Cleanup Engine (`POST /api/readiness/sync-status`)
- Auto-Post Revert Bug Fix (non-AP docs no longer revert)
- Exception Queue + Retry System (4x retry → escalate)
- Vendor Matching Gap Closer (variants, manual BC search, dismiss)
- PO Auto-Retry Queue (park, 4h retry, 3d escalation, UI tab)
- Inbox Metrics Panel — `GET /api/dashboard/inbox-metrics` (2026-04-09)
- Captured Doc Auto-Retry — Background scheduler + manual endpoint + UI button (2026-04-09)
- **Bugfix: is_duplicate filter** — Added to inbox-metrics and inbox-stats pending_review so numbers match inbox table (2026-04-09)
- **ReadyForPost Auto-Post Scheduler** — Background loop (5min interval, 5 retries) posts ReadyForPost docs to BC when BC_WRITE_ENABLED=true. Manual trigger: `POST /api/readiness/retry-ready-to-post`. UI "Post Ready" button added. (2026-04-10)
- **Transient BC error resilience** — Failed BC posts now keep docs at ReadyForPost (not NeedsReview) so the scheduler retries. Permanent errors (404/422) still revert to NeedsReview. (2026-04-10)
- **Draft Auto-Approve in scheduler** — `auto_approve_drafts` now runs automatically every 2h cycle alongside draft feedback sync + continuous learning. High-confidence vendors auto-approved. (2026-04-10)
- **Cross-document dedup guard** — Gate 2b in `check_auto_draft_eligibility` prevents duplicate PI creation when another doc for same vendor+invoice already has a PI. (2026-04-10)
- **Posted to BC stats widget** — Inbox stats strip now shows `posted_to_bc_7d` and `ready_for_post` counts in real-time. (2026-04-10)
- **Vendor maturity fix** — Fixed maturity level labels to match frontend (mastered/proficient/developing/learning/novice), lowered thresholds (75/60/40/20), field_coverage defaults to 50 when no extraction patterns exist. (2026-04-10)
- **Bulk Classify endpoint + UI** — `POST /api/documents/bulk-classify` assigns doc_type to multiple docs with AI learning feedback. Dropdown + button in Inbox selection bar. (2026-04-10)
- **Vendor learning backfill** — Background scheduler backfills amount/line data from approved drafts' BC records for vendors showing $0. (2026-04-10)
- **Auto gap closer** — Gap closer now runs automatically in intelligence maintenance scheduler (2h cycle), re-evaluating docs with blocking validation gaps. (2026-04-10)
- **Freight Business Rules Engine** — Codified controller's (Meghan) freight processing rules into `freight_business_rules.py`. Includes: order number pattern detection (W/WR=inbound, 6-digit=outbound), location code routing (00=dropship, 001=rerouted), international vendor detection (CARGOMO/USCUSTO), shipment method codes (PPDADD/PPD/Delivered), freight item code validation, $100 variance threshold, multi-order invoice detection, LTL carrier duplicate risk (XPO/R&L), invoice naming convention parser. (2026-04-10)
- **Enhanced Freight GL Routing** — Controller rules now feed into freight GL classification as high-weight signals. Results include `controller_rules` with review flags persisted to document. (2026-04-10)
- **Freight-Specific Readiness Checks** — High freight variance blocks readiness. Multi-order invoices and LTL duplicate risk generate warnings. (2026-04-10)
- **Enhanced Duplicate Detection** — LTL carriers flagged with duplicate risk warning. In-hub duplicate check now includes order reference. (2026-04-10)
- **Noise Learning Events Cleanup** — Readiness self-corrections no longer pollute `posting_learning_events`. Dashboard queries filter out noise. Startup cleanup removes existing bad data. (2026-04-10)

## Key API Endpoints
- `POST /api/readiness/sync-status` — Force cleanup engine
- `POST /api/readiness/retry-failed` — Batch retry extraction-failed docs
- `POST /api/readiness/retry-captured` — Retry stuck captured docs (4 max → exception)
- `POST /api/readiness/retry-ready-to-post` — Post ReadyForPost docs to BC
- `POST /api/documents/bulk-classify` — Bulk assign document type with AI learning
- `POST /api/readiness/po-pending/park` / `POST /api/readiness/po-pending/retry`
- `GET /api/dashboard/inbox-stats` / `GET /api/dashboard/inbox-metrics`
- `GET /api/aliases/vendors/unmatched-gaps` / `GET /api/aliases/vendors/search`

## Upcoming Tasks
- P1: Rep Overrides Management UI
- P1: Teams Adaptive Card integration (webhook → BC Sales Order)

## Future/Backlog
- P2: Low-volume vendor review routing (<5 docs skip auto-file)
- P2: Activate correction replay engine
- P2: Email sender → vendor mapping
- P3: `server.py` extraction/refactoring (7,500+ lines)
