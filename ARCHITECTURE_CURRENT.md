# GPI Document Hub - Architecture (Post-Remediation)

> Generated after the controlled technical-debt remediation pass of March 2026.

---

## 1. Authoritative Entrypoint

| File | Role |
|------|------|
| **`backend/main.py`** | **Single FastAPI app.** Creates the `app`, registers all routers, CORS, health check, and lifecycle hooks. This is what `uvicorn` serves. |
| `backend/server.py` | **Library.** Contains module-level DB connection, business-logic functions (upload, BC integration, email polling, etc.), the legacy `api_router`, and the `startup()` / `shutdown_db_client()` lifecycle functions that `main.py` calls. Does **not** create or serve a `FastAPI` instance. |
| `backend/server_new.py` | **Deleted.** Was an unused experimental entrypoint. |

### Startup flow

```
uvicorn main:app
  -> main.py creates FastAPI app
  -> main.py imports server (module-level code runs: DB connect, config load)
  -> main.py registers all routers
  -> main.py @on_event("startup") calls server.startup()
       -> creates indexes
       -> initializes services (event, cache, auto-resolve, vendor intel, etc.)
       -> starts background workers (email polling, alert eval, etc.)
```

---

## 2. Routing Convention

All API routers live under **`backend/routers/`** (single directory, single convention).

| Pattern | Example |
|---------|---------|
| Router file | `routers/auth.py`, `routers/ap_review.py`, `routers/spiro.py` |
| Router prefix | Each router sets its own prefix (e.g. `/auth`, `/ap-review`, `/spiro`) |
| App-level prefix | `main.py` adds `/api` when including: `app.include_router(router, prefix="/api")` |
| Effective URL | `/api/auth/login`, `/api/ap-review/vendors`, `/api/spiro/status` |

The legacy `api_router` from `server.py` (prefix `/api`) is still included for routes not yet extracted. The `backend/routes/` directory is **empty** (all modules migrated to `routers/`).

### Router inventory (37 modules)

```
routers/
  admin.py              alerts.py             aliases.py
  ap_review.py *        ap_validation.py      auth.py *
  auto_clear.py         automation_rules.py   bc_integration.py
  bc_sandbox.py         cache.py              dashboard.py
  document_intelligence.py  documents.py      email_polling.py
  events.py             file_import.py        freight_routing.py
  gpi_integration.py    inventory_items.py    inventory_ledger.py
  label_corrections.py  layout_fingerprints.py  mailbox_sources.py
  metrics.py            migration_routes.py   pilot.py
  reference_intelligence.py  sales_dashboard.py  settings.py
  sharepoint.py         spiro.py *            square9.py
  stable_vendor.py      vendor_extraction_profiles.py
  vendor_intelligence.py  vendors.py          workflows.py
```

`*` = migrated from `routes/` during this remediation pass.

---

## 3. Document Processing Pipeline

A canonical pipeline module at **`services/pipeline/document_pipeline.py`** defines the standard processing sequence for any ingested document.

### Pipeline stages (updated — 9 stages)

| # | Stage | Service | What it does |
|---|-------|---------|--------------|
| 1 | `classification` | `document_intelligence_service` → `document_intel_helpers` | AI doc-type classification + field extraction |
| 2 | `extraction` | (surfaces output from classification) | Expose extracted-field summary explicitly |
| 3 | `layout` | `layout_fingerprint_service` | Layout detection / structural signals / family ID |
| 4 | `entity_resolution` | `entity_resolution_service` | Match extracted names/IDs to DB entities |
| 5 | `transaction_match` | `transaction_matching_service` | Link document to existing draft transactions |
| 6 | `bundle_detection` | `document_bundle_service` | Group related documents into packets |
| 7 | `lifecycle_check` | `document_lifecycle_service` | Validate document set completeness for an entity |
| 8 | `policy_decision` | `decision_policy_service` | Evaluate automation rules and decide action |
| 9 | `learning_capture` | `learning_loop_service` | Update aggregated automation metrics |

> `STAGE_ORDER_V1` (7 stages without extraction/layout) is retained for backward compatibility.

### API

```
POST /api/document-intelligence/pipeline/{doc_id}
     ?stop_after=entity_resolution        (optional: stop early)
     &skip_stages=bundle_detection        (optional: comma-separated)

GET  /api/document-intelligence/pipeline/stages
     -> { "stages": ["classification", ...] }

GET  /api/document-intelligence/pipeline/runs/{doc_id}
     ?limit=20                            (optional: 1-100, default 20)
     -> { "document_id": "...", "runs": [...], "count": N }
```

### Key design decisions

- **Wraps, does not rewrite.** Each stage delegates to an existing service function.
- **Non-fatal errors.** A stage failure is logged and recorded but does not abort the pipeline.
- **Structured output.** `PipelineResult` contains per-stage status, duration, and output keys.
- **Partial runs.** `stop_after` and `skip_stages` allow callers to run subsets.

### 3a. Pipeline Hardening & Observability (March 2026)

#### Stage-level instrumentation

Every executed stage records:

