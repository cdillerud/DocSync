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
- **Orchestration Extraction Phase B** — extract `_update_standard_workflow_status` (427 lines) out of `server.py`. De-risked by Phase B.0 observer (iter_222) + Phase B readiness report (iter_223). Workflow: let observer run ~7 days in production → hit `/api/admin/workflow-observer/phase-b-readiness` → use the matrix as the test-coverage target list → extract.
- **Orchestration Extraction Phase C** — extract `_internal_intake_document` (771 lines) out of `server.py`. Highest-value: decouples `email_polling_service.py` + `inside_sales_pilot_service.py` + `batch_po_splitter.py` from server. Consider building a similar observer shim first.
- **Teams Adaptive Card Integration** — Webhook handler for "Approve" → BC Sales Order
- **Batch AR Release Evaluation** — Auto-evaluate all sales docs through AR gate in pipeline
- **Wire email delivery for the weekly digest** — MS Graph (existing creds) or Resend

### ✅ P1 — Already Built (grep-verified, no work needed)
- ~~Admin UI for Item Mapping Rules~~ — lives in `Settings → Item Mappings` tab + dedicated `ItemMappingsPage.js` + 4 endpoints in `gpi_integration.py`
- ~~Rep Overrides Management UI~~ — lives in `Settings → Rep Overrides` tab backed by `components/RepOverridesPanel.js`

### P1 — Recently Completed
- ~~Phase B Readiness Report stub~~ (2026-04-19, iter_223) — categorizes observer data into must_preserve/should_cover/edge_case with READY verdict + PR-ready markdown
- ~~Phase B.0 Workflow State Observer~~ (2026-04-19, iter_222) — observability shim with caller attribution, TTL-bounded
- ~~Orchestration Extraction Phase A~~ (2026-04-19, iter_221) — `update_vendor_profile_incremental` extracted to `services/vendor_profile_helpers.py`; `document_handlers.py` late-imports from server reduced 3 → 1
- ~~WoW Delta Banner~~ (2026-04-19, iter_220) — Rep Overrides admin UI ROLLED BACK (duplicate of existing Settings tab)
- ~~Weekly Learning Digest (preview-only) + U6 SO-Learning Telemetry~~ (2026-04-19, iter_219)
- ~~U5 — Reusable PatternHealthPanel + Learning Ops command center + reviewer leaderboard~~ (2026-04-19, iter_218)
- ~~U4 — Shared Feedback Ingest + AP Telemetry Tick~~ (2026-04-19, iter_217)
- ~~U3 — Shared Pattern Health & Hygiene Consolidation~~ (2026-04-19, iter_215/216)
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
