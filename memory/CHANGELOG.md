# GPI Document Hub - Changelog

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
