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

---

## 2026-03-14: Inventory Dashboard Summary Metrics

### What Was Built
- New endpoint `GET /api/inventory-ledger/dashboard-summary` computes inventory health from existing `derive_balances` pipeline
- Returns 9 fields: total_items, items_ok, items_low, items_short, total_on_hand, total_incoming, total_committed, total_available, total_reorder_recommendations
- Status logic (is_short/is_low) matches balance table and CSV export
- Reorder count mirrors `/reorder-recommendations` endpoint count
- Frontend SummaryStrip updated from 5 cards to 8 cards (Total Items, OK, LOW, SHORT, Incoming, Committed, Available, Reorders Needed)
- Responsive grid: 2 cols mobile, 4 cols tablet, 8 cols desktop
- Backend: 13/13 pytest tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_65.json`

---

## 2026-03-14: Inventory CSV Import

### What Was Built
- New endpoint `POST /api/inventory-ledger/import` accepts CSV upload with multipart form data
- Import modes: `opening_balance` and `manual_adjustment` — rows converted to immutable ledger movements
- Validates required columns (item, qty), rejects zero qty, non-numeric qty, empty item
- Duplicate import protection via SHA-256 file hash (customer_id + mode included in hash)
- Opening balance duplicates per item/warehouse/ownership rejected
- Optional columns: warehouse, ownership_type, uom, reference, notes, item_description
- Movements created with source_type=spreadsheet_import, reference_type=csv_import
- Frontend: Import CSV button on Balances tab, dialog with mode selector + file upload + results display
- Backend: 22/22 pytest tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_66.json`

---

## 2026-03-14: Inventory Snapshot Export

### What Was Built
- `GET /api/inventory-ledger/snapshot` — read-only JSON snapshot with generated_at, context, summary metrics, balance rows (with clean status field), optional reorder rows
- `GET /api/inventory-ledger/snapshot/export` — downloadable JSON file with Content-Disposition header (filename: snapshot_{name}_{timestamp}.json)
- Supports customer_id (required), item filter (optional), include_reorders toggle (default true)
- Summary values match dashboard-summary exactly; balance rows strip internal flags
- Empty/nonexistent customer returns valid snapshot with zeros and empty arrays
- Frontend: Export Snapshot button on Balances tab toolbar
- Backend: 25/25 pytest tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_67.json`

---

## 2026-03-14: Inventory Exception View

### What Was Built
- `GET /api/inventory-ledger/exceptions` — returns items needing attention with exception_types classification
- Exception types: short (status=SHORT), low (status=LOW), reorder (in recommendations), no_incoming (SHORT/LOW with incoming=0)
- Exception summary counts: short_count, low_count, reorder_count, no_incoming_count (short/low match dashboard metrics)
- Supports exception_type filter parameter, sorted by available ascending (most critical first)
- Reorder items include recommended_qty, reorder_threshold, safety_buffer
- Frontend: Exceptions tab with 4 clickable summary cards (filter toggle) + exception table with History/Supply action buttons
- Backend: 21/21 pytest tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_68.json`

---

## 2026-03-14: Inventory Item Detail View

### What Was Built
- `GET /api/inventory-ledger/item-detail` — complete operational picture for a single item
- Returns: balance (on_hand, incoming, committed, available, status), settings, reorder recommendation, exception flags, recent 10 movements, type_summary
- 404 for nonexistent items, 422 for missing params
- Frontend: ItemDetailDrawer opens from Balances, Reorder, and Exceptions tables
- Shows: balance strip (5 values), exception badges, reorder settings/status, history preview table, action buttons (Full History, Create Supply)
- Backend: 15/15 pytest tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_69.json`

---

## 2026-03-14: Inventory Demand Signal Tracking

### What Was Built
- `GET /api/inventory-ledger/demand-signals` — forward demand pressure per item from SO commitments
- total_open_order_qty = committed balance (outstanding SO commitments), demand_gap = committed - available
- Only items with total_open_order_qty > 0 included, sorted by demand_gap descending (highest risk first)
- Item detail endpoint updated: includes `demand` field (total_open_order_qty, demand_gap) when committed > 0, null otherwise
- Frontend: Demand tab with demand table, rows highlighted bg-red-500/5 when demand_gap > 0
- Item clicks open ItemDetailDrawer, Create Supply button on gap > 0 rows
- ItemDetailDrawer shows demand signal section with Open Orders and Demand Gap
- Backend: 16/16 pytest tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_70.json`