| Field | Type | Populated when |
|-------|------|---------------|
| `started_at` | ISO-8601 UTC string | Stage begins execution |
| `finished_at` | ISO-8601 UTC string | Stage completes (success or failure) |
| `duration_ms` | float (rounded to 0.1ms) | Always (computed from monotonic clock) |
| `output` | bounded dict | Stage produces summary output |
| `error` | string (max 500 chars) | Stage status is `error` only |

#### Status semantics (canonical)

| Status | Meaning | Example |
|--------|---------|---------|
| `ok` | Stage executed successfully and produced output | Classification returned a doc type |
| `skipped` | Stage did **not execute** — either explicitly skipped by caller (`skip_stages`) or a dependency-based precondition was not met (no work attempted) | Extraction skipped because classification returned no fields; lifecycle_check skipped because no high-confidence entity was resolved |
| `error` | Stage **attempted work and failed** (unhandled exception or domain-level failure) | Layout fingerprinting threw an exception; document not found in DB during a lookup |

**Key distinction:** `skipped` means "nothing was attempted", `error` means "work was attempted and it failed".

#### Pipeline-level metadata

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `RUN-{12 hex chars}` | Unique per pipeline execution |
| `document_id` | string | The processed document |
| `pipeline_version` | `v2` | Schema version for trace format |
| `started_at` / `finished_at` | ISO-8601 UTC | Pipeline wall-clock bounds |
| `total_duration_ms` | float | End-to-end monotonic duration |
| `status` | `ok` / `partial` / `pending` | `ok` = all stages ok/skipped, `partial` = at least one error |
| `stages_run` | int | Count of stages with status `ok` |
| `stages_skipped` | int | Count of stages with status `skipped` |
| `stages_errored` | int | Count of stages with status `error` |

#### Output safety

All stage outputs pass through `_sanitize_output()` before serialisation:

- String values capped at **500 characters**
- List values capped at **25 items** (with `_<key>_truncated` count)
- Maximum **25 keys** per output dict (with `_truncated_keys` count)
- Error messages capped at **500 characters**

This ensures persisted trace payloads remain bounded regardless of service output size.

#### Trace persistence

Every pipeline run is persisted to the **`pipeline_runs`** MongoDB collection (unless `persist=False`).

```
pipeline_runs document shape:
{
  "run_id":            "RUN-A1B2C3D4E5F6",
  "document_id":       "DOC-abc123",
  "pipeline_version":  "v2",
  "started_at":        "2026-03-15T14:00:00.000Z",
  "finished_at":       "2026-03-15T14:00:02.500Z",
  "total_duration_ms": 2500.0,
  "status":            "ok",
  "stages_run":        7,
  "stages_skipped":    2,
  "stages_errored":    0,
  "stages": [
    {
      "stage": "classification",
      "status": "ok",
      "started_at": "...",
      "finished_at": "...",
      "duration_ms": 350.0,
      "output": { "document_type": "AP_INVOICE", "confidence": 0.95, ... }
    },
    ...
  ],
  "_persisted_at": "2026-03-15T14:00:02.510Z"
}
```

Traces are retrieved via `GET /api/document-intelligence/pipeline/runs/{doc_id}` (newest first, default limit 20).

---

## 3b. Document Intelligence Domain (Consolidated)

### Before-state: server.py dependency

`document_intelligence_service.py` imported 4 functions directly from `server.py`:

| Function | Lines in server.py | Purpose |
|----------|-------------------|---------|
| `classify_document_with_ai()` | ~200 | Gemini AI classification + field extraction |
| `normalize_extracted_fields()` | ~40 | Amount/date/string normalization |
| `compute_ap_normalized_fields()` | ~100 | AP-specific flat field computation |
| `make_automation_decision()` | ~70 | Decision matrix (manual/review/auto_link/auto_create) |
| `validate_bc_match()` | ~450 | BC validation + extraction quality scoring |

### After-state: decoupled

```
services/
  document_intel_helpers.py       ← NEW: extracted logic from server.py
    classify_document_with_ai()     (fully extracted, no server.py dependency)
    normalize_extracted_fields()    (fully extracted, pure function)
    compute_ap_normalized_fields()  (fully extracted, pure function)
    make_automation_decision()      (fully extracted, pure function)
    validate_bc_match()             (thin adapter → server.py, too entangled for full extraction)

  document_intelligence_service.py  — orchestration facade (imports helpers, NOT server.py)
  ai_classifier.py                  — alternative classification (threshold-based, no AI)
  invoice_extractor.py              — structured extraction adapters
  layout_fingerprint_service.py     — layout detection / structural signals
  document_bundle_service.py        — bundle grouping logic
  document_lifecycle_service.py     — lifecycle derivation/validation
```

### Service boundaries

| Service | Boundary |
|---------|----------|
| `document_intel_helpers` | Pure business logic: classification, normalization, decision matrix |
| `document_intelligence_service` | **Orchestration facade only** — calls helpers, assembles readiness, stores results |
| `ai_classifier` | Alternative threshold-based classifier (no AI) |
| `invoice_extractor` | Structured extraction adapters |
| `layout_fingerprint_service` | Layout detection / structural signals / family ID |
| `document_bundle_service` | Bundle grouping logic |
| `document_lifecycle_service` | Lifecycle derivation / validation |

