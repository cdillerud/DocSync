# CHANGELOG - GPI Document Hub


## [2026-03-15] Iteration 98 — Document Bundle Detection & Transaction Grouping — COMPLETE
- **Backend:** New `services/document_bundle_service.py` — layered grouping (PO 0.95 → invoice 0.92 → linked entity 0.88 → vendor+amount fuzzy 0.65)
- **Backend:** `POST /api/document-intelligence/detect-bundles` — scans recent docs or specific IDs, groups by shared references
- **Backend:** `GET /api/document-intelligence/bundles` — list with filters (type, status, completeness, entity)
- **Backend:** `GET /api/document-intelligence/bundles/{id}` — full detail with member_documents, detected_keys, completeness, suggested_next_action
- **Backend:** `PATCH /api/document-intelligence/bundles/{id}` — reclassify, add/remove docs, change status, notes; re-evaluates completeness
- **Backend:** `GET /api/document-intelligence/bundle-review-queue` — bundles needing review or incomplete
- **Backend:** Completeness rules per bundle type: ap_packet (invoice+receiving), customer_order_packet (customer PO), purchasing_packet (PO support), warehouse_packet (agreement+PO)
- **Backend:** Document enrichment: intelligence results gain bundle_id, bundle_type, bundle_status, bundle_completeness_status, related_document_count
- **Backend:** Activity events: bundle_detected, added_to_bundle, bundle_completeness_changed, bundle_manually_corrected
- **Frontend:** New `/document-bundles` page — summary cards, 3 filter dropdowns, bundle table, detail drawer with member docs, detected keys, manual controls
- **Frontend:** Bundle membership section in DocumentIntelligencePanel — shows bundle info, related docs, missing docs, completeness badge
- **Frontend:** Nav item "Doc Bundles" added to sidebar
- **New collection:** `document_bundles`
- **Router fix:** Bundle endpoints placed before catch-all `/{doc_id}` to avoid route conflicts
- **Testing:** Backend 100% (24/24 passed), Frontend 100% — all verified by testing agent, all regression tests pass
- **Test report:** `/app/test_reports/iteration_98.json`



## [2026-03-15] Iteration 97 — Document-to-Existing-Transaction Matching & Auto-Linking — COMPLETE
- **Backend:** New `services/transaction_matching_service.py` — multi-strategy matching (PO exact → entity+reference → vendor+amount → linked doc cross-reference)
- **Backend:** `POST /api/document-intelligence/match-transactions/{id}` — finds candidate matches with confidence scoring (HIGH=0.90, MEDIUM=0.70)
- **Backend:** `GET /api/document-intelligence/transaction-matches/{id}` — returns stored match candidates
- **Backend:** `POST /api/document-intelligence/auto-link/{id}` — links document to high-confidence/confirmed match, rejects ambiguous (422)
- **Backend:** `PATCH /api/document-intelligence/transaction-matches/{match_id}` — manual confirm/reject with re-evaluation
- **Backend:** Auto-draft suppression: `auto_draft_suppressed_due_to_match=true` prevents duplicate drafts when a match is found
- **Backend:** Activity timeline events: transaction_match_found, transaction_match_ambiguous, transaction_match_none, transaction_auto_linked, transaction_match_confirmed, transaction_match_rejected
- **Backend:** Hub documents enriched with `linked_transaction_type/id/display` on successful linking
- **Frontend:** Transaction Matching section in DocumentIntelligencePanel — candidate list with confidence bars, confirm/reject buttons, auto-link button
- **Frontend:** Review Queue shows transaction matching status badges (tx match, tx ambiguous, linked, Link Available)
- **New collection:** `transaction_matches`
- **Bug fix:** Removed duplicate orphaned except blocks in router (lines 296-300)
- **Testing:** Backend 100% (19/21 passed, 2 skipped), Frontend 100% — all verified by testing agent
- **Test report:** `/app/test_reports/iteration_97.json`



