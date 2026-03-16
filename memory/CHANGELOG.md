# GPI Document Hub - Changelog

## March 16, 2026 — Fix: Vendor KPI `$or` Key Collision Bug (P0)
- **Root Cause:** MongoDB `$or` key collision when spreading `vendor_applicable_filter` (which contains `$or`) into queries that also define their own `$or` — second key silently overwrites the first.
- **Fix:** Wrapped both `vendor_auto_resolved_total` and `vendor_needs_review_total` queries in `$and` to combine filters without key collision.
- **Affected file:** `backend/routers/dashboard.py`
- **Validated:** `Needs Review` (8) ≤ `Applicable` (58) — all KPIs now correct.

## March 16, 2026 — Vendor Matching Remediation (KPI Accuracy + Matching Correctness)

### 1. Fixed Dashboard Vendor KPI
- **Old**: Used all 79 documents as denominator, checked `vendor_canonical` existence = misleading "Vendor Match Rate"
- **New**: Uses vendor-applicable filter (58 AP/invoice-style docs) as denominator
- New accurate metrics: `vendor_applicable_total`, `vendor_auto_resolved_total`, `vendor_auto_resolve_rate`, `vendor_final_resolved_total`, `vendor_final_resolved_rate`, `vendor_needs_review_total`, `vendor_by_method`
- Renamed dashboard label from "Vendor Match Rate" → "Vendor Auto-Resolve"
- Removed misleading `vendor_resolution_rate` and `auto_resolved_docs` from alias_metrics

### 2. Fixed Cached BC Exact Match
- **Old**: Used `$or` with `name_normalized` AND regex against raw `displayName`
- **New**: Matches only on `name_normalized` field
- Added `backfill_bc_vendor_normalized()` utility — runs at startup, ensures all cached BC vendor records have normalized names
- Added index on `name_normalized` for fast exact match

### 3. Fixed Fuzzy Scoring
- **Old**: Used ad-hoc `rapidfuzz.fuzz.token_sort_ratio` directly
- **New**: Uses shared `calculate_fuzzy_score` from `vendor_name_helpers.py` which handles BC code prefix stripping, partial_ratio, and multi-strategy scoring

### 4. Clean Fuzzy Auto-Match vs Candidate Semantics
- **Old**: `fuzzy_match` method used for ALL fuzzy results regardless of score; 0.50+ returned as matched
- **New**: `fuzzy_match` ONLY for scores >= 0.90 (true auto-resolve), `fuzzy_candidate` for 0.60-0.89 (needs review), `no_match` for <0.60
- Updated `vendor_resolution_service.py` to correctly handle `fuzzy_candidate` as `needs_review` status
- Rejection guardrails preserved — previously rejected pairings always become `fuzzy_candidate` with `needs_review`

### 5. Aligned Vendor Metrics Across App
- Dashboard, vendor-resolution metrics, and alias metrics all use consistent vendor-applicable denominator
- `vendor_resolution_service.get_resolution_metrics()` now includes `vendor_applicable_total` and wider fuzzy score buckets (60-79, 80-89)

### 6. Tests
- Created `tests/test_vendor_remediation.py` — 22 tests covering all remediation items
- All 202 existing tests pass (zero regressions)
- Test report: iteration_121.json

### Files Changed
- `backend/services/vendor_matching.py` — exact match, fuzzy scoring, fuzzy_candidate semantics, backfill utility
- `backend/services/vendor_resolution_service.py` — fuzzy_candidate handling, vendor-applicable denominator in metrics
- `backend/routers/dashboard.py` — accurate vendor KPI with applicable filter, removed misleading metrics
- `backend/main.py` — startup backfill hook
- `frontend/src/pages/DashboardPage.js` — new vendor KPI display, renamed labels, method breakdown



## March 16, 2026 — Automation Intelligence (Confidence, Explainability, Reviewer Assist, Metrics)