### Compatibility wrappers

`server.py` retains thin wrappers for all 4 extracted functions so that any other callers in the monolith continue to work without changes:
- `classify_document_with_ai()` → delegates to `document_intel_helpers`
- `normalize_extracted_fields()` → delegates to `document_intel_helpers`
- `compute_ap_normalized_fields()` → delegates to `document_intel_helpers`
- `make_automation_decision()` → delegates to `document_intel_helpers`

### Known follow-up debt

- `validate_bc_match()` remains in server.py (15+ module-level dependencies). Needs deeper extraction in a dedicated pass.
- `document_intelligence_service.py` still has some mixed formatting/readiness logic that could be further split.
- `ai_classifier.py` and the AI classification in `document_intel_helpers` are two separate classification paths — could be unified under a common interface.

---

## 4. Reference Intelligence Domain (Consolidated)

### Before-state

Seven services with overlapping responsibilities:

| Service | Lines | Responsibility |
|---------|-------|---------------|
| `entity_resolution_service` | 638 | Match extracted fields (customer, vendor, PO, invoice) to DB entities |
| `reference_intelligence_service` | 1729 | AI-assisted reference resolution against BC — extract, classify, normalize, score |
| `vendor_intelligence_service` | 533 | Vendor behavior profiles for scoring hints |
| `stable_vendor_service` | 1097 | Vendor stability evaluation and auto-ready routing |
| `unified_vendor_matcher` | 586 | Multi-source vendor name matching (doc history, Spiro, BC, SharePoint) |
| `bc_reference_resolver` | 550 | Resolve reference numbers against BC tables (cache-first, then API) |
| `bc_reference_cache_service` | 700 | Local searchable cache of BC entities |

**Overlaps removed:**
- 3 duplicate normalization implementations → `reference_helpers.py`
- 2 duplicate SequenceMatcher fuzzy scorers → `reference_helpers.fuzzy_ratio()`
- 2 duplicate BC OAuth token + company ID managers → `bc_access.BCAccessAdapter`
- 2 duplicate freight carrier keyword lists → `reference_helpers.is_freight_carrier()`

### After-state: service boundaries

```
services/
  reference_helpers.py          ← NEW: shared normalization, matching, freight detection
  bc_access.py                  ← NEW: shared BC OAuth adapter (token + company ID)
  entity_resolution_service.py  — Document field → DB entity matching (uses reference_helpers)
  reference_intelligence_service.py — AI reference scoring + resolution (uses reference_helpers)
  vendor_intelligence_service.py — Vendor behavior profiles (unchanged)
  stable_vendor_service.py      — Vendor stability + auto-ready (unchanged, consumes vendor_intel)
  unified_vendor_matcher.py     — Multi-source vendor matching (uses reference_helpers + bc_access)
  bc_reference_resolver.py      — BC table lookup (uses bc_access)
  bc_reference_cache_service.py — BC entity cache (unchanged)
```

### Canonical reference resolution flow

```
Document received
  │
  ├─ 1. NORMALIZATION  (reference_helpers)
  │     normalize_text()           — generic field matching
  │     normalize_reference()      — PO/BOL/INV → BC lookup key
  │     normalize_company_name()   — vendor/customer name matching
  │
  ├─ 2. ALIAS / STABLE-NAME LOOKUP
  │     entity_resolution_service  — checks vendor_aliases, customer_aliases
  │     vendor_intelligence_service — provides resolver hints from profile
  │
  ├─ 3. LOCAL MATCHING
  │     unified_vendor_matcher     — doc history, Spiro CRM, SharePoint patterns
  │     entity_resolution_service  — PO/invoice against drafts, hub_documents
  │
  ├─ 4. BC RESOLUTION
  │     bc_reference_cache_service — cache-first (fast, <50ms)
  │     bc_reference_resolver      — BC API fallback (via bc_access adapter)
  │
  ├─ 5. SCORING / BEST-MATCH SELECTION
  │     reference_intelligence_service.score_bc_match()
  │       — domain alignment, counterparty, semantic, date, amount, vendor behavior
  │     reference_intelligence_service.determine_match_outcome()
  │       — Strong / Likely / Needs Review / Suppressed / Rejected
  │
  └─ 6. STABILITY / ROUTING DECISION
        stable_vendor_service      — evaluate_vendor_stability() + evaluate_document()
```

### Shared helpers (`reference_helpers.py`)

| Function | Purpose | Used by |
|----------|---------|---------|
| `normalize_text(val)` | Generic string → matching-safe form | entity_resolution |
| `normalize_reference(val, return_trace)` | Reference number → BC lookup key | reference_intelligence, bc_cache |
| `normalize_company_name(name)` | Company name → matching key | unified_vendor_matcher |
| `fuzzy_ratio(a, b, normalizer)` | SequenceMatcher similarity | entity_resolution, unified_vendor_matcher |
| `fuzzy_vendor_match(a, b)` | Quick prefix/token vendor check | reference_intelligence |
| `is_freight_carrier(name)` | Freight keyword detection | reference_intelligence, unified_vendor_matcher |

