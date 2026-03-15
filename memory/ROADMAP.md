# ROADMAP - GPI Document Hub

## Prioritized Backlog

### P0 — Completed
- ~~Refactor server.py monolith~~ (2026-03-11)
- ~~Document Handler Extraction~~ (2026-03-15, iter_109)
- ~~Workflow Handler Extraction~~ (2026-03-15, iter_110) — 25 of 32 handlers extracted
- ~~Document Layout Fingerprinting~~ (2026-03-10)
- ~~Stable Vendor Auto-Ready Rules~~ (2026-03-11)
- ~~Stable Vendor Admin Page~~ (2026-03-11)
- ~~Remove SharePoint Migration Module~~ (2026-03-11)

### P1 — Next Up
- **Package and Publish BC (AL) Extension** — Updated `.app` file in `/app/BC_extension/` needs publishing to BC Sandbox
- **Add "Create BC Sales Order" Button to UI** — Frontend button to trigger BC sales order creation

### P2 — Medium Priority
- **Git Branch/Deployment Cleanup** — Standardize on main branch, resolve `conflict_020326_1424` branch issues
- **Reference Intelligence Handler Extraction** — Final extraction pass: 7 remaining handlers from server.py to `services/reference_intelligence_handlers.py`
- **Refactor monolithic files** — `backend/routers/inventory_ledger.py` and `frontend/src/pages/InventoryLedgerPage.js`

### P3 — Future/Backlog
- Implement Outbound Document Delivery module
- Implement "Stable Vendor" rules for auto-posting
- Replace mock email service with production-ready solution (e.g., SendGrid, Resend)
- Add multi-step approval routing for documents
- Decommission legacy Zetadocs system
- Replace mock JWT auth with Entra ID SSO
