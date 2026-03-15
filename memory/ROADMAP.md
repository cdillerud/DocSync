# ROADMAP - GPI Document Hub

## Prioritized Backlog

### P0 — Completed
- ~~Refactor server.py monolith~~ (2026-03-11)
- ~~Document Handler Extraction~~ (2026-03-15, iter_109)
- ~~Workflow Handler Extraction~~ (2026-03-15, iter_110)
- ~~Reference Intelligence Handler Extraction~~ (2026-03-15, iter_111) — ALL 32 handlers extracted
- ~~Shared Helper Extraction~~ (2026-03-15, iter_112) — 6 utilities extracted, 6 consumers rewired
- ~~Orchestration Logic Extraction~~ (2026-03-15, iter_113) — 7 orchestration functions into vendor_matching.py + ap_computation.py
- ~~Document Layout Fingerprinting~~ (2026-03-10)
- ~~Stable Vendor Auto-Ready Rules~~ (2026-03-11)
- ~~Stable Vendor Admin Page~~ (2026-03-11)
- ~~Remove SharePoint Migration Module~~ (2026-03-11)

### P1 — Next Up
- **Final server.py Cleanup Pass** — Extract remaining orchestration logic (email polling, draft creation coordination), separate app lifecycle/startup code
- **Package and Publish BC (AL) Extension** — Updated `.app` file in `/app/BC_extension/` needs publishing to BC Sandbox
- **Add "Create BC Sales Order" Button to UI** — Frontend button to trigger BC sales order creation

### P2 — Medium Priority
- **Git Branch/Deployment Cleanup** — Standardize on main branch, resolve `conflict_020326_1424` branch issues
- **Refactor monolithic files** — `backend/routers/inventory_ledger.py` and `frontend/src/pages/InventoryLedgerPage.js`

### P3 — Future/Backlog
- Implement Outbound Document Delivery module
- Implement "Stable Vendor" rules for auto-posting
- Replace mock email service with production-ready solution (e.g., SendGrid, Resend)
- Add multi-step approval routing for documents
- Decommission legacy Zetadocs system
- Replace mock JWT auth with Entra ID SSO