## [2026-03-15] Iteration 96 — Entity Resolution Engine — COMPLETE
- **Backend:** New `services/entity_resolution_service.py` — layered entity resolution (exact → normalized → fuzzy → reference lookup)
- **Backend:** `POST /api/document-intelligence/resolve-entities/{id}` — resolves customer, vendor, PO#, invoice# with confidence scoring
- **Backend:** `GET /api/document-intelligence/resolution/{id}` — get stored resolution results
- **Backend:** `PATCH /api/document-intelligence/resolution/{resolution_id}` — manual correction with audit trail (original_resolution preserved)
- **Backend:** Resolution statuses: matched, ambiguous, unmatched, corrected
- **Backend:** Auto-draft gating: blocks draft creation when entity_resolution_status=blocked (unresolved entities)
- **Backend:** Intelligence enrichment: entity_resolution_status, blocking_items, unresolved/ambiguous counts
- **Backend:** Activity timeline: entity_resolution_completed/issues/corrected events
- **Frontend:** Entity Resolution section in DocumentIntelligencePanel — status badges, candidate lists with Confirm buttons, manual override inputs
- **Frontend:** Review Queue shows entity resolution indicators (unresolved/ambiguous badges)
- **New collection:** `entity_resolutions`
- **Testing:** 16/16 backend, 100% frontend — all verified by testing agent
- **Test report:** `/app/test_reports/iteration_96.json`



## [2026-03-15] Iteration 95 — Document-to-Transaction Auto-Draft Creation — COMPLETE
- **Backend:** `POST /api/document-intelligence/auto-draft/{id}` — creates downstream draft from automation-ready documents
- **Backend:** `GET /api/document-intelligence/auto-draft/{id}` — returns latest automation action for a document
- **Backend:** Draft type mappings: AP_Invoice → ap_intake_draft, Freight/Shipping_Document → po_draft, Sales_PO/customer_po → sales_order_draft
- **Backend:** Duplicate prevention: blocks re-creation of same draft type from same document, returns existing action
- **Backend:** Automation readiness gate: only creates drafts when automation_readiness = ready
- **Backend:** Document intelligence enrichment: auto_draft_available, auto_draft_created, target_entity_type, target_entity_id, last_automation_action_status
- **Backend:** Activity timeline integration: logs auto_draft_created and auto_draft_failed events
- **Backend:** New collections: `automation_actions`, `so_drafts`, `ap_intake_drafts`
- **Frontend:** DocumentIntelligencePanel extended with auto-draft section: "Create Draft" button, "Draft Created" success state with draft ID, duplicate message
- **Frontend:** DocumentReviewQueuePage extended with "Create Draft" action column for ready documents, draft ID badges for existing drafts
- **Safeguards:** Drafts only — no BC API calls, no inventory mutations, no auto-finalization, human review preserved
- **Testing:** 29/30 backend tests passed (1 skipped), 100% frontend verification
- **Test report:** `/app/test_reports/iteration_95.json`


## [2026-03-15] Iteration 94 — Document Intelligence Engine — COMPLETE
- **Backend:** New `routers/document_intelligence.py` + `services/document_intelligence_service.py` (separate from monolith)
- **Backend:** `POST /api/document-intelligence/process/{id}` — full pipeline: classify → extract → validate → derive automation readiness → store
- **Backend:** `GET /api/document-intelligence/review-queue` — human-in-the-loop queue with status/type filters, enriched with doc metadata
- **Backend:** `PATCH /api/document-intelligence/{id}` — manual corrections with re-derivation of readiness, correction history tracking
- **Backend:** `GET /api/document-intelligence/summary` — stats by readiness and document type
- **Backend:** Automation readiness engine: score 0-100 based on classification confidence (40pts), extraction completeness (40pts), validation (10pts), optional fields (10pts)
- **Backend:** Readiness reasons: `missing_po_number`, `low_classification_confidence`, `validation_failed_bc_error`, etc.
- **Backend:** Model metadata tracking: model_name, model_provider, prompt_version, processing_duration_ms
- **Frontend:** DocumentReviewQueuePage at /document-review — summary cards, status/type filters, sort, review queue table with confidence bars and reason badges
- **Frontend:** DocumentIntelligencePanel component on Document Detail page — readiness banner, classification section, extracted fields with required/optional markers, inline edit mode, correction history
- **Frontend:** Edit/Re-process capabilities for on-demand re-processing and manual corrections
- **Key architectural improvement:** Centralized scattered AI pipeline into a formal Document Intelligence Engine that's re-runnable, user-correctable, and auditable
- **Testing:** 18/18 backend tests passed, 100% frontend verification (test_reports/iteration_94.json)
- **New MongoDB collection:** `document_intelligence_results`



