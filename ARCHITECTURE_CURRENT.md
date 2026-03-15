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

### Stages

| # | Stage | Service | What it does |
|---|-------|---------|--------------|
| 1 | `classification` | `document_intelligence_service` | AI doc-type classification + field extraction |
| 2 | `entity_resolution` | `entity_resolution_service` | Match extracted names/IDs to DB entities (customers, vendors, POs) |
| 3 | `transaction_match` | `transaction_matching_service` | Link document to existing draft transactions |
| 4 | `bundle_detection` | `document_bundle_service` | Group related documents into packets |
| 5 | `lifecycle_check` | `document_lifecycle_service` | Validate document set completeness for an entity |
| 6 | `policy_decision` | `decision_policy_service` | Evaluate automation rules and decide action |
| 7 | `learning_capture` | `learning_loop_service` | Update aggregated automation metrics |

### API

```
POST /api/document-intelligence/pipeline/{doc_id}
     ?stop_after=entity_resolution        (optional: stop early)
     &skip_stages=bundle_detection        (optional: comma-separated)

GET  /api/document-intelligence/pipeline/stages
     -> { "stages": ["classification", ...] }
```

### Key design decisions

- **Wraps, does not rewrite.** Each stage delegates to an existing service function.
- **Non-fatal errors.** A stage failure is logged and recorded but does not abort the pipeline.
- **Structured output.** `PipelineResult` contains per-stage status, duration, and output keys.
- **Partial runs.** `stop_after` and `skip_stages` allow callers to run subsets.

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
| **Document Intelligence** | `document_intelligence_service`, `ai_classifier` | `document_intelligence` |
| **Entity Resolution** | `entity_resolution_service`, `unified_vendor_matcher` | `entity_resolutions`, `vendor_aliases`, `customer_aliases` |
| **Transaction Matching** | `transaction_matching_service` | `transaction_matches` |
| **Document Bundling** | `document_bundle_service` | `document_bundles` |
| **Lifecycle Validation** | `document_lifecycle_service` | `lifecycle_validations` |
| **Decision Policy** | `decision_policy_service`, `automation_helpers` | `automation_policies`, `automation_decisions`, `activities` |
| **Automation & Execution** | `automation_rules_service`, `auto_resolution_service`, `auto_clear_service`, `auto_post_service`, `workflow_engine` | `hub_documents` (status fields), `automation_rules` |
| **Learning Loop** | `learning_loop_service` | `learning_events`, `extraction_hints`, `learning_metrics` |
| **Reference Intelligence** | `reference_intelligence_service`, `bc_reference_resolver`, `bc_reference_cache_service`, `reference_helpers`, `bc_access` | `matching_diagnostics`, `bc_reference_cache` |
| **Vendor Intelligence** | `vendor_intelligence_service`, `stable_vendor_service`, `vendor_extraction_profile_service` | `vendor_intelligence_profiles`, `vendor_extraction_profiles` |
| **Inventory Ledger** | `inventory_ledger_service` | `inventory_movements`, `inv_item_settings` |
| **Business Central** | `business_central_service`, `bc_sandbox_service`, `bc_write_safety_guard` | (external API) |
| **Email Ingestion** | Graph API polling (in `server.py`) | `mail_intake_log`, `mail_poll_runs` |

---

## 6. Known Follow-Up Refactor Targets

| Target | Description | Priority |
|--------|-------------|----------|
| **`server.py` (~9400 lines)** | Still contains all legacy business-logic functions (upload, BC calls, email polling, etc.). Should be broken into focused service/utility modules over time. | P1 |
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
- **BC adapter:** `bc_reference_resolver` and `unified_vendor_matcher` token/company methods are wrappers around `bc_access.BCAccessAdapter`. The adapter shares a single token cache across both services.

---

*Last updated: March 15, 2026*
