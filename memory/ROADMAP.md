# ROADMAP - GPI Document Hub

## Prioritized Backlog

### P0 — Completed
- ~~Learned Dunnage Patterns~~ (2026-03-25) — Full-stack feature: backend pattern learning + frontend Suggested Additions UI
- ~~Energy Surcharge / Customer-Level Patterns~~ (2026-03-25) — Customer-level patterns (trigger_item="*") for items like ENERGY that appear across all orders
- ~~Quantity Bounds Checking~~ (2026-03-25) — ±2σ statistical bounds on PO quantities, blocks approval, flags for review in queue
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
- ~~Vendor Resolution Pipeline Improvements~~ (2026-03-16, iter_115) — rapidfuzz fuzzy matching, BC bootstrap, standardized match methods, 55 tests
- ~~Vendor Resolution Observability + Negative Feedback Loop~~ (2026-03-16, iter_116) — per-doc resolution objects, rejection memory, guardrails, analytics, 71 tests

### P1 — Next Up
- **U4 — Shared Feedback Ingest (learning_core)** — single `POST /api/learning/feedback?scope_type=customer|vendor` endpoint replacing the two parallel AP + Intake feedback handlers
- **U5 — Parameterized `<PatternHealthPanel domain="...">` React component** — reusable panel mounted on both `/ai-learning` and `/intake/learning` (replaces inline Pattern Health markup in IntakeLearningPage.js)
- **Rep Overrides Management UI** — Admin screen to easily map customers to reps without DB scripts
- **Teams Adaptive Card Integration** — Webhook handler for "Approve" → BC Sales Order
- **Admin UI for Item Mapping Rules** — CRUD interface for managing item mapping rules
- **Continue Orchestration Extraction** — document_handlers.py, sharepoint helpers, email polling still import from server.py
- **Batch AR Release Evaluation** — Auto-evaluate all sales docs through AR gate in pipeline

### P1 — Recently Completed
- ~~U3 — Shared Pattern Health & Hygiene Consolidation~~ (2026-04-19, iter_215) — Cross-domain AP + intake health + unified hygiene
- ~~U2 — Shared Fingerprint Service~~ (2026-04-18, iter_214) — TF-IDF moved into learning_core; AP gets vendor-peer discovery for free
- ~~U1 — Unified Event Log + Drift Alerts~~ (2026-04-18, iter_214) — `learning_events_v2` + 5 drift rules with nightly scanner

### P1 — Recently Completed
- ~~Automation Confidence Scoring~~ (2026-03-16, iter_120) — Weighted 6-signal scoring model integrated into readiness
- ~~Decision Explainability Layer~~ (2026-03-16, iter_120) — Structured explanation objects with evidence/risks
- ~~Reviewer Assist Engine~~ (2026-03-16, iter_120) — AI-powered one-click suggestions for reviewers
- ~~Automation Metrics Dashboard~~ (2026-03-16, iter_120) — Rates, distribution, signal averages, top causes
- ~~Dashboard Readiness Summary Card~~ (2026-03-16, iter_118)
- ~~Config Service Extraction~~ (2026-03-16)
- ~~AR Release Gate (Prepay & Terms Approval)~~ (2026-03-16, iter_119)

### P2 — Medium Priority
- **Package and Publish BC (AL) Extension** — Updated `.app` file in `/app/BC_extension/` needs publishing to BC Sandbox
- **Add "Create BC Sales Order" Button to UI** — Frontend button to trigger BC sales order creation
- **Inventory Planning Horizon** — Demand Forecast + Purchase Timing
- **Utility helper extraction** — Extract shared helpers still imported from server.py by 12 router modules
- **Refactor monolithic files** — `backend/routers/inventory_ledger.py` and `frontend/src/pages/InventoryLedgerPage.js`

### P3 — Future/Backlog
- Vendor Inventory Dashboard
- Product/BOM (Bill of Materials) module
- Production-ready email service and Entra ID SSO
- Continue `server.py` extraction (ongoing)
- Routing engine extensions: stable_vendor auto-approval, layout family trust scoring, dynamic policy thresholds
- Implement Outbound Document Delivery module
- Admin UI for item mapping rules
- Replace mock email service with production-ready solution (e.g., SendGrid, Resend)
- Decommission legacy Zetadocs system
- Replace mock JWT auth with Entra ID SSO