### Feature 1: Automation Confidence Scoring
- Created `backend/services/automation_intelligence_service.py` with weighted scoring model
- 6 weighted signals: vendor_resolution (25%), entity_resolution (20%), extraction (20%), transaction_graph (15%), policy (10%), duplicate_risk (-10%)
- Thresholds: auto_execute >= 0.90, review >= 0.70, manual < 0.70
- Integrated into readiness engine — `evaluate_and_persist()` and `batch_evaluate()` now compute automation_confidence alongside readiness

### Feature 2: Decision Explainability Layer
- Structured explanation objects with decision, confidence, signals, supporting_evidence, risk_flags
- Endpoint: `GET /api/documents/{id}/decision-explanation`
- Frontend: `DecisionExplainabilityPanel.js` — "Why this decision?" card with confidence bar, evidence/risk lists, expandable signal breakdown

### Feature 3: Reviewer Assist Engine
- Generates context-aware suggestions for needs_review/blocked/ambiguous docs
- Suggestion types: confirm_vendor, resolve_vendor, confirm_customer, link_po, resolve_duplicate, correct_field
- Endpoints: `POST /api/documents/{id}/review-assist`, `POST /api/documents/{id}/accept-suggestion`
- Frontend: `ReviewerAssistPanel.js` — one-click accept/dismiss buttons for each suggestion

### Feature 4: Automation Metrics Dashboard
- Endpoint: `GET /api/automation/metrics` with rates, confidence distribution, signal averages, top causes
- Frontend: `AutomationMetricsCard.js` — shows automation/review/blocked rates, confidence distribution bar, signal strength chart, top review causes and blockers

### Files Created
- `backend/services/automation_intelligence_service.py`
- `backend/routers/automation_intelligence.py`
- `frontend/src/components/DecisionExplainabilityPanel.js`
- `frontend/src/components/ReviewerAssistPanel.js`
- `frontend/src/components/AutomationMetricsCard.js`
- `backend/tests/test_automation_intelligence.py` (35 tests)

### Testing: 35/35 backend, 3/3 frontend UI tests passed (iteration_120)


## March 16, 2026 — Dashboard Readiness, Config Extraction, AR Release Gate

### Dashboard Readiness Summary Card
- Added `readiness_summary` to `/api/dashboard/workflow-intelligence` endpoint
- Created `ReadinessSummaryCard` on dashboard with 5-status distribution, progress bar, confidence %, blockers/warnings
- 20/20 tests passing

### Config Service Extraction (Orchestration Refactor)
- Created `backend/services/config_service.py` — centralized config variables and token helpers
- Rewired settings.py, vendor_matching.py, mailbox_sources.py to import from config_service
- Added DB config sync in server.py `_load_config_from_db()`

### AR Release Gate (Prepay & Terms Approval)
- `backend/services/ar_release_gate_service.py` — 5 checks: customer_resolution, prepay_hold, credit_limit, payment_terms, ship_to
- `backend/routers/ar_release.py` — GET metrics, POST evaluate, POST override, GET queue
- `frontend/src/components/ARReleaseGatePanel.js` — sales document detail panel with check results, override form
- 27/27 backend tests, frontend UI verified
- Test reports: iteration_118.json, iteration_119.json



## March 15, 2026 — Shared Helper Extraction (iter_112)

### Extraction
- Extracted 6 shared utility helpers from server.py into 3 dedicated service modules:
  - `services/vendor_name_helpers.py`: `normalize_vendor_name`, `calculate_fuzzy_score`, `VENDOR_ALIAS_MAP`
  - `services/dashboard_helpers.py`: `aggregate_document_types_data`
  - `services/bc_api_helpers.py`: `get_bc_companies`, `get_bc_sales_orders`, `MOCK_COMPANIES`, `MOCK_SALES_ORDERS`
- Rewired 6 consumer modules: aliases.py, bc_integration.py, dashboard.py, workflow_handlers.py, metrics.py, pilot.py
- Fixed bc_sandbox_service.py: replaced `from server import BC_CLIENT_SECRET` with direct `os.environ.get()`
- Fixed latent `NameError` bugs in metrics.py and pilot.py (missing imports)
- Left thin compatibility wrappers in server.py for internal callers

### Testing
- 90/90 tests passed across 4 regression suites (0 failures, 0 regressions)
- Route count stable at 427