### Shared BC adapter (`bc_access.py`)

| Method | Purpose | Used by |
|--------|---------|---------|
| `BCAccessAdapter.get_token()` | Cached OAuth2 token | bc_reference_resolver, unified_vendor_matcher |
| `BCAccessAdapter.get_company_id(token)` | Company ID lookup | bc_reference_resolver, unified_vendor_matcher |
| `BCAccessAdapter.api_url(path)` | Build BC API URL | (utility) |

### What remains intentionally separate

- **`entity_resolution_service`** and **`unified_vendor_matcher`** both do "vendor matching" but at different layers: entity resolution matches extracted text fields to *any* entity type (customer, vendor, PO, invoice), while the unified matcher is specifically for vendor names across external data sources. They serve different pipeline stages.
- **`vendor_intelligence_service`** and **`stable_vendor_service`** both deal with vendors but have distinct concerns: intelligence builds behavioral profiles from history, while stability evaluates thresholds for automation routing.
- **`bc_reference_resolver`** and **`bc_reference_cache_service`** are separate by design: the cache provides fast reads, the resolver provides authoritative API-backed lookups as fallback.

### Known follow-up debt

- `reference_intelligence_service.py` (1660+ lines) is still large — candidate for splitting into extract/classify/score/resolve sub-modules.
- `bc_reference_cache_service.py` still has its own BC config loading (env vars) that could use `bc_access.py`.
- Two pre-existing unused variables in `reference_intelligence_service.py` (lines 930, 941).

---

## 4b. Decisioning and Automation Domain (Consolidated)

### Before-state

Six services with overlapping patterns for timestamps, activity logging, and document mutation:

| Service | Lines | Responsibility |
|---------|-------|---------------|
| `decision_policy_service` | 744 | Policy evaluation → action recommendation (create_draft / link / hold / block) |
| `automation_rules_service` | 474 | Rule evaluation → workflow routing (queue / priority / flags / auto-ready) |
| `auto_resolution_service` | 775 | Background orchestrator — reference resolution + post-processing chain |
| `workflow_engine` | 1433 | Deterministic state machine for document workflows |
| `auto_clear_service` | 420 | Threshold-based auto-archiving |
| `auto_post_service` | 675 | BC API execution for posting / creating |

**Overlaps removed:**
- ~30 inline `datetime.now(timezone.utc).isoformat()` calls across 5 services → `utcnow()`
- Activity record creation pattern (from decision_policy_service) → `create_activity()`
- Document `$set` dict construction without `updated_utc` protection → `build_document_update()` / `apply_document_update()`

### Service boundaries (after)

```
┌──────────────────────────────────────────────────────────────────────┐
│                     DECISIONING & AUTOMATION                         │
│                                                                      │
│  automation_helpers.py  ← shared: utcnow(), create_activity(),       │
│                           build_document_update(), EligibilityResult  │
│                                                                      │
│  ┌──────────────────┐  ┌─────────────────────┐  ┌────────────────┐  │
│  │ decision_policy   │  │ automation_rules     │  │ workflow_engine │  │
│  │ WHAT to do        │  │ WHERE to route       │  │ STATE MACHINE  │  │
│  │ (policy → action) │  │ (rule → queue/prio)  │  │ (transitions)  │  │
│  └──────────────────┘  └─────────────────────┘  └────────────────┘  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ auto_resolution_service                                        │  │
│  │ WHEN & ORCHESTRATE (background: resolve → validate → route)    │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────┐  ┌─────────────────────┐                      │
│  │ auto_clear        │  │ auto_post            │                      │
│  │ ARCHIVE decision  │  │ BC EXECUTION         │                      │
│  │ (threshold check) │  │ (API calls)          │                      │
│  └──────────────────┘  └─────────────────────┘                      │
└──────────────────────────────────────────────────────────────────────┘
```

### Canonical decision-to-execution flow

```
Document enters system
  │
  ├─ 1. GATHER CONTEXT
  │     auto_resolution_service runs reference intelligence,
  │     vendor intel update, layout fingerprinting, AP validation
  │
  ├─ 2. EVALUATE POLICY
  │     decision_policy_service.evaluate_decision()
  │     → action recommendation (create_draft / link / hold / block)
  │
  ├─ 3. EVALUATE RULES
  │     automation_rules_service.evaluate_document()
  │     → routing decision (queue, priority, flags, auto-ready)
  │
  ├─ 4. CHECK ELIGIBILITY
  │     auto_clear_service.evaluate_auto_clear()
  │     → threshold checks per doc type → cleared / needs_review
  │     auto_post_service.check_auto_post_eligibility()
  │     → field-present checks for BC API readiness
  │
  ├─ 5. EXECUTE
  │     auto_clear_service → archive high-confidence docs
  │     auto_post_service → post AP invoices / create SOs in BC
  │
  └─ 6. RECORD
        workflow_engine → state transition + history
        automation_helpers.create_activity() → audit trail
```

### Shared helpers (`automation_helpers.py`)

