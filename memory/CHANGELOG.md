# CHANGELOG - GPI Document Hub

## [2026-03-12] Backend Refactor Phase 2 — COMPLETE
- Extracted all 85 routes from server.py into 9 domain-specific router files
- server.py now has 0 active @api_router routes (down from 85)
- New router files: aliases.py, mailbox_sources.py, file_import.py, bc_integration.py, documents.py, workflows.py, reference_intelligence.py
- Dynamic route registration pattern: app.add_api_route() for complex routes during startup

## [2026-03-12] Reference Intelligence Redesign — COMPLETE
- Domain-aware multi-signal scoring replaces naive numeric matching
- Context gate: AP invoices exclude sales/customer candidates by default
- Counterparty consistency scoring: vendor match boosts, mismatch penalizes
- Two-signal minimum for "Likely Match" (at least one contextual)
- Candidate states: surfaced/suppressed/rejected
- Explainable scoring output with full signal breakdown
- 16 regression tests covering the original false positive scenario
- Critical regression verified: AP invoice PO→purchase beats PO→sales_shipment

## 2026-03-11: Stable Vendor Admin Page (New Feature)

### What Was Built
Complete admin page for vendor stability oversight, explainability, and manual controls.

**Backend:**
- Extended `stable_vendor_service.py` with:
  - `get_vendor_list()` — filterable/sortable/searchable vendor list with effective status
  - `get_vendor_detail()` — full vendor detail with checks, reasons, routing impact, quality signals, history
  - `apply_override()` / `clear_override()` — manual promote/demote/watch with audit trail
  - `get_override_history()` — full audit log
  - `_effective_status()` — computes system + override = effective status
- New collection: `stable_vendor_override_history`
- 5 new API endpoints: `/api/stable-vendor/vendors`, `/vendors/{id}`, `/vendors/{id}/override`, `/vendors/{id}/clear-override`, `/vendors/{id}/history`

**Frontend:**
- New page: `/stable-vendors` with sortable table, search, status filters (All/Stable/Watch/Unstable/Overridden)
- Detail drawer: Summary, Stability Reasoning, Check Details, Routing Impact, Quality Signals, Admin Actions, Override History
- Override actions: Promote Stable / Set Watch / Demote / Clear Override with reason/note
- Cross-links from Dashboard KPI widget ("View All") and Document Detail routing card
- Added to sidebar navigation

**Safety:** Manual overrides affect vendor trust/routing eligibility but NEVER bypass hard document blockers (validation, duplicates, freight GL, alerts)

### Test Results
- Backend: 20/20 (100%)
- Frontend: All UI flows verified (100%)
- Safety constraint validated: force_stable override does NOT bypass document validation failures
- Test report: `/app/test_reports/iteration_39.json`

---

## 2026-03-11: SharePoint Migration Module Removed

- Deleted backend routes, service, and test file
- Removed frontend page, route, and sidebar nav item
- All references cleaned from main.py, server.py

---

## 2026-03-11: Stable Vendor Auto-Ready Rules

### What Was Built
- Stable vendor service with configurable thresholds (volume, rates, correction, validation)
- Document auto-ready evaluation (10 safety checks including amount anomaly, layout family guards)
- 3 routing outcomes: auto_ready, low_priority_review, manual_review
- Dashboard KPI widget, Queue routing badges, Document Detail routing card
- Test report: `/app/test_reports/iteration_38.json`

---

## 2026-03-11: Backend Refactor (server.py Monolith -> Modular Architecture)

- Created `/app/backend/main.py` as new entry point (supervisor runs main:app)
- Fixed 7 broken router files, Re-process button 500 error
- Test report: `/app/test_reports/iteration_37.json`

---

## 2026-03-10: Document Layout Fingerprinting

- Structural document fingerprinting and layout families
- Test report: `/app/test_reports/iteration_3.json`

---

## Earlier Work (Pre-March 2026)
- Core platform, Vendor Intelligence, Automation Rules, Freight GL Routing
- AP Validation, Label Corrections, Alert Patterns, Email polling
- Spiro CRM, Sales module, Square9 workflow, BC Reference Cache
- Auto-Resolution Service, Vendor Extraction Profiles

---

## 2026-03-14: Configurable Item Master Data (Reorder Thresholds & Safety Buffers)

### What Was Built
- New backend router `/api/inventory-items/settings` (POST upsert, GET list) for per-item reorder settings
- DB collection `inv_item_settings` with schema: {customer_id, item, reorder_threshold, safety_buffer, notes, created_at, updated_at}
- Updated reorder recommendations to use configurable settings: `recommended_qty = max(0, threshold - available) + buffer`
- Fallback to defaults (threshold=0, buffer=10) when no settings exist
- Frontend: Item Settings tab in CustomerWorkspace with add/edit form + settings table
- Frontend: Reorder tab updated with Threshold and Buffer columns
- Backend: 17/17 pytest tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_64.json`
