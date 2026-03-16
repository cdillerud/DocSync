# ROADMAP - GPI Document Hub

## Prioritized Backlog

### P0 — Completed
- ~~Refactor server.py monolith~~ (2026-03-11)
- ~~Document Handler Extraction~~ (2026-03-15, iter_109)
- ~~Workflow Handler Extraction~~ (2026-03-15, iter_110) — 25 of 32 handlers extracted
- ~~Reference Intelligence Handler Extraction~~ (2026-03-15, iter_111) — ALL 32 handlers extracted from server.py
- ~~Shared Helper Extraction~~ (2026-03-15, iter_112) — 6 utilities extracted, 6 consumers rewired
- ~~Document Layout Fingerprinting~~ (2026-03-10)
- ~~Stable Vendor Auto-Ready Rules~~ (2026-03-11)
- ~~Stable Vendor Admin Page~~ (2026-03-11)
- ~~Remove SharePoint Migration Module~~ (2026-03-11)
- ~~Autonomous Document Routing (Auto-Clear Gate)~~ (2026-03-16, iter_113) — 6-rule routing engine, pipeline stage 9, dashboard UI, 38 tests
- ~~Vendor Alias Learning System~~ (2026-03-16, iter_114) — Auto-learns aliases from approvals, safety rules, dashboard metrics, 34 tests

### P1 — Next Up
- **Complete Orchestration Logic Extraction from server.py** — Business orchestration logic still in server.py, paused for routing feature
- **AR Release Gate (Prepay and Terms Approval)** — New approval step for AR documents

### P2 — Medium Priority
- **Package and Publish BC (AL) Extension** — Updated `.app` file in `/app/BC_extension/` needs publishing to BC Sandbox
- **Add "Create BC Sales Order" Button to UI** — Frontend button to trigger BC sales order creation
- **Inventory Planning Horizon** — Demand Forecast + Purchase Timing
- **Utility helper extraction** — Extract shared helpers still imported from server.py by 12 router modules
- **Refactor monolithic files** — `backend/routers/inventory_ledger.py` and `frontend/src/pages/InventoryLedgerPage.js`

### P3 — Future/Backlog
- Routing engine extensions: stable_vendor auto-approval, layout family trust scoring, dynamic policy thresholds
- Implement Outbound Document Delivery module
- Admin UI for item mapping rules
- Replace mock email service with production-ready solution (e.g., SendGrid, Resend)
- Decommission legacy Zetadocs system
- Replace mock JWT auth with Entra ID SSO