---

## March 15, 2026 — Reference Intelligence Handler Extraction (iter_111)

### Extraction
- Moved 7 reference-intelligence-domain handler implementations from server.py to `services/reference_intelligence_handlers.py`
- `routers/reference_intelligence.py` now imports from `services.reference_intelligence_handlers` (no longer from `server`)
- **Milestone: All 32 `add_api_route` handlers fully extracted from server.py**

### Handlers extracted (7)
- `resolve_bc_reference`, `resolve_document_reference`, `resolve_document_intelligence`, `get_document_reference_intelligence`, `trigger_auto_resolve`, `get_matching_debug`, `rerun_matching_with_diagnostics`

### Dependencies rewired (away from server.py)
- 8 service getters sourced directly from their proper service modules (bc_reference_resolver, event_service, reference_intelligence_service, auto_resolution_service, label_correction_service, vendor_extraction_profile_service, layout_fingerprint_service, vendor_intelligence_service)
- DB → `deps.get_db()`
- **Zero server.py-local functions required** — cleanest extraction of the three passes

### Testing
- 96/96 tests passed across 5 regression suites (0 failures, 0 regressions)
- Route count stable at 427

---

## March 15, 2026 — Workflow Handler Extraction (iter_110)

### Extraction
- Moved 15 workflow-domain handler implementations from server.py to `services/workflow_handlers.py`
- Moved `SetVendorRequest`, `UpdateFieldsRequest`, `BCValidationOverrideRequest`, `ApprovalActionRequest` Pydantic models to new module
- `routers/workflows.py` now imports from `services.workflow_handlers` (no longer from `server`)

### Handlers extracted (15)
- AP Invoice mutations: `set_vendor_for_document`, `update_document_fields`, `override_bc_validation`, `start_approval`, `approve_document`, `reject_document`
- Generic mutations: `mark_ready_for_review`, `mark_reviewed`, `start_approval_generic`, `approve_generic`, `reject_generic`, `complete_triage`, `link_credit_to_invoice`, `tag_quality_doc`, `export_document`

### Dependencies rewired (away from server.py)
- `WorkflowEngine`, `WorkflowStatus`, `WorkflowEvent`, `DocType` → `services.workflow_engine`
- `is_export_blocked` → `services.pilot_config`
- DB → `deps.get_db()`
- Remaining: `normalize_vendor_name` still lazy-imported from server.py (future extraction target)

### Testing
- 25/25 new workflow handler extraction tests passed
- 89/89 total tests passed across 4 regression suites (0 failures, 0 regressions)
- Route count stable at 427

### Architecture update
- Updated `ARCHITECTURE_CURRENT.md` with section 5e documenting the extraction
- 25 of 32 total `add_api_route` handlers now extracted (only 7 reference_intelligence handlers remain)

---

## March 15, 2026 — Document Handler Extraction (iter_109)

### Extraction
- Moved 10 document-domain handler implementations from server.py to `services/document_handlers.py`
- Moved `ResolveRequest` and `DryRunPreviewRequest` Pydantic models to new module
- `routers/documents.py` now imports from `services.document_handlers` (no longer from `server`)

### Dependencies rewired (away from server.py)
- Enums/classes → `services.workflow_engine`, `models.document_types`
- Square9/retry helpers → `services.square9_workflow`
- Event service → `services.event_service`
- Pilot config → `services.pilot_config`
- BC validation → `services.bc_validation_service`
- Vendor matching → `services.unified_vendor_matcher`
- Folder routing → `services.folder_routing_service`
- DB → `deps.get_db()`

### Testing
- 15/15 new handler extraction tests passed (10 route availability, 2 response shape, 2 decoupling, 1 route count)
- 112/112 total tests passed across all test files

---

## March 15, 2026 — Legacy api_router Cleanup (iter_108)

### Removed
- `api_router = APIRouter(prefix="/api")` from server.py (zero active routes)
- `app.include_router(legacy_api_router)` from main.py (was no-op)
- 46 commented-out `# @api_router.*` decorator lines from server.py
- Unused `APIRouter` import from server.py

