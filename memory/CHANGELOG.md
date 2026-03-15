# GPI Document Hub - Changelog

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
