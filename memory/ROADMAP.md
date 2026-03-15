# ROADMAP - GPI Document Hub

## Prioritized Backlog

### P0 — Completed
- ~~Refactor server.py monolith~~ (2026-03-11)
- ~~Document Handler Extraction~~ (2026-03-15, iter_109)
- ~~Workflow Handler Extraction~~ (2026-03-15, iter_110)
- ~~Reference Intelligence Handler Extraction~~ (2026-03-15, iter_111) — ALL 32 handlers extracted
- ~~Shared Helper Extraction~~ (2026-03-15, iter_112) — 6 utilities extracted, 6 consumers rewired
- ~~Orchestration Logic Extraction~~ (2026-03-15, iter_113) — 7 orchestration functions into vendor_matching.py + ap_computation.py
- ~~Architecture Hardening Pass~~ (2026-03-15, iter_114) — 89% reduction in server.py imports, 6 new modules, guardrail tests
- ~~Final Orchestration Extraction~~ (2026-03-15, iter_115) — 3 deep orchestration functions extracted, document_handlers fully decoupled, 95% cumulative import reduction
- ~~Document Layout Fingerprinting~~ (2026-03-10)
- ~~Stable Vendor Auto-Ready Rules~~ (2026-03-11)
- ~~Stable Vendor Admin Page~~ (2026-03-11)
- ~~Remove SharePoint Migration Module~~ (2026-03-11)

### P1 — Next Up
- **server.py _internal_intake_document extraction** — Extract the core 450-line intake pipeline and its sub-functions into a dedicated `services/document_intake.py`. This is the final major extraction target that would reduce server.py to pure lifecycle/bootstrap code.
- **Compatibility wrapper cleanup** — Remove the ~18 thin re-exports in server.py once all internal callers are migrated
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