### Documentation
- main.py docstring updated: server.py is a utility library, not a route source
- ARCHITECTURE_CURRENT.md section 5c added

### Testing
- 13/13 route cleanup tests passed (document routes, workflow routes, ref intel routes, route count = 427, api_router removed)
- 97/97 total tests passed across all test files
- Full API verification passed

---

## March 15, 2026 — BC Validation Isolation (iter_107)

### Extraction
- Moved `validate_bc_match()` (450 lines, 15+ deps) from `server.py` to new `services/bc_validation_service.py`
- Extracted: `_match_customer_in_bc`, `_validate_po`, `_compute_extraction_quality`, `_normalize_vendor_name`, `_calculate_fuzzy_score`
- Dependencies rewired: `deps.py` (config/DB), `bc_access.BCAccessAdapter` (token/company/URL), `document_intel_helpers` (normalization), `unified_vendor_matcher` (vendor matching)

### Compatibility
- `server.py` retains thin 3-line wrapper (6 internal call sites)
- `document_intel_helpers.validate_bc_match()` now imports from `bc_validation_service` (no longer from `server`)

### Testing
- 31/31 new BC validation tests passed (9 normalize, 5 fuzzy, 6 quality, 3 demo, 3 error, 2 compat, 3 API regression)
- 84/84 total tests passed across all test files
- Full API verification passed (health, auth, documents, dashboard, workflow, pipeline, events)

---

## March 15, 2026 — Pipeline Hardening & Observability (iter_106)

### Output Safety
- `_sanitize_output()` caps string values (500 chars), list values (25 items), and key count (25 keys) in stage outputs
- Error messages capped at 500 chars in `StageResult.to_dict()`
- Persisted traces bounded; no raw document data stored

### Status Semantics Documented
- `ok` = stage executed successfully
- `skipped` = stage did not execute (explicit skip or dependency-based)
- `error` = stage attempted work and failed
- Added inline docblock in `document_pipeline.py` formalizing the contract

### New API Endpoint
- `GET /api/document-intelligence/pipeline/runs/{doc_id}?limit=20` — retrieve persisted pipeline run traces, newest first

### Testing
- 31/31 new tests passed (5 sanitize, 5 StageResult, 2 PipelineResult, 3 timing, 3 status, 2 failure, 3 skip, 3 persistence, 4 API endpoint)
- 22/22 regression tests passed

---

## March 15, 2026 — Document Intelligence Consolidation (iter_105)

### Legacy Logic Extracted from server.py
- `services/document_intel_helpers.py` — classify_document_with_ai, normalize_extracted_fields, compute_ap_normalized_fields, make_automation_decision
- validate_bc_match → thin adapter (too entangled for full extraction)
- server.py retains 4-line compatibility wrappers

### document_intelligence_service Decoupled
- ZERO `from server import` statements remaining
- Now imports from document_intel_helpers + automation_helpers
- Uses shared utcnow() and create_activity()

### Pipeline Expanded (7 → 9 stages)
- Added `extraction` (stage 2) and `layout` (stage 3)
- STAGE_ORDER_V1 retained for backward compatibility

### Testing
- 115/115 passed (103 pytest + 12 API)

---

## March 15, 2026 — Decisioning & Automation Consolidation (iter_104)

### Shared Helpers Created
- `services/automation_helpers.py` — utcnow(), create_activity(), build_document_update(), apply_document_update(), EligibilityCheck, EligibilityResult

### Overlaps Removed
- ~30 inline datetime timestamp calls → 1 shared utcnow()
- Activity record pattern → 1 shared create_activity()
- Unprotected document $set dicts → build_document_update() with enforced updated_utc

### Services Updated
- decision_policy_service, automation_rules_service, auto_resolution_service, auto_clear_service, auto_post_service — all now use shared helpers
- workflow_engine — unchanged (no overlapping logic)

### Boundaries Documented
- decision_policy = WHAT to do, automation_rules = WHERE to route, auto_resolution = ORCHESTRATE, workflow_engine = STATE MACHINE, auto_clear = ARCHIVE, auto_post = BC EXECUTE