| Function | Purpose | Used by |
|----------|---------|---------|
| `utcnow()` | ISO-8601 UTC timestamp | All 5 automation services |
| `create_activity()` | Canonical activity record insertion | decision_policy (+ available to others) |
| `build_document_update(fields)` | `$set` dict with enforced `updated_utc` | auto_resolution, auto_post |
| `apply_document_update(db, doc_id, fields)` | Build + execute document update | auto_post |
| `EligibilityCheck` | Single check result dataclass | (available for adoption) |
| `EligibilityResult` | Aggregate eligibility result | (available for adoption) |

### What remains intentionally separate

- **`decision_policy_service`** evaluates *configurable policies* with MongoDB-style operators (`$in`, `$gte`, etc.). **`automation_rules_service`** evaluates *routing rules* with a different condition format (`_gte` suffix, bool matching). These serve different configuration audiences and cannot easily be unified.
- **`auto_clear_service`** and **`auto_post_service`** both execute automation but against different targets (queue archival vs. BC API posting). They share the `utcnow()` helper but their eligibility checks and execution logic are domain-specific.
- **`workflow_engine`** is a deterministic state machine — it does not make decisions; it validates and records transitions. It was not modified in this pass because it has no duplicated logic with the other services.

### Known follow-up debt

- `workflow_engine.py` (1433 lines) is the largest file in the domain — candidate for splitting the workflow definitions (per doc type) into a config file.
- `auto_resolution_service.py` post-processing chain (lines 350-650) calls ~8 services sequentially — candidate for making this an explicit pipeline similar to `document_pipeline.py`.
- `auto_clear_service` and `auto_post_service` eligibility checks could adopt the shared `EligibilityCheck`/`EligibilityResult` types for consistent reporting.
- `decision_policy_service` condition checking and `automation_rules_service` condition matching could share a base operator library in a future pass.

---

## 5. Core Service Domains

| Domain | Key Services | DB Collections |
|--------|-------------|----------------|
| **Document Intelligence** | `document_intelligence_service` (facade), `document_intel_helpers`, `ai_classifier`, `invoice_extractor`, `layout_fingerprint_service` | `document_intelligence_results` |
| **Entity Resolution** | `entity_resolution_service`, `unified_vendor_matcher` | `entity_resolutions`, `vendor_aliases`, `customer_aliases` |
| **Transaction Matching** | `transaction_matching_service` | `transaction_matches` |
| **Document Bundling** | `document_bundle_service` | `document_bundles` |
| **Lifecycle Validation** | `document_lifecycle_service` | `lifecycle_validations` |
| **Decision Policy** | `decision_policy_service`, `automation_helpers` | `automation_policies`, `automation_decisions`, `activities` |
| **Automation & Execution** | `automation_rules_service`, `auto_resolution_service`, `auto_clear_service`, `auto_post_service`, `workflow_engine` | `hub_documents` (status fields), `automation_rules` |
| **Learning Loop** | `learning_loop_service` | `learning_events`, `extraction_hints`, `learning_metrics` |
| **Reference Intelligence** | `reference_intelligence_service`, `bc_reference_resolver`, `bc_reference_cache_service`, `reference_helpers`, `bc_access` | `matching_diagnostics`, `bc_reference_cache` |
| **BC Validation** | `bc_validation_service` (authoritative), `bc_access` (adapter) | (external BC API via adapter) |
| **Vendor Intelligence** | `vendor_intelligence_service`, `stable_vendor_service`, `vendor_extraction_profile_service` | `vendor_intelligence_profiles`, `vendor_extraction_profiles` |
| **Inventory Ledger** | `inventory_ledger_service` | `inventory_movements`, `inv_item_settings` |
| **Business Central** | `business_central_service`, `bc_sandbox_service`, `bc_write_safety_guard` | (external API) |
| **Email Ingestion** | Graph API polling (in `server.py`) | `mail_intake_log`, `mail_poll_runs` |

---

## 6. Known Follow-Up Refactor Targets

| Target | Description | Priority |
|--------|-------------|----------|
| **`server.py` (~9100 lines)** | Still contains legacy business-logic functions and `validate_bc_match`. Has thin wrappers for 4 extracted functions. Should continue extraction over time. | P1 |
| **`validate_bc_match()` in server.py** | 450-line function with 15+ module-level dependencies. Needs dedicated extraction pass. | P1 |
| **`reference_intelligence_service.py` (~1660 lines)** | Large file covering extract, classify, score, and resolve. Candidate for splitting into sub-modules. | P2 |
| **`routers/document_intelligence.py`** | Grew to ~660 lines. Could be split into sub-routers per pipeline stage. | P2 |
| **`routers/inventory_ledger.py`** | Large monolithic router. Candidate for splitting. | P2 |
| **`frontend/.../DocumentIntelligencePanel.js`** | Contains UI for all 6+ pipeline stages in one component. Should be broken into sub-components. | P2 |
| **Legacy `api_router` in `server.py`** | Routes still registered directly on `api_router` rather than in modular router files. Extract over time. | P1 |
| **`bc_reference_cache_service.py`** | Still loads BC config from env vars directly; could use `bc_access.py`. | P3 |
| **`sales_module.py`** | Standalone module included as a router. Should be migrated into `routers/sales.py`. | P3 |

