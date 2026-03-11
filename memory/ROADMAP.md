# ROADMAP - GPI Document Hub

## Prioritized Backlog

### P0 — Completed
- ~~Refactor server.py monolith~~ ✅ (2026-03-11)
- ~~Document Layout Fingerprinting~~ ✅ (2026-03-10)

### P1 — Next Up
- **Package and Publish BC (AL) Extension** — Updated `.app` file in `/app/BC_extension/` needs publishing to BC Sandbox
- **Add "Create BC Sales Order" Button to UI** — Frontend button to trigger BC sales order creation

### P2 — Medium Priority
- **Git Branch/Deployment Cleanup** — Standardize on main branch, resolve `conflict_020326_1424` branch issues
- **Implement Migration UI Detail Drawer** — SharePoint migration detail view
- **Continue server.py Route Extraction** — Incrementally extract remaining routes from legacy api_router into new modular routers (documents, workflows, aliases, sales-file-import, etc.)

### P3 — Future/Backlog
- Implement Outbound Document Delivery module
- Implement "Stable Vendor" rules for auto-posting
- Replace mock email service with production-ready solution (e.g., SendGrid, Resend)
- Add multi-step approval routing for documents
- Decommission legacy Zetadocs system
- Replace mock JWT auth with Entra ID SSO