## [2026-03-15] Iteration 93 — Operational Templates — COMPLETE
- **Backend:** Template CRUD (POST/GET/PATCH/DELETE /api/inventory-ledger/templates) with entity_type/order_type validation, soft-delete
- **Backend:** Apply-template endpoint (POST /api/inventory-ledger/templates/{id}/apply) with safe-skip behavior (won't overwrite existing assignments/due dates/approvals), order type compatibility check, activity auto-generation
- **Backend:** Bulk apply_template action added to operations-queue/bulk-action endpoint
- **Frontend:** TemplatesPage at /templates — create/edit dialog, toggle active, filter by type, template cards
- **Frontend:** TemplateApplySection in SO and PO workflow views — compatible template buttons with applied/skipped result display
- **Frontend:** Operations Queue bulk toolbar: "Apply Template" button with template dropdown
- **Testing:** 22/22 backend tests passed, all frontend UI elements verified (100% pass rate)
- **Test report:** /app/test_reports/iteration_93.json


## [2026-03-15] Iteration 92 — Bulk Actions for Operations Queue — COMPLETE
- **Backend:** POST /api/inventory-ledger/operations-queue/bulk-action with 5 actions (assign_owner, update_assignment_status, set_due_date, set_escalation_status, request_approval), structured per-entity results, partial success handling, activity auto-generation
- **Frontend:** Operations Queue: checkbox per row, select all toggle, bulk action toolbar (5 buttons + clear), per-action dialogs with validation, result summary panel, queue refresh, selection clear on success
- **Testing:** 22/22 backend tests passed, all frontend UI elements verified (100% pass rate)
- **Test report:** /app/test_reports/iteration_92.json


## [2026-03-15] Iteration 91 — Saved Views and Personal Queue Presets — COMPLETE
- **Backend:** Saved view CRUD endpoints (POST/GET/PATCH/DELETE /api/inventory-ledger/saved-views) with view_type validation and default uniqueness per view_type+created_by
- **Backend:** Operations Queue response enriched with saved_views_count and default_view_name
- **Frontend:** Operations Queue: "Save View" button + dialog (name, notes, default toggle, filter summary), "Views" button with dropdown panel (list, apply, set default, overwrite, delete), active view badge in header, auto-load default on mount
- **Frontend:** Dashboard summary strip: Saved Views card showing count and default view name
- **Testing:** 15/15 backend tests passed, all frontend UI elements verified (100% pass rate)
- **Test report:** /app/test_reports/iteration_91.json


## [2026-03-14] Iteration 90 — Operational Notes and Activity Timeline — COMPLETE
- **Backend:** Activity model + CRUD endpoints (POST/GET /api/inventory-ledger/activities) with 11 activity types (note, assignment, approval, document, bc_export, bc_response, shipment, invoice, receipt, escalation, system)
- **Backend:** System auto-generation of activities for all major workflow events (approvals, documents, escalations, assignments, BC export/response, shipments, invoices, incoming supply creation)
- **Backend:** SO summary and PO Draft detail enriched with latest_activity_at, latest_activity_type, activity_count
- **Backend:** Operations Queue enriched with activity data + stale filter (stale_days), sort option (sort_by=latest_activity), dashboard counts (recent_activity_today, no_recent_activity_7d)
- **Frontend:** ActivityTimelineSection component in SO and PO workflow views — add notes, filter by type, collapsible timeline with color-coded type badges
- **Frontend:** Operations Queue: Activity Today / Stale (>7d) summary cards, Last Activity column with timeAgo, Sort: Latest Activity dropdown
- **Testing:** 20/20 backend tests passed, all frontend UI elements verified (100% pass rate)
- **Test report:** /app/test_reports/iteration_90.json


## [2026-03-14] Iteration 89 — Operational Ownership and Assignment Tracking — COMPLETE
- **Backend:** Assignment CRUD endpoints (POST/GET/PATCH /api/inventory-ledger/assignments) with upsert semantics
- **Backend:** Derived ownership logic (current_owner, assignment_status, assignment_updated_at) — unassigned returns null/unassigned
- **Backend:** Operations Queue enriched with assignment data + filters (assigned_to, assignment_status, unassigned_only)
- **Backend:** +10 priority boost for unassigned high-priority items; counts: unassigned_count, in_progress_count, waiting_count
- **Backend:** SO summary and PO Draft detail endpoints enriched with assignment fields
- **Frontend:** Operations Queue page: Owner column, assignment status badges, owner/assignment filter dropdowns, unassigned row highlighting (orange border)
- **Frontend:** Summary cards: Unassigned, In Progress, Waiting counts
- **Frontend:** AssignmentSection component in SO and PO workflow views — assign/reassign owner, update status (In Progress/Waiting/Completed), notes
- **Testing:** 22/22 backend tests passed, all frontend UI elements verified (100% pass rate)
- **Test report:** /app/test_reports/iteration_89.json


## [2026-03-14] Iteration 88 — Operational Escalations and Due Dates — COMPLETE
- **Backend:** Escalation CRUD endpoints (POST/GET/PATCH /api/inventory-ledger/escalations) with derived status logic (on_track, due_soon, overdue, escalated)
- **Backend:** Operations Queue enriched with escalation data (due_date, escalation_status, days_to_due, days_overdue), priority score boosted (+10/+20/+30)
- **Backend:** Escalation filter on operations-queue endpoint (?escalation=overdue|due_soon|escalated|on_track)
- **Backend:** SO summary and PO Draft detail endpoints enriched with escalation fields
- **Frontend:** Operations Queue page with summary cards (Total, High Priority, Due Soon, Overdue, Escalated), escalation filter dropdown, color-coded badges, row highlighting
- **Frontend:** EscalationSection component in SO and PO workflow views — set/edit due dates, manual escalation, status badges, days-to-due/overdue display
- **Testing:** 22/22 backend tests passed, all frontend UI elements verified (100% pass rate)
- **Test report:** /app/test_reports/iteration_88.json



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

---

## 2026-03-14: PO Draft to Incoming Supply Conversion (iteration_75)

### What Was Built
- `POST /api/inventory-ledger/po-drafts/{draft_id}/create-incoming-supply` — converts PO draft lines into planned incoming supply records
- Each draft line creates an `incoming_supply` record with `status=planned`, referencing the draft ID as `source_reference`
- Duplicate prevention: 409 if draft already converted (`incoming_supply_created` flag)
- Archived draft rejection: 422 if draft is archived
- After conversion, draft updated with `incoming_supply_created=true`, `incoming_supply_created_at`, `incoming_supply_ids[]`
- Planned supply integrates with existing `derive_balances` pipeline — no new balance math needed
- Frontend: "Create Incoming Supply" green button in PO Draft detail drawer (hidden for converted/archived drafts)
- Frontend: "Supply Created" green badge in header and green info box with conversion timestamp and record count
- Frontend: Conversion result display with processed/created/skipped counts and per-item status
- Frontend: "Supply" badge in PO Drafts list table for converted drafts
- Frontend: `onSupplyCreated` callback triggers inventory view refresh after conversion
- Backend: 10/10 tests passed, Frontend: all UI flows verified
---

## 2026-03-14: BC Purchase Order Payload Export (iteration_76)

### What Was Built
- `PATCH /api/inventory-ledger/po-drafts/{draft_id}/vendor` — assigns vendor_id and vendor_name to a PO draft
- `GET /api/inventory-ledger/po-drafts/{draft_id}/bc-export` — generates BC-compatible JSON payload for download
- BC payload structure: `{poDraftId, vendor: {vendorId, vendorName}, documentDate (YYYY-MM-DD), source: "GPI_Hub_PO_Draft", lines: [{itemNumber, quantity, sourceReference}]}`
- Validation: missing vendor → 422, archived draft → 422, no lines → 422, nonexistent → 404
- Content-Disposition header for file download (`BC-PO-{draft_id}.json`)
- Frontend: Vendor assignment section in PO Draft detail drawer (ID/Name inputs + Save button)
- Frontend: "No vendor assigned — required for BC export" warning when vendor missing
- Frontend: "Export for Business Central" button (disabled until vendor assigned, hidden for archived)
- Frontend: Mark as Sent prompt after BC export (confirm/dismiss)
- No ledger mutations, no BC API calls — strictly payload generation
- Backend: 18/18 tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_76.json`
---

## 2026-03-14: BC PO Submission Log Tracking (iteration_77)

### What Was Built
- New collection `po_submission_logs` for tracking BC handoff events per PO draft
- `POST /api/inventory-ledger/po-drafts/{id}/submission-log` — creates log entry with status, notes, vendor info, and bc_payload_snapshot
- `GET /api/inventory-ledger/po-drafts/{id}/submission-log` — lists entries reverse chronological
- Supported statuses: exported, submitted, acknowledged, failed
- BC export (`GET bc-export`) auto-creates "exported" log entry with payload snapshot
- PO Drafts list enriched with `latest_submission_status` and `latest_submission_at` via aggregation
- Validation: invalid status (422), archived draft (422), no vendor (422), not found (404)
- Frontend: Submission Log section in PO Draft detail drawer with status badge/timestamp/notes list
- Frontend: Add-entry form (status select: Submitted/Acknowledged/Failed, notes input, Log button)
- Frontend: Latest submission status badge in PO Drafts list table
- No ledger mutations, no BC API calls — strictly informational tracking
- Backend: 19/19 tests passed, Frontend: all UI flows verified
---

## 2026-03-14: BC PO Response Capture (iteration_78)

### What Was Built
- `PATCH /api/inventory-ledger/po-drafts/{id}/bc-response` — records downstream BC result (created/rejected/pending)
- Fields: bc_response_status, bc_po_number, bc_document_id, bc_response_at, bc_response_notes
- Validation: rejected requires notes (422), invalid status (422), not found (404)
- Auto-creates submission log entry mapped: created→acknowledged, rejected→failed, pending→submitted
- PO draft detail enriched with all BC response fields
- PO Drafts list shows bc_response_status badge and bc_po_number
- Item detail last_po_draft includes bc_po_number and bc_response_status
- Frontend: BC Response section in PO Draft detail drawer (info display + form with status/PO#/DocID/notes)
- Frontend: BC response badges and PO numbers in PO Drafts list table
- Frontend: BC PO number shown in Item Detail's last PO draft section
- No ledger mutations, no BC API calls — informational response capture only
- Backend: 19/19 tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_78.json`
---

## 2026-03-14: BC PO Linkage to Incoming Supply (iteration_79)

### What Was Built
- PO draft → incoming supply conversion now stores `po_draft_id` on created supply records
- Fixed pre-existing bug: duplicate check used wrong collection (`incoming_supply` → `inv_incoming_supply`)
- BC response `created` advances linked planned supply to `ordered`, sets `bc_po_number` and `bc_document_id`
- BC response `rejected`/`pending` do NOT alter linked supply
- Linkage is idempotent — safe to repeat
- `GET /api/inventory-ledger/po-drafts/{id}/incoming-supply` returns linked supply records
- PO draft detail enriched with `linked_supply_count`, `linked_supply_status_counts`, `linked_supply_has_bc_po_number`
- Frontend: Linked Incoming Supply section in PO Draft detail drawer (table with item/qty/status/BC PO#, status count badges)
- Frontend: After BC response created, linked supply refreshes to show ordered status and BC PO#
- No ledger mutations, no BC API calls
- Backend: 17/17 tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_79.json`
---

## 2026-03-14: BC Receipt Capture (iteration_80)

### What Was Built
- `POST /api/inventory-ledger/po-drafts/{id}/bc-receipt` — records BC PO receipt, advancing ordered→received via existing `transition_supply_status` pipeline
- Auto-creates receipt ledger movements through the standard workflow
- Full receipt supported; partial receipt cleanly rejected (422); over-receipt rejected (422)
- Sets `bc_receipt_at` and `bc_receipt_notes` on supply records for traceability
- Duplicate receipt is idempotent (returns skipped, not error)
- Validates: draft exists (404), bc_response_status=created (422), linked supply exists (422)
- PO draft detail enriched with `linked_supply_received_count`, `linked_supply_ordered_count`, `linked_supply_total_qty`, `linked_supply_received_qty`
- Linked supply endpoint returns `receipt_summary` object
- Frontend: "Record Receipt" button in Linked Incoming Supply section (visible when ordered supply exists)
- Frontend: Receipt form shows ordered items with qty, notes input, Confirm/Cancel
- Frontend: Receipt result summary (received/skipped/error counts)
- Frontend: Linked supply table now includes "Received" column with date
- Frontend: Receipt summary strip below table (total qty, received qty, ordered/received counts)
- Frontend: After receipt, refreshes linked supply, draft detail, and all inventory views
- Backend: 13/13 tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_80.json`
---

## 2026-03-14: BC Sales Shipment Capture (iteration_81)

### What Was Built
- `POST /api/inventory-ledger/sales-orders/{id}/bc-shipment` — records BC shipment and releases committed inventory via existing `release_order_commitments` pipeline
- Supports full and partial shipment. Over-shipment rejected (422). Idempotent for fully released SOs.
- Shipment logs stored in `bc_shipment_logs` collection (shipment_id, bc_shipment_number, bc_document_id, shipped_at, notes, lines)
- `GET /api/inventory-ledger/sales-orders/{id}/summary` — returns commitment/release/remaining per item with latest shipment info
- `GET /api/inventory-ledger/sales-orders/{id}/shipment-log` — reverse chronological shipment history
- Fixed data edge case: SO commitments across multiple customer_ids handled by aggregating from raw movements
- Frontend: "Record Shipment" button on Demand tab toolbar
- Frontend: ShipmentCaptureDialog — SO lookup, commitment summary, line-level ship qty inputs, BC fields, shipment result, shipment history
- Downstream views (demand, supply coverage, exceptions, Action Center) automatically reflect reduced commitment through existing pipelines
- Backend: 18/18 tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_81.json`


---

## 2026-03-14: BC Sales Invoice Capture (iteration_82)

### What Was Built
- `POST /api/inventory-ledger/sales-orders/{id}/bc-invoice` — records BC invoice after full shipment
- Validates: SO exists (404), remaining committed qty = 0 (422), shipment activity exists (422)
- Invoice log stored in `bc_invoice_logs` (invoice_log_id, bc_invoice_number, bc_document_id, invoice_date, invoice_notes, captured_at)
- `GET /api/inventory-ledger/sales-orders/{id}/invoice-log` — reverse chronological invoice history
- SO summary enriched with `operational_status` (committed | partially_released | partially_shipped | shipped | complete) and `is_fulfillment_complete` flag
- Summary includes `latest_bc_invoice_number` and `latest_bc_invoice_at`
- Frontend: Invoice Capture section in ShipmentCaptureDialog (visible when fully shipped + shipments exist)
- Frontend: Invoice form (BC Invoice #, Doc ID, Date, Notes, Record Invoice button)
- Frontend: Fulfillment Complete indicator when operational_status=complete
- Frontend: Invoice History section, operational status badge in summary
- No ledger mutations, no accounting entries, no BC API calls
- Backend: 16/16 tests passed, Frontend: all UI flows verified
- Test report: `/app/test_reports/iteration_82.json`



- Test report: `/app/test_reports/iteration_77.json`


- Test report: `/app/test_reports/iteration_75.json`

---

## 2026-03-14: Sales Order Type Awareness — Warehouse vs Drop-Ship (iteration_83)

### What Was Built
- `GET /api/inventory-ledger/sales-orders/{id}/order-type` — returns order type (default: warehouse)
- `PATCH /api/inventory-ledger/sales-orders/{id}/order-type` — sets order type (warehouse|drop_ship), validates no remaining commitments before allowing switch to drop_ship
- `POST /bc-shipment` updated: drop_ship orders record shipment without inventory release (no order_release movements)
- `POST /bc-invoice` updated: drop_ship orders only require shipment log (skip commitment/release checks)
- `GET /summary` updated: drop_ship returns order_type, 0 commitments, empty lines, operational_status from shipment/invoice logs
- `POST /reconcile-sales-order` rejects drop_ship orders (422: no inventory commitments to reconcile)
- `so_order_types` collection stores per-SO order type settings
- Demand signals, supply coverage, action center naturally exclude drop_ship (no commitments exist)
- Frontend: ShipmentCaptureDialog enhanced with order type selector (Warehouse/Drop-Ship dropdown)
- Frontend: Teal "Drop-Ship Order" summary strip for drop_ship, standard commitment strip for warehouse
- Frontend: Manual line entry (item # + qty) for drop_ship shipments instead of commitment-based lines
- Frontend: Order type badge ("No inventory impact" / "Warehouse inventory")
- Frontend: Conditional invoice section shows after shipment for drop_ship (no commitment gate)
- Frontend: Shipment history shows "drop-ship" badge for drop_ship shipments
- Backend: 14/14 tests passed, Frontend: 100% UI verification
- Test report: `/app/test_reports/iteration_83.json`

---

## 2026-03-14: Drop-Ship Purchase Order Workflow Tracking (iteration_84)

### What Was Built
- PO draft model extended with `po_type` (warehouse_supply|drop_ship) and `sales_order_id` fields
- `POST /api/inventory-ledger/sales-orders/{id}/generate-drop-ship-po-draft` — creates linked PO draft from drop-ship SO with lines, vendor, notes
- `GET /api/inventory-ledger/sales-orders/{id}/drop-ship-po-drafts` — lists linked DS PO drafts
- Drop-ship PO drafts excluded from incoming supply conversion (returns 422)
- BC PO response capture works for drop-ship drafts but skips incoming supply linkage
- `POST /api/inventory-ledger/sales-orders/{id}/drop-ship-vendor-shipment` — records vendor shipment for traceability only (no inventory movements)
- `GET /api/inventory-ledger/sales-orders/{id}/drop-ship-vendor-shipment-log` — lists vendor shipment logs
- Invoice capture updated: drop-ship accepts either BC shipment or vendor shipment as evidence
- SO summary enriched with: linked_drop_ship_po_draft_count, linked_drop_ship_po_draft_id, latest_drop_ship_po_status, latest_vendor_shipment_number, latest_vendor_shipped_at
- Operational status progression for drop-ship: pending → po_drafted → shipped → complete
- New collection: `ds_vendor_shipment_logs` for vendor shipment traceability
- Frontend: "Generate Drop-Ship PO" button + form (item/qty/description lines, vendor name, notes)
- Frontend: Linked PO drafts list with status, vendor, line counts
- Frontend: "Record Vendor Shipment" button + form (item/qty lines, vendor shipment #, linked PO draft select)
- Frontend: Vendor shipment log display
- Frontend: Drop-ship summary strip enriched with PO info, vendor shipment info
- All safeguards: no BC API calls, no incoming supply for DS POs, no warehouse inventory impact
- Backend: 15/15 tests passed, Frontend: 100% UI verified
- Test report: `/app/test_reports/iteration_84.json`

---

## 2026-03-14: Document Linkage & Process Checklist (iteration_85)

### What Was Built
- New `document_links` collection with CRUD endpoints: POST/GET/DELETE
- Document types: customer_po, warehouse_agreement, approval_backup, vendor_po_support, other
- Entity types: sales_order, po_draft
- Process checklist derivation:
  - Warehouse SO: customer_po_attached, approval_support_present, warehouse_agreement
  - Drop-ship SO: customer_po_attached, approval_support_present, ds_po_draft_created
  - PO Draft: vendor_assigned, export_ready, support_doc_present
- SO summary enriched with linked_document_count, linked_documents_by_type, process_checklist, checklist_complete
- PO draft detail enriched with same fields
- Dedicated checklist endpoints: GET /document-links/checklist/sales-order/{id} and /po-draft/{id}
- Frontend: Reusable DocumentLinksSection component (add/list/delete docs)
- Frontend: Reusable ProcessChecklistSection component (check/warning indicators, Complete/Incomplete badge)
- Both components integrated in ShipmentCaptureDialog (for SOs) and PODraftDetailDrawer (for PO drafts)
- All safeguards: no BC calls, no inventory changes, metadata pointers only
- Backend: 16/16 tests passed, Frontend: 100% verified, Regression: iteration 83+84 pass
- Test report: `/app/test_reports/iteration_85.json`

---

## 2026-03-14: Approval Workflow Tracking (iteration_86)

### What Was Built
- New `approval_logs` collection with CRUD endpoints: POST /approvals/request, PATCH /approvals/{id}, GET /approvals
- Approval statuses: pending, approved, rejected (not_requested is derived when no approvals exist)
- Entity types: sales_order, po_draft. Approval types: sales_order, purchase_order
- Validation: invalid entity_type/approval_type returns 422, non-existent PO draft returns 404, already-decided approval returns 422
- SO summary enriched with approval_status, latest_approval_type, latest_approval_at, approval_history_count
- PO draft detail enriched with same fields
- Checklist integration:
  - Warehouse SO: customer_po_attached, approval_requested, approval_granted, warehouse_agreement
  - Drop-ship SO: customer_po_attached, ds_po_draft_created, approval_granted
  - PO draft: vendor_assigned, export_ready, approval_granted
- Frontend: Reusable ApprovalSection component with status badge (color-coded), request form, approve/reject controls for pending, decision notes, approval history
- Integrated in both ShipmentCaptureDialog (for SOs) and PODraftDetailDrawer (for PO drafts)
- Visual indicators for pending (amber) and rejected (red) approvals
- Backend: 19/19 tests passed, Frontend: 100% verified, Regression: iteration 84+85 pass
- Test report: `/app/test_reports/iteration_86.json`

---

## 2026-03-14: Operations Queue — Unified Worklist (iteration_87)

### What Was Built
- GET /api/inventory-ledger/operations-queue endpoint with eligibility rules, priority scoring, filtering (entity_type, status), pagination (limit, offset)
- Queue logic:
  - Warehouse SO: approval, customer PO doc, shipment, invoice
  - Drop-ship SO: approval, customer PO doc, DS PO draft, vendor/BC shipment, invoice
  - PO Draft: vendor, approval, BC export, BC response
- Priority scoring: missing_approval=50, missing_documents=40, inventory_shortage=35, missing_po_draft=30, missing_vendor=25, pending_bc_export=20, pending_bc_response=15, pending_shipment=10, pending_invoice=5
- Items with all actions complete excluded from queue
- Response: total, high_priority_count, items with entity_type/id, order_type, vendor_name, approval_status, checklist_complete, priority_score, action_required[], next_action, created_at
- New /operations-queue page: table with Type/ID/Order Type/Priority/Action Required/Next Action/Approval/Created columns
- Type filter dropdown (All/Sales Orders/PO Drafts), search by ID or action, priority color badges (red>=40, amber 20-39, blue<20)
- Clickable rows open detail panel with entity info, actions list, link to Inventory Ledger
- Dashboard OperationsQueueSummaryCard with total + high priority + top 3 items preview + View All link
- Nav link "Operations Queue" in sidebar
- Backend: 19/19 tests, Frontend: 100%, Regression: iterations 85-86 pass
- Test report: `/app/test_reports/iteration_87.json`