### Testing
- 78/78 passed (68 pytest + 10 API), grep verified 0 raw datetime calls

---

## March 15, 2026 — Reference Intelligence Consolidation (iter_103)

### Shared Helpers Created
- `services/reference_helpers.py` — normalize_text, normalize_reference, normalize_company_name, fuzzy_ratio, fuzzy_vendor_match, is_freight_carrier
- `services/bc_access.py` — BCAccessAdapter (shared BC OAuth token + company ID management)

### Overlaps Removed
- 3 duplicate normalizers → 1 shared module
- 2 duplicate SequenceMatcher scorers → 1 shared function
- 2 duplicate BC OAuth token managers → 1 shared adapter
- 2 duplicate freight keyword lists → 1 shared function

### Services Updated
- entity_resolution_service, reference_intelligence_service, unified_vendor_matcher, bc_reference_resolver — now delegate to shared helpers
- All original method signatures preserved as thin wrappers

### Testing
- 56/56 passed (45 unit + 11 API)

---

## March 15, 2026 — Technical Debt Remediation Pass (iter_102)

### Entrypoint Consolidation
- `main.py` is the single authoritative FastAPI app (confirmed by supervisor: `uvicorn main:app`)
- `server.py` converted to library: removed `app = FastAPI(...)`, all `app.include_router()`, `app.add_middleware()`, `@app.on_event()` decorators, and health check endpoint
- `server_new.py` deleted (was unused)

### Routing Consolidation
- Migrated `routes/auth.py` → `routers/auth.py`
- Migrated `routes/ap_review.py` → `routers/ap_review.py` (prefix: `/api/ap-review` → `/ap-review`)
- Migrated `routes/spiro.py` → `routers/spiro.py` (prefix: `/api/spiro` → `/spiro`)
- Deleted unused: `routes/config.py`, `routes/dashboard.py`, `routes/documents.py`, `routes/ingestion.py`, `routes/workflows.py`
- All 37+ routers now under `routers/` (single convention)

### Canonical Document Pipeline
- Created `services/pipeline/document_pipeline.py`
- 7 stages: classification, entity_resolution, transaction_match, bundle_detection, lifecycle_check, policy_decision, learning_capture
- API: `POST /api/document-intelligence/pipeline/{doc_id}`, `GET /api/document-intelligence/pipeline/stages`

### Architecture Documentation
- Created `ARCHITECTURE_CURRENT.md` at repo root

### Testing
- 16/16 backend tests passed — all API contracts preserved
- Test report: `/app/test_reports/iteration_102.json`

---

## March 15, 2026 — Learning Loop Engine (iter_101)

- Implemented learning event capture for user corrections (classification, fields, entity overrides)
- Vendor/customer alias auto-creation from corrections
- Extraction hints recording for future accuracy improvements
- Automation metrics aggregation (correction rate, automation success rate)
- API: `/api/document-intelligence/learning/summary`, `/api/document-intelligence/learning/events`
- UI: Learning Insights section in DocumentIntelligencePanel

## March 15, 2026 — Decision Policy Engine (iter_100)

- Rule-based automation decision engine
- Policy CRUD (create, list, update, delete)
- Evaluate document against policies → action + explanation
- Execute decisions (create_draft, link_existing, hold_for_review)
- Collections: `decision_policies`, `decision_results`

## March 15, 2026 — Document Lifecycle Validation (iter_99)

- Lifecycle completeness analysis per entity
- Template-based stage detection (Sales Order, AP, PO templates)
- Duplicate and inconsistency detection
- API: validate lifecycle, get lifecycle issues
- UI: DocumentLifecyclePage

## March 15, 2026 — Document Bundle Detection (iter_98)

- Automatic grouping of related documents into bundles
- Bundle type detection and completeness scoring
- Bundle CRUD and review queue
- UI: DocumentBundlesPage

## March 15, 2026 — Transaction Matching Verification (iter_97)

- Comprehensive test run of document-to-transaction matching feature
- All tests passed successfully

## March 16, 2026 — Autonomous Document Routing (Auto-Clear Gate)

