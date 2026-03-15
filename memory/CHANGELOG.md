# GPI Document Hub - Changelog

## March 15, 2026 — Final Orchestration Extraction (iter_115)

### Extraction
- Extracted 3 deep orchestration functions + 1 helper from server.py:
  - `classify_document_type` + `_get_category_for_doc_type` → `services/document_classification.py` (new)
  - `run_upload_and_link_workflow` → `services/document_linking.py` (extended)
  - `poll_mailbox_for_documents` → `services/mailbox_polling.py` (new)
- Added `AI_CLASSIFICATION_ENABLED`, `AI_CLASSIFICATION_THRESHOLD` to deps.py

### Consumer rewiring
- `services/document_handlers.py` — **FULLY DECOUPLED** from server.py (removed `_server()` lazy import, all `srv.*` calls replaced)
- `routers/mailbox_sources.py` — `poll_mailbox_for_documents` now imported from `services.mailbox_polling`

### Architecture state
- server.py import sites: **4 → 2** (only background task state + `_internal_intake_document` pipeline call)
- server.py: 7831 → 7467 lines (3 functions replaced with thin wrappers)
- Cumulative: **37 → 2 import sites** (95% reduction across entire hardening program)

### Guardrail tests updated
- `test_architecture_guardrails.py`: 25 → 30 tests (added document_classification, mailbox_polling, run_upload_and_link_workflow importability + document_handlers full decoupling checks)

### Testing
- 30/30 architecture guardrail tests passed
- 136/136 regression tests passed
- Testing agent: 100% pass rate, zero action items
- Route count stable at 427

---

## March 15, 2026 — Architecture Hardening Pass (iter_114)

### Dependency cleanup
- Reduced server.py import sites from 37 → 4 across routers/services (89% reduction)
- **Fully decoupled** from server.py: `routers/settings.py`, `routers/sharepoint.py`, `routers/workflows.py`, `services/vendor_matching.py`
- **Partially decoupled**: `routers/mailbox_sources.py` (2 of 4), `services/document_handlers.py` (6 of 8)

### New modules extracted from server.py
- `services/settings_helpers.py`: Settings admin utilities (SECRET_KEYS, mask_secret, current_config)
- `services/graph_access.py`: Microsoft Graph API token acquisition (get_graph_token, get_email_token)
- `services/email_helpers.py`: Email watcher configuration and subscription management
- `services/sharepoint_helpers.py`: SharePoint file upload, folder creation, sharing links
- `services/bc_draft_service.py`: BC Purchase Invoice duplicate checking and header creation
- `services/document_linking.py`: BC document attachment linking workflow

### Consumer rewiring
- `routers/settings.py` → deps + settings_helpers + graph_access + email_helpers
- `routers/sharepoint.py` → sharepoint_helpers
- `routers/workflows.py` → document_linking
- `routers/mailbox_sources.py` → graph_access (get_email_token)
- `services/document_handlers.py` → sharepoint_helpers + document_linking + bc_draft_service
- `services/vendor_matching.py` → deps + vendor_name_helpers

### Architecture guardrails
- Created `tests/test_architecture_guardrails.py` (25 tests)
- Allowlist enforcement prevents new server.py imports in routers/services
- Route count stable at 427

### Config centralization
- Added `FOLDER_MAP` and `UPLOAD_DIR` to `deps.py`
- `settings.py` now mutates `deps.*` attributes (not module-local globals) for runtime config updates

### Testing
- 25/25 architecture guardrail tests passed
- 136/136 tests across all extraction suites (0 regressions)
- Route count stable at 427

---

## March 15, 2026 — Orchestration Logic Extraction (iter_113)

### Extraction
- Extracted 7 business orchestration functions from server.py into 2 new service modules:
  - `services/vendor_matching.py`: `lookup_vendor_alias`, `match_vendor_in_bc`, `check_duplicate_document` (async DB/API operations)
  - `services/ap_computation.py`: `compute_ap_validation`, `compute_ap_status`, `compute_draft_candidate_flag`, `is_eligible_for_draft_creation` (pure computation)
- Rewired `services/document_handlers.py` to import directly from new modules
- Left thin compatibility wrappers in server.py for internal callers

### Testing
- 24/24 orchestration extraction tests passed
- 22/22 regression tests passed
- 90/90 tests passed across all 4 extraction suites (0 failures, 0 regressions)
- Route count stable at 427

### Architecture update
- Updated `ARCHITECTURE_CURRENT.md` with section 5h documenting the extraction

---

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