---

## 7. Compatibility Notes

- **`backend/routes/`** directory exists but is empty (contains only a deprecation notice in `__init__.py`). Safe to delete entirely when all downstream references are confirmed removed.
- **`server.py`** no longer creates a `FastAPI` instance or registers routers. It is purely a library imported by `main.py`.
- All API endpoint paths are unchanged. No frontend modifications were required.
- **Reference helpers:** All existing per-service methods (`_normalize`, `_fuzzy_score`, `_normalize_name`, `_calculate_similarity`, `_is_freight_name`, `_fuzzy_vendor_match`, `normalize_reference`) are preserved as thin wrappers that delegate to `reference_helpers.py`. No external caller needs changes.
- **BC adapter:** `bc_reference_resolver`, `unified_vendor_matcher`, and `bc_validation_service` token/company methods are wrappers around `bc_access.BCAccessAdapter`. The adapter shares a single token cache across all three services.
- **`validate_bc_match()` wrapper:** `server.py` retains a 3-line wrapper that delegates to `services.bc_validation_service.validate_bc_match()`. All 6 internal call sites in server.py continue to work. `document_intel_helpers.validate_bc_match()` now imports from `bc_validation_service` directly (no longer imports from `server`).

---

## 5b. BC Validation Domain (Isolated — March 2026)

### Before-state

`validate_bc_match()` was a 450-line function in `server.py` with 15+ module-level dependencies:

| Dependency type | From server.py | Count |
|----------------|----------------|-------|
| Config globals | `DEMO_MODE`, `BC_CLIENT_ID`, `TENANT_ID`, `BC_READ_ENVIRONMENT` | 4 |
| BC auth functions | `get_bc_token()`, `get_bc_companies()` | 2 |
| Normalization | `normalize_extracted_fields()`, `normalize_vendor_name()` | 2 |
| Matching | `match_vendor_unified()`, `match_customer_in_bc()`, `calculate_fuzzy_score()` | 3 |
| Validation helpers | `_validate_po()` | 1 |
| DB access | `db` (module-level) | 1 |
| HTTP client | `httpx` | 1 |

### After-state

```
services/bc_validation_service.py   — Authoritative BC validation logic (NEW)
  ├─ validate_bc_match()            — Main orchestrator (public)
  ├─ _match_customer_in_bc()        — Customer matching against BC API (private)
  ├─ _validate_po()                 — PO validation against BC API (private)
  ├─ _compute_extraction_quality()  — Extraction completeness scoring (private)
  ├─ _normalize_vendor_name()       — BC-specific regex-based name normalization (private)
  └─ _calculate_fuzzy_score()       — BC-aware token overlap scoring (private)
```

### Dependency wiring (after)

| Need | Provided by | Replaces |
|------|------------|----------|
| Config (`DEMO_MODE`, `BC_CLIENT_ID`) | `deps` module | server.py globals |
| DB access | `deps.get_db()` | server.py module-level `db` |
| BC token + company ID | `bc_access.BCAccessAdapter` | server.py `get_bc_token()` / `get_bc_companies()` |
| BC API URL construction | `BCAccessAdapter.api_url()` | Hardcoded URL templates in server.py |
| Field normalization | `document_intel_helpers.normalize_extracted_fields()` | server.py `normalize_extracted_fields()` |
| Vendor matching | `unified_vendor_matcher.match_vendor_unified()` | Same (was already imported in server.py) |

### Compatibility wrappers retained

| Location | Wrapper | Reason |
|----------|---------|--------|
| `server.py:validate_bc_match()` | 3-line delegation to `bc_validation_service` | 6 internal call sites in server.py still reference it |
| `server.py:match_customer_in_bc()` | Delegation to `bc_validation_service._match_customer_in_bc()` | Called from within server.py scope |

### Why `_normalize_vendor_name` was NOT merged into `reference_helpers.normalize_company_name`

The two functions differ in suffix-removal approach:
- **`reference_helpers.normalize_company_name()`**: Uses simple `str.endswith()` check after lowercasing, removing punctuation last.
- **`_normalize_vendor_name()`**: Uses regex patterns with optional commas/dots (e.g., `r'\s*,?\s*(inc\.?|incorporated)$'`) *before* removing punctuation.

For input `"Acme, Inc."`:
- `normalize_company_name` → `"acme inc"` (comma removed, but suffix check runs before punct removal)
- `_normalize_vendor_name` → `"acme"` (regex matches `, Inc.` including comma and dot)

Merging would change validation outcomes for existing documents. Both are preserved.

### Known follow-up debt

- `server.py` still has ~6 call sites to the wrapper; these could migrate to importing from `bc_validation_service` directly in a future pass.
- `_match_customer_in_bc` creates its own `httpx.AsyncClient` per call; could share a session with the parent `validate_bc_match` call.
- `normalize_vendor_name()` and `reference_helpers.normalize_company_name()` should eventually be unified with a migration plan that verifies match outcomes don't change.