---

## 2026-03-14: Inventory Supply Coverage Projection

### What Was Built
- `GET /api/inventory-ledger/supply-coverage` — coverage = on_hand + incoming - committed per item
- coverage_status: 'covered' (>=0) or 'at_risk' (<0), only items with committed > 0, sorted ascending
- Item detail updated: includes supply_coverage (coverage, coverage_status) when committed > 0
- Frontend: Supply Coverage tab with table, at_risk rows highlighted bg-red-500/5
- Item clicks open ItemDetailDrawer, Create Supply button on at_risk rows
- ItemDetailDrawer shows Supply Coverage section with value + status badge
- Backend: 17/17 pytest tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_71.json`

---

## 2026-03-14: Inventory Action Center

### What Was Built
- `GET /api/inventory-ledger/action-center` — unified prioritized action queue
- Consolidates: exceptions, reorder, demand signals, supply coverage into merged action rows
- Action types: shortage(50), coverage_risk(30), demand_gap(20), reorder(10), no_incoming(5)
- Priority score = sum of weights, sorted by score desc, available asc for ties
- action_summary: shortage_count, coverage_risk_count, demand_gap_count, reorder_count, no_incoming_count, total_action_items
- Supports action_type filter parameter
- Item detail updated: action_summary (action_types, priority_score) when applicable
- Frontend: Action Center tab with 5 clickable summary cards (filter toggle) + action table with badges, priority scores, History/Supply buttons
- ItemDetailDrawer shows action summary section with badges and score
- Backend: 20/20 pytest tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_72.json`

---

## 2026-03-14: PO Draft Generation from Supply Actions

### What Was Built
- `POST /api/inventory-ledger/generate-po-draft` — generates PO draft from selected items
- Validates items exist in inventory, qty > 0, customer exists
- Duplicate guard: same item+customer within 5 minutes returns 409
- Stored in `po_drafts` collection: po_draft_id, lines, status (draft/sent/archived), total_qty, total_lines
- `GET /api/inventory-ledger/po-drafts` — lists drafts by customer_id, filterable by status
- `PATCH /api/inventory-ledger/po-drafts/{id}/status` — updates draft lifecycle
- Item detail: shows last_po_draft (po_draft_id, created_at, status)
- Frontend: Multi-select checkboxes on eligible Action Center rows (reorder/coverage_risk/shortage)
- Generate PO Draft button + confirmation with draft ID, lines, and total qty
- ItemDetailDrawer shows Last PO Draft section with ID, status badge, and date
- Bugs fixed: (1) _id:None in insert_one, (2) 'actions' used before declaration
- Backend: 20/20 pytest tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_73.json`

---

## 2026-03-14: PO Draft Review and Export

### What Was Built
- `GET /api/inventory-ledger/po-drafts/{id}` — returns full stored PO draft detail
- `GET /api/inventory-ledger/po-drafts/{id}/export` — downloadable JSON file with Content-Disposition header
- Export uses stored data exactly as saved (no recalculation)
- Frontend: PO Drafts tab with list table (ID, date, status badge, lines, total qty, items preview)
- PODraftDetailDrawer: header (ID, status, created, customer), summary, lines table, action buttons
- Export JSON, Mark as Sent, Archive controls in detail drawer
- Action Center confirmation: View Draft link opens draft detail
- Item Detail: PO draft indicator is clickable to open draft detail drawer
- Backend: 15/15 pytest tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_74.json`