- Created `services/document_routing_service.py`: pure-function routing engine evaluating 6 rule categories (confidence, required fields, validation, duplicates, entity resolution, optional fields)
- Routing statuses: `auto_process` (score >= 75), `review` (40-74), `blocked` (< 40)
- Integrated as pipeline stage 9 (`document_routing`) in `pipeline/document_pipeline.py`
- Integrated into document intake flow in `server.py` (runs after auto-clear)
- Added `/api/dashboard/routing-summary` endpoint
- Added `routing_summary` to `/api/dashboard/stats` and `/api/dashboard/workflow-intelligence`
- Added `/api/auto-clear/route/{doc_id}` and `/api/auto-clear/route-batch` endpoints
- Updated `DashboardPage.js` with `RoutingSummaryCard` showing counts, avg scores, progress bar, percentage labels
- Schema extension: `routing_status`, `routing_reasons`, `routing_score`, `routing_timestamp` on hub_documents
- 28 unit tests + 10 API integration tests, all passing
- Backfilled all 79 existing documents: 39 auto_process, 22 review, 18 blocked

## March 16, 2026 — Vendor Alias Learning System (iter_114)

- Created `services/vendor_alias_learning_service.py`: auto-learns vendor aliases from reviewer approvals
- Safety rules: requires ai_confidence >= 0.8, vendor_raw >= 3 chars, no conflict overwrite
- Hooked into `set_vendor_for_document` and `approve_document` in workflow_handlers.py
- Enhanced `lookup_vendor_alias` in vendor_matching.py to track usage_count and distinguish `learned_alias` from manual `alias`
- Added `GET /api/aliases/metrics` endpoint with total_aliases, auto_learned, alias_match_rate, top_aliases
- Added `DELETE /api/aliases/vendors/by-alias/{alias}` admin endpoint
- Enhanced `GET /api/aliases/vendors` with ?vendor_id and ?source filters
- Added alias_metrics to workflow-intelligence dashboard response
- Updated VendorIntelligenceCard in DashboardPage.js with alias learning metrics section
- Fixed Dockerfile CMD: server:app → main:app (was breaking Docker deployments)
- 21 unit tests + 13 API integration tests, all passing

## March 16, 2026 — Vendor Resolution Pipeline Improvements (iter_115)

- Upgraded fuzzy matching to use `rapidfuzz` (token_sort_ratio + partial_ratio) replacing simple token overlap
- Auto-match threshold: >=90% similarity triggers automatic vendor resolution
- Added rapidfuzz-based fuzzy step in `lookup_vendor_alias` against cached BC vendors (hub_bc_vendors)
- Added BC vendor alias bootstrap on startup: normalizes all BC vendor names and seeds vendor_aliases
- Standardized match_method values: `alias_match`, `fuzzy_match`, `bc_exact_match`, `manual_match`
- Added `vendor_resolution_rate` to `/api/aliases/metrics` and workflow-intelligence dashboard
- Updated VendorIntelligenceCard to show vendor resolution rate
- 25 unit tests for normalization + rapidfuzz + 9 API tests, all passing (55 total)

## March 16, 2026 — Vendor Resolution Observability + Negative Feedback Loop (iter_116)

- Created `services/vendor_resolution_service.py`: resolution object builder, rejection capture, guardrails, analytics
- Created `routers/vendor_resolution.py`: GET /api/vendor-resolution/metrics and /api/vendor-resolution/rejections
- Per-document `vendor_resolution` object: status (resolved/unresolved/ambiguous/needs_review), method, raw, normalized, score, reason, reviewed_override
- Negative feedback: captures rejected auto-matches in `vendor_match_rejections` collection when reviewer overrides fuzzy/exact match
- Safe auto-match guardrails: checks rejection history before accepting fuzzy matches, downgrades to needs_review if previously rejected
- Resolution analytics: rates, method breakdown, fuzzy score buckets (90-94/95-97/98-100), top 25 unresolved/corrected vendor strings
- Hooked into `set_vendor_for_document` for rejection capture + resolution override tracking
- 71 tests (14 unit + 25 normalization + 21 alias + 11 API), all passing