---

## 5c. Legacy api_router Cleanup (March 2026)

### What was done

- **Removed** `api_router = APIRouter(prefix="/api")` from server.py — it had zero active route registrations.
- **Removed** `app.include_router(legacy_api_router)` from main.py — it was a no-op.
- **Removed** 46 commented-out `# @api_router.*` decorator lines from server.py.
- **Removed** unused `APIRouter` import from server.py.
- **Updated** main.py docstring: server.py is documented as a utility library, not a route source.
- Route count verified stable at 427 (before and after).

### Current role of server.py

server.py is now a **utility library module**, not a router. It provides:

1. **Module-level startup side effects**: DB connection, scheduler, service initialization
2. **Handler function implementations**: 32 async handler functions consumed by router modules via `add_api_route()`
3. **Compatibility wrappers**: thin delegation functions for extracted services (`validate_bc_match`, etc.)
4. **Config globals**: `DEMO_MODE`, `TENANT_ID`, `BC_CLIENT_ID`, etc. (many also available in `deps.py`)

### Routes registered via add_api_route (still coupled)

| Router module | Route count | Handler source |
|--------------|------------|----------------|
| `routers/documents.py` | 10 | `services/document_handlers.py` |
| `routers/workflows.py` | 15 | `services/workflow_handlers.py` |
| `routers/reference_intelligence.py` | 7 | `services/reference_intelligence_handlers.py` |
| **Total** | **32** | All 32 extracted; server.py is no longer the authoritative source for any route handler |

All handler implementations have been extracted from server.py into dedicated service modules. The three router modules import exclusively from their respective handler services.

### Known follow-up debt

- **12 router modules** still import utility helpers from server.py (normalize_vendor_name, get_bc_companies, etc.)
- server.py retains orchestration logic (run_upload_and_link_workflow, email polling, BC integration helpers, AI classification) consumed by extracted handler modules via lazy import
- server.py retains module-level DB connection, startup/shutdown lifecycle, and background workers

### 5d. Document Handler Extraction (March 2026)

**10 document-domain handler implementations** moved from server.py to `services/document_handlers.py`.

#### Handlers extracted

| Handler | Route | Lines |
|---------|-------|-------|
| `upload_document` | `POST /api/documents/upload` | ~75 |
| `retry_document` | `POST /api/documents/{id}/retry` | ~55 |
| `resubmit_document` | `POST /api/documents/{id}/resubmit` | ~30 |
| `link_document` | `POST /api/documents/{id}/link` | ~35 |
| `intake_document` | `POST /api/documents/intake` | ~350 |
| `classify_document` | `POST /api/documents/{id}/classify` | ~55 |
| `resolve_and_link_document` | `POST /api/documents/{id}/resolve` | ~100 |
| `reprocess_document` | `POST /api/documents/{id}/reprocess` | ~120 |
| `batch_revalidate_documents` | `POST /api/documents/batch-revalidate` | ~90 |
| `preview_post_to_bc` | `POST /api/documents/{id}/preview-post` | ~200 |

Also extracted: `ResolveRequest` and `DryRunPreviewRequest` Pydantic models.

#### Dependency wiring (after)

| Need | Sourced from | NOT from server.py |
|------|-------------|-------------------|
| `DocType`, `WorkflowStatus`, `WorkflowEvent`, `SourceSystem`, `CaptureChannel`, `DocumentClassifier` | `services.workflow_engine` | ✓ |
| `TransactionAction`, `DEFAULT_JOB_TYPES` | `models.document_types` | ✓ |
| `DEFAULT_WORKFLOW_CONFIG`, `should_retry`, `increment_retry`, `initialize_retry_state`, `determine_square9_stage` | `services.square9_workflow` | ✓ |
| `get_event_service`, `emit_document_received` | `services.event_service` | ✓ |
| `get_derived_state_service` | `services.derived_state_service` | ✓ |
| `PILOT_MODE_ENABLED`, `get_pilot_metadata`, `get_pilot_capture_channel` | `services.pilot_config` | ✓ |
| `validate_bc_match` | `services.bc_validation_service` | ✓ |
| `match_vendor_unified` | `services.unified_vendor_matcher` | ✓ |
| `determine_folder_path` | `services.folder_routing_service` | ✓ |
| DB access | `deps.get_db()` | ✓ |

#### Remaining server.py imports (next-pass extraction targets)

These functions are still called via lazy `import server`:

| Function | Domain | Lines in server.py |
|----------|--------|-------------------|
| `run_upload_and_link_workflow` | Document orchestration | ~130 |
| `classify_document_with_ai` | AI/Gemini classification | ~20 |
| `classify_document_type` | Deterministic classification | ~50 |
| `upload_to_sharepoint` | SharePoint integration | ~80 |
| `create_sharing_link` | SharePoint integration | ~30 |
| `link_document_to_bc` | BC linking | ~60 |
| `get_bc_token` / `get_bc_companies` | BC auth | ~40 |
| `check_duplicate_purchase_invoice` | BC duplicate check | ~40 |
| `create_purchase_invoice_header` | BC draft creation | ~60 |
| `is_eligible_for_draft_creation` | Draft eligibility | ~50 |
| `compute_ap_normalized_fields` | AP normalization | ~20 |
| `lookup_vendor_alias` | Alias resolution | ~30 |
| `check_duplicate_document` | Document dedup | ~40 |
| `compute_ap_validation` | AP validation | ~50 |
| `make_automation_decision` | Decision matrix | ~40 |

---

### 5f. Reference Intelligence Handler Extraction (March 2026)

**7 reference-intelligence-domain handler implementations** moved from server.py to `services/reference_intelligence_handlers.py`.

#### Handlers extracted

| Handler | Route | Method |
|---------|-------|--------|
| `resolve_bc_reference` | `/api/bc/resolve-reference` | POST |
| `resolve_document_reference` | `/api/documents/{id}/resolve-reference` | POST |
| `resolve_document_intelligence` | `/api/documents/{id}/resolve-intelligence` | POST |
| `get_document_reference_intelligence` | `/api/documents/{id}/reference-intelligence` | GET |
| `trigger_auto_resolve` | `/api/documents/{id}/auto-resolve` | POST |
| `get_matching_debug` | `/api/documents/{id}/matching-debug` | GET |
| `rerun_matching_with_diagnostics` | `/api/documents/{id}/matching-debug/rerun` | POST |

#### Dependency wiring (after)

| Need | Sourced from | NOT from server.py |
|------|-------------|-------------------|
| `get_reference_resolver` | `services.bc_reference_resolver` | yes |
| `get_event_service` | `services.event_service` | yes |
| `get_reference_intelligence_service` | `services.reference_intelligence_service` | yes |
| `get_auto_resolve_service` | `services.auto_resolution_service` | yes |
| `get_label_correction_service` | `services.label_correction_service` | yes |
| `get_vep_service` | `services.vendor_extraction_profile_service` | yes |
| `get_layout_fingerprint_service` | `services.layout_fingerprint_service` | yes |
| `get_vendor_intelligence_service` | `services.vendor_intelligence_service` | yes |
| DB access | `deps.get_db()` | yes |

**No server.py-local functions required.** This was the cleanest extraction of the three passes — all service getters were already in proper service modules.

#### Milestone: All 32 add_api_route handlers extracted

With this pass, all three router domains are fully extracted:
- `services/document_handlers.py` — 10 handlers (March 2026)
- `services/workflow_handlers.py` — 15 handlers (March 2026)
- `services/reference_intelligence_handlers.py` — 7 handlers (March 2026)

server.py no longer serves as the authoritative source for any route handler implementation.

---

*Last updated: March 15, 2026 (Reference Intelligence Handler Extraction pass)*

### 5e. Workflow Handler Extraction (March 2026)

**15 workflow-domain handler implementations** moved from server.py to `services/workflow_handlers.py`.

#### Handlers extracted

| Handler | Route | Category |
|---------|-------|----------|
| `set_vendor_for_document` | `POST /api/workflows/ap_invoice/{id}/set-vendor` | AP mutation |
| `update_document_fields` | `POST /api/workflows/ap_invoice/{id}/update-fields` | AP mutation |
| `override_bc_validation` | `POST /api/workflows/ap_invoice/{id}/override-bc-validation` | AP mutation |
| `start_approval` | `POST /api/workflows/ap_invoice/{id}/start-approval` | AP approval |
| `approve_document` | `POST /api/workflows/ap_invoice/{id}/approve` | AP approval |
| `reject_document` | `POST /api/workflows/ap_invoice/{id}/reject` | AP approval |
| `mark_ready_for_review` | `POST /api/workflows/{id}/mark-ready-for-review` | Generic |
| `mark_reviewed` | `POST /api/workflows/{id}/mark-reviewed` | Generic |
| `start_approval_generic` | `POST /api/workflows/{id}/start-approval` | Generic |
| `approve_generic` | `POST /api/workflows/{id}/approve` | Generic |
| `reject_generic` | `POST /api/workflows/{id}/reject` | Generic |
| `complete_triage` | `POST /api/workflows/{id}/complete-triage` | Generic |
| `link_credit_to_invoice` | `POST /api/workflows/{id}/link-credit-to-invoice` | Generic |
| `tag_quality_doc` | `POST /api/workflows/{id}/tag-quality` | Generic |
| `export_document` | `POST /api/workflows/{id}/export` | Generic |

Also extracted: `SetVendorRequest`, `UpdateFieldsRequest`, `BCValidationOverrideRequest`, `ApprovalActionRequest` Pydantic models.

#### Dependency wiring (after)

| Need | Sourced from | NOT from server.py |
|------|-------------|-------------------|
| `WorkflowEngine`, `WorkflowStatus`, `WorkflowEvent`, `DocType` | `services.workflow_engine` | yes |
| `is_export_blocked` | `services.pilot_config` | yes |
| DB access | `deps.get_db()` | yes |

#### Remaining server.py imports (next-pass extraction targets)

| Function | Domain |
|----------|--------|
| `normalize_vendor_name` | Vendor name normalization (used by `update_document_fields`) |

---
